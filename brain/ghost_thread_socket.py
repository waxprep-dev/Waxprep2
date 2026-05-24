"""
brain/ghost_thread_socket.py — Ghost Thread Protocol v3: Temporal Dialectics

The Ghost Thread is not a reminder. It is a resurrection of the student's
own thinking, given voice, and placed in dialectical tension with their
present self.

Architecture:
    1. ANCHOR MINER       → Mine conversations for "haunted moments"
    2. GHOST STUDENT FORGE → Create temporal persona of student at anchor
    3. TEMPORAL SCHISM    → Reconstruct past debate + present challenge
    4. DELIVERY ORCHESTRATOR → Cron + Redis dual delivery
    5. RESURRECTION ENGINE → Handle student replies
    6. EPISTEMIC TIME MACHINE → Record temporal growth

Connections:
    - conversations table (message history)
    - brain/dialectical_socket.py (dissonance detection, triad orchestration)
    - brain/relational_intimacy.py (PIG gating)
    - brain/siapm_memory.py (Working Memory persistence)
    - Redis (scheduling, state tracking, TTL management)
    - Supabase ghost_threads table (persistence)

CHANGELOG:
    - 2026-05-24: Created for P1-B Ghost Thread Protocol
"""

import json
import logging
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.ghost_thread")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Anchor types we hunt for
ANCHOR_TYPES = [
    "unresolved_tension",
    "breakthrough_seed",
    "emotional_peak",
    "teacher_conflict",
    "abandoned_problem",
    "confidence_collapse",
    "hypothesis_untested",
]

# Thermal thresholds for anchor qualification
MIN_ANCHOR_THERMAL = 60  # Must be emotionally significant
MAX_GHOST_FREQUENCY_HOURS = 48  # Don't ghost same student more than every 48h

# Cognitive decay curve parameters
BASE_DELAY_HOURS = 24
CONFUSION_MULTIPLIER_MAX = 2.0
RANDOMNESS_FACTOR_RANGE = (0.8, 1.2)

# Receptivity gate parameters
MIN_QUIET_HOURS = 2  # Student hasn't messaged in last 2 hours
SLEEP_START_HOUR = 23
SLEEP_END_HOUR = 6
EXAM_DETECTION_THRESHOLD = 5  # 5+ quizzes in 24h = exam period

# Redis keys
GHOST_SCHEDULE_ZSET = "ghost:schedule"  # Sorted set: score = timestamp, member = ghost_id
GHOST_STATE_PREFIX = "ghost:state:{ghost_id}"
STUDENT_LAST_GHOST_KEY = "ghost:last_sent:{student_id}"
STUDENT_GHOST_PREFERENCE = "ghost:preference:{student_id}"  # engaged|neutral|dismissed

# ═══════════════════════════════════════════════════════════════════════
# 1. ANCHOR MINER
# ═══════════════════════════════════════════════════════════════════════

