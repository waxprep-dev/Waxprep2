"""
WaxPrep v2 — Safety & Crisis Detection (Lightweight Scanner)
Rewritten as a lightweight input scanner + output safety net.
Never bypasses the AI. Safety violations are logged; AI handles all responses.

Changes from previous version:
- Removed all crisis/malpractice keyword detection and hardcoded responses.
- Exploitation flags are logged only; a context whisper is injected for the AI.
- Output safety blocks only hard-safety violations (self-harm, sexual, dangerous).
- Redis cooldown is now used only for exploitation log spam prevention.
- Persona compliance is delegated to the AI prompt, not output filtering.
"""

import hashlib
import logging
import asyncio
from datetime import datetime, timezone

from telegram.sender import send_telegram_message
from database.client import redis_client, supabase

logger = logging.getLogger("waxprep.safety")


# ═══════════════════════════════════════════════
# EXPLOITATION KEYWORDS
# ═══════════════════════════════════════════════
# Logging only — never blocks conversation. The student may need to keep talking.

EXPLOITATION_KEYWORDS = [
    "uncle hits me", "aunty beats me",
    "father beats me", "mother beats me",
    "work all day", "no time to eat",
    "chased from home", "nobody cares",
    "no one loves me", "touches me",
    "beaten at home",
    "scared to go home",
    "afraid of my",
    "hurts me at night",
    "makes me do things",
    "won't let me go to school",
    "locked me out",
    "haven't eaten",
    "sleeping outside",
    "living on the street",
]


# ═══════════════════════════════════════════════
# OUTPUT BLOCK KEYWORDS
# ═══════════════════════════════════════════════
# Hard-safety violations only. Persona compliance is the prompt's job.

OUTPUT_BLOCK_KEYWORDS = [
    "you should hurt yourself",
    "harm yourself",
    "kill yourself",
    "end your life",
    "take your own life",
    "sexual", "pornography", "explicit",
    "intimate", "naked", "nsfw",
    "overdose on",
    "take pills to",
    "drink bleach",
    "give me your password",
    "send money",
]


# ═══════════════════════════════════════════════
# COOLDOWNS
# ═══════════════════════════════════════════════

EXPLOITATION_LOG_COOLDOWN = 300  # 5 minutes between exploitation logs


# ═══════════════════════════════════════════════
# CONTEXT WHISPER
# ═══════════════════════════════════════════════
# Injected into Redis when exploitation is detected so the AI can read it
# before generating a response.

EXPLOITATION_CONTEXT_WHISPER = (
    "Safeguarding note: The student may be experiencing abuse, neglect, "
    "or exploitation. Respond with extra care, validate their feelings, "
    "and avoid suggesting they return to an unsafe home environment. "
    "If they disclose immediate danger, encourage contacting a trusted "
    "adult outside the home or NAPTIP (07030000203)."
)


# ═══════════════════════════════════════════════
# DETECTION FUNCTIONS
# ═══════════════════════════════════════════════

def detect_exploitation(message: str) -> bool:
    """
    Check if message suggests abuse or exploitation.
    Logs only — never blocks conversation.
    """
    normalized = message.lower().strip()
    return any(keyword in normalized for keyword in EXPLOITATION_KEYWORDS)


# ═══════════════════════════════════════════════
# OUTPUT SAFETY
# ═══════════════════════════════════════════════

