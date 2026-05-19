"""
WaxPrep v2 — Observation Database Layer
Stores, retrieves, and manages observations about students.
Handles deduplication, conflict resolution, tiered loading, and deletion.

Architecture:
    - Content-addressable keys: Same fact → same key, no duplicates
    - Redis primary store (fast), Supabase durable backup
    - Tiered loading: Critical always, subject-specific on demand, archive rarely
    - Authority-based conflict resolution: Quiz data > student statement > AI inference
    - Soft delete with 30-day recovery window
    - NDPR-compliant: Student owns their data, can view/edit/delete/export
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from database.client import redis_client, supabase
from brain.observation_utils import normalize_observation_key, calculate_authority

logger = logging.getLogger("waxprep.database.observations")

# ═══════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════

OBSERVATION_TTL = 86400 * 365  # 1 year in Redis
OBSERVATION_DELETION_RECOVERY = 86400 * 30  # 30 days before hard delete

# Categories that are always loaded (Tier 1 — critical context)
CRITICAL_CATEGORIES = [
    "career_goal",
    "exam_target",
    "academic_struggle",
    "domain_preference",
    "personal_context",
]

# Maximum observations to load per tier
MAX_CRITICAL_OBSERVATIONS = 15
MAX_SESSION_OBSERVATIONS = 20
MAX_ARCHIVE_OBSERVATIONS = 100


# ═══════════════════════════════════════════════
# KEY GENERATION
# ═══════════════════════════════════════════════

def _observation_key(student_id: str, category: str, fact: str) -> str:
    """Build a full Redis key for an observation."""
    normalized = normalize_observation_key(category, fact)
    return f"observation:{student_id}:{normalized}"


# ═══════════════════════════════════════════════
# SAVE
# ═══════════════════════════════════════════════

async def save_observation(
    student_id: str,
    category: str,
    fact: str,
    confidence: float = 0.5,
    source: str = "ai_inferred_single",
) -> bool:
    """
    Save an observation with content-addressable deduplication.
    
    If the same fact was already saved, this UPDATES the existing record
    (increments times_observed, updates timestamp, adjusts confidence).
    No duplicates are ever created.
    
    Args:
        student_id: Student's database ID
        category: Observation category
        fact: The extracted fact text
        confidence: Confidence score (0.0 to 1.0)
        source: Where this observation came from
        
    Returns:
        True if saved successfully
    """
    if not student_id or student_id.startswith("temp_"):
        return False
    
    obs_key = _observation_key(student_id, category, fact)
    normalized = normalize_observation_key(category, fact)
    now = datetime.now(timezone.utc).isoformat()
    
    # Check if this observation already exists
    try:
        existing_raw = redis_client.get(obs_key)
        existing = None
        if existing_raw:
            existing_str = existing_raw.decode("utf-8") if isinstance(existing_raw, bytes) else existing_raw
            existing = json.loads(existing_str)
    except Exception:
        existing = None
    
    # Always check for conflicts before saving (Fix 4: run on both UPDATE and CREATE)
    await _resolve_category_conflicts(student_id, category, fact, obs_key, source, confidence)
    
    # Source-based confidence increment (Fix 6)
    source_increment = {
        "student_stated_explicitly": 0.15,
        "student_confirmed": 0.20,
        "quiz_data": 0.15,
        "student_implied": 0.08,
        "ai_inferred_single": 0.03,
        "ai_inferred_multiple": 0.05,
    }.get(source, 0.05)
    
    if existing:
        # UPDATE existing observation
        observation = {
            **existing,
            "confidence": min(1.0, existing.get("confidence", 0.5) + source_increment),
            "times_observed": existing.get("times_observed", 1) + 1,
            "last_updated": now,
            "active": True,
        }
        logger.debug(f"Updated existing observation: {normalized}")
    else:
        # CREATE new observation (conflicts already resolved above)
        observation = {
            "student_id": student_id,
            "category": category,
            "fact": fact,
            "normalized_key": normalized,
            "confidence": confidence,
            "source": source,
            "first_seen": now,
            "last_updated": now,
            "times_observed": 1,
            "active": True,
            "deleted": False,
            "deleted_at": None,
            "outdated_reason": None,
            "superseded_by": None,
            "previous_value": None,
        }
        logger.info(f"Created new observation: {normalized} for {student_id}")
    
    # Atomic save to Redis
    try:
        redis_client.setex(obs_key, OBSERVATION_TTL, json.dumps(observation))
    except Exception as e:
        logger.error(f"Redis save failed for observation {obs_key}: {e}")
        return False
    
    # Add to index for fast retrieval
    try:
        redis_client.sadd(f"observation_index:{student_id}", obs_key)
        redis_client.sadd(f"observation_index:{student_id}:category:{category}", obs_key)
        redis_client.expire(f"observation_index:{student_id}", OBSERVATION_TTL)
        redis_client.expire(f"observation_index:{student_id}:category:{category}", OBSERVATION_TTL)
    except Exception as e:
        logger.warning(f"Observation index update failed: {e}")
    
    # Async sync to Supabase (non-blocking)
    asyncio.ensure_future(_sync_observation_to_supabase(observation))
    
    return True


async def _resolve_category_conflicts(
    student_id: str, 
    new_category: str, 
    new_fact: str,
    new_key: str,
    source: str = "ai_inferred_single",
    confidence: float = 0.5,
) -> None:
    """
    Check for conflicting observations in the same category.
    
    If a conflict is found (e.g., old career_goal vs new career_goal),
    mark the old observation as outdated.
    """
    try:
        # Get all observations in this category
        category_keys = redis_client.smembers(
            f"observation_index:{student_id}:category:{new_category}"
        )
        
        for key_bytes in category_keys:
            key = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes
            
            # Skip the new key itself
            if key == new_key:
                continue
            
            raw = redis_client.get(key)
            if not raw:
                continue
            
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            existing = json.loads(raw_str)
            
            # Only handle conflicts for active observations
            if not existing.get("active", True):
                continue
            
            # Check if new observation has HIGHER authority (Fix 5: > not >=)
            existing_authority = calculate_authority(existing)
            new_authority = calculate_authority({
                "source": source,
                "confidence": confidence,
                "times_observed": 1,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            })
            
            if new_authority > existing_authority:
                # New observation supersedes old one
                existing["active"] = False
                existing["outdated_reason"] = "superseded_by_newer_observation"
                existing["superseded_by"] = new_key
                existing["last_updated"] = datetime.now(timezone.utc).isoformat()
                
                redis_client.setex(key, OBSERVATION_TTL, json.dumps(existing))
                
                logger.info(
                    f"Resolved conflict: '{existing.get('fact', '')}' "
                    f"→ superseded by '{new_fact}' for {student_id}"
                )
    
    except Exception as e:
        logger.warning(f"Conflict resolution failed: {e}")


# ═══════════════════════════════════════════════
# LOAD (Tiered)
# ═══════════════════════════════════════════════

async def get_active_observations(
    student_id: str,
    categories: Optional[List[str]] = None,
    limit: int = 50,
    min_confidence: float = 0.3,
) -> List[Dict]:
    """
    Get active observations for a student.
    
    Args:
        student_id: Student's database ID
        categories: Filter by categories (None = all)
        limit: Maximum observations to return
        min_confidence: Minimum confidence threshold
        
    Returns:
        List of observation dicts, sorted by last_updated (newest first)
    """
    if not student_id:
        return []
    
    observations = []
    
    try:
        # Get observation keys from index
        if categories:
            all_keys = set()
            for category in categories:
                cat_keys = redis_client.smembers(
                    f"observation_index:{student_id}:category:{category}"
                )
                all_keys.update(cat_keys)
        else:
            all_keys = redis_client.smembers(f"observation_index:{student_id}")
        
        # Fix 7: Fetch all keys, filter, then apply limit
        all_keys_list = [k.decode("utf-8") if isinstance(k, bytes) else k for k in all_keys]
        
        for key in all_keys_list:
            raw = redis_client.get(key)
            if not raw:
                continue
            
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                obs = json.loads(raw_str)
            except json.JSONDecodeError:
                continue
            
            # Filter: only active, non-deleted, above confidence threshold
            if not obs.get("active", True):
                continue
            if obs.get("deleted", False):
                continue
            if obs.get("confidence", 0) < min_confidence:
                continue
            
            observations.append(obs)
            
            # Stop once we have enough
            if len(observations) >= limit:
                break
    
    except Exception as e:
        logger.error(f"Failed to load observations for {student_id}: {e}")
    
    # Fix 8: Supabase fallback when Redis is empty or sparse
    if len(observations) < 3:
        try:
            result = supabase.table("observations") \
                .select("*") \
                .eq("student_id", student_id) \
                .eq("active", True) \
                .eq("deleted", False) \
                .order("last_updated", desc=True) \
                .limit(limit) \
                .execute()
            if result.data:
                # Repopulate Redis from Supabase
                for row in result.data:
                    obs_key = _observation_key(student_id, row["category"], row["fact"])
                    redis_client.setex(obs_key, OBSERVATION_TTL, json.dumps(row))
                return result.data
        except Exception as e:
            logger.error(f"Supabase fallback failed: {e}")
    
    # Sort by last_updated (newest first)
    observations.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
    
    return observations[:limit]


async def load_critical_observations(student_id: str) -> List[Dict]:
    """
    Load Tier 1 observations — critical context always loaded.
    
    These are observations in CRITICAL_CATEGORIES with high confidence.
    Loaded before every conversation. Fast. (~10 observations)
    
    Args:
        student_id: Student's database ID
        
    Returns:
        List of critical observation dicts
    """
    return await get_active_observations(
        student_id=student_id,
        categories=CRITICAL_CATEGORIES,
        limit=MAX_CRITICAL_OBSERVATIONS,
        min_confidence=0.5,  # Higher threshold for critical context
    )


async def load_session_observations(
    student_id: str,
    current_subject: Optional[str] = None,
) -> List[Dict]:
    """
    Load Tier 2 observations — session-specific context.
    
    Includes observations matching the current subject and recent
    high-confidence observations about learning style.
    
    Args:
        student_id: Student's database ID
        current_subject: Current subject being discussed
        
    Returns:
        List of session-relevant observation dicts
    """
    categories = ["academic_strength", "academic_struggle", "learning_style"]
    
    if current_subject:
        categories.append("domain_preference")
    
    return await get_active_observations(
        student_id=student_id,
        categories=categories,
        limit=MAX_SESSION_OBSERVATIONS,
        min_confidence=0.4,
    )


# ═══════════════════════════════════════════════
# STUDENT REVIEW (Accuracy self-correction)
# ═══════════════════════════════════════════════

async def get_observations_for_review(student_id: str) -> List[Dict]:
    """
    Get observations ready for student review.
    
    Returns high-confidence observations that the student should confirm.
    Used for the periodic "Here's what I've learned about you" check.
    
    Args:
        student_id: Student's database ID
        
    Returns:
        List of observations needing review (up to 5)
    """
    observations = await get_active_observations(
        student_id=student_id,
        limit=5,
        min_confidence=0.4,  # Include medium-confidence for review
    )
    
    # Only return observations that haven't been reviewed recently
    reviewable = []
    for obs in observations:
        last_reviewed = obs.get("last_reviewed_by_student")
        if not last_reviewed:
            reviewable.append(obs)
        else:
            try:
                reviewed_time = datetime.fromisoformat(last_reviewed)
                days_since_review = (datetime.now(timezone.utc) - reviewed_time).days
                if days_since_review > 30:  # Review again after 30 days
                    reviewable.append(obs)
            except Exception:
                reviewable.append(obs)
    
    return reviewable[:5]


async def confirm_observation(observation_key: str, confirmed: bool = True) -> bool:
    """
    Student confirms or denies an observation.
    
    Confirmed → confidence set to 1.0, marked as reviewed.
    Denied → observation deactivated.
    
    Args:
        observation_key: The full Redis key of the observation
        confirmed: True if student confirms, False if they deny it
        
    Returns:
        True if updated successfully
    """
    try:
        raw = redis_client.get(observation_key)
        if not raw:
            return False
        
        raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        obs = json.loads(raw_str)
        
        now = datetime.now(timezone.utc).isoformat()
        
        if confirmed:
            obs["confidence"] = 1.0
            obs["source"] = "student_confirmed"
        else:
            obs["active"] = False
            obs["outdated_reason"] = "denied_by_student"
        
        obs["last_reviewed_by_student"] = now
        obs["last_updated"] = now
        
        redis_client.setex(observation_key, OBSERVATION_TTL, json.dumps(obs))
        
        logger.info(
            f"Observation {'confirmed' if confirmed else 'denied'}: "
            f"{obs.get('fact', '')[:50]}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to confirm observation: {e}")
        return False


# ═══════════════════════════════════════════════
# DELETION (Three-Layer Forgetting)
# ═══════════════════════════════════════════════

async def forget_all_observations(student_id: str) -> bool:
    """
    Complete observation purge — 'forget everything about me.'
    
    Layer 1: Soft delete all observations (30-day recovery)
    Layer 2: Will be automatic — active=False observations excluded from loading
    Layer 3: Conversation history deletion handled separately by handler
    
    Args:
        student_id: Student's database ID
        
    Returns:
        True if successful
    """
    now = datetime.now(timezone.utc).isoformat()
    
    try:
        all_keys = redis_client.smembers(f"observation_index:{student_id}")
        deleted_count = 0
        
        for key_bytes in all_keys:
            key = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes
            
            raw = redis_client.get(key)
            if not raw:
                continue
            
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                obs = json.loads(raw_str)
            except json.JSONDecodeError:
                continue
            
            obs["active"] = False
            obs["deleted"] = True
            obs["deleted_at"] = now
            
            # Set shorter TTL for deleted observations (30-day recovery)
            redis_client.setex(key, OBSERVATION_DELETION_RECOVERY, json.dumps(obs))
            
            # Fix 9: Clean up index sets on soft delete
            redis_client.srem(f"observation_index:{student_id}", key)
            redis_client.srem(f"observation_index:{student_id}:category:{obs['category']}", key)
            
            deleted_count += 1
        
        logger.info(
            f"Soft-deleted {deleted_count} observation(s) for {student_id}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to forget observations for {student_id}: {e}")
        return False


async def hard_delete_expired_observations() -> int:
    """
    Permanently delete observations past the recovery window.
    
    Redis TTL handles this automatically — when OBSERVATION_DELETION_RECOVERY 
    expires, Redis deletes the key. Supabase cleanup is not yet implemented.
    
    This function exists as a hook for future Supabase hard-deletion.
    """
    logger.debug("Hard delete relying on Redis TTL expiration")
    return 0


# ═══════════════════════════════════════════════
# EXPORT (NDPR Compliance)
# ═══════════════════════════════════════════════

async def export_observations(student_id: str) -> Dict:
    """
    Export all observations for a student (NDPR data portability).
    
    Returns a complete JSON-serializable dict of all observations,
    including inactive and deleted ones.
    
    Args:
        student_id: Student's database ID
        
    Returns:
        Dict with all observation data
    """
    observations = []
    
    try:
        all_keys = redis_client.smembers(f"observation_index:{student_id}")
        
        for key_bytes in all_keys:
            key = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes
            
            raw = redis_client.get(key)
            if not raw:
                continue
            
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                obs = json.loads(raw_str)
                observations.append(obs)
            except json.JSONDecodeError:
                continue
    
    except Exception as e:
        logger.error(f"Failed to export observations for {student_id}: {e}")
    
    return {
        "student_id": student_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_observations": len(observations),
        "observations": observations,
    }


# ═══════════════════════════════════════════════
# SUPABASE SYNC (Non-blocking)
# ═══════════════════════════════════════════════

async def _sync_observation_to_supabase(observation: Dict) -> None:
    """Sync a single observation to Supabase. Non-blocking background task."""
    try:
        # REQUIRES unique constraint on Supabase observations table:
        #   CREATE UNIQUE INDEX idx_observations_dedup ON observations(student_id, normalized_key);
        # Without this, upserts will create duplicates.
        supabase.table("observations").upsert(
            {
                "student_id": observation["student_id"],
                "normalized_key": observation["normalized_key"],
                "category": observation["category"],
                "fact": observation["fact"],
                "confidence": observation["confidence"],
                "source": observation["source"],
                "first_seen": observation["first_seen"],
                "last_updated": observation["last_updated"],
                "times_observed": observation["times_observed"],
                "active": observation["active"],
                "deleted": observation.get("deleted", False),
            },
            on_conflict="student_id,normalized_key"
        ).execute()
    except Exception as e:
        logger.error(f"Supabase sync failed for observation: {e}")
