"""
brain/state_socket.py — Wax State Socket (The Sacred Wall)

THE ONLY STATE INTERFACE YOUR EXISTING CODE TOUCHES.

This file provides a stable API for all state operations.
NOW WIRED TO: brain/state_cortex.py (4D Living State Architecture)

RULES:
- NEVER change the function signatures below. They are sacred.
- ALWAYS return safe defaults if something fails.
- ALWAYS log errors but never crash the caller.
"""

import json
import logging
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from decimal import Decimal

logger = logging.getLogger("waxprep.state_socket")

# ═══════════════════════════════════════════════════════════════════════
# CORTEX INTEGRATION
# ═══════════════════════════════════════════════════════════════════════

# Lazy import to avoid circular dependencies
_cortex = None

def _get_cortex():
    """Lazy singleton for StateCortex."""
    global _cortex
    if _cortex is None:
        try:
            from brain.state_cortex import get_state_cortex
            _cortex = get_state_cortex()
        except Exception as e:
            logger.error(f"Failed to initialize StateCortex: {e}")
            _cortex = None
    return _cortex


# ═══════════════════════════════════════════════════════════════════════
# SACRED API — These functions never change
# ═══════════════════════════════════════════════════════════════════════

async def get_current_mode(student_id: str) -> str:
    """
    Return the dominant Wax mode for this student.
    
    SACRED: Always returns a string. Never crashes.
    """
    if not student_id:
        return "idle"
    
    try:
        cortex = _get_cortex()
        if cortex:
            vector = await cortex.get_vector(student_id)
            dominant_mode, _ = vector.dominant_mode()
            return dominant_mode
    except Exception as e:
        logger.error(f"Cortex get_current_mode failed for {student_id}: {e}")
    
    # Fallback: try legacy Redis
    try:
        from database.client import redis_client
        key = f"state_socket:mode:{student_id}"
        raw = redis_client.get(key)
        if raw:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return data.get("mode", "idle")
    except Exception:
        pass
    
    return "idle"