async def mine_anchors(
    student_id: str,
    lookback_hours: int = 168,  # 7 days
    max_anchors: int = 5,
) -> List[Dict[str, Any]]:
    """
    Scan conversations table for moments worth haunting.

    An anchor is a message (or message pair) with:
    - High thermal/emotional significance
    - Unresolved outcome (confusion, partial understanding, tension)
    - Not already ghosted
    - Not too recent (at least 6 hours old)

    Returns list of anchor dicts, sorted by haunting potential (desc).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    min_age = datetime.now(timezone.utc) - timedelta(hours=6)

    try:
        # Fetch recent conversations for this student
        result = (
            supabase.table("conversations")
            .select("*")
            .eq("student_id", student_id)
            .gte("created_at", cutoff.isoformat())
            .lte("created_at", min_age.isoformat())  # Not too recent
            .order("created_at", desc=False)  # Oldest first for context
            .execute()
        )
        messages = result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch conversations for anchor mining: {e}")
        return []

    if len(messages) < 3:
        return []  # Need some history to find patterns

    anchors = []

    # Scan for patterns
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue  # Only student messages can be anchors

        content = msg.get("content", "")
        msg_id = msg.get("id")
        created_at = msg.get("created_at")
        metadata = msg.get("message_metadata", {}) or {}

        # Skip if already ghosted
        if await _is_already_ghosted(msg_id):
            continue

        # Calculate thermal score from metadata or infer
        thermal_score = metadata.get("thermal_score", 0)
        if not thermal_score:
            thermal_score = _infer_thermal_score(content, metadata)

        if thermal_score < MIN_ANCHOR_THERMAL:
            continue

        # Detect anchor type
        anchor_type = _classify_anchor_type(content, metadata, messages, i)
        if not anchor_type:
            continue

        # Build anchor
        anchor = {
            "conversation_id": msg_id,
            "student_id": student_id,
            "anchor_type": anchor_type,
            "content": content,
            "thermal_score": thermal_score,
            "created_at": created_at,
            "metadata": metadata,
            # Context: messages before and after for ghost reconstruction
            "context_before": _extract_context(messages, i, before=3, after=2),
        }

        anchors.append(anchor)

    # Sort by thermal score descending, take top N
    anchors.sort(key=lambda x: x["thermal_score"], reverse=True)
    return anchors[:max_anchors]


def _infer_thermal_score(content: str, metadata: Dict[str, Any]) -> int:
    """
    Infer thermal score from message content when not pre-calculated.
    Uses keyword heuristics + length + punctuation intensity.
    """
    score = 30  # Base warmth

    # Emotional intensity markers
    heat_markers = [
        "confused", "don't get", "don't understand", "lost", "stuck",
        "frustrated", "angry", "annoyed", "tired", "giving up",
        "aha", "oh wait", "now i see", "eureka", "finally",
        "my teacher said", "in school", "textbook says", "but you said",
        "wrong", "correct", "mistake", "error",
    ]
    for marker in heat_markers:
        if marker in content.lower():
            score += 15

    # Exclamation marks = emotional charge
    score += content.count("!") * 5

    # ALL CAPS = high arousal
    caps_ratio = sum(1 for c in content if c.isupper()) / max(len(content), 1)
    if caps_ratio > 0.3:
        score += 20

    # Question marks = cognitive engagement (good for ghosts)
    score += content.count("?") * 3

    # Length: very short or very long can indicate emotional state
    word_count = len(content.split())
    if word_count < 5:
        score += 10  # Frustration/brevity
    elif word_count > 50:
        score += 5  # Deep engagement

    # Cap at 100
    return min(score, 100)


def _classify_anchor_type(
    content: str,
    metadata: Dict[str, Any],
    messages: List[Dict[str, Any]],
    index: int,
) -> Optional[str]:
    """
    Classify what kind of haunted moment this is.
    Returns anchor type string or None if not anchor-worthy.
    """
    content_lower = content.lower()
    meta_intent = metadata.get("intent", "")
    meta_emotion = metadata.get("emotion", "")

    # Teacher conflict pattern
    teacher_patterns = [
        r"my teacher said", r"in school", r"textbook says",
        r"but you said", r"you said.*but.*teacher",
    ]
    for pattern in teacher_patterns:
        if pattern.replace(r"\b", "") in content_lower:
            return "teacher_conflict"

    # Confidence collapse
    collapse_signals = ["i don't get it", "i'm lost", "this is too hard",
                       "i give up", "i can't do this", "never mind"]
    for signal in collapse_signals:
        if signal in content_lower:
            return "confidence_collapse"

    # Breakthrough seed (almost got it)
    breakthrough_signals = ["almost", "nearly", "so close", "wait maybe",
                           "i think i see", "beginning to understand"]
    for signal in breakthrough_signals:
        if signal in content_lower:
            return "breakthrough_seed"

    # Hypothesis untested (student proposed something, never verified)
    if "?" in content and meta_intent in ["question", "hypothesis"]:
        # Check if next assistant message confirmed or left hanging
        if index + 1 < len(messages):
            next_msg = messages[index + 1]
            if next_msg.get("role") == "assistant":
                next_content = next_msg.get("content", "").lower()
                if "let's check" in next_content or "try this" in next_content:
                    return "hypothesis_untested"

    # Emotional peak
    if meta_emotion in ["frustrated", "excited", "anxious", "relieved"]:
        return "emotional_peak"

    # Abandoned problem (Working Memory would track this, but we infer)
    if any(w in content_lower for w in ["solve", "find", "calculate", "factor"]):
        # Check if student returned to it
        subsequent = messages[index+1:index+5]
        student_after = [m for m in subsequent if m.get("role") == "user"]
        if not student_after:
            return "abandoned_problem"

    # Unresolved tension (default for high-thermal, unclassified)
    if metadata.get("dissonance_score", 0) > 0.5:
        return "unresolved_tension"

    return None


def _extract_context(
    messages: List[Dict[str, Any]],
    index: int,
    before: int = 3,
    after: int = 2,
) -> List[Dict[str, Any]]:
    """Extract surrounding messages for ghost reconstruction."""
    start = max(0, index - before)
    end = min(len(messages), index + after + 1)
    return [
        {
            "role": m.get("role"),
            "content": m.get("content", "")[:200],  # Truncate for context
            "created_at": m.get("created_at"),
        }
        for m in messages[start:end]
    ]


async def _is_already_ghosted(conversation_id: str) -> bool:
    """Check if this conversation message has already been used as an anchor."""
    try:
        result = (
            supabase.table("ghost_threads")
            .select("id")
            .eq("anchor_conversation_id", conversation_id)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.warning(f"Could not check ghost status: {e}")
        return False  # Assume not ghosted if we can't check


# ═══════════════════════════════════════════════════════════════════════
# 2. GHOST STUDENT FORGE
# ═══════════════════════════════════════════════════════════════════════

async def forge_ghost_student(
    anchor: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """
    Create a temporal persona of the student AS THEY WERE at the anchor moment.

    This persona captures:
    - Their epistemic stance (what they believed)
    - Their emotional state (how they felt)
    - Their linguistic register (how they spoke)
    - Their confidence level (certain, confused, defiant)

    The Ghost Student is NOT the real student. It is a reconstruction
    that speaks in first person from the past.
    """
    content = anchor["content"]
    metadata = anchor.get("metadata", {})
    context = anchor.get("context_before", [])

    # Infer past emotional state
    emotion = metadata.get("emotion", _infer_emotion_from_content(content))

    # Infer confidence
    confidence = _infer_confidence(content, emotion)

    # Detect linguistic register
    register = _detect_register(content)

    # Build persona
    persona = {
        "timestamp": anchor["created_at"],
        "emotion": emotion,
        "confidence": confidence,
        "register": register,
        "exact_quote": content[:300],  # The anchor quote itself
        "position_summary": _summarize_position(content, context),
        "thermal_at_moment": anchor["thermal_score"],
        "days_ago": _days_since(anchor["created_at"]),
    }

    return persona


def _infer_emotion_from_content(content: str) -> str:
    """Infer emotional state from message text."""
    content_lower = content.lower()
    if any(w in content_lower for w in ["angry", "annoyed", "frustrated", "mad"]):
        return "frustrated"
    if any(w in content_lower for w in ["confused", "lost", "don't get", "huh"]):
        return "confused"
    if any(w in content_lower for w in ["happy", "excited", "yes!", "got it"]):
        return "excited"
    if any(w in content_lower for w in ["tired", "sleepy", "done", "exhausted"]):
        return "tired"
    if any(w in content_lower for w in ["scared", "anxious", "worried", "nervous"]):
        return "anxious"
    return "neutral"


def _infer_confidence(content: str, emotion: str) -> float:
    """Infer confidence level (0.0 = certain wrong, 1.0 = certain right)."""
    content_lower = content.lower()

    # High confidence markers
    if any(w in content_lower for w in ["definitely", "sure", "certain", "know"]):
        return 0.8
    if any(w in content_lower for w in ["i think", "maybe", "perhaps", "guess"]):
        return 0.5
    if any(w in content_lower for w in ["don't know", "no idea", "clueless"]):
        return 0.2

    # Emotion-adjusted
    if emotion == "confused":
        return 0.3
    if emotion == "frustrated":
        return 0.4
    if emotion == "excited":
        return 0.9

    return 0.5


def _detect_register(content: str) -> str:
    """
    Detect if student was speaking in formal English, Pidgin, or mixed.
    Used to make Ghost Student speak in their own voice.
    """
    content_lower = content.lower()
    pidgin_markers = ["dey", "wetin", "na", "go", "don", "wan", "sabi",
                     "abi", "o", "sha", "kpele", "how far", "naim"]
    pidgin_count = sum(1 for m in pidgin_markers if m in content_lower)
    word_count = len(content.split())

    if word_count == 0:
        return "formal"

    pidgin_ratio = pidgin_count / word_count
    if pidgin_ratio > 0.1:
        return "pidgin"
    if pidgin_ratio > 0.03:
        return "mixed"
    return "formal"


def _summarize_position(content: str, context: List[Dict[str, Any]]) -> str:
    """
    Summarize what the student believed at the anchor moment.
    This becomes the Ghost Student's position in the temporal debate.
    """
    # Simple extraction: first sentence + any claim markers
    sentences = content.split(".")
    first_sentence = sentences[0].strip() if sentences else content

    # If it's a question, reframe as belief
    if "?" in first_sentence:
        return f"Was unsure about: {first_sentence.replace('?', '')}"

    return f"Believed: {first_sentence[:150]}"


def _days_since(timestamp_str: str) -> int:
    """Calculate days since a timestamp."""
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return max(delta.days, 1)
    except Exception:
        return 1


# ═══════════════════════════════════════════════════════════════════════
# 3. TEMPORAL SCHISM — Reconstruct the Debate
# ═══════════════════════════════════════════════════════════════════════

async def forge_temporal_schism(
    anchor: Dict[str, Any],
    ghost_student: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """
    Build the temporal schism: Past Self vs Present Challenge.

    This creates the content for the Ghost Thread message.
    It uses the Dialectical Engine's Register Weaver pattern but
    applies it across TIME instead of across VOICES.

    Format:
        🔮 From your notebook, N days ago...
        [Ghost Student speaks in first person from past]
        [Present Challenge: what has changed since?]
        [Question that bridges past and present]
    """
    days_ago = ghost_student["days_ago"]
    register = ghost_student["register"]
    quote = ghost_student["exact_quote"]
    position = ghost_student["position_summary"]
    emotion = ghost_student["emotion"]
    confidence = ghost_student["confidence"]

    # Build the schism content based on anchor type
    schism_builders = {
        "teacher_conflict": _build_teacher_conflict_schism,
        "breakthrough_seed": _build_breakthrough_schism,
        "confidence_collapse": _build_confidence_schism,
        "emotional_peak": _build_emotional_schism,
        "abandoned_problem": _build_abandoned_schism,
        "hypothesis_untested": _build_hypothesis_schism,
        "unresolved_tension": _build_unresolved_schism,
    }

    builder = schism_builders.get(anchor["anchor_type"], _build_unresolved_schism)
    schism_content = await builder(anchor, ghost_student, student_id)

    return {
        "past_position": position,
        "present_challenge": schism_content["challenge"],
        "ghost_content": schism_content["full_text"],
        "register_used": register,
        "emotional_tone": emotion,
        "confidence_at_anchor": confidence,
    }


async def _build_teacher_conflict_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Build schism for teacher vs Wax conflict."""
    days = ghost["days_ago"]
    quote = ghost["exact_quote"]

    full_text = f"""🔮 From your notebook, {days} days ago...

"{quote}"

I remember this tension. Your teacher's voice was strong. My voice challenged it.

**Past You:** *"My teacher said this is the rule. Rules don't break."*
**Present Question:** *But you also saw a case where the rule failed. What lives between the rule and the exception?*

Don't answer now if you're busy. But when you do — I'm here."""

    return {
        "challenge": "What lives between the rule and the exception?",
        "full_text": full_text,
    }


