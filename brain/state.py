"""
WaxPrep v2 — State Machine
Defines every state a student can be in and what transitions are allowed.
This is the brain's foundation — everything else depends on this.

Architecture:
    - StudentState enum: All possible states with documentation
    - ALLOWED_TRANSITIONS: Guards against impossible state jumps
    - Dual persistence: Redis (fast read) + Database (durable write)
    - Session ENDED trigger: Automatically saves memory for the Teacher Voice
    
Memory Flow:
    set_state("ended") → _on_session_ended() → save_session_summary() + save_student_memory()
    Next login → _build_memory_context() → "Last time we did Biology - Diffusion. Scored 80%."
"""

import logging
from enum import Enum
from typing import Optional, Dict, Any, List

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.state")


class StudentState(Enum):
    """Every possible state a student can be in."""
    ONBOARDING = "onboarding"          # First time, setting up profile
    IDLE = "idle"                      # Between sessions, waiting
    GREETING = "greeting"              # Just opened the app, being welcomed
    IN_LESSON = "in_lesson"            # Actively learning a topic
    IN_PRACTICE = "in_practice"        # Doing practice questions
    STUCK = "stuck"                    # Failed 3+ times, needs intervention
    IN_EXAM_MODE = "in_exam_mode"      # Close to exam, different behavior
    ASKING_QUESTION = "asking_question" # Temporary detour from lesson
    PAUSED = "paused"                  # Student said "not now"
    CHATTING = "chatting"              # Non-learning conversation
    ENDED = "ended"                    # Session complete


# ── Allowed Transitions ──────────────────────
# A state can only change to certain other states.
# This prevents schizophrenic behavior where the bot
# jumps from onboarding directly to exam mode.

ALLOWED_TRANSITIONS: Dict[StudentState, List[StudentState]] = {
    StudentState.ONBOARDING: [
        StudentState.IDLE,
        StudentState.GREETING,
    ],
    StudentState.IDLE: [
        StudentState.GREETING,
        StudentState.IN_LESSON,
        StudentState.IN_PRACTICE,
        StudentState.ASKING_QUESTION,
        StudentState.CHATTING,
    ],
    StudentState.GREETING: [
        StudentState.IN_LESSON,
        StudentState.IN_PRACTICE,
        StudentState.IDLE,
        StudentState.CHATTING,
        StudentState.PAUSED,
    ],
    StudentState.IN_LESSON: [
        StudentState.IN_PRACTICE,
        StudentState.STUCK,
        StudentState.ASKING_QUESTION,
        StudentState.PAUSED,
        StudentState.ENDED,
    ],
    StudentState.IN_PRACTICE: [
        StudentState.IN_LESSON,
        StudentState.STUCK,
        StudentState.ASKING_QUESTION,
        StudentState.ENDED,
    ],
    StudentState.STUCK: [
        StudentState.IN_LESSON,
        StudentState.IDLE,
        StudentState.ASKING_QUESTION,
        StudentState.PAUSED,
    ],
    StudentState.ASKING_QUESTION: [
        StudentState.IN_LESSON,
        StudentState.IN_PRACTICE,
        StudentState.IDLE,
    ],
    StudentState.PAUSED: [
        StudentState.IDLE,
        StudentState.GREETING,
        StudentState.IN_LESSON,
    ],
    StudentState.CHATTING: [
        StudentState.IDLE,
        StudentState.GREETING,
        StudentState.IN_LESSON,
    ],
    StudentState.ENDED: [
        StudentState.IDLE,
        StudentState.GREETING,
    ],
    # IN_EXAM_MODE not yet implemented — reserved
    StudentState.IN_EXAM_MODE: [],
}


# ── State cache TTL (seconds) ────────────────
STATE_CACHE_TTL = 3600  # 1 hour in Redis


# ═══════════════════════════════════════════════
# STATE MANAGEMENT
# ═══════════════════════════════════════════════

async def get_state(student_id: str) -> Optional[str]:
    """
    Get the current state for a student.
    
    Returns None if the student doesn't exist.
    Checks Redis first (fast), falls back to database (durable).
    On database fallback, repopulates Redis cache.
    
    Args:
        student_id: Student database ID
        
    Returns:
        State string (e.g., "in_lesson") or None
    """
    # Check Redis first
    key = f"student_state:{student_id}"
    try:
        cached = redis_client.get(key)
        if cached:
            # Redis get() returns bytes — decode to string
            decoded = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            if decoded:
                return decoded
    except Exception as e:
        logger.error(f"Redis get_state error for {student_id}: {e}")

    # Fall back to database
    try:
        result = (
            supabase.table("students")
            .select("current_state, onboarding_complete")
            .eq("id", student_id)
            .execute()
        )
        if result.data:
            row = result.data[0]
            state = row.get("current_state")
            if not state:
                # No state stored yet — infer from onboarding status
                is_complete = row.get("onboarding_complete", False)
                state = (
                    StudentState.IDLE.value
                    if is_complete
                    else StudentState.ONBOARDING.value
                )
                logger.info(
                    f"Inferred state for {student_id}: {state} "
                    f"(onboarding_complete={is_complete})"
                )

            # Repopulate Redis cache
            try:
                redis_client.setex(key, STATE_CACHE_TTL, state)
            except Exception as e:
                logger.warning(f"Redis cache repopulation failed: {e}")

            return state
        
        logger.warning(f"Student {student_id} not found in database")
    except Exception as e:
        logger.error(f"Database get_state error for {student_id}: {e}")

    return None  # Student not found


