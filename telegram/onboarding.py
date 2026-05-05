"""
WaxPrep v2 — Telegram Onboarding Flow
Handles every step of onboarding for new students on Telegram.
State is stored in Redis via database/onboarding_state.py — NOT in conversations.
"""

import random
from datetime import datetime

from telegram.sender import send_telegram_message
from database.onboarding_state import save_onboarding_state, clear_onboarding_state
from helpers import clean_name
from database.students import create_student
from content.subject_hooks import normalize_subject, get_magic_trick, get_subject_fallback


# ──────────────────────────────────────────────
# STEP MAP — which function handles each step
# ──────────────────────────────────────────────

STEP_HANDLERS = {}


def register_step(step_name: str):
    """Decorator to register an onboarding step handler."""
    def wrapper(func):
        STEP_HANDLERS[step_name] = func
        return func
    return wrapper


# ──────────────────────────────────────────────
# RETRY VARIANT GENERATORS — each step gets its own rotating prompts
# ──────────────────────────────────────────────

def _get_goal_retry():
    return random.choice([
        "Just pick one that's closest:\n\n"
        "*1* — My schoolwork\n"
        "*2* — Preparing for a test or exam\n"
        "*3* — I just want to learn something new",

        "No wahala — choose the one that fits best:\n\n"
        "*1* — Schoolwork help\n"
        "*2* — Exam preparation\n"
        "*3* — General learning",

        "I just need to know where to focus:\n\n"
        "*1* — Schoolwork\n"
        "*2* — Exam prep\n"
        "*3* — I want to learn something",

        "Pick one — you can always change later:\n\n"
        "*1* — My schoolwork\n"
        "*2* — Test or exam prep\n"
        "*3* — Just curious to learn",
    ])


def _get_class_level_retry():
    return random.choice([
        "Please reply with a number from 1 to 6:\n\n"
        "1 — JSS1\n2 — JSS2\n3 — JSS3\n"
        "4 — SS1\n5 — SS2\n6 — SS3",

        "Just type the number that matches your class:\n\n"
        "1 = JSS1, 2 = JSS2, 3 = JSS3\n"
        "4 = SS1, 5 = SS2, 6 = SS3",

        "Which class? Reply with just the number:\n\n"
        "1 — JSS1\n2 — JSS2\n3 — JSS3\n"
        "4 — SS1\n5 — SS2\n6 — SS3",
    ])


def _get_exam_retry():
    return random.choice([
        "Please reply with 1, 2, or 3:\n\n"
        "1 — JAMB\n2 — WAEC\n3 — NECO",

        "Which exam? Just the number:\n\n"
        "1 = JAMB, 2 = WAEC, 3 = NECO",

        "Pick your exam — 1, 2, or 3:\n\n"
        "1 — JAMB (UTME)\n2 — WAEC (SSCE)\n3 — NECO",
    ])


def _get_pin_retry(failed_attempts: int):
    """Escalates help after repeated PIN failures."""
    base = "Your PIN must be exactly 4 digits."
    if failed_attempts < 2:
        return random.choice([
            f"{base} Please try again.",
            f"{base} Just type any 4 numbers.",
            f"{base} Something like 5823 — but pick your own!",
        ])
    elif failed_attempts < 4:
        return random.choice([
            f"Still having trouble? {base} Think of the last 4 digits of a phone number only you know.",
            f"Let me help. {base} Pick 4 numbers from something around you — a receipt, a clock, or a page number.",
            f"No wahala. {base} Try using 4 digits you won't forget — maybe from a number you see often but others don't.",
        ])
    else:
        return f"I know this is frustrating. {base} Take a breath. Pick any 4 digits that are easy for YOU to remember but hard for others to guess. Type them now."


# ──────────────────────────────────────────────
# MAIN DISPATCHER
# ──────────────────────────────────────────────

async def handle_onboarding(chat_id: int, state: dict, message: str):
    """
    Called for EVERY message from an unregistered user.
    Reads the current step from state, routes to the right handler.
    If no step is set, starts from new_or_existing.
    """
    step = state.get("awaiting_response_for", "new_or_existing")
    handler = STEP_HANDLERS.get(step)

    if handler:
        await handler(chat_id, state, message)
    else:
        # Unknown step — restart
        await _start_new_or_existing(chat_id, state, message)


# ──────────────────────────────────────────────
# STEP: new_or_existing
# ──────────────────────────────────────────────

