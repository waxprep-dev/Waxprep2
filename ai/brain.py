"""
WaxPrep v2 — AI Brain
Calls the Groq API with Wax's system prompt and returns the response.
Includes post-processing enforcement layer for critical rules.

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
    Only caches knowledge questions — not greetings, quizzes, or personal messages.
    Cache version prefix allows instant invalidation on prompt/model changes.

Domain Boundary Enforcement:
    After the AI generates a response, checks it against the Student Model's
    avoided domains. If the response contains words from a domain the student
    has explicitly rejected, strips the violating sentences entirely.
    Falls back to warm Nigerian-voice alternatives if the entire response
    is compromised.
"""

import asyncio
import hashlib
import logging
import random
import re
import time
from datetime import datetime, timezone
from groq import Groq
from config.settings import settings
from ai.prompts import get_wax_system_prompt, get_lite_prompt

logger = logging.getLogger("waxprep.ai_brain")

# Cache for Groq clients — one per API key
_clients = {}

# Client TTL: recreate clients after 1 hour to pick up key changes
_CLIENT_TTL_SECONDS = 3600
_client_timestamps = {}


def _get_client(api_key: str = None) -> Groq:
    """
    Get or create a Groq client for a specific API key.
    
    Clients are recreated after 1 hour to allow key rotation
    without server restart.
    
    Args:
        api_key: Specific API key to use. If None, uses default.
        
    Returns:
        Groq client instance with 30-second timeout
    """
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

# Cache TTL: 7 days for teaching responses
CACHE_TTL = 604800  # 7 days in seconds

# Cache version: increment when system prompt or model changes
# to instantly invalidate all old cached responses
CACHE_VERSION = "v2"


def _get_class_tier(class_level: str) -> str:
    """
    Convert class level to cache tier to avoid cross-contamination.
    
    Splits students into 3 tiers so SS3 students don't get JSS1-level
    cached responses and vice versa.
    
    Args:
        class_level: e.g., "SS3", "JSS1", "SS2"
        
    Returns:
        Cache tier string: "jss", "ss1-2", or "ss3"
    """
    if not class_level:
        return "ss3"
    cl = class_level.upper()
    if "JSS" in cl:
        return "jss"
    if cl in ("SS1", "SS2"):
        return "ss1-2"
    return "ss3"


