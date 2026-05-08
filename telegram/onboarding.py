"""
WaxPrep v2 — Telegram Onboarding Flow
The Smart Older Cousin Who Aced JAMB.

No dashes. No numbers. No AI feel.
Just a conversation that makes students feel seen.
"""

import asyncio
import random
from datetime import datetime, timezone
from telegram.sender import send_telegram_message
from database.onboarding_state import save_onboarding_state, clear_onboarding_state
from helpers import clean_name
from database.students import create_student
from content.subject_hooks import normalize_subject, get_magic_trick, get_subject_fallback

STEP_HANDLERS = {}

def register_step(step_name: str):
    def wrapper(func):
        STEP_HANDLERS[step_name] = func
        return func
    return wrapper

async def _breathe(seconds: float = 0.6):
    await asyncio.sleep(seconds)

NIGERIAN_STATES = {
    "abia", "adamawa", "akwa ibom", "anambra", "bauchi", "bayelsa", "benue",
    "borno", "cross river", "delta", "ebonyi", "edo", "ekiti", "enugu",
    "gombe", "imo", "jigawa", "kaduna", "kano", "katsina", "kebbi",
    "kogi", "kwara", "lagos", "nasarawa", "niger", "ogun", "ondo",
    "osun", "oyo", "plateau", "rivers", "sokoto", "taraba", "yobe",
    "zamfara", "abuja", "fct", "federal capital territory",
}

FIRST_CONTACT = [
    "Oya, a serious student has entered the chat. I'm Wax. Quick one — are you new here, or have we met before? Just type new or returning.",
    "Ah, someone is tired of reading textbooks that feel like they were written in 1972. I see you. I'm Wax. First things first — am I meeting you for the first time, or are you coming back? Just say new or returning.",
    "Welcome o. I'm Wax — your personal exam prep partner. Not a textbook. Not a principal. Just someone who actually gets what you're going through. Real quick — are you new here, or returning?",
    "Finally. Someone serious. I'm Wax. I help Nigerian students crush JAMB, WAEC, and NECO. Not with magic. With smart work. Before we dive in — are you new or returning?",
]

def _react_to_name(name: str) -> str:
    first = name.split()[0]
    reactions = [
        f"{first}. Solid name. Okay {first} — before I start asking you questions like a village auntie, let me tell you what WaxPrep actually is.",
        f"{first}. Clean. I like it. Okay {first} — let me quickly tell you what this thing is about before we dive in.",
        f"{first}. Your parents knew what they were doing. Strong name. Okay {first} — before the serious stuff, let me tell you what WaxPrep actually does.",
    ]
    return random.choice(reactions)

def _get_pitch(name: str) -> str:
    return (
        f"Here's the truth, {name}. You already know how to study. You've been doing it since primary school. "
        f"The problem isn't you. The problem is that studying alone is BORING. And confusing. "
        f"And sometimes you stare at your textbook for 30 minutes and realize you didn't actually understand anything.\n\n"
        f"I'm here to fix that. I'll teach you. Quiz you. Remember what you struggle with. "
        f"Celebrate when you get it right. And unlike your textbook, I'll actually explain things "
        f"in a way that makes sense — with examples from real life. Lagos traffic. Suya. Danfo conductors. You'll see.\n\n"
        f"I'm not a counsellor o. If you're feeling really low, I'll give you real numbers to call. "
        f"But for everything else — JAMB, WAEC, NECO, or just trying to understand Chemistry before "
        f"your teacher humiliates you in class — I'm your guy.\n\n"
        f"Ready?"
    )

