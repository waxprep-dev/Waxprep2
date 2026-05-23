"""
WaxPrep v2 — Telegram Message Handler (State Socket Migration)

MIGRATED: All state operations now go through brain/state_socket.py
instead of direct brain/state.py calls. This is the Sacred Wall pattern.

Core files never touch engines directly. They touch Sockets.
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

# ═══════════════════════════════════════════════════════════════════════
# NEW: AI-First Intent Router (P0-A001)
# ═══════════════════════════════════════════════════════════════════════
from ai.intent_router import classify_intent

# ═══════════════════════════════════════════════════════════════════════
# MIGRATED: State Socket replaces direct state.py (P0-F Socket Pattern)
# ═══════════════════════════════════════════════════════════════════════
from brain.state_socket import (
    get_current_mode,
    set_mode,
    get_context_for_ai,
    record_message,
    on_crash_recovery,
)

logger = logging.getLogger("waxprep.handler")

# ── Quiz trigger keywords (FALLBACK ONLY — intent router handles detection) ──
QUIZ_TRIGGERS = ["quiz", "quiz me", "test me"]

# ── Deferral keywords (FALLBACK ONLY) ──
DEFERRAL_KEYWORDS = [
    "you pick", "any one", "whatever",
    "up to you", "choose for me", "i don't know what to study",
    "i don't care", "surprise me",
    "let's change topic", "change topic", "let's move on",
    "next topic", "something else", "new topic",
    "i'm tired of this", "this one is boring",
    "let's do something else", "switch topic",
    "suggest something", "suggest a topic",
]

# ── Session end keywords (FALLBACK ONLY) ──
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

    # ═══════════════════════════════════════════════════════════════════════
    # LAYER 1: INPUT SAFETY CHECK (BEFORE AI)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        from brain.safety import check_input_safety
        safety_result = await check_input_safety(chat_id, text, student_id=None)

        if not safety_result["safe"]:
            await send_telegram_message(chat_id, safety_result["response"])
            logger.warning(f"Message blocked: {safety_result['reason']} for chat_id={chat_id}")
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

    # ═══════════════════════════════════════════════════════════════════════
    # UNREGISTERED USER — temp student flow
    # ═══════════════════════════════════════════════════════════════════════
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

    await _handle_registered_student(chat_id, new_student, text)
    return


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
            if name.lower() not in (
                "not", "good", "fine", "ok", "okay", "sure", "new", "student",
                "done", "tired", "confused", "just", "here", "ready", "back",
                "leaving", "going", "thinking", "trying", "really", "so", "very",
                "still", "sorry", "hungry", "lost", "stuck", "waiting", "coming",
                "serious",
            ):
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


# ═══════════════════════════════════════════════════════════════════════
# ACCOUNT CREATION (DISABLED — waiting for friend's research)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_account_creation_response(
    chat_id: int,
    student_id: str,
    text: str,
    conversation_history: List[Dict]
) -> bool:
    """DISABLED: Account creation flow paused pending research."""
    return False


async def _handle_pin_submission(
    chat_id: int,
    student_id: str,
    text: str,
    conversation_history: List[Dict]
) -> bool:
    """DISABLED: Account creation flow paused pending research."""
    return False


# ═══════════════════════════════════════════════════════════════════════
# AI-FIRST INTENT ROUTING (P0-A002, P0-A003, P0-A004, P0-A005)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_registered_student(chat_id: int, student: Dict[str, Any], text: str) -> None:
    """
    Route a registered student's message using AI-first intent classification.
    EVERY message goes to the AI first. The AI decides what to do.
    """
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]

    # Get conversation history for context
    try:
        from database.conversations import get_history
        conversation_history = await get_history(student_id)
    except Exception:
        conversation_history = []

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: AI INTENT CLASSIFICATION (ALWAYS FIRST)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        intent = await classify_intent(text, conversation_history)
        logger.info(f"Intent classified for {student_id}: {intent['action']} (confidence: {intent['confidence']:.2f})")
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        intent = _fallback_intent_classification(text)

    action = intent.get("action", "teach")
    confidence = intent.get("confidence", 0.5)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: LOW CONFIDENCE → ASK FOR CLARITY
    # ═══════════════════════════════════════════════════════════════════════
    if confidence < 0.7 and action != "teach":
        hint = ""
        if action == "quiz":
            hint = f"The student might want a quiz"
            if intent.get("subject"):
                hint += f" on {intent['subject']}"
            hint += ". "
        elif action == "end_session":
            hint = "The student might want to end the session. "
        elif action == "defer":
            hint = "The student is deferring topic choice. "

        await _handle_ai_conversation(
            chat_id, student, text, student_id, name,
            intent_hint=hint, suggested_action=action
        )
        return

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: ROUTE BASED ON AI'S DECISION
    # ═══════════════════════════════════════════════════════════════════════

    if action == "quiz":
        subject = intent.get("subject")
        topic = intent.get("topic")
        await _start_quiz(chat_id, student, text, subject=subject, topic=topic)
        return

    if action == "end_session":
        await _handle_session_end(chat_id, student, text, student_id, name, text.lower())
        return

    if action == "defer":
        await _handle_deferral(chat_id, student, student_id, name, text)
        return

    if action == "emotional_support":
        await _handle_ai_conversation(
            chat_id, student, text, student_id, name,
            intent_hint="The student needs emotional support. Be empathetic, validate their feelings, then gently guide back to actionable steps."
        )
        return

    if action == "greeting":
        await _handle_ai_conversation(chat_id, student, text, student_id, name)
        return

    # DEFAULT: TEACH
    await _handle_ai_conversation(chat_id, student, text, student_id, name)


def _fallback_intent_classification(text: str) -> dict:
    """Emergency fallback if the AI intent classifier fails completely."""
    msg_lower = text.lower().strip()

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

    return {"action": "teach", "subject": None, "topic": None,
            "confidence": 0.5, "student_emotion": "neutral", "context_aware": False}


# ═══════════════════════════════════════════════════════════════════════
# SESSION END HANDLER (MIGRATED to State Socket)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_session_end(
    chat_id: int, student: dict, text: str,
    student_id: str, name: str, msg_lower: str
) -> None:
    """Handle natural session endings with State Socket."""
    from ai.brain import think
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

    # MIGRATED: Use State Socket instead of direct set_state
    session_context = {
        "subject": recent_subject or "unknown",
        "topic": session_topic or "discussed",
        "completed": False,
        "score": None,
        "struggled_with": [],
    }

    await set_mode(
        student_id=student_id,
        mode="ended",
        confidence=1.0,
        metadata={"reason": f"Student ended session: {msg_lower[:50]}", "session_context": session_context}
    )

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

    # DISABLED: Account creation offer (waiting for research)
    # if student_id.startswith("temp_"):
    #     await _maybe_offer_account_creation(...)


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


# ═══════════════════════════════════════════════════════════════════════
# DEFERRAL HANDLER
# ═══════════════════════════════════════════════════════════════════════

async def _handle_deferral(
    chat_id: int, student: dict, student_id: str, name: str, text: str
) -> None:
    """Handle when a student defers or asks to change topic."""
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

    try:
        redis_client.setex(deferral_key, DEFERRAL_TTL, str(deferral_count))
    except Exception:
        pass

    whisper = (
        f"The student is deferring topic choice (deferral count: {deferral_count}). "
        f"Pick a subject for them based on their conversation history. "
        f"If they've deferred multiple times, be gently firm — not frustrated."
    )
    whisper_key = f"waxprep:deferral_whisper:{student_id}"
    try:
        redis_client.setex(whisper_key, 60, whisper)
    except Exception as e:
        logger.error(f"Failed to inject deferral whisper: {e}")

    await _handle_ai_conversation(chat_id, student, text, student_id, name)


# ═══════════════════════════════════════════════════════════════════════
# AI CONVERSATION HANDLER (MIGRATED to State Socket)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_ai_conversation(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    student_id: str,
    name: str,
    intent_hint: str = "",
    suggested_action: str = ""
) -> None:
    """
    Process a student message through the AI brain with State Socket integration.
    """
    from ai.brain import think
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

    # MIGRATED: Get current mode from State Socket
    try:
        current_mode = await get_current_mode(student_id)
    except Exception:
        current_mode = "idle"

    recent_subject = _infer_recent_subject(student, conversation_history)
    current_topic = recent_subject or "unknown"

    try:
        context_str = await _build_memory_context(student_id)
    except Exception:
        context_str = ""

    # Check for deferral whisper
    whisper_key = f"waxprep:deferral_whisper:{student_id}"
    try:
        whisper_raw = redis_client.get(whisper_key)
        if whisper_raw:
            whisper_text = whisper_raw.decode("utf-8") if isinstance(whisper_raw, bytes) else whisper_raw
            if context_str:
                context_str = whisper_text + "\n\n" + context_str
            else:
                context_str = whisper_text
            redis_client.delete(whisper_key)
    except Exception:
        pass

    # Add intent hint from the intent router
    if intent_hint:
        hint_text = f"INTENT HINT: {intent_hint}"
        if suggested_action:
            hint_text += f" Suggested action: {suggested_action}."
        if context_str:
            context_str = hint_text + "\n\n" + context_str
        else:
            context_str = hint_text

    # MIGRATED: Get state context from Socket for AI injection
    try:
        state_context = await get_context_for_ai(student_id)
        if context_str:
            context_str = state_context + "\n\n" + context_str
        else:
            context_str = state_context
    except Exception:
        pass

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

    # DISABLED: Account creation flow
    # if is_temp:
    #     ... (account creation logic removed)

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

    is_practice = current_mode in ("teaching", "chatting", "idle", "paused")

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

    # LAYER 2: OUTPUT SAFETY CHECK (AFTER AI)
    try:
        from brain.safety import check_output_safety
        output_check = await check_output_safety(response, context=context_str)

        if not output_check["safe"]:
            logger.warning(f"AI response blocked: {output_check['reason']}")
            try:
                strict_context = context_str + "\n\nSTRICT MODE: Do not give away answers. Guide with questions only."
                response = await think(
                    message=text, student=student,
                    conversation_history=conversation_history,
                    recent_subject=recent_subject, context_str=strict_context,
                    is_practice=is_practice
                )
            except Exception:
                response = f"I can't give you the answer directly, {name}. But I can help you figure it out. What have you tried so far?"
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"Output safety check error: {e}")

    try:
        await save_message(student_id, "assistant", response)
    except Exception:
        pass
    try:
        await send_telegram_message(chat_id, response)
    except Exception:
        pass

    # Auto-save Working Memory
    try:
        await _save_working_memory_update(
            student_id=student_id,
            response=response,
            current_topic=recent_subject,
            text=text
        )
    except Exception as e:
        logger.error(f"Working memory auto-save failed: {e}")

    # MIGRATED: Record message in State Socket for future mind mirror
    try:
        await record_message(student_id, "user", text)
        await record_message(student_id, "assistant", response)
    except Exception:
        pass

    # MIGRATED: Update state via Socket
    try:
        if current_mode == "idle":
            await set_mode(student_id, "chatting", confidence=1.0, metadata={"reason": "First message"})
        elif current_mode == "paused":
            await set_mode(student_id, "chatting", confidence=1.0, metadata={"reason": "Returned from pause"})
    except Exception:
        pass

    try:
        timestamp_key = f"last_message_time:{student_id}"
        redis_client.setex(timestamp_key, 86400, datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SESSION PRIMING — wake detection
# ═══════════════════════════════════════════════════════════════════════

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
                wake_line = f"Last session: {subject} - {topic}."
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
                parts.append(f"This is the student's {sessions_count + 1}th session.")
            mastered = memory.get("topics_mastered", [])
            if mastered:
                parts.append(f"Topics mastered: {', '.join(mastered)}. Mention if natural.")
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


# ═══════════════════════════════════════════════════════════════════════
# SESSION SIGNAL EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
# SUBJECT INFERENCE
# ═══════════════════════════════════════════════════════════════════════

def _infer_recent_subject(student: Dict[str, Any], conversation_history: List[Dict]) -> Optional[str]:
    """Infer what subject the student is currently discussing."""
    for msg in reversed(conversation_history[-10:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                if subject.replace("_", " ").lower() in content.lower():
                    return subject
    for msg in reversed(conversation_history[-5:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            for subject in SUBJECT_MAP:
                display = subject.replace("_", " ")
                if display.lower() in content.lower():
                    return subject
    trouble_subject = student.get("student_subject")
    if trouble_subject:
        return trouble_subject
    subjects = student.get("subjects", [])
    if subjects and subjects[0]:
        return subjects[0]
    return None


# ═══════════════════════════════════════════════════════════════════════
# MEMORY CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════

async def _build_memory_context(student_id: str) -> str:
    """Build memory context for the AI prompt with all 5 memory layers."""
    if student_id.startswith("temp_"):
        return ""

    from database.conversations import get_session_summary, get_student_memory
    from brain.siapm_memory import load_all_memory

    context_parts: List[str] = []

    # 1. WORKING MEMORY
    try:
        memory = await load_all_memory(student_id)
        working_memory = memory.get("working_memory", {})

        if working_memory:
            wm_lines = ["CURRENT SESSION STATE:"]
            active_topic = working_memory.get("active_topic", "unknown")
            if active_topic and active_topic != "unknown":
                wm_lines.append(f"- Active topic: {active_topic}")

            stuck_on = working_memory.get("stuck_on", "")
            if stuck_on:
                wm_lines.append(f"- Student is stuck on: {stuck_on}")

            emotional_state = working_memory.get("emotional_state", "neutral")
            if emotional_state and emotional_state != "neutral":
                wm_lines.append(f"- Emotional state: {emotional_state}")

            last_question = working_memory.get("last_question", "")
            if last_question:
                wm_lines.append(f"- Last question asked: {last_question}")

            pace = working_memory.get("pace", "normal")
            if pace and pace != "normal":
                wm_lines.append(f"- Pace: {pace}")

            cliffhanger = working_memory.get("cliffhanger", "")
            if cliffhanger:
                wm_lines.append(f"- Unfinished: {cliffhanger}")

            if len(wm_lines) > 1:
                context_parts.append("\n".join(wm_lines))

            if active_topic and active_topic != "unknown":
                context_parts.append(
                    f"TOPIC CONTINUITY: You are currently discussing {active_topic}. "
                    f"Stay on this topic unless the student explicitly asks to switch. "
                    f"Do not introduce new subjects without checking if the student wants to move on."
                )
    except Exception as e:
        logger.error(f"Working memory load error for {student_id}: {e}")

    # 2. OBSERVATIONS (FILTERED BY THERMAL SCORE)
    try:
        memory = memory if 'memory' in locals() else await load_all_memory(student_id)
        observations = memory.get("observations", [])

        relevant_obs = []
        for obs in observations:
            thermal_score = obs.get("thermal_score", 0)
            if isinstance(thermal_score, str):
                try:
                    thermal_score = float(thermal_score)
                except (ValueError, TypeError):
                    thermal_score = 0

            if thermal_score > 30:
                surface_value = obs.get("surface_value", obs.get("content", ""))
                provenance = obs.get("provenance", "EXTRACTED")
                marker = ""
                if provenance in ("INFERRED", "EXTRACTED"):
                    marker = "~"
                elif provenance == "UNCERTAIN":
                    marker = "?"
                relevant_obs.append(f"{marker}{surface_value}")

        if relevant_obs:
            context_parts.append("STUDENT OBSERVATIONS:\n" + "\n".join(relevant_obs[:10]))
    except Exception as e:
        logger.error(f"Observation filtering error for {student_id}: {e}")

    # 3. EPISODIC MEMORY (LAST 3 SESSIONS)
    try:
        memory = memory if 'memory' in locals() else await load_all_memory(student_id)
        episodic = memory.get("episodic_memory", [])
        recent_episodic = episodic[-3:] if len(episodic) > 3 else episodic

        for session in recent_episodic:
            session_date = session.get("date", "recent")
            topics = session.get("topics", [])
            victories = session.get("victories", [])
            struggles = session.get("struggles", [])
            emotional_arc = session.get("emotional_arc", "")

            parts = []
            if topics:
                parts.append(f"Topics: {', '.join(topics[:3])}")
            if victories:
                parts.append(f"Wins: {', '.join(victories[:2])}")
            if struggles:
                parts.append(f"Struggled with: {', '.join(struggles[:2])}")
            if emotional_arc:
                parts.append(f"Mood: {emotional_arc}")

            if parts:
                context_parts.append(f"SESSION ({session_date}): {' | '.join(parts)}")
    except Exception as e:
        logger.error(f"Episodic memory load error for {student_id}: {e}")

    # 4. SEMANTIC MEMORY
    try:
        memory = memory if 'memory' in locals() else await load_all_memory(student_id)
        semantic = memory.get("semantic_memory", {})
        semantic_lines = []

        identity = semantic.get("identity_traits", {})
        if identity:
            for key, value in identity.items():
                if isinstance(value, dict):
                    val = value.get("value", "")
                    prov = value.get("provenance", "EXTRACTED")
                else:
                    val = value
                    prov = "EXTRACTED"
                marker = "" if prov == "VERIFIED" else "~"
                semantic_lines.append(f"{marker}{key}: {val}")

        learning_style = semantic.get("learning_style", {})
        if learning_style:
            for key, value in learning_style.items():
                if isinstance(value, dict):
                    val = value.get("value", "")
                else:
                    val = value
                semantic_lines.append(f"~{key}: {val}")

        career_goals = semantic.get("career_goals", {})
        if career_goals:
            for key, value in career_goals.items():
                if isinstance(value, dict):
                    val = value.get("value", "")
                    prov = value.get("provenance", "EXTRACTED")
                else:
                    val = value
                    prov = "EXTRACTED"
                marker = "" if prov == "VERIFIED" else "~"
                semantic_lines.append(f"{marker}Goal: {val}")

        mastered = semantic.get("mastered_topics", {})
        if mastered:
            mastered_list = []
            for topic, data in mastered.items():
                if isinstance(data, dict):
                    date = data.get("date", "")
                    mastered_list.append(f"{topic} ({date})")
                else:
                    mastered_list.append(topic)
            if mastered_list:
                semantic_lines.append(f"Mastered: {', '.join(mastered_list[:5])}")

        struggling = semantic.get("struggling_topics", {})
        if struggling:
            struggling_list = []
            for topic, data in struggling.items():
                if isinstance(data, dict):
                    error_pattern = data.get("error_pattern", "")
                    struggling_list.append(f"{topic} ({error_pattern})")
                else:
                    struggling_list.append(topic)
            if struggling_list:
                semantic_lines.append(f"Struggling: {', '.join(struggling_list[:5])}")

        if semantic_lines:
            context_parts.append("STUDENT PROFILE:\n" + "\n".join(semantic_lines))
    except Exception as e:
        logger.error(f"Semantic memory load error for {student_id}: {e}")

    # 5. PROCEDURAL MEMORY
    try:
        memory = memory if 'memory' in locals() else await load_all_memory(student_id)
        procedural = memory.get("procedural_memory", {})

        if procedural:
            proc_lines = ["TEACHING PREFERENCES:"]
            explanation_depth = procedural.get("explanation_depth", "")
            if explanation_depth:
                proc_lines.append(f"- Explanation style: {explanation_depth}")

            joke_frequency = procedural.get("joke_frequency", "")
            if joke_frequency and joke_frequency != "medium":
                proc_lines.append(f"- Joke frequency: {joke_frequency}")

            encouragement_style = procedural.get("encouragement_style", "")
            if encouragement_style and encouragement_style != "general":
                proc_lines.append(f"- Encouragement: {encouragement_style}")

            correction_style = procedural.get("correction_style", "")
            if correction_style and correction_style != "direct":
                proc_lines.append(f"- Correction style: {correction_style}")

            analogy_domains = procedural.get("analogy_domains", [])
            if analogy_domains:
                proc_lines.append(f"- Best analogies: {', '.join(analogy_domains[:3])}")

            trigger_phrases = procedural.get("trigger_phrases", {})
            if trigger_phrases:
                motivates = trigger_phrases.get("motivates", [])
                demotivates = trigger_phrases.get("demotivates", [])
                if motivates:
                    proc_lines.append(f"- Motivates them: {', '.join(motivates[:3])}")
                if demotivates:
                    proc_lines.append(f"- Demotivates them: {', '.join(demotivates[:3])}")

            if len(proc_lines) > 1:
                context_parts.append("\n".join(proc_lines))
    except Exception as e:
        logger.error(f"Procedural memory load error for {student_id}: {e}")

    # 6. LEGACY: LAST SESSION SUMMARY
    try:
        last_session = await get_session_summary(student_id)
        if last_session:
            subject = last_session.get("subject", "a subject")
            topic = last_session.get("topic", "a topic")
            if subject not in ("unknown", "a subject", "") and topic not in ("unknown", "a topic", "discussed", ""):
                session_line = f"LAST SESSION: {subject} - {topic}."
                if last_session.get("completed") and last_session.get("score") is not None:
                    session_line += f" Score: {int(last_session['score'] * 100)}%."
                context_parts.append(session_line)
    except Exception:
        pass

    # 7. LEGACY: STUDENT MEMORY
    try:
        db_memory = await get_student_memory(student_id)
        if db_memory:
            struggles = db_memory.get("struggles_with", [])
            strengths = db_memory.get("strong_in", [])
            mastered = db_memory.get("topics_mastered", [])
            sessions_count = db_memory.get("sessions_completed", 0)
            if struggles:
                context_parts.append(f"STUDENT STRUGGLES WITH: {', '.join(struggles[-5:])}.")
            if strengths:
                context_parts.append(f"STUDENT IS STRONG IN: {', '.join(strengths[-5:])}.")
            if mastered:
                context_parts.append(f"TOPICS MASTERED: {', '.join(mastered[-5:])}.")
            if sessions_count > 0:
                context_parts.append(f"Sessions completed: {sessions_count}.")
    except Exception:
        pass

    return "MEMORY CONTEXT:\n" + "\n\n".join(context_parts) if context_parts else ""


# ═══════════════════════════════════════════════════════════════════════
# WORKING MEMORY AUTO-SAVE
# ═══════════════════════════════════════════════════════════════════════

async def _save_working_memory_update(
    student_id: str,
    response: str,
    current_topic: Optional[str],
    text: str
) -> None:
    """Auto-save Working Memory after every AI response."""
    if student_id.startswith("temp_"):
        return

    from brain.siapm_memory import save_working_memory

    wm_update = {}

    if current_topic and current_topic != "unknown":
        wm_update["active_topic"] = current_topic

    confusion_signals = ["don't understand", "confused", "stuck", "lost", "don't get", "huh", "wait"]
    if any(signal in text.lower() for signal in confusion_signals):
        wm_update["emotional_state"] = "confused"
        for signal in confusion_signals:
            if signal in text.lower():
                idx = text.lower().find(signal)
                context = text[max(0, idx-30):idx+50]
                wm_update["stuck_on"] = context.strip()
                break

    frustration_signals = ["this is hard", "i give up", "too difficult", "impossible", "i can't"]
    if any(signal in text.lower() for signal in frustration_signals):
        wm_update["emotional_state"] = "frustrated"

    excitement_signals = ["i get it", "that makes sense", "oh wow", "cool", "awesome"]
    if any(signal in text.lower() for signal in excitement_signals):
        wm_update["emotional_state"] = "engaged"

    sentences = [s.strip() for s in re.split(r'[.!?]+', response) if s.strip()]
    if sentences and sentences[-1].endswith("?"):
        wm_update["last_question"] = sentences[-1]

    if len(sentences) <= 2:
        wm_update["pace"] = "fast"
    elif len(sentences) >= 6:
        wm_update["pace"] = "slow"
    else:
        wm_update["pace"] = "normal"

    cliffhanger_signals = ["try this", "solve this", "what about", "how about", "next problem"]
    if any(signal in response.lower() for signal in cliffhanger_signals):
        for signal in cliffhanger_signals:
            if signal in response.lower():
                idx = response.lower().find(signal)
                cliffhanger = response[idx:idx+100].strip()
                wm_update["cliffhanger"] = cliffhanger
                break

    if wm_update:
        try:
            await save_working_memory(student_id, wm_update)
            logger.debug(f"Working memory updated for {student_id}: {wm_update}")
        except Exception as e:
            logger.error(f"Working memory save failed for {student_id}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# QUIZ ENGINE
# ═══════════════════════════════════════════════════════════════════════

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


async def _start_quiz(chat_id: int, student: Dict[str, Any], message_text: str = "",
                      subject: str = None, topic: str = None) -> None:
    """Start a quiz session with State Socket integration."""
    student_id = str(student["id"])
    student_subjects = student.get("subjects", [])
    student_track = _infer_track(student_subjects)

    if not student_subjects:
        subjects_pool = TRACK_FALLBACKS.get(student_track, TRACK_FALLBACKS["unknown"]).copy()
    else:
        subjects_pool = student_subjects.copy()

    if subject:
        db_subject = SUBJECT_MAP.get(subject.lower().replace(" ", "_"), subject.lower())
    else:
        requested_subject = None
        msg_lower = message_text.strip().lower()
        for subject_key, mapped_subject in SUBJECT_MAP.items():
            display = subject_key.replace("_", " ")
            if re.search(r'\b' + re.escape(display) + r'\b', msg_lower):
                requested_subject = mapped_subject
                break

        if requested_subject:
            db_subject = requested_subject
        else:
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

    # MIGRATED: Set state via Socket for quiz mode
    await set_mode(
        student_id=student_id,
        mode="in_quiz",
        confidence=1.0,
        metadata={"quiz_subject": db_subject, "question_id": question.get("id")}
    )

    keyboard = build_quiz_keyboard(question)
    if not keyboard:
        await send_telegram_message(chat_id, "This question is missing options. Type *quiz* for another.")
        return

    display_subject = db_subject.replace("_", " ").title()
    question_body = question.get("question_text", question.get("question", "Question loading..."))

    topic_hint = ""
    if topic:
        topic_hint = f" (Topic: {topic.replace('_', ' ').title()})"

    try:
        await send_telegram_message(
            chat_id,
            f"📝 *{display_subject}*{topic_hint}\n\n{question_body}\n\n_Tap your answer below:_",
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
        await send_telegram_message(chat_id, "Omo, I no fit find your account. Just send 'hi' make we start fresh.")
        return
    if callback_data in ("A", "B", "C", "D"):
        await _handle_quiz_answer(chat_id, student, callback_data)


async def _handle_quiz_answer(chat_id: int, student: Dict[str, Any], answer: str) -> None:
    """Evaluate a quiz answer with State Socket integration."""
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

    correct_responses = [
        f"✅ *Correct!* You sabi that one, {name}.",
        f"✅ *Correct!* E don enter. Nice one, {name}.",
        f"✅ *Correct!* You get am. Keep going, {name}.",
        f"✅ *Correct!* Na so e be. Well done, {name}.",
    ]
    incorrect_responses = [
        f"Almost, {name}. The answer na *{correct}*. Make I show you why...",
        f"Close! But no be that one. Correct answer: *{correct}*. Let me break it down...",
        f"No wahala, {name}. The correct answer be *{correct}*. Here's why...",
    ]

    if is_correct:
        response = random.choice(correct_responses)
    else:
        response = random.choice(incorrect_responses)

    _log_quiz_answer(student_id, question, is_correct)
    response += "\n\nType *quiz* for another question!"

    # MIGRATED: Clear quiz mode via Socket
    await set_mode(
        student_id=student_id,
        mode="chatting",
        confidence=1.0,
        metadata={"reason": "Quiz completed", "was_correct": is_correct}
    )

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
    body = question.get("question_text") or question.get("question") or ""
    if len(body.strip()) < 10:
        return False
    if not question.get("correct_answer"):
        return False
    options = question.get("options")
    if not options or not isinstance(options, dict) or len(options) == 0:
        return False
    correct = question.get("correct_answer", "").strip().upper()
    if correct not in options:
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
