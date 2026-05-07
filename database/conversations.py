"""
WaxPrep v2 — Conversation History & Memory Store
Stores and retrieves recent messages, session summaries, and persistent
student memory so Wax remembers who each student is across sessions.
"""

from database.client import redis_client
from datetime import datetime, timezone
import json

# ── Conversation History ──────────────────────
HISTORY_MAX_LENGTH = 50   # Store up to 50 messages (retrieve 20 for AI)
HISTORY_TTL = 86400 * 7   # 7 days (was 2 hours — much too short)


async def save_message(student_id: str, role: str, content: str):
    """
    Save a message to the student's conversation history.
    role: "user" or "assistant"
    Each message includes a UTC timestamp.
    """
    key = f"conversation:{student_id}"
    try:
        raw = redis_client.get(key)
        history = json.loads(raw) if raw else []

        history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        # Keep only the last N messages
        if len(history) > HISTORY_MAX_LENGTH:
            history = history[-HISTORY_MAX_LENGTH:]

        redis_client.setex(key, HISTORY_TTL, json.dumps(history))
    except Exception as e:
        print(f"Conversation save error: {e}")


async def get_history(student_id: str, limit: int = 20) -> list:
    """
    Get the student's recent conversation history.
    Returns last `limit` messages as [{"role": "user/assistant", "content": "...", "timestamp": "..."}]
    """
    key = f"conversation:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            history = json.loads(raw)
            return history[-limit:] if len(history) > limit else history
    except Exception as e:
        print(f"Conversation load error: {e}")
    return []


async def clear_history(student_id: str):
    """Clear conversation history."""
    key = f"conversation:{student_id}"
    try:
        redis_client.delete(key)
    except Exception:
        pass


# ── Session Summaries (for Teacher Memory Voice) ──

SESSION_SUMMARY_TTL = 86400 * 30  # 30 days


async def save_session_summary(student_id: str, summary: dict):
    """
    Store a summary of the last teaching session.
    
    summary should contain:
        - subject: str (e.g. "Biology")
        - topic: str (e.g. "Diffusion")
        - completed: bool
        - score: float or None (e.g. 0.8 for 80%)
        - struggled_with: list (e.g. ["membrane concept"])
        - ended_at: str (ISO timestamp)
    """
    key = f"session_summary:{student_id}"
    try:
        summary["saved_at"] = datetime.now(timezone.utc).isoformat()
        redis_client.setex(key, SESSION_SUMMARY_TTL, json.dumps(summary))
    except Exception as e:
        print(f"Session summary save error: {e}")


async def get_session_summary(student_id: str) -> dict | None:
    """
    Get the last session summary.
    Returns None if no previous session exists.
    """
    key = f"session_summary:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        print(f"Session summary load error: {e}")
    return None


# ── Student Memory (persistent knowledge about the student) ──

STUDENT_MEMORY_TTL = 86400 * 90  # 90 days


async def save_student_memory(student_id: str, memory_updates: dict):
    """
    Update persistent knowledge about a student.
    Merges with existing memory so nothing is lost.
    
    memory_updates can include:
        - struggles_with: list of topics
        - strong_in: list of topics
        - topics_mastered: list of topics
        - sessions_completed: int (will increment)
        - last_compliment: str
        - preferred_pace: str ("slow", "medium", "fast")
    """
    key = f"student_memory:{student_id}"
    try:
        raw = redis_client.get(key)
        memory = json.loads(raw) if raw else {}

        # Merge updates
        for k, v in memory_updates.items():
            if k == "sessions_completed" and k in memory:
                memory[k] = memory[k] + v
            elif isinstance(v, list) and k in memory and isinstance(memory[k], list):
                # Merge lists without duplicates
                existing = set(memory[k])
                existing.update(v)
                memory[k] = list(existing)
            else:
                memory[k] = v

        redis_client.setex(key, STUDENT_MEMORY_TTL, json.dumps(memory))
    except Exception as e:
        print(f"Student memory save error: {e}")


async def get_student_memory(student_id: str) -> dict:
    """
    Get everything Wax knows about this student.
    Returns empty dict if no memory exists yet.
    """
    key = f"student_memory:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        print(f"Student memory load error: {e}")
    return {}
