"""
WaxPrep v2 — Telegram Message Sender
Sends text messages via Telegram Bot API.
"""

import httpx
from config.settings import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Send a text message to a Telegram chat. Returns True on success."""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

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
