"""
ai/intent_router.py — WaxPrep Intent Classification (P0-A001 + P1-A)

Every message goes through the AI FIRST before any action is taken.
The AI returns structured JSON telling us what the student wants.
No more keyword guessing.

NOW INCLUDES: Dissonance Scanner integration (P1-A)
- Detects cognitive contradictions in student messages
- Returns dialectical_midwifery intent when student's mind is in tension
- Respects intimacy gating (full Schism vs muted Schism)

Aligned with: WaxPrep Foundation Blueprint v1.0, Part 1, Layer 1 (Bedrock)
"""

import asyncio
import json
import logging
import random
from decimal import Decimal
from groq import Groq
from config.settings import settings

logger = logging.getLogger("waxprep.intent_router")

# ═══════════════════════════════════════════════
# DISSONANCE SCANNER IMPORT (P1-A)
# ═══════════════════════════════════════════════
try:
    from brain.dialectical_socket import detect_dissonance
    _dialectical_available = True
except ImportError:
    _dialectical_available = False
    logger.warning("Dialectical socket not available — dissonance detection disabled")

# ═══════════════════════════════════════════════
# SYSTEM PROMPT FOR INTENT CLASSIFICATION
# ═══════════════════════════════════════════════

INTENT_SYSTEM_PROMPT = """You are an intent classifier for Wax, an AI tutor for Nigerian students.

Read the student's message and classify their intent. Return ONLY a JSON object.

Rules:
- "action": what they want — teach, quiz, emotional_support, defer, end_session, greeting, or dialectical_midwifery (when student contradicts themselves or expresses confusion about conflicting ideas)
- "subject": if they mention a subject (mathematics, physics, english, etc.), include it
- "topic": if they mention a specific topic (quadratic equations, osmosis, etc.), include it
- "confidence": 0.0 to 1.0 — how sure you are
- "student_emotion": frustrated, confused, bored, excited, neutral, or stressed
- "context_aware": true if the message references previous conversation, false if standalone

Examples:
Message: "quiz me on physics"
→ {"action":"quiz","subject":"physics","topic":null,"confidence":0.95,"student_emotion":"neutral","context_aware":false}

Message: "i'm done for today, goodnight"
→ {"action":"end_session","subject":null,"topic":null,"confidence":0.92,"student_emotion":"neutral","context_aware":false}

Message: "you pick what we study next"
→ {"action":"defer","subject":null,"topic":null,"confidence":0.88,"student_emotion":"neutral","context_aware":true}

Message: "i don't understand quadratic equations"
→ {"action":"teach","subject":"mathematics","topic":"quadratic_equations","confidence":0.95,"student_emotion":"confused","context_aware":false}

Message: "i got 189 in jamb and i feel like a failure"
→ {"action":"emotional_support","subject":null,"topic":"jamb_results","confidence":0.93,"student_emotion":"stressed","context_aware":false}

Message: "hi wax"
→ {"action":"greeting","subject":null,"topic":null,"confidence":0.98,"student_emotion":"neutral","context_aware":false}

Message: "my teacher said water boils at 90°C but you said 100°C"
→ {"action":"dialectical_midwifery","subject":"physics","topic":"boiling_point","confidence":0.91,"student_emotion":"confused","context_aware":false}

Message: "i understand the formula but i don't feel like it makes sense"
→ {"action":"dialectical_midwifery","subject":"mathematics","topic":"understanding_vs_feeling","confidence":0.88,"student_emotion":"confused","context_aware":true}

Return ONLY the JSON object. No explanation, no markdown, no extra text."""

# ═══════════════════════════════════════════════
# MAIN CLASSIFICATION FUNCTION
# ═══════════════════════════════════════════════

