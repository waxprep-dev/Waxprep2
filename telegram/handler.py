"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain. Handles quiz commands and answers.
Supports callback queries (inline keyboard) AND text-based answers.
"""
import asyncio
import hashlib
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from telegram.sender import send_telegram_message, build_quiz_keyboard, answer_callback_query
from database.client import redis_client

logger = logging.getLogger("waxprep.handler")

# ── Quiz trigger keywords ────────────────────
QUIZ_TRIGGERS = ["quiz", "quiz me", "test me", "question"]
# "practice" removed — too ambiguous, could match "I need to practice differentiation"

# ── Subject name mapping (student profile display → database column) ──
# Keys: what students might say or what's stored in profile
# Values: database column/table subject identifier
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
    # Nigerian languages
    "yoruba": "yoruba", "igbo": "igbo", "hausa": "hausa",
    # Other
    "food_and_nutrition": "food_and_nutrition", "food & nutrition": "food_and_nutrition",
    "technical_drawing": "technical_drawing", "technical drawing": "technical_drawing",
    "computer_studies": "computer_studies", "computer": "computer_studies", "ict": "computer_studies",
}

# ── Fallback subject pools by track ───────────
# Used when a student profile has no subjects set
TRACK_FALLBACKS: Dict[str, List[str]] = {
    "science": ["english", "mathematics", "physics", "chemistry", "biology"],
    "commercial": ["english", "mathematics", "economics", "commerce", "accounting"],
    "arts": ["english", "mathematics", "government", "literature_in_english", "civic_education"],
    "unknown": ["english", "mathematics"],  # Minimal fallback — prompt student to set subjects
}

# TTL for active quiz in Redis
QUIZ_TTL_SECONDS = 1800  # 30 minutes

# Maximum quiz history entries per student
MAX_QUIZ_HISTORY = 200


async def process_telegram_message(chat_id: int, text: str) -> None:
    """
    Entry point for all Telegram text messages.
    
    Processing order:
    1. Sanitize (length limit, strip)
    2. Admin commands (operator overrides)
    3. Safety checks (child protection — MUST precede AI)
    4. Student lookup (registered or new)
    5. Route to: onboarding OR registered student handler
    
    Args:
        chat_id: Telegram chat ID
        text: Raw message text from user
    """
    # 1. Sanitize
    text = text.strip()[:4000]
    if not text:
        return

    logger.debug(f"Processing message from chat_id={chat_id}: {text[:100]}...")

    # 2. Admin commands (MUST run first — bypasses all other logic)
    try:
        from admin.commands import handle_admin_command
        if await handle_admin_command(chat_id, text):
            logger.info(f"Admin command handled for chat_id={chat_id}")
            return
    except ImportError as e:
        logger.error(f"Admin module import failed: {e}")
    except Exception as e:
        logger.error(f"Admin handler error for chat_id={chat_id}: {e}", exc_info=True)

    # 3. Safety checks (child protection barrier)
    try:
        from brain.safety import run_safety_checks
        if await run_safety_checks(chat_id, text):
            logger.warning(f"Safety check blocked message from chat_id={chat_id}")
            return
    except ImportError as e:
        logger.error(f"Safety module import failed: {e}")
    except Exception as e:
        logger.error(f"Safety check error for chat_id={chat_id}: {e}", exc_info=True)
        # On safety failure, do NOT proceed to AI — block the message
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
    1. Quiz answer (single letter, active quiz exists)
    2. Quiz trigger (explicit quiz keywords)
    3. AI conversation (everything else)
    
    Args:
        chat_id: Telegram chat ID
        student: Student profile dict from database
        text: Sanitized message text
    """
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]
    msg_lower = text.strip().lower()

    # 1. Quiz answer detection
    # Check if single letter answer AND quiz is active
    cleaned = text.strip().upper()
    if cleaned in ("A", "B", "C", "D") and len(cleaned) == 1:
        quiz_key = f"active_quiz:{student_id}"
        try:
            if redis_client.exists(quiz_key):
                await _handle_quiz_answer(chat_id, student, cleaned)
                return
        except Exception as e:
            logger.error(f"Redis quiz check failed for {student_id}: {e}", exc_info=True)
            # Fall through to AI conversation rather than losing the message

    # 2. Quiz trigger
    if any(trigger in msg_lower for trigger in QUIZ_TRIGGERS):
        await _start_quiz(chat_id, student)
        return

    # 3. AI conversation
    await _handle_ai_conversation(chat_id, student, text, student_id, name)