def _react_to_subject(subject: str, name: str) -> str:
    subject_lower = subject.lower()
    if "chemistry" in subject_lower:
        return (
            f"Chemistry! {name}, you went straight for the subject with symbols that look like "
            f"someone fell asleep on the keyboard. I respect that. Most people pick Maths because "
            f"it's the 'safe' scary subject. But you? You came for the real challenge.\n\n"
            f"That tells me something about you. You don't run from hard things. You face them. "
            f"Even when they confuse you. That's not a small thing, {name}. That's character.\n\n"
            f"Here's the secret — Chemistry is just cooking. You mix things, heat things, and "
            f"sometimes things explode. We'll start simple. No strange symbols until you're ready."
        )
    elif "physics" in subject_lower:
        return (
            f"Physics! {name}, you picked the subject where everything is moving, falling, or colliding. "
            f"Most people run from Physics. You walked toward it.\n\n"
            f"That says something about you. You're not afraid of things that seem complicated "
            f"from the outside. You know there's sense underneath the confusion.\n\n"
            f"Here's the truth — Physics is just common sense with numbers. Drop a pen. It falls. "
            f"That's physics. We'll build from there. Together."
        )
    elif "math" in subject_lower or "maths" in subject_lower:
        return (
            f"Mathematics! The one subject where 'x' has been hiding for centuries and nobody "
            f"has found it yet. {name}, I love that you chose Maths.\n\n"
            f"Most people avoid it. You faced it. That's not something everyone does.\n\n"
            f"Here's the secret — Maths is just a language. Once you learn to read it, "
            f"everything changes. We'll take it small small. No rushing."
        )
    elif "biology" in subject_lower:
        return (
            f"Biology! {name}, you want to understand living things — including yourself. "
            f"That's deep. Most people memorize Biology. You're here to actually understand it.\n\n"
            f"That's the difference between passing and mastering. You chose mastering.\n\n"
            f"We'll make it come alive. Not textbook definitions. Real things. "
            f"Your own body. The plants outside. The suya you ate last night."
        )
    elif "english" in subject_lower:
        return (
            f"English! {name}, you're smart to focus on this. English is the one subject "
            f"that appears in EVERY exam — JAMB, WAEC, NECO. You can't escape it.\n\n"
            f"But here's what most people don't realize — English isn't about big grammar. "
            f"It's about communication. And you already communicate every day. "
            f"We're just going to sharpen what you already know."
        )
    elif "government" in subject_lower:
        return (
            f"Government! {name}, you want to understand how Nigeria actually works. Respect. "
            f"Fair warning — once you understand the three arms of government, "
            f"you'll never watch the news the same way again.\n\n"
            f"That's not a bad thing. That's what educated citizens do. They understand. "
            f"And you're on your way there."
        )
    elif "economics" in subject_lower:
        return (
            f"Economics! {name}, you want to understand money, markets, and why things cost "
            f"what they cost. That's practical knowledge. Not just for exams — for life.\n\n"
            f"Every time you buy something at the market, you're doing economics. "
            f"We're just going to give you the language to describe what you already know."
        )
    elif "geography" in subject_lower:
        return (
            f"Geography! {name}, you want to understand the world — the land, the weather, "
            f"the people, and how they all connect. That's big-picture thinking.\n\n"
            f"Most people think Geography is just memorizing capitals. It's not. "
            f"It's understanding why Lagos floods, why the north is dry, "
            f"and why some places grow cocoa and others grow groundnuts.\n\n"
            f"We'll make it real. Not textbook maps. Real places you've been to."
        )
    elif "history" in subject_lower:
        return (
            f"History! {name}, you want to understand how we got here. That's deep. "
            f"Most people think History is just dates and dead people. It's not.\n\n"
            f"It's the story of how Nigeria became Nigeria. The empires. The trade routes. "
            f"The people who shaped everything before we were born.\n\n"
            f"Once you start seeing those connections, you'll never look at Nigeria the same way."
        )
    else:
        return (
            f"{subject.title()}! {name}, most students pick the 'easy' subjects. "
            f"You picked {subject.title()}. That's not random. That's a choice.\n\n"
            f"And choices tell me who you are. You know what you need to work on. "
            f"And you're not afraid to face it. Let's tackle it together."
        )

def _get_emotional_checkin(name: str, subject: str) -> str:
    return (
        f"Real talk, {name}. Before we dive into {subject} — how are you actually feeling about it?\n\n"
        f"No need to impress me. I'm not your teacher. I'm not your parent. "
        f"I'm just someone who's been where you are.\n\n"
        f"Just type it anyhow — scared, confused, ready, confident, angry at the textbook... whatever is true."
    )

def _respond_to_emotion(feeling: str, name: str, subject: str) -> str:
    feeling_lower = feeling.lower()
    if any(word in feeling_lower for word in ["scared", "confused", "lost", "don't know", "struggling", "hard"]):
        return (
            f"Thank you for telling me the truth, {name}. Most students just suffer in silence "
            f"and hope for the best. You just did something harder than {subject} — "
            f"you admitted you're struggling.\n\n"
            f"Here's what I know about you now. You're honest. You're brave enough to say "
            f"when something isn't working. And you're still here — still trying — "
            f"even though {subject} has been confusing you.\n\n"
            f"That's not confusion, {name}. That's persistence. "
            f"And persistence beats talent every single time."
        )
    elif any(word in feeling_lower for word in ["ready", "confident", "okay", "fine", "good", "can do"]):
        return (
            f"I like that energy, {name}. You're ready to work. That's half the battle won already.\n\n"
            f"But even when you're confident, everyone hits walls. When that happens — "
            f"and it will happen — just say 'Wax, I'm stuck.' I'll switch it up. "
            f"No judgment. No disappointment. Just a different approach."
        )
    else:
        return (
            f"I hear you, {name}. Whatever you're feeling about {subject} right now — "
            f"it's valid. And it doesn't scare me.\n\n"
            f"We're going to work with where you are. Not where a textbook says you should be. "
            f"Ready to start?"
        )