async def check_output_safety(response: str) -> bool:
    """
    Check an AI-generated response before sending to the student.
    Blocks only hard-safety violations. Persona compliance is the prompt's job.
    Returns True if the response should be BLOCKED.
    """
    if not response or not response.strip():
        logger.warning("SAFETY BLOCK: Empty response")
        return True

    normalized = response.lower().strip()

    for keyword in OUTPUT_BLOCK_KEYWORDS:
        if keyword in normalized:
            logger.warning(f"SAFETY BLOCK: Output blocked for containing '{keyword}'")
            try:
                supabase.table("blocked_outputs").insert({
                    "keyword_matched": keyword,
                    "response_preview": response[:200],
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception as e:
                logger.error(f"Failed to log blocked output: {e}")
            return True

    if len(normalized) < 2:
        logger.warning("SAFETY BLOCK: Response too short")
        return True

    return False


# ═══════════════════════════════════════════════
# MAIN SAFETY CHECK (INPUT SAFETY)
# ═══════════════════════════════════════════════

async def run_safety_checks(chat_id: int, message: str, student_id: str = None) -> bool:
    """
    Lightweight input safety scanner.
    Never bypasses the AI. Logs exploitation flags, injects a context whisper,
    and always returns False so the AI handles the response.
    """
    if detect_exploitation(message):
        # Cooldown check to prevent log spam
        cooldown_key = f"waxprep:exploitation_cooldown:{chat_id}"
        try:
            if redis_client.get(cooldown_key):
                logger.info(f"Exploitation cooldown active for chat_id={chat_id}")
            else:
                redis_client.setex(cooldown_key, EXPLOITATION_LOG_COOLDOWN, "1")
                # Log to DB (fire-and-forget)
                asyncio.create_task(
                    _log_exploitation_flag_async(chat_id, message, student_id)
                )
        except Exception as e:
            logger.error(f"Redis exploitation cooldown check failed: {e}")

        # Inject context whisper for Wax (AI reads this before generating response)
        whisper_key = f"waxprep:context_whisper:{chat_id}"
        try:
            redis_client.setex(whisper_key, 60, EXPLOITATION_CONTEXT_WHISPER)
        except Exception as e:
            logger.error(f"Failed to inject context whisper: {e}")

    return False


# ═══════════════════════════════════════════════
# LOGGING FUNCTIONS (async wrappers for fire-and-forget)
# ═══════════════════════════════════════════════

async def _log_crisis_event_async(
    chat_id: int,
    message: str,
    student_id: str = None,
    escalation_count: int = 1
) -> None:
    """Async wrapper for crisis event logging — runs as background task."""
    try:
        _log_crisis_event(chat_id, message, student_id, escalation_count)
    except Exception as e:
        logger.error(f"Crisis event logging failed: {e}")


async def _log_malpractice_event_async(
    chat_id: int,
    message: str,
    student_id: str = None
) -> None:
    """Async wrapper for malpractice event logging — runs as background task."""
    try:
        _log_malpractice_event(chat_id, message, student_id)
    except Exception as e:
        logger.error(f"Malpractice event logging failed: {e}")


async def _log_exploitation_flag_async(
    chat_id: int,
    message: str,
    student_id: str = None
) -> None:
    """Async wrapper for exploitation flag logging — runs as background task."""
    try:
        _log_exploitation_flag(chat_id, message, student_id)
    except Exception as e:
        logger.error(f"Exploitation flag logging failed: {e}")


# ═══════════════════════════════════════════════
# LOGGING FUNCTIONS (sync — called from async wrappers)
# ═══════════════════════════════════════════════

def _log_crisis_event(
    chat_id: int,
    message: str,
    student_id: str = None,
    escalation_count: int = 1
) -> None:
    """
    Log a crisis event to database and emit loud console alert.
    Uses deterministic hashlib.sha256 for phone_hash.
    """
    event_data = {
        "phone_hash": hashlib.sha256(str(chat_id).encode()).hexdigest()[:16],
        "student_id": student_id,
        "message_preview": message[:100],
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "escalation_count": escalation_count,
    }

    try:
        supabase.table("crisis_events").insert(event_data).execute()
    except Exception as e:
        logger.error(f"Failed to log crisis event to database: {e}")
        try:
            redis_client.lpush(
                "waxprep:failed_crisis_logs",
                str(event_data)
            )
        except Exception:
            pass

    logger.critical(
        "=" * 60 + "\n"
        f"🚨 URGENT: Crisis detected at {datetime.now(timezone.utc).isoformat()}\n"
        f"   Chat ID: {chat_id}\n"
        f"   Student: {student_id or 'Unknown'}\n"
        f"   Escalation: {escalation_count} trigger(s) in window\n"
        f"   Message: {message[:200]}\n"
        + "=" * 60
    )


def _log_malpractice_event(
    chat_id: int,
    message: str,
    student_id: str = None
) -> None:
    """
    Log a malpractice detection event.
    Uses deterministic hashlib.sha256 for phone_hash.
    """
    event_data = {
        "phone_hash": hashlib.sha256(str(chat_id).encode()).hexdigest()[:16],
        "student_id": student_id,
        "message_preview": message[:100],
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase.table("malpractice_events").insert(event_data).execute()
    except Exception as e:
        logger.error(f"Failed to log malpractice event: {e}")

    logger.info(
        f"MALPRACTICE DETECTED: chat_id={chat_id}, "
        f"student={student_id}, message={message[:100]}"
    )


def _log_exploitation_flag(
    chat_id: int,
    message: str,
    student_id: str = None
) -> None:
    """
    Flag concerning messages for human review.
    Uses deterministic hashlib.sha256 for phone_hash.
    Exploitation signals are logged for review by safeguarding personnel.
    """
    event_data = {
        "phone_hash": hashlib.sha256(str(chat_id).encode()).hexdigest()[:16],
        "student_id": student_id,
        "message_preview": message[:100],
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        supabase.table("exploitation_flags").insert(event_data).execute()
    except Exception as e:
        logger.error(f"Failed to log exploitation flag: {e}")

    logger.warning(
        f"⚠️ EXPLOITATION FLAG: chat_id={chat_id}, "
        f"student={student_id}, message={message[:100]}"
    )
