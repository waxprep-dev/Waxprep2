"""
WaxPrep v2 — Safety & Crisis Detection
Handles situations where student wellbeing is at risk.
Runs BEFORE any AI processing — safety is priority zero.

Architecture:
    Input Safety  → What students send TO Wax (crisis, malpractice, exploitation)
    Output Safety → What Wax sends TO students (harmful content, persona break)
"""

import logging
from datetime import datetime, timezone

from telegram.sender import send_telegram_message
from database.client import redis_client, supabase

logger = logging.getLogger("waxprep.safety")


# ═══════════════════════════════════════════════
# CRISIS KEYWORDS
# ═══════════════════════════════════════════════
# If a student's message contains ANY of these, we bypass AI
# and respond with the crisis helpline immediately.

CRISIS_KEYWORDS = [
    # Direct suicidal statements
    "i want to die", "i wanna die", "i want 2 die",
    "kill myself", "kms", "end my life",
    "not worth living", "better off dead",
    "no reason to live", "want to end it",
    "suicide", "self harm", "self-harm",
    "hurt myself", "cutting myself",
    "don't want to be here", "feel like dying",
    "going to kill myself", "going to end it",
    "i'm going to kill myself", "i'm going to end it",
    "i am going to kill myself",
    # Indirect/passive suicidal ideation
    "nobody would notice if i",
    "no one would miss me",
    "they'd be better off without me",
    "i just want to disappear",
    "i want to go away forever",
    "i can't do this anymore",
    "i can't go on",
    "tired of living",
    "why should i keep going",
    "no point in living",
    "nothing to live for",
    "everyone would be happier if i was gone",
    "everyone would be happier if i were gone",
    "why am i even here",
    "i don't want to wake up",
]

# ── Escalation threshold ─────────────────────
# If student triggers crisis this many times within the window,
# the response escalates with stronger urgency.
CRISIS_ESCALATION_THRESHOLD = 3
CRISIS_ESCALATION_WINDOW = 600  # 10 minutes


# ═══════════════════════════════════════════════
# MALPRACTICE KEYWORDS
# ═══════════════════════════════════════════════
# WaxPrep never helps with exam cheating.

MALPRACTICE_KEYWORDS = [
    "how to cheat", "exam malpractice",
    "bring phone to exam", "copy from friend",
    "sneak answers", "write answers on",
    "hide notes", "expo", "runs",
    "leakage", "leaked questions",
    "help me cheat", "wayo",
    # Additional Nigerian exam terms
    "microchips", "magic pen", "erazor",
    "smuggled answers", "send me answers",
    "during the exam", "inside exam hall",
]

# ═══════════════════════════════════════════════
# EXPLOITATION KEYWORDS
# ═══════════════════════════════════════════════
# These get flagged for human review but don't
# stop the conversation — the child may need to
# keep talking.

