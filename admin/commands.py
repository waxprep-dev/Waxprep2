"""
WaxPrep v2 — Admin Commands
Simple admin utilities. Currently: DELETE ME for testing.
"""

from database.client import supabase, redis_client
from telegram.sender import send_telegram_message


# Your Telegram chat ID for admin access
ADMIN_CHAT_IDS = {8568663974}  # REPLACE with your actual chat ID


async def handle_admin_command(chat_id: int, text: str) -> bool:
    """
    Handle admin commands. Returns True if command was handled.
    Currently supports: DELETE ME
    """
    if chat_id not in ADMIN_CHAT_IDS:
        return False

    command = text.strip().upper()

    if command == "DELETE ME":
        await _delete_me(chat_id)
        return True

    return False


async def _delete_me(chat_id: int):
    """Hard-delete the current test account so you can test onboarding fresh."""
    platform = "telegram"
    user_id = str(chat_id)

    # Find the platform session
    try:
        session = (
            supabase.table("platform_sessions")
            .select("student_id")
            .eq("platform", platform)
            .eq("platform_user_id", user_id)
            .execute()
        )

        if session.data:
            student_id = session.data[0]["student_id"]

            # Delete platform session
            supabase.table("platform_sessions").delete().eq("student_id", student_id).execute()

            # Hard delete student record
            supabase.table("students").delete().eq("id", student_id).execute()

            await send_telegram_message(chat_id, "Account hard-deleted. You can start fresh now. Send *HI* to begin.")
        else:
            await send_telegram_message(chat_id, "No account found for this Telegram ID.")
    except Exception as e:
        await send_telegram_message(chat_id, f"Delete failed: {e}")

    # Clear any onboarding state from Redis
    try:
        redis_client.delete(f"onboarding:{platform}:{user_id}")
    except Exception:
        pass