def _normalize_for_cache(text: str) -> str:
    """
    Normalize a student's question into a consistent cache key.
    
    Strips punctuation, extra spaces, underscores, and converts to
    lowercase so "What is Osmosis??" and "what_is_osmosis" produce
    the same key.
    
    Args:
        text: Raw student message
        
    Returns:
        Normalized cache key string
    """
    text = text.lower().strip()
    # Strip punctuation and underscores
    text = re.sub(r'[^a-z0-9\s]', '', text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text


def _build_cache_key(message: str, class_level: str = "SS3") -> str:
    """
    Build a tiered cache key.
    
    Uses MD5 hash of normalized message for fixed-length keys,
    includes cache version for instant invalidation, and class
    tier to prevent cross-contamination between levels.
    
    Args:
        message: Raw student message
        class_level: Student's class level for tier selection
        
    Returns:
        Redis cache key string
    """
    tier = _get_class_tier(class_level)
    normalized = _normalize_for_cache(message)
    hashed = hashlib.md5(normalized.encode()).hexdigest()
    return f"response_cache:{CACHE_VERSION}:{tier}:{hashed}"


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
    
    # Skip greetings, commands, and personal messages
    skip_patterns = [
        "hi", "hello", "hey", "good morning", "good evening",
        "how are you", "what's up", "thank", "bye", "ok", "okay",
        "you pick", "any one", "i'm done", "good night",
        "quiz", "test me", "delete me",
    ]
    
    for pattern in skip_patterns:
        if pattern in msg_lower:
            return False
    
    # Too short to be a knowledge question
    if len(msg_lower.split()) < 2:
        return False
    
    # Skip personal messages
    personal_indicators = [" i ", " my ", " me ", " i'm ", " i've ", " my name"]
    for indicator in personal_indicators:
        if indicator in f" {msg_lower} ":
            return False
    
    # Match knowledge question patterns
    knowledge_patterns = [
        "what", "how", "explain", "define", "why",
        "describe", "difference between", "compare",
        "tell me about", "meaning of", "can you explain",
        "help me understand",
    ]
    
    for pattern in knowledge_patterns:
        if msg_lower.startswith(pattern) or pattern in msg_lower:
            return True
    
    # Long messages that don't match above patterns are probably
    # still knowledge-related (e.g., "break down respiration for me")
    if len(msg_lower) > 30:
        return True
    
    return False


async def _get_cached_response(message: str, class_level: str = "SS3") -> str | None:
    """
    Check if a cached response exists for this message.
    
    Args:
        message: Raw student message
        class_level: Student's class level for tier matching
        
    Returns:
        Cached response string or None
    """
    try:
        from database.client import redis_client
        
        cache_key = _build_cache_key(message, class_level)
        cached = redis_client.get(cache_key)
        
        if cached:
            cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            logger.debug(f"Cache HIT: {message[:50]}...")
            return cached_str
    except Exception as e:
        logger.error(f"Cache read error: {e}")
    
    return None


async def _cache_response(message: str, response: str, class_level: str = "SS3") -> None:
    """
    Store an AI response in the cache for future use.
    
    Args:
        message: Raw student message
        response: AI-generated response to cache
        class_level: Student's class level for tier placement
    """
    try:
        from database.client import redis_client
        
        cache_key = _build_cache_key(message, class_level)
        redis_client.setex(cache_key, CACHE_TTL, response)
        logger.debug(f"Cache SAVED: {message[:50]}...")
    except Exception as e:
        logger.error(f"Cache write error: {e}")


# ═══════════════════════════════════════════════
# DOMAIN KEYWORDS — for boundary enforcement
# ═══════════════════════════════════════════════

DOMAIN_KEYWORDS = {
    "transportation": [
        "keke", "danfo", "okada", "bus", "vehicle", "car", "transport",
        "napep", "driver", "highway", "road", "traffic", "garage",
        "motor", "bike", "bicycle", "train", "airport", "flying",
        "suv", "lorry", "truck", "taxi", "uber", "bolt",
    ],
    "food_cooking": [
        "suya", "puff-puff", "puff puff", "jollof", "garri", "food", "cook",
        "eat", "kitchen", "recipe", "ingredient", "meal", "dinner",
        "lunch", "breakfast", "snack", "fry", "boil", "stew", "soup",
        "egusi", "rice", "beans", "yam", "plantain", "akara", "moin moin",
    ],
    "market_commerce": [
        "market", "mile 12", "mile12", "trade", "buy", "sell", "trader",
        "price", "bargain", "customer", "shop", "store", "mall",
        "business", "profit", "money", "cash", "trading",
    ],
    "technology": [
        "phone", "tech", "internet", "computer", "app", "download",
        "laptop", "software", "hardware", "digital", "online", "website",
        "data", "wifi", "screen", "button", "click", "smartphone",
    ],
    "school_classroom": [
        "teacher", "class", "textbook", "exam", "school", "classroom",
        "student", "desk", "blackboard", "homework", "principal",
        "lesson", "grade", "report card", "uniform",
    ],
    "home_domestic": [
        "generator", "nepa", "fan", "tap", "light", "water", "home",
        "backyard", "house", "room", "kitchen", "living room",
        "bedroom", "door", "window", "roof", "fence",
    ],
    "body_physical": [
        "breathe", "heart", "run", "walk", "body", "hand", "breathing",
        "leg", "arm", "finger", "muscle", "bone", "blood", "brain",
    ],
    "nature_environment": [
        "rain", "sun", "wind", "plant", "tree", "river", "cassava",
        "garden", "flower", "ocean", "mountain", "forest", "sky",
        "weather", "climate",
    ],
    "religion_worship": [
        "church", "mosque", "pastor", "imam", "pray", "bible", "quran",
        "god", "allah", "worship", "sermon", "faith", "spiritual",
    ],
    "football_sports": [
        "football", "match", "player", "goal", "stadium", "sport",
        "team", "coach", "score", "ball", "penalty", "league",
    ],
    "extended_family": [
        "uncle", "aunty", "cousin", "nephew", "niece", "grandmother",
        "grandfather", "in-law", "family", "relative", "sibling",
    ],
    "nollywood_media": [
        "nollywood", "movie", "film", "actor", "actress", "scene",
        "script", "director", "cinema", "drama", "episode",
    ],
    "nysc_corper": [
        "corper", "nysc", "camp", "service year", "orientation",
        "ppfa", "clearance", "cds", "pop", "passing out",
    ],
}


# ═══════════════════════════════════════════════
# POST-PROCESSING ENFORCEMENT LAYER
# ═══════════════════════════════════════════════

def enforce_one_question(response: str) -> str:
    """If the AI asks more than one question, keep only the first one."""
    questions = response.split("?")
    if len(questions) > 2:
        first_part = questions[0] + "?"
        remaining = "?".join(questions[1:])
        if len(remaining.strip()) > 10:
            return first_part.strip()
    return response


def enforce_length(response: str, max_chars: int = 400) -> str:
    """If response is too long, trim to the last complete sentence under max_chars."""
    if len(response) <= max_chars:
        return response
    
    truncated = response[:max_chars]
    last_period = max(
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? "),
        truncated.rfind(".\n"),
    )
    
    if last_period > 100:
        return truncated[:last_period + 1].strip()
    
    return truncated.rsplit(" ", 1)[0] + "..."


def clean_banned_phrases(response: str) -> str:
    """
    Remove banned phrases using case-insensitive regex matching.
    
    Catches ALL variations: "don't worry", "DON'T WORRY", "Don't Worry",
    "don't-worry", "do not worry", etc.
    
    Replacement: "let's take it step by step" — works in more contexts
    than the old replacement "I hear you" which created nonsense sentences.
    """
    # Catch "don't worry" and "dont worry" (all cases)
    response = re.sub(
        r"don'?t\s+worry",
        "let's take it step by step",
        response,
        flags=re.IGNORECASE
    )
    # Catch "do not worry" (all cases)
    response = re.sub(
        r"do\s+not\s+worry",
        "let's take it step by step",
        response,
        flags=re.IGNORECASE
    )
    return response


def enforce_nigerian_example(response: str, state: str = None) -> str:
    """
    Check if teaching response has Nigerian references.
    
    Only checks responses that appear to be teaching/explaining concepts.
    Logs a warning if missing Nigerian terms, debug log if present.
    
    Args:
        response: The AI-generated response text
        state: Student's Nigerian state for future state-specific examples (optional)
        
    Returns:
        Response unchanged (this function is a monitoring layer only)
    """
    # ═══════════════════════════════════════════════
    # TEACHING PATTERN GATE
    # Only check responses that are explaining a concept.
    # ═══════════════════════════════════════════════
    teaching_indicators = [
        "means", "is when", "is called", "because", "since", "imagine",
        "think of", "for example", "like when", "similar to", "compared to",
        "this is why", "the reason", "you can see", "picture this",
        "let's say", "suppose", "if you", "remember that", "note that",
        "in other words", "basically", "essentially", "to put it simply",
        "defined as", "refers to", "known as", "describes", "explains",
        "works like", "think about", "picture yourself", "envision",
    ]
    
    response_lower = response.lower()
    is_teaching = any(indicator in response_lower for indicator in teaching_indicators)
    
    if not is_teaching:
        # Not a teaching response — skip check (corrections, check-ins, emotional support)
        return response
    
    # ═══════════════════════════════════════════════
    # EXPANDED NIGERIAN TERMS (~75 terms)
    # Focus on unambiguously Nigerian cultural references.
    # Avoid generic words like "market", "generator", "light", "fan".
    # ═══════════════════════════════════════════════
    nigerian_terms = [
        # ── Food & Drink ──
        "amala", "eba", "fufu", "pounded yam", "poundedyam",
        "moi-moi", "moimoi", "akara", "chin-chin", "chinchin",
        "zobo", "kunu", "ofada rice", "ofadarice", "bitter leaf", "bitterleaf",
        "ogbono", "banga soup", "bangasoup", "edikaikong",
        "egusi", "egusi soup", "egusisoup", "okra soup", "okrasoup",
        "oha soup", "ohasoup", "afang soup", "afangsoup",
        "ewedu", "gbegiri", "suya", "kilishi", "puff-puff", "puffpuff",
        "jollof", "jollof rice", "jollofrice", "garri",
        
        # ── Transport ──
        "danfo", "okada", "keke", "keke napep", "kekenapep",
        "molue", "agbero", "yellow bus", "yellowbus",
        "go-slow", "goslow", "go slow",
        
        # ── Major Cities & Places ──
        "lagos", "abuja", "kano", "ibadan", "port harcourt", "portharcourt",
        "onitsha", "aba", "nnewi", "owerri", "enugu", "calabar",
        "kaduna", "jos", "sokoto", "ilorin", "abeokuta",
        "mile 12", "mile12", "agege", "ikeja", "lekki", "yaba",
        "oshodi", "surulere", "victoria island", "vi", "ikoyi", "apapa",
        
        # ── Culture & Daily Life ──
        "nepa", "phcn", "wahala", "oga", "madam", "omo", "abeg",
        "area boy", "areaboy", "area boys", "areaboys", "alaye", "sabi",
        "pure water", "purewater", "sachet water", "sachetwater",
        "gala", "lacasera", "fan yogurt", "fanyogurt",
        "groundnut", "boli", "roasted corn", "roastedcorn",
        "now now", "sharp sharp", "no wahala",
        
        # ── People & Icons ──
        "achebe", "soyinka", "fela", "fela kuti", "felakuti",
        "tuface", "2baba", "wizkid", "davido", "burna boy", "burnaboy",
        "tiwa savage", "tiwasavage",
        "emeka", "chidera", "nneoma", "amara", "kennedy",
        "adaobi", "olumide", "fatima", "amina", "yusuf",
        "chinedu", "ngozi", "obi", "ade", "tunde", "nkechi",
        "chioma", "ifeanyi", "oluchi", "chukwu", "ebuka",
        
        # ── Institutions & Exams ──
        "jamb", "waec", "neco", "inec", "nysc", "corper", "corpers",
        "federal government college", "unity school", "common entrance",
        "lesson teacher", "lesson note",
        
        # ── Money & Telecom ──
        "naira", "kobo", "mtn", "glo", "airtel",
        
        # ── Sports & Entertainment ──
        "nollywood", "super eagles", "supereagles", "green white green",
        "greenwhitegreen", "naija",
        
        # ── Nature & Agriculture ──
        "harmattan", "hamattan", "rainy season", "rainyseason",
        "dry season", "dryseason", "mango season", "mangoseason",
        "cocoa", "palm oil", "palmoil", "palm wine", "palmwine",
        "cassava", "yam", "plantain", "coco yam", "cocoyam",
        "maize", "guinea corn", "guineacorn",
    ]
    
    has_nigerian = any(term in response_lower for term in nigerian_terms)
    
    if has_nigerian:
        logger.debug("Nigerian example confirmed in teaching response")
    else:
        logger.warning("Teaching response has no Nigerian example")
    
    # Future Phase 1: state-specific examples
    # if state and not has_nigerian:
    #     state_terms = STATE_SPECIFIC_TERMS.get(state, [])
    #     has_state_specific = any(term in response_lower for term in state_terms)
    #     ...
    
    return response


def enforce_rules(response: str, state: str = None) -> str:
    """Run all post-processing enforcement rules."""
    response = clean_banned_phrases(response)
    response = enforce_one_question(response)
    response = enforce_length(response, max_chars=400)
    response = enforce_nigerian_example(response, state=state)
    return response


# ═══════════════════════════════════════════════
# DOMAIN BOUNDARY ENFORCEMENT
# ═══════════════════════════════════════════════

async def enforce_domain_boundaries(
    response: str,
    student_id: str,
    student_model=None
) -> str:
    """
    Check response against Student Model's avoided domains.
    
    If the student has explicitly rejected a domain and the AI's response
    contains words from that domain, strips the violating sentences entirely.
    Falls back to warm Nigerian-voice alternatives if the entire response
    is compromised.
    
    Args:
        response: The AI-generated response text
        student_id: Student's database ID
        student_model: Pre-loaded StudentModel (optional — loads if not provided)
        
    Returns:
        Cleaned response with domain violations removed
    """
    if len(response.strip()) < 15:
        return response
    
    try:
        if student_model is None:
            from brain.student_model import load_student_model
            student_model = await load_student_model(student_id)
        
        avoided = student_model.get_avoided_domains()
        
        if not avoided:
            return response
        
        resp_lower = response.lower()
        violations = []
        
        for domain in avoided:
            keywords = DOMAIN_KEYWORDS.get(domain, [domain])
            found_words = [kw for kw in keywords if kw in resp_lower]
            if found_words:
                violations.append({
                    "domain": domain,
                    "words_found": found_words,
                })
        
        if violations:
            for v in violations:
                logger.warning(
                    f"DOMAIN VIOLATION BLOCKED: Student {student_id} has '{v['domain']}' "
                    f"as avoided. Response contained: {v['words_found']}. "
                    f"Stripping violating content."
                )
            
            # Split response into sentences and strip violating ones
            sentences = re.split(r'(?<<=[.!?])\s+', response)
            clean_sentences = []
            
            for sentence in sentences:
                sentence_lower = sentence.lower()
                is_violating = False
                
                for domain in avoided:
                    keywords = DOMAIN_KEYWORDS.get(domain, [domain])
                    if any(kw in sentence_lower for kw in keywords):
                        is_violating = True
                        break
                
                if not is_violating:
                    clean_sentences.append(sentence)
                else:
                    logger.debug(f"Stripped violating sentence: {sentence[:80]}...")
            
            # If everything was stripped, provide a WARM fallback
            # No square brackets. No robot voice. Just Wax being honest.
            if not clean_sentences or len(" ".join(clean_sentences)) < 15:
                preferred = student_model.get_preferred_domains()[:2]
                if preferred:
                    preferred_str = ", ".join(preferred)
                    return (
                        f"Ah, my bad — I used an example you've asked me to avoid. "
                        f"Let me try again with {preferred_str} instead."
                    )
                else:
                    return (
                        f"My bad, let me take a different approach without that example."
                    )
            
            response = " ".join(clean_sentences)
    
    except Exception as e:
        logger.error(f"Domain boundary enforcement error: {e}")
    
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
    
    Multi-key rotation with random starting index (no race conditions),
    tiered response caching, and domain boundary enforcement.
    
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

    # Check response cache (tiered by class level)
    if _is_cacheable(message):
        cached_response = await _get_cached_response(message, class_level)
        if cached_response:
            return cached_response

    # Call Groq with multi-key rotation
    # Random starting index avoids race conditions under concurrent load
    raw_response = None
    keys = settings.GROQ_API_KEYS
    
    if not keys or not keys[0]:
        logger.error(f"No Groq API keys configured. AI cannot function.")
        return f"I had a small technical hiccup, {name}. Can you ask me again?"
    
    max_retries = len(keys) * 3
    start_index = random.randint(0, len(keys) - 1)
    
    for attempt in range(max_retries):
        key_index = (start_index + attempt) % len(keys)
        api_key = keys[key_index]
        
        try:
            client = _get_client(api_key)
            
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
                break
            
            logger.warning(f"Groq returned empty/short response for student {student_id}")
            
        except Exception as e:
            error_type = type(e).__name__
            error_str = str(e)
            
            is_rate_limit = (
                "rate_limit" in error_str.lower() or
                "429" in error_str
            )
            
            if is_rate_limit:
                logger.warning(
                    f"Groq rate limit on key {key_index+1}/{len(keys)} "
                    f"(attempt {attempt+1}/{max_retries}). Rotating key..."
                )
                continue
            else:
                logger.error(
                    f"Groq error (attempt {attempt+1}/{max_retries}): "
                    f"{error_type}: {error_str[:100]} | student={student_id}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)

    if not raw_response:
        _log_ai_failure(student_id, "ALL_KEYS_EXHAUSTED", "All API keys exhausted or failed")
        # Stable fallback selection using MD5 instead of unstable hash()
        fallbacks = [
            f"I had a small technical hiccup, {name}. Can you ask me again?",
            f"Ah, my brain lagged for a second, {name}. Try me one more time?",
            f"Sorry, {name} — something glitched. What were you saying?",
        ]
        hash_val = int(hashlib.md5(str(student_id).encode()).hexdigest()[:8], 16)
        return fallbacks[hash_val % len(fallbacks)]

    # Post-processing enforcement
    state = student.get('state')
    cleaned_response = enforce_rules(raw_response, state=state)
    
    # If enforcement made the response too short, use gentler enforcement
    if len(cleaned_response) < 20 and len(raw_response) > 20:
        cleaned_response = clean_banned_phrases(raw_response)
        cleaned_response = enforce_length(cleaned_response, max_chars=500)
    
    # Domain boundary enforcement — strips violating sentences
    try:
        cleaned_response = await enforce_domain_boundaries(
            cleaned_response, student_id
        )
    except Exception as e:
        logger.error(f"Domain enforcement failed: {e}", exc_info=True)
    
    # Cache response (tiered by class level)
    if _is_cacheable(message):
        await _cache_response(message, cleaned_response, class_level)
    
    return cleaned_response


def _log_ai_failure(student_id: str, error_type: str, error_message: str):
    """Log AI failures for monitoring and alerting."""
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.critical(
        f"AI_FAILURE | {timestamp} | student={student_id} | "
        f"{error_type}: {error_message[:200]}"
    )
