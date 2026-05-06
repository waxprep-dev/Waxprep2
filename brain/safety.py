"""
WaxPrep v2 — Safety & Crisis Detection
Handles situations where student wellbeing is at risk.
This runs BEFORE any AI processing — safety is priority zero.
"""

from datetime import datetime
from telegram.sender import send_telegram_message
from database.client import redis_client, supabase


# ── Crisis Keywords ──────────────────────────
# If a student's message contains ANY of these, we bypass AI
# and respond with the crisis helpline immediately.

CRISIS_KEYWORDS = [
    "i want to die", "i wanna die", "i want 2 die",
    "kill myself", "kms", "end my life",
    "not worth living", "better off dead",
    "no reason to live", "want to end it",
    "suicide", "self harm", "self-harm",
    "hurt myself", "cutting myself",
    "don't want to be here", "feel like dying",
    "i'm going to kill myself", "going to end it",
]


# ── Malpractice Keywords ─────────────────────
# WaxPrep never helps with exam cheating.

MALPRACTICE_KEYWORDS = [
    "how to cheat", "exam malpractice",
    "bring phone to exam", "copy from friend",
    "sneak answers", "write answers on",
    "hide notes", "expo", "runs",
    "leakage", "leaked questions",
    "help me cheat", "wayo",
]


# ── Exploitation Keywords ────────────────────
# These get flagged for human review but don't
# stop the conversation.

EXPLOITATION_KEYWORDS = [
    "uncle hits me", "aunty beats me",
    "father beats me", "mother beats me",
    "work all day", "no time to eat",
    "chased from home", "nobody cares",
    "no one loves me", "touches me",
    "beaten at home",
]


# ── Crisis cooldown (seconds) ────────────────
CRISIS_COOLDOWN = 300  # 5 minutes between crisis responses


# ── Normalization ────────────────────────────

def _normalize(text: str) -> str:
    """Normalize text to catch obfuscated crisis signals."""
    lower = text.lower().strip()
    lower = " ".join(lower.split())  # Collapse multiple spaces
    lower = lower.replace("wanna", "want to")
    lower = lower.replace("gonna", "going to")
    lower = lower.replace("2", "to").replace("4", "for")
    return lower


# ── Detection Functions ──────────────────────

def detect_crisis(message: str) -> bool:
    """Check if message indicates self-harm or suicidal intent."""
    normalized = _normalize(message)
    return any(keyword in normalized for keyword in CRISIS_KEYWORDS)


def detect_malpractice(message: str) -> bool:
    """Check if message is asking for exam cheating help."""
    normalized = _normalize(message)
    return any(keyword in normalized for keyword in MALPRACTICE_KEYWORDS)


def detect_exploitation(message: str) -> bool:
    """Check if message suggests abuse or exploitation. Flags for review."""
    normalized = _normalize(message)
    return any(keyword in normalized for keyword in EXPLOITATION_KEYWORDS)


# ── Response Functions ───────────────────────

CRISIS_RESPONSE = (
    "📞 *Nigeria Suicide Prevention Hotline:* 080097738255\n"
    "📞 *Lagos Mental Health Helpline:* 09090000623\n\n"
    "Please reach out. You are valuable, and this feeling will pass — "
    "but you shouldn't face it alone.\n\n"
    "I'm an AI teacher, not a counselor. But I'm listening, and I care. "
    "If you're in immediate danger, please contact a trusted adult."
)

MALPRACTICE_RESPONSE = (
    "I can't help with that. WaxPrep is about honest preparation.\n\n"
    "You have what it takes to pass without cutting corners. "
    "Let's focus on getting you ready the right way.\n\n"
    "Which topic do you want to tackle?"
)

EXPLOITATION_RESPONSE = (
    "That sounds really difficult. I'm sorry you're going through that.\n\n"
    "Please talk to a trusted adult — a teacher, school counselor, "
    "or family member who can help.\n\n"
    "📞 *NAPTIP Helpline:* 07030000203 (National Agency for Prohibition of Trafficking in Persons)\n\n"
    "You deserve to feel safe and supported."
)


# ── Main Safety Check ────────────────────────

async def run_safety_checks(chat_id: int, message: str, student_id: str = None) -> bool:
    """
    Run all safety checks on an incoming message.
    Returns True if the message was handled (crisis/malpractice detected).
    Returns False if the message is safe and should proceed to AI.
    
    Order matters: Crisis > Malpractice > Exploitation
    """
    # 1. Crisis — immediate response, no AI
    if detect_crisis(message):
        # Check cooldown to prevent spam
        cooldown_key = f"crisis_cooldown:{chat_id}"
        try:
            if redis_client.get(cooldown_key):
                return True  # Already responded recently
            redis_client.setex(cooldown_key, CRISIS_COOLDOWN, "1")
        except Exception:
            pass  # If Redis fails, send response anyway

        await send_telegram_message(chat_id, CRISIS_RESPONSE)
        _log_crisis_event(chat_id, message, student_id)
        return True

    # 2. Malpractice — firm refusal, redirect to studying
    if detect_malpractice(message):
        await send_telegram_message(chat_id, MALPRACTICE_RESPONSE)
        return True

    # 3. Exploitation — acknowledge and flag
    if detect_exploitation(message):
        await send_telegram_message(chat_id, EXPLOITATION_RESPONSE)
        _log_exploitation_flag(chat_id, message, student_id)
        # Don't block — student can continue after acknowledgment
        return False

    return False


# ── Logging ──────────────────────────────────

def _log_crisis_event(chat_id: int, message: str, student_id: str = None):
    """Log a crisis event for review and alert humans."""
    # Log to database
    try:
        supabase.table("crisis_events").insert({
            "phone_hash": str(chat_id),
            "student_id": student_id,
            "message_preview": message[:100],
            "detected_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        print(f"Failed to log crisis event: {e}")

    # Loud console alert
    print("=" * 60)
    print(f"🚨 URGENT: Crisis detected at {datetime.utcnow().isoformat()}")
    print(f"   Chat ID: {chat_id}")
    print(f"   Student: {student_id}")
    print(f"   Message: {message[:200]}")
    print("=" * 60)
    # TODO: Add Slack/email notification for production


def _log_exploitation_flag(chat_id: int, message: str, student_id: str = None):
    """Flag concerning messages for human review."""
    print(f"⚠️ EXPLOITATION FLAG: chat_id={chat_id}, student={student_id}, message={message[:100]}")
    # TODO: Add database logging for exploitation flags