@register_step("new_or_existing")
async def _start_new_or_existing(chat_id: int, state: dict, message: str):
    msg = message.strip().lower()

    # Check if returning user
    if any(k in msg for k in ["2", "existing", "login", "log in", "have", "wax"]):
        await send_telegram_message(
            chat_id,
            "Before we log you in, please accept our Terms of Service.\n\n"
            "By using WaxPrep, you agree to use it for your own study, "
            "keep your PIN private, and not misuse the platform.\n\n"
            "Type *YES* to accept and log in."
        )
        state["awaiting_response_for"] = "terms_acceptance"
        state["is_new_student"] = False
        await save_onboarding_state("telegram", str(chat_id), state)
        return

    # New student
    if any(k in msg for k in ["1", "new", "i'm new", "create", "register", "signup"]):
        await send_telegram_message(
            chat_id,
            "Great! Let's get you set up. First — what do you need help with?\n\n"
            "*1* — My schoolwork\n"
            "*2* — Preparing for a test or exam\n"
            "*3* — I just want to learn something new\n\n"
            "_(Reply with the number, or just tell me in your own words)_"
        )
        state["awaiting_response_for"] = "student_goal"
        state["is_new_student"] = True
        await save_onboarding_state("telegram", str(chat_id), state)
        return

    # Unclear — ask again with a random variant
    welcomes = [
        "Are you new to WaxPrep, or do you already have an account?\n\n"
        "*1* — I'm new\n"
        "*2* — I have a WAX ID",

        "Quick one — have we met before?\n\n"
        "*1* — No, I'm new here\n"
        "*2* — Yes, I have a WAX ID",

        "Welcome! Let me know where you stand:\n\n"
        "*1* — I'm creating a new account\n"
        "*2* — I already have an account",

        "First time or returning? No wrong answer:\n\n"
        "*1* — First time, let's go\n"
        "*2* — I've been here before",

        "Before we dive in — are you new or returning?\n\n"
        "*1* — Brand new\n"
        "*2* — I have a WAX ID",
    ]
    await send_telegram_message(chat_id, random.choice(welcomes))


# ──────────────────────────────────────────────
# STEP: student_goal
# ──────────────────────────────────────────────

@register_step("student_goal")
async def _step_student_goal(chat_id: int, state: dict, message: str):
    msg = message.strip().lower()

    goal_map = {
        "1": "schoolwork", "2": "exam prep", "3": "learning",
        "school": "schoolwork", "exam": "exam prep", "learn": "learning",
    }

    goal = None
    for key, value in goal_map.items():
        if key in msg:
            goal = value
            break

    if not goal:
        await send_telegram_message(chat_id, _get_goal_retry())
        return

    await send_telegram_message(
        chat_id,
        f"Got it — {goal}. Before we continue, please accept our Terms of Service.\n\n"
        "By using WaxPrep, you agree to use it for your own study, "
        "keep your PIN private, and not misuse the platform.\n\n"
        "Type *YES* to accept and create your account."
    )
    state["student_goal"] = goal
    state["awaiting_response_for"] = "terms_acceptance"
    await save_onboarding_state("telegram", str(chat_id), state)


# ──────────────────────────────────────────────
# STEP: terms_acceptance
# ──────────────────────────────────────────────

@register_step("terms_acceptance")
async def _step_terms_acceptance(chat_id: int, state: dict, message: str):
    msg = message.strip().lower()
    is_new = state.get("is_new_student", False)

    if msg in ["yes", "y", "agree", "accept", "i agree", "i accept", "ok", "okay", "1"]:
        if is_new:
            await send_telegram_message(
                chat_id,
                "Thank you! Let's set up your account.\n\n"
                "First, what is your full name?\n\n"
                "_(Type your first and last name)_"
            )
            state["terms_accepted"] = True
            state["terms_accepted_at"] = datetime.utcnow().isoformat()
            state["awaiting_response_for"] = "name"
            await save_onboarding_state("telegram", str(chat_id), state)
        else:
            await send_telegram_message(
                chat_id,
                "Welcome back!\n\nSend your WAX ID to log in.\n\n"
                "It looks like: *WAX-A74892*"
            )
            state["terms_accepted"] = True
            state["terms_accepted_at"] = datetime.utcnow().isoformat()
            state["awaiting_response_for"] = "wax_id_entry"
            await save_onboarding_state("telegram", str(chat_id), state)
    elif msg in ["no", "n", "decline", "reject", "2"]:
        state["terms_declined"] = True
        state["awaiting_response_for"] = "decline_reason"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(
            chat_id,
            "No problem at all.\n\n"
            "Before you go — would you mind telling me why? It helps me improve.\n\n"
            "*1* — I don't understand what this is\n"
            "*2* — I'm not comfortable with the terms\n"
            "*3* — I was just looking around\n"
            "*4* — I'll decide later"
        )
    else:
        await send_telegram_message(
            chat_id,
            "Please reply *YES* to accept and continue, or *NO* to decline."
        )


