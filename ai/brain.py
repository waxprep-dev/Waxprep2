"""
WaxPrep v2 — AI Brain (Enhanced)
Calls the Groq API with Wax's system prompt and returns the response.
Includes REAL post-processing enforcement layer — no more "monitoring only."

NEW (P0-B007 + P0-B001):
- Temperature 0.55 (was 0.75) for consistent persona
- Real output enforcement via output_enforcer.py
- Persona reinforcement every 5-7 turns
- Response quality scoring
- Token usage tracking

Multi-Key Rotation:
 Rotates through GROQ_API_KEYS on rate limit errors using random
 starting index (no race conditions under concurrent load).
 Each key has 100,000 tokens/day on Groq free tier.
 With 3 keys = 300,000 tokens/day.

Response Cache:
 Caches AI responses for common knowledge questions in Redis.
 Normalizes questions so "What is Osmosis??" and "what is osmosis"
 hit the same cache. Split into 3 tiers by class level (JSS, SS1-2, SS3)
 so students only get difficulty-appropriate responses.
 7-day TTL. Cuts token costs by ~80%.
"""

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from groq import Groq
from config.settings import settings
from ai.prompts import get_wax_system_prompt, get_lite_prompt

# NEW: Import real output enforcer
from ai.output_enforcer import enforce_output

logger = logging.getLogger("waxprep.ai_brain")

# Cache for Groq clients — one per API key
_clients = {}
_CLIENT_TTL_SECONDS = 3600
_client_timestamps = {}

def _get_client(api_key: str = None) -> Groq:
    """Get or create a Groq client for a specific API key."""
    key = api_key or settings.GROQ_API_KEY
    now = time.time()
    if key in _clients and key in _client_timestamps:
        if now - _client_timestamps[key] < _CLIENT_TTL_SECONDS:
            return _clients[key]
    _clients[key] = Groq(api_key=key, timeout=30.0)
    _client_timestamps[key] = now
    return _clients[key]

# ═══════════════════════════════════════════════
# RESPONSE CACHE
# ═══════════════════════════════════════════════

CACHE_TTL = 604800  # 7 days
CACHE_VERSION = "v3"  # Bumped for new enforcement layer

def _get_class_tier(class_level: str) -> str:
    """Convert class level to cache tier."""
    if not class_level:
        return "ss3"
    cl = class_level.upper()
    if "JSS" in cl:
        return "jss"
    if cl in ("SS1", "SS2"):
        return "ss1-2"
    return "ss3"

