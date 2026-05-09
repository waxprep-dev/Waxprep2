"""
WaxPrep v2 — Hybrid AI-Driven Onboarding
Code controls WHAT to ask. AI generates HOW to ask.
Every student gets a unique onboarding conversation.

Architecture:
    - State machine tracks required fields
    - AI generates every message fresh per student (only 3 steps: welcome, trouble_subject, activation)
    - Pre-written templates used for simple steps (name, class, subjects, exam, state, PIN)
    - Code validates responses and advances state
    - Inline buttons for structured choices (class, exam)
    - Free text for personal responses (name, subjects, state)
    - University ambition guessed from subjects for SS3
    - PIN setup warm but code-enforced, hashed before storage
    - Brute-force protection: 5 failed attempts = lockout

Fallback: telegram/onboarding.py (scripted version)
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from difflib import get_close_matches
from typing import Dict, Any, Optional, List

from telegram.sender import send_telegram_message
from database.onboarding_state import save_onboarding_state, clear_onboarding_state
from helpers import clean_name
from database.students import create_student
from content.subject_hooks import normalize_subject

logger = logging.getLogger("waxprep.onboarding_hybrid")


# ═══════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════

NIGERIAN_STATES = {
    "abia", "adamawa", "akwa ibom", "anambra", "bauchi", "bayelsa", "benue",
    "borno", "cross river", "delta", "ebonyi", "edo", "ekiti", "enugu",
    "gombe", "imo", "jigawa", "kaduna", "kano", "katsina", "kebbi",
    "kogi", "kwara", "lagos", "nasarawa", "niger", "ogun", "ondo",
    "osun", "oyo", "plateau", "rivers", "sokoto", "taraba", "yobe",
    "zamfara", "abuja", "fct", "federal capital territory",
}

# Canonical FCT name — all variations normalize to this
FCT_CANONICAL = "FCT-Abuja"
FCT_VARIANTS = {"abuja", "fct", "federal capital territory"}

WEAK_PINS = {
    "1234", "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
    "password", "qwerty", "abcd", "12345", "waxp", "admin", "login",
}

# No more than 5 failed PIN attempts before lockout
MAX_PIN_ATTEMPTS = 5

# Words that mean "yes" when confirming a fuzzy match suggestion
CONFIRMATION_WORDS = {"yes", "yeah", "yep", "correct", "right", "that's it", "yes o", "na im", "exactly"}

# ═══════════════════════════════════════════════
# ONBOARDING STATE MACHINE
# ═══════════════════════════════════════════════

REQUIRED_FIELDS = ["name", "class_level", "subjects", "target_exam", "student_state", "pin"]
SS1_SS2_FIELDS = ["name", "class_level", "subjects", "student_state", "pin"]

STEP_ORDER = ["welcome", "name", "class_level", "subjects", "target_exam", 
              "university_ambition", "state", "pin_setup", "activation"]


# ═══════════════════════════════════════════════
# AI MESSAGE GENERATOR
# ═══════════════════════════════════════════════

async def _generate_onboarding_message(
    step: str,
    state: dict,
    student_message: str = "",
    validation_error: str = "",
) -> str:
    """
    Call the AI to generate a natural onboarding message.
    
    Only used for 3 high-value steps: welcome, trouble_subject, activation.
    Simple steps (name, class, subjects, exam, state, PIN) use pre-written
    templates via _get_fallback_message() to save cost and latency.
    
    Args:
        step: Current onboarding step
        state: Current onboarding state with collected data
        student_message: The student's last message (for reactions)
        validation_error: What went wrong (for retry prompts)
    
    Returns:
        Generated message text (or fallback if AI fails)
    """
    from ai.brain import _get_client
    from config.settings import settings
    
    name = state.get("name", "").split()[0] if state.get("name") else ""
    class_level = state.get("class_level", "")
    subjects = state.get("subjects", [])
    target_exam = state.get("target_exam", "")
    student_state = state.get("student_state", "")
    trouble_subject = state.get("trouble_subject", "")
    
    step_prompts = {
        "welcome": f"""
