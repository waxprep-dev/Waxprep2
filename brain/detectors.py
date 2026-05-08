"""
WaxPrep v2 — Student Signal Detectors
Detects emotional and learning signals from student messages:
confusion, fatigue, frustration, boredom, exam anxiety, topic hopping.

Unified pattern: Detect → Count → Log → Escalate
"""

import logging
from typing import Optional, Dict, Any, List

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
            "explicit": bool,
            "implicit": bool,
            "post_reset": bool,
            "topic": str,
            "attempt": int,
            "should_park": bool,
            "context_instruction": str,
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
    
    is_explicit = any(phrase in msg_lower for phrase in CONFUSION_PHRASES)
    
    is_post_reset = is_explicit and any(
        word in msg_lower for word in POST_RESET_CONFUSION
    )
    
    is_implicit = same_topic_wrong_count >= 2
    
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
    
    attempt_count = await _get_confusion_count(student_id, topic)
    
    if is_explicit or is_idk_with_context:
        attempt_count += 1
        await _increment_confusion_count(student_id, topic, attempt_count)
    
    if is_post_reset and not is_explicit:
        attempt_count += 1
        await _increment_confusion_count(student_id, topic, attempt_count)
    
    should_park = attempt_count > MAX_CONFUSION_ATTEMPTS
    
    if attempt_count == 1:
        instruction = (
            f"⚠️ CONFUSION DETECTED (Attempt 1/3). The student is confused "
            f"by your explanation of '{topic}'. You MUST: "
            f"1) Stop introducing ANY new information about '{topic}'. "
            f"2) Use a COMPLETELY different example from a DIFFERENT domain. "
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
        instruction = (
            f"⚠️ CONFUSION LIMIT REACHED. The student has been confused about "
            f"'{topic}' for {attempt_count} attempts. Do NOT explain '{topic}' "
            f"further. Instead, gracefully park the topic: 'No wahala. Let's park "
            f"this for now and come back fresh. Want to try something else?'"
        )
    
    result["confused"] = True
    result["explicit"] = is_explicit
    result["implicit"] = is_implicit
    result["post_reset"] = is_post_reset
    result["attempt"] = min(attempt_count, MAX_CONFUSION_ATTEMPTS)
    result["should_park"] = should_park
    result["context_instruction"] = instruction
    
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
        redis_client.setex(key, 7200, str(count))
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


# ═══════════════════════════════════════════════
# TOPIC COHERENCE DETECTION (NEW)
# ═══════════════════════════════════════════════

# Topic keywords for extraction
TOPIC_KEYWORDS = {
    "physics": {
        "acceleration": ["acceleration", "accelerating", "accelerate"],
        "velocity": ["velocity", "speed", "fast", "moving"],
        "force": ["force", "push", "pull", "newton"],
        "energy": ["energy", "kinetic", "potential", "thermal", "heat"],
        "electricity": ["electricity", "current", "voltage", "resistance", "circuit"],
        "momentum": ["momentum", "collision", "impulse"],
        "motion": ["motion", "movement", "linear", "projectile"],
        "waves": ["wave", "sound", "light wave", "frequency"],
        "gravity": ["gravity", "gravitational", "weight"],
    },
    "chemistry": {
        "atomic_structure": ["atom", "atomic", "proton", "neutron", "electron", "nucleus"],
        "periodic_table": ["periodic table", "element", "group", "period", "metal"],
        "bonding": ["bond", "ionic", "covalent", "metallic", "sigma", "pi"],
        "acids_bases": ["acid", "base", "ph", "alkaline", "neutralization"],
        "organic": ["organic", "carbon", "hydrocarbon", "alkane", "alkene"],
        "electrolysis": ["electrolysis", "electrolyte", "anode", "cathode"],
        "stoichiometry": ["mole", "molar", "stoichiometry", "equation"],
    },
    "biology": {
        "cell": ["cell", "organelle", "mitochondria", "nucleus", "membrane"],
        "photosynthesis": ["photosynthesis", "chlorophyll", "light reaction"],
        "respiration": ["respiration", "aerobic", "anaerobic", "glycolysis"],
        "genetics": ["genetics", "dna", "gene", "chromosome", "heredity"],
        "ecology": ["ecology", "ecosystem", "habitat", "food chain"],
        "osmosis": ["osmosis", "diffusion", "semi-permeable"],
        "enzymes": ["enzyme", "catalyst", "substrate", "active site"],
    },
    "mathematics": {
        "algebra": ["algebra", "equation", "variable", "solve"],
        "quadratic": ["quadratic", "parabola", "discriminant"],
        "trigonometry": ["trig", "sine", "cosine", "tangent", "sohcahtoa"],
        "calculus": ["calculus", "derivative", "integral", "differentiation"],
        "statistics": ["statistics", "probability", "mean", "median", "mode"],
        "geometry": ["geometry", "triangle", "circle", "angle", "pythagoras"],
    },
}

TOPIC_COMPLETION_SIGNALS = [
    "i get it", "i understand", "that makes sense", "i'm ready to move on",
    "next topic", "let's switch", "i got it", "i see", "that's clear",
    "move on", "continue", "go ahead", "what's next", "i know this now",
    "i've got it", "i understand now", "it's clear", "ready for the next",
]


def extract_topics_from_history(conversation_history: list, last_n: int = 10) -> List[str]:
    """
    Extract recent topics from conversation history.
    Returns list of unique topic strings like ["physics:acceleration", "biology:photosynthesis"].
    """
    if not conversation_history:
        return []
    
    recent = conversation_history[-last_n:]
    topics_found = []
    
    for msg in recent:
        content = msg.get("content", "").lower()
        
        for subject, topics in TOPIC_KEYWORDS.items():
            for topic_name, keywords in topics.items():
                if any(kw in content for kw in keywords):
                    topic_key = f"{subject}:{topic_name}"
                    if topic_key not in topics_found:
                        topics_found.append(topic_key)
    
    return topics_found


def detect_topic_completion(topic: str, conversation_history: list) -> bool:
    """Check if a topic was completed based on student signals."""
    if not conversation_history:
        return False
    
    recent_user_msgs = [
        m for m in conversation_history[-5:]
        if m.get("role") == "user"
    ]
    
    for msg in recent_user_msgs:
        content = msg.get("content", "").lower()
        if any(signal in content for signal in TOPIC_COMPLETION_SIGNALS):
            return True
    
    recent_assistant_msgs = [
        m for m in conversation_history[-5:]
        if m.get("role") == "assistant"
    ]
    praise_phrases = ["exactly", "you've got it", "well done", "correct"]
    for msg in recent_assistant_msgs:
        content = msg.get("content", "").lower()
        if any(phrase in content for phrase in praise_phrases):
            return True
    
    return False


def detect_topic_hopping(
    conversation_history: list,
    current_message: str = "",
    student_id: str = "",
) -> dict:
    """
    Detect if student is rapidly switching topics without completing any.
    
    Returns:
        {
            "hopping": bool,
            "topics": list of recent incomplete topic keys,
            "count": int,
            "stage": "gentle" or "firm" or "accept",
            "context_instruction": str or empty
        }
    """
    result = {
        "hopping": False,
        "topics": [],
        "count": 0,
        "stage": "",
        "context_instruction": "",
    }
    
    if not conversation_history:
        return result
    
    all_topics = extract_topics_from_history(conversation_history, last_n=10)
    
    if len(all_topics) < 3:
        return result
    
    incomplete_topics = [
        t for t in all_topics
        if not detect_topic_completion(t, conversation_history)
    ]
    
    if len(incomplete_topics) < 3:
        return result
    
    result["hopping"] = True
    result["topics"] = incomplete_topics
    result["count"] = len(incomplete_topics)
    
    if len(incomplete_topics) <= 4:
        result["stage"] = "gentle"
        topic_names = [t.split(":")[1].replace("_", " ") for t in incomplete_topics]
        result["context_instruction"] = (
            f"⚠️ TOPIC HOPPING DETECTED (Gentle). The student has discussed "
            f"{', '.join(topic_names)} without completing any. "
            f"Before starting another new topic, gently check in: "
            f"'We've touched on a few things. Want to pick one and go deep?' "
            f"Don't block the switch — just offer focus. Keep it warm."
        )
    elif len(incomplete_topics) <= 6:
        result["stage"] = "firm"
        topic_names = [t.split(":")[1].replace("_", " ") for t in incomplete_topics]
        result["context_instruction"] = (
            f"⚠️ TOPIC HOPPING DETECTED (Firm). The student has discussed "
            f"{len(incomplete_topics)} topics without completing any. "
            f"Make a deal: 'That's {len(incomplete_topics)} topics without finishing any. "
            f"Let's pick ONE and commit for 10 minutes. After that, we can switch. Deal?' "
            f"Be warm but firm. They need structure."
        )
    else:
        result["stage"] = "accept"
        result["context_instruction"] = (
            f"⚠️ TOPIC HOPPING DETECTED (Accept). The student has discussed "
            f"{len(incomplete_topics)} topics without completing any. "
            f"Accept exploration mode: 'Alright, you're in exploration mode today. "
            f"That's fine. When you're ready to focus on one topic, I'm here.' "
            f"Don't fight it. Adapt to their style."
        )
    
    return result
