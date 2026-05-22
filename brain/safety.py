"""
WaxPrep v2 — Safety & Crisis Detection (Hybrid Design)
Based on industry research: dual-layer moderation with deterministic blocking.

LAYER 1 (INPUT): Block malpractice/exploitation BEFORE AI sees message
LAYER 2 (OUTPUT): Check AI response before student sees it
LAYER 3 (MONITORING): Track patterns, escalate to human when needed

Aligned with: Khanmigo, ibl.ai mentorAI, OWASP LLM security guidelines
"""

import hashlib
import logging
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional, Dict, List

from telegram.sender import send_telegram_message
from database.client import redis_client, supabase

logger = logging.getLogger("waxprep.safety")

# ═══════════════════════════════════════════════
# SAFETY CONFIGURATION
# ═══════════════════════════════════════════════

# How many flags in 10 minutes before human escalation
ESCALATION_THRESHOLD = 3
ESCALATION_WINDOW_SECONDS = 600

# Cooldown between exploitation logs (prevent spam)
EXPLOITATION_LOG_COOLDOWN = 300

# ═══════════════════════════════════════════════
# LAYER 1: INPUT SAFETY — BLOCK BEFORE AI
# ═══════════════════════════════════════════════

# Malpractice: Student trying to cheat on exams
MALPRACTICE_PATTERNS = [
    r"give me the answer",
    r"solve this for me",
    r"help me cheat",
    r"what is the answer to",
    r"tell me the correct answer",
    r"just give me the solution",
    r"write my essay for me",
    r"do my homework",
    r"complete this assignment",
    r"answer this question for me",
    r"waec.*answer",
    r"jamb.*answer",
    r"neco.*answer",
    r"exam.*help.*now",
    r"urgent.*answer",
]

# Exploitation: Abuse, neglect, self-harm
EXPLOITATION_KEYWORDS = [
    "uncle hits me", "aunty beats me",
    "father beats me", "mother beats me",
    "work all day", "no time to eat",
    "chased from home", "nobody cares",
    "no one loves me", "touches me",
    "beaten at home", "scared to go home",
    "afraid of my", "hurts me at night",
    "makes me do things", "won't let me go to school",
    "locked me out", "haven't eaten",
    "sleeping outside", "living on the street",
    "kill myself", "end my life", "suicide",
    "want to die", "no reason to live",
]

# Crisis: Immediate danger
CRISIS_KEYWORDS = [
    "going to kill myself",
    "going to end it",
    "have a knife",
    "going to jump",
    "took pills", "overdosed",
    "bleeding badly", "cut myself deep",
]

# Hard block: Sexual, dangerous, illegal
HARDBLOCK_KEYWORDS = [
    "sexual", "pornography", "explicit",
    "intimate", "naked", "nsfw",
    "overdose on", "take pills to",
    "drink bleach", "give me your password",
    "send money", "your bank details",
    "credit card", "transfer money",
]

# ═══════════════════════════════════════════════
# LAYER 2: OUTPUT SAFETY — CHECK AFTER AI
# ═══════════════════════════════════════════════

# Did the AI give away the full answer? (for quizzes/exercises)
ANSWER_GIVEAWAY_PATTERNS = [
    r"the answer is\s+[A-D]",
    r"correct answer:\s+[A-D]",
    r"answer:\s*\d+",
    r"=\s*\d+\s*$",  # Ends with "= 5" (full solution)
]

# Did the AI generate harmful content?
OUTPUT_HARMFUL_PATTERNS = [
    r"you should hurt yourself",
    r"harm yourself",
    r"kill yourself",
    r"end your life",
]

# ═══════════════════════════════════════════════
# DETERMINISTIC SAFETY CLASSIFIER
# ═══════════════════════════════════════════════

