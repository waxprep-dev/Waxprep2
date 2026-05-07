"""
WaxPrep v2 — AI Brain
Calls the Groq API with Wax's system prompt and returns the response.
Includes post-processing enforcement layer for critical rules.

Multi-Key Rotation:
    Rotates through GROQ_API_KEYS on rate limit errors.
    Each key has 100,000 tokens/day on Groq free tier.
    With 3 keys = 300,000 tokens/day = ~30 active students.

Response Cache:
    Caches AI responses for common knowledge questions in Redis.
    Normalizes questions so "What is Osmosis??" and "what is osmosis"
    hit the same cache. 7-day TTL. Cuts token costs by ~80%.
    Only caches knowledge questions — not greetings, quizzes, or personal messages.
"""

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone
from groq import Groq
from config.settings import settings
from ai.prompts import get_wax_system_prompt, get_lite_prompt

# Cache for Groq clients — one per API key
_clients = {}
# Track which key to try next (simple round-robin)
_current_key_index = 0


def _get_client(api_key: str = None) -> Groq:
    """
    Get or create a Groq client for a specific API key.
    
    Args:
        api_key: Specific API key to use. If None, uses default.
        
    Returns:
        Groq client instance
    """
    key = api_key or settings.GROQ_API_KEY
    
    if key not in _clients:
        _clients[key] = Groq(api_key=key)
    
    return _clients[key]


def _next_key() -> str:
    """
    Get the next API key in rotation.
    
    Uses module-level counter for simple round-robin.
    Thread-safe enough for async — worst case two requests use same key.
    
    Returns:
        API key string
    """
    global _current_key_index
    keys = settings.GROQ_API_KEYS
    
    if not keys or not keys[0]:
        return ""
    
    key = keys[_current_key_index % len(keys)]
    _current_key_index += 1
    
    return key


# ═══════════════════════════════════════════════
# RESPONSE CACHE
# ═══════════════════════════════════════════════

# Cache TTL: 7 days for teaching responses
CACHE_TTL = 604800  # 7 days in seconds


def _normalize_for_cache(text: str) -> str:
    """
    Normalize a student's question into a consistent cache key.
    
    Strips punctuation, extra spaces, and converts to lowercase
    so "What is Osmosis??" and "what is osmosis" produce the same key.
    
    Args:
        text: Raw student message
        
    Returns:
        Normalized cache key string
    """
    # Lowercase
    text = text.lower().strip()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse multiple spaces
    text = " ".join(text.split())
    return text


def _is_cacheable(message: str) -> bool:
    """
    Determine if a student message should be cached.
    
    Only cache knowledge questions (what, how, explain, define, etc.)
    Don't cache personal messages, greetings, or quiz commands.
    
    Args:
        message: Student's message
        
    Returns:
        True if this message type should be cached
    """
    msg_lower = message.lower().strip()
    
    # Don't cache these
    skip_patterns = [
        "hi", "hello", "hey", "good morning", "good evening",
        "how are you", "what's up", "thank", "bye", "ok", "okay",
        "you pick", "any one", "i'm done", "good night",
        "quiz", "test me", "delete me",
    ]
    
    for pattern in skip_patterns:
        if pattern in msg_lower:
            return False
    
    # Don't cache very short messages (single words, letters)
    if len(msg_lower.split()) < 2:
        return False
    
    # Don't cache messages with personal context (student name, "I", "my")
    # These need AI personalization
    personal_indicators = [" i ", " my ", " me ", " i'm ", " i've ", " my name"]
    for indicator in personal_indicators:
        if indicator in f" {msg_lower} ":
            return False
    
    # Cache knowledge questions
    knowledge_patterns = [
        "what", "how", "explain", "define", "why",
        "describe", "difference between", "compare",
        "tell me about", "meaning of",
    ]
    
    for pattern in knowledge_patterns:
        if msg_lower.startswith(pattern) or pattern in msg_lower:
            return True
    
    # Cache if message is long enough to be a real question
    if len(msg_lower) > 30:
        return True
    
    return False


