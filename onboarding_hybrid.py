"""
WaxPrep v2 — Hybrid AI-Driven Onboarding
Code controls WHAT to ask. AI generates HOW to ask.
Every student gets a unique onboarding conversation.

Architecture:
    - State machine tracks required fields
    - AI generates every message fresh per student
    - Code validates responses and advances state
    - Inline buttons for structured choices (class, exam)
    - Free text for personal responses (name, subjects, state)
    - University ambition guessed from subjects for SS3
    - PIN setup warm but code-enforced

Fallback: telegram/onboarding.py (scripted version)
"""

import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from telegram.sender import send_telegram_message
from database.onboarding_state import save_onboarding_state, clear_onboarding_state
from helpers import clean_name
from database.students import create_student
from content.subject_hooks import normalize_subject

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

WEAK_PINS = {
    "1234", "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
    "password", "qwerty", "abcd", "12345", "waxp", "admin", "login",
}

# ═══════════════════════════════════════════════
# ONBOARDING STATE MACHINE
# ═══════════════════════════════════════════════

REQUIRED_FIELDS = ["name", "class_level", "subjects", "target_exam", "student_state", "pin"]
SS1_SS2_FIELDS = ["name", "class_level", "subjects", "student_state", "pin"]  # No exam for SS1/SS2

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
    
    The AI receives context about the student and the current step,
    and generates a message that feels human, not scripted.
    
    Args:
        step: Current onboarding step (welcome, name, class_level, etc.)
        state: Current onboarding state with collected data
        student_message: The student's last message (for reactions)
        validation_error: What went wrong (for retry prompts)
    
    Returns:
        AI-generated message text
    """
    from ai.brain import _get_client
    from config.settings import settings
    
    name = state.get("name", "").split()[0] if state.get("name") else ""
    class_level = state.get("class_level", "")
    subjects = state.get("subjects", [])
    target_exam = state.get("target_exam", "")
    student_state = state.get("student_state", "")
    trouble_subject = state.get("trouble_subject", "")
    
    # Build the AI prompt based on the current step
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

        "name": f"""
You are Wax onboarding a new student.
The student just said: "{student_message}"
{f"Validation error: {validation_error}" if validation_error else ""}

Generate a message asking for their name. 
- If they already gave a name but it's invalid (too short, single word), gently ask again
- If this is the first ask: "What do people call you at home? Your real name o."
- React to their name if they gave one. If it's Nigerian, acknowledge it warmly.
- Keep it under 3 sentences. No dashes, no numbers.
""",

        "class_level": f"""
You are Wax onboarding {name if name else 'a new student'}.
{f"They just said: '{student_message}'" if student_message else ""}
{f"Validation error: {validation_error}" if validation_error else ""}

Generate a message asking for their class level (SS1, SS2, or SS3).
- Make it natural: "What class are you in?"
- If this is a retry: "Just type SS1, SS2, or SS3."
- Include inline button suggestion but the code handles buttons separately
- Keep it under 2 sentences.
""",

        "subjects": f"""
You are Wax onboarding {name}, an {class_level} student.
{f"They just said: '{student_message}'" if student_message else ""}

Generate a message asking what subjects they're doing in school.
- Start open-ended: "What subjects are you doing in school?"
- If they already mentioned some subjects, acknowledge them: "So you're doing Physics and Chemistry. What else?"
- Make it feel like a teacher getting to know them, not a form
- Keep it under 3 sentences.
""",

        "target_exam": f"""
You are Wax onboarding {name}, an {class_level} student doing {', '.join(subjects) if subjects else 'subjects'}.

Generate a message asking which exam they're preparing for.
- For SS3: "Which exam are you preparing for? JAMB, WAEC, or NECO?"
- Be warm but efficient. They've already answered several questions.
- Keep it under 2 sentences.
""",

        "university_ambition": f"""
You are Wax onboarding {name}, an SS3 student doing {', '.join(subjects) if subjects else 'subjects'} and preparing for {target_exam}.

Generate a message asking what they want to study in university.
- Make a guess based on their subjects: if they have Physics+Chemistry+Biology, guess Medicine or Engineering
- "With these subjects, I'm guessing Medicine or Engineering. Am I close?"
- If you guess wrong, it invites them to correct you. That's good.
- Keep it under 3 sentences.
""",

        "state": f"""
