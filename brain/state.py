"""
WaxPrep v2 — State Machine
Defines every state a student can be in.
Lightweight context tracker. Triggers backend events (session save, memory update).
The AI prompt and student memory are the real foundation.

Architecture:
    - StudentState enum: All possible states with documentation
    - No transition whitelist — any valid state is accepted
    - Dual persistence: Supabase FIRST (durable source of truth), Redis SECOND (fast cache)
    - Temp students: Redis only, default state "active", no Supabase calls
    - Session ENDED trigger: Automatically saves memory for the Teacher Voice, then flips to IDLE
    
Memory Flow:
    set_state("ended") → _on_session_ended() → save_session_summary() + save_student_memory()
    → auto-flip to IDLE
    Next login → _build_memory_context() → "LAST SESSION: biology - diffusion."
    (The context builder produces structured labels, not narrative text.)

Score-based memory rules:
    - Score >= 0.8: Mark as strong, remove from struggles
    - Score < 0.5: Mark as struggling using real data
    - No score data: Fall back to keyword auto-detection (with negation awareness)
    - Score >= 0.9 AND completed: Mark as mastered
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.state")


class StudentState(Enum):
    """All possible states a student can be in."""
    ONBOARDING = "onboarding"          # First contact, temp student, learning name/level
    ACTIVE = "active"                  # Session in progress — Wax decides the flow
    ENDED = "ended"                    # Session just finished — triggers memory save
    IDLE = "idle"                      # Between sessions, waiting for student to return


# ── Old state remapping for backward compatibility ──────────────────────
# Students with legacy state values get silently migrated on read.
# A one-time DB migration should also be run:
#   UPDATE students SET current_state = 'active' WHERE current_state IN
#     ('in_lesson', 'in_practice', 'stuck', 'asking_question', 'paused', 'chatting', 'in_exam_mode');
#   UPDATE students SET current_state = 'idle' WHERE current_state IN ('greeting', 'idle');

OLD_STATE_MAP = {
    "greeting": "idle",
    "in_lesson": "active",
    "in_practice": "active",
    "stuck": "active",
    "asking_question": "active",
    "paused": "active",
    "chatting": "active",
    "in_exam_mode": "active",
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
    Temp students use Redis only — no Supabase queries.
    Checks Redis first (fast), falls back to database (durable).
    On database fallback, repopulates Redis cache.
    
    Args:
        student_id: Student database ID
        
    Returns:
        State string (e.g., "active") or None
    """
    # Basic validation to save a database round-trip
    if not student_id or not student_id.strip():
        logger.warning("get_state called with empty student_id")
        return None
    
    # ── Temp students: Redis only, default "active" ──
    if student_id.startswith("temp_"):
        key = f"student_state:{student_id}"
        try:
            cached = redis_client.get(key)
            if cached:
                decoded = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                if decoded:
                    # Remap old state values for temp students too
                    if decoded in OLD_STATE_MAP:
                        logger.warning(
                            f"Temp student {student_id} has old state '{decoded}' — "
                            f"remapping to '{OLD_STATE_MAP[decoded]}'"
                        )
                        return OLD_STATE_MAP[decoded]
                    return decoded
        except Exception as e:
            logger.error(f"Redis get_state error for temp student {student_id}: {e}")
        # Default state for temp students — they're always active
        return StudentState.ACTIVE.value
    
    # ── Registered students: Redis first, Supabase fallback ──
    # Check Redis first
    key = f"student_state:{student_id}"
    try:
        cached = redis_client.get(key)
        if cached:
            decoded = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            if decoded:
                # Remap old state values silently
                if decoded in OLD_STATE_MAP:
                    logger.warning(
                        f"Student {student_id} has old state '{decoded}' in Redis — "
                        f"remapping to '{OLD_STATE_MAP[decoded]}'"
                    )
                    return OLD_STATE_MAP[decoded]
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
            
            # Remap old state values from database
            if state in OLD_STATE_MAP:
                logger.warning(
                    f"Student {student_id} has old state '{state}' in DB — "
                    f"remapping to '{OLD_STATE_MAP[state]}'"
                )
                state = OLD_STATE_MAP[state]
            
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

    return None