async def _handle_ai_conversation(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    student_id: str,
    name: str
) -> None:
    """
    Process a student message through the AI brain, with memory context.
    
    Args:
        chat_id: Telegram chat ID
        student: Student profile dict
        text: Sanitized message text
        student_id: String student ID (pre-extracted for reuse)
        name: Student's first name (pre-extracted for reuse)
    """
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message

    # Save user message
    try:
        await save_message(student_id, "user", text)
    except Exception as e:
        logger.error(f"Failed to save user message for {student_id}: {e}", exc_info=True)
        # Continue anyway — don't block the student

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

    # Determine recent subject (prefer the one the student has been discussing)
    recent_subject = _infer_recent_subject(student, conversation_history)

    # Build memory context
    try:
        context_str = await _build_memory_context(student_id)
    except Exception as e:
        logger.error(f"Memory context build failed for {student_id}: {e}", exc_info=True)
        context_str = ""  # Graceful degradation — AI works without memory

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

    # Run output safety check before sending
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

    # Update state
    try:
        if current_state == "idle":
            await set_state(student_id, "chatting", reason="First message")
        elif current_state == "paused":
            await set_state(student_id, "chatting", reason="Returned from pause")
    except Exception as e:
        logger.error(f"State update failed for {student_id}: {e}", exc_info=True)


def _infer_recent_subject(student: Dict[str, Any], conversation_history: List[Dict]) -> Optional[str]:
    """
    Infer what subject the student is currently discussing.
    
    Priority:
    1. Last assistant message that mentioned a subject
    2. Student's first subject in profile
    3. None
    
    Returns:
        Subject name string or None
    """
    # Scan last few assistant messages for subject mentions
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in ALL_SUPPORTED_SUBJECTS:
                if subject.lower() in content.lower():
                    return subject

    # Fallback: first subject from profile
    subjects = student.get("subjects", [])
    if subjects and subjects[0]:
        return subjects[0]

    return None


# ═══════════════════════════════════════════════
# MEMORY CONTEXT BUILDER
# ═══════════════════════════════════════════════

async def _build_memory_context(student_id: str) -> str:
    """
    Build memory context for the AI prompt.
    
    Fetches last session summary and persistent student memory,
    formats them into a concise context string for the AI.
    
    Returns empty string if no memory exists (new student).
    This is intentional — the AI prompt handles empty context gracefully.
    
    Args:
        student_id: String student identifier
        
    Returns:
        Formatted memory context string, or empty string
    """
    from database.conversations import get_session_summary, get_student_memory

    context_parts: List[str] = []

    # 1. Last session summary
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

    # 2. Persistent student memory
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
            context_parts.append(
                f"STUDENT STRUGGLES WITH: {', '.join(struggles[-5:])}."
            )
        if strengths:
            context_parts.append(
                f"STUDENT IS STRONG IN: {', '.join(strengths[-5:])}."
            )
        if mastered:
            context_parts.append(
                f"TOPICS MASTERED: {', '.join(mastered[-5:])}."
            )
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

# Track selection for fairness (avoid repeating same subject)
_QUIZ_TRACKER: Dict[str, List[str]] = {}  # student_id → recently used subjects


