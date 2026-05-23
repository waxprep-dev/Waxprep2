"""
brain/state_socket.py — Wax State Socket (The Sacred Wall)

THE ONLY STATE INTERFACE YOUR EXISTING CODE TOUCHES.

This file provides a stable API for all state operations. Currently runs in
DUMMY MODE (mirrors old brain/state.py behavior). Will be wired to the
State Cortex in Step 4.

RULES:
- NEVER import from state_cortex, state_archaeologist, or student_mind_mirror here.
- NEVER change the function signatures below. They are sacred.
- ALWAYS return safe defaults if something fails.
- ALWAYS log errors but never crash the caller.

Migration guide for existing code:
OLD: from brain.state import get_state, set_state
NEW: from brain.state_socket import get_current_mode, set_mode
"""

import json
import logging
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("waxprep.state_socket")

# ═══════════════════════════════════════════════════════════════════════
# DUMMY MODE: Current behavior mirroring brain/state.py
# ═══════════════════════════════════════════════════════════════════════

# In-memory fallback if Redis fails
_local_state_cache: Dict[str, Dict[str, Any]] = {}

# Valid modes (same as current state machine + new ones for future)
VALID_MODES = {
    "onboarding", "active", "ended", "idle",
    "in_quiz", "in_emotional_support", "awaiting_response",
    "teaching", "chatting", "paused"
}

# Default state for new students
DEFAULT_STATE = {
    "mode": "idle",
    "confidence": 1.0,
    "metadata": {},
    "updated_at": None,
    "session_count": 0,
}


async def get_current_mode(student_id: str) -> str:
    """
    Return the dominant Wax mode for this student.
    
    SACRED: Always returns a string. Never crashes.
    Current: Reads from Redis, falls back to local cache, falls back to 'idle'.
    Future: Will query State Cortex for dominant mode after decay.
    """
    if not student_id:
        logger.warning("get_current_mode called with empty student_id")
        return "idle"
    
    # Try Redis first
    try:
        from database.client import redis_client
        key = f"state_socket:mode:{student_id}"
        raw = redis_client.get(key)
        if raw:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            mode = data.get("mode", "idle")
            if mode in VALID_MODES:
                return mode
    except Exception as e:
        logger.error(f"Redis state read failed for {student_id}: {e}")
    
    # Fallback to local cache
    if student_id in _local_state_cache:
        mode = _local_state_cache[student_id].get("mode", "idle")
        if mode in VALID_MODES:
            return mode
    
    # Ultimate fallback
    return "idle"