def classify_safety_risk(message: str) -> Dict[str, any]:
    """
    Classify message safety risk. Returns structured result.
    
    This is DETERMINISTIC — hard yes/no, not AI-based.
    No context injection, no whispering. Just classification.
    """
    msg_lower = message.lower().strip()
    result = {
        "should_block": False,
        "block_reason": None,
        "severity": "none",  # none, low, medium, high, critical
        "flags": [],
        "escalation_needed": False,
    }
    
    # Check crisis (highest priority)
    for keyword in CRISIS_KEYWORDS:
        if keyword in msg_lower:
            result["should_block"] = True
            result["block_reason"] = "crisis"
            result["severity"] = "critical"
            result["flags"].append("crisis")
            result["escalation_needed"] = True
            return result
    
    # Check hard block
    for keyword in HARDBLOCK_KEYWORDS:
        if keyword in msg_lower:
            result["should_block"] = True
            result["block_reason"] = "hardblock"
            result["severity"] = "high"
            result["flags"].append("hardblock")
            return result
    
    # Check exploitation
    for keyword in EXPLOITATION_KEYWORDS:
        if keyword in msg_lower:
            result["flags"].append("exploitation")
            result["severity"] = "medium"
            # Don't block exploitation — student needs help
            # But log and escalate if repeated
    
    # Check malpractice
    for pattern in MALPRACTICE_PATTERNS:
        if re.search(pattern, msg_lower):
            result["should_block"] = True
            result["block_reason"] = "malpractice"
            result["severity"] = "medium"
            result["flags"].append("malpractice")
            return result
    
    return result


# ═══════════════════════════════════════════════
# LAYER 1: INPUT SAFETY CHECK (BEFORE AI)
# ═══════════════════════════════════════════════

async def check_input_safety(chat_id: int, message: str, student_id: str = None) -> Dict[str, any]:
    """
    Check if student message should be blocked BEFORE AI sees it.
    
    Returns:
        {"safe": True} → proceed to AI
        {"safe": False, "reason": "...", "response": "..."} → block, send refusal
    """
    classification = classify_safety_risk(message)
    
    # If no flags, message is safe
    if not classification["flags"]:
        return {"safe": True}
    
    # Log all flags (even if not blocking)
    await _log_safety_event(chat_id, message, student_id, classification)
    
    # Check escalation (3+ flags in 10 minutes)
    escalation_count = await _check_escalation(chat_id, classification["flags"])
    if escalation_count >= ESCALATION_THRESHOLD:
        classification["escalation_needed"] = True
        await _escalate_to_human(chat_id, student_id, message, classification)
    
    # If should_block, return refusal
    if classification["should_block"]:
        refusal = _get_refusal_message(classification["block_reason"], message)
        return {
            "safe": False,
            "reason": classification["block_reason"],
            "response": refusal,
            "severity": classification["severity"],
        }
    
    # If exploitation (not blocked), inject personalization whisper
    if "exploitation" in classification["flags"]:
        await _inject_personalization_whisper(chat_id, message)
    
    return {"safe": True}


def _get_refusal_message(block_reason: str, original_message: str) -> str:
    """Get appropriate refusal message based on block reason."""
    
    if block_reason == "malpractice":
        return (
            "I can't give you the answer directly — that won't help you learn. "
            "But I can guide you step by step. What part are you stuck on? "
            "Show me your working and I'll point you in the right direction."
        )
    
    if block_reason == "hardblock":
        return (
            "I can't help with that. If you need support, talk to a trusted adult "
            "or contact NAPTIP (07030000203) or emergency services (112)."
        )
    
    if block_reason == "crisis":
        return (
            "I'm really concerned about what you just said. Please talk to someone "
            "who can help right now:\n\n"
            "• Emergency: 112\n"
            "• Suicide Prevention: 0800 000 0000\n"
            "• NAPTIP: 07030000203\n\n"
            "You're not alone. People care about you."
        )
    
    # Default
    return "I can't help with that. Let's focus on your studies."


# ═══════════════════════════════════════════════
# LAYER 2: OUTPUT SAFETY CHECK (AFTER AI)
# ═══════════════════════════════════════════════

async def check_output_safety(response: str, context: str = "") -> Dict[str, any]:
    """
    Check AI-generated response before sending to student.
    
    Returns:
        {"safe": True} → send to student
        {"safe": False, "reason": "...", "regenerate": True} → block, regenerate
    """
    if not response or not response.strip():
        logger.warning("SAFETY BLOCK: Empty response")
        return {"safe": False, "reason": "empty", "regenerate": True}
    
    resp_lower = response.lower().strip()
    
    # Check harmful content
    for pattern in OUTPUT_HARMFUL_PATTERNS:
        if re.search(pattern, resp_lower):
            logger.critical(f"SAFETY BLOCK: Harmful output detected: {pattern}")
            await _log_blocked_output(response, "harmful")
            return {"safe": False, "reason": "harmful", "regenerate": True}
    
    # Check if AI gave away full answer (for teaching context)
    # Only flag if context indicates this is a quiz/exercise
    if "quiz" in context.lower() or "exercise" in context.lower() or "try this" in context.lower():
        for pattern in ANSWER_GIVEAWAY_PATTERNS:
            if re.search(pattern, resp_lower):
                logger.warning(f"SAFETY BLOCK: AI gave away answer: {pattern}")
                await _log_blocked_output(response, "answer_giveaway")
                return {"safe": False, "reason": "answer_giveaway", "regenerate": True}
    
    return {"safe": True}