def _get_pin_prompt(state_name: str) -> str:
    return (
        f"Last step, {state_name}. Create a secret code — at least 4 characters. "
        f"Letters, numbers, or mix them up. Something easy for YOU to remember, "
        f"but hard for your younger sibling to guess.\n\n"
        f"Don't use 1234 or password o — I'll know. And I'll be disappointed. "
        f"Not angry. Just... disappointed."
    )

def _get_weak_pin_response(name: str) -> str:
    return (
        f"{name}. My friend. My brother. You chose the secret code equivalent of leaving your door "
        f"wide open with a sign that says 'come in.' Pick another one. I believe in you."
    )

def _get_pin_retry(failed_attempts: int) -> str:
    if failed_attempts < 3:
        return "At least 4 characters. Letters, numbers, or both — your choice. Try again."
    elif failed_attempts < 5:
        return "4 characters minimum. Pick something you'll remember — like a nickname or a favorite number with letters mixed in."
    else:
        return "I know this is frustrating. Pick any 4+ characters that are easy for YOU to remember. Letters or numbers — anything works."

def _get_activation(name: str, subject: str, state_name: str, exam: str, class_level: str) -> str:
    if exam and exam != "not_applicable":
        exam_line = f"I know you're preparing for {exam}. And I know you've been struggling alone.\n\n"
    else:
        exam_line = f"And I know you've been working hard on your own.\n\n"
    
    return (
        f"{name}. You're in! 🎉\n\n"
        f"Your WAX ID: {{wax_id}}\n"
        f"Your Recovery Code: {{recovery_code}}\n\n"
        f"Write that code somewhere safe. Notebook. Phone. WhatsApp it to yourself. "
        f"Don't lose it. If you ever can't access your account, that code is your key back.\n\n"
        f"Now. Let me tell you what happens next.\n\n"
        f"I know {subject} has been confusing you. "
        f"{exam_line}"
        f"That ends today.\n\n"
        f"I'm going to teach you {subject} differently. No strange symbols until you're ready. "
        f"No assuming you already know things. Just us — one topic at a time — until it CLICKS.\n\n"
        f"And {name}? If you ever feel lost, just say 'Wax, I'm lost.' I'll slow down. "
        f"I'll explain again. I'll find another way. I won't give up on you.\n\n"
        f"What do you want to study first?"
    )


# ═══════════════════════════════════════════════
# DISPATCHER
# ═══════════════════════════════════════════════

async def handle_onboarding(chat_id: int, state: dict, message: str):
    step = state.get("awaiting_response_for", "new_or_existing")
    handler = STEP_HANDLERS.get(step)
    if handler:
        await handler(chat_id, state, message)
    else:
        await _start_new_or_existing(chat_id, state, message)


@register_step("new_or_existing")
async def _start_new_or_existing(chat_id: int, state: dict, message: str):
    msg = message.strip().lower()
    if any(k in msg for k in ["2", "existing", "login", "log in", "returning", "back", "have", "wax"]):
        state["awaiting_response_for"] = "wax_id_entry"
        state["is_new_student"] = False
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            "Welcome back o. Send me your WAX ID — it looks like WAX-A74892. "
            "If you've forgotten it, just type forgot and we'll sort it out."
        )
        return
    if any(k in msg for k in ["1", "new", "i'm new", "create", "register", "signup", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            "My person! New student. I love this. Okay — first, I need to know your name. "
            "Your real name o, not 'Baby Girl' or 'Boss Man.' What do people call you at home?"
        )
        return
    await send_telegram_message(chat_id, random.choice(FIRST_CONTACT))


@register_step("wax_id_entry")
async def _step_wax_id_entry(chat_id: int, state: dict, message: str):
    msg = message.strip().lower()
    if any(k in msg for k in ["new", "create", "register", "i'm new", "signup", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            "Ah, starting fresh? No wahala. First — what do people call you at home?"
        )
        return
    if "forgot" in msg:
        await send_telegram_message(chat_id,
            "No wahala. Even me, I forget things. What name did you use when you signed up? "
            "I'll try to find your account."
        )
        return
    wax_id = message.strip().upper()
    if wax_id.startswith("WAX-") and len(wax_id) == 10:
        state["pending_wax_id"] = wax_id
        state["awaiting_response_for"] = "pin_entry"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            f"Got you. Now enter your secret code. And don't worry — if you've forgotten it, "
            f"just type forgot. No judgment here."
        )
        return
    await send_telegram_message(chat_id,
        "That doesn't look like a WAX ID. It should be something like WAX-A74892. "
        "Check and try again, or type new to start fresh."
    )


@register_step("pin_entry")
async def _step_pin_entry(chat_id: int, state: dict, message: str):
    msg = message.strip().lower()
    if any(k in msg for k in ["new", "create", "register", "fresh"]):
        state["is_new_student"] = True
        state["awaiting_response_for"] = "name"
        state["pending_wax_id"] = None
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            "Starting fresh? I respect that. First — what do people call you at home?"
        )
        return
    await send_telegram_message(chat_id,
        "PIN login is coming soon. For now, you can create a fresh account to start "
        "studying immediately. Just type new to get started."
    )