# ──────────────────────────────────────────────
# STEP: decline_reason
# ──────────────────────────────────────────────

@register_step("decline_reason")
async def _step_decline_reason(chat_id: int, state: dict, message: str):
    msg = message.strip()
    reason_map = {
        "1": "didn't understand",
        "2": "uncomfortable with terms",
        "3": "just looking",
        "4": "decide later",
    }
    reason = reason_map.get(msg, msg[:200])
    print(f"User {chat_id} declined terms. Reason: {reason}")
    await send_telegram_message(
        chat_id,
        "Thanks for letting me know. WaxPrep will be here whenever you're ready.\n\n"
        "Type *HI* anytime to start again."
    )
    await clear_onboarding_state("telegram", str(chat_id))


# ──────────────────────────────────────────────
# STEP: name
# ──────────────────────────────────────────────

@register_step("name")
async def _step_name(chat_id: int, state: dict, message: str):
    name = clean_name(message)

    if len(name) < 3 or len(name.split()) < 2:
        await send_telegram_message(
            chat_id,
            "Please enter your first and last name, like *Chidera Emeka* or *Amina Bello*."
        )
        return

    first = name.split()[0]
    state["name"] = name
    state["awaiting_response_for"] = "subject_selection"
    await save_onboarding_state("telegram", str(chat_id), state)

    await send_telegram_message(
        chat_id,
        f"Nice to meet you, *{first}*!\n\n"
        "Before we go further — which subject gives you the most trouble right now?\n\n"
        "_(Just type the subject name — e.g. Physics, Maths, Chemistry, English)_"
    )


# ──────────────────────────────────────────────
# STEP: subject_selection → fires Magic Trick instantly
# ──────────────────────────────────────────────

@register_step("subject_selection")
async def _step_subject_selection(chat_id: int, state: dict, message: str):
    raw_subject = message.strip()
    normalized = normalize_subject(raw_subject)

    # Handle "I don't know" or empty responses
    dont_know = ["i don't know", "i dont know", "all of them", "everything", "not sure", "idk", "none", "all"]
    if raw_subject.lower() in dont_know:
        normalized = "Mathematics"
        await send_telegram_message(
            chat_id,
            "No wahala. Let's start with Mathematics — it's the foundation for most subjects."
        )

    # Save the subject
    state["student_subject"] = normalized
    state["awaiting_response_for"] = "class_level"
    await save_onboarding_state("telegram", str(chat_id), state)

    # Determine level for the Magic Trick (default SS3 since we don't know yet)
    level = state.get("class_level", "SS3")
    first = state.get("name", "Student").split()[0]

    # Get the Magic Trick
    trick = get_magic_trick(normalized, level)
    if trick:
        await send_telegram_message(chat_id, trick.render())
    else:
        fallback = get_subject_fallback(normalized)
        await send_telegram_message(chat_id, fallback)

    # Auto-advance to class level
    await send_telegram_message(
        chat_id,
        f"Now let's get you set up, *{first}*.\n\n"
        "What class are you in?\n\n"
        "1 — JSS1\n2 — JSS2\n3 — JSS3\n"
        "4 — SS1\n5 — SS2\n6 — SS3\n\n"
        "_(Reply with the number)_"
    )


# ──────────────────────────────────────────────
# STEP: class_level
# ──────────────────────────────────────────────

@register_step("class_level")
async def _step_class_level(chat_id: int, state: dict, message: str):
    msg = message.strip()

    class_map = {
        "1": "JSS1", "2": "JSS2", "3": "JSS3",
        "4": "SS1", "5": "SS2", "6": "SS3",
    }

    class_level = class_map.get(msg)
    if not class_level:
        await send_telegram_message(chat_id, _get_class_level_retry())
        return

    await send_telegram_message(
        chat_id,
        f"{class_level}!\n\n"
        "Which exam are you preparing for?\n\n"
        "1 — JAMB (UTME)\n2 — WAEC (SSCE)\n3 — NECO\n\n"
        "_(Reply with the number)_"
    )
    state["class_level"] = class_level
    state["awaiting_response_for"] = "target_exam"
    await save_onboarding_state("telegram", str(chat_id), state)


