"""
WaxPrep v2 — Telegram Message Handler (State Socket Migration + P1-A Dialectical)

MIGRATED: All state operations now go through brain/state_socket.py
instead of direct brain/state.py calls. This is the Sacred Wall pattern.

NEW (P1-A):
- Dialectical debate handler with triad state tracking in Redis
- Removed ALL keyword fallback lists (Intent Router is single source of truth)
- Imported _default_intent from ai.intent_router instead of duplicating
- Account creation intent now flows through Intent Router, not hard-coded keywords
- Fetches PIG intimacy score via get_current_intimacy_score() for fast path
- Thermal-aware phrase fetching via config.constants.get_phrases
- Session management via database.sessions (ensure/end session)
- /audit command (admin only)
- Ghost Thread Protocol (P1-B) — temporal dialectics

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
from decimal import Decimal

from telegram.sender import send_telegram_message, build_quiz_keyboard, answer_callback_query
from database.client import redis_client

# ═══════════════════════════════════════════════════════════════════════
# Session management (P1-A integration)
# ═══════════════════════════════════════════════════════════════════════
from database.sessions import ensure_active_session, end_session, add_topic_to_session

# ═══════════════════════════════════════════════════════════════════════
# AI-First Intent Router (P0-A001 + P1-A)
# ═══════════════════════════════════════════════════════════════════════
from ai.intent_router import classify_intent, _default_intent

# ═══════════════════════════════════════════════════════════════════════
# Dialectical Engine Socket (P1-A)
# ═══════════════════════════════════════════════════════════════════════
try:
    from brain.dialectical_socket import process_for_dialectical, continue_triad, weave_rupture
    _dialectical_available = True
    logger = logging.getLogger("waxprep.handler")
except ImportError:
    _dialectical_available = False
    logger = logging.getLogger("waxprep.handler")
    logger.warning("Dialectical socket not available — dialectical debates disabled")

# ═══════════════════════════════════════════════════════════════════════
# Ghost Thread Protocol (P1-B)
# ═══════════════════════════════════════════════════════════════════════
try:
    from brain.ghost_thread_socket import (
        spawn_ghost_thread,
        on_student_message,
        process_due_ghosts,
        get_student_ghost_history,
    )
    _ghost_available = True
except ImportError:
    _ghost_available = False
    logger.warning("Ghost Thread socket not available — temporal dialectics disabled")

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

# ═══════════════════════════════════════════════════════════════════════
# PIG Intimacy Score Fast Path (P0-G + P1-A)
# ═══════════════════════════════════════════════════════════════════════
from brain.relational_intimacy import get_current_intimacy_score

# ═══════════════════════════════════════════════════════════════════════
# NEW: Living Constants Registry (P1-A thermal-aware phrases)
# ═══════════════════════════════════════════════════════════════════════
from config.constants import SUBJECT_MAP, TRACK_FALLBACKS, get_phrases

# ═══════════════════════════════════════════════════════════════════════
# Admin configuration
# ═══════════════════════════════════════════════════════════════════════
ADMIN_CHAT_IDS = [8510180724]  # Only these can use admin commands

# TTLs and limits
QUIZ_TTL_SECONDS = 1800
MAX_QUIZ_HISTORY = 200
JAMB_CHECK_COOLDOWN = 604800
DEFERRAL_TTL = 3600
SESSION_GAP_MINUTES = 60
PROGRESSIVE_EXTRACTION_INTERVAL = 5
ACCOUNT_OFFER_COOLDOWN = 86400
TRIAD_TTL_SECONDS = 3600  # How long a dialectical debate stays active

# Phrases that indicate a student wants continuity (still static for now)
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

    # ═══════════════════════════════════════════════════════════════════════
    # ADMIN COMMANDS (checked before student lookup)
    # ═══════════════════════════════════════════════════════════════════════
    if text.strip().lower() == "/audit":
        if chat_id not in ADMIN_CHAT_IDS:
            await send_telegram_message(chat_id, "Sorry, I don't recognize that command. Try /help for available commands.")
            return
        try:
            from brain.audit_engine import run_audit
            audit_report = await run_audit()
            await send_telegram_message(chat_id, audit_report)
        except Exception as e:
            logger.error(f"Audit command failed: {e}")
            await send_telegram_message(chat_id, "Audit command failed. Check logs.")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # ADMIN COMMAND: /ghost — Manual ghost thread trigger (admin only)
    # ═══════════════════════════════════════════════════════════════════════
    if text.strip().lower() == "/ghost":
        if chat_id not in ADMIN_CHAT_IDS:
            await send_telegram_message(chat_id, "Sorry, I don't recognize that command.")
            return
        if not _ghost_available:
            await send_telegram_message(chat_id, "Ghost Thread Protocol not available.")
            return
        
        # Spawn a ghost thread for this admin (for testing)
        try:
            from database.students import get_student_by_platform_id
            admin_student = await get_student_by_platform_id("telegram", str(chat_id))
            if admin_student:
                ghost_id = await spawn_ghost_thread(str(admin_student["id"]))
                if ghost_id:
                    await send_telegram_message(chat_id, f"👻 Ghost thread spawned: {ghost_id}\nCheck back in ~24 hours.")
                else:
                    await send_telegram_message(chat_id, "No suitable anchor found. Have a conversation with dissonance first.")
            else:
                await send_telegram_message(chat_id, "You need to be registered to test ghost threads.")
        except Exception as e:
            logger.error(f"/ghost command failed: {e}")
            await send_telegram_message(chat_id, f"Ghost spawn failed: {e}")
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
# AI-FIRST INTENT ROUTING (P0-A002, P0-A003, P0-A004, P0-A005 + P1-A)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_registered_student(chat_id: int, student: Dict[str, Any], text: str) -> None:
    """
    Route a registered student's message using AI-first intent classification.
    EVERY message goes to the AI first. The AI decides what to do.
    """
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]

    # ═══════════════════════════════════════════════════════════════════════
    # ADMIN COMMANDS (also check here for registered users)
    # ═══════════════════════════════════════════════════════════════════════
    if text.strip().lower() == "/audit":
        if chat_id not in ADMIN_CHAT_IDS:
            await send_telegram_message(chat_id, "Sorry, I don't recognize that command. Try /help for available commands.")
            return
        try:
            from brain.audit_engine import run_audit
            audit_report = await run_audit()
            await send_telegram_message(chat_id, audit_report)
        except Exception as e:
            logger.error(f"Audit command failed: {e}")
            await send_telegram_message(chat_id, "Audit command failed. Check logs.")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # ADMIN COMMAND: /ghost (registered users)
    # ═══════════════════════════════════════════════════════════════════════
    if text.strip().lower() == "/ghost":
        if chat_id not in ADMIN_CHAT_IDS:
            await send_telegram_message(chat_id, "Sorry, I don't recognize that command.")
            return
        if not _ghost_available:
            await send_telegram_message(chat_id, "Ghost Thread Protocol not available.")
            return
        try:
            ghost_id = await spawn_ghost_thread(student_id)
            if ghost_id:
                await send_telegram_message(chat_id, f"👻 Ghost thread spawned: {ghost_id}\nCheck back in ~24 hours.")
            else:
                await send_telegram_message(chat_id, "No suitable anchor found in your recent conversations.")
        except Exception as e:
            logger.error(f"/ghost command failed: {e}")
            await send_telegram_message(chat_id, f"Ghost spawn failed: {e}")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # SESSION MANAGEMENT: Ensure active session (P1-A integration)
    # ═══════════════════════════════════════════════════════════════════════
    session_id = await ensure_active_session(student_id)

    # Get conversation history for context
    try:
        from database.conversations import get_history
        conversation_history = await get_history(student_id)
    except Exception:
        conversation_history = []

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK: Is this a reply to a Ghost Thread? (P1-B)
    # ═══════════════════════════════════════════════════════════════════════
    if _ghost_available:
        try:
            ghost_result = await on_student_message(student_id, text, conversation_history)
            if ghost_result and ghost_result.get("status") == "resurrected":
                # This is a ghost reply — handle resurrection
                resurrection_response = ghost_result.get("response", "")
                if resurrection_response:
                    await send_telegram_message(chat_id, resurrection_response)
                    logger.info(f"Ghost resurrection handled for {student_id}: {ghost_result.get('classification')}")
                return  # Don't process as normal message
        except Exception as e:
            logger.error(f"Ghost reply check failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK: Is there an active dialectical triad?
    # ═══════════════════════════════════════════════════════════════════════
    triad_state = await _get_active_triad(student_id)
    if triad_state and _dialectical_available:
        await _continue_dialectical_debate(chat_id, student, student_id, text, triad_state, conversation_history)
        return

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: AI INTENT CLASSIFICATION (ALWAYS FIRST)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        intimacy_score = await get_current_intimacy_score(student_id)
        intent = await classify_intent(text, conversation_history, intimacy_score=float(intimacy_score))
        logger.info(f"Intent classified for {student_id}: {intent['action']} (confidence: {intent['confidence']:.2f})")
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        intent = _default_intent(text)

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
            intent_hint=hint, suggested_action=action,
            session_id=session_id  # Pass session_id
        )
        return

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: ROUTE BASED ON AI'S DECISION
    # ═══════════════════════════════════════════════════════════════════════

    if action == "dialectical_midwifery" and _dialectical_available:
        await _start_dialectical_debate(chat_id, student, student_id, text, intent, conversation_history)
        return

    if action == "quiz":
        subject = intent.get("subject")
        topic = intent.get("topic")
        await _start_quiz(chat_id, student, text, subject=subject, topic=topic)
        return

    if action == "end_session":
        await _handle_session_end(chat_id, student, text, student_id, name, text.lower(), session_id=session_id)
        return

    if action == "defer":
        await _handle_deferral(chat_id, student, student_id, name, text)
        return

    if action == "emotional_support":
        await _handle_ai_conversation(
            chat_id, student, text, student_id, name,
            intent_hint="The student needs emotional support. Be empathetic, validate their feelings, then gently guide back to actionable steps.",
            session_id=session_id
        )
        return

    if action == "greeting":
        await _handle_ai_conversation(chat_id, student, text, student_id, name, session_id=session_id)
        return

    # DEFAULT: TEACH
    await _handle_ai_conversation(chat_id, student, text, student_id, name, session_id=session_id)


# ═══════════════════════════════════════════════════════════════════════
# DIALECTICAL DEBATE HANDLERS (P1-A)
# ═══════════════════════════════════════════════════════════════════════

async def _start_dialectical_debate(
    chat_id: int,
    student: Dict[str, Any],
    student_id: str,
    text: str,
    intent: Dict[str, Any],
    conversation_history: List[Dict]
) -> None:
    """
    Start a new dialectical debate when dissonance is detected.
    """
    if not _dialectical_available:
        await _handle_ai_conversation(chat_id, student, text, student_id, student.get("name", "Student").split()[0])
        return

    topic = intent.get("subject") or intent.get("topic") or "this topic"
    dissonance = intent.get("dissonance", {})

    intimacy_score = Decimal("0")
    try:
        from brain.relational_intimacy import get_intimacy_manager
        manager = get_intimacy_manager()
        stack = await manager.get_stack(student_id)
        intimacy_score = stack.current_score()
    except Exception:
        pass

    result = await process_for_dialectical(
        student_id=student_id,
        message=text,
        topic=topic,
        intimacy_score=intimacy_score,
        context={"conversation_history": conversation_history}
    )

    if not result:
        await _handle_ai_conversation(chat_id, student, text, student_id, student.get("name", "Student").split()[0])
        return

    triad_state = result.get("triad_state", {})
    await _set_active_triad(student_id, triad_state)

    rupture = result.get("rupture_interface", "")
    if rupture:
        await send_telegram_message(chat_id, rupture)

    logger.info(f"Dialectical debate started for {student_id}: {topic} (score: {dissonance.get('score', 'N/A')})")


async def _continue_dialectical_debate(
    chat_id: int,
    student: Dict[str, Any],
    student_id: str,
    text: str,
    triad_state: Dict[str, Any],
    conversation_history: List[Dict]
) -> None:
    """
    Continue an active dialectical debate after the student replies.
    """
    if not _dialectical_available:
        await _clear_active_triad(student_id)
        await _handle_ai_conversation(chat_id, student, text, student_id, student.get("name", "Student").split()[0])
        return

    result = await continue_triad(triad_state, text)

    new_triad_state = result.get("triad_state", {})
    await _set_active_triad(student_id, new_triad_state)

    rupture = result.get("rupture_interface", "")
    if rupture:
        await send_telegram_message(chat_id, rupture)

    stance = result.get("student_stance", "undetermined")
    if stance in ["synthetic", "rejecting", "formal_leaning", "vernacular_leaning"]:
        await _clear_active_triad(student_id)
        closing = _generate_debate_closing(stance, student.get("name", "Student").split()[0])
        await send_telegram_message(chat_id, closing)

    logger.info(f"Dialectical debate continued for {student_id}: round {new_triad_state.get('round_number', '?')}, stance={stance}")


def _generate_debate_closing(stance: str, name: str) -> str:
    """Generate a closing message when the student takes a stance in the debate."""
    closings = {
        "synthetic": f"Nice one, {name}! You no just pick one side — you weave both together. That's the real thinking. Let's build on that.",
        "rejecting": f"Fair, {name}. You no gree with either side. That mean your mind dey work hard. Let's look at why both no fit you.",
        "formal_leaning": f"You dey feel the school voice more, {name}. That's solid — the marking scheme go love am. But no forget say your own experience matter too.",
        "vernacular_leaning": f"You dey feel the home voice more, {name}. Your gut sabi wetin your head never explain yet. Let's see how we fit write am in exam language.",
    }
    return closings.get(stance, f"Good, {name}. You don take a stand. Let's keep building from here.")


# ═══════════════════════════════════════════════════════════════════════
# TRIAD STATE MANAGEMENT (Fixed: clean return, no UnboundLocalError)
# ═══════════════════════════════════════════════════════════════════════

async def _get_active_triad(student_id: str) -> Optional[Dict[str, Any]]:
    """Check if student has an active dialectical triad."""
    try:
        key = f"triad_state:{student_id}"
        raw = redis_client.get(key)
        if raw:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            return data
    except Exception:
        pass
    return None


async def _set_active_triad(student_id: str, triad_state: Dict[str, Any]) -> None:
    """Store active triad state in Redis."""
    try:
        key = f"triad_state:{student_id}"
        redis_client.setex(key, TRIAD_TTL_SECONDS, json.dumps(triad_state))
    except Exception as e:
        logger.error(f"Failed to set triad state for {student_id}: {e}")


async def _clear_active_triad(student_id: str) -> None:
    """Clear active triad state."""
    try:
        key = f"triad_state:{student_id}"
        redis_client.delete(key)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SESSION END HANDLER (MIGRATED to State Socket, session-aware)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_session_end(
    chat_id: int, student: dict, text: str,
    student_id: str, name: str, msg_lower: str,
    session_id: Optional[str] = None  # NEW: session_id parameter
) -> None:
    """Handle natural session endings with State Socket and database session."""
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

    # ═══════════════════════════════════════════════════════════════════════
    # PROPERLY END DATABASE SESSION (P1-A)
    # ═══════════════════════════════════════════════════════════════════════
    topics_covered = [recent_subject] if recent_subject else []
    end_emotion = _detect_end_emotion(text)
    await end_session(
        student_id=student_id,
        session_id=session_id,
        ended_by="student",
        topics_covered=topics_covered,
        emotional_arc=f"ended_{end_emotion}",
    )


def _detect_end_emotion(text: str) -> str:
    """Simple heuristic to detect emotion at session end."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["tired", "sleep", "goodnight", "good night", "i'm done", "i am done"]):
        return "tired"
    if any(w in text_lower for w in ["bye", "goodbye", "see you", "later"]):
        return "neutral"
    return "neutral"


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
# AI CONVERSATION HANDLER (MIGRATED to State Socket, PIG-Triggered Onboarding, Ghost Threads)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_ai_conversation(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    student_id: str,
    name: str,
    intent_hint: str = "",
    suggested_action: str = "",
    session_id: Optional[str] = None  # NEW: session_id parameter
) -> None:
    """
    Process a student message through the AI brain with State Socket integration
    and PIG-triggered onboarding for temp students.
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

    # DISABLED: Account creation flow (old hard-coded logic removed)
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

    # ═══════════════════════════════════════════════════════════════════════
    # PIG-TRIGGERED ONBOARDING: Natural Conversion (Ubuntu/Study-Circle)
    # ═══════════════════════════════════════════════════════════════════════
    if is_temp and not student.get("onboarding_complete"):
        try:
            from brain.state_socket import should_trigger_onboarding
            should_trigger, intimacy_score = await should_trigger_onboarding(student_id)

            if should_trigger:
                import random
                from ai.prompts import CLIFF_EDGE_PROMPTS

                last_user_msg = None
                for msg in reversed(conversation_history[-5:]):
                    if msg.get("role") == "user":
                        last_user_msg = msg.get("content", "").lower()
                        break

                if last_user_msg and any(w in last_user_msg for w in ["scared", "worried", "stressed", "fail", "anxious"]):
                    prompt_list = CLIFF_EDGE_PROMPTS["after_vulnerability"]
                elif last_user_msg and any(w in last_user_msg for w in ["oh i see", "now i understand", "i get it now", "e don clear"]):
                    prompt_list = CLIFF_EDGE_PROMPTS["after_breakthrough"]
                else:
                    prompt_list = CLIFF_EDGE_PROMPTS["mid_session"]

                topic_display = (recent_subject or "this topic").replace("_", " ").title()
                onboarding_prompt = random.choice(prompt_list).format(topic=topic_display)
                response += "\n\n" + onboarding_prompt

                try:
                    from brain.relational_intimacy import get_intimacy_manager
                    manager = get_intimacy_manager()
                    stack = await manager.get_stack(student_id)
                    stack.record_cliff_prompt(declined=False)
                    await manager.save_stack(student_id, stack)
                except Exception:
                    pass

                logger.info(f"PIG cliff-edge shown to {student_id} (score: {intimacy_score:.1f})")

        except Exception as e:
            logger.error(f"Onboarding trigger check failed: {e}")

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

    # ═══════════════════════════════════════════════════════════════════════
    # GHOST THREAD SPAWN: Check if this response should haunt later (P1-B)
    # ═══════════════════════════════════════════════════════════════════════
    if _ghost_available and not student_id.startswith("temp_"):
        try:
            # Only spawn ghosts after teaching interactions (not quizzes, not greetings)
            if current_mode in ("teaching", "chatting") and len(conversation_history) > 3:
                # Check if conversation has high thermal potential
                last_user_msg = None
                for msg in reversed(conversation_history[-5:]):
                    if msg.get("role") == "user":
                        last_user_msg = msg.get("content", "")
                        break
                
                if last_user_msg:
                    # Quick thermal check before spawning
                    from brain.ghost_thread_socket import _infer_thermal_score
                    thermal = _infer_thermal_score(last_user_msg, {})
                    if thermal >= 60:
                        # Spawn asynchronously — don't block response
                        asyncio.ensure_future(spawn_ghost_thread(student_id))
                        logger.info(f"Ghost thread spawn triggered for {student_id} (thermal: {thermal})")
        except Exception as e:
            logger.error(f"Ghost spawn trigger failed: {e}")

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
# INVISIBLE ONBOARDING STATE MACHINE (PIG-Triggered)
# ═══════════════════════════════════════════════════════════════════════

async def _start_invisible_onboarding(chat_id: int, student: dict, student_id: str, name: str) -> None:
    """
    Start the invisible onboarding state machine.

    This is NOT a form. It is a conversation where Wax "gets to know" the student.
    Each piece of data is collected across sessions, framed as teaching preparation.
    """
    from ai.prompts import STUDY_CIRCLE_FRAMING, GENTLE_GHOST_PROMPTS
    from brain.state_socket import get_full_state, set_mode

    try:
        state_data = await get_full_state(student_id)
        conversion_phase = state_data.get("conversion_phase", "anonymous")
    except Exception:
        conversion_phase = "anonymous"

    if conversion_phase == "anonymous":
        prompt = STUDY_CIRCLE_FRAMING["data_collection"]["name"]
        await set_mode(student_id, "onboarding", confidence=1.0, metadata={
            "conversion_phase": "awaiting_name",
            "onboarding_started": datetime.now(timezone.utc).isoformat(),
        })
        await send_telegram_message(chat_id, prompt)
        return

    if conversion_phase == "named":
        prompt = STUDY_CIRCLE_FRAMING["data_collection"]["class"]
        await set_mode(student_id, "onboarding", confidence=1.0, metadata={
            "conversion_phase": "awaiting_class",
        })
        await send_telegram_message(chat_id, prompt)
        return

    if conversion_phase == "classified":
        prompt = STUDY_CIRCLE_FRAMING["data_collection"]["subjects"]
        await set_mode(student_id, "onboarding", confidence=1.0, metadata={
            "conversion_phase": "awaiting_subjects",
        })
        await send_telegram_message(chat_id, prompt)
        return

    if conversion_phase == "subjected":
        prompt = STUDY_CIRCLE_FRAMING["data_collection"]["pin"]
        await set_mode(student_id, "onboarding", confidence=1.0, metadata={
            "conversion_phase": "awaiting_pin",
        })
        await send_telegram_message(chat_id, prompt)
        return

    if conversion_phase == "authenticated":
        from ai.prompts import STUDY_CIRCLE_FRAMING
        completion_msg = random.choice(STUDY_CIRCLE_FRAMING["account_created"])
        await set_mode(student_id, "active", confidence=1.0, metadata={
            "conversion_phase": "complete",
            "account_created": True,
        })
        await send_telegram_message(chat_id, completion_msg)
        return


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
# SESSION SIGNAL EXTRACTOR (Thermal-aware phrase usage)
# ═══════════════════════════════════════════════════════════════════════

async def _extract_session_signals(
    message: str, response: str, student: dict,
    conversation_history: list, recent_subject: str,
    student_id: str = None  # NEW: to fetch thermal state
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

    # Fetch thermal-aware understanding phrases dynamically
    thermal = "hot"  # default
    if student_id:
        try:
            mode = await get_current_mode(student_id)
            thermal = "hot" if mode in ("teaching", "chatting", "in_quiz") else "cool"
        except Exception:
            pass

    understanding_phrases = get_phrases("understanding", thermal_state=thermal)

    if any(phrase in msg_lower for phrase in ["give me an example", "show me"]):
        signals["teaching_style"]["examples"] = signals["teaching_style"].get("examples", 0) + 0.3
    if any(phrase in msg_lower for phrase in ["just the definition", "be direct", "no examples"]):
        signals["teaching_style"]["definitions"] = signals["teaching_style"].get("definitions", 0) + 0.3
    if any(phrase in msg_lower for phrase in ["tell me a story", "make it a story"]):
        signals["teaching_style"]["stories"] = signals["teaching_style"].get("stories", 0) + 0.3

    if any(phrase in resp_lower for phrase in understanding_phrases):
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
                parts.append(f"Wins: {', '.join(victories[:3])}")
            if struggles:
                parts.append(f"Struggles: {', '.join(struggles[:3])}")
            if emotional_arc:
                parts.append(f"Mood: {emotional_arc}")

            if parts:
                context_parts.append(f"SESSION {session_date}: {' | '.join(parts)}")
    except Exception as e:
        logger.error(f"Episodic memory error for {student_id}: {e}")

    # 4. SEMANTIC MEMORY (STUDENT FACTS)
    try:
        memory = memory if 'memory' in locals() else await load_all_memory(student_id)
        semantic = memory.get("semantic_memory", {})

        if semantic:
            semantic_lines = ["WHAT I KNOW ABOUT THIS STUDENT:"]
            for key, value in semantic.items():
                if key == "subjects":
                    continue
                if isinstance(value, str) and value.strip():
                    semantic_lines.append(f"- {key}: {value}")
                elif isinstance(value, (int, float)):
                    semantic_lines.append(f"- {key}: {value}")
                elif isinstance(value, list) and value:
                    semantic_lines.append(f"- {key}: {', '.join(str(v) for v in value[:5])}")

            if len(semantic_lines) > 1:
                context_parts.append("\n".join(semantic_lines))
    except Exception as e:
        logger.error(f"Semantic memory error for {student_id}: {e}")

    # 5. PROCEDURAL MEMORY (TEACHING PREFERENCES)
    try:
        memory = memory if 'memory' in locals() else await load_all_memory(student_id)
        procedural = memory.get("procedural_memory", {})

        if procedural:
            pref_lines = ["TEACHING PREFERENCES:"]
            for key, value in procedural.items():
                if isinstance(value, (str, int, float)):
                    pref_lines.append(f"- {key}: {value}")
                elif isinstance(value, list) and value:
                    pref_lines.append(f"- {key}: {', '.join(str(v) for v in value[:5])}")

            if len(pref_lines) > 1:
                context_parts.append("\n".join(pref_lines))
    except Exception as e:
        logger.error(f"Procedural memory error for {student_id}: {e}")

    if not context_parts:
        return ""

    return "\n\n".join(context_parts)


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

    try:
        from brain.siapm_memory import save_working_memory

        wm_update = {}
        if current_topic and current_topic != "unknown":
            wm_update["active_topic"] = current_topic

        msg_lower = text.lower()
        if any(w in msg_lower for w in ["confused", "i don't get", "i dont get", "lost", "stuck"]):
            wm_update["emotional_state"] = "confused"
        elif any(w in msg_lower for w in ["scared", "worried", "stressed", "anxious", "afraid"]):
            wm_update["emotional_state"] = "stressed"
        elif any(w in msg_lower for w in ["happy", "excited", "great", "awesome", "love this"]):
            wm_update["emotional_state"] = "excited"
        elif any(w in msg_lower for w in ["bored", "tired", "sleepy", "not interested"]):
            wm_update["emotional_state"] = "bored"

        sentences = [s.strip() for s in response.split(".") if s.strip()]
        if sentences and sentences[-1].endswith("?"):
            wm_update["last_question"] = sentences[-1]

        if len(text.split()) > 50:
            wm_update["pace"] = "fast"
        elif len(text.split()) < 5:
            wm_update["pace"] = "slow"

        if any(w in msg_lower for w in ["stuck", "can't solve", "dont know how", "no idea", "help me start"]):
            wm_update["stuck_on"] = current_topic or "unknown"

        if any(w in response.lower() for w in ["next time", "tomorrow", "we'll continue", "hang on", "not yet"]):
            wm_update["cliffhanger"] = "Session paused mid-topic"

        if wm_update:
            await save_working_memory(student_id, wm_update)
            logger.debug(f"Working memory auto-saved for {student_id}: {wm_update}")
    except Exception as e:
        logger.error(f"Working memory auto-save failed for {student_id}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# QUIZ HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def _start_quiz(
    chat_id: int,
    student: Dict[str, Any],
    text: str,
    subject: Optional[str] = None,
    topic: Optional[str] = None
) -> None:
    """Start a quiz session for the student."""
    student_id = str(student["id"])
    name = student.get("name", "Student").split()[0]

    if subject:
        subject = subject.lower().strip()
        subject = SUBJECT_MAP.get(subject, subject)
    else:
        try:
            from database.conversations import get_history
            conversation_history = await get_history(student_id)
        except Exception:
            conversation_history = []
        subject = _infer_recent_subject(student, conversation_history)

    if not subject:
        track = student.get("track", "unknown")
        fallback_subjects = TRACK_FALLBACKS.get(track, TRACK_FALLBACKS["unknown"])
        subject = random.choice(fallback_subjects)

    question_data = await _get_quiz_question(student_id, subject, topic)

    if not question_data:
        await send_telegram_message(
            chat_id,
            f"{name}, I don't have quiz questions for {subject.replace('_', ' ')} yet. "
            f"Let's study the topic first, then I'll quiz you."
        )
        return

    quiz_state = {
        "subject": subject,
        "topic": topic,
        "current_question": question_data,
        "question_number": 1,
        "score": 0,
        "total_questions": 5,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        redis_client.setex(f"quiz:{student_id}", QUIZ_TTL_SECONDS, json.dumps(quiz_state))
    except Exception as e:
        logger.error(f"Failed to save quiz state: {e}")
        return

    question_text = question_data.get("question", "")
    options = question_data.get("options", [])

    if options:
        keyboard = build_quiz_keyboard(options, question_data.get("correct_index", 0))
        await send_telegram_message(chat_id, question_text, reply_markup=keyboard)
    else:
        await send_telegram_message(chat_id, question_text)

    logger.info(f"Quiz started for {student_id}: {subject} - {topic or 'general'}")


async def _get_quiz_question(student_id: str, subject: str, topic: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get a quiz question for the student."""
    try:
        from database.students import get_student_by_id
        student = await get_student_by_id(student_id)
        class_level = student.get("class_level", "SS3")
    except Exception:
        class_level = "SS3"

    if "SS3" in class_level.upper() or "JAMB" in class_level.upper():
        jamb_question = await _get_jamb_question(subject)
        if jamb_question:
            return jamb_question

    try:
        from ai.brain import think
        from database.conversations import get_history

        conversation_history = await get_history(student_id)
        student = {"id": student_id, "name": "Student", "class_level": class_level}

        quiz_prompt = (
            f"Generate ONE multiple-choice question for {subject.replace('_', ' ')} "
            f"{'about ' + topic if topic else ''}. "
            f"Format: Question text followed by 4 options (A, B, C, D). "
            f"Include the correct answer. Make it appropriate for {class_level} level."
        )

        response = await think(
            message=quiz_prompt,
            student=student,
            conversation_history=conversation_history,
            is_practice=True
        )

        lines = [l.strip() for l in response.split("\n") if l.strip()]
        if len(lines) >= 5:
            question_text = lines[0]
            options = lines[1:5]
            correct = 0

            for i, opt in enumerate(options):
                if "*" in opt or "(correct)" in opt.lower():
                    correct = i
                    options[i] = opt.replace("*", "").replace("(correct)", "").strip()

            return {
                "question": question_text,
                "options": options,
                "correct_index": correct,
                "source": "ai_generated",
            }
    except Exception as e:
        logger.error(f"AI quiz generation failed: {e}")

    return None