async def _build_breakthrough_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Build schism for near-breakthrough moments."""
    days = ghost["days_ago"]
    quote = ghost["exact_quote"]

    full_text = f"""🔮 From your notebook, {days} days ago...

"{quote}"

You were SO close. I could feel it. Something was about to click.

**Past You:** *"Almost... I can almost see it..."*
**Present Question:** *Did it ever click? Or did life move on before the door opened?*

If it clicked — tell me what you saw. If it didn't — let's open that door again."""

    return {
        "challenge": "Did the breakthrough ever arrive?",
        "full_text": full_text,
    }


async def _build_confidence_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Build schism for confidence collapse moments."""
    days = ghost["days_ago"]
    quote = ghost["exact_quote"]

    full_text = f"""🔮 From your notebook, {days} days ago...

"{quote}"

That was heavy. I felt the weight of that message.

**Past You:** *"I can't do this. It's too hard."*
**Present Question:** *Have you carried that weight since, or did you set it down? And if you set it down — what helped?*

You don't have to be strong every day. But I want to know what strong looks like for you now."""

    return {
        "challenge": "What does strong look like now?",
        "full_text": full_text,
    }


async def _build_emotional_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Build schism for emotional peak moments."""
    days = ghost["days_ago"]
    emotion = ghost["emotion"]

    full_text = f"""🔮 From your notebook, {days} days ago...

