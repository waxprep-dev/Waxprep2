"""
WaxPrep v2 — State Machine
Defines every state a student can be in and what transitions are allowed.
This is the brain's foundation — everything else depends on this.
"""

from enum import Enum
from typing import Optional
from database.client import supabase, redis_client


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


# ── Allowed transitions ──────────────────────
# A state can only change to certain other states.
# This prevents schizophrenic behavior.

ALLOWED_TRANSITIONS = {
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
}


# ── State Manager ────────────────────────────

async def get_state(student_id: str) -> str:
    """
    Get the current state for a student.
    Defaults to IDLE for existing students, ONBOARDING for new.
    """
    # Check Redis first (fast)
    key = f"student_state:{student_id}"
    try:
        cached = redis_client.get(key)
        if cached:
            return cached
    except Exception:
        pass

    # Fall back to database
    try:
        result = (
            supabase.table("students")
            .select("onboarding_complete")
            .eq("id", student_id)
            .execute()
        )
        if result.data:
            is_complete = result.data[0].get("onboarding_complete", False)
            state = StudentState.IDLE.value if is_complete else StudentState.ONBOARDING.value
            # Cache it
            try:
                redis_client.setex(key, 3600, state)
            except Exception:
                pass
            return state
    except Exception:
        pass

    return StudentState.IDLE.value


async def set_state(student_id: str, new_state: str) -> bool:
    """
    Change a student's state. Returns True if successful.
    Validates the transition before saving.
    """
    current_state_str = await get_state(student_id)

    # Parse current state
    try:
        current_state = StudentState(current_state_str)
    except ValueError:
        current_state = StudentState.IDLE

    # Parse new state
    try:
        target_state = StudentState(new_state)
    except ValueError:
        return False

    # Check if transition is allowed
    if target_state not in ALLOWED_TRANSITIONS.get(current_state, []):
        print(f"State transition blocked: {current_state.value} → {new_state}")
        return False

    # Save to Redis
    key = f"student_state:{student_id}"
    try:
        redis_client.setex(key, 3600, new_state)
    except Exception as e:
        print(f"State save error: {e}")
        return False

    return True


async def is_in_state(student_id: str, state: str) -> bool:
    """Check if student is in a specific state."""
    current = await get_state(student_id)
    return current == state


async def force_state(student_id: str, new_state: str):
    """
    Force a state change without validation.
    Use only for admin/reset operations.
    """
    key = f"student_state:{student_id}"
    try:
        redis_client.setex(key, 3600, new_state)
    except Exception:
        pass


async def clear_state(student_id: str):
    """Remove state from cache (on account deletion)."""
    key = f"student_state:{student_id}"
    try:
        redis_client.delete(key)
    except Exception:
        pass
