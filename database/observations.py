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

FIXES APPLIED:
    1.  _observation_key() now uses SHA256 (like siapm_memory.py) instead of MD5.
    2.  TODO: Filler phrase stripping is too aggressive — trim the list (extraction engine).
    3.  TODO: Remove category whitelist validation — let categories grow organically.
    4.  TODO: Allow implied observations in extraction prompt, not just explicit.
    5.  Age penalty is now category-aware (volatile categories decay, stable ones don't).
    6.  Added check_observation_exists() for explicit deduplication before save.
    7.  TODO: Change hardcoded 'Wax' to 'Teacher' in transcript builder.
    8.  TODO: Move mini-prompt to ai/prompts.py.
    9.  TODO: Add negative signal extraction.
    10. Redis persistence now delegates to brain/siapm_memory.save_observation().
    11. Imports normalize_observation_key and calculate_authority from brain/observation_utils.
    12. FIX: now variable defined inside _resolve_category_conflicts.
    13. FIX: _normalize_siapm_to_legacy builds explicit dict (no **siapm_data spread).
    14. FIX: Supabase fallback merges with Redis data, removes early return.
    15. FIX: confirm_observation appends SIAPM layers instead of mutating in place.
    16. FIX: Documented fragile import chain.
    17. FIX: _normalize_siapm_to_legacy uses explicit first/last guard for clarity.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from database.client import redis_client, supabase
# NOTE: brain.siapm_memory imports from database.client (leaf module).
# This import chain works because database.client has no dependencies on
# database.observations. If database.client ever imports from here,
# this becomes circular. Monitor when refactoring.
from brain.siapm_memory import save_observation as siapm_save_observation
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

# Fix 5: Category volatility for age penalty
VOLATILE_CATEGORIES = {
    "mood", "current_topic", "active_subject", "recent_struggle",
    "emotional_state", "session_context",
}
STABLE_CATEGORIES = {
    "career_goal", "learning_style", "identity_traits",
    "domain_preference", "exam_target", "personal_context",
}

# Maximum observations to load per tier
MAX_CRITICAL_OBSERVATIONS = 15
MAX_SESSION_OBSERVATIONS = 20
MAX_ARCHIVE_OBSERVATIONS = 100


# ═══════════════════════════════════════════════
# KEY GENERATION
# ═══════════════════════════════════════════════

def _observation_key(student_id: str, category: str, fact: str) -> str:
    """Build a full Redis key for an observation using SIAPM-style SHA256 hashing."""
    hash_input = f"{student_id}:{fact}:{category}"
    fact_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]
    return f"wax:om:{student_id}:{fact_hash}"


# ═══════════════════════════════════════════════
# SIAPM HELPERS
# ═══════════════════════════════════════════════

def _decode_siapm_hash(raw: dict) -> dict:
    """Decode a Redis Hash (bytes keys/values) into a plain Python dict."""
    obs = {}
    for field, value in raw.items():
        field_str = field.decode("utf-8") if isinstance(field, bytes) else field
        value_str = value.decode("utf-8") if isinstance(value, bytes) else value
        try:
            obs[field_str] = json.loads(value_str)
        except json.JSONDecodeError:
            obs[field_str] = value_str
    return obs


def _normalize_siapm_to_legacy(siapm_data: dict) -> dict:
    """
    Normalize SIAPM hash data to legacy observation format for backward compatibility.
    Maps surface_value → fact, layer dates → first_seen / last_updated, etc.
    """
    layers = siapm_data.get("layers", [])
    first = layers[0] if layers else {}
    last = layers[-1] if layers else {}

    return {
        "fact": siapm_data.get("surface_value", last.get("value", "")),
        "category": siapm_data.get("category", ""),
        "confidence": last.get("confidence", siapm_data.get("confidence", 0.5)),
        "source": last.get("source", siapm_data.get("source", "ai_inferred_single")),
        "first_seen": first.get("date") if first else siapm_data.get("first_seen", ""),
        "last_updated": last.get("date") if last else siapm_data.get("last_updated", ""),
        "times_observed": len(layers) if layers else siapm_data.get("times_observed", 1),
        "active": siapm_data.get("active", True),
        "deleted": siapm_data.get("deleted", False),
        "last_reviewed_by_student": siapm_data.get("last_reviewed_by_student"),
    }