async def _load_questions(subject: str) -> List[Dict[str, Any]]:
    """
    Load quiz questions for a subject with layered fallback.
    
    Order: Database (Supabase) → JSON file cache → Empty list
    
    Questions are cached in memory for 5 minutes to reduce database load.
    
    Args:
        subject: Database subject identifier (e.g., "mathematics", "government")
        
    Returns:
        List of question dicts, empty list if no questions found
    """
    # Check in-memory cache first
    cache_key = f"questions_cache:{subject}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for questions:{subject}")
            return json.loads(cached)
    except Exception:
        pass

    questions: List[Dict[str, Any]] = []

    # Try database
    try:
        from database.client import supabase
        result = (
            supabase.table("questions")
            .select("*")
            .eq("subject", subject)
            .order("id", desc=False)  # Consistent ordering
            .limit(200)  # Increased from 100 for better sampling
            .execute()
        )
        if result.data:
            questions = result.data
            logger.info(f"Loaded {len(questions)} questions from database for {subject}")
    except Exception as e:
        logger.warning(f"Database question load failed for {subject}: {e}")

    # Fallback: JSON file
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

    # Cache for 5 minutes
    if questions:
        try:
            redis_client.setex(cache_key, 300, json.dumps(questions))
        except Exception:
            pass

    return questions


async def _start_quiz(chat_id: int, student: Dict[str, Any]) -> None:
    """
    Start a quiz session for the student.
    
    Selects a subject using fairness rotation (avoids repeating same subject),
    loads questions, picks one randomly, and sends it with inline keyboard.
    
    Args:
        chat_id: Telegram chat ID
        student: Student profile dict
    """
    student_id = str(student["id"])
    student_subjects = student.get("subjects", [])
    student_track = _infer_track(student_subjects)

    # Determine subject pool
    if not student_subjects:
        # No subjects set — use track-based fallback
        fallback = TRACK_FALLBACKS.get(student_track, TRACK_FALLBACKS["unknown"])
        subjects_pool = fallback.copy()
        logger.warning(
            f"Student {student_id} ({student_track} track) has no subjects set. "
            f"Using fallback: {subjects_pool}"
        )
        # If track is unknown, warn the student
        if student_track == "unknown":
            await send_telegram_message(
                chat_id,
                "Your subject preferences aren't set yet. "
                "I'll ask some general questions for now. "
                "Reply with your subject (e.g. *Government*, *Physics*) to get specific quizzes."
            )
    else:
        subjects_pool = student_subjects.copy()

    # Rotate to avoid repeating the same subject
    subject = _pick_rotated_subject(student_id, subjects_pool)
    db_subject = SUBJECT_MAP.get(subject.lower().replace(" ", "_"), subject.lower())
    logger.info(f"Quiz subject for {student_id}: {db_subject} (from {subject})")

    # Load questions
    questions = await _load_questions(db_subject)

    if not questions:
        await send_telegram_message(
            chat_id,
            f"No questions found for *{db_subject.replace('_', ' ').title()}* yet. "
            f"Try another subject — type *quiz {subjects_pool[0] if subjects_pool else 'maths'}* if you like."
        )
        return

    # Pick random question
    question = random.choice(questions)
    logger.debug(
        f"Selected question for {student_id}: "
        f"{question.get('question_text', question.get('question', ''))[:80]}..."
    )

    # Validate question has required fields
    if not _validate_question(question):
        logger.error(f"Invalid question data for {db_subject}: {question.get('id', 'unknown')}")
        await send_telegram_message(chat_id, "This question has invalid options. Let me try another. Type *quiz*.")
        return

    # Store active quiz in Redis
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

    # Build inline keyboard
    keyboard = build_quiz_keyboard(question)
    if not keyboard:
        await send_telegram_message(chat_id, "This question is missing options. Type *quiz* for another.")
        return

    # Format and send question
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
        # Clean up orphaned quiz state
        try:
            redis_client.delete(quiz_key)
        except Exception:
            pass