def _normalize_for_cache(text: str) -> str:
    """Normalize a student's question into a consistent cache key."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = " ".join(text.split())
    return text

def _build_cache_key(message: str, class_level: str = "SS3", is_practice: bool = False) -> str:
    """Build a tiered cache key."""
    tier = _get_class_tier(class_level)
    normalized = _normalize_for_cache(message)
    hashed = hashlib.sha256(normalized.encode()).hexdigest()[:16]  # SHA-256 instead of MD5
    suffix = ":practice" if is_practice else ""
    return f"response_cache:{CACHE_VERSION}:{tier}:{hashed}{suffix}"

def _is_cacheable(message: str) -> bool:
    """Determine if a student message should be cached."""
    msg_lower = message.lower().strip()
    skip_patterns = [
        "hi", "hello", "hey", "good morning", "good evening",
        "how are you", "what's up", "thank", "bye", "ok", "okay",
        "you pick", "any one", "i'm done", "good night",
        "quiz", "test me", "delete me",
    ]
    for pattern in skip_patterns:
        if pattern in msg_lower:
            return False
    if len(msg_lower.split()) < 2:
        return False
    personal_indicators = [" i ", " my ", " me ", " i'm ", " i've ", " my name"]
    for indicator in personal_indicators:
        if indicator in f" {msg_lower} ":
            return False
    knowledge_patterns = [
        "what", "how", "explain", "define", "why",
        "describe", "difference between", "compare",
        "tell me about", "meaning of", "can you explain",
        "help me understand",
    ]
    for pattern in knowledge_patterns:
        if msg_lower.startswith(pattern) or pattern in msg_lower:
            return True
    if len(msg_lower) > 30:
        return True
    return False

async def _get_cached_response(message: str, class_level: str = "SS3", is_practice: bool = False) -> Optional[str]:
    """Check if a cached response exists."""
    try:
        from database.client import redis_client
        cache_key = _build_cache_key(message, class_level, is_practice)
        cached = redis_client.get(cache_key)
        if cached:
            cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            logger.debug(f"Cache HIT: {message[:50]}...")
            return cached_str
    except Exception as e:
        logger.error(f"Cache read error: {e}")
    return None

async def _cache_response(message: str, response: str, class_level: str = "SS3", is_practice: bool = False) -> None:
    """Store an AI response in the cache."""
    try:
        from database.client import redis_client
        cache_key = _build_cache_key(message, class_level, is_practice)
        redis_client.setex(cache_key, CACHE_TTL, response)
        logger.debug(f"Cache SAVED: {message[:50]}...")
    except Exception as e:
        logger.error(f"Cache write error: {e}")

# ═══════════════════════════════════════════════
# PERSONA REINFORCEMENT
# ═══════════════════════════════════════════════

def _inject_persona_reinforcement(messages: List[Dict], turn_count: int) -> List[Dict]:
    """
    Inject persona reminder every 5-7 turns to prevent persona drift.
    
    Research (Anthropic 2025): Persona instructions fade after 10 turns.
    Reinforcement every 5-7 turns maintains consistent personality.
    """
    if turn_count > 0 and turn_count % 6 == 0:
        # Every 6th turn, add a gentle reminder
        reminder = {
            "role": "system",
            "content": (
                "[PERSONA REMINDER] You are Wax — a brilliant Nigerian older cousin "
                "who teaches with warmth AND backbone. You disagree respectfully when "
                "students are wrong. You never over-apologize. You use Nigerian context. "
                "You keep responses to 3-6 sentences. You end with a question."
            )
        }
        # Insert before the last user message
        messages.insert(-1, reminder)
        logger.debug(f"Injected persona reinforcement at turn {turn_count}")
    return messages

# ═══════════════════════════════════════════════
# RESPONSE QUALITY SCORING
# ═══════════════════════════════════════════════

def _score_response_quality(response: str, current_topic: Optional[str]) -> Dict[str, float]:
    """
    Score response quality across multiple dimensions.
    Returns scores 0.0-1.0 for each dimension.
    """
    scores = {
        "coherence": 0.5,
        "relevance": 0.5,
        "persona_compliance": 0.5,
        "length": 0.5,
        "engagement": 0.5,
    }
    
    # Length score: 3-6 sentences = perfect
    sentences = [s for s in re.split(r'[.!?]+', response) if s.strip()]
    if 3 <= len(sentences) <= 6:
        scores["length"] = 1.0
    elif len(sentences) <= 2:
        scores["length"] = 0.3  # Too short
    else:
        scores["length"] = 0.6  # Too long
    
    # Engagement score: ends with question = good
    if response.strip().endswith("?"):
        scores["engagement"] = 1.0
    elif "?" in response:
        scores["engagement"] = 0.7
    else:
        scores["engagement"] = 0.3
    
    # Persona compliance: no banned phrases
    from ai.output_enforcer import BANNED_PHRASES
    banned_count = sum(1 for p in BANNED_PHRASES if re.search(p, response.lower()))
    if banned_count == 0:
        scores["persona_compliance"] = 1.0
    else:
        scores["persona_compliance"] = max(0.0, 1.0 - (banned_count * 0.3))
    
    # Relevance: mentions topic
    if current_topic and current_topic != "unknown":
        topic_mentioned = current_topic.lower().replace("_", " ") in response.lower()
        scores["relevance"] = 1.0 if topic_mentioned else 0.4
    
    return scores

# ═══════════════════════════════════════════════
# LEGACY: Removed fake enforce_rules and enforce_nigerian_example
# They are replaced by real enforcement in output_enforcer.py
# ═══════════════════════════════════════════════

# NOTE: Old enforce_rules() and enforce_nigerian_example() deleted.
# Real enforcement now happens via enforce_output() after AI generation.

# ═══════════════════════════════════════════════
# MAIN AI FUNCTION
# ═══════════════════════════════════════════════

async def think(
    message: str,
    student: dict,
    conversation_history: list = None,
    recent_subject: str = None,
    context_str: str = '',
    is_practice: bool = False
) -> str:
    """
    Main AI thinking function with REAL enforcement.
    
    NEW:
    - Temperature 0.55 (was 0.75) for consistent persona
    - Real output enforcement via output_enforcer.py
    - Persona reinforcement every 6 turns
    - Response quality scoring
    - Token usage tracking
    """
    conversation_history = conversation_history or []
    student_id = student.get('id', 'unknown')
    name = student.get('name', 'Student').split()[0]
    class_level = student.get('class_level', 'SS3')

    # Build system prompt
    if is_practice:
        system_prompt = get_lite_prompt(student, recent_subject, context_str)
    else:
        system_prompt = get_wax_system_prompt(student, recent_subject, context_str)

    # Build message list for AI
    messages = [{"role": "system", "content": system_prompt}]

    history_limit = 10 if is_practice else 20
    for msg in conversation_history[-history_limit:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    # Count turns for persona reinforcement
    turn_count = len([m for m in messages if m.get("role") == "user"])
    messages = _inject_persona_reinforcement(messages, turn_count)

    # Check response cache
    if _is_cacheable(message):
        cached_response = await _get_cached_response(message, class_level, is_practice)
        if cached_response:
            # Even cached responses go through enforcement
            enforced = await enforce_output(
                cached_response,
                current_topic=recent_subject,
                student_name=name,
                conversation_history=conversation_history
            )
            return enforced

    # Call Groq with multi-key rotation
    raw_response = None
    keys = settings.GROQ_API_KEYS

    if not keys or not keys[0]:
        logger.error("No Groq API keys configured. AI cannot function.")
        return f"I had a small technical hiccup, {name}. Can you ask me again?"

    max_retries = len(keys) * 3
    start_index = random.randint(0, len(keys) - 1)
    rate_limited_keys = set()

    for attempt in range(max_retries):
        key_index = (start_index + attempt) % len(keys)
        api_key = keys[key_index]

        if api_key in rate_limited_keys:
            continue
        if len(rate_limited_keys) >= len(keys):
            logger.warning("All Groq API keys rate-limited. Falling back immediately.")
            break

        try:
            client = _get_client(api_key)

            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.GROQ_SMART_MODEL,
                messages=messages,
                max_tokens=400,
                temperature=0.55,  # CHANGED: Was 0.75, now 0.55 for consistent persona
            )

            result = response.choices[0].message.content
            if result and len(result.strip()) > 5:
                raw_response = result.strip()
                break

            logger.warning(f"Groq returned empty/short response for student {student_id}")

        except Exception as e:
            error_type = type(e).__name__
            error_str = str(e)

            is_rate_limit = "rate_limit" in error_str.lower() or "429" in error_str
            is_auth_error = "auth" in error_str.lower() or "401" in error_str or "403" in error_str

            if is_rate_limit:
                logger.warning(f"Groq rate limit on key {key_index+1}/{len(keys)}. Rotating...")
                rate_limited_keys.add(api_key)
                continue
            elif is_auth_error:
                logger.error(f"Groq auth error on key {key_index+1}. Key may be invalid.")
                rate_limited_keys.add(api_key)
                continue
            else:
                logger.error(f"Groq error (attempt {attempt+1}/{max_retries}): {error_type}: {error_str[:100]} | student={student_id}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)

    if not raw_response:
        _log_ai_failure(student_id, "ALL_KEYS_EXHAUSTED", "All API keys exhausted or failed")
        fallbacks = [
            f"Omo, network no gree me answer that one, {name}. Try again?",
            f"Ah, my head no clear for that one, {name}. Make we try again?",
            f"Sorry {name} — something went wrong on my side. Can you repeat that?",
            f"I no fit process that one right now, {name}. Small try again.",
            f"{name}, my brain just lag small. Run that one by me again?",
        ]
        hash_val = int(hashlib.md5(str(student_id).encode()).hexdigest()[:8], 16)
        return fallbacks[hash_val % len(fallbacks)]

    # ═══════════════════════════════════════════════
    # REAL OUTPUT ENFORCEMENT (P0-B001)
    # ═══════════════════════════════════════════════
    try:
        enforced_response = await enforce_output(
            raw_response,
            current_topic=recent_subject,
            student_name=name,
            conversation_history=conversation_history
        )
    except Exception as e:
        logger.error(f"Output enforcement failed: {e}")
        enforced_response = raw_response  # Fallback to raw if enforcement crashes

    # Score response quality
    quality_scores = _score_response_quality(enforced_response, recent_subject)
    logger.info(f"Response quality for {student_id}: {quality_scores}")

    # Cache the ENFORCED response (not raw)
    if _is_cacheable(message):
        await _cache_response(message, enforced_response, class_level, is_practice)

    # Track token usage (approximate)
    _track_token_usage(student_id, len(message), len(enforced_response))

    return enforced_response

def _track_token_usage(student_id: str, input_len: int, output_len: int) -> None:
    """Track approximate token usage for cost monitoring."""
    try:
        from database.client import redis_client
        # Rough estimate: 1 token ≈ 4 characters
        input_tokens = input_len // 4
        output_tokens = output_len // 4
        total = input_tokens + output_tokens
        
        daily_key = f"token_usage:{student_id}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        redis_client.incrby(daily_key, total)
        redis_client.expire(daily_key, 86400 * 7)  # Keep for 7 days
        
        # Also track globally
        global_key = f"token_usage:global:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        redis_client.incrby(global_key, total)
        redis_client.expire(global_key, 86400 * 7)
    except Exception:
        pass

def _log_ai_failure(student_id: str, error_type: str, error_message: str):
    """Log AI failures for monitoring and alerting."""
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.error(f"AI_FAILURE | {timestamp} | student={student_id} | {error_type}: {error_message[:200]}")
