"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain. Handles quiz commands and answers.
Supports callback queries (inline keyboard) AND text-based answers.

Now with JAMB Subject Checker — Wax proactively brings up university
ambition at natural moments after trust is built.

Now with Deferral Handler — when a student says "anything" or "you pick,"
Wax takes control. Doesn't ask again. Leads.
"""
import asyncio
import hashlib
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from telegram.sender import send_telegram_message, build_quiz_keyboard, answer_callback_query
from database.client import redis_client

logger = logging.getLogger("waxprep.handler")

# ── Quiz trigger keywords ────────────────────
QUIZ_TRIGGERS = ["quiz", "quiz me", "test me"]

# ── Deferral keywords ─────────────────────────
# When a student says any of these, Wax takes control.
# No more asking "what subject?" — the teacher leads.
DEFERRAL_KEYWORDS = [
    "anything", "you pick", "any one", "whatever",
    "up to you", "choose for me", "i don't know what to study",
    "i don't care", "surprise me",
]

# ── Subject name mapping (student profile display → database column) ──
SUBJECT_MAP: Dict[str, str] = {
    # Core
    "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics",
    "english": "english", "english_language": "english",
    # Science
    "physics": "physics", "chemistry": "chemistry", "biology": "biology",
    "further_mathematics": "further_mathematics", "further mathematics": "further_mathematics",
    "agricultural_science": "agricultural_science", "agric": "agricultural_science",
    # Commercial
    "economics": "economics", "commerce": "commerce",
    "accounting": "accounting", "accounts": "accounting",
    "business_studies": "business_studies", "business studies": "business_studies",
    "marketing": "marketing",
    # Arts
    "government": "government",
    "literature": "literature_in_english",
    "literature_in_english": "literature_in_english",
    "literature-in-english": "literature_in_english",
    "civic_education": "civic_education", "civic education": "civic_education",
    "christian_religious_studies": "crs", "crs": "crs",
    "islamic_religious_studies": "irs", "irs": "irs",
    "geography": "geography",
    "history": "history",
    # Nigerian languages
    "yoruba": "yoruba", "igbo": "igbo", "hausa": "hausa",
    # Other
    "food_and_nutrition": "food_and_nutrition", "food & nutrition": "food_and_nutrition",
    "technical_drawing": "technical_drawing", "technical drawing": "technical_drawing",
    "computer_studies": "computer_studies", "computer": "computer_studies", "ict": "computer_studies",
}

# ── Fallback subject pools by track ───────────
TRACK_FALLBACKS: Dict[str, List[str]] = {
    "science": ["english", "mathematics", "physics", "chemistry", "biology"],
    "commercial": ["english", "mathematics", "economics", "commerce", "accounting"],
    "arts": ["english", "mathematics", "government", "literature_in_english", "civic_education"],
    "unknown": ["english", "mathematics"],
}

# TTL for active quiz in Redis
QUIZ_TTL_SECONDS = 1800  # 30 minutes

# Maximum quiz history entries per student
MAX_QUIZ_HISTORY = 200

# JAMB check cooldown — 7 days between prompts
JAMB_CHECK_COOLDOWN = 604800  # 7 days in seconds

# Deferral count TTL — 1 hour (resets each session)
DEFERRAL_TTL = 3600


async def process_telegram_message(chat_id: int, text: str) -> None:
    """
    Entry point for all Telegram text messages.
    
    Processing order:
    1. Sanitize (length limit, strip)
    2. Admin commands (operator overrides)
    3. Safety checks (child protection — MUST precede AI)
    4. Student lookup (registered or new)
    5. Route to: onboarding OR registered student handler
    """
    # 1. Sanitize
    text = text.strip()[:4000]
    if not text:
        return

    logger.debug(f"Processing message from chat_id={chat_id}: {text[:100]}...")

    # 2. Admin commands
    try:
        from admin.commands import handle_admin_command
        if await handle_admin_command(chat_id, text):
            logger.info(f"Admin command handled for chat_id={chat_id}")
            return
    except ImportError as e:
        logger.error(f"Admin module import failed: {e}")
    except Exception as e:
        logger.error(f"Admin handler error for chat_id={chat_id}: {e}", exc_info=True)

    # 3. Safety checks
    try:
        from brain.safety import run_safety_checks
        if await run_safety_checks(chat_id, text):
            logger.warning(f"Safety check blocked message from chat_id={chat_id}")
            return
    except ImportError as e:
        logger.error(f"Safety module import failed: {e}")
    except Exception as e:
        logger.error(f"Safety check error for chat_id={chat_id}: {e}", exc_info=True)
        return

    # 4. Check if registered student
    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception as e:
        logger.error(f"Student lookup failed for chat_id={chat_id}: {e}", exc_info=True)
        await send_telegram_message(chat_id, "I'm having trouble connecting. Please try again in a moment.")
        return

    if student:
        await _handle_registered_student(chat_id, student, text)
        return

    # 5. Unregistered user — onboarding flow
    try:
        from telegram.onboarding import handle_onboarding
        from database.onboarding_state import get_onboarding_state
        state = await get_onboarding_state("telegram", str(chat_id))
    except Exception as e:
        logger.error(f"Onboarding state fetch failed for chat_id={chat_id}: {e}", exc_info=True)
        state = {}

    try:
        await handle_onboarding(chat_id, state, text)
    except Exception as e:
        logger.error(f"Onboarding handler failed for chat_id={chat_id}: {e}", exc_info=True)
        await send_telegram_message(chat_id, "Something went wrong. Type *HI* to start again.")


async def _handle_registered_student(chat_id: int, student: Dict[str, Any], text: str) -> None:
    """
    Route a registered student's message to the appropriate handler.
    
    Priority:
    0. JAMB ambition response (if Wax asked about university)
    0.5. Deferral keywords — "anything", "you pick" → Wax leads
    1. Quiz answer (single letter, active quiz exists)
    2. Quiz trigger (explicit quiz keywords)
    3. AI conversation (everything else)
    """
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]
    msg_lower = text.strip().lower()

    # 0. JAMB ambition response — student is replying to Wax's university question
    try:
        from database.onboarding_state import get_onboarding_state
        jamb_state = await get_onboarding_state("telegram", f"jamb_{student_id}")
        if jamb_state and jamb_state.get("awaiting_response_for") == "jamb_ambition":
            await _handle_jamb_ambition_response(chat_id, student, text, student_id, jamb_state)
            return
    except Exception:
        pass

    # 0.5. Deferral keywords — student says "anything" or "you pick"
    # Wax takes control. Doesn't ask again. Leads.
    if any(phrase in msg_lower for phrase in DEFERRAL_KEYWORDS):
        await _handle_deferral(chat_id, student, student_id, name, msg_lower)
        return

    # 1. Quiz answer detection
    cleaned = text.strip().upper()
    if cleaned in ("A", "B", "C", "D") and len(cleaned) == 1:
        quiz_key = f"active_quiz:{student_id}"
        try:
            if redis_client.exists(quiz_key):
                await _handle_quiz_answer(chat_id, student, cleaned)
                return
        except Exception as e:
            logger.error(f"Redis quiz check failed for {student_id}: {e}", exc_info=True)

    # 2. Quiz trigger
    if any(trigger in msg_lower for trigger in QUIZ_TRIGGERS):
        await _start_quiz(chat_id, student, text)
        return

    # 3. AI conversation
    await _handle_ai_conversation(chat_id, student, text, student_id, name)


# ═══════════════════════════════════════════════
# DEFERRAL HANDLER — "anything" / "you pick"
# ═══════════════════════════════════════════════

async def _handle_deferral(
    chat_id: int,
    student: dict,
    student_id: str,
    name: str,
    msg_lower: str
) -> None:
    """
    Handle when a student defers — "anything", "you pick", "whatever."
    
    Wax doesn't ask again. The teacher leads. The student's trouble subject
    from onboarding is used. Deferral count escalates firmness across
    three levels — warm, firm, direct.
    
    Args:
        chat_id: Telegram chat ID
        student: Student profile dict
        student_id: String student ID
        name: Student's first name
        msg_lower: Lowercase message for keyword matching
    """
    from database.conversations import save_message

    # Determine the trouble subject
    trouble_subject = student.get("student_subject")
    if not trouble_subject:
        # Fallback: try to infer from conversation or profile
        trouble_subject = _infer_recent_subject(student, [])
    if not trouble_subject or trouble_subject in ("unknown", "a subject", ""):
        # Last fallback: Mathematics — universal foundation
        trouble_subject = "Mathematics"

    # Track how many times this student has deferred
    deferral_key = f"deferral_count:{student_id}"
    deferral_count = 0
    try:
        raw = redis_client.get(deferral_key)
        if raw:
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            deferral_count = int(raw_str)
    except Exception:
        pass

    deferral_count += 1

    # Build response based on escalation level
    if deferral_count == 1:
        # First time — warm but firm. References their emotional check-in.
        response = (
            f"{trouble_subject}. You said it's been confusing you — "
            f"that's exactly where we start. Let's go."
        )
    elif deferral_count == 2:
        # Second time — firmer, uses their own words against hesitation
        response = (
            f"{name}, I already picked. {trouble_subject}. You told me "
            f"it's confusing and you're not alone in that. But running "
            f"from it won't help. Let's face it together. Ready?"
        )
    else:
        # Third+ time — direct, no explanation needed. The teacher stands firm.
        response = (
            f"{trouble_subject}, {name}. No more running. We're doing this. "
            f"Tell me what you already know about {trouble_subject}."
        )

    # Update deferral count with TTL
    try:
        redis_client.setex(deferral_key, DEFERRAL_TTL, str(deferral_count))
    except Exception:
        pass

    # Save and send — bypass AI entirely
    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass

    await send_telegram_message(chat_id, response)
    logger.info(f"Deferral handled for {student_id}: count={deferral_count}, subject={trouble_subject}")


# ═══════════════════════════════════════════════
# JAMB AMBITION HANDLER
# ═══════════════════════════════════════════════

async def _maybe_trigger_jamb_check(
    student_id: str,
    student: dict,
    chat_id: int,
    current_state: str
) -> bool:
    """
    Check if it's the right moment to bring up the JAMB subject conversation.
    
    Conditions:
    1. Student has completed at least 1 session (trust exists)
    2. Student hasn't been asked recently (7-day cooldown)
    3. Student is at a natural break (state is idle/chatting/ended/paused)
    4. Student hasn't already declared a university ambition
    
    Returns True if Wax sent the JAMB message, False otherwise.
    """
    from database.conversations import get_student_memory

    # Only at natural breaks — end of session, not mid-lesson
    if current_state not in ("idle", "chatting", "ended", "paused"):
        return False

    # Check cooldown
    cooldown_key = f"jamb_check_cooldown:{student_id}"
    try:
        if redis_client.get(cooldown_key):
            return False
    except Exception:
        pass

    # Get student memory
    try:
        memory = await get_student_memory(student_id)
    except Exception:
        memory = {}

    # Has student completed at least 1 session?
    sessions = memory.get("sessions_completed", 0)
    if sessions < 1:
        return False

    # Has student already declared an ambition?
    if student.get("university_ambition"):
        return False

    # All conditions met — bring it up
    name = student.get("name", "Student").split()[0]

    await send_telegram_message(
        chat_id,
        f"{name}, real quick before you go. I've been teaching you and you're "
        f"making progress — that persistence is paying off. But I want to make "
        f"sure I'm preparing you for the right thing.\n\n"
        f"Have you thought about what you want to study in university? "
        f"No pressure if you haven't figured it out yet. Just type your course "
        f"or say 'not sure' — whatever is true."
    )

    # Set cooldown — don't ask again for 7 days
    try:
        redis_client.setex(cooldown_key, JAMB_CHECK_COOLDOWN, "1")
    except Exception:
        pass

    # Save state so we know what the student is responding to
    try:
        from database.onboarding_state import save_onboarding_state
        await save_onboarding_state("telegram", f"jamb_{student_id}", {
            "awaiting_response_for": "jamb_ambition",
            "name": student.get("name", ""),
        })
    except Exception:
        pass

    return True


async def _handle_jamb_ambition_response(
    chat_id: int,
    student: dict,
    text: str,
    student_id: str,
    jamb_state: dict
) -> None:
    """
    Process the student's response to Wax's university ambition question.
    
    Three paths:
    1. Student knows their course → run JAMB check
    2. Student doesn't know → accept, promise to help later
    3. Student already told us → reference existing ambition
    """
    from content.jamb_checker import check_jamb_readiness, resolve_course
    from database.onboarding_state import clear_onboarding_state

    name = student.get("name", "Student").split()[0]
    msg = text.strip()

    # Clear the JAMB state — we're handling the response now
    try:
        await clear_onboarding_state("telegram", f"jamb_{student_id}")
    except Exception:
        pass

    # Path 2: Student doesn't know
    dont_know = ["not sure", "i don't know", "i dont know", "idk", "haven't thought", "not yet", "undecided"]
    if msg.lower() in dont_know or any(phrase in msg.lower() for phrase in dont_know):
        await send_telegram_message(
            chat_id,
            f"No wahala. Plenty of SS3 students are still figuring it out. "
            f"I was the same. Here's what I'll do — as we keep studying, I'll "
            f"pay attention to what you're naturally good at and what you enjoy. "
            f"After a few more sessions, I might have some suggestions for you. Sound good?"
        )
        # Save that student was asked but doesn't know yet
        try:
            from database.students import update_student
            await update_student(student_id, {"university_ambition_status": "undecided"})
        except Exception:
            pass
        return

    # Resolve the course
    course_key = resolve_course(msg)
    if not course_key:
        await send_telegram_message(
            chat_id,
            f"I don't have data for '{msg}' yet. Can you try a different "
            f"course name? Or tell me the official JAMB name — I'll look it up."
        )
        return

    # Run the check
    result = check_jamb_readiness(
        student_subjects=student.get("subjects", []),
        desired_course=msg
    )

    if result.get("error"):
        await send_telegram_message(
            chat_id,
            result.get("message", "I couldn't check that course. Can you try a different name?")
        )
        return

    # Path 1: Match found — celebrate!
    if result["ready"]:
        course_display = result["course_display"]
        have_list = "\n".join([f"✅ {s}" for s in result["have"]])
        
        await send_telegram_message(
            chat_id,
            f"{name}! Your subjects line up perfectly for {course_display}.\n\n"
            f"{have_list}\n\n"
            f"You're on track. Want me to put together a celebration card? "
            f"It's got your name and your achievement on it. Some students "
            f"send it to their friends. No pressure either way."
        )

        # Save the ambition
        try:
            from database.students import update_student
            await update_student(student_id, {
                "university_ambition": course_display,
                "university_ambition_status": "matched",
                "jamb_readiness_checked_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        return

    # Path 1b: Mismatch — be honest but offer alternatives
    missing_list = []
    for m in result["missing"]:
        if isinstance(m, dict):
            if m.get("alternatives"):
                alt_text = " or ".join(m["alternatives"])
                missing_list.append(f"❌ {m['preferred']} (or {alt_text})")
            else:
                missing_list.append(f"❌ {m['preferred']}")
        else:
            missing_list.append(f"❌ {m}")

    missing_text = "\n".join(missing_list)
    have_text = "\n".join([f"✅ {s}" for s in result["have"]])
    
    alternatives = result.get("alternatives", [])
    
    # Build the mismatch message
    message = (
        f"{name}, I need to be straight with you. {result['course_display']} "
        f"requires specific subjects — and you're missing some.\n\n"
        f"What you have:\n{have_text}\n\n"
        f"What's missing:\n{missing_text}"
    )

    if result.get("notes"):
        message += f"\n\n{result['notes']}"

    # Add the "not your fault" beat
    message += (
        f"\n\nAnd {name}? This doesn't mean you're not smart enough for "
        f"{result['course_display']}. It means nobody told you earlier what "
        f"you needed — and that's not your fault. What matters now is what "
        f"you do with this information."
    )

    # Add alternatives if available
    if alternatives:
        alt_names = [a["display"] for a in alternatives[:3]]
        alt_text = ", ".join(alt_names)
        message += (
            f"\n\nBut here's the thing — you're already on track for {alt_text} "
            f"with the subjects you have right now. Want to explore any of those? "
            f"Or do you want to figure out how to add the missing subjects before "
            f"JAMB registration?"
        )
    else:
        message += (
            f"\n\nWant to explore what courses DO match your subjects? "
            f"Or do you want to figure out how to add the missing subjects?"
        )

    await send_telegram_message(chat_id, message)

    # Save the result
    try:
        from database.students import update_student
        await update_student(student_id, {
            "university_ambition": result["course_display"],
            "university_ambition_status": "mismatched",
            "jamb_readiness_checked_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass


# ═══════════════════════════════════════════════
# AI CONVERSATION HANDLER
# ═══════════════════════════════════════════════

async def _handle_ai_conversation(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    student_id: str,
    name: str
) -> None:
    """
    Process a student message through the AI brain, with memory context.
    Triggers JAMB checker at natural moments.
    """
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message

    # Save user message
    try:
        await save_message(student_id, "user", text)
    except Exception as e:
        logger.error(f"Failed to save user message for {student_id}: {e}", exc_info=True)

    # Load conversation history
    try:
        conversation_history = await get_history(student_id)
    except Exception as e:
        logger.error(f"Failed to load history for {student_id}: {e}", exc_info=True)
        conversation_history = []

    # Load current state
    try:
        current_state = await get_state(student_id)
        if not current_state:
            current_state = "idle"
    except Exception as e:
        logger.error(f"Failed to load state for {student_id}: {e}", exc_info=True)
        current_state = "idle"

    # Determine recent subject
    recent_subject = _infer_recent_subject(student, conversation_history)

    # Build memory context
    try:
        context_str = await _build_memory_context(student_id)
    except Exception as e:
        logger.error(f"Memory context build failed for {student_id}: {e}", exc_info=True)
        context_str = ""

    # Determine practice mode
    is_practice = current_state in ("in_practice", "chatting", "idle", "paused")

    # Call AI brain
    try:
        response = await think(
            message=text,
            student=student,
            conversation_history=conversation_history,
            recent_subject=recent_subject,
            context_str=context_str,
            is_practice=is_practice
        )
    except Exception as e:
        logger.error(f"AI brain error for {student_id}: {e}", exc_info=True)
        response = f"Ah, my brain just froze for a second, {name}. Can you try again?"

    # Output safety check
    try:
        from brain.safety import check_output_safety
        if await check_output_safety(response):
            logger.warning(f"Output safety block for {student_id}")
            response = f"Let me try that differently, {name}. What subject are you studying right now?"
    except ImportError:
        logger.warning("Output safety module not available")
    except Exception as e:
        logger.error(f"Output safety check failed: {e}", exc_info=True)

    # Save assistant response
    try:
        await save_message(student_id, "assistant", response)
    except Exception as e:
        logger.error(f"Failed to save assistant message for {student_id}: {e}", exc_info=True)

    # Send response
    try:
        await send_telegram_message(chat_id, response)
    except Exception as e:
        logger.error(f"Failed to send message to chat_id={chat_id}: {e}", exc_info=True)

    # Save session snapshot
    try:
        from database.conversations import save_session_summary

        user_msg_count = sum(
            1 for m in conversation_history[-10:]
            if m.get("role") == "user"
        )

        if user_msg_count >= 2:
            session_subject = recent_subject or "unknown"
            session_topic = "discussed"

            if response:
                topic_keywords = [
                    "Today:", "today:", "Let's learn about",
                    "let's learn about", "we'll cover", "focusing on",
                    "Let's focus on", "let's focus on",
                    "Let's dive into", "let's dive into"
                ]
                for keyword in topic_keywords:
                    if keyword in response:
                        parts = response.split(keyword, 1)
                        if len(parts) > 1:
                            extracted = parts[1].strip().split(".")[0].strip()[:50]
                            if extracted:
                                session_topic = extracted
                                break

            await save_session_summary(student_id, {
                "subject": session_subject,
                "topic": session_topic,
                "completed": False,
                "score": None,
                "struggled_with": [],
                "ended_at": None
            })
            logger.debug(
                f"Session snapshot saved for {student_id}: "
                f"{session_subject} - {session_topic}"
            )
    except Exception as e:
        logger.error(f"Failed to save session snapshot: {e}")

    # Update state
    try:
        if current_state == "idle":
            await set_state(student_id, "chatting", reason="First message")
        elif current_state == "paused":
            await set_state(student_id, "chatting", reason="Returned from pause")
    except Exception as e:
        logger.error(f"State update failed for {student_id}: {e}", exc_info=True)

    # ── JAMB Check: bring up university ambition at natural moment ──
    await _maybe_trigger_jamb_check(student_id, student, chat_id, current_state)


# ═══════════════════════════════════════════════
# SUBJECT INFERENCE
# ═══════════════════════════════════════════════

def _infer_recent_subject(student: Dict[str, Any], conversation_history: List[Dict]) -> Optional[str]:
    """Infer what subject the student is currently discussing."""
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                subject_display = subject.replace("_", " ")
                if subject_display.lower() in content.lower():
                    return subject

    trouble_subject = student.get("student_subject")
    if trouble_subject:
        return trouble_subject

    subjects = student.get("subjects", [])
    if subjects and subjects[0]:
        return subjects[0]

    return None


# ═══════════════════════════════════════════════
# MEMORY CONTEXT BUILDER
# ═══════════════════════════════════════════════

async def _build_memory_context(student_id: str) -> str:
    """Build memory context for the AI prompt."""
    from database.conversations import get_session_summary, get_student_memory

    context_parts: List[str] = []

    try:
        last_session = await get_session_summary(student_id)
    except Exception as e:
        logger.error(f"Failed to load session summary for {student_id}: {e}")
        last_session = None

    if last_session:
        subject = last_session.get("subject", "a subject")
        topic = last_session.get("topic", "a topic")
        completed = last_session.get("completed", False)
        score = last_session.get("score")
        struggled = last_session.get("struggled_with", [])

        has_content = (
            subject not in ("unknown", "a subject", "") and
            topic not in ("unknown", "a topic", "")
        )
        
        if has_content:
            session_line = f"LAST SESSION: {subject} - {topic}."
            if completed:
                session_line += " Completed."
                if score is not None:
                    session_line += f" Score: {int(score * 100)}%."
            else:
                session_line += " Not completed."

            if struggled:
                session_line += f" Struggled with: {', '.join(struggled)}."

            context_parts.append(session_line)

    try:
        memory = await get_student_memory(student_id)
    except Exception as e:
        logger.error(f"Failed to load student memory for {student_id}: {e}")
        memory = None

    if memory:
        struggles = memory.get("struggles_with", [])
        strengths = memory.get("strong_in", [])
        mastered = memory.get("topics_mastered", [])
        sessions_count = memory.get("sessions_completed", 0)
        pace = memory.get("preferred_pace")

        if struggles:
            context_parts.append(f"STUDENT STRUGGLES WITH: {', '.join(struggles[-5:])}.")
        if strengths:
            context_parts.append(f"STUDENT IS STRONG IN: {', '.join(strengths[-5:])}.")
        if mastered:
            context_parts.append(f"TOPICS MASTERED: {', '.join(mastered[-5:])}.")
        if sessions_count > 0:
            context_parts.append(f"Sessions completed: {sessions_count}.")
        if pace:
            context_parts.append(f"Preferred pace: {pace}.")

    if context_parts:
        return "MEMORY CONTEXT:\n" + "\n".join(context_parts)

    return ""


# ═══════════════════════════════════════════════
# QUIZ ENGINE
# ═══════════════════════════════════════════════

_QUIZ_TRACKER: Dict[str, List[str]] = {}


async def _load_questions(subject: str) -> List[Dict[str, Any]]:
    """Load quiz questions for a subject with layered fallback."""
    cache_key = f"questions_cache:{subject}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            logger.debug(f"Cache hit for questions:{subject}")
            return json.loads(cached_str)
    except Exception:
        pass

    questions: List[Dict[str, Any]] = []

    try:
        from database.client import supabase
        result = (
            supabase.table("questions")
            .select("*")
            .eq("subject", subject)
            .order("id", desc=False)
            .limit(200)
            .execute()
        )
        if result.data:
            questions = result.data
            logger.info(f"Loaded {len(questions)} questions from database for {subject}")
    except Exception as e:
        logger.warning(f"Database question load failed for {subject}: {e}")

    if not questions:
        try:
            json_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "jamb_questions_clean.json"
            )
            json_path = os.path.abspath(json_path)
            logger.info(f"Loading questions from JSON: {json_path}")
            with open(json_path, "r", encoding="utf-8") as f:
                all_questions = json.load(f)
            questions = [q for q in all_questions if q.get("subject") == subject]
            logger.info(f"Loaded {len(questions)} questions from JSON for {subject}")
        except FileNotFoundError:
            logger.error(f"Question JSON file not found: {json_path}")
        except Exception as e:
            logger.error(f"JSON question load failed for {subject}: {e}")

    if questions:
        try:
            redis_client.setex(cache_key, 300, json.dumps(questions))
        except Exception:
            pass

    return questions


async def _start_quiz(chat_id: int, student: Dict[str, Any], message_text: str = "") -> None:
    """Start a quiz session for the student."""
    student_id = str(student["id"])
    student_subjects = student.get("subjects", [])
    student_track = _infer_track(student_subjects)

    if not student_subjects:
        fallback = TRACK_FALLBACKS.get(student_track, TRACK_FALLBACKS["unknown"])
        subjects_pool = fallback.copy()
        logger.warning(
            f"Student {student_id} ({student_track} track) has no subjects set. "
            f"Using fallback: {subjects_pool}"
        )
        if student_track == "unknown":
            await send_telegram_message(
                chat_id,
                "Your subject preferences aren't set yet. "
                "I'll ask some general questions for now. "
                "Reply with your subject (e.g. *Government*, *Physics*) to get specific quizzes."
            )
    else:
        subjects_pool = student_subjects.copy()

    requested_subject = None
    if message_text:
        msg_lower = message_text.lower()
        for subj in subjects_pool:
            subj_display = subj.lower().replace("_", " ")
            if subj_display in msg_lower:
                requested_subject = subj
                logger.info(f"Quiz subject from student pool: {subj}")
                break
        
        if not requested_subject:
            for map_key in SUBJECT_MAP:
                display = map_key.replace("_", " ")
                if display in msg_lower and display not in ("quiz", "me", "test"):
                    requested_subject = map_key
                    logger.info(f"Quiz subject from SUBJECT_MAP: {map_key}")
                    break

    if requested_subject:
        subject = requested_subject
    else:
        subject = _pick_rotated_subject(student_id, subjects_pool)
    
    db_subject = SUBJECT_MAP.get(subject.lower().replace(" ", "_"), subject.lower())
    logger.info(f"Quiz subject for {student_id}: {db_subject} (from {'message' if requested_subject else 'rotation'})")

    questions = await _load_questions(db_subject)

    if not questions:
        await send_telegram_message(
            chat_id,
            f"No questions found for *{db_subject.replace('_', ' ').title()}* yet. "
            f"Try another subject — type *quiz {subjects_pool[0] if subjects_pool else 'maths'}* if you like."
        )
        return

    question = random.choice(questions)
    logger.debug(
        f"Selected question for {student_id}: "
        f"{question.get('question_text', question.get('question', ''))[:80]}..."
    )

    if not _validate_question(question):
        logger.error(f"Invalid question data for {db_subject}: {question.get('id', 'unknown')}")
        await send_telegram_message(chat_id, "This question has invalid options. Let me try another. Type *quiz*.")
        return

    quiz_key = f"active_quiz:{student_id}"
    try:
        redis_client.setex(
            quiz_key,
            QUIZ_TTL_SECONDS,
            json.dumps({
                "question": question,
                "subject": db_subject,
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
        )
    except Exception as e:
        logger.error(f"Failed to save quiz state for {student_id}: {e}", exc_info=True)
        await send_telegram_message(chat_id, "Quiz setup failed. Type *quiz* to try again.")
        return

    keyboard = build_quiz_keyboard(question)
    if not keyboard:
        await send_telegram_message(chat_id, "This question is missing options. Type *quiz* for another.")
        return

    display_subject = db_subject.replace("_", " ").title()
    question_body = question.get("question_text", question.get("question", "Question loading..."))

    question_text = (
        f"📝 *{display_subject}*\n\n"
        f"{question_body}\n\n"
        f"_Tap your answer below:_"
    )

    try:
        await send_telegram_message(chat_id, question_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Failed to send quiz message to chat_id={chat_id}: {e}", exc_info=True)
        try:
            redis_client.delete(quiz_key)
        except Exception:
            pass


async def handle_quiz_callback(chat_id: int, callback_query_id: str, callback_data: str) -> None:
    """Handle inline keyboard callback queries from quiz buttons."""
    logger.info(f"Quiz callback: chat_id={chat_id}, data={callback_data}")

    try:
        await answer_callback_query(callback_query_id, text="")
    except Exception as e:
        logger.error(f"Callback acknowledgment failed: {e}")

    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception as e:
        logger.error(f"Student lookup failed in callback for chat_id={chat_id}: {e}")
        return

    if not student:
        await send_telegram_message(chat_id, "I can't find your account. Type *HI* to restart.")
        return

    if callback_data in ("A", "B", "C", "D"):
        await _handle_quiz_answer(chat_id, student, callback_data)
    else:
        logger.warning(f"Unknown callback data: {callback_data}")


async def _handle_quiz_answer(chat_id: int, student: Dict[str, Any], answer: str) -> None:
    """Evaluate a quiz answer and provide feedback."""
    student_id = str(student["id"])
    quiz_key = f"active_quiz:{student_id}"
    name = student.get("name", "Student").split()[0]

    try:
        raw = redis_client.get(quiz_key)
        if not raw:
            await send_telegram_message(chat_id, "No active quiz. Reply with *quiz* to start one!")
            return
        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        quiz_data = json.loads(raw_str)
    except json.JSONDecodeError:
        logger.error(f"Corrupted quiz data for {student_id}")
        redis_client.delete(quiz_key)
        await send_telegram_message(chat_id, "Quiz data was corrupted. Let's start fresh — type *quiz*.")
        return
    except Exception as e:
        logger.error(f"Failed to load quiz for {student_id}: {e}", exc_info=True)
        await send_telegram_message(chat_id, "I lost track of the quiz. Type *quiz* to start a new one.")
        return

    try:
        redis_client.delete(quiz_key)
    except Exception:
        pass

    question = quiz_data["question"]
    correct = question.get("correct_answer", "A").strip().upper()
    is_correct = (answer == correct)

    explanation = question.get("explanation_correct") or question.get("explanation") or ""
    wrong_explanation = question.get(f"explanation_{answer.lower()}") or ""

    if is_correct:
        response = f"✅ *Correct!*\n\n"
        if explanation:
            response += f"{explanation}\n\n"
        response += f"Well done, {name}!"
    else:
        response = (
            f"❌ That's not quite right.\n\n"
            f"The correct answer is *{correct}*."
        )
        if explanation:
            response += f"\n\n{explanation}"
        if wrong_explanation:
            response += f"\n\n💡 *Why {answer} wasn't right:* {wrong_explanation}"

    opt_key = f"option_{answer.lower()}"
    correct_key = f"option_{correct.lower()}"
    opt_text = question.get(opt_key, "")
    correct_text = question.get(correct_key, "")
    if opt_text and correct_text and answer != correct:
        response += f"\n\nYour answer: *{answer}*) {opt_text}\nCorrect answer: *{correct}*) {correct_text}"

    _log_quiz_answer(student_id, question, is_correct)
    response += "\n\nType *quiz* for another question!"

    try:
        await send_telegram_message(chat_id, response)
    except Exception as e:
        logger.error(f"Failed to send quiz feedback to chat_id={chat_id}: {e}")


def _log_quiz_answer(student_id: str, question: Dict[str, Any], is_correct: bool) -> None:
    """Log quiz answer to Redis for progress tracking."""
    try:
        key = f"quiz_history:{student_id}"
        entry = json.dumps({
            "subject": question.get("subject", "unknown"),
            "question_id": question.get("id", "unknown"),
            "correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        pipe = redis_client.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -MAX_QUIZ_HISTORY, -1)
        pipe.expire(key, 86400 * 30)
        pipe.execute()

        logger.debug(f"Quiz logged for {student_id}: correct={is_correct}")
    except Exception as e:
        logger.error(f"Quiz log error for {student_id}: {e}")


def _validate_question(question: Dict[str, Any]) -> bool:
    """Validate that a question dict has the required fields for a quiz."""
    if not question.get("question_text") and not question.get("question"):
        return False
    if not question.get("correct_answer"):
        return False
    correct = question["correct_answer"].strip().upper()
    if not question.get(f"option_{correct.lower()}"):
        return False
    return True


def _infer_track(subjects: List[str]) -> str:
    """Infer the student's academic track from their subject list."""
    if not subjects:
        return "unknown"

    subject_set = {s.lower().replace(" ", "_") for s in subjects}

    science_indicators = {"physics", "chemistry", "biology", "further_mathematics", "agricultural_science"}
    if subject_set & science_indicators:
        return "science"

    commercial_indicators = {"accounting", "commerce", "business_studies", "marketing"}
    if subject_set & commercial_indicators:
        return "commercial"

    arts_indicators = {"literature_in_english", "government", "civic_education", "crs", "irs"}
    if subject_set & arts_indicators:
        return "arts"

    if "economics" in subject_set and "government" in subject_set:
        return "arts"
    if "economics" in subject_set:
        return "commercial"

    return "unknown"


def _pick_rotated_subject(student_id: str, subjects: List[str]) -> str:
    """Pick a subject using fair rotation."""
    if not subjects:
        return "mathematics"

    recent = _QUIZ_TRACKER.get(student_id, [])
    available = [s for s in subjects if s not in recent]
    if not available:
        available = subjects
        _QUIZ_TRACKER[student_id] = []

    chosen = random.choice(available)
    _QUIZ_TRACKER.setdefault(student_id, []).append(chosen)
    if len(_QUIZ_TRACKER[student_id]) > 3:
        _QUIZ_TRACKER[student_id] = _QUIZ_TRACKER[student_id][-3:]

    return chosen


async def warmup_question_cache() -> None:
    """Preload common subjects into Redis cache."""
    common_subjects = ["mathematics", "english", "physics", "chemistry", "biology", "government", "economics"]
    for subject in common_subjects:
        try:
            await _load_questions(subject)
            logger.info(f"Warmed up question cache for {subject}")
        except Exception as e:
            logger.warning(f"Failed to warmup {subject}: {e}")
