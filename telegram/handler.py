"""
WaxPrep v2 — Telegram Message Handler
Processes incoming Telegram messages. Routes new students to a warm AI conversation,
registered users to the AI brain. Handles quiz commands and answers.
Supports callback queries (inline keyboard) AND text-based answers.

Now with Observation Extraction — Wax learns from every conversation.
Observations extracted progressively (every 5 messages) and at session end.
Content-addressable deduplication prevents duplicates.

Now with Account Creation Trigger — Wax offers account creation at the right moment:
trust demonstrated + value received + loss is visible.
"""
import asyncio
import hashlib
import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from telegram.sender import send_telegram_message, build_quiz_keyboard, answer_callback_query
from database.client import redis_client

logger = logging.getLogger("waxprep.handler")

# ── Quiz trigger keywords ────────────────────
QUIZ_TRIGGERS = ["quiz", "quiz me", "test me"]

# ── Deferral keywords ─────────────────────────
DEFERRAL_KEYWORDS = [
    "anything", "you pick", "any one", "whatever",
    "up to you", "choose for me", "i don't know what to study",
    "i don't care", "surprise me",
    "let's change topic", "change topic", "let's move on",
    "next topic", "something else", "new topic",
    "i'm tired of this", "this one is boring",
    "let's do something else", "switch topic",
    "suggest something", "suggest a topic",
]

# ── Preference keywords ───────────────────────
PREFERENCE_KEYWORDS = [
    "i prefer", "i don't like", "i dont like", "i like",
    "use something from", "don't use", "dont use",
    "stop using", "no more", "i changed my mind",
    "instead of", "rather than", "not that",
]

# ── Session end keywords ─────────────────────
SESSION_END_KEYWORDS = [
    "i'm tired", "i am tired", "i'm done", "i am done",
    "good night", "goodnight", "i need a break", "taking a break",
    "i'll be back", "i will be back", "bye", "goodbye",
    "see you later", "see you tomorrow", "i'm going to sleep",
    "i'm leaving", "i have to go", "gotta go", "gtg",
    "i don tire", "i don tire o", "my brain don full",
    "make i rest small", "make i rest", "i wan sleep",
    "i dey go", "e don do", "e don do me",
    "i dey come", "make i chop", "make i eat",
    "i go come back", "i dey go sleep",
]

# ── Nigerian time phrases ──
NIGERIAN_TIME_PHRASES = [
    "i'm coming", "i dey come", "make i chop", "make i eat",
    "i wan eat", "let me eat first", "i dey go bathroom",
    "one minute", "small time", "i dey come back",
    "no dey far",
]

# ── Subject name mapping ──────────────────────
SUBJECT_MAP: Dict[str, str] = {
    "mathematics": "mathematics", "maths": "mathematics", "math": "mathematics",
    "english": "english", "english_language": "english",
    "civic_education": "civic_education", "civic": "civic_education",
    "computer_studies": "computer_studies", "computer": "computer_studies", "ict": "computer_studies",
    "data_processing": "data_processing", "data": "data_processing",
    "physics": "physics", "chemistry": "chemistry", "biology": "biology",
    "further_mathematics": "further_mathematics", "further mathematics": "further_mathematics",
    "agricultural_science": "agricultural_science", "agric": "agricultural_science",
    "health_education": "health_education", "health": "health_education",
    "physical_education": "physical_education", "physical": "physical_education", "phe": "physical_education",
    "technical_drawing": "technical_drawing", "technical drawing": "technical_drawing",
    "food_and_nutrition": "food_and_nutrition", "food & nutrition": "food_and_nutrition",
    "economics": "economics", "econs": "economics",
    "commerce": "commerce",
    "accounting": "accounting", "accounts": "accounting", "financial_accounting": "accounting",
    "business_studies": "business_studies", "business studies": "business_studies",
    "marketing": "marketing",
    "book_keeping": "book_keeping", "book keeping": "book_keeping",
    "office_practice": "office_practice", "office practice": "office_practice",
    "insurance": "insurance",
    "government": "government", "govt": "government",
    "literature": "literature_in_english",
    "literature_in_english": "literature_in_english",
    "literature-in-english": "literature_in_english",
    "history": "history",
    "christian_religious_studies": "crs", "crs": "crs",
    "islamic_religious_studies": "irs", "irs": "irs", "islamic": "irs",
    "geography": "geography", "geo": "geography",
    "visual_arts": "visual_arts", "visual arts": "visual_arts", "art": "visual_arts", "fine_art": "visual_arts",
    "music": "music",
    "french": "french",
    "arabic": "arabic",
    "yoruba": "yoruba", "igbo": "igbo", "hausa": "hausa",
    "fashion_design": "fashion_design", "fashion design": "fashion_design", "garment_making": "fashion_design",
    "gsm_repairs": "gsm_repairs", "gsm repairs": "gsm_repairs", "computer_hardware": "gsm_repairs",
    "solar_installation": "solar_installation", "solar installation": "solar_installation", "solar": "solar_installation",
    "livestock_farming": "livestock_farming", "livestock farming": "livestock_farming",
    "beauty_cosmetology": "beauty_cosmetology", "beauty": "beauty_cosmetology", "cosmetology": "beauty_cosmetology",
    "horticulture": "horticulture", "crop_production": "horticulture",
}

# ── Fallback subject pools by track ───────────
TRACK_FALLBACKS: Dict[str, List[str]] = {
    "science": [
        "english", "mathematics", "physics", "chemistry", "biology",
        "further_mathematics", "agricultural_science", "health_education",
        "physical_education", "technical_drawing", "food_and_nutrition",
        "computer_studies", "data_processing",
    ],
    "commercial": [
        "english", "mathematics", "economics", "commerce", "accounting",
        "business_studies", "marketing", "book_keeping", "office_practice",
        "insurance", "data_processing", "computer_studies",
    ],
    "arts": [
        "english", "mathematics", "government", "literature_in_english",
        "civic_education", "history", "christian_religious_studies",
        "islamic_religious_studies", "geography", "visual_arts", "music",
        "french", "arabic", "yoruba", "igbo", "hausa",
    ],
    "trade": [
        "english", "mathematics", "fashion_design", "gsm_repairs",
        "solar_installation", "livestock_farming", "beauty_cosmetology",
        "horticulture", "computer_studies",
    ],
    "unknown": ["english", "mathematics", "civic_education"],
}

