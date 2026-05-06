"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain. Handles quiz commands and answers.
"""

from telegram.sender import send_telegram_message, build_quiz_keyboard
from database.client import redis_client
import json
import random
import os


# ── Quiz trigger keywords ────────────────────
QUIZ_TRIGGERS = ["quiz", "quiz me", "test me", "question", "practice"]


async def process_telegram_message(chat_id: int, text: str) -> None:
    """
    Entry point for all Telegram text messages.
    Processes in strict order: Sanitize → Admin → Safety → Student Lookup → Route
    """
    # Sanitize
    text = text.strip()[:4000]
    if not text:
        return

    # ── Admin commands (MUST be first) ───────
    from admin.commands import handle_admin_command
    if await handle_admin_command(chat_id, text):
        return

    # ── Safety checks (MUST come before AI) ──
    from brain.safety import run_safety_checks
    if await run_safety_checks(chat_id, text):
        return

    # ── Check if registered student ──────────
    from database.students import get_student_by_platform_id
    student = await get_student_by_platform_id("telegram", str(chat_id))

    if student:
        await _handle_registered_student(chat_id, student, text)
        return

    # ── Unregistered user — onboarding ───────
    from telegram.onboarding import handle_onboarding
    from database.onboarding_state import get_onboarding_state
    state = await get_onboarding_state("telegram", str(chat_id))
    await handle_onboarding(chat_id, state, text)


async def _handle_registered_student(chat_id: int, student: dict, text: str):
    """Route a registered student's message."""
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]
    msg_lower = text.strip().lower()

    # ── Quiz answer? (single letter A/B/C/D, only if quiz is active) ──
    if text.strip().upper() in ("A", "B", "C", "D") and len(text.strip()) == 1:
        quiz_key = f"active_quiz:{student_id}"
        if redis_client.get(quiz_key):
            await _handle_quiz_answer(chat_id, student, text.strip().upper())
            return

    # ── Quiz trigger? ──
    if any(trigger in msg_lower for trigger in QUIZ_TRIGGERS):
        await _start_quiz(chat_id, student)
        return

    # ── Normal AI conversation ──
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message

    await save_message(student_id, "user", text)
    conversation_history = await get_history(student_id)

    try:
        current_state = await get_state(student_id)
        if not current_state:
            current_state = "idle"
    except Exception:
        current_state = "idle"

    is_practice = current_state in ("in_practice", "chatting", "idle", "paused")
    recent_subject = student.get("subjects", [None])[0] if student.get("subjects") else None

    try:
        response = await think(
            message=text,
            student=student,
            conversation_history=conversation_history,
            recent_subject=recent_subject,
            context_str="",
            is_practice=is_practice
        )
    except Exception as e:
        print(f"AI brain error for {student_id}: {e}")
        response = f"Ah, my brain just froze for a second, {name}. Can you try again?"

    await save_message(student_id, "assistant", response)
    await send_telegram_message(chat_id, response)

    try:
        if current_state == "idle":
            await set_state(student_id, "chatting", reason="First message")
        elif current_state == "paused":
            await set_state(student_id, "chatting", reason="Returned from pause")
    except Exception:
        pass


# ═══════════════════════════════════════════════
# QUIZ ENGINE
# ═══════════════════════════════════════════════

# Subject name mapping (student profile → database column)
SUBJECT_MAP = {
    "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics",
    "english": "english", "english_language": "english",
    "physics": "physics", "chemistry": "chemistry", "biology": "biology",
    "economics": "economics", "government": "government",
    "commerce": "commerce", "accounting": "accounting",
    "literature": "literature_in_english", "literature_in_english": "literature_in_english",
    "christian_religious_studies": "crs", "crs": "crs",
}