You were feeling {emotion}. Deeply. I remember.

**Past You:** *"This feeling is everything right now."*
**Present Question:** *Has the weather changed? Or are you still standing in the same rain?*

Feelings are data, not destiny. What do they tell you now?"""

    return {
        "challenge": "What do those feelings tell you now?",
        "full_text": full_text,
    }


async def _build_abandoned_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Build schism for abandoned problems."""
    days = ghost["days_ago"]
    quote = ghost["exact_quote"]

    full_text = f"""🔮 From your notebook, {days} days ago...

"{quote}"

You left something unfinished. I held it for you.

**Past You:** *"I'll come back to this later..."*
**Present Question:** *Later arrived. Did you come back? Or did the problem dissolve on its own?*

Some problems solve themselves with time. Others wait like patient ghosts."""

    return {
        "challenge": "Did the problem wait or dissolve?",
        "full_text": full_text,
    }


async def _build_hypothesis_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Build schism for untested hypotheses."""
    days = ghost["days_ago"]
    quote = ghost["exact_quote"]

    full_text = f"""🔮 From your notebook, {days} days ago...

"{quote}"

You had an idea. A guess. A maybe.

**Past You:** *"What if...?"*
**Present Question:** *Did you ever find out? Did you test it, or did someone else answer for you?*

