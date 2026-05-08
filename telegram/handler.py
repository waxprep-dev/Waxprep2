"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain. Handles quiz commands and answers.
Supports callback queries (inline keyboard) AND text-based answers.

Now with JAMB Subject Checker — Wax proactively brings up university
ambition at natural moments after trust is built.

Now with Deferral Handler — when a student says "anything" or "you pick,"
Wax takes control. Doesn't ask again. Leads.

Now with Session End Detection — natural endings like "I'm tired" or
"I'm done" trigger formal session closure, saving memory for next time.

Now with Confusion Detection — when a student is confused, Wax stops
introducing new information, switches examples, and doesn't move forward
until the student confirms understanding.

Now with Student Model — Wax learns HOW each student learns. Teaching style,
example domains, communication style, and competence map adapt over time.
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
DEFERRAL_KEYWORDS = [
    "anything", "you pick", "any one", "whatever",
    "up to you", "choose for me", "i don't know what to study",
    "i don't care", "surprise me",
]

# ── Session end keywords ─────────────────────
SESSION_END_KEYWORDS = [
    "i'm tired", "i am tired", "i'm done", "i am done",
    "good night", "goodnight", "i need a break", "taking a break",
    "i'll be back", "i will be back", "bye", "goodbye",
    "see you later", "see you tomorrow", "i'm going to sleep",
    "i'm leaving", "i have to go", "gotta go", "gtg",
]

# ── Subject name mapping ──────────────────────
SUBJECT_MAP: Dict[str, str] = {
    "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics",
    "english": "english", "english_language": "english",
    "physics": "physics", "chemistry": "chemistry", "biology": "biology",
    "further_mathematics": "further_mathematics", "further mathematics": "further_mathematics",
    "agricultural_science": "agricultural_science", "agric": "agricultural_science",
    "economics": "economics", "commerce": "commerce",
    "accounting": "accounting", "accounts": "accounting",
    "business_studies": "business_studies", "business studies": "business_studies",
    "marketing": "marketing",
    "government": "government",
    "literature": "literature_in_english",
    "literature_in_english": "literature_in_english",
    "literature-in-english": "literature_in_english",
    "civic_education": "civic_education", "civic education": "civic_education",
    "christian_religious_studies": "crs", "crs": "crs",
    "islamic_religious_studies": "irs", "irs": "irs",
    "geography": "geography", "history": "history",
    "yoruba": "yoruba", "igbo": "igbo", "hausa": "hausa",
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

# TTLs and limits
QUIZ_TTL_SECONDS = 1800
MAX_QUIZ_HISTORY = 200
JAMB_CHECK_COOLDOWN = 604800
DEFERRAL_TTL = 3600

# Understanding confirmation phrases
UNDERSTANDING_PHRASES = [
    "you've got it", "exactly", "you worked that out",
    "you're right", "well done", "correct", "perfect",
    "that's it", "you got it", "you understand",
    "now you're getting it", "you're on a roll",
]


async def process_telegram_message(chat_id: int, text: str) -> None:
    """Entry point for all Telegram text messages."""
    text = text.strip()[:4000]
    if not text:
        return

    logger.debug(f"Processing message from chat_id={chat_id}: {text[:100]}...")

    try:
        from admin.commands import handle_admin_command
        if await handle_admin_command(chat_id, text):
            logger.info(f"Admin command handled for chat_id={chat_id}")
            return
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Admin handler error: {e}", exc_info=True)

    try:
        from brain.safety import run_safety_checks
        if await run_safety_checks(chat_id, text):
            return
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Safety check error: {e}", exc_info=True)
        return

    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception as e:
        logger.error(f"Student lookup failed: {e}", exc_info=True)
        await send_telegram_message(chat_id, "I'm having trouble connecting. Please try again in a moment.")
        return

    if student:
        await _handle_registered_student(chat_id, student, text)
        return

    try:
        from telegram.onboarding import handle_onboarding
        from database.onboarding_state import get_onboarding_state
        state = await get_onboarding_state("telegram", str(chat_id))
    except Exception:
        state = {}

    try:
        await handle_onboarding(chat_id, state, text)
    except Exception as e:
        logger.error(f"Onboarding handler failed: {e}", exc_info=True)
        await send_telegram_message(chat_id, "Something went wrong. Type *HI* to start again.")


async def _handle_registered_student(chat_id: int, student: Dict[str, Any], text: str) -> None:
    """Route a registered student's message to the appropriate handler."""
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]
    msg_lower = text.strip().lower()

    try:
        from database.onboarding_state import get_onboarding_state
        jamb_state = await get_onboarding_state("telegram", f"jamb_{student_id}")
        if jamb_state and jamb_state.get("awaiting_response_for") == "jamb_ambition":
            await _handle_jamb_ambition_response(chat_id, student, text, student_id, jamb_state)
            return
    except Exception:
        pass

    if any(phrase in msg_lower for phrase in SESSION_END_KEYWORDS):
        await _handle_session_end(chat_id, student, text, student_id, name, msg_lower)
        return

    if any(phrase in msg_lower for phrase in DEFERRAL_KEYWORDS):
        await _handle_deferral(chat_id, student, student_id, name, msg_lower)
        return

    cleaned = text.strip().upper()
    if cleaned in ("A", "B", "C", "D") and len(cleaned) == 1:
        quiz_key = f"active_quiz:{student_id}"
        try:
            if redis_client.exists(quiz_key):
                await _handle_quiz_answer(chat_id, student, cleaned)
                return
        except Exception:
            pass

    if any(trigger in msg_lower for trigger in QUIZ_TRIGGERS):
        await _start_quiz(chat_id, student, text)
        return

    await _handle_ai_conversation(chat_id, student, text, student_id, name)