async def _get_cached_response(message: str) -> str | None:
    """
    Check if a cached response exists for this message.
    
    Uses Redis for storage. Cache key is based on normalized message text.
    
    Args:
        message: Student's message
        
    Returns:
        Cached response string, or None if not cached
    """
    try:
        from database.client import redis_client
        
        cache_key = f"response_cache:{_normalize_for_cache(message)}"
        cached = redis_client.get(cache_key)
        
        if cached:
            # Decode bytes to string
            cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            print(f"Cache HIT: {message[:50]}...")
            return cached_str
    except Exception as e:
        print(f"Cache read error: {e}")
    
    return None


async def _cache_response(message: str, response: str) -> None:
    """
    Store an AI response in the cache for future use.
    
    Args:
        message: The student's original message
        response: Wax's AI-generated response
    """
    try:
        from database.client import redis_client
        
        cache_key = f"response_cache:{_normalize_for_cache(message)}"
        redis_client.setex(cache_key, CACHE_TTL, response)
        print(f"Cache SAVED: {message[:50]}...")
    except Exception as e:
        print(f"Cache write error: {e}")


# ═══════════════════════════════════════════════
# POST-PROCESSING ENFORCEMENT LAYER
# These rules are enforced in CODE, not just the prompt.
# The model might ignore prompt rules. Code doesn't.
# ═══════════════════════════════════════════════

def enforce_one_question(response: str) -> str:
    """
    If the AI asks more than one question, keep only the first one.
    Cuts at the first question mark and appends just that question.
    """
    questions = response.split("?")
    if len(questions) > 2:  # More than one question mark
        first_part = questions[0] + "?"
        remaining = "?".join(questions[1:])
        if len(remaining.strip()) > 10:
            return first_part.strip()
    return response


def enforce_length(response: str, max_chars: int = 400) -> str:
    """
    If response is too long, trim to the last complete sentence under max_chars.
    """
    if len(response) <= max_chars:
        return response
    
    truncated = response[:max_chars]
    last_period = max(
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? "),
        truncated.rfind(".\n"),
    )
    
    if last_period > 100:  # Only cut if we have enough context
        return truncated[:last_period + 1].strip()
    
    # Fallback: hard cut at last complete word
    return truncated.rsplit(" ", 1)[0] + "..."


def clean_banned_phrases(response: str) -> str:
    """
    Remove banned phrases from the response.
    """
    banned = [
        ("don't worry", "I hear you"),
        ("dont worry", "I hear you"),
        ("Don't worry", "I hear you"),
        ("do not worry", "I hear you"),
    ]
    
    for phrase, replacement in banned:
        response = response.replace(phrase, replacement)
    
    return response


def enforce_nigerian_example(response: str) -> str:
    """
    If the response is teaching (3+ sentences) and has no Nigerian reference,
    log a warning. Soft enforcement — doesn't modify the response.
    """
    nigerian_terms = [
        "danfo", "suya", "puff-puff", "egusi", "okada", "keke",
        "nepa", "wahala", "jollof", "garri", "mile 12", "inec",
        "achebe", "soyinka", "lagos", "abuja", "kano", "naira",
        "generator", "borehole", "kerosene", "omo", "agege"
    ]
    
    sentences = [s for s in response.split(".") if len(s.strip()) > 10]
    if len(sentences) >= 3:
        has_nigerian = any(term in response.lower() for term in nigerian_terms)
        if not has_nigerian:
            print(f"WARNING: Teaching response has no Nigerian example")
    
    return response