async def set_mode(student_id: str, mode: str, confidence: float = 1.0,
                   metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Set Wax mode with confidence. Allows future superposition.
    
    SACRED: Always succeeds. Never crashes.
    Current: Writes to Redis + local cache.
    Future: Will push to State Cortex as probability update.
    """
    if not student_id:
        logger.warning("set_mode called with empty student_id")
        return
    
    if mode not in VALID_MODES:
        logger.warning(f"Invalid mode '{mode}' for {student_id}, using 'idle'")
        mode = "idle"
    
    # Clamp confidence
    confidence = max(0.0, min(1.0, float(confidence)))
    
    state_data = {
        "mode": mode,
        "confidence": confidence,
        "metadata": metadata or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Update local cache
    _local_state_cache[student_id] = state_data
    
    # Try Redis
    try:
        from database.client import redis_client
        key = f"state_socket:mode:{student_id}"
        redis_client.setex(key, 86400, json.dumps(state_data))  # 24h TTL
    except Exception as e:
        logger.error(f"Redis state write failed for {student_id}: {e}")
        # Local cache already updated, so we're fine


async def is_in_superposition(student_id: str, threshold: float = 0.3) -> bool:
    """
    True if multiple modes are active simultaneously.
    
    SACRED: Always returns bool. Never crashes.
    Current: Dummy — always returns False (old state machine has no superposition).
    Future: Will query State Cortex for probability distribution.
    """
    # For now, no superposition in dummy mode
    # This will become True when Cortex is wired in
    return False


async def get_student_mind(student_id: str) -> Dict[str, float]:
    """
    Return inferred cognitive/affective state of the student.
    
    SACRED: Always returns a dict. Never crashes.
    Current: Returns empty dict (old system has no mind model).
    Future: Will query Student Mind Mirror.
    """
    # Dummy implementation — no mind model yet
    return {
        "confidence": 0.5,
        "confusion": 0.0,
        "frustration": 0.0,
        "engagement": 0.5,
        "commitment": 0.0,  # For account creation timing
    }


async def record_message(student_id: str, role: str, content: str) -> None:
    """
    Feed a message into the state system for analysis.
    
    SACRED: Always succeeds silently. Never crashes.
    Current: No-op (old system doesn't analyze messages for state).
    Future: Will push to Student Mind Mirror + State Cortex.
    """
    # Dummy — just log at debug level
    logger.debug(f"Message recorded for {student_id}: {role}={content[:50]}...")
    
    # In future, this will:
    # - Update mind mirror with sentiment analysis
    # - Shift state probabilities in Cortex
    # - Trigger archaeology if needed
    pass


async def get_context_for_ai(student_id: str) -> str:
    """
    Return state context string for AI prompt injection.
    
    SACRED: Always returns a string. Never crashes.
    Current: Returns basic mode description.
    Future: Will query State Cortex for rich 4D context.
    """
    mode = await get_current_mode(student_id)
    
    # Map modes to human-readable context
    mode_descriptions = {
        "idle": "The student just started or returned after a break.",
        "chatting": "The student is in a normal conversation.",
        "teaching": "Wax is actively teaching a concept.",
        "in_quiz": "The student is currently answering a quiz question.",
        "in_emotional_support": "The student needs emotional support.",
        "awaiting_response": "Wax asked a question and is waiting for the student.",
        "onboarding": "The student is new and being onboarded.",
        "active": "The student is actively learning.",
        "ended": "The session has ended.",
        "paused": "The session is paused.",
    }
    
    description = mode_descriptions.get(mode, "The student is learning.")
    
    return f"[STATE CONTEXT] {description} Current mode: {mode}."


async def on_crash_recovery(student_id: str, history: list) -> Dict[str, Any]:
    """
    Reconstruct state from message history after crash or long gap.
    
    SACRED: Always returns a dict. Never crashes.
    Current: Returns default state (old system has no archaeology).
    Future: Will call State Archaeologist for full reconstruction.
    """
    logger.info(f"Crash recovery triggered for {student_id} with {len(history)} messages")
    
    # For now, just return a safe default
    # In future, this will analyze history and reconstruct 4D state
    return {
        "recovered_mode": "idle",
        "confidence": 0.5,
        "note": "Crash recovery not yet implemented — defaulting to idle.",
    }


async def should_trigger_onboarding(student_id: str) -> Tuple[bool, float]:
    """
    Return (should_trigger, commitment_score) for natural account creation.
    
    SACRED: Always returns (bool, float). Never crashes.
    Current: Returns (False, 0.0) — disabled until friend's research arrives.
    Future: Will read Student Mind Mirror commitment score.
    """
    # DISABLED: Waiting for friend's research on natural conversion triggers
    # When enabled, this will return (True, commitment_score) when:
    # - student_mind.commitment > 0.6
    # - conversation_topology == "deepening"
    # - student has demonstrated value receipt
    
    return (False, 0.0)


async def get_full_state(student_id: str) -> Dict[str, Any]:
    """
    Return complete state data for debugging/admin.
    
    SACRED: Always returns a dict. Never crashes.
    """
    mode = await get_current_mode(student_id)
    mind = await get_student_mind(student_id)
    
    return {
        "student_id": student_id,
        "mode": mode,
        "student_mind": mind,
        "superposition": await is_in_superposition(student_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "socket_v1_dummy",  # Will change when Cortex is wired
    }


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY (for gradual migration)
# ═══════════════════════════════════════════════════════════════════════

async def get_state(student_id: str) -> str:
    """
    LEGACY: Old brain/state.py signature.
    Maps to get_current_mode() for backward compatibility.
    """
    return await get_current_mode(student_id)


async def set_state(student_id: str, mode: str, reason: str = "",
                    session_context: Optional[Dict] = None) -> None:
    """
    LEGACY: Old brain/state.py signature.
    Maps to set_mode() for backward compatibility.
    """
    metadata = {"reason": reason}
    if session_context:
        metadata["session_context"] = session_context
    
    await set_mode(student_id, mode, confidence=1.0, metadata=metadata)