async def handle_quiz_callback(chat_id: int, callback_query_id: str, callback_data: str) -> None:
    """
    Handle inline keyboard callback queries from quiz buttons.
    
    Telegram sends callback queries (not text messages) when users tap
    inline keyboard buttons. This function MUST be called from the webhook
    handler that receives callback_query updates.
    
    Args:
        chat_id: Telegram chat ID (from callback_query.message.chat.id)
        callback_query_id: Telegram callback query ID (for acknowledgment)
        callback_data: The callback_data string from the button (e.g., "A", "B", "C", "D")
    """
    logger.info(f"Quiz callback: chat_id={chat_id}, data={callback_data}")

    # Acknowledge the callback immediately (Telegram requires this within ~30 seconds)
    try:
        await answer_callback_query(callback_query_id, text="")
    except Exception as e:
        logger.error(f"Callback acknowledgment failed: {e}")

    # Look up student
    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception as e:
        logger.error(f"Student lookup failed in callback for chat_id={chat_id}: {e}")
        return

    if not student:
        await send_telegram_message(chat_id, "I can't find your account. Type *HI* to restart.")
        return

    # Process the answer
    if callback_data in ("A", "B", "C", "D"):
        await _handle_quiz_answer(chat_id, student, callback_data)
    else:
        logger.warning(f"Unknown callback data: {callback_data}")


async def _handle_quiz_answer(chat_id: int, student: Dict[str, Any], answer: str) -> None:
    """
    Evaluate a quiz answer and provide feedback.
    
    Works for both text answers and callback query answers.
    
    Args:
        chat_id: Telegram chat ID
        student: Student profile dict
        answer: The student's answer ("A", "B", "C", or "D")
    """
    student_id = str(student["id"])
    quiz_key = f"active_quiz:{student_id}"
    name = student.get("name", "Student").split()[0]

    # Load quiz data with error handling
    try:
        raw = redis_client.get(quiz_key)
        if not raw:
            await send_telegram_message(chat_id, "No active quiz. Reply with *quiz* to start one!")
            return
        quiz_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Corrupted quiz data for {student_id}")
        redis_client.delete(quiz_key)
        await send_telegram_message(chat_id, "Quiz data was corrupted. Let's start fresh — type *quiz*.")
        return
    except Exception as e:
        logger.error(f"Failed to load quiz for {student_id}: {e}", exc_info=True)
        await send_telegram_message(chat_id, "I lost track of the quiz. Type *quiz* to start a new one.")
        return

    # Clean up immediately to prevent double-answering
    try:
        redis_client.delete(quiz_key)
    except Exception:
        pass

    question = quiz_data["question"]
    correct = question.get("correct_answer", "A").strip().upper()
    is_correct = (answer == correct)

    # Build feedback message
    explanation = question.get("explanation_correct", question.get("explanation", ""))

    if is_correct:
        response = (
            f"✅ *Correct!*\n\n"
            f"{explanation}\n\n"
            f"Well done, {name}!"
        )
    else:
        # Educational feedback: explain WHY it's wrong, not just WHAT is right
        wrong_explanation = question.get(f"explanation_{answer.lower()}", "")
        response = (
            f"❌ That's not quite right.\n\n"
            f"The correct answer is *{correct}*.\n\n"
            f"{explanation}"
        )
        if wrong_explanation:
            response += f"\n\n💡 *Why {answer} wasn't right:* {wrong_explanation}"

    # Show the options for context
    opt_key = f"option_{answer.lower()}"
    correct_key = f"option_{correct.lower()}"
    opt_text = question.get(opt_key, "")
    correct_text = question.get(correct_key, "")
    if opt_text and correct_text and answer != correct:
        response += f"\n\nYour answer: *{answer}*) {opt_text}\nCorrect answer: *{correct}*) {correct_text}"

    # Log for progress tracking
    _log_quiz_answer(student_id, question, is_correct)

    # Encouraging next step
    response += "\n\nType *quiz* for another question!"

    try:
        await send_telegram_message(chat_id, response)
    except Exception as e:
        logger.error(f"Failed to send quiz feedback to chat_id={chat_id}: {e}")


