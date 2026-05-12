"""
WaxPrep v2 — Observation Extraction Engine
Extracts structured observations about a student from conversation history.
Runs progressively during conversations (every 5 messages) and at session end.

Architecture:
    - Progressive extraction: Lightweight, runs mid-conversation
    - Session-end extraction: Full extraction with higher confidence
    - Content-addressable keys: Same fact → same key, no duplicates
    - Confidence scoring: Source-based authority weighting
    - Streaming save: Observations persist even if session crashes
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("waxprep.brain.observations")

# ═══════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════

OBSERVATION_CATEGORIES = [
    "career_goal",
    "academic_strength",
    "academic_struggle",
    "learning_style",
    "domain_preference",
    "personal_context",
    "exam_target",
    "communication_style",
    "emotional_state",
    "life_circumstance",
]

# Source authority weights — higher = more trusted
SOURCE_AUTHORITY = {
    "quiz_data": 1.0,
    "student_stated_explicitly": 0.9,
    "student_stated_multiple_times": 0.85,
    "student_implied": 0.5,
    "ai_inferred_single": 0.3,
    "ai_inferred_multiple": 0.5,
}

# How often to run progressive extraction (every N user messages)
PROGRESSIVE_EXTRACTION_INTERVAL = 5

# Maximum conversation messages to include in extraction prompt
MAX_EXTRACTION_WINDOW = 30


# ═══════════════════════════════════════════════
# NORMALIZATION
# ═══════════════════════════════════════════════

def _normalize_observation(category: str, fact: str) -> str:
    """
    Normalize an observation into a stable, content-addressable key.
    
    Same fact always produces the same key, regardless of phrasing.
    This is the deduplication mechanism.
    
    Args:
        category: Observation category (career_goal, academic_struggle, etc.)
        fact: The extracted fact text
        
    Returns:
        Normalized key string like "career_goal:brain_surgeon"
    """
    # Lowercase and strip
    normalized = fact.lower().strip()
    
    # Remove filler phrases that change wording but not meaning
    filler_phrases = [
        "wants to be a", "wants to become a", "wants to study",
        "is interested in", "mentioned", "said they want",
        "thinks about", "considering", "might want to",
    ]
    for phrase in filler_phrases:
        normalized = normalized.replace(phrase, "")
    
    # Collapse whitespace
    normalized = " ".join(normalized.split())
    
    # Create a short hash for the key
    # For career goals, use the actual goal as the key
    # For other categories, hash to prevent absurdly long keys
    if category in ("career_goal", "exam_target"):
        # Keep readable for these critical categories
        key_content = normalized.replace(" ", "_")[:50]
    else:
        # Hash for everything else
        key_content = hashlib.md5(normalized.encode()).hexdigest()[:12]
    
    return f"{category}:{key_content}"


def _normalize_fact_for_display(fact: str) -> str:
    """Clean up a fact for storage display."""
    # Capitalize first letter
    fact = fact.strip()
    if fact and fact[0].islower():
        fact = fact[0].upper() + fact[1:]
    # Ensure it ends with proper punctuation
    if fact and fact[-1] not in ".!?":
        fact += "."
    return fact


# ═══════════════════════════════════════════════
# AI EXTRACTION
# ═══════════════════════════════════════════════

def _build_extraction_prompt(conversation_history: List[Dict], 
                              existing_observations: List[Dict]) -> str:
    """
    Build a compact prompt for the AI to extract observations.
    
    Uses the FAST model to save tokens. Only asks for NEW observations.
    
    Args:
        conversation_history: Recent messages
        existing_observations: Already-saved observations (to avoid re-extracting)
        
    Returns:
        Prompt string for the AI
    """
    # Build a compact conversation transcript
    transcript_lines = []
    for msg in conversation_history[-MAX_EXTRACTION_WINDOW:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")[:200]  # Truncate long messages
        prefix = "Student" if role == "user" else "Wax"
        transcript_lines.append(f"{prefix}: {content}")
    
    transcript = "\n".join(transcript_lines)
    
    # List what we already know (to avoid re-extracting)
    known_facts = ""
    if existing_observations:
        known_items = []
        for obs in existing_observations[:10]:  # Limit to 10 most recent
            known_items.append(f"- [{obs.get('category', '')}] {obs.get('fact', '')}")
        known_facts = "Already known about this student:\n" + "\n".join(known_items)
    
    return f"""Extract 1-3 NEW facts about this student from the conversation below.
Only extract facts the student EXPLICITLY stated. Don't infer.
If nothing new was shared, return an empty list.

Categories: career_goal, academic_strength, academic_struggle, learning_style, 
domain_preference, personal_context, exam_target, communication_style, 
emotional_state, life_circumstance

{known_facts}

Conversation:
{transcript}