async def _get_jamb_question(subject: str) -> Optional[Dict[str, Any]]:
    """Get a JAMB past question for the subject."""
    try:
        cooldown_key = f"jamb_cooldown:{subject}"
        if redis_client.exists(cooldown_key):
            return None

        import os
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        jamb_file = os.path.join(data_dir, "jamb_questions_clean.json")

        if not os.path.exists(jamb_file):
            return None

        with open(jamb_file, 'r') as f:
            questions = json.load(f)

        subject_questions = [q for q in questions if q.get("subject", "").lower() == subject.lower()]
        if not subject_questions:
            return None

        question = random.choice(subject_questions)

        redis_client.setex(cooldown_key, JAMB_CHECK_COOLDOWN, "1")

        return {
            "question": question.get("question", ""),
            "options": question.get("options", []),
            "correct_index": question.get("correct_index", 0),
            "source": "jamb_past",
            "year": question.get("year", ""),
        }
    except Exception as e:
        logger.error(f"JAMB question load failed: {e}")
    return None


async def _evaluate_quiz_answer(
    chat_id: int,
    student_id: str,
    selected_option: int,
    quiz_state: Dict[str, Any]
) -> None:
    """Evaluate the student's quiz answer and send feedback."""
    current_question = quiz_state.get("current_question", {})
    correct_index = current_question.get("correct_index", 0)
    question_number = quiz_state.get("question_number", 1)
    total_questions = quiz_state.get("total_questions", 5)
    score = quiz_state.get("score", 0)
    subject = quiz_state.get("subject", "")

    is_correct = selected_option == correct_index
    if is_correct:
        score += 1

    name = "Student"
    try:
        from database.students import get_student_by_id
        student = await get_student_by_id(student_id)
        name = student.get("name", "Student").split()[0]
    except Exception:
        pass

    if is_correct:
        feedback = f"Correct, {name}! ✅\n\n"
    else:
        correct_option = current_question.get("options", [])[correct_index] if current_question.get("options") else "Unknown"
        feedback = f"Not quite, {name}. The correct answer was: {correct_option}\n\n"

    feedback += f"Score: {score}/{question_number}\n"

    if question_number >= total_questions:
        feedback += f"\nQuiz complete! Final score: {score}/{total_questions}"
        if score == total_questions:
            feedback += " 🔥 Perfect score!"
        elif score >= total_questions * 0.7:
            feedback += " 👍 Solid work!"
        elif score >= total_questions * 0.5:
            feedback += " 💪 Keep practicing!"
        else:
            feedback += " 📚 Let's review this topic together."

        await send_telegram_message(chat_id, feedback)
        await _save_quiz_result(student_id, subject, score, total_questions)

        try:
            redis_client.delete(f"quiz:{student_id}")
        except Exception:
            pass
    else:
        feedback += f"Question {question_number + 1} of {total_questions}:"
        await send_telegram_message(chat_id, feedback)

        next_question = await _get_quiz_question(student_id, subject, quiz_state.get("topic"))
        if next_question:
            quiz_state["current_question"] = next_question
            quiz_state["question_number"] = question_number + 1
            quiz_state["score"] = score

            try:
                redis_client.setex(f"quiz:{student_id}", QUIZ_TTL_SECONDS, json.dumps(quiz_state))
            except Exception:
                pass

            question_text = next_question.get("question", "")
            options = next_question.get("options", [])
            if options:
                keyboard = build_quiz_keyboard(options, next_question.get("correct_index", 0))
                await send_telegram_message(chat_id, question_text, reply_markup=keyboard)
        else:
            await send_telegram_message(chat_id, "No more questions available for this topic.")
            try:
                redis_client.delete(f"quiz:{student_id}")
            except Exception:
                pass


async def _save_quiz_result(student_id: str, subject: str, score: int, total: int) -> None:
    """Save quiz result to database."""
    try:
        from database.conversations import save_quiz_result
        await save_quiz_result(student_id, {
            "subject": subject,
            "score": score,
            "total": total,
            "percentage": round(score / total * 100, 1) if total > 0 else 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"Failed to save quiz result: {e}")
