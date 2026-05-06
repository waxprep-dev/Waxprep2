"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain. Handles quiz commands and answers.
"""

from telegram.sender import send_telegram_message, build_quiz_keyboard


# ── Quiz trigger keywords ────────────────────
QUIZ_TRIGGERS = ["quiz", "quiz me", "test me", "question", "practice"]

# ── In-memory quiz session store (active quizzes per student) ──
# Format: {student_id: {"question": {...}, "subject": "biology"}}
ACTIVE_QUIZZES = {}


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

    # ── Quiz answer? (single letter A/B/C/D or a-d) ──
    if text.strip().upper() in ("A", "B", "C", "D") and len(text.strip()) == 1:
        if student_id in ACTIVE_QUIZZES:
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

async def _start_quiz(chat_id: int, student: dict):
    """Start a quiz session for the student. Pulls a question from Supabase."""
    from database.client import supabase
    import random

    student_id = str(student["id"])
    subjects = student.get("subjects", ["english"])

    # Pick a random subject from the student's list
    subject = random.choice(subjects).lower().replace(" ", "_")
    
    # Map common subject names to database values
    subject_map = {
        "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics",
        "english": "english", "english_language": "english",
        "physics": "physics", "chemistry": "chemistry", "biology": "biology",
        "economics": "economics", "government": "government",
        "commerce": "commerce", "accounting": "accounting",
        "literature": "literature_in_english", "literature_in_english": "literature_in_english",
        "christian_religious_studies": "crs", "crs": "crs",
    }
    
    db_subject = subject_map.get(subject, subject)

    # Fetch a random question for this subject
    try:
        result = supabase.table("questions") \
            .select("*") \
            .eq("subject", db_subject) \
            .eq("is_active", True) \
            .limit(1) \
            .execute()

        if not result.data:
            await send_telegram_message(chat_id, f"No questions found for {subject}. Try another subject.")
            return

        question = result.data[0]
    except Exception as e:
        print(f"Quiz fetch error: {e}")
        await send_telegram_message(chat_id, "Couldn't fetch a question. Try again.")
        return

    # Store the active quiz
    ACTIVE_QUIZZES[student_id] = {
        "question": question,
        "subject": db_subject,
    }

    # Build the quiz keyboard
    keyboard = build_quiz_keyboard(question)

    # Send the question
    question_text = (
        f"📝 *{db_subject.replace('_', ' ').title()}*\n\n"
        f"{question['question_text']}\n\n"
        f"_Tap your answer below:_"
    )

    await send_telegram_message(chat_id, question_text, reply_markup=keyboard)


async def _handle_quiz_answer(chat_id: int, student: dict, answer: str):
    """Evaluate a quiz answer and provide feedback."""
    student_id = str(student["id"])
    quiz_data = ACTIVE_QUIZZES.pop(student_id, None)

    if not quiz_data:
        await send_telegram_message(chat_id, "No active quiz. Type *quiz* to start one.")
        return

    question = quiz_data["question"]
    correct = question.get("correct_answer", "A").strip().upper()
    is_correct = (answer == correct)

    # Build feedback
    if is_correct:
        response = f"✅ *Correct!*\n\n{question.get('explanation_correct', 'Well done!')}"
    else:
        response = (
            f"❌ Not quite. The correct answer was *{correct}*.\n\n"
            f"{question.get('explanation_correct', '')}"
        )

    # Add option text for context
    opt_text = question.get(f"option_{answer.lower()}", "")
    correct_text = question.get(f"option_{correct.lower()}", "")
    if opt_text and correct_text:
        response += f"\n\nYou picked: {answer}) {opt_text}\nCorrect: {correct}) {correct_text}"

    response += "\n\nType *quiz* for another question!"

    await send_telegram_message(chat_id, response)
