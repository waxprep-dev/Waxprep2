"""
WaxPrep v2 — Onboarding State Store
Stores onboarding progress for unregistered users in Redis.
This is SEPARATE from the conversation system because anonymous
users don't exist in Supabase yet.

Redis key format: onboarding:{platform}:{user_id}
Example: onboarding:telegram:123456789
"""

import json
from database.client import redis_client

ONBOARDING_STATE_TTL = 3600  # 1 hour to complete onboarding


async def get_onboarding_state(platform: str, user_id: str) -> dict:
    """
    Load the current onboarding step for an unregistered user.
    Returns empty dict if this is their very first message.
    """
    key = f"onboarding:{platform}:{user_id}"
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        print(f"get_onboarding_state error: {e}")
    return {}


async def save_onboarding_state(platform: str, user_id: str, state: dict):
    """
    Save the current onboarding step. Called after every step.
    The state includes at minimum: {'awaiting_response_for': 'step_name', ...}
    """
    key = f"onboarding:{platform}:{user_id}"
    try:
        redis_client.setex(
            key,
            ONBOARDING_STATE_TTL,
            json.dumps(state, default=str)
        )
    except Exception as e:
        print(f"save_onboarding_state error: {e}")


async def clear_onboarding_state(platform: str, user_id: str):
    """
    Delete the state after account creation. Keeps Redis clean.
    """
    key = f"onboarding:{platform}:{user_id}"
    try:
        redis_client.delete(key)
    except Exception as e:
        print(f"clear_onboarding_state error: {e}")