async def set_state(
    student_id: str,
    new_state: str,
    reason: str = "",
    session_context: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Change a student's state. Returns True if successful.
    
    Validates the transition before saving.
    Persists to both Redis (fast) and database (durable).
    
    If transitioning to ENDED, automatically saves a session summary
    and updates student memory for the Teacher Memory Voice.
    
    Args:
        student_id: Student's database ID
        new_state: Target state (must be a valid StudentState value)
        reason: Human-readable reason for the transition (logged)
        session_context: Optional dict with session details for memory.
            Used when transitioning to ENDED.
            Keys: subject, topic, completed, score, struggled_with
            
    Returns:
        True if state was changed successfully, False otherwise
    """
    current_state_str = await get_state(student_id)
    if not current_state_str:
        logger.warning(f"set_state failed: student {student_id} not found")
        return False

    # Parse current state
    try:
        current_state = StudentState(current_state_str)
    except ValueError:
        logger.warning(
            f"Invalid current state '{current_state_str}' for {student_id}. "
            f"Defaulting to IDLE."
        )
        current_state = StudentState.IDLE

    # Parse new state
    try:
        target_state = StudentState(new_state)
    except ValueError:
        logger.error(f"set_state failed: invalid target state '{new_state}'")
        return False

    # Check if transition is allowed
    allowed = ALLOWED_TRANSITIONS.get(current_state, [])
    if target_state not in allowed:
        logger.warning(
            f"State transition blocked: {current_state.value} → {new_state} "
            f"(allowed from {current_state.value}: {[s.value for s in allowed]})"
        )
        return False

    # Log the transition
    logger.info(
        f"STATE TRANSITION: {student_id}: {current_state.value} → {new_state}"
        + (f" | Reason: {reason}" if reason else "")
    )

    # ── Save to Redis (fast path) ──
    key = f"student_state:{student_id}"
    redis_saved = False
    try:
        redis_client.setex(key, STATE_CACHE_TTL, new_state)
        redis_saved = True
    except Exception as e:
        logger.error(f"Redis set_state error for {student_id}: {e}")

    # ── Save to database (durable path) ──
    db_saved = False
    try:
        supabase.table("students") \
            .update({"current_state": new_state}) \
            .eq("id", student_id) \
            .execute()
        db_saved = True
    except Exception as e:
        logger.error(f"Database set_state error for {student_id}: {e}")

    # ── Warn if neither save succeeded ──
    if not redis_saved and not db_saved:
        logger.critical(
            f"set_state COMPLETELY FAILED for {student_id}: "
            f"neither Redis nor database saved!"
        )
        return False

    # ── Session ENDED → Save memory (non-blocking) ──
    if target_state == StudentState.ENDED:
        try:
            await _on_session_ended(student_id, session_context or {})
        except Exception as e:
            logger.error(
                f"Session memory save failed for {student_id}: {e}",
                exc_info=True
            )
            # Don't block — state change succeeded, memory is non-critical

    return True


# ═══════════════════════════════════════════════
# SESSION ENDED HANDLER
# ═══════════════════════════════════════════════

async def _on_session_ended(student_id: str, context: Dict[str, Any]) -> None:
    """
    Called automatically when a student's state changes to ENDED.
    
    Saves a session summary and updates persistent student memory
    so Wax remembers what happened next time the student returns.
    
    This is the bridge between the state machine and the Memory Voice.
    
    Args:
        student_id: Student database ID
        context: Session details with optional keys:
            subject, topic, completed, score, struggled_with
    """
    # Import here to avoid circular dependency at module level
    from database.conversations import (
        save_session_summary,
        save_student_memory,
        get_history
    )
    from datetime import datetime, timezone

    # ── Extract context ──
    subject = context.get("subject", "unknown")
    topic = context.get("topic", "unknown")
    completed = context.get("completed", True)
    score = context.get("score")  # Optional — may be None
    struggled_with = list(context.get("struggled_with", []))

    # If no explicit struggles, try to detect from conversation
    if not struggled_with:
        try:
            recent_history = await get_history(student_id, limit=10)
            struggle_keywords = [
                "confused", "don't understand", "not sure",
                "hard", "difficult", "struggling", "i don't get",
                "doesn't make sense", "too complex"
            ]
            for msg in recent_history:
                if msg.get("role") == "user":
                    content = msg.get("content", "").lower()
                    for keyword in struggle_keywords:
                        if keyword in content:
                            if topic and topic not in struggled_with:
                                struggled_with.append(topic)
                            break
            if struggled_with:
                logger.info(
                    f"Auto-detected struggles for {student_id}: {struggled_with}"
                )
        except Exception as e:
            logger.warning(f"Struggle detection failed for {student_id}: {e}")

    # ── Build session summary ──
    summary = {
        "subject": subject,
        "topic": topic,
        "completed": completed,
        "score": score,
        "struggled_with": struggled_with,
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await save_session_summary(student_id, summary)
        logger.info(
            f"Session summary saved: {student_id} - {subject}/{topic} "
            + (f"(score: {score})" if score is not None else "")
        )
    except Exception as e:
        logger.error(f"Failed to save session summary for {student_id}: {e}")

    # ── Update persistent student memory ──
    # Build memory updates with clear, non-contradictory rules
    memory_updates: Dict[str, Any] = {}

    # Rule 1: If they struggled (explicitly OR from detection), record it
    if struggled_with:
        memory_updates["struggles_with"] = struggled_with
        logger.info(f"Memory: {student_id} struggles with {struggled_with}")

    # Rule 2: If score is high, record as strength
    # Only set strength if NOT also in struggles (prevents contradiction)
    if score is not None and score >= 0.8 and topic not in struggled_with:
        memory_updates["strong_in"] = [topic]
        logger.info(f"Memory: {student_id} is strong in {topic} (score: {score})")

    # Rule 3: If score is very low, reinforce struggles
    elif score is not None and score < 0.5:
        if topic not in struggled_with:
            struggled_with.append(topic)
        memory_updates["struggles_with"] = struggled_with
        logger.info(f"Memory: {student_id} scored low on {topic} (score: {score})")

    # Rule 4: If score is very high AND completed, consider mastered
    if completed and score is not None and score >= 0.9:
        memory_updates["topics_mastered"] = [topic]
        logger.info(f"Memory: {student_id} mastered {topic} (score: {score})")

    # Rule 5: Increment session count (read current, add 1)
    try:
        from database.conversations import get_student_memory
        existing_memory = await get_student_memory(student_id)
        current_sessions = existing_memory.get("sessions_completed", 0) if existing_memory else 0
        memory_updates["sessions_completed"] = current_sessions + 1
        logger.info(
            f"Memory: {student_id} session count: "
            f"{current_sessions} → {current_sessions + 1}"
        )
    except Exception as e:
        logger.warning(f"Failed to get existing session count: {e}")
        memory_updates["sessions_completed"] = 1  # Fallback

    # ── Save memory ──
    try:
        await save_student_memory(student_id, memory_updates)
        logger.info(f"Student memory updated for {student_id}: {list(memory_updates.keys())}")
    except Exception as e:
        logger.error(f"Failed to save student memory for {student_id}: {e}")


# ═══════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════

async def is_in_state(student_id: str, state: str) -> bool:
    """
    Check if student is in a specific state.
    
    Args:
        student_id: Student database ID
        state: State string to check (e.g., "in_lesson")
        
    Returns:
        True if student is in the specified state
    """
    current = await get_state(student_id)
    return current == state


async def force_state(student_id: str, new_state: str, admin_id: str = "unknown") -> bool:
    """
    Force a state change without transition validation.
    
    ⚠️ Use ONLY for admin/reset operations.
    Logs the admin who performed the action.
    
    Args:
        student_id: Student database ID
        new_state: Target state string
        admin_id: Identifier of the admin performing the action
        
    Returns:
        True if successful
    """
    logger.warning(
        f"FORCE STATE: {admin_id} forcing {student_id} → {new_state}"
    )

    key = f"student_state:{student_id}"
    try:
        redis_client.setex(key, STATE_CACHE_TTL, new_state)
    except Exception as e:
        logger.error(f"force_state Redis error: {e}")

    try:
        supabase.table("students") \
            .update({"current_state": new_state}) \
            .eq("id", student_id) \
            .execute()
    except Exception as e:
        logger.error(f"force_state database error: {e}")
        return False

    # Log admin action for audit
    try:
        supabase.table("admin_actions").insert({
            "admin_id": admin_id,
            "action": "force_state",
            "target_student": student_id,
            "details": f"State forced to: {new_state}",
            "performed_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")

    return True


async def clear_state(student_id: str) -> None:
    """
    Remove state from cache and database.
    
    Used on account deletion or complete reset.
    """
    logger.info(f"Clearing state for {student_id}")
    
    key = f"student_state:{student_id}"
    try:
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"clear_state Redis error: {e}")

    try:
        supabase.table("students") \
            .update({"current_state": None}) \
            .eq("id", student_id) \
            .execute()
    except Exception as e:
        logger.error(f"clear_state database error: {e}")
