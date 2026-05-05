"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes anonymous users to onboarding,
registered users to the AI brain.
"""

from telegram.sender import send_telegram_message
from database.onboarding_state import get_onboarding_state


async def process_telegram_message(chat_id: int, text: str) -> None:
    """
    Entry point for all Telegram text messages.
    Decides: is this a registered student or a new user?
    """
    # Sanitize
    text = text.strip()[:4000]
    if not text:
        return

    # ── Admin commands ───────────────────────
    from admin.commands import handle_admin_command
    if await handle_admin_command(chat_id, text):
        return

    # ── Check if registered student ──────────
    from database.students import get_student_by_platform_id

    student = await get_student_by_platform_id("telegram", str(chat_id))

    if student:
        # Registered user — TODO: AI brain handling (Phase 2)
        name = student.get("name", "Student").split()[0]
        await send_telegram_message(
            chat_id,
            f"Hey {name}! I'm here. (Full AI coming in Phase 2 — for now, onboarding is ready!)"
        )
        return

    # ── Unregistered user — onboarding ───────
    from telegram.onboarding import handle_onboarding

    # Load their current onboarding state from Redis
    state = await get_onboarding_state("telegram", str(chat_id))

    # Route to the correct onboarding step
    await handle_onboarding(chat_id, state, text)
