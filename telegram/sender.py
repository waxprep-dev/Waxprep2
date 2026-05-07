"""
WaxPrep v2 — Telegram Message Sender

Handles all Telegram Bot API communication:
- Sending text messages (with Markdown formatting and fallback)
- Building inline keyboards for quiz questions
- Acknowledging callback queries (button taps)

This module is a pure API client — no business logic, no database.
"""

import logging
from typing import Optional, Dict, Any

import httpx
from config.settings import settings

logger = logging.getLogger("waxprep.telegram_sender")

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"

# ── Message length limit ─────────────────────
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


async def send_telegram_message(
    chat_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    max_retries: int = 2
) -> bool:
    """
    Send a text message to a Telegram chat.
    
    Features:
    - Truncates messages exceeding Telegram's 4096 character limit
    - Sends with Markdown formatting by default
    - Falls back to plain text if Markdown parsing fails
    - Retries on transient server errors (429, 5xx)
    
    Args:
        chat_id: Telegram chat ID
        text: Message text (supports Telegram Markdown)
        reply_markup: Optional inline keyboard or reply markup dict
        max_retries: Maximum retry attempts for transient failures
        
    Returns:
        True if message was sent successfully, False otherwise
    """
    # Truncate if necessary
    if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH:
        logger.warning(
            f"Message truncated from {len(text)} to {TELEGRAM_MAX_MESSAGE_LENGTH} chars"
        )
        text = text[:TELEGRAM_MAX_MESSAGE_LENGTH - 3] + "..."

    url = f"{TELEGRAM_API}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)

                # Success
                if response.status_code == 200:
                    return True

                # Markdown parsing error — retry without formatting
                if response.status_code == 400:
                    try:
                        error_data = response.json()
                        error_desc = error_data.get("description", "")
                    except Exception:
                        error_desc = response.text

                    if "parse" in error_desc.lower() or "can't parse" in error_desc.lower():
                        logger.info(
                            f"Markdown parse failed for chat_id={chat_id}, "
                            f"retrying without formatting"
                        )
                        payload.pop("parse_mode", None)
                        # Don't count this as a retry — it's a format correction
                        try:
                            async with httpx.AsyncClient(timeout=15.0) as client_retry:
                                retry_response = await client_retry.post(url, json=payload)
                                if retry_response.status_code == 200:
                                    return True
                                logger.error(
                                    f"Plain text retry also failed: "
                                    f"{retry_response.status_code}"
                                )
                        except Exception as e:
                            logger.error(f"Plain text retry exception: {e}")
                        return False

                # Rate limit — wait and retry
                if response.status_code == 429:
                    retry_after = _extract_retry_after(response)
                    logger.warning(
                        f"Rate limited by Telegram. Retrying after {retry_after}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries:
                        import asyncio
                        await asyncio.sleep(retry_after)
                        continue

                # Server error — retry
                if response.status_code >= 500:
                    logger.warning(
                        f"Telegram server error {response.status_code}. "
                        f"Retrying (attempt {attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries:
                        import asyncio
                        await asyncio.sleep(1.0 * (attempt + 1))  # Exponential-ish backoff
                        continue

                # Other error — don't retry
                logger.error(
                    f"Telegram send error (status={response.status_code}): "
                    f"{response.text[:200]}"
                )
                return False

        except httpx.TimeoutException:
            logger.error(f"Telegram send timeout for chat_id={chat_id}")
            if attempt < max_retries:
                continue
            return False

        except Exception as e:
            logger.error(f"Telegram send exception: {e}", exc_info=True)
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(0.5)
                continue
            return False

    logger.error(f"All retries exhausted for chat_id={chat_id}. Last error: {last_error}")
    return False


def _extract_retry_after(response: httpx.Response) -> float:
    """
    Extract retry_after seconds from Telegram's 429 response.
    
    Telegram returns retry_after in the JSON body or as a header.
    Default: 3 seconds if not specified.
    """
    try:
        data = response.json()
        retry = data.get("parameters", {}).get("retry_after", 3)
        return float(retry)
    except Exception:
        return 3.0


async def answer_callback_query(
    callback_query_id: str,
    text: str = "",
    show_alert: bool = False
) -> bool:
    """
    Acknowledge a Telegram callback query (button tap).
    
    Telegram requires callback queries to be acknowledged within 30 seconds
    or the button shows a loading spinner forever.
    
    Call this FIRST in your callback handler, before any processing.
    
    Args:
        callback_query_id: The callback query ID from Telegram update
        text: Optional notification text shown to the user.
              Leave empty ("") for silent acknowledgment.
        show_alert: If True, shows as a popup dialog.
                    If False, shows as a brief toast notification.
                    Default: False (less disruptive)
    
    Returns:
        True if acknowledgment was successful, False otherwise
    """
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    payload: Dict[str, Any] = {
        "callback_query_id": callback_query_id,
    }

    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)

            if response.status_code == 200:
                return True

            # Log but don't retry — callback queries are time-sensitive
            logger.error(
                f"Callback answer error (status={response.status_code}): "
                f"{response.text[:200]}"
            )
            return False

    except httpx.TimeoutException:
        logger.error(f"Callback answer timeout for query_id={callback_query_id}")
        return False
    except Exception as e:
        logger.error(f"Callback answer exception: {e}", exc_info=True)
        return False


def build_quiz_keyboard(question: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build a Telegram inline keyboard for a multiple-choice quiz question.
    
    Expected question dict keys:
        'option_a', 'option_b', 'option_c', 'option_d'
    
    Layout:
        Row 1: [A) ...] [B) ...]
        Row 2: [C) ...] [D) ...]
    
    Validation:
        - Requires at least options A and B to have content
        - Requires at least 2 unique options (prevents AI hallucination)
        - Strips whitespace from options
    
    Args:
        question: Dict with option_a through option_d keys
        
    Returns:
        Inline keyboard markup dict ready for reply_markup,
        or None if the question is invalid for display
    """
    opt_a = question.get("option_a", "").strip()
    opt_b = question.get("option_b", "").strip()
    opt_c = question.get("option_c", "").strip()
    opt_d = question.get("option_d", "").strip()

    # Must have at least A and B
    if not opt_a or not opt_b:
        logger.warning("Quiz keyboard rejected: missing option A or B")
        return None

    # Check for unique options (AI hallucination guard)
    options = [opt_a, opt_b, opt_c, opt_d]
    unique_options = [o for o in options if o]  # Remove empty strings
    unique_set = set(unique_options)

    if len(unique_set) < 2:
        logger.warning(
            f"Quiz keyboard rejected: all options identical "
            f"(unique: {unique_set})"
        )
        return None

    # Truncate long option text for button display
    max_option_length = 50
    opt_a = _truncate_button_text(opt_a, max_option_length)
    opt_b = _truncate_button_text(opt_b, max_option_length)
    opt_c = _truncate_button_text(opt_c, max_option_length) if opt_c else ""
    opt_d = _truncate_button_text(opt_d, max_option_length) if opt_d else ""

    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"A) {opt_a}", "callback_data": "A"},
                {"text": f"B) {opt_b}", "callback_data": "B"},
            ],
            [
                {"text": f"C) {opt_c}", "callback_data": "C"} if opt_c else None,
                {"text": f"D) {opt_d}", "callback_data": "D"} if opt_d else None,
            ],
        ]
    }
    
    # Remove None buttons (empty options)
    keyboard["inline_keyboard"][1] = [
        btn for btn in keyboard["inline_keyboard"][1] if btn is not None
    ]
    if not keyboard["inline_keyboard"][1]:
        keyboard["inline_keyboard"] = keyboard["inline_keyboard"][:1]

    return keyboard


def _truncate_button_text(text: str, max_length: int = 50) -> str:
    """
    Truncate button text to fit Telegram's button display limits.
    
    Telegram inline buttons have practical width limits.
    Long option text gets truncated with ellipsis.
    
    Args:
        text: Button label text
        max_length: Maximum characters before truncation
        
    Returns:
        Truncated text (with "..." if truncated)
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - 3].rstrip() + "..."


def escape_markdown(text: str) -> str:
    """
    Escape user-provided text for safe use in Telegram Markdown messages.
    
    Telegram Markdown interprets these characters as formatting:
    _, *, [, ], (, ), ~, `, >, #, +, -, =, |, {, }, ., !
    
    This function escapes them so user names and input display correctly.
    Use this when inserting student names or other user-provided text
    into Markdown-formatted Telegram messages.
    
    Args:
        text: Raw user input (e.g., student name, subject)
        
    Returns:
        Escaped text safe for Markdown parse_mode
        
    Example:
        >>> escape_markdown("Chidera_Emeka")
        'Chidera\\_Emeka'
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for char in text:
        if char in escape_chars:
            escaped += "\\" + char
        else:
            escaped += char
    return escaped
