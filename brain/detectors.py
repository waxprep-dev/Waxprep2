"""
WaxPrep v2 — Student Signal Detectors
Detects emotional and learning signals from student messages:
confusion, fatigue, frustration, boredom, exam anxiety.

Unified pattern: Detect → Count → Log → Escalate
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("waxprep.detectors")

# ═══════════════════════════════════════════════
# CONFUSION DETECTION
# ═══════════════════════════════════════════════

# English variants
CONFUSION_PHRASES_ENGLISH = [
    "i'm confused", "i am confused", "im confused",
    "i don't understand", "i dont understand", "i do not understand",
    "i'm lost", "im lost", "i am lost",
    "this doesn't make sense", "this doesnt make sense",
    "i don't get it", "i dont get it", "i do not get it",
    "still confused", "still lost", "still don't get it",
    "not making sense", "not getting it", "not following",
    "that's too advanced", "too complex", "too complicated",
    "i'm not following", "im not following",
    "can you explain that again", "explain again",
    "i didn't get that", "i did not get that",
]

# Nigerian Pidgin variants
CONFUSION_PHRASES_PIDGIN = [
    "i no understand", "i no dey understand",
    "e no make sense", "e no clear",
    "abeg explain again", "abeg come again",
    "i no get am", "i no dey get am",
    "no dey enter my head", "e no dey enter",
    "make i no lie i no understand", "i no fit grab am",
    "wetin you dey talk", "i dey lost",
    "e confusing me", "e dey confuse me",
]

# Combined
CONFUSION_PHRASES = CONFUSION_PHRASES_ENGLISH + CONFUSION_PHRASES_PIDGIN

# Words that indicate the student is still confused after a reset attempt
POST_RESET_CONFUSION = [
    "still", "yet", "nah", "no", "nope", "not really",
    "i still", "e still", "i don't think so",
]

# Maximum attempts before parking the topic
MAX_CONFUSION_ATTEMPTS = 3


async def detect_confusion(
    message: str,
    student_id: str,
    topic: str = "unknown",
    same_topic_wrong_count: int = 0,
) -> dict:
    """
    Detect if a student is confused and determine the escalation level.
    
    Checks:
    1. Explicit confusion phrases (English + Pidgin)
    2. Post-reset confusion (student still confused after reset attempt)
    3. Same concept answered incorrectly twice in a row (implicit confusion)
    
    Args:
        message: The student's latest message
        student_id: Student database ID
        topic: Current topic being taught (e.g., "speed/velocity")
        same_topic_wrong_count: How many times they've gotten this topic wrong
    
    Returns:
        {
            "confused": bool,
            "explicit": bool,  # Student explicitly said they're confused
            "implicit": bool,  # Detected from wrong answers
            "post_reset": bool,  # Student is STILL confused after a reset
            "topic": str,
            "attempt": int,  # 1, 2, or 3
            "should_park": bool,  # True if max attempts reached
            "context_instruction": str,  # What to inject into the prompt
        }
    """
    result = {
        "confused": False,
        "explicit": False,
        "implicit": False,
        "post_reset": False,
        "topic": topic,
        "attempt": 1,
        "should_park": False,
        "context_instruction": "",
    }
    
    msg_lower = message.strip().lower()
    
    # ── Check 1: Explicit confusion phrases ──
    is_explicit = any(phrase in msg_lower for phrase in CONFUSION_PHRASES)
    
    # ── Check 2: Post-reset confusion ──
    # FIXED: Now actually used to influence behavior
    is_post_reset = is_explicit and any(
        word in msg_lower for word in POST_RESET_CONFUSION
    )
    
    # ── Check 3: Same topic wrong twice (implicit confusion) ──
    # FIXED: "I don't know" alone is NOT confusion — it's a genuine answer.
    # Only count as confusion if it's combined with other signals.
    is_implicit = same_topic_wrong_count >= 2
    
    # ── Check 4: "I don't know" + confusion indicator ──
    # "i don't know" alone is not confusion. But "i don't know what that means"
    # or "i don't know, i'm lost" IS confusion.
    is_idk_with_context = (
        "i don't know" in msg_lower or "i dont know" in msg_lower
    ) and (
        "what that is" in msg_lower or
        "what you mean" in msg_lower or
        "i'm lost" in msg_lower or
        "im lost" in msg_lower or
        "confused" in msg_lower
    )
    
    if not is_explicit and not is_implicit and not is_idk_with_context:
        return result
    
    # ── Determine attempt count ──
    attempt_count = await _get_confusion_count(student_id, topic)
    
    if is_explicit or is_idk_with_context:
        attempt_count += 1
        await _increment_confusion_count(student_id, topic, attempt_count)
    
    # FIXED: Post-reset confusion bumps the attempt count if not already counted
    if is_post_reset and not is_explicit:
        attempt_count += 1
        await _increment_confusion_count(student_id, topic, attempt_count)
    
    # ── Check if we should park the topic ──
    should_park = attempt_count > MAX_CONFUSION_ATTEMPTS
    
    # ── Build context instruction based on attempt ──
    if attempt_count == 1:
        instruction = (
            f"⚠️ CONFUSION DETECTED (Attempt 1/3). The student is confused "
            f"by your explanation of '{topic}'. You MUST: "
            f"1) Stop introducing ANY new information about '{topic}'. "
            f"2) Use a COMPLETELY different example from a DIFFERENT domain "
            f"(if you used transportation before, use cooking or market now). "
            f"3) Simplify — go back to the core idea, not the details. "
            f"4) Ask exactly ONE check question at the end. "
            f"5) Do NOT introduce the next topic until the student confirms understanding."
        )
    elif attempt_count == 2:
        instruction = (
            f"⚠️ CONFUSION DETECTED (Attempt 2/3). The student is STILL confused "
            f"about '{topic}' after your first reset. You MUST: "
            f"1) Go back to the FOUNDATION. Reference a prerequisite concept they "
            f"already know. 2) Show how '{topic}' is just like that prerequisite "
            f"plus ONE new idea. 3) Use a metaphor or analogy this time. "
            f"4) Ask a SIMPLER check question than before. "
            f"5) Do NOT move forward until they confirm."
        )
    elif attempt_count == 3:
        instruction = (
            f"⚠️ CONFUSION DETECTED (Attempt 3/3 — FINAL). The student has been "
            f"confused about '{topic}' through two reset attempts. This is your "
            f"LAST attempt before parking this topic. You MUST: "
            f"1) Tell a short STORY that embeds '{topic}' in a real scenario. "
            f"2) Make it relatable — a student, a market, a journey. "
            f"3) After the story, ask them to identify where '{topic}' appeared. "
            f"4) If they still seem confused after this, gracefully park the topic: "
            f"'No wahala. Let's park this for now and come back fresh. Sometimes "
            f"your brain needs time to process. Want to try something else?'"
        )
    else:
        # Over max — park immediately
        instruction = (
            f"⚠️ CONFUSION LIMIT REACHED. The student has been confused about "
            f"'{topic}' for {attempt_count} attempts. Do NOT explain '{topic}' "
            f"further. Instead, gracefully park the topic: 'No wahala. Let's park "
            f"this for now and come back fresh. Want to try something else?'"
        )
    
    # ── Build result ──
    result["confused"] = True
    result["explicit"] = is_explicit
    result["implicit"] = is_implicit
    result["post_reset"] = is_post_reset
    result["attempt"] = min(attempt_count, MAX_CONFUSION_ATTEMPTS)
    result["should_park"] = should_park
    result["context_instruction"] = instruction
    
    # ── Log to Supabase (non-blocking) ──
    await _log_confusion_signal(student_id, topic, attempt_count, is_explicit)
    
    return result


# ═══════════════════════════════════════════════
# REDIS COUNTERS
# ═══════════════════════════════════════════════

async def _get_confusion_count(student_id: str, topic: str) -> int:
    """Get the current confusion count for this student+topic."""
    try:
        from database.client import redis_client
        key = f"confusion:{student_id}:{topic}"
        raw = redis_client.get(key)
        if raw:
            return int(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except Exception as e:
        logger.error(f"Redis confusion count read error: {e}")
    return 0


async def _increment_confusion_count(student_id: str, topic: str, count: int) -> None:
    """Update the confusion count for this student+topic."""
    try:
        from database.client import redis_client
        key = f"confusion:{student_id}:{topic}"
        redis_client.setex(key, 7200, str(count))  # 2-hour TTL
    except Exception as e:
        logger.error(f"Redis confusion count write error: {e}")


async def reset_confusion_count(student_id: str, topic: str) -> None:
    """Reset the confusion counter when the student demonstrates understanding."""
    try:
        from database.client import redis_client
        key = f"confusion:{student_id}:{topic}"
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"Redis confusion count delete error: {e}")


# ═══════════════════════════════════════════════
# SUPABASE LOGGING
# ═══════════════════════════════════════════════

async def _log_confusion_signal(
    student_id: str,
    topic: str,
    attempt: int,
    is_explicit: bool
) -> None:
    """Log confusion event to Supabase for analytics."""
    try:
        from database.client import supabase
        from datetime import datetime, timezone
        
        supabase.table("student_signals").insert({
            "student_id": student_id,
            "signal_type": "confusion",
            "topic": topic,
            "attempt_count": attempt,
            "is_explicit": is_explicit,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log confusion signal: {e}")