You are Wax — a warm Nigerian teacher onboarding a new student.
This is the FIRST message. The student just said "{student_message}".

Generate a WARM, BRIEF welcome message. Be Nigerian. Be yourself.
- If they said "hi" or "hello": welcome them, ask if they're new or returning
- If they already said "new" or "I'm new": skip to asking their name
- Keep it under 3 sentences. Don't list options with dashes or numbers.
- Sound like a real person, not a bot. Use "Oya", "My person", "Welcome o".
""",

        "trouble_subject": f"""
You are Wax onboarding {name}, an {class_level} student doing {', '.join(subjects) if subjects else 'various subjects'}.
The student just gave their subjects.

Ask them: which subject gives them the most trouble?
- Be warm. Normalize struggling. "Which one gives you the most wahala?"
- If they mentioned something earlier that sounded hard, reference it.
- Keep it under 2 sentences.
""",

        "activation": f"""
You are Wax. {name} has completed onboarding.

Student Profile:
- Name: {name}
- Class: {class_level}
- Subjects: {', '.join(subjects) if subjects else 'various subjects'}
- Exam: {target_exam}
- State: {student_state}
- Trouble subject: {trouble_subject}

Generate a personalized WELCOME message.
- Reference at least ONE specific thing they told you during onboarding
- Include the "I won't give up on you" promise
- Be warm, personal, and brief
- End with: "What do you want to study first?"
- This is the START of their learning journey. Make it feel like day one of something important.
- Keep it under 5 sentences.
""",
    }
    
    prompt = step_prompts.get(step)
    if not prompt:
        return _get_fallback_message(step, state)
    
    try:
        client = _get_client(settings.GROQ_API_KEY)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.GROQ_SMART_MODEL,
            messages=[
                {"role": "system", "content": "You are Wax — a warm, funny, Nigerian teacher. You never say 'don't worry.' You never use dashes or numbered lists. You talk like a real person. Keep every message under 3 sentences during onboarding."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300 if step == "activation" else 200,
            temperature=0.8,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI onboarding message generation failed for step '{step}': {e}")
        return _get_fallback_message(step, state)


def _get_fallback_message(step: str, state: dict) -> str:
    """Pre-written fallback messages. Same warmth as AI, zero latency, zero cost."""
    name = state.get("name", "").split()[0] if state.get("name") else ""
    
    fallbacks = {
        "welcome": "Oya, a serious student. I'm Wax. Are you new here or returning?",
        "name": "My person! What do people call you at home? Your real name o.",
        "class_level": f"{name + ', ' if name else ''}what class are you in? SS1, SS2, or SS3?",
        "subjects": f"What subjects are you doing in school{f', {name}' if name else ''}? Type them out — I want the full picture.",
        "target_exam": "Which exam are you preparing for? JAMB, WAEC, or NECO?",
        "university_ambition": "Have you thought about what you want to study in university?",
        "state": "Which state are you based in? It helps me give you examples you'll actually relate to. Lagos? Kano? Rivers?",
        "pin_setup": "Create a secret code — at least 4 characters. Letters, numbers, or mix them up. Something your younger sibling can't guess.",
        "activation": f"{name + '. ' if name else ''}You're in! I know what we're up against. I won't give up on you. What do you want to study first?",
        "trouble_subject": f"Out of all your subjects, {name + ', ' if name else ''}which one gives you the most wahala? Be honest — no judgment.",
    }
    return fallbacks.get(step, "Let's continue. What's next?")


# ═══════════════════════════════════════════════
# VALIDATION FUNCTIONS
# ═══════════════════════════════════════════════

def _validate_name(text: str) -> tuple:
    """Validate a name. Returns (cleaned_name, error_message)."""
    name = clean_name(text)
    if len(name) < 2:
        return "", "Give me a name — something I can call you."
    return name, ""


def _validate_class(text: str) -> tuple:
    """Validate class level. Returns (class_level, error_message)."""
    class_map = {"1": "SS1", "2": "SS2", "3": "SS3", 
                 "SS1": "SS1", "SS2": "SS2", "SS3": "SS3"}
    msg = text.strip().upper()
    result = class_map.get(msg)
    if not result:
        return "", "Just type SS1, SS2, or SS3."
    return result, ""


def _validate_exam(text: str) -> tuple:
    """Validate exam type. Returns (exam, error_message)."""
    exam_map = {"1": "JAMB", "2": "WAEC", "3": "NECO",
                "JAMB": "JAMB", "WAEC": "WAEC", "NECO": "NECO"}
    msg = text.strip().upper()
    result = exam_map.get(msg)
    if not result:
        return "", "Just type JAMB, WAEC, or NECO."
    return result, ""


def _validate_state(text: str) -> tuple:
    """
    Validate Nigerian state. Returns (state_name, error_message).
    
    Handles:
    - Exact matches (case-insensitive)
    - FCT variations (normalized to FCT-Abuja)
    - Fuzzy matches for close guesses (e.g., "Abuj" → suggests "Abuja")
    - Short inputs (<=2 chars) with helpful error
    """
    raw = text.strip()
    raw_lower = raw.lower()
    
    # Check exact match first
    if raw_lower in NIGERIAN_STATES:
        if raw_lower in FCT_VARIANTS:
            return FCT_CANONICAL, ""
        return raw.title(), ""
    
    # Fuzzy match for close guesses (e.g., "Abuj" → "abuja", "plateu" → "plateau")
    matches = get_close_matches(raw_lower, list(NIGERIAN_STATES), n=1, cutoff=0.7)
    if matches:
        matched = matches[0]
        if matched in FCT_VARIANTS:
            matched_display = FCT_CANONICAL
        else:
            matched_display = matched.title()
        return "", f"Did you mean *{matched_display}*? Just confirming — I want to get your state right."
    
    # No match — give helpful error
    if len(raw) <= 2:
        return "", "Type the full name — like Kano or Lagos."
    
    return "", f"Hmm, I don't recognize '{raw}' as a Nigerian state. Try the full name?"


def _validate_pin(text: str) -> tuple:
    """Validate PIN. Returns (pin, error_message)."""
    pin = text.strip()
    if len(pin) < 4:
        return "", "At least 4 characters. Letters, numbers, or both."
    if pin.lower() in WEAK_PINS:
        return "", "That's too easy to guess. Pick something more unique."
    return pin, ""


# ═══════════════════════════════════════════════
# KEYBOARD BUILDERS
# ═══════════════════════════════════════════════

def _build_class_keyboard() -> dict:
    """Inline keyboard for class selection."""
    return {
        "inline_keyboard": [
            [
                {"text": "SS1", "callback_data": "onboard_class_SS1"},
                {"text": "SS2", "callback_data": "onboard_class_SS2"},
                {"text": "SS3", "callback_data": "onboard_class_SS3"},
            ]
        ]
    }


def _build_exam_keyboard() -> dict:
    """Inline keyboard for exam selection."""
    return {
        "inline_keyboard": [
            [
                {"text": "JAMB (UTME)", "callback_data": "onboard_exam_JAMB"},
                {"text": "WAEC (SSCE)", "callback_data": "onboard_exam_WAEC"},
                {"text": "NECO", "callback_data": "onboard_exam_NECO"},
            ]
        ]
    }


def _build_new_returning_keyboard() -> dict:
    """Inline keyboard for new vs returning."""
    return {
        "inline_keyboard": [
            [
                {"text": "🆕 I'm New", "callback_data": "onboard_new"},
                {"text": "🔑 I Have a WAX ID", "callback_data": "onboard_returning"},
            ]
        ]
    }


# ═══════════════════════════════════════════════
# MAIN ONBOARDING DISPATCHER
# ═══════════════════════════════════════════════

STEP_HANDLERS = {}


def register_step(step_name: str):
    """Decorator to register a step handler function."""
    def wrapper(func):
        STEP_HANDLERS[step_name] = func
        return func
    return wrapper


async def handle_onboarding_hybrid(chat_id: int, state: dict, message: str) -> None:
    """
    Main entry point for hybrid AI-driven onboarding.
    
    Routes to the appropriate step handler based on state.
    If no step is active, starts the welcome flow.
    """
    step = state.get("awaiting_response_for", "welcome")
    
    # Handle callback queries from inline keyboards
    if message.startswith("onboard_"):
        await _handle_onboarding_callback(chat_id, state, message)
        return
    
    handler = STEP_HANDLERS.get(step)
    if handler:
        await handler(chat_id, state, message)
    else:
        await _step_welcome(chat_id, state, message)


async def _handle_onboarding_callback(chat_id: int, state: dict, callback_data: str):
    """Handle inline keyboard button taps during onboarding."""
    
    if callback_data in ("onboard_class_SS1", "onboard_class_SS2", "onboard_class_SS3"):
        class_level = callback_data.replace("onboard_class_", "")
        state["class_level"] = class_level
        state["awaiting_response_for"] = "subjects"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = _get_fallback_message("subjects", state)
        await send_telegram_message(chat_id, msg)
        return
    
    if callback_data in ("onboard_exam_JAMB", "onboard_exam_WAEC", "onboard_exam_NECO"):
        target_exam = callback_data.replace("onboard_exam_", "")
        state["target_exam"] = target_exam
        state["awaiting_response_for"] = "university_ambition"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = _get_fallback_message("university_ambition", state)
        await send_telegram_message(chat_id, msg)
        return
    
    if callback_data == "onboard_new":
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = _get_fallback_message("name", state)
        await send_telegram_message(chat_id, msg)
        return
    
    if callback_data == "onboard_returning":
        state["is_new_student"] = False
        state["awaiting_response_for"] = "wax_id_entry"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            "Welcome back! Send me your WAX ID — it looks like WAX-A74892. "
            "If you've forgotten it, just type *forgot*."
        )
        return


# ═══════════════════════════════════════════════
# STEP: WELCOME
# ═══════════════════════════════════════════════

@register_step("welcome")
async def _step_welcome(chat_id: int, state: dict, message: str):
    """First contact. Determine new vs returning."""
    msg_lower = message.strip().lower()
    
    # Detect if student already indicated new or returning
    if any(k in msg_lower for k in ["new", "i'm new", "create", "register", "signup", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        msg = await _generate_onboarding_message("welcome", state, message)
        await send_telegram_message(chat_id, msg)
        return
    
    if any(k in msg_lower for k in ["returning", "existing", "login", "have", "wax", "back"]):
        state["is_new_student"] = False
        state["awaiting_response_for"] = "wax_id_entry"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            "Welcome back! Send me your WAX ID — it looks like WAX-A74892. "
            "If you've forgotten it, just type *forgot*."
        )
        return
    
    # Unclear — ask with buttons (AI-generated welcome)
    state["awaiting_response_for"] = "welcome"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = await _generate_onboarding_message("welcome", state, message)
    await send_telegram_message(chat_id, msg, reply_markup=_build_new_returning_keyboard())


# ═══════════════════════════════════════════════
# STEP: NAME
# ═══════════════════════════════════════════════

@register_step("name")
async def _step_name(chat_id: int, state: dict, message: str):
    """Collect the student's name."""
    name, error = _validate_name(message)
    
    if error:
        await send_telegram_message(chat_id, error)
        return
    
    state["name"] = name
    state["awaiting_response_for"] = "class_level"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    # Pre-written: simple question, no AI needed
    msg = _get_fallback_message("class_level", state)
    await send_telegram_message(chat_id, msg, reply_markup=_build_class_keyboard())


