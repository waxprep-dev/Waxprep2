"""
WaxPrep v2 — Database Clients
Supabase + Redis connections. Import these anywhere you need the database.
"""

from supabase import create_client, Client
from config.settings import settings
import redis
from functools import lru_cache


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Returns a cached Supabase client. Created once, reused forever."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@lru_cache(maxsize=1)
def get_redis():
    """Returns a cached Redis client. Created once, reused forever."""
    if not settings.REDIS_URL:
        raise ValueError("REDIS_URL must be set")
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )


# These are what you import in other files:
#   from database.client import supabase
#   from database.client import redis_client
supabase = get_supabase()
redis_client = get_redis()