async def set_state(
    student_id: str,
    new_state: str,
    reason: str = "",
    session_context: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Change a student's state. Returns True if successful.
    
    No transition whitelist — any valid state is accepted.
    Prevents impossible state jumps that would confuse the backend trigger pipeline.
    Temp students: Redis only, no Supabase calls, no session memory.
    Registered students: Persists to Supabase FIRST, then Redis.
    
    If transitioning to ENDED, automatically saves a session summary
    and updates student memory for the Teacher Memory Voice (registered only),
    then auto-flips to IDLE so the student is ready for the next session.
    
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
    # Only validation: is this a real state?
    try:
        target_state = StudentState(new_state)
    except ValueError:
        logger.error(f"set_state failed: invalid target state '{new_state}'")
        return False

    is_temp = student_id.startswith("temp_")
    
    # ── Temp students: Redis only ──
    if is_temp:
        current_state_str = await get_state(student_id)
        if not current_state_str:
            current_state_str = StudentState.ACTIVE.value
        
        # Save to Redis only
        key = f"student_state:{student_id}"
        try:
            redis_client.setex(key, STATE_CACHE_TTL, new_state)
            logger.info(
                f"STATE TRANSITION (temp): {student_id}: "
                f"{current_state_str} → {new_state}"
                + (f" | Reason: {reason}" if reason else "")
            )
            return True
        except Exception as e:
            logger.error(f"Redis set_state error for temp {student_id}: {e}")
            return False
    
    # ── Registered students: full persistence ──
    current_state_str = await get_state(student_id)
    if not current_state_str:
        logger.warning(f"set_state failed: student {student_id} not found")
        return False

    # Log the transition
    logger.info(
        f"STATE TRANSITION: {student_id}: {current_state_str} → {new_state}"
        + (f" | Reason: {reason}" if reason else "")
    )

    # ── 1. Save to database FIRST (durable source of truth) ──
    db_saved = False
    try:
        supabase.table("students") \
            .update({"current_state": new_state}) \
            .eq("id", student_id) \
            .execute()
        db_saved = True
    except Exception as e:
        logger.error(f"Database set_state error for {student_id}: {e}")

    # ── 2. Save to Redis SECOND (fast cache) ──
    # Only cache if database write succeeded — prevents stale cache
    key = f"student_state:{student_id}"
    redis_saved = False
    if db_saved:
        try:
            redis_client.setex(key, STATE_CACHE_TTL, new_state)
            redis_saved = True
        except Exception as e:
            logger.error(f"Redis set_state error for {student_id}: {e}")
            # Redis failure is non-critical — database has the truth
    else:
        logger.warning(
            f"Skipping Redis cache for {student_id} — database write failed, "
            f"don't want stale state in cache"
        )

    # ── Warn if neither save succeeded ──
    if not db_saved and not redis_saved:
        logger.critical(
            f"set_state COMPLETELY FAILED for {student_id}: "
            f"neither database nor Redis saved!"
        )
        return False

    # ── Session ENDED → Save memory (non-blocking), then flip to IDLE ──
    if target_state == StudentState.ENDED:
        try:
            await _on_session_ended(student_id, session_context or {})
        except Exception as e:
            logger.error(
                f"Session memory save failed for {student_id}: {e}",
                exc_info=True
            )
            # Don't block — state change succeeded, memory is non-critical
        
        # Auto-flip to IDLE so next message triggers a fresh welcome
        try:
            await set_state(student_id, StudentState.IDLE.value, reason="Auto-flip after session ended")
        except Exception as e:
            logger.error(f"Auto-flip to IDLE failed for {student_id}: {e}")

    return True


# ═══════════════════════════════════════════════
# SESSION ENDED HANDLER
# ═══════════════════════════════════════════════

async def _on_session_ended(student_id: str, context: Dict[str, Any]) -> None:
    """
    Called automatically when a student's state changes to ENDED.
    
    Saves a session summary and updates persistent student memory
    so Wax remembers what happened next time the student returns.
    
    Memory rules (ordered by priority):
    1. Score >= 0.8: Mark as strong, REMOVE from struggles
    2. Score < 0.5: Mark as struggling using real data
    3. No score data: Fall back to keyword auto-detection (with negation awareness)
    4. Score >= 0.9 AND completed: Mark as mastered
    
    Score data ALWAYS wins over keyword guessing.
    
    Args:
        student_id: Student database ID
        context: Session details with optional keys:
            subject, topic, completed, score, struggled_with
    """
    # Skip for temp students — no persistent memory to save
    if student_id.startswith("temp_"):
        return
    
    # Import here to avoid circular dependency at module level
    from database.conversations import (
        save_session_summary,
        save_student_memory,
        get_history
    )

    # ── Extract context ──
    subject = context.get("subject", "unknown")
    topic = context.get("topic", "unknown")
    completed = context.get("completed", True)
    score = context.get("score")  # Optional — may be None
    struggled_with = list(context.get("struggled_with", []))

    # If no explicit struggles, try to detect from conversation
    # (Only runs if no score data available — score wins over keywords)
    # TODO Phase 2: Replace keyword detection with Silent Guide signal data
    if not struggled_with and score is None:
        try:
            recent_history = await get_history(student_id)
            if recent_history:
                recent_history = recent_history[-10:]
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
                            # Check for negation: "NOT hard", "isn't confusing",
                            # "no longer struggling"
                            idx = content.find(keyword)
                            before = content[max(0, idx-15):idx]
                            negated = any(neg in before for neg in [
                                "not ", "isn't ", "wasn't ", "no longer ",
                                "not as ", "don't ", "doesn't ", "arent ",
                                "won't ",
                            ])
                            if not negated:
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
    # Score-based rules: real performance data ALWAYS wins over keyword guessing
    memory_updates: Dict[str, Any] = {}

    # Rule 1: Check score FIRST — it's the highest-quality signal
    if score is not None and score >= 0.8:
        # High score = strong. Remove from struggles if auto-detection added it.
        memory_updates["strong_in"] = [topic]
        if topic in struggled_with:
            struggled_with.remove(topic)
        logger.info(f"Memory: {student_id} is strong in {topic} (score: {score})")
    
    elif score is not None and score < 0.5:
        # Low score = struggling. Confirm with real data.
        if topic not in struggled_with:
            struggled_with.append(topic)
        memory_updates["struggles_with"] = struggled_with
        logger.info(f"Memory: {student_id} scored low on {topic} (score: {score})")
    
    else:
        # No score data available — fall back to keyword detection
        if struggled_with:
            memory_updates["struggles_with"] = struggled_with
            logger.info(
                f"Memory: {student_id} struggles with {struggled_with} "
                f"(from keywords)"
            )
    
    # Rule 2: Mastery requires BOTH high score AND completion
    if completed and score is not None and score >= 0.9:
        memory_updates["topics_mastered"] = [topic]
        # Also clear from struggles if they were there
        if topic in struggled_with:
            struggled_with.remove(topic)
            memory_updates["struggles_with"] = struggled_with
        logger.info(f"Memory: {student_id} mastered {topic} (score: {score})")

    # Rule 3: Increment session count
    # Pass the FINAL value (current + 1). save_student_memory will OVERWRITE,
    # not add again — prevents double-increment.
    try:
        from database.conversations import get_student_memory
        existing_memory = await get_student_memory(student_id)
        current_sessions = (
            existing_memory.get("sessions_completed", 0)
            if existing_memory else 0
        )
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
        logger.info(
            f"Student memory updated for {student_id}: "
            f"{list(memory_updates.keys())}"
        )
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
        state: State string to check (e.g., "active")
        
    Returns:
        True if student is in the specified state
    """
    current = await get_state(student_id)
    return current == state


async def force_state(
    student_id: str,
    new_state: str,
    admin_id: str = "unknown"
) -> bool:
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
            "performed_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")

    return True


async def clear_state(student_id: str) -> None:
    """
    Remove state from cache and set to idle in database.
    
    Used on account deletion or complete reset.
    A reset student never has an undefined state.
    """
    logger.info(f"Clearing state for {student_id}")
    
    key = f"student_state:{student_id}"
    try:
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"clear_state Redis error: {e}")

    try:
        supabase.table("students") \
            .update({"current_state": "idle"}) \
            .eq("id", student_id) \
            .execute()
    except Exception as e:
        logger.error(f"clear_state database error: {e}")