# ──────────────────────────────────────────────
# STEP: target_exam
# ──────────────────────────────────────────────

@register_step("target_exam")
async def _step_target_exam(chat_id: int, state: dict, message: str):
    msg = message.strip().upper()

    exam_map = {"1": "JAMB", "2": "WAEC", "3": "NECO", "JAMB": "JAMB", "WAEC": "WAEC", "NECO": "NECO"}

    target_exam = exam_map.get(msg)
    if not target_exam:
        await send_telegram_message(chat_id, _get_exam_retry())
        return

    await send_telegram_message(
        chat_id,
        f"{target_exam}!\n\n"
        "Which state are you in?\n\n"
        "_(e.g. Lagos, Abuja, Kano, Rivers)_"
    )
    state["target_exam"] = target_exam
    state["awaiting_response_for"] = "state"
    await save_onboarding_state("telegram", str(chat_id), state)


# ──────────────────────────────────────────────
# STEP: state
# ──────────────────────────────────────────────

@register_step("state")
async def _step_state(chat_id: int, state: dict, message: str):
    student_state = message.strip().title()

    await send_telegram_message(
        chat_id,
        f"{student_state}!\n\n"
        "Almost done! Set a 4-digit security PIN.\n\n"
        "Your PIN is how you log in on any device. Keep it private.\n\n"
        "_(Enter any 4 digits, e.g. 5823)_"
    )
    state["student_state"] = student_state
    state["awaiting_response_for"] = "pin_setup"
    state["pin_failed_attempts"] = 0
    await save_onboarding_state("telegram", str(chat_id), state)


# ──────────────────────────────────────────────
# STEP: pin_setup
# ──────────────────────────────────────────────

@register_step("pin_setup")
async def _step_pin_setup(chat_id: int, state: dict, message: str):
    pin = message.strip()

    if not pin.isdigit() or len(pin) != 4:
        failed = state.get("pin_failed_attempts", 0) + 1
        state["pin_failed_attempts"] = failed
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id, _get_pin_retry(failed))
        return

    weak_pins = {"1234", "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999"}
    if pin in weak_pins:
        await send_telegram_message(
            chat_id,
            "That PIN is too easy to guess. Please choose a more unique one."
        )
        return

    await send_telegram_message(
        chat_id,
        "Got it! Confirm your PIN by typing it again."
    )
    state["pending_pin"] = pin
    state["awaiting_response_for"] = "pin_confirm"
    await save_onboarding_state("telegram", str(chat_id), state)


# ──────────────────────────────────────────────
# STEP: pin_confirm
# ──────────────────────────────────────────────

@register_step("pin_confirm")
async def _step_pin_confirm(chat_id: int, state: dict, message: str):
    pin_confirm = message.strip()
    pending_pin = state.get("pending_pin", "")

    if pin_confirm != pending_pin:
        await send_telegram_message(
            chat_id,
            "Those PINs do not match.\n\n"
            "Please enter your desired PIN again:"
        )
        state["pending_pin"] = None
        state["awaiting_response_for"] = "pin_setup"
        await save_onboarding_state("telegram", str(chat_id), state)
        return

    # ── CREATE ACCOUNT ────────────────────────
    student = await create_student(
        platform="telegram",
        platform_user_id=str(chat_id),
        name=state.get("name", "Student"),
        pin=pending_pin,
        class_level=state.get("class_level"),
        target_exam=state.get("target_exam"),
        student_state=state.get("student_state"),
    )

    if not student:
        await send_telegram_message(
            chat_id,
            "Something went wrong creating your account. Please try again — send *HI* to restart."
        )
        return

    # ── CLEANUP ───────────────────────────────
    await clear_onboarding_state("telegram", str(chat_id))

    name_first = student["name"].split()[0]
    student_subject = state.get("student_subject", "your subjects")

    await send_telegram_message(
        chat_id,
        f"Welcome to WaxPrep, *{name_first}*!\n\n"
        f"*Your account details — save these:*\n"
        f"WAX ID: *{student['wax_id']}*\n"
        f"Recovery Code: *{student['recovery_code']}*\n\n"
        f"*Full Access is now ACTIVE!*\n\n"
        f"We'll tackle {student_subject} together. "
        f"You can ask me questions, take quizzes, and I'll remember "
        f"everything you've learned. What would you like to study first?"
    )
