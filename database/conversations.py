"""
WaxPrep v2 — Conversation History Store
Stores and retrieves recent messages for AI context.
"""

from database.client import redis_client
import json

HISTORY_MAX_LENGTH = 20  # Keep last 20 messages per student
HISTORY_TTL = 7200  # 2 hours


async def save_message(student_id: str, role: str, content: str):
    """
    Save a message to the student's conversation history.
    role: "user" or "assistant"
    """
    key = f"conversation:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            history = json.loads(raw)
        else:
            history = []
        
        history.append({"role": role, "content": content})
        
        if len(history) > HISTORY_MAX_LENGTH:
            history = history[-HISTORY_MAX_LENGTH:]
        
        redis_client.setex(key, HISTORY_TTL, json.dumps(history))
    except Exception as e:
        print(f"Conversation save error: {e}")


async def get_history(student_id: str) -> list:
    """
    Get the student's recent conversation history.
    Returns list of {"role": "user/assistant", "content": "..."}
    """
    key = f"conversation:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            return json.loads(raw)
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