# ═══════════════════════════════════════════════
# STEP: name
# ═══════════════════════════════════════════════

@register_step("name")
async def _step_name(chat_id: int, state: dict, message: str):
    name = clean_name(message)

    if len(name) < 2:
        await send_telegram_message(chat_id,
            "Give me a name — something I can call you. Doesn't have to be your full name."
        )
        return

    parts = name.split()
    first = parts[0]
    if len(parts) >= 2:
        last = parts[-1]
        display_name = f"{first} {last}"
    else:
        display_name = first

    state["name"] = display_name
    state["awaiting_response_for"] = "class_level"
    await save_onboarding_state("telegram", str(chat_id), state)

    await send_telegram_message(chat_id, _react_to_name(display_name))
    await _breathe(0.8)
    await send_telegram_message(chat_id, _get_pitch(first))
    await send_telegram_message(chat_id,
        "So what class are you in? Just type SS1, SS2, or SS3."
    )


@register_step("class_level")
async def _step_class_level(chat_id: int, state: dict, message: str):
    msg = message.strip().upper()
    class_map = {"1": "SS1", "2": "SS2", "3": "SS3", "SS1": "SS1", "SS2": "SS2", "SS3": "SS3"}
    class_level = class_map.get(msg)
    if not class_level:
        await send_telegram_message(chat_id,
            "Just type SS1, SS2, or SS3. I need to know so I don't give SS1 student JAMB panic attacks."
        )
        return
    first = state.get("name", "Student").split()[0]
    state["class_level"] = class_level
    state["awaiting_response_for"] = "subject_selection"
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id,
        f"{class_level}. Got it.\n\n"
        f"Okay {first} — what subject makes you want to close your textbook and go watch TV? "
        f"Be honest. No judgment here. I once wanted to burn my Chemistry textbook. True story."
    )


@register_step("subject_selection")
async def _step_subject_selection(chat_id: int, state: dict, message: str):
    raw_subject = message.strip()
    first = state.get("name", "Student").split()[0]
    level = state.get("class_level", "SS3")
    dont_know = ["i don't know", "i dont know", "all of them", "everything", "not sure", "idk", "none", "all"]
    if raw_subject.lower() in dont_know:
        await send_telegram_message(chat_id,
            f"Ha! 'All of them' — I felt that in my spirit. Okay, let's start with Mathematics. "
            f"It's the foundation for most things, and honestly, once Maths starts making sense, "
            f"a lot of other things fall into place. That work for you?"
        )
        normalized = "Mathematics"
    else:
        normalized = normalize_subject(raw_subject)
    state["student_subject"] = normalized
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id, _react_to_subject(normalized, first))
    await _breathe(0.8)
    state["awaiting_response_for"] = "emotional_checkin"
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id, _get_emotional_checkin(first, normalized))


@register_step("emotional_checkin")
async def _step_emotional_checkin(chat_id: int, state: dict, message: str):
    first = state.get("name", "Student").split()[0]
    subject = state.get("student_subject", "your subject")
    class_level = state.get("class_level", "SS3")
    state["student_feeling"] = message.strip()
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id, _respond_to_emotion(message, first, subject))
    await _breathe(0.6)
    if class_level == "SS3":
        state["awaiting_response_for"] = "target_exam"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            f"Okay {first} — which exam are you preparing for? JAMB, WAEC, or NECO? Just type it."
        )
    else:
        state["target_exam"] = "not_applicable"
        state["awaiting_response_for"] = "state"
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id,
            f"Quick one, {first} — which state are you based in? This helps me give you examples "
            f"that actually make sense. If you're in Lagos, I'll talk about danfos. "
            f"If you're in Kano, I'll switch it up. Just type your state."
        )