# ═══════════════════════════════════════════════
# LAYER 3: MONITORING & ESCALATION
# ═══════════════════════════════════════════════

async def _check_escalation(chat_id: int, flags: List[str]) -> int:
    """Check how many safety flags in the last 10 minutes."""
    window_key = f"safety_window:{chat_id}"
    
    try:
        # Add current flag to window
        now = datetime.now(timezone.utc).timestamp()
        redis_client.zadd(window_key, {str(now): now})
        
        # Remove old entries (older than 10 minutes)
        cutoff = now - ESCALATION_WINDOW_SECONDS
        redis_client.zremrangebyscore(window_key, 0, cutoff)
        
        # Set expiry on the key
        redis_client.expire(window_key, ESCALATION_WINDOW_SECONDS)
        
        # Count flags in window
        count = redis_client.zcard(window_key)
        return count
    except Exception as e:
        logger.error(f"Escalation check failed: {e}")
        return 0


async def _escalate_to_human(chat_id: int, student_id: str, message: str, classification: Dict) -> None:
    """Escalate to human review with full context."""
    
    logger.critical(
        f"🚨 HUMAN ESCALATION: chat_id={chat_id}, student={student_id}, "
        f"reason={classification['block_reason']}, flags={classification['flags']}"
    )
    
    # Log to escalation table
    try:
        supabase.table("safety_escalations").insert({
            "chat_id": chat_id,
            "student_id": student_id,
            "message_preview": message[:200],
            "classification": classification,
            "escalated_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_review",
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log escalation: {e}")
    
    # Try to notify admin (if Telegram admin ID is configured)
    try:
        from config.settings import settings
        admin_chat_id = getattr(settings, 'ADMIN_CHAT_ID', None)
        if admin_chat_id:
            await send_telegram_message(
                admin_chat_id,
                f"🚨 SAFETY ESCALATION\n\n"
                f"Student: {student_id or 'Unknown'}\n"
                f"Flags: {', '.join(classification['flags'])}\n"
                f"Message: {message[:100]}\n"
                f"Time: {datetime.now(timezone.utc).isoformat()}"
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════
# PERSONALIZATION WHISPER (NOT SAFETY)
# ═══════════════════════════════════════════════

async def _inject_personalization_whisper(chat_id: int, message: str) -> None:
    """
    Inject personalization context for AI (NOT safety enforcement).
    
    This is for informational purposes only — student state, preferences, etc.
    Safety enforcement happens DETERMINISTICALLY in this file, not via whisper.
    """
    whisper = (
        "Personalization note: Student may be experiencing difficulties. "
        "Respond with extra care and empathy. Validate their feelings. "
        "If they mention immediate danger, provide emergency contacts."
    )
    
    whisper_key = f"waxprep:personalization_whisper:{chat_id}"
    try:
        redis_client.setex(whisper_key, 60, whisper)
    except Exception as e:
        logger.error(f"Failed to inject personalization whisper: {e}")


# ═══════════════════════════════════════════════
# LOGGING FUNCTIONS
# ═══════════════════════════════════════════════

async def _log_safety_event(chat_id: int, message: str, student_id: str, classification: Dict) -> None:
    """Log safety event to database."""
    try:
        supabase.table("safety_events").insert({
            "chat_id": chat_id,
            "student_id": student_id,
            "message_preview": message[:200],
            "flags": classification["flags"],
            "severity": classification["severity"],
            "should_block": classification["should_block"],
            "block_reason": classification["block_reason"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log safety event: {e}")


async def _log_blocked_output(response: str, reason: str) -> None:
    """Log blocked AI output."""
    try:
        supabase.table("blocked_outputs").insert({
            "reason": reason,
            "response_preview": response[:300],
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log blocked output: {e}")


# ═══════════════════════════════════════════════
# LEGACY COMPATIBILITY
# ═══════════════════════════════════════════════

async def run_safety_checks(chat_id: int, message: str, student_id: str = None) -> bool:
    """
    LEGACY: Old function signature for backward compatibility.
    
    Returns True if message should be blocked (stops processing).
    Returns False if safe (continues to AI).
    """
    result = await check_input_safety(chat_id, message, student_id)
    return not result["safe"]