# TTLs and limits
QUIZ_TTL_SECONDS = 1800
MAX_QUIZ_HISTORY = 200
JAMB_CHECK_COOLDOWN = 604800
DEFERRAL_TTL = 3600
SESSION_GAP_MINUTES = 60
PROGRESSIVE_EXTRACTION_INTERVAL = 5
ACCOUNT_OFFER_COOLDOWN = 86400

# Understanding confirmation phrases (English + Pidgin)
UNDERSTANDING_PHRASES = [
    "you've got it", "exactly", "you worked that out",
    "you're right", "well done", "correct", "perfect",
    "that's it", "you got it", "you understand",
    "now you're getting it", "you're on a roll",
    "you don sabi am", "na so e be", "you get am",
    "e don enter", "correct guy", "correct girl",
    "you dey try", "na im be that",
]

# Wake phrases that should NEVER appear for temp students
WAKE_PHRASES = [
    "welcome back", "you're back", "you returned", "welcome back,",
    "STUDENT IS RETURNING", "INFORMED GREETING", "CELEBRATE:",
]

# Phrases that indicate a student wants continuity
CONTINUITY_PHRASES = [
    "will you remember", "can we continue", "come back",
    "tomorrow", "next time", "save this", "keep this",
    "don't forget", "remember me", "will this be here",
    "will you be here", "can i come back",
]


async def process_telegram_message(chat_id: int, text: str) -> None:
    """Entry point for all Telegram text messages."""
    text = text.strip()[:4000]
    if not text:
        return

    logger.debug(f"Processing message from chat_id={chat_id}: {text[:100]}...")

    try:
        from brain.safety import run_safety_checks
        if await run_safety_checks(chat_id, text):
            return
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Safety check error: {e}", exc_info=True)
        return

    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception as e:
        logger.error(f"Student lookup failed: {e}", exc_info=True)
        await send_telegram_message(chat_id, "I'm having trouble connecting. Please try again in a moment.")
        return

    if student:
        await _handle_registered_student(chat_id, student, text)
        return

    # ═══════════════════════════════════════════════
    # UNREGISTERED USER — temp student flow
    # ═══════════════════════════════════════════════
    temp_id = f"temp_{chat_id}"
    new_student = {
        "id": temp_id,
        "name": "Student",
        "class_level": "unknown",
        "subjects": [],
        "state": "Nigeria",
        "language_preference": "english",
        "current_streak": 0,
    }

    # Load any existing history and recover name so the AI doesn't forget
    try:
        from database.conversations import get_history
        conversation_history = await get_history(temp_id)
    except Exception:
        conversation_history = []

    if conversation_history:
        recovered_name = _extract_name_from_history(conversation_history)
        if recovered_name:
            new_student["name"] = recovered_name
            logger.info(f"Recovered name for {temp_id}: {recovered_name}")

        # Route through the full handler stack so temp students get session-end
        # detection, deferrals, quizzes, account offers, and observation extraction
        await _handle_registered_student(chat_id, new_student, text)
        return

    # ── First conversation for this temp student ──
    try:
        from ai.brain import think
        from database.conversations import save_message

        await save_message(temp_id, "user", text)

        try:
            conversation_history = await get_history(temp_id)
        except Exception:
            conversation_history = []

        context_str = (
            "This is a new student. You don't know anything about them yet. "
            "Introduce yourself warmly. Ask their name naturally when it feels right. "
            "Don't interrogate. Just welcome them and let the conversation flow. "
            "NEVER say 'Welcome back' to a new student. This is their first conversation."
        )

        response = await think(
            message=text,
            student=new_student,
            conversation_history=conversation_history,
            recent_subject=None,
            context_str=context_str,
            is_practice=False,
        )

        response = _sanitize_wake_phrases(response, is_temp=True)

        try:
            await save_message(temp_id, "assistant", response)
        except Exception:
            pass

        await send_telegram_message(chat_id, response)

        # Name extraction — current message first, then scan recent history
        extracted_name = _extract_name_from_message(text)
        if not extracted_name and conversation_history:
            extracted_name = _extract_name_from_history(conversation_history[-5:])

        if extracted_name:
            new_student["name"] = extracted_name
            try:
                await save_message(
                    temp_id,
                    "system",
                    f"Student introduced themselves as {extracted_name}."
                )
            except Exception:
                pass

        try:
            timestamp_key = f"last_message_time:{temp_id}"
            redis_client.setex(timestamp_key, 86400, datetime.now(timezone.utc).isoformat())
        except Exception:
            pass

    except Exception as e:
        logger.error(f"New student handler failed: {e}", exc_info=True)
        await send_telegram_message(chat_id, "Hey. I'm Wax. What's your name?")