async def _load_questions(subject: str) -> list:
    """
    Load questions for a subject.
    Tries database first, falls back to JSON file.
    """
    # Try database
    try:
        from database.client import supabase
        result = supabase.table("questions") \
            .select("*") \
            .eq("subject", subject) \
            .limit(100) \
            .execute()
        if result.data:
            print(f"Loaded {len(result.data)} questions from database for {subject}")
            return result.data
    except Exception as e:
        print(f"Database question load failed: {e}")

    # Fallback: load from JSON file
    try:
        # On Render, file is in the project root (same directory as main.py)
        json_path = os.path.join(os.path.dirname(__file__), "..", "jamb_questions_clean.json")
        json_path = os.path.abspath(json_path)
        print(f"Loading questions from: {json_path}")
        with open(json_path, "r") as f:
            all_questions = json.load(f)
        print(f"Loaded {len(all_questions)} total questions from JSON")
        filtered = [q for q in all_questions if q.get("subject") == subject]
        print(f"Found {len(filtered)} questions for subject: {subject}")
        return filtered
    except Exception as e:
        print(f"JSON question load failed: {e}")
        return []


async def _start_quiz(chat_id: int, student: dict):
    """Start a quiz session for the student."""
    student_id = str(student["id"])
    subjects = student.get("subjects", ["english"])
    print(f"Starting quiz for {student_id}, subjects: {subjects}")

    # Pick a random subject from the student's list
    subject = random.choice(subjects).lower().replace(" ", "_")
    db_subject = SUBJECT_MAP.get(subject, subject)
    print(f"Selected subject: {db_subject}")

    # Load questions
    questions = await _load_questions(db_subject)

    if not questions:
        await send_telegram_message(chat_id, f"No questions found for {db_subject.replace('_', ' ').title()}. Try another subject.")
        return

    # Pick a random question
    question = random.choice(questions)
    print(f"Selected question: {question.get('question_text', question.get('question', ''))[:80]}...")

    # Store active quiz in Redis (30-minute expiry)
    quiz_key = f"active_quiz:{student_id}"
    redis_client.setex(quiz_key, 1800, json.dumps({
        "question": question,
        "subject": db_subject,
    }))

    # Build and send
    keyboard = build_quiz_keyboard(question)
    if not keyboard:
        await send_telegram_message(chat_id, "This question has invalid options. Try again.")
        return

    question_text = (
        f"📝 *{db_subject.replace('_', ' ').title()}*\n\n"
        f"{question.get('question_text', question.get('question', ''))}\n\n"
        f"_Tap your answer below:_"
    )

    await send_telegram_message(chat_id, question_text, reply_markup=keyboard)


async def _handle_quiz_answer(chat_id: int, student: dict, answer: str):
    """Evaluate a quiz answer and provide feedback."""
    student_id = str(student["id"])
    quiz_key = f"active_quiz:{student_id}"

    # Load quiz data from Redis
    raw = redis_client.get(quiz_key)
    if not raw:
        await send_telegram_message(chat_id, "No active quiz. Type *quiz* to start one.")
        return

    quiz_data = json.loads(raw)
    redis_client.delete(quiz_key)

    question = quiz_data["question"]
    correct = question.get("correct_answer", "A").strip().upper()
    is_correct = (answer == correct)

    # Build feedback
    if is_correct:
        response = f"✅ *Correct!*\n\n{question.get('explanation_correct', question.get('explanation', 'Well done!'))}"
    else:
        response = (
            f"❌ Not quite. The correct answer was *{correct}*.\n\n"
            f"{question.get('explanation_correct', question.get('explanation', ''))}"
        )

    # Add option text for context
    opt_key = f"option_{answer.lower()}"
    correct_key = f"option_{correct.lower()}"
    opt_text = question.get(opt_key, "")
    correct_text = question.get(correct_key, "")
    if opt_text and correct_text:
        response += f"\n\nYou picked: {answer}) {opt_text}\nCorrect: {correct}) {correct_text}"

    # Log for progress tracking
    _log_quiz_answer(student_id, question, is_correct)

    response += "\n\nType *quiz* for another question!"

    await send_telegram_message(chat_id, response)


def _log_quiz_answer(student_id: str, question: dict, is_correct: bool):
    """Log quiz answer to Redis for progress tracking."""
    try:
        key = f"quiz_history:{student_id}"
        raw = redis_client.get(key)
        history = json.loads(raw) if raw else []
        
        history.append({
            "subject": question.get("subject", "unknown"),
            "correct": is_correct,
        })
        
        if len(history) > 200:
            history = history[-200:]
        
        redis_client.setex(key, 86400 * 30, json.dumps(history))
    except Exception as e:
        print(f"Quiz log error: {e}")