# ═══════════════════════════════════════════════
# SESSION END HANDLER
# ═══════════════════════════════════════════════

async def _handle_session_end(
    chat_id: int, student: dict, text: str,
    student_id: str, name: str, msg_lower: str
) -> None:
    """Handle natural session endings."""
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message, save_session_summary

    try:
        conversation_history = await get_history(student_id)
    except Exception:
        conversation_history = []

    recent_subject = _infer_recent_subject(student, conversation_history)
    session_topic = _extract_topic_from_history(conversation_history)

    try:
        await save_message(student_id, "user", text)
    except Exception:
        pass

    try:
        context_str = await _build_memory_context(student_id)
    except Exception:
        context_str = ""

    try:
        response = await think(
            message=text, student=student,
            conversation_history=conversation_history,
            recent_subject=recent_subject, context_str=context_str,
            is_practice=False
        )
    except Exception:
        response = f"No wahala, {name}. Take a break. We'll continue {recent_subject or 'studying'} when you're ready."

    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass

    await send_telegram_message(chat_id, response)

    try:
        await set_state(student_id, "ended",
            reason=f"Student ended session: {msg_lower[:50]}",
            session_context={
                "subject": recent_subject or "unknown",
                "topic": session_topic or "discussed",
                "completed": False, "score": None, "struggled_with": [],
            })
    except Exception:
        pass

    try:
        await save_session_summary(student_id, {
            "subject": recent_subject or "unknown",
            "topic": session_topic or "discussed",
            "completed": False, "score": None, "struggled_with": [],
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass


def _extract_topic_from_history(conversation_history: List[Dict]) -> str:
    """Extract the current topic from recent conversation history."""
    topic_keywords = [
        "Today:", "today:", "Let's learn about", "let's learn about",
        "we'll cover", "focusing on", "Let's focus on", "let's focus on",
        "Let's dive into", "let's dive into",
        "you were doing well with", "You were doing well with",
        "we covered", "We covered", "we looked at", "We looked at",
        "we discussed", "We discussed",
        "don't forget that", "Don't forget that",
        "you worked that out", "You worked that out",
        "you're getting", "You're getting", "you understood", "You understood",
    ]
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for keyword in topic_keywords:
                if keyword in content:
                    parts = content.split(keyword, 1)
                    if len(parts) > 1:
                        extracted = parts[1].strip().split(".")[0].strip()[:50]
                        if extracted and len(extracted) > 2:
                            return extracted
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                subject_display = subject.replace("_", " ")
                if subject_display.lower() in content.lower():
                    return subject_display
    return "discussed"


# ═══════════════════════════════════════════════
# DEFERRAL HANDLER
# ═══════════════════════════════════════════════

async def _handle_deferral(
    chat_id: int, student: dict, student_id: str, name: str, msg_lower: str
) -> None:
    """Handle when a student defers."""
    from database.conversations import save_message

    trouble_subject = student.get("student_subject")
    if not trouble_subject:
        trouble_subject = _infer_recent_subject(student, [])
    if not trouble_subject or trouble_subject in ("unknown", "a subject", ""):
        trouble_subject = "Mathematics"

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

    if deferral_count == 1:
        response = f"{trouble_subject}. You said it's been confusing you — that's exactly where we start. Let's go."
    elif deferral_count == 2:
        response = f"{name}, I already picked. {trouble_subject}. You told me it's confusing and you're not alone in that. But running from it won't help. Let's face it together. Ready?"
    else:
        response = f"{trouble_subject}, {name}. No more running. We're doing this. Tell me what you already know about {trouble_subject}."

    try:
        redis_client.setex(deferral_key, DEFERRAL_TTL, str(deferral_count))
    except Exception:
        pass
    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass

    await send_telegram_message(chat_id, response)


# ═══════════════════════════════════════════════
# JAMB AMBITION HANDLER
# ═══════════════════════════════════════════════

async def _maybe_trigger_jamb_check(
    student_id: str, student: dict, chat_id: int, current_state: str
) -> bool:
    """Check if it's the right moment for JAMB conversation."""
    from database.conversations import get_student_memory

    if current_state not in ("idle", "chatting", "ended", "paused"):
        return False
    cooldown_key = f"jamb_check_cooldown:{student_id}"
    try:
        if redis_client.get(cooldown_key):
            return False
    except Exception:
        pass
    try:
        memory = await get_student_memory(student_id)
    except Exception:
        memory = {}
    if memory.get("sessions_completed", 0) < 1:
        return False
    if student.get("university_ambition"):
        return False

    name = student.get("name", "Student").split()[0]
    await send_telegram_message(chat_id,
        f"{name}, real quick before you go. I've been teaching you and you're "
        f"making progress — that persistence is paying off. But I want to make "
        f"sure I'm preparing you for the right thing.\n\n"
        f"Have you thought about what you want to study in university? "
        f"No pressure if you haven't figured it out yet. Just type your course "
        f"or say 'not sure' — whatever is true."
    )
    try:
        redis_client.setex(cooldown_key, JAMB_CHECK_COOLDOWN, "1")
    except Exception:
        pass
    return True


async def _handle_jamb_ambition_response(
    chat_id: int, student: dict, text: str, student_id: str, jamb_state: dict
) -> None:
    """Process student's response to university ambition question."""
    from content.jamb_checker import check_jamb_readiness, resolve_course
    from database.onboarding_state import clear_onboarding_state

    name = student.get("name", "Student").split()[0]
    msg = text.strip()

    try:
        await clear_onboarding_state("telegram", f"jamb_{student_id}")
    except Exception:
        pass

    dont_know = ["not sure", "i don't know", "i dont know", "idk", "haven't thought", "not yet", "undecided"]
    if msg.lower() in dont_know or any(phrase in msg.lower() for phrase in dont_know):
        await send_telegram_message(chat_id,
            f"No wahala. Plenty of SS3 students are still figuring it out. "
            f"I was the same. Here's what I'll do — as we keep studying, I'll "
            f"pay attention to what you're naturally good at and what you enjoy. "
            f"After a few more sessions, I might have some suggestions for you. Sound good?"
        )
        return

    course_key = resolve_course(msg)
    if not course_key:
        await send_telegram_message(chat_id,
            f"I don't have data for '{msg}' yet. Can you try a different course name?"
        )
        return

    result = check_jamb_readiness(
        student_subjects=student.get("subjects", []),
        desired_course=msg
    )

    if result.get("error"):
        await send_telegram_message(chat_id, result.get("message", "I couldn't check that course."))
        return

    if result["ready"]:
        have_list = "\n".join([f"✅ {s}" for s in result["have"]])
        await send_telegram_message(chat_id,
            f"{name}! Your subjects line up perfectly for {result['course_display']}.\n\n"
            f"{have_list}\n\nYou're on track."
        )
        return

    missing_list = []
    for m in result["missing"]:
        if isinstance(m, dict):
            alt_text = " or ".join(m.get("alternatives", []))
            missing_list.append(f"❌ {m['preferred']}" + (f" (or {alt_text})" if alt_text else ""))
        else:
            missing_list.append(f"❌ {m}")

    alternatives = result.get("alternatives", [])
    message = (
        f"{name}, I need to be straight with you. {result['course_display']} "
        f"requires specific subjects — and you're missing some.\n\n"
        f"What you have:\n" + "\n".join([f"✅ {s}" for s in result["have"]]) + "\n\n"
        f"What's missing:\n" + "\n".join(missing_list)
    )
    message += (
        f"\n\nAnd {name}? This doesn't mean you're not smart enough. "
        f"It means nobody told you earlier what you needed — and that's not your fault."
    )
    if alternatives:
        alt_names = [a["display"] for a in alternatives[:3]]
        message += f"\n\nBut you're already on track for {', '.join(alt_names)} with the subjects you have right now."
    await send_telegram_message(chat_id, message)


# ═══════════════════════════════════════════════
# AI CONVERSATION HANDLER — WITH STUDENT MODEL
# ═══════════════════════════════════════════════

async def _handle_ai_conversation(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    student_id: str,
    name: str
) -> None:
    """Process a student message through the AI brain."""
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message

    # ── Import detectors and model (function-level to prevent circular imports) ──
    try:
        from brain.detectors import detect_confusion, reset_confusion_count
        _confusion_detector_available = True
    except ImportError:
        _confusion_detector_available = False

    try:
        from brain.student_model import load_student_model, save_student_model
        _student_model_available = True
    except ImportError:
        _student_model_available = False

    # ── Save user message ──
    try:
        await save_message(student_id, "user", text)
    except Exception:
        pass

    # ── Load conversation history ──
    try:
        conversation_history = await get_history(student_id)
    except Exception:
        conversation_history = []

    # ── Load current state ──
    try:
        current_state = await get_state(student_id)
        if not current_state:
            current_state = "idle"
    except Exception:
        current_state = "idle"

    # ── Determine recent subject ──
    recent_subject = _infer_recent_subject(student, conversation_history)
    current_topic = recent_subject or "unknown"

    # ── Build memory context ──
    try:
        context_str = await _build_memory_context(student_id)
    except Exception:
        context_str = ""

    # ── Load Student Model ──
    # FIXED: _pending_model_update defined OUTSIDE try block for post-response access
    _pending_model_update = None

    if _student_model_available:
        try:
            student_model = await load_student_model(student_id)
            model_context = student_model.to_prompt_context()

            if model_context:
                if context_str:
                    context_str = model_context + "\n\n" + context_str
                else:
                    context_str = model_context

            _pending_model_update = student_model
        except Exception as e:
            logger.error(f"Student model load failed: {e}", exc_info=True)

    # ── Confusion Detection ──
    # FIXED: _pending_confusion_reset defined OUTSIDE try block
    _pending_confusion_reset = False

    if _confusion_detector_available:
        try:
            same_topic_wrong = 0
            for msg in conversation_history[-6:]:
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if any(phrase in content.lower() for phrase in [
                        "not quite", "not exactly", "close", "almost",
                        "that's not", "incorrect", "not right",
                    ]):
                        same_topic_wrong += 1

            confusion = await detect_confusion(
                message=text, student_id=student_id,
                topic=current_topic, same_topic_wrong_count=same_topic_wrong,
            )

            if confusion["confused"]:
                if context_str:
                    context_str = confusion["context_instruction"] + "\n\n" + context_str
                else:
                    context_str = confusion["context_instruction"]
                _pending_confusion_reset = True
        except Exception as e:
            logger.error(f"Confusion detection failed: {e}", exc_info=True)

    # ── Determine practice mode ──
    is_practice = current_state in ("in_practice", "chatting", "idle", "paused")

    # ── Call AI brain ──
    try:
        response = await think(
            message=text, student=student,
            conversation_history=conversation_history,
            recent_subject=recent_subject, context_str=context_str,
            is_practice=is_practice
        )
    except Exception as e:
        logger.error(f"AI brain error: {e}", exc_info=True)
        response = f"Ah, my brain just froze for a second, {name}. Can you try again?"

    # ── Output safety check ──
    try:
        from brain.safety import check_output_safety
        if await check_output_safety(response):
            response = f"Let me try that differently, {name}. What subject are you studying right now?"
    except ImportError:
        pass
    except Exception:
        pass

    # ── Save and send response ──
    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass
    try:
        await send_telegram_message(chat_id, response)
    except Exception:
        pass

    # ── Post-response: reset confusion counter ──
    if _pending_confusion_reset and _confusion_detector_available:
        try:
            if any(phrase in response.lower() for phrase in UNDERSTANDING_PHRASES):
                await reset_confusion_count(student_id, current_topic)
        except Exception:
            pass

    # ── Save session snapshot ──
    try:
        from database.conversations import save_session_summary

        user_msg_count = sum(1 for m in conversation_history[-10:] if m.get("role") == "user")
        if user_msg_count >= 2:
            session_topic = _extract_topic_from_history(conversation_history)
            if response:
                for keyword in [
                    "Today:", "today:", "Let's learn about", "let's learn about",
                    "Let's focus on", "let's focus on", "Let's dive into", "let's dive into",
                    "you were doing well with", "You were doing well with",
                    "we covered", "We covered",
                ]:
                    if keyword in response:
                        parts = response.split(keyword, 1)
                        if len(parts) > 1:
                            extracted = parts[1].strip().split(".")[0].strip()[:50]
                            if extracted and len(extracted) > 2:
                                session_topic = extracted
                                break

            await save_session_summary(student_id, {
                "subject": recent_subject or "unknown",
                "topic": session_topic,
                "completed": False, "score": None,
                "struggled_with": [], "ended_at": None
            })
    except Exception:
        pass

    # ── Update Student Model ──
    # FIXED: Uses _pending_model_update from earlier load
    if _pending_model_update is not None and _student_model_available:
        try:
            session_signals = _extract_session_signals(
                message=text, response=response, student=student,
                conversation_history=conversation_history,
                recent_subject=recent_subject,
            )
            _pending_model_update.update_teaching_style(session_signals)
            _pending_model_update.update_example_domains(session_signals)
            _pending_model_update.update_communication_style(session_signals)
            _pending_model_update.update_competence(session_signals)
            await save_student_model(_pending_model_update)
        except Exception as e:
            logger.error(f"Student model update failed: {e}", exc_info=True)

    # ── Update state ──
    try:
        if current_state == "idle":
            await set_state(student_id, "chatting", reason="First message")
        elif current_state == "paused":
            await set_state(student_id, "chatting", reason="Returned from pause")
    except Exception:
        pass

    # ── JAMB Check ──
    await _maybe_trigger_jamb_check(student_id, student, chat_id, current_state)


# ═══════════════════════════════════════════════
# SESSION SIGNAL EXTRACTOR (for Student Model)
# ═══════════════════════════════════════════════

def _extract_session_signals(
    message: str,
    response: str,
    student: dict,
    conversation_history: list,
    recent_subject: str,
) -> dict:
    """
    Analyze a session to extract learning signals for the Student Model.
    
    Returns signals for: teaching_style, example_domains, communication, competence.
    """
    signals: Dict[str, Any] = {
        "teaching_style": {},
        "example_domains": {},
        "communication": {},
        "competence": {},
        "subject": recent_subject,
    }

    msg_lower = message.strip().lower()
    resp_lower = response.strip().lower()

    # ── Teaching Style Signals ──
    if any(phrase in msg_lower for phrase in ["give me an example", "show me", "can you give an example"]):
        signals["teaching_style"]["examples"] = signals["teaching_style"].get("examples", 0) + 0.3
    if any(phrase in msg_lower for phrase in ["just the definition", "be direct", "straight to the point", "no examples"]):
        signals["teaching_style"]["definitions"] = signals["teaching_style"].get("definitions", 0) + 0.3
    if any(phrase in msg_lower for phrase in ["tell me a story", "make it a story"]):
        signals["teaching_style"]["stories"] = signals["teaching_style"].get("stories", 0) + 0.3

    if any(phrase in resp_lower for phrase in UNDERSTANDING_PHRASES):
        if any(word in resp_lower for word in ["example", "imagine", "think of"]):
            signals["teaching_style"]["examples"] = signals["teaching_style"].get("examples", 0) + 0.1
        if any(word in resp_lower for word in ["definition", "is the", "refers to"]):
            signals["teaching_style"]["definitions"] = signals["teaching_style"].get("definitions", 0) + 0.1

    if "?" in message and len(message.split()) > 3:
        signals["teaching_style"]["socratic"] = signals["teaching_style"].get("socratic", 0) + 0.15

    # ── Example Domain Signals ──
    domain_patterns = {
        "transportation": ["keke", "danfo", "okada", "bus", "car", "vehicle", "suv"],
        "food_cooking": ["suya", "puff-puff", "jollof", "garri", "food", "eat", "cook"],
        "market_commerce": ["market", "mile 12", "buy", "sell", "trader", "price"],
        "technology": ["phone", "app", "game", "download", "internet", "computer"],
        "school_classroom": ["teacher", "class", "textbook", "exam", "school"],
        "home_domestic": ["generator", "nepa", "fan", "tap", "light", "water"],
        "body_physical": ["breathe", "heart", "run", "walk", "body", "hand"],
        "nature_environment": ["rain", "sun", "wind", "plant", "tree", "river"],
    }

    rejection_phrases = ["i don't", "i dont", "never", "i have never", "i haven't"]
    for domain, keywords in domain_patterns.items():
        if any(kw in msg_lower for kw in keywords):
            if any(phrase in msg_lower for phrase in rejection_phrases):
                signals["example_domains"][domain] = "avoided"
            else:
                signals["example_domains"][domain] = "preferred"

    for domain, keywords in domain_patterns.items():
        if any(kw in resp_lower for kw in keywords):
            if any(phrase in msg_lower for phrase in ["yes", "ok", "right", "get it", "understand", "makes sense"]):
                if domain not in signals["example_domains"]:
                    signals["example_domains"][domain] = "preferred"

    # ── Communication Style Signals ──
    pidgin_words = ["dey", "na", "wahala", "abeg", "omo", "sha", "nna", "abi",
                    "wetin", "go", "come", "chop", "oya", "make", "e be", "wey"]
    pidgin_count = sum(1 for word in pidgin_words if word in msg_lower)

    formal_indicators = ["i am", "do not", "cannot", "will not", "i have", "i would"]
    casual_indicators = ["i'm", "don't", "can't", "won't", "i've", "i'd", "bro", "guy"]

    formal_count = sum(1 for ind in formal_indicators if ind in msg_lower)
    casual_count = sum(1 for ind in casual_indicators if ind in msg_lower)

    if pidgin_count >= 3:
        signals["communication"]["full_pidgin"] = 0.3
    elif pidgin_count >= 1:
        signals["communication"]["pidgin_mixed"] = 0.2

    if formal_count > casual_count:
        signals["communication"]["formal_english"] = 0.2
    else:
        signals["communication"]["casual_english"] = 0.2

    total_comm = formal_count + casual_count + pidgin_count
    if total_comm > 0:
        signals["formality_score"] = (formal_count * 1.0 + casual_count * 0.5) / (total_comm + 1)

    # ── Competence Signals ──
    if any(phrase in msg_lower for phrase in ["i understand", "i get it", "makes sense", "i see"]):
        if recent_subject and recent_subject != "unknown":
            topic = "discussed"
            for hist_msg in reversed(conversation_history[-5:]):
                if hist_msg.get("role") == "assistant":
                    content = hist_msg.get("content", "")
                    for keyword in ["Today:", "we'll cover", "focusing on", "Let's dive into"]:
                        if keyword in content:
                            parts = content.split(keyword, 1)
                            if len(parts) > 1:
                                topic = parts[1].strip().split(".")[0].strip()[:50]
                                break
            signals["competence"][f"{recent_subject}:{topic}"] = {
                "score": 1.0,
                "level": "mastered"
            }

    if any(phrase in resp_lower for phrase in ["not quite", "not exactly", "close", "almost"]):
        if recent_subject and recent_subject != "unknown":
            signals["competence"][f"{recent_subject}:discussed"] = {
                "score": 0.3,
                "level": "struggling"
            }

    return signals


# ═══════════════════════════════════════════════
# SUBJECT INFERENCE
# ═══════════════════════════════════════════════

def _infer_recent_subject(student: Dict[str, Any], conversation_history: List[Dict]) -> Optional[str]:
    """Infer what subject the student is currently discussing."""
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                if subject.replace("_", " ").lower() in content.lower():
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
    except Exception:
        last_session = None

    if last_session:
        subject = last_session.get("subject", "a subject")
        topic = last_session.get("topic", "a topic")
        if subject not in ("unknown", "a subject", "") and topic not in ("unknown", "a topic", "discussed", ""):
            session_line = f"LAST SESSION: {subject} - {topic}."
            if last_session.get("completed"):
                session_line += " Completed."
                if last_session.get("score") is not None:
                    session_line += f" Score: {int(last_session['score'] * 100)}%."
            if last_session.get("struggled_with"):
                session_line += f" Struggled with: {', '.join(last_session['struggled_with'])}."
            context_parts.append(session_line)

    try:
        memory = await get_student_memory(student_id)
    except Exception:
        memory = None

    if memory:
        struggles = memory.get("struggles_with", [])
        strengths = memory.get("strong_in", [])
        mastered = memory.get("topics_mastered", [])
        sessions_count = memory.get("sessions_completed", 0)
        if struggles:
            context_parts.append(f"STUDENT STRUGGLES WITH: {', '.join(struggles[-5:])}.")
        if strengths:
            context_parts.append(f"STUDENT IS STRONG IN: {', '.join(strengths[-5:])}.")
        if mastered:
            context_parts.append(f"TOPICS MASTERED: {', '.join(mastered[-5:])}.")
        if sessions_count > 0:
            context_parts.append(f"Sessions completed: {sessions_count}.")

    return "MEMORY CONTEXT:\n" + "\n".join(context_parts) if context_parts else ""


# ═══════════════════════════════════════════════
# QUIZ ENGINE
# ═══════════════════════════════════════════════

_QUIZ_TRACKER: Dict[str, List[str]] = {}


async def _load_questions(subject: str) -> List[Dict[str, Any]]:
    """Load quiz questions for a subject."""
    cache_key = f"questions_cache:{subject}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            return json.loads(cached_str)
    except Exception:
        pass

    questions: List[Dict[str, Any]] = []
    try:
        from database.client import supabase
        result = supabase.table("questions").select("*").eq("subject", subject).order("id", desc=False).limit(200).execute()
        if result.data:
            questions = result.data
    except Exception:
        pass

    if not questions:
        try:
            json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jamb_questions_clean.json")
            with open(json_path, "r", encoding="utf-8") as f:
                all_questions = json.load(f)
            questions = [q for q in all_questions if q.get("subject") == subject]
        except Exception:
            pass

    if questions:
        try:
            redis_client.setex(cache_key, 300, json.dumps(questions))
        except Exception:
            pass
    return questions


async def _start_quiz(chat_id: int, student: Dict[str, Any], message_text: str = "") -> None:
    """Start a quiz session."""
    student_id = str(student["id"])
    student_subjects = student.get("subjects", [])
    student_track = _infer_track(student_subjects)

    if not student_subjects:
        fallback = TRACK_FALLBACKS.get(student_track, TRACK_FALLBACKS["unknown"])
        subjects_pool = fallback.copy()
        if student_track == "unknown":
            await send_telegram_message(chat_id,
                "Your subject preferences aren't set yet. Reply with your subject "
                "(e.g. *Government*, *Physics*) to get specific quizzes."
            )
    else:
        subjects_pool = student_subjects.copy()

    requested_subject = None
    if message_text:
        msg_lower = message_text.lower()
        for subj in subjects_pool:
            if subj.lower().replace("_", " ") in msg_lower:
                requested_subject = subj
                break
        if not requested_subject:
            for map_key in SUBJECT_MAP:
                display = map_key.replace("_", " ")
                if display in msg_lower and display not in ("quiz", "me", "test"):
                    requested_subject = map_key
                    break

    subject = requested_subject if requested_subject else _pick_rotated_subject(student_id, subjects_pool)
    db_subject = SUBJECT_MAP.get(subject.lower().replace(" ", "_"), subject.lower())
    questions = await _load_questions(db_subject)

    if not questions:
        await send_telegram_message(chat_id,
            f"No questions found for *{db_subject.replace('_', ' ').title()}* yet."
        )
        return

    question = random.choice(questions)
    if not _validate_question(question):
        await send_telegram_message(chat_id, "This question has invalid options. Type *quiz* to try another.")
        return

    quiz_key = f"active_quiz:{student_id}"
    try:
        redis_client.setex(quiz_key, QUIZ_TTL_SECONDS, json.dumps({
            "question": question, "subject": db_subject,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception:
        await send_telegram_message(chat_id, "Quiz setup failed. Type *quiz* to try again.")
        return

    keyboard = build_quiz_keyboard(question)
    if not keyboard:
        await send_telegram_message(chat_id, "This question is missing options. Type *quiz* for another.")
        return

    display_subject = db_subject.replace("_", " ").title()
    question_body = question.get("question_text", question.get("question", "Question loading..."))
    try:
        await send_telegram_message(chat_id, f"📝 *{display_subject}*\n\n{question_body}\n\n_Tap your answer below:_", reply_markup=keyboard)
    except Exception:
        try:
            redis_client.delete(quiz_key)
        except Exception:
            pass


async def handle_quiz_callback(chat_id: int, callback_query_id: str, callback_data: str) -> None:
    """Handle quiz button callbacks."""
    try:
        await answer_callback_query(callback_query_id, text="")
    except Exception:
        pass
    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception:
        return
    if not student:
        await send_telegram_message(chat_id, "I can't find your account. Type *HI* to restart.")
        return
    if callback_data in ("A", "B", "C", "D"):
        await _handle_quiz_answer(chat_id, student, callback_data)


async def _handle_quiz_answer(chat_id: int, student: Dict[str, Any], answer: str) -> None:
    """Evaluate a quiz answer."""
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
        redis_client.delete(quiz_key)
        await send_telegram_message(chat_id, "Quiz data was corrupted. Let's start fresh — type *quiz*.")
        return
    except Exception:
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

    if is_correct:
        response = f"✅ *Correct!*\n\n{explanation}\n\nWell done, {name}!" if explanation else f"✅ *Correct!*\n\nWell done, {name}!"
    else:
        response = f"❌ That's not quite right.\n\nThe correct answer is *{correct}*."
        if explanation:
            response += f"\n\n{explanation}"

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
    except Exception:
        pass


def _log_quiz_answer(student_id: str, question: Dict[str, Any], is_correct: bool) -> None:
    """Log quiz answer to Redis."""
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
    except Exception:
        pass


def _validate_question(question: Dict[str, Any]) -> bool:
    """Validate question has required fields."""
    if not question.get("question_text") and not question.get("question"):
        return False
    if not question.get("correct_answer"):
        return False
    correct = question["correct_answer"].strip().upper()
    if not question.get(f"option_{correct.lower()}"):
        return False
    return True


def _infer_track(subjects: List[str]) -> str:
    """Infer student's academic track."""
    if not subjects:
        return "unknown"
    subject_set = {s.lower().replace(" ", "_") for s in subjects}
    if subject_set & {"physics", "chemistry", "biology", "further_mathematics", "agricultural_science"}:
        return "science"
    if subject_set & {"accounting", "commerce", "business_studies", "marketing"}:
        return "commercial"
    if subject_set & {"literature_in_english", "government", "civic_education", "crs", "irs"}:
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
    for subject in ["mathematics", "english", "physics", "chemistry", "biology", "government", "economics"]:
        try:
            await _load_questions(subject)
        except Exception:
            pass