# ═══════════════════════════════════════════════
# STEP: CLASS LEVEL
# ═══════════════════════════════════════════════

@register_step("class_level")
async def _step_class_level(chat_id: int, state: dict, message: str):
    """Collect class level. Can come from button callback or text."""
    class_level, error = _validate_class(message)
    
    if error:
        await send_telegram_message(chat_id, error, reply_markup=_build_class_keyboard())
        return
    
    state["class_level"] = class_level
    state["awaiting_response_for"] = "subjects"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = _get_fallback_message("subjects", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: SUBJECTS
# ═══════════════════════════════════════════════

@register_step("subjects")
async def _step_subjects(chat_id: int, state: dict, message: str):
    """Collect subjects. Extracts from free text using SUBJECT_MAP."""
    raw = message.strip()
    
    # Handle "I don't know"
    dont_know = ["i don't know", "idk", "not sure", "all of them", "everything"]
    if raw.lower() in dont_know:
        state["trouble_subject"] = ""
        state["subjects"] = ["english", "mathematics"]
        state["awaiting_response_for"] = "trouble_subject"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        # AI-generated: reacting to "I don't know" is a human moment
        msg = await _generate_onboarding_message("trouble_subject", state)
        await send_telegram_message(chat_id, msg)
        return
    
    # Try to extract subjects from their message
    # Lazy import to avoid circular dependency
    from telegram.handler import SUBJECT_MAP
    
    found_subjects = []
    msg_lower = raw.lower()
    
    for key, value in SUBJECT_MAP.items():
        if key.replace("_", " ") in msg_lower or key in msg_lower:
            if value not in found_subjects:
                found_subjects.append(value)
    
    # Always include English and Mathematics
    for core in ["english", "mathematics"]:
        if core not in found_subjects:
            found_subjects.insert(0, core)
    
    if len(found_subjects) >= 3:
        state["subjects"] = found_subjects[:12]
        state["awaiting_response_for"] = "trouble_subject"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("trouble_subject", state)
        await send_telegram_message(chat_id, msg)
        return
    
    # Not enough subjects — ask follow-up (pre-written)
    state["subjects"] = found_subjects
    await save_onboarding_state("telegram", str(chat_id), state)
    
    await send_telegram_message(chat_id,
        f"I caught {len(found_subjects)}. What else are you doing? I want the full picture."
    )


# ═══════════════════════════════════════════════
# STEP: TROUBLE SUBJECT
# ═══════════════════════════════════════════════

@register_step("trouble_subject")
async def _step_trouble_subject(chat_id: int, state: dict, message: str):
    """Collect the one subject that gives them the most trouble."""
    raw = message.strip()
    normalized = normalize_subject(raw)
    state["trouble_subject"] = normalized
    state["student_subject"] = normalized
    
    class_level = state.get("class_level", "SS3")
    
    if class_level == "SS3":
        state["awaiting_response_for"] = "target_exam"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = _get_fallback_message("target_exam", state)
        await send_telegram_message(chat_id, msg, reply_markup=_build_exam_keyboard())
    else:
        state["target_exam"] = "not_applicable"
        state["awaiting_response_for"] = "state"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = _get_fallback_message("state", state)
        await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: TARGET EXAM (SS3 only)
# ═══════════════════════════════════════════════

@register_step("target_exam")
async def _step_target_exam(chat_id: int, state: dict, message: str):
    """Collect exam type. Can come from button or text."""
    target_exam, error = _validate_exam(message)
    
    if error:
        await send_telegram_message(chat_id, error, reply_markup=_build_exam_keyboard())
        return
    
    state["target_exam"] = target_exam
    state["awaiting_response_for"] = "university_ambition"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = _get_fallback_message("university_ambition", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: UNIVERSITY AMBITION (SS3 only)
# ═══════════════════════════════════════════════

@register_step("university_ambition")
async def _step_university_ambition(chat_id: int, state: dict, message: str):
    """Collect university course ambition and check JAMB combination."""
    msg_lower = message.strip().lower()
    
    dont_know = ["not sure", "i don't know", "idk", "undecided", "haven't thought"]
    if any(phrase in msg_lower for phrase in dont_know):
        state["university_ambition"] = "undecided"
    else:
        state["university_ambition"] = message.strip()
        
        # Run JAMB Checker silently
        try:
            from content.jamb_checker import check_jamb_readiness
            result = check_jamb_readiness(
                student_subjects=state.get("subjects", []),
                desired_course=message.strip()
            )
            state["jamb_result"] = result
        except Exception:
            logger.error("JAMB checker failed during onboarding", exc_info=True)
    
    state["awaiting_response_for"] = "state"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = _get_fallback_message("state", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: STATE
# ═══════════════════════════════════════════════

@register_step("state")
async def _step_state(chat_id: int, state: dict, message: str):
    """Collect Nigerian state."""
    msg_lower = message.strip().lower()
    
    # Handle "yes" confirmations from fuzzy match suggestions
    if msg_lower in CONFIRMATION_WORDS:
        suggested_state = state.get("_suggested_state")
        if suggested_state:
            state["student_state"] = suggested_state
            state.pop("_suggested_state", None)
            state["pin_failed_attempts"] = 0
            state["awaiting_response_for"] = "pin_setup"
            await save_onboarding_state("telegram", str(chat_id), state)
            
            msg = _get_fallback_message("pin_setup", state)
            await send_telegram_message(chat_id, msg)
            return
    
    student_state, error = _validate_state(message)
    
    if error:
        # Check if error contains a fuzzy match suggestion (starts with "Did you mean")
        if error.startswith("Did you mean"):
            # Extract the suggested state from the error message
            # Format: "Did you mean *State Name*? ..."
            import re
            match = re.search(r'\*([^*]+)\*', error)
            if match:
                state["_suggested_state"] = match.group(1)
                await save_onboarding_state("telegram", str(chat_id), state)
        
        await send_telegram_message(chat_id, error)
        return
    
    # Clean up fuzzy match suggestion state if present
    state.pop("_suggested_state", None)
    state["student_state"] = student_state
    state["pin_failed_attempts"] = 0
    state["awaiting_response_for"] = "pin_setup"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = _get_fallback_message("pin_setup", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: PIN SETUP
# ═══════════════════════════════════════════════

@register_step("pin_setup")
async def _step_pin_setup(chat_id: int, state: dict, message: str):
    """Collect and validate PIN. Hashes before storing."""
    pin, error = _validate_pin(message)
    
    if error:
        failed = state.get("pin_failed_attempts", 0) + 1
        state["pin_failed_attempts"] = failed
        
        # Brute-force protection: lock after MAX_PIN_ATTEMPTS failures
        if failed >= MAX_PIN_ATTEMPTS:
            await clear_onboarding_state("telegram", str(chat_id))
            await send_telegram_message(chat_id, 
                "You've tried too many times. For your security, I'm restarting.\n\n"
                "Type *HI* when you're ready to try again with a code you'll remember."
            )
            logger.warning(f"PIN lockout triggered for chat_id={chat_id} after {failed} failed attempts")
            return
        
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id, error)
        return
    
    # Hash PIN with SHA-256 before storing in state
    state["pending_pin"] = hashlib.sha256(pin.encode()).hexdigest()
    state["pin_failed_attempts"] = 0  # Reset counter on valid PIN
    state["awaiting_response_for"] = "pin_confirm"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    await send_telegram_message(chat_id, "Got it! Type it again to confirm.")


# ═══════════════════════════════════════════════
# STEP: PIN CONFIRM
# ═══════════════════════════════════════════════

@register_step("pin_confirm")
async def _step_pin_confirm(chat_id: int, state: dict, message: str):
    """Confirm PIN and create account."""
    pin_confirm_hash = hashlib.sha256(message.strip().encode()).hexdigest()
    pending_pin = state.get("pending_pin", "")
    
    if pin_confirm_hash != pending_pin:
        failed = state.get("pin_failed_attempts", 0) + 1
        state["pin_failed_attempts"] = failed
        
        # Brute-force protection: lock after MAX_PIN_ATTEMPTS failures on confirm too
        if failed >= MAX_PIN_ATTEMPTS:
            await clear_onboarding_state("telegram", str(chat_id))
            await send_telegram_message(chat_id,
                "Too many wrong attempts. For your security, I'm restarting.\n\n"
                "Type *HI* when you're ready to try again."
            )
            logger.warning(f"PIN confirm lockout triggered for chat_id={chat_id} after {failed} failed confirm attempts")
            return
        
        state["pending_pin"] = None
        state["awaiting_response_for"] = "pin_setup"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        await send_telegram_message(chat_id, "Those didn't match. Let's try again — pick a code and type it.")
        return
    
    # PINs match — create account
    # Note: create_student receives the RAW PIN (not hashed) so it can hash with
    # its own salt/algorithm for final storage. We pass the original message.strip()
    # for the final PIN. Verif_ that create_student handles hashing internally.
    raw_pin = message.strip()
    
    subjects = state.get("subjects", ["english", "mathematics"])
    if "english" not in subjects:
        subjects.insert(0, "english")
    if "mathematics" not in subjects:
        subjects.insert(1, "mathematics")
    
    student = await create_student(
        platform="telegram",
        platform_user_id=str(chat_id),
        name=state.get("name", "Student"),
        pin=raw_pin,
        class_level=state.get("class_level"),
        target_exam=state.get("target_exam"),
        subjects=subjects,
        student_subject=state.get("trouble_subject", ""),
        student_state=state.get("student_state"),
    )
    
    if not student:
        await clear_onboarding_state("telegram", str(chat_id))
        await send_telegram_message(chat_id, 
            "Something went wrong creating your account. Try again — just send *HI* to restart."
        )
        logger.error(f"create_student returned None for chat_id={chat_id}")
        return
    
    await clear_onboarding_state("telegram", str(chat_id))
    
    # ── Activation: AI-generated welcome message ──
    msg = await _generate_onboarding_message("activation", state)
    await send_telegram_message(chat_id, msg)
    
    # ── Recovery code: separate urgent message ──
    recovery_msg = (
        f"🔐 *Your Recovery Code:* `{student['recovery_code']}`\n\n"
        f"⚠️ *Write this down NOW. On paper. Not in this chat.*\n"
        f"This message is not saved anywhere. If you lose this code and forget your PIN, "
        f"you cannot recover your account.\n\n"
        f"Your WAX ID (safe to share): *{student['wax_id']}*"
    )
    await send_telegram_message(chat_id, recovery_msg)
    
    # ── JAMB result: separate follow-up (if applicable) ──
    jamb_result = state.get("jamb_result")
    if jamb_result:
        await asyncio.sleep(1.5)  # Small pause so messages don't arrive all at once
        if jamb_result.get("ready"):
            await send_telegram_message(chat_id,
                f"✅ Good news — your subjects match *{jamb_result.get('course_display', 'your course')}*! "
                f"You're on the right track."
            )
        elif jamb_result.get("missing"):
            missing_names = [m["preferred"] if isinstance(m, dict) else m for m in jamb_result["missing"]]
            await send_telegram_message(chat_id,
                f"Quick note: for *{jamb_result.get('course_display', 'that course')}*, "
                f"you'd need {', '.join(missing_names)}. We can talk about this — but first, let's study."
            )
    
    # ── Final nudge to start ──
    await asyncio.sleep(1)
    await send_telegram_message(chat_id, 
        "Did you write down the recovery code? Good.\n\nNow — what do you want to study first?"
    )


# ═══════════════════════════════════════════════
# WAX ID ENTRY (Returning Students)
# ═══════════════════════════════════════════════

@register_step("wax_id_entry")
async def _step_wax_id_entry(chat_id: int, state: dict, message: str):
    """Handle returning student WAX ID entry."""
    msg = message.strip().lower()
    
    if any(k in msg for k in ["new", "create", "register", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        msg = _get_fallback_message("name", state)
        await send_telegram_message(chat_id, msg)
        return
    
    wax_id = message.strip().upper()
    if wax_id.startswith("WAX-") and len(wax_id) == 10:
        state["pending_wax_id"] = wax_id
        state["awaiting_response_for"] = "pin_entry"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            f"Got you. Now enter your secret code. If you've forgotten it, type *forgot*."
        )
        return
    
    await send_telegram_message(chat_id,
        "That doesn't look like a WAX ID. It should be WAX-A74892. Try again, or type *new* to start fresh."
    )


@register_step("pin_entry")
async def _step_pin_entry(chat_id: int, state: dict, message: str):
    """Handle returning student PIN entry."""
    msg = message.strip().lower()
    
    if any(k in msg for k in ["new", "create", "register", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        msg = _get_fallback_message("name", state)
        await send_telegram_message(chat_id, msg)
        return
    
    await send_telegram_message(chat_id,
        "PIN login is coming soon. For now, type *new* to create a fresh account and start studying immediately."
    )
