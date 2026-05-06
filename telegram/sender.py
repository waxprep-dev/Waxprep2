"""
WaxPrep v2 — Telegram Message Sender
Sends text messages via Telegram Bot API.
Includes quiz keyboard builder for tappable A/B/C/D buttons.
"""

import httpx
from config.settings import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """Send a text message to a Telegram chat. Returns True on success."""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)

            if response.status_code == 200:
                return True

            # If Markdown parsing fails, retry without formatting
            if response.status_code == 400 and "parse" in str(response.json()).lower():
                payload.pop("parse_mode", None)
                retry = await client.post(url, json=payload)
                return retry.status_code == 200

            print(f"Telegram send error: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"Telegram send exception: {e}")
        return False


def build_quiz_keyboard(question: dict) -> dict:
    """
    Given a quiz question dict with keys 'option_a','option_b','option_c','option_d',
    returns a Telegram inline keyboard markup with tappable A/B/C/D buttons.
    Returns None if the question is not a valid multiple-choice.
    """
    opt_a = question.get('option_a', '')
    opt_b = question.get('option_b', '')
    opt_c = question.get('option_c', '')
    opt_d = question.get('option_d', '')

    # Only build keyboard if we have at least two options with content
    if not opt_a or not opt_b:
        return None

    # Check that not all options are identical (AI hallucination guard)
    options = [opt_a.strip(), opt_b.strip(), opt_c.strip(), opt_d.strip()]
    unique = list(set(o for o in options if o))
    if len(unique) < 2:
        return None

    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"A) {opt_a}", "callback_data": "A"},
                {"text": f"B) {opt_b}", "callback_data": "B"},
            ],
            [
                {"text": f"C) {opt_c}", "callback_data": "C"},
                {"text": f"D) {opt_d}", "callback_data": "D"},
            ],
        ]
    }
    return keyboard