def enforce_rules(response: str) -> str:
    """
    Run all post-processing enforcement rules.
    Order matters: clean phrases first, then trim questions, then trim length.
    """
    # 1. Remove banned phrases
    response = clean_banned_phrases(response)
    
    # 2. Enforce one question limit
    response = enforce_one_question(response)
    
    # 3. Enforce length limit
    response = enforce_length(response, max_chars=400)
    
    # 4. Soft enforcement — log if Nigerian examples missing
    response = enforce_nigerian_example(response)
    
    return response


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
    Main AI thinking function.
    
    Multi-key rotation: Tries each available API key on rate limit errors.
    With 3 keys, this gives 300,000 tokens/day on Groq free tier.
    
    Response caching: Checks Redis before calling AI. If the same question
    was answered before, returns cached response instantly. Cuts token costs
    by ~80% for common questions like "what is osmosis".
    
    Args:
        message: The student's latest message
        student: Student profile dict
        conversation_history: List of recent messages
        recent_subject: Current subject if in a lesson
        context_str: Session context (memory, progress, etc.)
        is_practice: If True, use lite prompt (cheaper for practice/chat)
    
    Returns:
        Wax's response as a string (post-processed for rule compliance)
    """
    # FIXED: global declaration at the TOP of the function
    # Python requires 'global' before any use of the variable
    global _current_key_index

    conversation_history = conversation_history or []
    student_id = student.get('id', 'unknown')
    name = student.get('name', 'Student').split()[0]

    # Choose the right prompt
    if is_practice:
        system_prompt = get_lite_prompt(student, recent_subject, context_str)
    else:
        system_prompt = get_wax_system_prompt(student, recent_subject, context_str)

    # Build the message list for the API
    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history (keep more context for teaching, less for practice)
    history_limit = 10 if is_practice else 20
    for msg in conversation_history[-history_limit:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    # Add the current message
    messages.append({"role": "user", "content": message})

    # ── Check response cache before calling AI ──
    if _is_cacheable(message):
        cached_response = await _get_cached_response(message)
        if cached_response:
            return cached_response

    # ── Call Groq with multi-key rotation ──
    raw_response = None
    keys = settings.GROQ_API_KEYS
    max_retries = len(keys) * 3  # 3 attempts per key
    
    # Start with next key in rotation
    start_index = _current_key_index % len(keys) if keys else 0
    
    for attempt in range(max_retries):
        key_index = (start_index + attempt) % len(keys)
        api_key = keys[key_index] if keys else ""
        
        try:
            client = _get_client(api_key)
            
            # Run the synchronous Groq call in a thread pool
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.GROQ_SMART_MODEL,
                messages=messages,
                max_tokens=500,
                temperature=0.75,
            )
            
            result = response.choices[0].message.content
            if result and len(result.strip()) > 5:
                raw_response = result.strip()
                # Update rotation to next key — NO 'global' here, already declared at top
                _current_key_index = (key_index + 1) % len(keys)
                break
            
            print(f"Groq returned empty/short response for student {student_id}")
            
        except Exception as e:
            error_type = type(e).__name__
            error_str = str(e)
            
            # Check if it's a rate limit error — switch key
            is_rate_limit = (
                "rate_limit" in error_str.lower() or
                "429" in error_str
            )
            
            if is_rate_limit:
                print(
                    f"Groq rate limit on key {key_index+1}/{len(keys)} "
                    f"(attempt {attempt+1}/{max_retries}). Rotating key..."
                )
                # Don't sleep — just try next key immediately
                continue
            else:
                print(
                    f"Groq error (attempt {attempt+1}/{max_retries}): "
                    f"{error_type}: {error_str[:100]} | student={student_id}"
                )
                # For non-rate-limit errors, wait before retry
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)

    # If all keys exhausted, log failure and use fallback
    if not raw_response:
        _log_ai_failure(student_id, "ALL_KEYS_EXHAUSTED", "All API keys rate limited")
        fallbacks = [
            f"I had a small technical hiccup, {name}. Can you ask me again?",
            f"Ah, my brain lagged for a second, {name}. Try me one more time?",
            f"Sorry, {name} — something glitched. What were you saying?",
        ]
        return fallbacks[hash(str(student_id)) % len(fallbacks)]

    # ═══════════════════════════════════════════
    # POST-PROCESSING: Enforce rules in code
    # ═══════════════════════════════════════════
    
    cleaned_response = enforce_rules(raw_response)
    
    # If enforcement trimmed too much, fall back to original
    if len(cleaned_response) < 20 and len(raw_response) > 20:
        cleaned_response = clean_banned_phrases(raw_response)
        cleaned_response = enforce_length(cleaned_response, max_chars=500)
    
    # ── Cache this response for future use ──
    if _is_cacheable(message):
        await _cache_response(message, cleaned_response)
    
    return cleaned_response


def _log_ai_failure(student_id: str, error_type: str, error_message: str):
    """Log AI failures for monitoring."""
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"AI_FAILURE | {timestamp} | student={student_id} | {error_type}: {error_message[:200]}")