def _log_quiz_answer(student_id: str, question: Dict[str, Any], is_correct: bool) -> None:
    """
    Log quiz answer to Redis for progress tracking and analytics.
    
    Uses atomic RPUSH + LTRIM for efficient list management.
    
    Args:
        student_id: String student identifier
        question: The question dict that was answered
        is_correct: Whether the answer was correct
    """
    try:
        key = f"quiz_history:{student_id}"
        entry = json.dumps({
            "subject": question.get("subject", "unknown"),
            "question_id": question.get("id", "unknown"),
            "correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Atomic push + trim using pipeline
        pipe = redis_client.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -MAX_QUIZ_HISTORY, -1)  # Keep last N entries
        pipe.expire(key, 86400 * 30)  # 30-day TTL
        pipe.execute()

        logger.debug(f"Quiz logged for {student_id}: correct={is_correct}")
    except Exception as e:
        logger.error(f"Quiz log error for {student_id}: {e}")


def _validate_question(question: Dict[str, Any]) -> bool:
    """
    Validate that a question dict has the required fields for a quiz.
    
    Returns:
        True if question is valid for display
    """
    # Must have question text
    if not question.get("question_text") and not question.get("question"):
        return False

    # Must have a correct answer
    if not question.get("correct_answer"):
        return False

    # Must have at least the correct option text
    correct = question["correct_answer"].strip().upper()
    if not question.get(f"option_{correct.lower()}"):
        return False

    return True


def _infer_track(subjects: List[str]) -> str:
    """
    Infer the student's academic track from their subject list.
    
    Returns:
        "science", "commercial", "arts", or "unknown"
    """
    if not subjects:
        return "unknown"

    subject_set = {s.lower().replace(" ", "_") for s in subjects}

    # Science indicators
    science_indicators = {"physics", "chemistry", "biology", "further_mathematics", "agricultural_science"}
    if subject_set & science_indicators:
        return "science"

    # Commercial indicators
    commercial_indicators = {"accounting", "commerce", "business_studies", "marketing"}
    if subject_set & commercial_indicators:
        return "commercial"

    # Arts indicators
    arts_indicators = {"literature_in_english", "government", "civic_education", "crs", "irs"}
    if subject_set & arts_indicators:
        return "arts"

    # Economics and Geography can go either Commercial or Arts
    if "economics" in subject_set and "government" in subject_set:
        return "arts"
    if "economics" in subject_set:
        return "commercial"

    return "unknown"


def _pick_rotated_subject(student_id: str, subjects: List[str]) -> str:
    """
    Pick a subject using fair rotation to avoid repeating the same subject.
    
    Tracks recently used subjects per student in memory.
    
    Args:
        student_id: Student identifier
        subjects: Available subjects pool
        
    Returns:
        Selected subject string
    """
    if not subjects:
        return "mathematics"

    # Get recently used subjects
    recent = _QUIZ_TRACKER.get(student_id, [])

    # Filter out recently used if we have enough variety
    available = [s for s in subjects if s not in recent]
    if not available:
        # All subjects recently used, reset rotation
        available = subjects
        _QUIZ_TRACKER[student_id] = []

    chosen = random.choice(available)

    # Track this choice
    _QUIZ_TRACKER.setdefault(student_id, []).append(chosen)
    if len(_QUIZ_TRACKER[student_id]) > 3:
        _QUIZ_TRACKER[student_id] = _QUIZ_TRACKER[student_id][-3:]

    return chosen


# ── Module-level preload of common subjects (optional warmup) ──
async def warmup_question_cache() -> None:
    """
    Preload common subjects into Redis cache for faster cold starts.
    Call during application startup.
    """
    common_subjects = ["mathematics", "english", "physics", "chemistry", "biology", "government", "economics"]
    for subject in common_subjects:
        try:
            await _load_questions(subject)
            logger.info(f"Warmed up question cache for {subject}")
        except Exception as e:
            logger.warning(f"Failed to warmup {subject}: {e}")