Return ONLY valid JSON:
[{{"category": "...", "fact": "...", "source": "student_stated_explicitly" or "student_implied", "confidence": 0.0-1.0}}]"""


async def extract_observations_from_conversation(
    conversation_history: List[Dict],
    student_id: str,
    existing_observations: Optional[List[Dict]] = None,
    is_session_end: bool = False
) -> List[Dict]:
    """
    Extract observations from conversation history using AI.
    
    Args:
        conversation_history: Recent messages
        student_id: Student's database ID
        existing_observations: Already-saved observations
        is_session_end: If True, use SMART model for higher accuracy
        
    Returns:
        List of new observation dicts to save
    """
    if not conversation_history or len(conversation_history) < 3:
        return []
    
    existing = existing_observations or []
    
    try:
        from ai.brain import _get_client
        from config.settings import settings
        
        prompt = _build_extraction_prompt(conversation_history, existing)
        
        # Use FAST model for progressive, SMART for session end
        model = settings.GROQ_SMART_MODEL if is_session_end else settings.GROQ_FAST_MODEL
        
        client = _get_client(settings.GROQ_API_KEY)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=[
                {"role": "system", "content": "You are an observation extractor. Extract only facts the student explicitly stated. Return valid JSON only. No commentary."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300 if is_session_end else 150,
            temperature=0.3,  # Low temperature for factual extraction
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        # Handle cases where the AI wraps JSON in markdown
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        result_text = result_text.strip()
        
        observations = json.loads(result_text)
        
        if not isinstance(observations, list):
            logger.warning(f"AI returned non-list for observations: {result_text[:100]}")
            return []
        
        # Validate and clean each observation
        cleaned = []
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            
            category = obs.get("category", "")
            fact = obs.get("fact", "")
            
            # Skip invalid entries
            if not category or not fact:
                continue
            if category not in OBSERVATION_CATEGORIES:
                continue
            if len(fact) < 3 or len(fact) > 200:
                continue
            
            # Clean the fact
            fact = _normalize_fact_for_display(fact)
            
            # Calculate source authority
            source = obs.get("source", "ai_inferred_single")
            base_confidence = obs.get("confidence", 0.5)
            
            cleaned.append({
                "category": category,
                "fact": fact,
                "source": source,
                "confidence": base_confidence,
            })
        
        if cleaned:
            logger.info(
                f"Extracted {len(cleaned)} observation(s) for {student_id} "
                f"({'session_end' if is_session_end else 'progressive'})"
            )
        
        return cleaned
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI observation response: {e}")
        return []
    except Exception as e:
        logger.error(f"Observation extraction failed for {student_id}: {e}")
        return []


# ═══════════════════════════════════════════════
# EXTRACTION ORCHESTRATOR
# ═══════════════════════════════════════════════

async def extract_and_save_observations(
    student_id: str,
    conversation_history: List[Dict],
    is_session_end: bool = False
) -> int:
    """
    Extract observations and save them to the database.
    
    This is the main entry point called by the handler.
    Runs as a fire-and-forget background task during conversations,
    or synchronously at session end.
    
    Args:
        student_id: Student's database ID
        conversation_history: Recent messages
        is_session_end: If True, this is the final extraction for the session
        
    Returns:
        Number of new observations saved
    """
    if not student_id or student_id.startswith("temp_"):
        return 0  # Don't extract for temporary/unregistered students
    
    try:
        from database.observations import get_active_observations, save_observation
        
        # Load existing observations to avoid re-extracting
        existing = await get_active_observations(student_id, limit=20)
        
        # Extract new observations
        new_observations = await extract_observations_from_conversation(
            conversation_history=conversation_history,
            student_id=student_id,
            existing_observations=existing,
            is_session_end=is_session_end,
        )
        
        # Save each new observation
        saved_count = 0
        for obs in new_observations:
            success = await save_observation(
                student_id=student_id,
                category=obs["category"],
                fact=obs["fact"],
                confidence=obs["confidence"],
                source=obs["source"],
            )
            if success:
                saved_count += 1
        
        if saved_count > 0:
            logger.info(
                f"Saved {saved_count} new observation(s) for {student_id}"
            )
        
        return saved_count
        
    except Exception as e:
        logger.error(f"extract_and_save_observations failed for {student_id}: {e}")
        return 0


# ═══════════════════════════════════════════════
# AUTHORITY CALCULATION
# ═══════════════════════════════════════════════

def calculate_authority(observation: Dict) -> float:
    """
    Calculate the authority weight of an observation.
    
    Higher authority = more trusted. Used for conflict resolution.
    
    Args:
        observation: Observation dict with source, confidence, times_observed
        
    Returns:
        Authority score (0.0 to 1.0+)
    """
    source = observation.get("source", "ai_inferred_single")
    base = SOURCE_AUTHORITY.get(source, 0.3)
    
    # Bonus for repeated observations
    times = observation.get("times_observed", 1)
    if times >= 5:
        base += 0.15
    elif times >= 3:
        base += 0.1
    
    # Bonus for high confidence
    confidence = observation.get("confidence", 0.5)
    if confidence >= 0.9:
        base += 0.1
    
    # Penalty for old observations
    last_updated = observation.get("last_updated")
    if last_updated:
        try:
            updated_time = datetime.fromisoformat(last_updated)
            days_old = (datetime.now(timezone.utc) - updated_time).days
            if days_old > 60:
                base -= 0.2
            elif days_old > 30:
                base -= 0.1
        except Exception:
            pass
    
    return max(0.0, min(1.0, base))