def _extract_name_from_message(text: str) -> Optional[str]:
    """Try to extract a name from a student's message."""
    msg = text.strip()
    patterns = [
        r"(?:my\s+name\s+is|call\s+me|i'?m|am|you\s+can\s+call\s+me)\s+([A-Za-z]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            name = match.group(1)
            if name.lower() not in ("not", "good", "fine", "ok", "okay", "sure", "new", "student", "done", "tired"):
                return name[0].upper() + name[1:].lower() if len(name) > 1 else name.upper()
    return None


def _extract_name_from_history(conversation_history: List[Dict]) -> Optional[str]:
    """Scan conversation history for student name introductions."""
    if not conversation_history:
        return None
    for msg in reversed(conversation_history):
        if msg.get("role") == "user":
            name = _extract_name_from_message(msg.get("content", ""))
            if name:
                return name
        elif msg.get("role") == "system":
            content = msg.get("content", "")
            match = re.search(r"Student introduced themselves as ([A-Za-z]+)", content)
            if match:
                return match.group(1)
    return None


def _sanitize_wake_phrases(text: str, is_temp: bool = False) -> str:
    """Remove wake/session-reset phrases from AI responses."""
    if not is_temp:
        return text
    sanitized = text
    for phrase in WAKE_PHRASES:
        sanitized = re.sub(re.escape(phrase), "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'\s+', ' ', sanitized)
    sanitized = re.sub(r'\n\s*\n', '\n\n', sanitized)
    return sanitized.strip()


# ═══════════════════════════════════════════════
# ACCOUNT CREATION TRIGGER
# ═══════════════════════════════════════════════

def should_offer_account_creation(
    conversation_history: List[Dict],
    student_id: str,
    current_state: str
) -> bool:
    """
    Determine if this is the right moment to offer account creation.
    
    Three conditions must ALL be true:
    1. Trust demonstrated: 5+ substantive exchanges
    2. Value received: At least one confirmed learning moment
    3. Loss is visible: Continuity concern OR natural session end
    """
    if not student_id.startswith("temp_"):
        return False
    
    cooldown_key = f"account_offer_cooldown:{student_id}"
    try:
        if redis_client.exists(cooldown_key):
            return False
    except Exception:
        pass
    
    in_progress_key = f"account_creation_in_progress:{student_id}"
    try:
        if redis_client.exists(in_progress_key):
            return False
    except Exception:
        pass
    
    if not conversation_history:
        return False
    
    user_messages = [m for m in conversation_history if m.get("role") == "user"]
    substantive = [
        m for m in user_messages
        if len(m.get("content", "").split()) > 2
        and m.get("content", "").lower().strip() not in (
            "ok", "okay", "yes", "yeah", "no", "yep", "k", "oh", "hmm",
            "nothing", "good", "fine", "sure", "cool", "alright",
        )
    ]
    if len(substantive) < 5:
        return False
    
    assistant_messages = [m for m in conversation_history if m.get("role") == "assistant"]
    had_breakthrough = False
    
    for i, msg in enumerate(assistant_messages):
        content = msg.get("content", "").lower()
        if any(phrase in content for phrase in [
            "you've got it", "exactly", "you worked that out",
            "you're right", "well done", "correct", "you get",
            "you understand", "now you're getting", "perfect",
            "that's it",
        ]):
            try:
                msg_index = conversation_history.index(msg)
                if msg_index >= 0 and msg_index + 1 < len(conversation_history):
                    next_msg = conversation_history[msg_index + 1]
                    if next_msg.get("role") == "user":
                        next_content = next_msg.get("content", "").lower()
                        if not any(word in next_content for word in [
                            "whatever", "i guess", "if you say", "i don't",
                            "not really", "not sure", "maybe",
                        ]):
                            had_breakthrough = True
                            break
            except (ValueError, IndexError):
                pass
    
    if not had_breakthrough:
        return False
    
    last_few_user = [m.get("content", "").lower() for m in user_messages[-5:]]
    has_continuity_concern = any(
        phrase in msg
        for msg in last_few_user
        for phrase in CONTINUITY_PHRASES
    )
    
    is_session_ending = (
        current_state == "ended"
        or any(
            phrase in (user_messages[-1].get("content", "").lower() if user_messages else "")
            for phrase in SESSION_END_KEYWORDS
        )
    )
    
    if not (has_continuity_concern or is_session_ending):
        return False
    
    return True


async def _maybe_offer_account_creation(
    chat_id: int,
    student: Dict[str, Any],
    student_id: str,
    conversation_history: List[Dict],
    current_state: str
) -> bool:
    """Check if we should offer account creation and send the offer if so."""
    logger.info(f"ACCOUNT OFFER CHECK: student_id={student_id}, temp={student_id.startswith('temp_')}")
    
    if not should_offer_account_creation(conversation_history, student_id, current_state):
        return False
    
    try:
        redis_client.setex(f"account_offer_cooldown:{student_id}", ACCOUNT_OFFER_COOLDOWN, "1")
    except Exception:
        pass
    
    name = student.get("name", "Student").split()[0]
    if name == "Student":
        for msg in reversed(conversation_history):
            if msg.get("role") == "user":
                extracted = _extract_name_from_message(msg.get("content", ""))
                if extracted:
                    name = extracted
                    break
    
    if current_state == "ended" or any(
        phrase in conversation_history[-1].get("content", "").lower()
        for phrase in SESSION_END_KEYWORDS
    ):
        offer_message = (
            f"{name}, before you go — everything we did today? "
            f"Once you close this chat, it's gone. I won't remember any of it tomorrow.\n\n"
            f"If you want me to remember you next time, just say *yes*. "
            f"Takes 10 seconds."
        )
    else:
        offer_message = (
            f"{name}, you asked if I'll remember everything. "
            f"Truth is, without an account, I start fresh every time you open this chat.\n\n"
            f"If you want me to remember you — your name, your subjects, your progress — "
            f"just say *yes*. Takes 10 seconds."
        )
    
    await send_telegram_message(chat_id, offer_message)
    
    try:
        redis_client.setex(f"account_creation_offered:{student_id}", 3600, "1")
    except Exception:
        pass
    
    return True


# ═══════════════════════════════════════════════
# ACCOUNT CREATION HANDLER
# ═══════════════════════════════════════════════

async def _handle_account_creation_response(
    chat_id: int,
    student_id: str,
    text: str,
    conversation_history: List[Dict]
) -> bool:
    """Handle a student's response to the account creation offer."""
    msg_lower = text.strip().lower()
    
    positive_responses = [
        "yes", "yeah", "yep", "sure", "ok", "okay", "yes o",
        "create", "create it", "let's do it", "do it", "go ahead",
        "how", "what do i do", "tell me", "show me",
    ]
    
    if any(msg_lower == resp or msg_lower.startswith(resp) for resp in positive_responses):
        try:
            redis_client.setex(f"account_creation_in_progress:{student_id}", 600, "1")
        except Exception:
            pass
        
        try:
            redis_client.delete(f"account_creation_offered:{student_id}")
        except Exception:
            pass
        
        await send_telegram_message(
            chat_id,
            "Pick a code. At least 4 characters. Something you'll remember."
        )
        return True
    
    negative_responses = [
        "no", "nope", "nah", "not now", "later", "maybe later",
        "no thanks", "i'm good", "no o",
    ]
    
    if any(msg_lower == resp or msg_lower.startswith(resp) for resp in negative_responses):
        try:
            redis_client.delete(f"account_creation_offered:{student_id}")
        except Exception:
            pass
        
        await send_telegram_message(
            chat_id,
            "No wahala. We'll keep studying — I'm not going anywhere. "
            "When you're ready, just say *create account*."
        )
        return True
    
    return False


async def _handle_pin_submission(
    chat_id: int,
    student_id: str,
    text: str,
    conversation_history: List[Dict]
) -> bool:
    """Handle a student's PIN submission during account creation."""
    in_progress_key = f"account_creation_in_progress:{student_id}"
    try:
        if not redis_client.exists(in_progress_key):
            return False
    except Exception:
        return False
    
    pin = text.strip()
    
    if len(pin) < 4:
        await send_telegram_message(
            chat_id,
            "At least 4 characters. Try again."
        )
        return True
    
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    try:
        from database.students import create_student
        
        student = await create_student(
            platform="telegram",
            platform_user_id=str(chat_id).split("_")[-1] if "_" in str(chat_id) else str(chat_id),
            name=_extract_name_from_history(conversation_history) or "Student",
            pin=pin,
            class_level="unknown",
            target_exam="unknown",
            subjects=[],
            student_subject="",
            student_state="Nigeria",
        )
        
        if not student:
            await _handle_account_creation_failure(chat_id, student_id)
            return True
        
        permanent_id = student.get("id")
        if not permanent_id:
            await _handle_account_creation_failure(chat_id, student_id)
            return True
        
        from database.migrations import migrate_temp_to_permanent
        migration_results = await migrate_temp_to_permanent(student_id, permanent_id)
        
        if not migration_results.get("conversation_history"):
            logger.critical(
                f"Conversation migration failed for {student_id} → {permanent_id}"
            )
            await _handle_account_creation_failure(chat_id, student_id)
            return True
        
        try:
            redis_client.delete(f"account_creation_in_progress:{student_id}")
            redis_client.delete(f"account_creation_offered:{student_id}")
            redis_client.delete(f"account_offer_cooldown:{student_id}")
        except Exception:
            pass
        
        name = student.get("name", "Student")
        raw_name = name.strip()
        display_name = raw_name.split()[0] if raw_name else "Student"

        await send_telegram_message(
            chat_id,
            f"You're in, {display_name}. 🎉\n\n"
            f"Your WAX ID: *{student['wax_id']}*\n\n"
            f"Everything we talked about today? It's all here. I remember all of it."
        )

        await asyncio.sleep(2)

        await send_telegram_message(
            chat_id,
            f"One more thing — write this down. On paper. Not in this chat.\n\n"
            f"Recovery Code: *{student['recovery_code']}*\n\n"
            f"If you lose it, I can't get it back for you. That's the only copy."
        )

        logger.info(f"Account created: {student_id} → {permanent_id} ({display_name})")
        return True
        
    except Exception as e:
        logger.error(f"Account creation failed for {student_id}: {e}")
        await _handle_account_creation_failure(chat_id, student_id)
        return True


async def _handle_account_creation_failure(chat_id: int, student_id: str) -> None:
    """Handle a failed account creation gracefully."""
    
    logger.error(f"Account creation failed for {student_id}")
    
    try:
        redis_client.delete(f"account_creation_in_progress:{student_id}")
    except Exception:
        pass
    
    await send_telegram_message(
        chat_id,
        "Ah, my fault. The account didn't create — something glitched on my end.\n\n"
        "But here's the good part: everything we talked about today? Still here. "
        "Still saved. We can try again now, or we can keep studying and fix it later.\n\n"
        "Your call. Try again or keep going?"
    )


async def _handle_registered_student(chat_id: int, student: Dict[str, Any], text: str) -> None:
    """Route a registered student's message to the appropriate handler."""
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]
    msg_lower = text.strip().lower()

    if any(phrase in msg_lower for phrase in SESSION_END_KEYWORDS):
        await _handle_session_end(chat_id, student, text, student_id, name, msg_lower)
        return

    if any(phrase in msg_lower for phrase in NIGERIAN_TIME_PHRASES):
        await _handle_stepping_away(chat_id, student_id, name)
        return

    is_preference = any(phrase in msg_lower for phrase in PREFERENCE_KEYWORDS)
    is_deferral = any(phrase in msg_lower for phrase in DEFERRAL_KEYWORDS)
    
    if is_deferral and not is_preference:
        await _handle_deferral(chat_id, student, student_id, name, msg_lower)
        return

    cleaned = text.strip().upper()
    if cleaned in ("A", "B", "C", "D") and len(cleaned) == 1:
        quiz_key = f"active_quiz:{student_id}"
        try:
            if redis_client.exists(quiz_key):
                await _handle_quiz_answer(chat_id, student, cleaned)
                return
        except Exception:
            pass

    if any(trigger in msg_lower for trigger in QUIZ_TRIGGERS):
        await _start_quiz(chat_id, student, text)
        return

    await _handle_ai_conversation(chat_id, student, text, student_id, name)


# ═══════════════════════════════════════════════
# STEPPING AWAY HANDLER
# ═══════════════════════════════════════════════

async def _handle_stepping_away(chat_id: int, student_id: str, name: str) -> None:
    """Handle Nigerian time expressions."""
    key = f"stepped_away:{student_id}"
    try:
        redis_client.setex(key, 3600, "1")
    except Exception:
        pass
    try:
        timestamp_key = f"last_message_time:{student_id}"
        redis_client.setex(timestamp_key, 86400, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass
    await send_telegram_message(chat_id, "No wahala. I dey here.")


# ═══════════════════════════════════════════════
# SESSION END HANDLER
# ═══════════════════════════════════════════════

async def _handle_session_end(
    chat_id: int, student: dict, text: str,
    student_id: str, name: str, msg_lower: str
) -> None:
    """Handle natural session endings with observation extraction."""
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message, save_session_summary

    try:
        conversation_history = await get_history(student_id)
    except Exception:
        conversation_history = []

    recent_subject = _infer_recent_subject(student, conversation_history)
    session_topic = _extract_topic_from_history(conversation_history)

    try:
        await save_message(student_id, "user", text)
    except Exception:
        pass

    try:
        context_str = await _build_memory_context(student_id)
    except Exception:
        context_str = ""

    try:
        response = await think(
            message=text, student=student,
            conversation_history=conversation_history,
            recent_subject=recent_subject, context_str=context_str,
            is_practice=False
        )
    except Exception:
        response = f"No wahala, {name}. Take a break. We'll continue {recent_subject or 'studying'} when you're ready."

    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass

    await send_telegram_message(chat_id, response)

    # Natural pause before account offer so goodbye and offer are separate messages
    await asyncio.sleep(1.5)

    session_completed = False
    session_score = None
    session_struggles = []

    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "").lower()
            if any(phrase in content for phrase in UNDERSTANDING_PHRASES):
                session_completed = True
                correct_count = sum(
                    1 for m in conversation_history[-20:]
                    if m.get("role") == "assistant" and
                    any(p in m.get("content", "").lower() for p in UNDERSTANDING_PHRASES)
                )
                wrong_count = sum(
                    1 for m in conversation_history[-20:]
                    if m.get("role") == "assistant" and
                    any(p in m.get("content", "").lower() for p in [
                        "not quite", "not exactly", "close", "almost", "that's not",
                    ])
                )
                total = correct_count + wrong_count
                if total > 0:
                    session_score = correct_count / total
                break

    struggle_keywords = ["confused", "don't understand", "struggling", "hard", "difficult"]
    for msg in conversation_history[-10:]:
        if msg.get("role") == "user":
            content = msg.get("content", "").lower()
            for kw in struggle_keywords:
                if kw in content:
                    idx = content.find(kw)
                    before = content[max(0, idx-15):idx]
                    negated = any(neg in before for neg in [
                        "not ", "isn't ", "wasn't ", "no longer ", "not as ", "don't ",
                    ])
                    if not negated and session_topic and session_topic not in session_struggles:
                        session_struggles.append(session_topic)
                    break

    session_context = {
        "subject": recent_subject or "unknown",
        "topic": session_topic or "discussed",
        "completed": session_completed,
        "score": session_score,
        "struggled_with": session_struggles,
    }

    try:
        await set_state(student_id, "ended",
            reason=f"Student ended session: {msg_lower[:50]}",
            session_context=session_context,
        )
    except Exception:
        pass

    try:
        await save_session_summary(student_id, {
            **session_context,
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    # Session-end observation extraction
    if not student_id.startswith("temp_"):
        try:
            from brain.observations import extract_and_save_observations
            asyncio.ensure_future(
                extract_and_save_observations(
                    student_id=student_id,
                    conversation_history=conversation_history,
                    is_session_end=True,
                )
            )
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"Session-end extraction trigger failed: {e}")

    # Account creation offer for temp students at session end
    if student_id.startswith("temp_"):
        try:
            await _maybe_offer_account_creation(
                chat_id=chat_id,
                student=student,
                student_id=student_id,
                conversation_history=conversation_history,
                current_state="ended",
            )
        except Exception as e:
            logger.error(f"Account offer at session end failed: {e}")


def _extract_topic_from_history(conversation_history: List[Dict]) -> str:
    """Extract the current topic from recent conversation history."""
    topic_keywords = [
        "Today:", "today:", "Let's learn about", "let's learn about",
        "we'll cover", "focusing on", "Let's focus on", "let's focus on",
        "Let's dive into", "let's dive into",
        "you were doing well with", "You were doing well with",
        "we covered", "We covered", "we looked at", "We looked at",
        "we discussed", "We discussed",
        "don't forget that", "Don't forget that",
        "you worked that out", "You worked that out",
        "you're getting", "You're getting", "you understood", "You understood",
    ]
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for keyword in topic_keywords:
                if keyword in content:
                    parts = content.split(keyword, 1)
                    if len(parts) > 1:
                        extracted = parts[1].strip().split(".")[0].strip()[:50]
                        if extracted and len(extracted) > 2:
                            return extracted
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                subject_display = subject.replace("_", " ")
                if subject_display.lower() in content.lower():
                    return subject_display
    return "discussed"


# ═══════════════════════════════════════════════
# DEFERRAL HANDLER
# ═══════════════════════════════════════════════

async def _handle_deferral(
    chat_id: int, student: dict, student_id: str, name: str, msg_lower: str
) -> None:
    """Handle when a student defers or asks to change topic."""
    from database.conversations import save_message

    trouble_subject = student.get("student_subject")
    if not trouble_subject:
        trouble_subject = _infer_recent_subject(student, [])
    if not trouble_subject or trouble_subject in ("unknown", "a subject", ""):
        trouble_subject = "Mathematics"

    deferral_key = f"deferral_count:{student_id}"
    deferral_count = 0
    try:
        raw = redis_client.get(deferral_key)
        if raw:
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            deferral_count = int(raw_str)
    except Exception:
        pass

    deferral_count += 1

    if deferral_count == 1:
        response = f"{trouble_subject}. You said it's been confusing you — that's exactly where we start. Let's go."
    elif deferral_count == 2:
        response = f"{name}, I already picked. {trouble_subject}. You told me it's confusing and you're not alone in that. But running from it won't help. Let's face it together. Ready?"
    else:
        response = f"{trouble_subject}, {name}. No more running. We're doing this. Tell me what you already know about {trouble_subject}."

    try:
        redis_client.setex(deferral_key, DEFERRAL_TTL, str(deferral_count))
    except Exception:
        pass
    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass

    try:
        timestamp_key = f"last_message_time:{student_id}"
        redis_client.setex(timestamp_key, 86400, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass

    await send_telegram_message(chat_id, response)


# ═══════════════════════════════════════════════
# AI CONVERSATION HANDLER
# ═══════════════════════════════════════════════

async def _handle_ai_conversation(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    student_id: str,
    name: str
) -> None:
    """Process a student message through the AI brain with progressive observation extraction."""
    from ai.brain import think
    from brain.state import get_state, set_state
    from database.conversations import get_history, save_message

    try:
        from brain.student_model import load_student_model, save_student_model
        _student_model_available = True
    except ImportError:
        _student_model_available = False

    try:
        await save_message(student_id, "user", text)
    except Exception:
        pass

    try:
        conversation_history = await get_history(student_id)
    except Exception:
        conversation_history = []

    try:
        current_state = await get_state(student_id)
        if not current_state:
            current_state = "idle"
    except Exception:
        current_state = "idle"

    recent_subject = _infer_recent_subject(student, conversation_history)
    current_topic = recent_subject or "unknown"

    try:
        context_str = await _build_memory_context(student_id)
    except Exception:
        context_str = ""

    # Session priming: skip for temp students
    is_temp = student_id.startswith("temp_")
    if not is_temp:
        is_waking = await _detect_session_gap(student_id)
        if is_waking:
            try:
                wake_context = await _build_wake_context(student_id)
                if wake_context:
                    context_str = wake_context + "\n\n" + context_str if context_str else wake_context
            except Exception as e:
                logger.error(f"Wake context build failed: {e}")
    else:
        context_str = _strip_wake_context(context_str)

    # Account creation flow for temp students
    if is_temp:
        try:
            if redis_client.exists(f"account_creation_offered:{student_id}"):
                handled = await _handle_account_creation_response(
                    chat_id=chat_id,
                    student_id=student_id,
                    text=text,
                    conversation_history=conversation_history,
                )
                if handled:
                    return
            elif redis_client.exists(f"account_creation_in_progress:{student_id}"):
                handled = await _handle_pin_submission(
                    chat_id=chat_id,
                    student_id=student_id,
                    text=text,
                    conversation_history=conversation_history,
                )
                if handled:
                    return
        except Exception as e:
            logger.error(f"Account creation flow error: {e}")

    # Progressive observation extraction
    if not is_temp:
        try:
            from brain.observations import extract_and_save_observations
            user_msg_count = sum(1 for m in conversation_history[-20:] if m.get("role") == "user")
            if user_msg_count > 0 and user_msg_count % PROGRESSIVE_EXTRACTION_INTERVAL == 0:
                asyncio.ensure_future(
                    extract_and_save_observations(
                        student_id=student_id,
                        conversation_history=conversation_history[-30:],
                        is_session_end=False,
                    )
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"Progressive extraction trigger failed: {e}")

    _pending_model_update = None

    if _student_model_available:
        try:
            student_model = await load_student_model(student_id)
            model_context = student_model.to_prompt_context()
            if model_context:
                context_str = model_context + "\n\n" + context_str if context_str else model_context
            _pending_model_update = student_model
        except Exception as e:
            logger.error(f"Student model load failed: {e}", exc_info=True)

    is_practice = current_state in ("in_practice", "chatting", "idle", "paused")

    try:
        response = await think(
            message=text, student=student,
            conversation_history=conversation_history,
            recent_subject=recent_subject, context_str=context_str,
            is_practice=is_practice
        )
    except Exception as e:
        logger.error(f"AI brain error: {e}", exc_info=True)
        response = f"Ah, my brain just froze for a second, {name}. Can you try again?"

    if is_temp:
        response = _sanitize_wake_phrases(response, is_temp=True)

    try:
        from brain.safety import check_output_safety
        if await check_output_safety(response):
            response = f"Let me try that differently, {name}. What subject are you studying right now?"
    except ImportError:
        pass
    except Exception:
        pass

    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass
    try:
        await send_telegram_message(chat_id, response)
    except Exception:
        pass

    try:
        from database.conversations import save_session_summary
        user_msg_count = sum(1 for m in conversation_history[-10:] if m.get("role") == "user")
        if user_msg_count >= 2:
            session_topic = _extract_topic_from_history(conversation_history)
            if response:
                for keyword in [
                    "Today:", "today:", "Let's learn about", "let's learn about",
                    "Let's focus on", "let's focus on", "Let's dive into", "let's dive into",
                    "you were doing well with", "You were doing well with",
                    "we covered", "We covered",
                ]:
                    if keyword in response:
                        parts = response.split(keyword, 1)
                        if len(parts) > 1:
                            extracted = parts[1].strip().split(".")[0].strip()[:50]
                            if extracted and len(extracted) > 2:
                                session_topic = extracted
                                break
            await save_session_summary(student_id, {
                "subject": recent_subject or "unknown",
                "topic": session_topic,
                "completed": False, "score": None,
                "struggled_with": [], "ended_at": None
            })
    except Exception:
        pass

    if _pending_model_update is not None and _student_model_available:
        try:
            session_signals = _extract_session_signals(
                message=text, response=response, student=student,
                conversation_history=conversation_history,
                recent_subject=recent_subject,
            )
            _pending_model_update.update_teaching_style(session_signals)
            _pending_model_update.update_example_domains(session_signals)
            _pending_model_update.update_communication_style(session_signals)
            _pending_model_update.update_competence(session_signals)
            await save_student_model(_pending_model_update)
        except Exception as e:
            logger.error(f"Student model update failed: {e}", exc_info=True)

    try:
        if current_state == "idle":
            await set_state(student_id, "chatting", reason="First message")
        elif current_state == "paused":
            await set_state(student_id, "chatting", reason="Returned from pause")
    except Exception:
        pass

    try:
        timestamp_key = f"last_message_time:{student_id}"
        redis_client.setex(timestamp_key, 86400, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass

    # Account creation offer for temp students (mid-conversation)
    if is_temp:
        try:
            await _maybe_offer_account_creation(
                chat_id=chat_id,
                student=student,
                student_id=student_id,
                conversation_history=conversation_history,
                current_state=current_state,
            )
        except Exception as e:
            logger.error(f"Account offer check failed: {e}")


# ═══════════════════════════════════════════════
# SESSION PRIMING — wake detection
# ═══════════════════════════════════════════════

async def _detect_session_gap(student_id: str) -> bool:
    """Check if enough time has passed to treat this as a new session wake."""
    if student_id.startswith("temp_"):
        return False
    key = f"last_message_time:{student_id}"
    try:
        raw = redis_client.get(key)
        if raw:
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            last_time = datetime.fromisoformat(raw_str)
            gap_minutes = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
            return gap_minutes >= SESSION_GAP_MINUTES
        return False
    except Exception:
        return False


async def _build_wake_context(student_id: str) -> str:
    """Build context for when a student returns after a gap."""
    if student_id.startswith("temp_"):
        return ""
    from database.conversations import get_session_summary, get_student_memory

    parts = []
    try:
        last_session = await get_session_summary(student_id)
        if last_session:
            subject = last_session.get("subject", "")
            topic = last_session.get("topic", "")
            score = last_session.get("score")
            struggles = last_session.get("struggled_with", [])
            if subject and subject != "unknown" and topic and topic != "discussed":
                wake_line = f"STUDENT IS RETURNING. Last session: {subject} - {topic}."
                if score is not None:
                    wake_line += f" Scored {int(score * 100)}%."
                if struggles:
                    wake_line += f" Struggled with: {', '.join(struggles)}."
                parts.append(wake_line)
    except Exception:
        pass

    try:
        memory = await get_student_memory(student_id)
        if memory:
            sessions_count = memory.get("sessions_completed", 0)
            if sessions_count > 0:
                parts.append(f"INFORMED GREETING: Acknowledge this is session #{sessions_count + 1}.")
            mastered = memory.get("topics_mastered", [])
            if mastered:
                parts.append(f"CELEBRATE: Student has mastered {len(mastered)} topics. Mention if natural.")
    except Exception:
        pass

    return "WAKE CONTEXT:\n" + "\n".join(f"- {p}" for p in parts) if parts else ""


def _strip_wake_context(context_str: str) -> str:
    """Remove any wake context markers from a context string."""
    if not context_str:
        return ""
    lines = context_str.split("\n")
    filtered = []
    skip_block = False
    for line in lines:
        upper = line.upper()
        if "WAKE CONTEXT" in upper or "STUDENT IS RETURNING" in upper:
            skip_block = True
            continue
        if "MEMORY CONTEXT" in upper or "LAST SESSION" in upper:
            skip_block = False
        if not skip_block:
            filtered.append(line)
    return "\n".join(filtered).strip()


# ═══════════════════════════════════════════════
# SESSION SIGNAL EXTRACTOR
# ═══════════════════════════════════════════════

def _extract_session_signals(
    message: str, response: str, student: dict,
    conversation_history: list, recent_subject: str,
) -> dict:
    """Analyze a session to extract learning signals for the Student Model."""
    signals: Dict[str, Any] = {
        "teaching_style": {},
        "example_domains": {},
        "communication": {},
        "competence": {},
        "subject": recent_subject,
    }

    msg_lower = message.strip().lower()
    resp_lower = response.strip().lower()

    if any(phrase in msg_lower for phrase in ["give me an example", "show me"]):
        signals["teaching_style"]["examples"] = signals["teaching_style"].get("examples", 0) + 0.3
    if any(phrase in msg_lower for phrase in ["just the definition", "be direct", "no examples"]):
        signals["teaching_style"]["definitions"] = signals["teaching_style"].get("definitions", 0) + 0.3
    if any(phrase in msg_lower for phrase in ["tell me a story", "make it a story"]):
        signals["teaching_style"]["stories"] = signals["teaching_style"].get("stories", 0) + 0.3

    if any(phrase in resp_lower for phrase in UNDERSTANDING_PHRASES):
        if any(word in resp_lower for word in ["example", "imagine", "think of"]):
            signals["teaching_style"]["examples"] = signals["teaching_style"].get("examples", 0) + 0.1

    domain_patterns = {
        "transportation": ["keke", "danfo", "okada", "bus", "car", "vehicle", "suv"],
        "food_cooking": ["suya", "puff-puff", "jollof", "garri", "food", "eat", "cook"],
        "market_commerce": ["market", "mile 12", "buy", "sell", "trader", "price"],
        "technology": ["phone", "app", "game", "download", "internet", "computer"],
        "school_classroom": ["teacher", "class", "textbook", "exam", "school"],
        "home_domestic": ["generator", "nepa", "fan", "tap", "light", "water", "home", "backyard"],
        "body_physical": ["breathe", "heart", "run", "walk", "body", "hand"],
        "nature_environment": ["rain", "sun", "wind", "plant", "tree", "cassava", "garden"],
    }

    rejection_phrases = [
        "i don't", "i dont", "never", "i have never",
        "don't use", "dont use", "stop using", "no more", "i don't like",
        "i dont like", "not that", "i hate",
    ]

    for domain, keywords in domain_patterns.items():
        if any(kw in msg_lower for kw in keywords):
            if any(phrase in msg_lower for phrase in rejection_phrases):
                signals["example_domains"][domain] = "avoided"
            else:
                signals["example_domains"][domain] = "preferred"

    pidgin_words = ["dey", "na", "wahala", "abeg", "omo", "sha", "nna", "abi",
                    "wetin", "go", "come", "chop", "oya", "make", "e be", "wey"]
    pidgin_count = sum(1 for word in pidgin_words if word in msg_lower)

    if pidgin_count >= 3:
        signals["communication"]["full_pidgin"] = 0.3
    elif pidgin_count >= 1:
        signals["communication"]["pidgin_mixed"] = 0.2

    if any(phrase in msg_lower for phrase in ["i understand", "i get it", "makes sense"]):
        if recent_subject and recent_subject != "unknown":
            signals["competence"][f"{recent_subject}:discussed"] = {
                "score": 0.6,
                "level": "in_progress"
            }

    return signals


# ═══════════════════════════════════════════════
# SUBJECT INFERENCE
# ═══════════════════════════════════════════════

def _infer_recent_subject(student: Dict[str, Any], conversation_history: List[Dict]) -> Optional[str]:
    """Infer what subject the student is currently discussing."""
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                if subject.replace("_", " ").lower() in content.lower():
                    return subject
    trouble_subject = student.get("student_subject")
    if trouble_subject:
        return trouble_subject
    subjects = student.get("subjects", [])
    if subjects and subjects[0]:
        return subjects[0]
    return None


# ═══════════════════════════════════════════════
# MEMORY CONTEXT BUILDER
# ═══════════════════════════════════════════════

async def _build_memory_context(student_id: str) -> str:
    """Build memory context for the AI prompt."""
    if student_id.startswith("temp_"):
        return ""
    from database.conversations import get_session_summary, get_student_memory

    context_parts: List[str] = []
    try:
        last_session = await get_session_summary(student_id)
    except Exception:
        last_session = None

    if last_session:
        subject = last_session.get("subject", "a subject")
        topic = last_session.get("topic", "a topic")
        if subject not in ("unknown", "a subject", "") and topic not in ("unknown", "a topic", "discussed", ""):
            session_line = f"LAST SESSION: {subject} - {topic}."
            if last_session.get("completed") and last_session.get("score") is not None:
                session_line += f" Score: {int(last_session['score'] * 100)}%."
            context_parts.append(session_line)

    try:
        memory = await get_student_memory(student_id)
    except Exception:
        memory = None

    if memory:
        struggles = memory.get("struggles_with", [])
        strengths = memory.get("strong_in", [])
        mastered = memory.get("topics_mastered", [])
        sessions_count = memory.get("sessions_completed", 0)
        if struggles:
            context_parts.append(f"STUDENT STRUGGLES WITH: {', '.join(struggles[-5:])}.")
        if strengths:
            context_parts.append(f"STUDENT IS STRONG IN: {', '.join(strengths[-5:])}.")
        if mastered:
            context_parts.append(f"TOPICS MASTERED: {', '.join(mastered[-5:])}.")
        if sessions_count > 0:
            context_parts.append(f"Sessions completed: {sessions_count}.")

    return "MEMORY CONTEXT:\n" + "\n".join(context_parts) if context_parts else ""


# ═══════════════════════════════════════════════
# QUIZ ENGINE
# ═══════════════════════════════════════════════

async def _load_questions(subject: str) -> List[Dict[str, Any]]:
    """Load quiz questions for a subject asynchronously."""
    cache_key = f"questions_cache:{subject}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached.decode("utf-8") if isinstance(cached, bytes) else cached)
    except Exception:
        pass

    questions: List[Dict[str, Any]] = []
    try:
        from database.client import supabase
        result = supabase.table("questions") \
            .select("id, subject, question_text, question, correct_answer, options") \
            .eq("subject", subject) \
            .limit(200) \
            .execute()
        if result.data:
            questions = result.data
    except Exception:
        pass

    if not questions:
        try:
            json_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "jamb_questions_clean.json"
            )
            questions = await asyncio.to_thread(_read_questions_file, json_path, subject)
        except Exception:
            pass

    if questions:
        try:
            redis_client.setex(cache_key, 300, json.dumps(questions))
        except Exception:
            pass
    return questions


def _read_questions_file(json_path: str, subject: str) -> List[Dict[str, Any]]:
    """Read and filter questions from local JSON file."""
    with open(json_path, "r", encoding="utf-8") as f:
        return [q for q in json.load(f) if q.get("subject") == subject]


async def _start_quiz(chat_id: int, student: Dict[str, Any], message_text: str = "") -> None:
    """Start a quiz session."""
    student_id = str(student["id"])
    student_subjects = student.get("subjects", [])
    student_track = _infer_track(student_subjects)

    if not student_subjects:
        subjects_pool = TRACK_FALLBACKS.get(student_track, TRACK_FALLBACKS["unknown"]).copy()
    else:
        subjects_pool = student_subjects.copy()

    subject = _pick_rotated_subject(student_id, subjects_pool)
    db_subject = SUBJECT_MAP.get(subject.lower().replace(" ", "_"), subject.lower())
    questions = await _load_questions(db_subject)

    if not questions:
        await send_telegram_message(chat_id, f"No questions found for *{db_subject.replace('_', ' ').title()}* yet.")
        return

    question = random.choice(questions)
    if not _validate_question(question):
        await send_telegram_message(chat_id, "This question has invalid options. Type *quiz* to try another.")
        return

    quiz_key = f"active_quiz:{student_id}"
    try:
        redis_client.setex(quiz_key, QUIZ_TTL_SECONDS, json.dumps({
            "question": question, "subject": db_subject,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception:
        await send_telegram_message(chat_id, "Quiz setup failed. Type *quiz* to try again.")
        return

    keyboard = build_quiz_keyboard(question)
    if not keyboard:
        await send_telegram_message(chat_id, "This question is missing options. Type *quiz* for another.")
        return

    display_subject = db_subject.replace("_", " ").title()
    question_body = question.get("question_text", question.get("question", "Question loading..."))
    try:
        await send_telegram_message(
            chat_id,
            f"📝 *{display_subject}*\n\n{question_body}\n\n_Tap your answer below:_",
            reply_markup=keyboard
        )
    except Exception:
        try:
            redis_client.delete(quiz_key)
        except Exception:
            pass


async def handle_quiz_callback(chat_id: int, callback_query_id: str, callback_data: str) -> None:
    """Handle quiz button callbacks."""
    try:
        await answer_callback_query(callback_query_id, text="✅")
    except Exception:
        pass

    try:
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id("telegram", str(chat_id))
    except Exception:
        return
    if not student:
        await send_telegram_message(chat_id, "I can't find your account. Type *HI* to restart.")
        return
    if callback_data in ("A", "B", "C", "D"):
        await _handle_quiz_answer(chat_id, student, callback_data)


async def _handle_quiz_answer(chat_id: int, student: Dict[str, Any], answer: str) -> None:
    """Evaluate a quiz answer."""
    student_id = str(student["id"])
    quiz_key = f"active_quiz:{student_id}"
    name = student.get("name", "Student").split()[0]

    try:
        raw = redis_client.get(quiz_key)
        if not raw:
            await send_telegram_message(chat_id, "No active quiz. Reply with *quiz* to start one!")
            return
        quiz_data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except json.JSONDecodeError:
        redis_client.delete(quiz_key)
        await send_telegram_message(chat_id, "Quiz data was corrupted. Type *quiz* to start fresh.")
        return
    except Exception:
        await send_telegram_message(chat_id, "I lost track of the quiz. Type *quiz* to start a new one.")
        return

    try:
        redis_client.delete(quiz_key)
    except Exception:
        pass

    question = quiz_data["question"]
    correct = question.get("correct_answer", "A").strip().upper()
    is_correct = (answer == correct)

    if is_correct:
        response = f"✅ *Correct!*\n\nWell done, {name}!"
    else:
        response = f"❌ That's not quite right.\n\nThe correct answer is *{correct}*."

    _log_quiz_answer(student_id, question, is_correct)
    response += "\n\nType *quiz* for another question!"
    try:
        await send_telegram_message(chat_id, response)
    except Exception:
        pass

    try:
        timestamp_key = f"last_message_time:{student_id}"
        redis_client.setex(timestamp_key, 86400, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def _log_quiz_answer(student_id: str, question: Dict[str, Any], is_correct: bool) -> None:
    """Log quiz answer to Redis pipeline."""
    try:
        key = f"quiz_history:{student_id}"
        entry = json.dumps({
            "subject": question.get("subject", "unknown"),
            "question_id": question.get("id", "unknown"),
            "correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        pipe = redis_client.pipeline()
        pipe.lpush(key, entry)
        pipe.ltrim(key, 0, MAX_QUIZ_HISTORY - 1)
        pipe.expire(key, 86400 * 30)
        pipe.execute()
    except Exception:
        pass


def _validate_question(question: Dict[str, Any]) -> bool:
    """Validate that a question has required fields."""
    if not question.get("question_text") and not question.get("question"):
        return False
    if not question.get("correct_answer"):
        return False
    return True


def _infer_track(subjects: List[str]) -> str:
    """Infer the student's academic track from their subject combination."""
    if not subjects:
        return "unknown"
    subject_set = {s.lower().replace(" ", "_") for s in subjects}
    if subject_set & {"physics", "chemistry", "biology", "further_mathematics", "agricultural_science"}:
        return "science"
    if subject_set & {"accounting", "commerce", "business_studies", "marketing", "book_keeping", "office_practice", "insurance"}:
        return "commercial"
    if subject_set & {"literature_in_english", "government", "civic_education", "crs", "irs", "history", "visual_arts", "music", "french", "arabic"}:
        return "arts"
    if subject_set & {"fashion_design", "gsm_repairs", "solar_installation", "livestock_farming", "beauty_cosmetology", "horticulture"}:
        return "trade"
    if "economics" in subject_set and "government" in subject_set:
        return "arts"
    if "economics" in subject_set:
        return "commercial"
    return "unknown"


def _pick_rotated_subject(student_id: str, subjects: List[str]) -> str:
    """Pick a subject using Redis-backed rotation tracking."""
    if not subjects:
        return "mathematics"
    
    tracker_key = f"quiz_rotation:{student_id}"
    recent = []
    
    try:
        raw = redis_client.get(tracker_key)
        if raw:
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            recent = json.loads(raw_str)
    except Exception:
        pass
    
    available = [s for s in subjects if s not in recent]
    if not available:
        available = subjects
        recent = []
    
    chosen = random.choice(available)
    recent.append(chosen)
    
    if len(recent) > 5:
        recent = recent[-5:]
    
    try:
        redis_client.setex(tracker_key, 86400, json.dumps(recent))
    except Exception:
        pass
    
    return chosen


async def warmup_question_cache() -> None:
    """Pre-load question caches for common subjects on startup."""
    for subject in ["mathematics", "english", "physics", "chemistry", "biology", "government", "economics"]:
        try:
            await _load_questions(subject)
        except Exception:
            pass
