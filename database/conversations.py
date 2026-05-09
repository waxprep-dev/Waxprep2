"""
WaxPrep v2 — Conversation History & Memory Store
Stores and retrieves recent messages, session summaries, and persistent
student memory so Wax remembers who each student is across sessions.

Storage format:
    - Conversation History: Redis Lists (RPUSH + LTRIM, atomic)
    - Session Summaries: Redis Strings (JSON, 30-day TTL)
    - Student Memory: Redis Strings (JSON, 90-day TTL, order-preserving merge)
"""

from database.client import redis_client
from datetime import datetime, timezone
import json
import logging

logger = logging.getLogger("waxprep.conversations")

# ── Conversation History ──────────────────────
HISTORY_MAX_LENGTH = 50   # Store up to 50 messages
HISTORY_TTL = 86400 * 14  # 14 days (covers weekend-only students who study Saturdays)


async def save_message(student_id: str, role: str, content: str):
    """
    Save a message to the student's conversation history atomically.
    
    Uses Redis List (RPUSH + LTRIM in pipeline) for atomic append-and-cap.
    No read-modify-write race condition. Messages cannot be lost.
    
    Args:
        student_id: Student's database ID
        role: "user" or "assistant" (validated)
        content: Message content (truncated to 5000 chars)
    """
    # Validate role
    if role not in ("user", "assistant"):
        logger.warning(f"Invalid role '{role}' for student {student_id}. Defaulting to 'user'.")
        role = "user"
    
    # Truncate content to prevent memory abuse from buggy/malicious callers
    content = content[:5000]
    
    key = f"conversation:{student_id}"
    try:
        message_json = json.dumps({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Atomic: push to list, trim to max length, set TTL
        pipe = redis_client.pipeline()
        pipe.rpush(key, message_json)
        pipe.ltrim(key, -HISTORY_MAX_LENGTH, -1)
        pipe.expire(key, HISTORY_TTL)
        pipe.execute()
        
    except Exception as e:
        logger.error(f"Conversation save error for {student_id}: {e}")


async def get_history(student_id: str, limit: int = 20) -> list:
    """
    Get the student's recent conversation history.
    
    Fetches only the last `limit` messages directly from Redis using LRANGE.
    No loading of excess data — efficient at scale.
    
    Args:
        student_id: Student's database ID
        limit: Number of recent messages to return (default 20)
        
    Returns:
        List of message dicts: [{"role": "user/assistant", "content": "...", "timestamp": "..."}]
    """
    key = f"conversation:{student_id}"
    try:
        # Fetch only the last `limit` messages directly from Redis
        raw_messages = redis_client.lrange(key, -limit, -1)
        if raw_messages:
            history = []
            for msg in raw_messages:
                msg_str = msg.decode("utf-8") if isinstance(msg, bytes) else msg
                try:
                    history.append(json.loads(msg_str))
                except json.JSONDecodeError:
                    logger.warning(f"Corrupted message in history for {student_id}, skipping")
                    continue
            return history
    except Exception as e:
        logger.error(f"Conversation load error for {student_id}: {e}")
    return []


async def clear_history(student_id: str):
    """Clear conversation history permanently."""
    key = f"conversation:{student_id}"
    try:
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"Conversation clear error for {student_id}: {e}")


# ── Session Summaries (for Teacher Memory Voice) ──

SESSION_SUMMARY_TTL = 86400 * 30  # 30 days


async def save_session_summary(student_id: str, summary: dict):
    """
    Store a summary of the last teaching session.
    
    Args:
        student_id: Student's database ID
        summary: Dict with keys:
            - subject: str (e.g. "Biology")
            - topic: str (e.g. "Diffusion")
            - completed: bool
            - score: float or None (e.g. 0.8 for 80%)
            - struggled_with: list (e.g. ["membrane concept"])
            - ended_at: str (ISO timestamp)
    """
    key = f"session_summary:{student_id}"
    try:
        # Create a copy so we don't mutate the caller's dict
        summary_to_save = {
            **summary,
            "saved_at": datetime.now(timezone.utc).isoformat()
        }
        redis_client.setex(key, SESSION_SUMMARY_TTL, json.dumps(summary_to_save))
    except Exception as e:
        logger.error(f"Session summary save error for {student_id}: {e}")


async def get_session_summary(student_id: str) -> dict | None:
    """
    Get the last session summary.
    
    Returns:
        Dict with session summary, or None if no previous session exists.
    """
    key = f"session_summary:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.error(f"Session summary load error for {student_id}: {e}")
    return None


# ── Student Memory (persistent knowledge about the student) ──

STUDENT_MEMORY_TTL = 86400 * 90  # 90 days


async def save_student_memory(student_id: str, memory_updates: dict):
    """
    Update persistent knowledge about a student.
    Merges with existing memory so nothing is lost.
    
    Merge rules:
        - sessions_completed: OVERWRITE (caller already computed correct value)
        - Lists: APPEND new items, preserve order, no duplicates
        - Other fields: SET directly
    
    Args:
        student_id: Student's database ID
        memory_updates: Dict with keys:
            - struggles_with: list of topics
            - strong_in: list of topics
            - topics_mastered: list of topics
            - sessions_completed: int (caller passes FINAL value, not delta)
    """
    key = f"student_memory:{student_id}"
    try:
        raw = redis_client.get(key)
        memory = json.loads(raw) if raw else {}

        # Merge updates
        for k, v in memory_updates.items():
            if k == "sessions_completed":
                # Caller already computed the correct value (current + 1).
                # Overwrite, don't add — prevents double-increment.
                memory[k] = v
            elif isinstance(v, list) and k in memory and isinstance(memory[k], list):
                # Merge lists without duplicates, PRESERVING ORDER.
                # New items are appended to the end so [-N:] returns most recent.
                existing = memory[k]
                for item in v:
                    if item not in existing:
                        existing.append(item)
                memory[k] = existing
            else:
                memory[k] = v

        redis_client.setex(key, STUDENT_MEMORY_TTL, json.dumps(memory))
    except Exception as e:
        logger.error(f"Student memory save error for {student_id}: {e}")


async def get_student_memory(student_id: str) -> dict:
    """
    Get everything Wax knows about this student.
    
    Returns:
        Dict with memory fields, or empty dict if no memory exists yet.
    """
    key = f"student_memory:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.error(f"Student memory load error for {student_id}: {e}")
    return {}