def _calculate_observation_score(obs: dict) -> float:
    """
    Fix 5: Score observation by confidence, repetition, and category-aware age penalty.
    Volatile categories decay quickly; stable categories persist.
    """
    confidence = obs.get("confidence", 0.5)
    layers = obs.get("layers", [])
    times_observed = len(layers) if layers else obs.get("times_observed", 1)
    category = obs.get("category", "")

    # Base score from confidence and repetition
    score = confidence * (1 + 0.1 * times_observed)

    # Age penalty for volatile categories only
    if category in VOLATILE_CATEGORIES:
        last_updated = obs.get("last_updated") or (
            layers[-1].get("date") if layers else None
        )
        if last_updated:
            try:
                last_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - last_dt).days
                decay = 0.05 * age_days  # 5% per day
                score *= max(0.1, 1.0 - decay)
            except Exception:
                pass

    return score


# ═══════════════════════════════════════════════
# DEDUPLICATION CHECK (Fix 6)
# ═══════════════════════════════════════════════

async def check_observation_exists(student_id: str, category: str, fact: str) -> bool:
    """Explicit deduplication check before calling save_observation."""
    obs_key = _observation_key(student_id, category, fact)
    return redis_client.exists(obs_key) > 0


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
    Persists via SIAPM memory system (brain/siapm_memory.py).
    
    If the same fact was already saved, SIAPM appends a new layer
    (palimpsest) rather than overwriting.
    
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
    now = datetime.now(timezone.utc).isoformat()

    # Build SIAPM observation dict (Fix 10)
    observation = {
        "content": fact,
        "category": category,
        "confidence": confidence,
        "valence": 0,
        "arousal": 0,
        "source": source,
        "date": now,
        "consolidation_strength": 0.5,
        "active": True,
        "deleted": False,
        "deleted_at": None,
        "outdated_reason": None,
        "superseded_by": None,
        "previous_value": None,
        "last_reviewed_by_student": None,
    }

    # Persist via SIAPM
    fact_hash = await siapm_save_observation(student_id, observation)
    if not fact_hash:
        logger.error(f"SIAPM save failed for observation {obs_key}")
        return False

    # Conflict resolution (always run — Fix 4 from original audit)
    await _resolve_category_conflicts(student_id, category, fact, obs_key, source, confidence)

    # Update indexes
    try:
        redis_client.sadd(f"observation_index:{student_id}", obs_key)
        redis_client.sadd(f"observation_index:{student_id}:category:{category}", obs_key)
        redis_client.expire(f"observation_index:{student_id}", OBSERVATION_TTL)
        redis_client.expire(f"observation_index:{student_id}:category:{category}", OBSERVATION_TTL)
    except Exception as e:
        logger.warning(f"Observation index update failed: {e}")

    # Async sync to Supabase (non-blocking)
    legacy_obs = {
        "student_id": student_id,
        "normalized_key": fact_hash,
        "category": category,
        "fact": fact,
        "confidence": confidence,
        "source": source,
        "first_seen": now,
        "last_updated": now,
        "times_observed": 1,
        "active": True,
        "deleted": False,
    }
    asyncio.ensure_future(_sync_observation_to_supabase(legacy_obs))

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
    now = datetime.now(timezone.utc).isoformat()

    try:
        category_keys = redis_client.smembers(
            f"observation_index:{student_id}:category:{new_category}"
        )

        for key_bytes in category_keys:
            key = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes

            # Skip the new key itself
            if key == new_key:
                continue

            raw = redis_client.hgetall(key)
            if not raw:
                continue

            existing = _decode_siapm_hash(raw)

            # Only handle conflicts for active observations
            if not existing.get("active", True):
                continue

            # Check if new observation has HIGHER authority (> not >=)
            existing_authority = calculate_authority({
                "source": existing.get("source", "ai_inferred_single"),
                "confidence": existing.get("confidence", 0.5),
                "times_observed": len(existing.get("layers", [])),
                "last_updated": existing.get("last_updated", ""),
            })
            new_authority = calculate_authority({
                "source": source,
                "confidence": confidence,
                "times_observed": 1,
                "last_updated": now,
            })

            if new_authority > existing_authority:
                # Mark old observation as outdated
                existing["active"] = False
                existing["outdated_reason"] = "superseded_by_newer_observation"
                existing["superseded_by"] = new_key
                existing["last_updated"] = now

                pipe = redis_client.pipeline()
                for field, value in existing.items():
                    pipe.hset(key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
                pipe.execute()

                logger.info(
                    f"Resolved conflict: key superseded by new observation for {student_id}"
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
        List of observation dicts, sorted by relevance score (descending)
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

        all_keys_list = [k.decode("utf-8") if isinstance(k, bytes) else k for k in all_keys]

        for key in all_keys_list:
            raw = redis_client.hgetall(key)
            if not raw:
                continue

            obs = _decode_siapm_hash(raw)

            # Filter: only active, non-deleted, above confidence threshold
            if not obs.get("active", True):
                continue
            if obs.get("deleted", False):
                continue
            if obs.get("confidence", 0) < min_confidence:
                continue

            # Fix 5: Apply category-aware age penalty for sorting
            obs["_score"] = _calculate_observation_score(obs)
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
                # Repopulate Redis in background (Fix 5: fire-and-forget)
                for row in result.data:
                    siapm_obs = {
                        "content": row["fact"],
                        "category": row["category"],
                        "confidence": row["confidence"],
                        "valence": 0,
                        "arousal": 0,
                        "source": row["source"],
                        "date": row["last_updated"],
                        "consolidation_strength": 0.5,
                        "active": True,
                        "deleted": False,
                    }
                    asyncio.ensure_future(siapm_save_observation(student_id, siapm_obs))

                # Normalize Supabase rows and merge with Redis observations
                for row in result.data:
                    siapm_style = {
                        "surface_value": row.get("fact", ""),
                        "category": row.get("category", ""),
                        "confidence": row.get("confidence", 0.5),
                        "source": row.get("source", ""),
                        "first_seen": row.get("first_seen", ""),
                        "last_updated": row.get("last_updated", ""),
                        "times_observed": row.get("times_observed", 1),
                        "active": row.get("active", True),
                        "deleted": row.get("deleted", False),
                        "_score": row.get("confidence", 0.5),
                    }
                    # Avoid duplicates with Redis data already collected
                    if not any(
                        (o.get("surface_value") == siapm_style["surface_value"] or o.get("content") == siapm_style["surface_value"])
                        and o.get("category") == siapm_style["category"]
                        for o in observations
                    ):
                        observations.append(siapm_style)

        except Exception as e:
            logger.error(f"Supabase fallback failed: {e}")

    # Sort by score descending (Fix 5: category-aware ranking)
    observations.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # Normalize to legacy format and strip internal sorting field
    for obs in observations:
        obs.pop("_score", None)

    # Normalize only SIAPM observations; Supabase-style ones are already compatible
    result = []
    for obs in observations[:limit]:
        if "layers" in obs or "surface_value" in obs or "content" in obs:
            result.append(_normalize_siapm_to_legacy(obs))
        else:
            result.append(obs)
    return result


async def load_critical_observations(student_id: str) -> List[Dict]:
    """
    Load Tier 1 observations — critical context always loaded.
    
    These are observations in CRITICAL_CATEGORIES with high confidence.
    Loaded before every conversation. Fast. (~10 observations)
    """
    return await get_active_observations(
        student_id=student_id,
        categories=CRITICAL_CATEGORIES,
        limit=MAX_CRITICAL_OBSERVATIONS,
        min_confidence=0.5,
    )


async def load_session_observations(
    student_id: str,
    current_subject: Optional[str] = None,
) -> List[Dict]:
    """
    Load Tier 2 observations — session-specific context.
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
    """
    observations = await get_active_observations(
        student_id=student_id,
        limit=5,
        min_confidence=0.4,
    )

    reviewable = []
    for obs in observations:
        last_reviewed = obs.get("last_reviewed_by_student")
        if not last_reviewed:
            reviewable.append(obs)
        else:
            try:
                reviewed_time = datetime.fromisoformat(last_reviewed)
                days_since_review = (datetime.now(timezone.utc) - reviewed_time).days
                if days_since_review > 30:
                    reviewable.append(obs)
            except Exception:
                reviewable.append(obs)

    return reviewable[:5]


async def confirm_observation(observation_key: str, confirmed: bool = True) -> bool:
    """
    Student confirms or denies an observation.
    
    Confirmed → appends a confirmed layer via SIAPM.
    Denied → appends a denied layer via SIAPM.
    """
    try:
        raw = redis_client.hgetall(observation_key)
        if not raw:
            return False

        obs = _decode_siapm_hash(raw)
        now = datetime.now(timezone.utc).isoformat()

        # Extract student_id from key: wax:om:{student_id}:{hash}
        student_id = None
        if observation_key.startswith("wax:om:"):
            remainder = observation_key[len("wax:om:"):]
            student_id = remainder.rsplit(":", 1)[0]

        if not student_id:
            logger.error(f"Could not extract student_id from key: {observation_key}")
            return False

        if confirmed:
            # Append a confirmed layer via SIAPM
            confirmed_obs = {
                "content": obs.get("surface_value", obs.get("fact", "")),
                "category": obs.get("category", ""),
                "confidence": 1.0,
                "valence": obs.get("valence", 0),
                "arousal": obs.get("arousal", 0),
                "source": "student_confirmed",
                "date": now,
                "consolidation_strength": 1.0,
            }
            await siapm_save_observation(student_id, confirmed_obs)
        else:
            # Append a denied layer
            denied_obs = {
                "content": obs.get("surface_value", obs.get("fact", "")),
                "category": obs.get("category", ""),
                "confidence": 0.0,
                "valence": -0.5,
                "arousal": 0.3,
                "source": "student_denied",
                "date": now,
                "consolidation_strength": 0.0,
            }
            await siapm_save_observation(student_id, denied_obs)

        # Update the Redis hash for backward compatibility with existing indexes
        obs["last_reviewed_by_student"] = now
        obs["last_updated"] = now
        if confirmed:
            obs["confidence"] = 1.0
            obs["source"] = "student_confirmed"
        else:
            obs["active"] = False
            obs["outdated_reason"] = "denied_by_student"

        pipe = redis_client.pipeline()
        for field, value in obs.items():
            pipe.hset(observation_key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
        pipe.execute()

        logger.info(
            f"Observation {'confirmed' if confirmed else 'denied'}: "
            f"{obs.get('surface_value', '')[:50]}"
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
    Layer 2: active=False observations excluded from loading
    Layer 3: Conversation history deletion handled separately by handler
    
    TODO: Phase 2 — append deletion layers via SIAPM instead of mutating hashes.
    """
    now = datetime.now(timezone.utc).isoformat()

    try:
        all_keys = redis_client.smembers(f"observation_index:{student_id}")
        deleted_count = 0

        for key_bytes in all_keys:
            key = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes

            raw = redis_client.hgetall(key)
            if not raw:
                continue

            obs = _decode_siapm_hash(raw)

            obs["active"] = False
            obs["deleted"] = True
            obs["deleted_at"] = now

            # Write back with shorter TTL
            pipe = redis_client.pipeline()
            for field, value in obs.items():
                pipe.hset(key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
            pipe.expire(key, OBSERVATION_DELETION_RECOVERY)
            pipe.execute()

            # Clean up index sets on soft delete
            redis_client.srem(f"observation_index:{student_id}", key)
            redis_client.srem(f"observation_index:{student_id}:category:{obs.get('category', '')}", key)

            deleted_count += 1

        logger.info(f"Soft-deleted {deleted_count} observation(s) for {student_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to forget observations for {student_id}: {e}")
        return False


async def hard_delete_expired_observations() -> int:
    """
    Permanently delete observations past the recovery window.
    
    Redis TTL handles this automatically.
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
    """
    observations = []

    try:
        all_keys = redis_client.smembers(f"observation_index:{student_id}")

        for key_bytes in all_keys:
            key = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes

            raw = redis_client.hgetall(key)
            if not raw:
                continue

            obs = _decode_siapm_hash(raw)
            observations.append(obs)

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