async def set_mode(student_id: str, mode: str, confidence: float = 1.0,
                   metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Set Wax mode with confidence. Updates the 4D StateVector.
    
    SACRED: Always succeeds. Never crashes.
    """
    if not student_id:
        return
    
    # Validate mode
    valid_modes = {
        "onboarding", "active", "ended", "idle",
        "in_quiz", "in_emotional_support", "awaiting_response",
        "teaching", "chatting", "paused"
    }
    if mode not in valid_modes:
        logger.warning(f"Invalid mode '{mode}' for {student_id}, using 'idle'")
        mode = "idle"
    
    confidence_decimal = Decimal(str(max(0.0, min(1.0, float(confidence))))
    
    try:
        cortex = _get_cortex()
        if cortex:
            await cortex.set_dominant_mode(
                student_id=student_id,
                mode=mode,
                confidence=confidence_decimal,
                metadata=metadata or {}
            )
            return
    except Exception as e:
        logger.error(f"Cortex set_mode failed for {student_id}: {e}")
    
    # Fallback: legacy Redis write
    try:
        from database.client import redis_client
        state_data = {
            "mode": mode,
            "confidence": float(confidence_decimal),
            "metadata": metadata or {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        key = f"state_socket:mode:{student_id}"
        redis_client.setex(key, 86400, json.dumps(state_data))
    except Exception:
        pass


async def is_in_superposition(student_id: str, threshold: float = 0.3) -> bool:
    """
    True if multiple modes are active simultaneously.
    
    SACRED: Always returns bool. Never crashes.
    """
    if not student_id:
        return False
    
    try:
        cortex = _get_cortex()
        if cortex:
            vector = await cortex.get_vector(student_id)
            return vector.is_in_superposition(Decimal(str(threshold)))
    except Exception as e:
        logger.error(f"Cortex superposition check failed for {student_id}: {e}")
    
    return False


async def get_student_mind(student_id: str) -> Dict[str, float]:
    """
    Return inferred cognitive/affective state of the student.
    
    SACRED: Always returns a dict. Never crashes.
    """
    if not student_id:
        return {
            "confidence": 0.5, "confusion": 0.0, "frustration": 0.0,
            "engagement": 0.5, "commitment": 0.0,
        }
    
    try:
        cortex = _get_cortex()
        if cortex:
            vector = await cortex.get_vector(student_id)
            effective_mind = vector.current_effective_mind()
            return {
                "confidence": float(effective_mind.get("confident", Decimal("0.5"))),
                "confusion": float(effective_mind.get("confused", Decimal("0"))),
                "frustration": float(effective_mind.get("frustrated", Decimal("0"))),
                "engagement": float(effective_mind.get("engaged", Decimal("0.5"))),
                "commitment": float(effective_mind.get("motivated", Decimal("0"))),
            }
    except Exception as e:
        logger.error(f"Cortex get_student_mind failed for {student_id}: {e}")
    
    # Fallback
    return {
        "confidence": 0.5, "confusion": 0.0, "frustration": 0.0,
        "engagement": 0.5, "commitment": 0.0,
    }


async def record_message(student_id: str, role: str, content: str) -> None:
    """
    Feed a message into the state system for analysis.
    
    SACRED: Always succeeds silently. Never crashes.
    """
    if not student_id:
        return
    
    try:
        cortex = _get_cortex()
        if cortex:
            await cortex.record_message(student_id, role, content)
            return
    except Exception as e:
        logger.error(f"Cortex record_message failed for {student_id}: {e}")
    
    # Fallback: legacy no-op
    logger.debug(f"Message recorded (fallback) for {student_id}: {role}={content[:50]}...")


async def get_context_for_ai(student_id: str) -> str:
    """
    Return state context string for AI prompt injection.
    
    SACRED: Always returns a string. Never crashes.
    """
    if not student_id:
        return ""
    
    try:
        cortex = _get_cortex()
        if cortex:
            return await cortex.get_context_string(student_id)
    except Exception as e:
        logger.error(f"Cortex get_context_for_ai failed for {student_id}: {e}")
    
    # Fallback: basic mode description
    mode = await get_current_mode(student_id)
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
    return f"[STATE CONTEXT] {mode_descriptions.get(mode, 'The student is learning.')} Current mode: {mode}."


async def on_crash_recovery(student_id: str, history: list) -> Dict[str, Any]:
    """
    Reconstruct state from message history after crash or long gap.
    
    SACRED: Always returns a dict. Never crashes.
    """
    logger.info(f"Crash recovery triggered for {student_id} with {len(history)} messages")
    
    try:
        cortex = _get_cortex()
        if cortex:
            vector = await cortex.reconstruct_from_history(student_id, history)
            dominant_mode, confidence = vector.dominant_mode()
            return {
                "recovered_mode": dominant_mode,
                "confidence": float(confidence),
                "superposition": vector.is_in_superposition(),
                "student_mind": {
                    "dominant": vector.dominant_mind_state()[0],
                    "confidence": float(vector.dominant_mind_state()[1]),
                },
                "note": "State reconstructed from message history via State Cortex.",
            }
    except Exception as e:
        logger.error(f"Cortex crash recovery failed for {student_id}: {e}")
    
    return {
        "recovered_mode": "idle",
        "confidence": 0.5,
        "note": "Crash recovery failed — defaulting to idle.",
    }


async def should_trigger_onboarding(student_id: str) -> Tuple[bool, float]:
    """
    Return (should_trigger, commitment_score) for natural account creation.
    
    SACRED: Always returns (bool, float). Never crashes.
    DISABLED: Waiting for friend's research on natural conversion triggers.
    """
    # DISABLED: Waiting for research
    # When enabled:
    # try:
    #     cortex = _get_cortex()
    #     if cortex:
    #         commitment = await cortex.get_commitment_score(student_id)
    #         return (commitment > Decimal("0.6"), float(commitment))
    # except Exception:
    #     pass
    
    return (False, 0.0)


async def get_full_state(student_id: str) -> Dict[str, Any]:
    """
    Return complete state data for debugging/admin.
    
    SACRED: Always returns a dict. Never crashes.
    """
    try:
        cortex = _get_cortex()
        if cortex:
            vector = await cortex.get_vector(student_id)
            return {
                "student_id": student_id,
                "mode": vector.dominant_mode()[0],
                "mode_confidence": float(vector.dominant_mode()[1]),
                "student_mind": {k: float(v) for k, v in vector.current_effective_mind().items()},
                "superposition": vector.is_in_superposition(),
                "topology": vector.conversation_topology,
                "env_context": vector.env_context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": f"cortex_v{vector.version}",
            }
    except Exception as e:
        logger.error(f"Cortex get_full_state failed for {student_id}: {e}")
    
    return {
        "student_id": student_id,
        "mode": await get_current_mode(student_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "fallback_v1",
    }


# ═══════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY (for gradual migration)
# ═══════════════════════════════════════════════════════════════════════

async def get_state(student_id: str) -> str:
    """LEGACY: Maps to get_current_mode()."""
    return await get_current_mode(student_id)


async def set_state(student_id: str, mode: str, reason: str = "",
                    session_context: Optional[Dict] = None) -> None:
    """LEGACY: Maps to set_mode()."""
    metadata = {"reason": reason}
    if session_context:
        metadata["session_context"] = session_context
    await set_mode(student_id, mode, confidence=1.0, metadata=metadata)