async def classify_intent(message: str, conversation_history: list = None, intimacy_score: float = 0.0) -> dict:
    """
    Classify student intent using the AI.

    This replaces keyword-based routing. Every message goes to the AI first.
    
    NEW (P1-A): Also runs Dissonance Scanner. If cognitive contradiction detected,
    overrides action to 'dialectical_midwifery' regardless of AI classification.

    Args:
        message: The student's latest message
        conversation_history: Recent messages for context (optional)
        intimacy_score: PIG intimacy score (0.0-10.0). Affects dissonance threshold.
                       ≥4.0 = full Schism (threshold 0.75), <4.0 = muted Schism (threshold 0.90)

    Returns:
        dict with keys: action, subject, topic, confidence, student_emotion, context_aware
                         PLUS dissonance metadata if triggered
    """
    conversation_history = conversation_history or []

    # Build messages for intent classification
    messages = [{"role": "system", "content": INTENT_SYSTEM_PROMPT}]

    # Add last 3 messages for context (if available)
    for msg in conversation_history[-3:]:
        role = msg.get("role", "user")
        if role in ["user", "assistant"]:
            messages.append({"role": role, "content": msg.get("content", "")})

    messages.append({"role": "user", "content": message})

    # Call Groq with multi-key rotation (same as brain.py)
    keys = settings.GROQ_API_KEYS
    if not keys or not keys[0]:
        logger.error("No Groq API keys configured")
        return _default_intent(message)

    max_retries = len(keys) * 2
    start_index = random.randint(0, len(keys) - 1)

    result = None

    for attempt in range(max_retries):
        key_index = (start_index + attempt) % len(keys)
        api_key = keys[key_index]

        try:
            client = Groq(api_key=api_key, timeout=15.0)

            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.GROQ_FAST_MODEL,  # Uses "llama-3.1-8b-instant" — fast and cheap
                messages=messages,
                max_tokens=200,
                temperature=0.1,  # Very low — consistent classification
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)

            # Validate required fields
            if "action" not in result or "confidence" not in result:
                logger.warning(f"Intent classification missing fields: {result}")
                return _default_intent(message)

            # Normalize action to valid values
            valid_actions = [
                "teach", "quiz", "emotional_support", "defer", 
                "end_session", "greeting", "dialectical_midwifery"
            ]
            if result["action"] not in valid_actions:
                result["action"] = "teach"  # Safe default

            # Ensure confidence is a float between 0 and 1
            try:
                result["confidence"] = float(result["confidence"])
                result["confidence"] = max(0.0, min(1.0, result["confidence"]))
            except (ValueError, TypeError):
                result["confidence"] = 0.5

            break  # Success — exit retry loop

        except json.JSONDecodeError as e:
            logger.warning(f"Intent classification returned invalid JSON: {e}")
            continue
        except Exception as e:
            error_str = str(e).lower()
            if "rate_limit" in error_str or "429" in error_str:
                logger.warning(f"Rate limit on intent key {key_index}")
                continue
            logger.error(f"Intent classification error: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.3)

    # All retries failed — return safe default
    if result is None:
        logger.error("All intent classification retries failed")
        return _default_intent(message)

    # ═══════════════════════════════════════════════════════════════════════
    # DISSONANCE SCANNER INTEGRATION (P1-A)
    # ═══════════════════════════════════════════════════════════════════════
    if _dialectical_available:
        try:
            dissonance = detect_dissonance(
                message=message,
                context=None,
                intimacy_score=Decimal(str(intimacy_score))
            )

            if dissonance.triggered:
                logger.info(
                    f"Dissonance override: {result['action']} → dialectical_midwifery "
                    f"(score={float(dissonance.score):.2f}, type={dissonance.contradiction_type}, "
                    f"intimacy={intimacy_score:.1f})"
                )
                
                # Override action to dialectical midwifery
                result["action"] = "dialectical_midwifery"
                
                # Boost confidence to at least dissonance score so it doesn't 
                # get caught in low-confidence clarifying-question logic
                dissonance_confidence = float(dissonance.score)
                result["confidence"] = max(result["confidence"], dissonance_confidence)
                
                # Attach dissonance metadata for downstream use
                result["dissonance"] = dissonance.to_dict()
                
                # If AI didn't extract subject/topic, try to infer from dissonance positions
                if not result.get("subject") and dissonance.extracted_positions:
                    # Use first position as topic hint — handler will refine
                    result["topic"] = result.get("topic") or dissonance.contradiction_type

        except Exception as e:
            logger.warning(f"Dissonance scan failed: {e}")

    logger.info(f"Intent: {result['action']} (confidence: {result['confidence']:.2f})")
    return result

# ═══════════════════════════════════════════════
# FALLBACK FUNCTION (Emergency Only)
# ═══════════════════════════════════════════════

def _default_intent(message: str) -> dict:
    """
    Return a safe default intent when AI classification fails.
    This is ONLY for emergencies — normally the AI handles this.
    """
    msg_lower = message.lower().strip()

    # Very basic keyword fallback — only used when AI is down
    if any(w in msg_lower for w in ["quiz", "test me", "test my"]):
        return {"action": "quiz", "subject": None, "topic": None,
                "confidence": 0.5, "student_emotion": "neutral", "context_aware": False}

    if any(w in msg_lower for w in ["bye", "goodnight", "good night", "i'm done", "i am done"]):
        return {"action": "end_session", "subject": None, "topic": None,
                "confidence": 0.5, "student_emotion": "neutral", "context_aware": False}

    if any(w in msg_lower for w in ["you pick", "choose for me", "whatever", "surprise me"]):
        return {"action": "defer", "subject": None, "topic": None,
                "confidence": 0.5, "student_emotion": "neutral", "context_aware": False}

    if any(w in msg_lower for w in ["hi", "hello", "hey", "good morning", "good evening"]):
        return {"action": "greeting", "subject": None, "topic": None,
                "confidence": 0.5, "student_emotion": "neutral", "context_aware": False}

    # Default: just teach — safest option
    return {"action": "teach", "subject": None, "topic": None,
            "confidence": 0.5, "student_emotion": "neutral", "context_aware": False}
