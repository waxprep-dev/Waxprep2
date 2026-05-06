"""
WaxPrep v2 — AI Brain
Calls the Groq API with Wax's system prompt and returns the response.
This is the bridge between the rules and the actual AI.
"""

import asyncio
import time
from datetime import datetime
from groq import Groq
from config.settings import settings
from ai.prompts import get_wax_system_prompt, get_lite_prompt

# Cache the Groq client
_groq_client = None


def _get_client() -> Groq:
    """Get or create the Groq client (singleton)."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


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
    
    Args:
        message: The student's latest message
        student: Student profile dict
        conversation_history: List of recent messages [{"role": "user/assistant", "content": "..."}]
        recent_subject: Current subject if in a lesson
        context_str: Session context (memory, progress, etc.)
        is_practice: If True, use lite prompt (cheaper for practice/chat)
    
    Returns:
        Wax's response as a string
    """
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

    # Call Groq with retry logic
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            client = _get_client()
            
            # Run the synchronous Groq call in a thread pool to avoid blocking the event loop
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.GROQ_FAST_MODEL,
                messages=messages,
                max_tokens=600,
                temperature=0.75,
            )
            
            result = response.choices[0].message.content
            if result and len(result.strip()) > 5:
                return result.strip()
            
            # Empty or too-short response — treat as failure
            print(f"Groq returned empty/short response for student {student_id}")
            
        except Exception as e:
            error_type = type(e).__name__
            print(f"Groq error (attempt {attempt+1}/{max_retries+1}): {error_type}: {e} | student={student_id}")
            
            if attempt < max_retries:
                # Exponential backoff: 1s, 2s
                wait_time = (attempt + 1) * 1.0
                await asyncio.sleep(wait_time)
            else:
                # All retries exhausted — log structured error
                _log_ai_failure(student_id, error_type, str(e))

    # Fallback — student should never see silence
    fallbacks = [
        f"I had a small technical hiccup, {name}. Can you ask me again?",
        f"Ah, my brain lagged for a second, {name}. Try me one more time?",
        f"Sorry, {name} — something glitched. What were you saying?",
    ]
    return fallbacks[hash(str(student_id)) % len(fallbacks)]


def _log_ai_failure(student_id: str, error_type: str, error_message: str):
    """Log AI failures for monitoring."""
    timestamp = datetime.utcnow().isoformat()
    print(f"AI_FAILURE | {timestamp} | student={student_id} | {error_type}: {error_message[:200]}")
    # TODO: Send to monitoring dashboard (Datadog, Sentry, etc.)