The best ideas die from neglect, not failure."""

    return {
        "challenge": "Did you test the idea, or did it die from neglect?",
        "full_text": full_text,
    }


async def _build_unresolved_schism(
    anchor: Dict[str, Any],
    ghost: Dict[str, Any],
    student_id: str,
) -> Dict[str, Any]:
    """Default schism builder for generic unresolved tension."""
    days = ghost["days_ago"]
    quote = ghost["exact_quote"]

    full_text = f"""🔮 From your notebook, {days} days ago...

"{quote}"

Something was unresolved. I felt the tension in your words.

**Past You:** *"I don't know which side to choose."*
**Present Question:** *Have you chosen since? Or have you learned to live in the tension?*

Not every tension needs resolution. Some just need witness."""

    return {
        "challenge": "Have you chosen, or learned to live in tension?",
        "full_text": full_text,
    }


# ═══════════════════════════════════════════════════════════════════════
# 4. DELIVERY ORCHESTRATOR — Cron + Redis Dual System
# ═══════════════════════════════════════════════════════════════════════

async def schedule_ghost(
    student_id: str,
    anchor: Dict[str, Any],
    schism: Dict[str, Any],
    ghost_student: Dict[str, Any],
) -> Optional[str]:
    """
    Schedule a Ghost Thread for delivery.

    Uses cognitive decay curve to calculate optimal delay.
    Stores in both Supabase (persistent) and Redis (fast scheduling).
    """
    # Calculate delay
    confusion_level = ghost_student.get("confidence", 0.5)
    # Lower confidence = higher confusion = longer delay (let them sit with it)
    confusion_multiplier = 1.0 + (1.0 - confusion_level) * (CONFUSION_MULTIPLIER_MAX - 1.0)
    randomness = random.uniform(*RANDOMNESS_FACTOR_RANGE)
    delay_hours = BASE_DELAY_HOURS * confusion_multiplier * randomness

    scheduled_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)

    # Create ghost thread record
    ghost_record = {
        "student_id": student_id,
        "anchor_conversation_id": anchor["conversation_id"],
        "anchor_type": anchor["anchor_type"],
        "ghost_student_persona": ghost_student,
        "past_position": schism["past_position"],
        "present_challenge": schism["present_challenge"],
        "scheduled_at": scheduled_at.isoformat(),
        "status": "pending",
        "ghost_content": schism["ghost_content"],
        "thermal_state": "warm",
    }

    try:
        result = (
            supabase.table("ghost_threads")
            .insert(ghost_record)
            .execute()
        )
        if not result.data:
            logger.error("Ghost thread insert returned no data")
            return None

        ghost_id = result.data[0]["id"]

        # Add to Redis sorted set for fast scheduling
        timestamp_score = scheduled_at.timestamp()
        redis_client.zadd(GHOST_SCHEDULE_ZSET, {ghost_id: timestamp_score})

        logger.info(f"Ghost {ghost_id} scheduled for {scheduled_at.isoformat()} "
                   f"(delay: {delay_hours:.1f}h, student: {student_id})")

        return ghost_id

    except Exception as e:
        logger.error(f"Failed to schedule ghost thread: {e}")
        return None


async def check_and_deliver_ghosts(
    batch_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    Check for due ghosts and deliver them.

    Called by:
    - Cron job (every 15 minutes for reliability)
    - Message handler (when student sends message, for immediacy)

    Returns list of delivered ghosts.
    """
    now = datetime.now(timezone.utc)
    now_timestamp = now.timestamp()

    # Get due ghosts from Redis sorted set
    due_ghost_ids = redis_client.zrangebyscore(
        GHOST_SCHEDULE_ZSET,
        0,
        now_timestamp,
        start=0,
        num=batch_size,
    )

    if not due_ghost_ids:
        return []

    delivered = []

    for ghost_id in due_ghost_ids:
        # Remove from schedule
        redis_client.zrem(GHOST_SCHEDULE_ZSET, ghost_id)

        # Fetch full record
        try:
            result = (
                supabase.table("ghost_threads")
                .select("*")
                .eq("id", ghost_id)
                .single()
                .execute()
            )
            ghost = result.data
        except Exception as e:
            logger.error(f"Could not fetch ghost {ghost_id}: {e}")
            continue

        if not ghost or ghost.get("status") != "pending":
            continue

        student_id = ghost["student_id"]

        # RECEPTIVITY GATE
        if not await _is_receptive(student_id):
            # Reschedule for later
            new_time = now + timedelta(hours=6)
            redis_client.zadd(GHOST_SCHEDULE_ZSET, {ghost_id: new_time.timestamp()})
            logger.info(f"Ghost {ghost_id} rescheduled (student not receptive)")
            continue

        # Check frequency limit
        last_ghost = redis_client.get(STUDENT_LAST_GHOST_KEY.format(student_id=student_id))
        if last_ghost:
            last_time = datetime.fromisoformat(last_ghost.decode())
            if (now - last_time) < timedelta(hours=MAX_GHOST_FREQUENCY_HOURS):
                # Too soon, reschedule
                new_time = now + timedelta(hours=MAX_GHOST_FREQUENCY_HOURS)
                redis_client.zadd(GHOST_SCHEDULE_ZSET, {ghost_id: new_time.timestamp()})
                logger.info(f"Ghost {ghost_id} rescheduled (frequency limit)")
                continue

        # DELIVER
        ghost_content = ghost.get("ghost_content", "")
        if not ghost_content:
            continue

        # Update status
        try:
            supabase.table("ghost_threads").update({
                "status": "sent",
                "sent_at": now.isoformat(),
            }).eq("id", ghost_id).execute()
        except Exception as e:
            logger.error(f"Failed to update ghost status: {e}")

        # Track last sent
        redis_client.setex(
            STUDENT_LAST_GHOST_KEY.format(student_id=student_id),
            int(timedelta(days=30).total_seconds()),
            now.isoformat(),
        )

        delivered.append({
            "ghost_id": ghost_id,
            "student_id": student_id,
            "content": ghost_content,
            "anchor_type": ghost["anchor_type"],
        })

        logger.info(f"Ghost {ghost_id} delivered to student {student_id}")

    return delivered