@register_step("target_exam")
async def _step_target_exam(chat_id: int, state: dict, message: str):
    msg = message.strip().upper()
    exam_map = {"1": "JAMB", "2": "WAEC", "3": "NECO", "JAMB": "JAMB", "WAEC": "WAEC", "NECO": "NECO"}
    target_exam = exam_map.get(msg)
    if not target_exam:
        await send_telegram_message(chat_id, "Just type JAMB, WAEC, or NECO. Which one is coming for you?")
        return
    first = state.get("name", "Student").split()[0]
    state["target_exam"] = target_exam
    state["awaiting_response_for"] = "state"
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id,
        f"{target_exam}. Okay, we're preparing for war. "
        f"Quick one, {first} — which state are you based in? Lagos? Kano? Rivers? Just type it."
    )


@register_step("state")
async def _step_state(chat_id: int, state: dict, message: str):
    raw = message.strip()
    student_state = raw.title()
    if len(raw) <= 3 and raw.lower() not in NIGERIAN_STATES:
        await send_telegram_message(chat_id, "Type the full name — like Kano or Lagos. Which state are you in?")
        return
    state["student_state"] = student_state
    state["pin_failed_attempts"] = 0
    state["awaiting_response_for"] = "pin_setup"
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id, _get_pin_prompt(student_state))


@register_step("pin_setup")
async def _step_pin_setup(chat_id: int, state: dict, message: str):
    pin = message.strip()
    name = state.get("name", "Student").split()[0]
    if len(pin) < 4:
        failed = state.get("pin_failed_attempts", 0) + 1
        state["pin_failed_attempts"] = failed
        await save_onboarding_state("telegram", str(chat_id), state)
        await send_telegram_message(chat_id, _get_pin_retry(failed))
        return
    weak_pins = {
        "1234", "0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
        "abcd", "password", "qwerty", "waxp", "abcd1234", "pass", "admin", "letmein",
        "12345", "abc123", "qwerty123", "login", "welcome", "monkey", "dragon",
    }
    if pin.lower() in weak_pins:
        await send_telegram_message(chat_id, _get_weak_pin_response(name))
        return
    state["pending_pin"] = pin
    state["awaiting_response_for"] = "pin_confirm"
    await save_onboarding_state("telegram", str(chat_id), state)
    await send_telegram_message(chat_id, "Got it! Confirm your secret code — type it again.")


@register_step("pin_confirm")
async def _step_pin_confirm(chat_id: int, state: dict, message: str):
    pin_confirm = message.strip()
    pending_pin = state.get("pending_pin", "")
    if pin_confirm != pending_pin:
        await send_telegram_message(chat_id, "Those codes don't match. Try again — enter your secret code:")
        state["pending_pin"] = None
        state["awaiting_response_for"] = "pin_setup"
        await save_onboarding_state("telegram", str(chat_id), state)
        return

    student_subject = state.get("student_subject", "Mathematics")
    subjects = ["english", "mathematics"]
    if student_subject.lower() not in subjects:
        subjects.append(student_subject.lower())
    if student_subject.lower() in ("physics", "chemistry", "biology"):
        for s in ("physics", "chemistry", "biology"):
            if s not in subjects:
                subjects.append(s)

    student = await create_student(
        platform="telegram",
        platform_user_id=str(chat_id),
        name=state.get("name", "Student"),
        pin=pending_pin,
        class_level=state.get("class_level"),
        target_exam=state.get("target_exam"),
        subjects=subjects,
        student_subject=state.get("student_subject"),
        student_state=state.get("student_state"),
    )
    if not student:
        await send_telegram_message(chat_id, "Something went wrong creating your account. Try again — just send HI to restart.")
        return

    await clear_onboarding_state("telegram", str(chat_id))
    name = state.get("name", "Student")
    first = name.split()[0]
    subject = state.get("student_subject", "your subject")
    student_state_name = state.get("student_state", "your state")
    exam = state.get("target_exam", "your exam")
    class_level = state.get("class_level", "SS3")

    activation = _get_activation(first, subject, student_state_name, exam, class_level)
    activation = activation.format(wax_id=student["wax_id"], recovery_code=student["recovery_code"])
    await send_telegram_message(chat_id, activation)
