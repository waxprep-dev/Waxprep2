"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain.
"""

from telegram.sender import send_telegram_message


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
        return  # Message was handled by safety (crisis/malpractice)

    # ── Check if registered student ──────────
    from database.students import get_student_by_platform_id

    student = await get_student_by_platform_id("telegram", str(chat_id))

    if student:
        # ── Registered student → AI brain ────
        await _handle_registered_student(chat_id, student, text)
        return

    # ── Unregistered user — onboarding ───────
    from telegram.onboarding import handle_onboarding
    from database.onboarding_state import get_onboarding_state

    # Load their current onboarding state from Redis
    state = await get_onboarding_state("telegram", str(chat_id))

    # Route to the correct onboarding step
    await handle_onboarding(chat_id, state, text)


async def _handle_registered_student(chat_id: int, student: dict, text: str):
    """
    Route a registered student's message to the AI brain.
    Sets up conversation context and sends the response.
    """
    from ai.brain import think
    from brain.state import get_state, set_state

    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]

    # Get current state
    try:
        current_state = await get_state(student_id)
        if not current_state:
            current_state = "idle"
    except Exception as e:
        print(f"State lookup failed for {student_id}: {e}")
        current_state = "idle"

    # Determine if this is a practice/chat message (lite prompt)
    is_practice = current_state in ("in_practice", "chatting", "idle", "paused")

    # Get current subject if in a lesson
    # TODO: Load from session state (database), not from student profile
    recent_subject = None
    if current_state in ("in_lesson", "in_practice", "stuck"):
        recent_subject = student.get("subjects", [None])[0] if student.get("subjects") else None

    # TODO: Load conversation history from database
    # This is the biggest missing piece — without it, Wax has amnesia
    # Phase 2B: Implement message history storage and retrieval
    conversation_history = []

    # TODO: Build context string from memory/progress
    # Phase 2C: Include recent performance, weak topics, session goals
    context_str = ""

    # Call the AI brain
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
        print(f"AI brain error for student {student_id}: {e}")
        response = (
            f"Ah, my brain just froze for a second, {name}. "
            f"Can you try again? I'm back now."
        )

    await send_telegram_message(chat_id, response)

    # Transition to appropriate state
    # TODO: More sophisticated state transitions based on message content
    # Phase 2B: Analyze intent to drive state changes
    try:
        if current_state == "idle":
            await set_state(student_id, "chatting", reason="First message of session")
        elif current_state == "paused":
            await set_state(student_id, "chatting", reason="Student returned from pause")
    except Exception as e:
        print(f"State update failed for {student_id}: {e}")