You are Wax onboarding {name}, an {class_level} student from Nigeria.
{f"They just said: '{student_message}'" if student_message else ""}
{f"Validation error: {validation_error}" if validation_error else ""}

Generate a message asking which state they're in.
- Explain WHY: "This helps me use examples you'll actually relate to."
- Give examples: "Lagos? Kano? Rivers?"
- Keep it under 2 sentences.
""",

        "pin_setup": f"""
You are Wax onboarding {name}.
{f"Validation error: {validation_error}" if validation_error else ""}

Generate a message asking them to create a secret code (PIN).
- First ask: "Create a secret code — at least 4 characters. Letters, numbers, or mix them up."
- If they picked a weak PIN: be funny but firm. "My friend. You chose the code equivalent of leaving your door open."
- If they confirmed: "Got it. Type it again to confirm."
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
    
    prompt = step_prompts.get(step, f"Generate a warm, brief onboarding message for step: {step}. Student: {name}. Be Nigerian. Be yourself.")
    
    try:
        client = _get_client(settings.GROQ_API_KEY)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.GROQ_SMART_MODEL,
            messages=[
                {"role": "system", "content": "You are Wax — a warm, funny, Nigerian teacher. You never say 'don't worry.' You never use dashes or numbered lists. You talk like a real person. Keep every message under 3 sentences during onboarding."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.8,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI onboarding message generation failed: {e}")
        return _get_fallback_message(step, state)


def _get_fallback_message(step: str, state: dict) -> str:
    """Fallback messages if AI generation fails. Same warmth, just pre-written."""
    name = state.get("name", "").split()[0] if state.get("name") else ""
    
    fallbacks = {
        "welcome": "Oya, a serious student. I'm Wax. Are you new here or returning?",
        "name": "My person! What do people call you at home? Your real name o.",
        "class_level": f"{name}, what class are you in? SS1, SS2, or SS3?",
        "subjects": f"What subjects are you doing in school, {name}? Type them out — I want the full picture.",
        "target_exam": "Which exam are you preparing for? JAMB, WAEC, or NECO?",
        "university_ambition": "Have you thought about what you want to study in university?",
        "state": "Which state are you based in? It helps me give you examples you'll actually relate to.",
        "pin_setup": "Create a secret code — at least 4 characters. Letters, numbers, or mix them up. Something your younger sibling can't guess.",
        "activation": f"{name}. You're in! I know what we're up against. I won't give up on you. What do you want to study first?",
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
    """Validate Nigerian state. Returns (state_name, error_message)."""
    raw = text.strip()
    state_name = raw.title()
    if len(raw) <= 2:
        return "", "Type the full name — like Kano or Lagos."
    if raw.lower() not in NIGERIAN_STATES:
        return "", f"Hmm, I don't recognize '{raw}' as a Nigerian state. Try the full name?"
    return state_name, ""

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
        
        msg = await _generate_onboarding_message("subjects", state)
        await send_telegram_message(chat_id, msg)
        return
    
    if callback_data in ("onboard_exam_JAMB", "onboard_exam_WAEC", "onboard_exam_NECO"):
        target_exam = callback_data.replace("onboard_exam_", "")
        state["target_exam"] = target_exam
        state["awaiting_response_for"] = "university_ambition"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("university_ambition", state)
        await send_telegram_message(chat_id, msg)
        return
    
    if callback_data == "onboard_new":
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("name", state)
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
        msg = await _generate_onboarding_message("name", state)
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
    
    # Unclear — ask with buttons
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
        msg = await _generate_onboarding_message("name", state, message, error)
        await send_telegram_message(chat_id, msg)
        return
    
    state["name"] = name
    state["awaiting_response_for"] = "class_level"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    # Send name reaction + class question with buttons
    msg = await _generate_onboarding_message("class_level", state, name)
    await send_telegram_message(chat_id, msg, reply_markup=_build_class_keyboard())


# ═══════════════════════════════════════════════
# STEP: CLASS LEVEL
# ═══════════════════════════════════════════════

@register_step("class_level")
async def _step_class_level(chat_id: int, state: dict, message: str):
    """Collect class level. Can come from button callback or text."""
    class_level, error = _validate_class(message)
    
    if error:
        msg = await _generate_onboarding_message("class_level", state, message, error)
        await send_telegram_message(chat_id, msg, reply_markup=_build_class_keyboard())
        return
    
    state["class_level"] = class_level
    state["awaiting_response_for"] = "subjects"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = await _generate_onboarding_message("subjects", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: SUBJECTS
# ═══════════════════════════════════════════════

@register_step("subjects")
async def _step_subjects(chat_id: int, state: dict, message: str):
    """Collect subjects. AI extracts from free text."""
    raw = message.strip()
    first = state.get("name", "Student").split()[0]
    
    # Handle "I don't know"
    dont_know = ["i don't know", "idk", "not sure", "all of them", "everything"]
    if raw.lower() in dont_know:
        state["trouble_subject"] = "Mathematics"
        state["subjects"] = ["english", "mathematics"]
        state["awaiting_response_for"] = "trouble_subject"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("subjects", state, 
            "Student doesn't know their subjects. Defaulting to English and Maths. Ask which subject gives them trouble.")
        await send_telegram_message(chat_id, msg)
        return
    
    # Try to extract subjects from their message
    # First pass: normalize subjects from SUBJECT_MAP
    from telegram.handler import SUBJECT_MAP
    
    found_subjects = []
    msg_lower = raw.lower()
    
    for key, value in SUBJECT_MAP.items():
        # Check if the subject name or key appears in the message
        if key.replace("_", " ") in msg_lower or key in msg_lower:
            if value not in found_subjects:
                found_subjects.append(value)
    
    # Always include English and Mathematics
    for core in ["english", "mathematics"]:
        if core not in found_subjects:
            found_subjects.insert(0, core)
    
    if len(found_subjects) >= 3:
        # We got enough subjects
        state["subjects"] = found_subjects[:12]  # Cap at 12
        state["awaiting_response_for"] = "trouble_subject"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("subjects", state,
            f"Student mentioned {len(found_subjects)} subjects. Ask which one gives them the most trouble.")
        await send_telegram_message(chat_id, msg)
        return
    
    # Not enough subjects extracted — ask follow-up
    state["subjects"] = found_subjects
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = await _generate_onboarding_message("subjects", state,
        f"Only found {len(found_subjects)} subjects. Ask what else they're doing.")
    await send_telegram_message(chat_id, msg)


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
    
    # SS3 → ask exam. SS1/SS2 → skip to state
    if class_level == "SS3":
        state["awaiting_response_for"] = "target_exam"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("target_exam", state)
        await send_telegram_message(chat_id, msg, reply_markup=_build_exam_keyboard())
    else:
        state["target_exam"] = "not_applicable"
        state["awaiting_response_for"] = "state"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("state", state)
        await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: TARGET EXAM (SS3 only)
# ═══════════════════════════════════════════════

@register_step("target_exam")
async def _step_target_exam(chat_id: int, state: dict, message: str):
    """Collect exam type. Can come from button or text."""
    target_exam, error = _validate_exam(message)
    
    if error:
        msg = await _generate_onboarding_message("target_exam", state, message, error)
        await send_telegram_message(chat_id, msg, reply_markup=_build_exam_keyboard())
        return
    
    state["target_exam"] = target_exam
    state["awaiting_response_for"] = "university_ambition"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = await _generate_onboarding_message("university_ambition", state)
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
            pass
    
    state["awaiting_response_for"] = "state"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = await _generate_onboarding_message("state", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: STATE
# ═══════════════════════════════════════════════

@register_step("state")
async def _step_state(chat_id: int, state: dict, message: str):
    """Collect Nigerian state."""
    student_state, error = _validate_state(message)
    
    if error:
        msg = await _generate_onboarding_message("state", state, message, error)
        await send_telegram_message(chat_id, msg)
        return
    
    state["student_state"] = student_state
    state["pin_failed_attempts"] = 0
    state["awaiting_response_for"] = "pin_setup"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    msg = await _generate_onboarding_message("pin_setup", state)
    await send_telegram_message(chat_id, msg)


# ═══════════════════════════════════════════════
# STEP: PIN SETUP
# ═══════════════════════════════════════════════

@register_step("pin_setup")
async def _step_pin_setup(chat_id: int, state: dict, message: str):
    """Collect and validate PIN."""
    pin, error = _validate_pin(message)
    
    if error:
        failed = state.get("pin_failed_attempts", 0) + 1
        state["pin_failed_attempts"] = failed
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("pin_setup", state, message, error)
        await send_telegram_message(chat_id, msg)
        return
    
    state["pending_pin"] = pin
    state["awaiting_response_for"] = "pin_confirm"
    await save_onboarding_state("telegram", str(chat_id), state)
    
    await send_telegram_message(chat_id, "Got it! Type it again to confirm.")


@register_step("pin_confirm")
async def _step_pin_confirm(chat_id: int, state: dict, message: str):
    """Confirm PIN and create account."""
    pin_confirm = message.strip()
    pending_pin = state.get("pending_pin", "")
    
    if pin_confirm != pending_pin:
        state["pending_pin"] = None
        state["awaiting_response_for"] = "pin_setup"
        await save_onboarding_state("telegram", str(chat_id), state)
        
        msg = await _generate_onboarding_message("pin_setup", state, "", "PINs don't match")
        await send_telegram_message(chat_id, msg)
        return
    
    # ── Create account ──
    subjects = state.get("subjects", ["english", "mathematics"])
    if "english" not in subjects:
        subjects.insert(0, "english")
    if "mathematics" not in subjects:
        subjects.insert(1, "mathematics")
    
    student = await create_student(
        platform="telegram",
        platform_user_id=str(chat_id),
        name=state.get("name", "Student"),
        pin=pending_pin,
        class_level=state.get("class_level"),
        target_exam=state.get("target_exam"),
        subjects=subjects,
        student_subject=state.get("trouble_subject", ""),
        student_state=state.get("student_state"),
    )
    
    if not student:
        await send_telegram_message(chat_id, 
            "Something went wrong creating your account. Try again — just send *HI* to restart.")
        return
    
    await clear_onboarding_state("telegram", str(chat_id))
    
    # ── Activation ──
    msg = await _generate_onboarding_message("activation", state)
    
    # Insert WAX ID and recovery code
    activation = (
        f"{msg}\n\n"
        f"*Your account details — save these:*\n"
        f"WAX ID: *{student['wax_id']}*\n"
        f"Recovery Code: *{student['recovery_code']}*\n\n"
        f"⚠️ Write that code somewhere safe. Not in this chat."
    )
    
    # If JAMB Checker ran, add result
    jamb_result = state.get("jamb_result")
    if jamb_result:
        if jamb_result.get("ready"):
            activation += f"\n\n✅ Your subjects match *{jamb_result.get('course_display', 'your course')}*!"
        elif jamb_result.get("missing"):
            missing_names = [m["preferred"] if isinstance(m, dict) else m for m in jamb_result["missing"]]
            activation += f"\n\n⚠️ You're missing {', '.join(missing_names)} for {jamb_result.get('course_display', 'that course')}."
    
    await send_telegram_message(chat_id, activation)


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
        msg = await _generate_onboarding_message("name", state)
        await send_telegram_message(chat_id, msg)
        return
    
    wax_id = message.strip().upper()
    if wax_id.startswith("WAX-") and len(wax_id) == 10:
        state["pending_wax_id"] = wax_id
        state["awaiting_response_for"] = "pin_entry"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            f"Got you. Now enter your secret code. If you've forgotten it, type *forgot*.")
        return
    
    await send_telegram_message(chat_id,
        "That doesn't look like a WAX ID. It should be WAX-A74892. Try again, or type *new* to start fresh.")


@register_step("pin_entry")
async def _step_pin_entry(chat_id: int, state: dict, message: str):
    """Handle returning student PIN entry."""
    msg = message.strip().lower()
    
    if any(k in msg for k in ["new", "create", "register", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        msg = await _generate_onboarding_message("name", state)
        await send_telegram_message(chat_id, msg)
        return
    
    await send_telegram_message(chat_id,
        "PIN login is coming soon. For now, type *new* to create a fresh account and start studying immediately.")