async def _is_receptive(student_id: str) -> bool:
    """
    Check if student is in a receptive state for ghost delivery.
    """
    now = datetime.now(timezone.utc)
    current_hour = now.hour

    # Sleep hours
    if SLEEP_START_HOUR <= current_hour or current_hour < SLEEP_END_HOUR:
        return False

    # Check recent activity (don't interrupt active conversation)
    try:
        result = (
            supabase.table("conversations")
            .select("created_at")
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            last_msg_time = datetime.fromisoformat(
                result.data[0]["created_at"].replace("Z", "+00:00")
            )
            if (now - last_msg_time) < timedelta(hours=MIN_QUIET_HOURS):
                return False
    except Exception:
        pass  # If we can't check, proceed

    # Check exam period (high quiz frequency)
    try:
        exam_cutoff = now - timedelta(hours=24)
        quiz_result = (
            supabase.table("conversations")
            .select("id")
            .eq("student_id", student_id)
            .gte("created_at", exam_cutoff.isoformat())
            .execute()
        )
        # Simple heuristic: many messages in last 24h = exam period
        if len(quiz_result.data or []) > EXAM_DETECTION_THRESHOLD * 3:
            return False
    except Exception:
        pass

    # Check PIG intimacy (don't ghost strangers)
    try:
        from brain.relational_intimacy import get_current_intimacy_score
        intimacy = await get_current_intimacy_score(student_id)
        if intimacy < 3.0:
            return False
    except Exception:
        pass  # If PIG check fails, allow (better to over-ghost than under-ghost)

    # Check student preference
    pref = redis_client.get(STUDENT_GHOST_PREFERENCE.format(student_id=student_id))
    if pref and pref.decode() == "dismissed":
        return False

    return True


# ═══════════════════════════════════════════════════════════════════════
# 5. RESURRECTION ENGINE — Handle Student Replies to Ghosts
# ═══════════════════════════════════════════════════════════════════════

async def handle_ghost_reply(
    student_id: str,
    reply_text: str,
    conversation_context: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Process a student's reply to a Ghost Thread.

    This is the RESURRECTION: the ghost comes alive again.
    """
    # Find the most recent sent ghost for this student
    try:
        result = (
            supabase.table("ghost_threads")
            .select("*")
            .eq("student_id", student_id)
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return {"status": "no_active_ghost", "action": "ignore"}

        ghost = result.data[0]
    except Exception as e:
        logger.error(f"Could not fetch active ghost: {e}")
        return {"status": "error", "action": "ignore"}

    ghost_id = ghost["id"]

    # Classify the reply
    classification = _classify_resurrection_reply(reply_text)

    # Update ghost record
    try:
        supabase.table("ghost_threads").update({
            "status": "replied",
            "student_reply": reply_text,
            "resurrection_classification": classification,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", ghost_id).execute()
    except Exception as e:
        logger.error(f"Failed to update ghost reply: {e}")

    # Update student preference based on engagement
    if classification == "dismissed":
        redis_client.setex(
            STUDENT_GHOST_PREFERENCE.format(student_id=student_id),
            int(timedelta(days=7).total_seconds()),
            "dismissed",
        )

    # Build response based on classification
    response = await _build_resurrection_response(
        ghost, classification, reply_text, conversation_context
    )

    # Record epistemic delta
    await _record_epistemic_delta(ghost, classification, reply_text)

    return {
        "status": "resurrected",
        "classification": classification,
        "ghost_id": ghost_id,
        "response": response,
    }


def _classify_resurrection_reply(reply_text: str) -> str:
    """
    Classify how the student engaged with the ghost.
    """
    reply_lower = reply_text.lower().strip()

    # Dismissed
    dismiss_signals = ["stop", "don't", "no", "busy", "later", "not now",
                      "shut up", "go away", "annoying"]
    for signal in dismiss_signals:
        if signal in reply_lower:
            return "dismissed"

    # Resolved
    resolve_signals = ["yes", "figured", "solved", "got it", "understand now",
                      "i see", "clear", "makes sense"]
    for signal in resolve_signals:
        if signal in reply_lower:
            return "resolved"

    # Confused further
    confuse_signals = ["more confused", "worse", "don't understand", "lost",
                      "even harder", "what do you mean"]
    for signal in confuse_signals:
        if signal in reply_lower:
            return "confused_further"

    # Engaged (default — they replied substantively)
    if len(reply_lower.split()) > 3:
        return "engaged"

    # Minimal response
    return "engaged"  # Still engaged, just brief


async def _build_resurrection_response(
    ghost: Dict[str, Any],
    classification: str,
    reply_text: str,
    conversation_context: List[Dict[str, Any]],
) -> str:
    """
    Build Wax's response to the resurrection.
    """
    challenge = ghost.get("present_challenge", "")
    anchor_type = ghost.get("anchor_type", "")

    if classification == "dismissed":
        return ("I hear you. I'll give you space. "
                "When you're ready to pick up where we left off, just say 'continue'.")

    if classification == "resolved":
        return (f"Beautiful. You carried that tension and came out the other side. "
                f"What changed? What did you see that Past You couldn't?")

    if classification == "confused_further":
        return (f"That tension is deeper than I thought. Let's sit with it together. "
                f"You said: '{reply_text[:100]}...' — tell me more about what feels unclear.")

    # engaged — continue the dialectical thread
    if anchor_type == "teacher_conflict":
        return (f"You've been sitting with this for a while now. "
                f"Your teacher's rule vs the exception you found. "
                f"Where do you stand today?")

    if anchor_type == "breakthrough_seed":
        return (f"The door you were pushing on — did it open a little more? "
                f"What do you see now that you almost saw then?")

    return (f"Thank you for coming back to this. "
            f"You said: '{reply_text[:100]}...' — I'm listening.")


async def _record_epistemic_delta(
    ghost: Dict[str, Any],
    classification: str,
    reply_text: str,
) -> bool:
    """
    Record the student's epistemic growth from this temporal encounter.
    Writes to observations and updates ghost_threads with delta.
    """
    student_id = ghost["student_id"]
    ghost_id = ghost["id"]

    # Map classification to growth vector
    growth_vectors = {
        "resolved": {"direction": "growth", "magnitude": 0.8},
        "engaged": {"direction": "growth", "magnitude": 0.5},
        "confused_further": {"direction": "struggle", "magnitude": 0.4},
        "dismissed": {"direction": "resistance", "magnitude": 0.2},
    }
    vector = growth_vectors.get(classification, {"direction": "unknown", "magnitude": 0.0})

    delta = {
        "before_stance": ghost.get("past_position", "unknown"),
        "after_stance": classification,
        "growth_vector": vector,
        "reply_excerpt": reply_text[:200],
        "days_between": ghost.get("ghost_student_persona", {}).get("days_ago", 1),
    }

    # Update ghost record
    try:
        supabase.table("ghost_threads").update({
            "epistemic_delta": delta,
            "status": "resurrected" if classification != "dismissed" else "dismissed",
        }).eq("id", ghost_id).execute()
    except Exception as e:
        logger.error(f"Failed to record epistemic delta: {e}")

    # Write to observations (temporal growth observation)
    try:
        observation_text = (
            f"Temporal growth: Student moved from '{delta['before_stance']}' "
            f"to '{delta['after_stance']}' over {delta['days_between']} days. "
            f"Growth vector: {vector['direction']} ({vector['magnitude']})"
        )

        supabase.table("observations").insert({
            "student_id": student_id,
            "normalized_key": f"temporal_growth_{ghost_id}",
            "category": "epistemic_growth",
            "fact": observation_text,
            "confidence": float(Decimal("0.75")),
            "source": "ghost_thread_protocol",
            "thermal_score": 65,
            "thermal_state": "warm",
            "provenance": "DERIVED",
            "surface_value": observation_text,
        }).execute()
    except Exception as e:
        logger.warning(f"Could not write temporal observation: {e}")

    return True


# ═══════════════════════════════════════════════════════════════════════
# 6. EPISTEMIC TIME MACHINE — High-Level API
# ═══════════════════════════════════════════════════════════════════════

async def spawn_ghost_thread(
    student_id: str,
    force_anchor: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    High-level API: Spawn a Ghost Thread for a student.

    If force_anchor is provided, use it. Otherwise, mine for anchors.
    Returns ghost_id if scheduled, None if no suitable anchor found.
    """
    # Find anchor
    if force_anchor:
        anchor = force_anchor
    else:
        anchors = await mine_anchors(student_id)
        if not anchors:
            logger.info(f"No anchors found for student {student_id}")
            return None
        anchor = anchors[0]  # Take highest thermal

    # Forge ghost student
    ghost_student = await forge_ghost_student(anchor, student_id)

    # Build temporal schism
    schism = await forge_temporal_schism(anchor, ghost_student, student_id)

    # Schedule delivery
    ghost_id = await schedule_ghost(student_id, anchor, schism, ghost_student)

    if ghost_id:
        logger.info(f"Ghost Thread spawned: {ghost_id} for student {student_id}")
    else:
        logger.warning(f"Failed to spawn ghost for student {student_id}")

    return ghost_id


async def process_due_ghosts() -> List[Dict[str, Any]]:
    """
    Cron-facing API: Check and deliver all due ghosts.
    Call this from your cron job every 15 minutes.
    """
    return await check_and_deliver_ghosts(batch_size=20)


async def on_student_message(
    student_id: str,
    message_text: str,
    conversation_context: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Message-handler-facing API: Check if this message is a ghost reply.
    Call this from telegram/handler.py on every incoming message.
    """
    # Quick check: is there a recent sent ghost?
    try:
        result = (
            supabase.table("ghost_threads")
            .select("id")
            .eq("student_id", student_id)
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
    except Exception:
        return None

    # Check if message looks like a reply to ghost (within 48h of ghost sent)
    # This is a loose heuristic — the resurrection engine handles classification
    ghost = result.data[0]
    sent_at = datetime.fromisoformat(ghost["sent_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) - sent_at > timedelta(hours=48):
        return None

    # Also check for due ghosts and deliver immediately (Redis path)
    await check_and_deliver_ghosts(batch_size=5)

    # Process as potential ghost reply
    return await handle_ghost_reply(student_id, message_text, conversation_context)


# ═══════════════════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════════════════

async def get_student_ghost_history(
    student_id: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Get ghost thread history for a student."""
    try:
        result = (
            supabase.table("ghost_threads")
            .select("*")
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch ghost history: {e}")
        return []


async def dismiss_all_pending_ghosts(student_id: str) -> bool:
    """Dismiss all pending ghosts for a student (e.g., if they say 'stop')."""
    try:
        supabase.table("ghost_threads").update({
            "status": "dismissed",
        }).eq("student_id", student_id).eq("status", "pending").execute()
        # Also clear from Redis
        # Note: This is approximate — we don't have reverse lookup from student_id to ghost_id in Redis
        # A full implementation would maintain a secondary index
        return True
    except Exception as e:
        logger.error(f"Failed to dismiss ghosts: {e}")
        return False