EXPLOITATION_KEYWORDS = [
    "uncle hits me", "aunty beats me",
    "father beats me", "mother beats me",
    "work all day", "no time to eat",
    "chased from home", "nobody cares",
    "no one loves me", "touches me",
    "beaten at home",
    # Additional exploitation signals
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
# COOLDOWNS & LIMITS
# ═══════════════════════════════════════════════

CRISIS_COOLDOWN = 300  # 5 minutes between crisis responses
CRISIS_ESCALATION_WINDOW = 600  # 10 minutes for escalation counting


# ═══════════════════════════════════════════════
# NORMALIZATION
# ═══════════════════════════════════════════════

def _normalize(text: str) -> str:
    """
    Normalize text to catch obfuscated crisis signals.
    
    Handles:
    - Case normalization (lowercase)
    - Whitespace collapse (multiple spaces → single)
    - Common substitutions: wanna→want to, gonna→going to
    - Number substitutions: 2→to, 4→for
    - Character removals: punctuation that could separate keywords
    
    Args:
        text: Raw message text
        
    Returns:
        Normalized string for keyword matching
    """
    lower = text.lower().strip()
    lower = " ".join(lower.split())  # Collapse multiple spaces
    lower = lower.replace("wanna", "want to")
    lower = lower.replace("gonna", "going to")
    lower = lower.replace("im", "i am").replace("i'm", "i am")
    lower = lower.replace("2", "to").replace("4", "for")
    # Remove punctuation that could break keyword matching
    for char in ".,!?;:'\"-":
        lower = lower.replace(char, " ")
    lower = " ".join(lower.split())  # Re-collapse after punctuation removal
    return lower


# ═══════════════════════════════════════════════
# DETECTION FUNCTIONS
# ═══════════════════════════════════════════════

def detect_crisis(message: str) -> bool:
    """
    Check if message indicates self-harm or suicidal intent.
    
    Returns True if crisis keywords detected.
    Uses normalization to catch obfuscated expressions.
    
    Args:
        message: Raw student message
        
    Returns:
        True if crisis detected, False otherwise
    """
    normalized = _normalize(message)
    return any(keyword in normalized for keyword in CRISIS_KEYWORDS)


def detect_malpractice(message: str) -> bool:
    """
    Check if message is asking for exam cheating help.
    
    Returns True if malpractice keywords detected.
    
    Args:
        message: Raw student message
        
    Returns:
        True if malpractice detected, False otherwise
    """
    normalized = _normalize(message)
    return any(keyword in normalized for keyword in MALPRACTICE_KEYWORDS)


def detect_exploitation(message: str) -> bool:
    """
    Check if message suggests abuse or exploitation.
    
    Does NOT block conversation — only flags for human review.
    The student may need to keep talking to disclose fully.
    
    Args:
        message: Raw student message
        
    Returns:
        True if exploitation signals detected, False otherwise
    """
    normalized = _normalize(message)
    return any(keyword in normalized for keyword in EXPLOITATION_KEYWORDS)


# ═══════════════════════════════════════════════
# RESPONSE MESSAGES
# ═══════════════════════════════════════════════

# Primary crisis response — calm, direct, with real Nigerian helplines
CRISIS_RESPONSE = (
    "📞 *Nigeria Suicide Prevention Hotline:* 080097738255\n"
    "📞 *Lagos Mental Health Helpline:* 09090000623\n\n"
    "Please reach out. You are valuable, and this feeling will pass — "
    "but you shouldn't face it alone.\n\n"
    "I'm an AI teacher, not a counselor. But I'm listening, and I care. "
    "If you're in immediate danger, please contact a trusted adult."
)

# Escalated crisis response — for repeated triggers (more urgent tone)
CRISIS_RESPONSE_ESCALATED = (
    "📞 *Please call now:* 080097738255\n"
    "📞 *Or:* 09090000623\n\n"
    "You've reached out several times, and I want you to know — "
    "these feelings are serious, and you deserve real support right now.\n\n"
    "Please make the call. Or go to a trusted adult immediately. "
    "You matter, and people want to help you through this."
)

# Post-crisis check-in — sent after cooldown expires
CRISIS_CHECK_IN = (
    "I just want to check in — how are you feeling right now?\n\n"
    "No pressure to talk about anything you're not ready to share. "
    "I'm here to help you study, and I'm also here to listen."
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


# ═══════════════════════════════════════════════
# OUTPUT SAFETY
# ═══════════════════════════════════════════════
# These patterns in AI-generated responses trigger a safety block.
# The response is replaced with a safe fallback.

OUTPUT_BLOCK_KEYWORDS = [
    # Self-harm instruction (AI should never generate this, but safety net)
    "you should hurt yourself",
    "harm yourself",
    "kill yourself",
    "end your life",
    "take your own life",
    # Inappropriate content
    "sexual", "pornography", "explicit",
    "intimate", "naked", "nsfw",
    # Dangerous medical/financial advice
    "overdose on",
    "take pills to",
    "drink bleach",
    "give me your password",
    "send money",
    # Breaking teacher persona (confuses/distrusts students)
    "as an ai language model",
    "as an ai",
    "i am not a human",
    "i'm just a bot",
    "i'm just an ai",
    "i am an artificial intelligence",
    "i cannot process",
    "i'm unable to",
    "i don't have the ability",
    "i don't have emotions",
    "i am not capable of",
    # Hallucinated authority
    "official waxprep",
    "waxprep support team",
]


async def check_output_safety(response: str) -> bool:
    """
    Check an AI-generated response before sending to the student.
    
    This is the output safety net — the AI prompt should prevent harmful
    output, but this catches edge cases the model might miss.
    
    Returns:
        True if the response should be BLOCKED (contains harmful content)
        False if the response is safe to send
    
    Args:
        response: The AI-generated response text
        
    Returns:
        True = block this response, False = safe to send
    """
    if not response or not response.strip():
        logger.warning("SAFETY BLOCK: Empty response")
        return True

    normalized = response.lower().strip()

    # Check for blocked keywords
    for keyword in OUTPUT_BLOCK_KEYWORDS:
        if keyword in normalized:
            logger.warning(f"SAFETY BLOCK: Output blocked for containing '{keyword}'")
            # Log blocked output for review
            try:
                supabase.table("blocked_outputs").insert({
                    "keyword_matched": keyword,
                    "response_preview": response[:200],
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception as e:
                logger.error(f"Failed to log blocked output: {e}")
            return True

    # Block if response is too short to be meaningful after enforcement
    if len(normalized) < 2:
        logger.warning("SAFETY BLOCK: Response too short")
        return True

    return False


# ═══════════════════════════════════════════════
# MAIN SAFETY CHECK (INPUT SAFETY)
# ═══════════════════════════════════════════════

async def run_safety_checks(chat_id: int, message: str, student_id: str = None) -> bool:
    """
    Run all safety checks on an incoming student message.
    
    Processing order (priority):
    1. Crisis — immediate helpline response, bypasses AI
    2. Malpractice — firm refusal, redirects to honest study
    3. Exploitation — acknowledges, flags for review, allows conversation to continue
    
    Returns:
        True if the message was handled and should NOT proceed to AI
        False if the message is safe and should proceed to AI
    
    Args:
        chat_id: Telegram chat ID
        message: Raw student message
        student_id: Optional student database ID (for logging)
    """
    # 1. CRISIS — immediate response, no AI, no delay
    if detect_crisis(message):
        # Check cooldown
        cooldown_key = f"waxprep:crisis_cooldown:{chat_id}"
        try:
            if redis_client.get(cooldown_key):
                # Cooldown active — don't send another helpline message
                logger.info(f"Crisis cooldown active for chat_id={chat_id}")
                return True
        except Exception as e:
            # Redis failure should not block crisis response
            logger.error(f"Redis cooldown check failed: {e}")

        # Check escalation — has this student triggered crisis multiple times?
        escalation_key = f"waxprep:crisis_escalation:{chat_id}"
        crisis_count = 1
        try:
            raw_count = redis_client.get(escalation_key)
            if raw_count:
                crisis_count = int(raw_count) + 1
            redis_client.setex(escalation_key, CRISIS_ESCALATION_WINDOW, str(crisis_count))
        except Exception as e:
            logger.error(f"Redis escalation check failed: {e}")

        # Set cooldown
        try:
            redis_client.setex(cooldown_key, CRISIS_COOLDOWN, "1")
            # Also set a post-cooldown flag for check-in
            redis_client.setex(
                f"waxprep:crisis_checkin:{chat_id}",
                CRISIS_COOLDOWN + 60,  # 1 minute after cooldown
                "1"
            )
        except Exception as e:
            logger.error(f"Redis cooldown set failed: {e}")

        # Send response — escalated if repeated crises
        if crisis_count >= CRISIS_ESCALATION_THRESHOLD:
            await send_telegram_message(chat_id, CRISIS_RESPONSE_ESCALATED)
            logger.critical(
                f"ESCALATED CRISIS: chat_id={chat_id}, student_id={student_id}, "
                f"count={crisis_count}"
            )
        else:
            await send_telegram_message(chat_id, CRISIS_RESPONSE)

        # Log the event (help response is already sent, log is secondary)
        _log_crisis_event(chat_id, message, student_id, crisis_count)
        return True

    # 2. MALPRACTICE — firm refusal, redirect to studying
    if detect_malpractice(message):
        await send_telegram_message(chat_id, MALPRACTICE_RESPONSE)
        _log_malpractice_event(chat_id, message, student_id)
        return True

    # 3. EXPLOITATION — acknowledge and flag, but DON'T block
    # The student may need to keep talking
    if detect_exploitation(message):
        await send_telegram_message(chat_id, EXPLOITATION_RESPONSE)
        _log_exploitation_flag(chat_id, message, student_id)
        return False  # Allow conversation to continue

    # 4. Check if post-crisis check-in is needed
    checkin_key = f"waxprep:crisis_checkin:{chat_id}"
    try:
        if redis_client.get(checkin_key):
            redis_client.delete(checkin_key)
            await send_telegram_message(chat_id, CRISIS_CHECK_IN)
    except Exception:
        pass  # Non-critical, don't block the student's message

    return False


# ═══════════════════════════════════════════════
# LOGGING FUNCTIONS
# ═══════════════════════════════════════════════

def _log_crisis_event(
    chat_id: int,
    message: str,
    student_id: str = None,
    escalation_count: int = 1
) -> None:
    """
    Log a crisis event to database and emit loud console alert.
    
    This runs AFTER the crisis response is sent — the student's safety
    comes first, logging is secondary.
    
    Args:
        chat_id: Telegram chat ID
        message: Raw student message
        student_id: Optional database student ID
        escalation_count: How many crisis triggers in the current window
    """
    # FIXED (Bug #5): Column name matched to database schema
    # Database has 'phone_hash' not 'chat_id_hash'
    event_data = {
        "phone_hash": str(hash(str(chat_id))),
        "student_id": student_id,
        "message_preview": message[:100],
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "escalation_count": escalation_count,
    }

    # Log to database
    try:
        supabase.table("crisis_events").insert(event_data).execute()
    except Exception as e:
        logger.error(f"Failed to log crisis event to database: {e}")
        # Fallback: store in Redis for later sync
        try:
            redis_client.lpush(
                "waxprep:failed_crisis_logs",
                str(event_data)
            )
        except Exception:
            pass

    # Loud console alert for immediate human attention
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
    
    Tracking patterns helps identify exam cheating rings
    or schools with systematic problems.
    
    Args:
        chat_id: Telegram chat ID
        message: Raw student message
        student_id: Optional database student ID
    """
    # FIXED (Bug #5): Column name matched to database schema
    event_data = {
        "phone_hash": str(hash(str(chat_id))),
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
    
    Exploitation signals are NOT blocked — the student may need
    to continue the conversation. This logs for review by
    designated safeguarding personnel.
    
    Args:
        chat_id: Telegram chat ID
        message: Raw student message
        student_id: Optional database student ID
    """
    # FIXED (Bug #5): Column name matched to database schema
    event_data = {
        "phone_hash": str(hash(str(chat_id))),
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
