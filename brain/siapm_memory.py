"""
brain/siapm_memory.py — SIAPM Memory System for WaxPrep
Five-layer Redis storage for student cognitive memory.

Built as a NEW file (does not modify database/conversations.py).
Each layer uses a distinct Redis data type and TTL strategy:
    1. Working Memory    — Redis Hash, 30-min TTL, session-hot state
    2. Episodic Memory   — Redis ZSET, last 10 entries, scored by timestamp
    3. Semantic Memory   — Redis Hash, permanent, no TTL
    4. Procedural Memory — Redis Hash, permanent, no TTL
    5. Observation Memory— Redis Hash per observation, 90-day TTL default

FIXES APPLIED:
    1. Observation hash now uses student_id + content + category only (deduplication).
    2. Palimpsest layering: observations append layers instead of overwriting.
    3. Added thermal_score field to observation schema.
    4. Added try/except around episodic date parsing.
    5. Added TODO for thermal-weighted observation filtering in load_all_memory.
    6. Added clarifying comment for ZREMRANGEBYRANK in episodic save.
    7. Preserve old consolidation_strength during flat-to-layers format conversion.
    8. Remove duplicate flat fields after conversion (content, date, source, etc.).
    9. Add floor of 15 to thermal_score so neutral observations remain visible.
    10. Ensure surface_value is always stored as a string (both new and existing paths).
    11. Keep thermal_score at top-level (not popped as a flat field).
"""

from database.client import redis_client
from datetime import datetime, timezone
import json
import logging
import hashlib

logger = logging.getLogger("waxprep.brain.siapm")

# ── TTL Constants ───────────────────────────
WORKING_MEMORY_TTL = 1800          # 30 minutes
EPISODIC_MEMORY_MAX_ENTRIES = 10   # Keep last 10 sessions hot
OBSERVATION_MEMORY_TTL = 86400 * 90  # 90 days

# ── Key Prefixes ────────────────────────────
WM_KEY = "wax:wm:{student_id}"
EM_KEY = "wax:em:{student_id}"
SM_KEY = "wax:sm:{student_id}"
PM_KEY = "wax:pm:{student_id}"
OM_KEY = "wax:om:{student_id}:{hash}"


# ── 1. Working Memory ─────────────────────────
async def save_working_memory(student_id: str, data: dict):
    """
    Save the student's current session state to Working Memory.
    Redis Hash with 30-minute TTL (refreshes on every write).
    
    Expected fields in `data`:
        active_topic, stuck_on, emotional_state, last_question,
        pace, cliffhanger
    """
    key = WM_KEY.format(student_id=student_id)
    try:
        pipe = redis_client.pipeline()
        for field, value in data.items():
            pipe.hset(key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
        pipe.expire(key, WORKING_MEMORY_TTL)
        pipe.execute()
    except Exception as e:
        logger.error(f"Working memory save error for {student_id}: {e}")


# ── 2. Episodic Memory ────────────────────────
async def save_episodic_memory(student_id: str, entry: dict):
    """
    Append a session summary to Episodic Memory.
    Redis ZSET scored by timestamp. Trims to last 10 entries.
    
    Expected fields in `entry`:
        session_id, date, duration, topics, victories,
        struggles, emotional_arc, cliffhanger
    """
    key = EM_KEY.format(student_id=student_id)
    try:
        # Use the entry's date as score; fallback to now
        date_str = entry.get("date")
        try:
            score = datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            score = datetime.now(timezone.utc).timestamp()
            entry["date"] = datetime.now(timezone.utc).isoformat()

        member = json.dumps(entry)

        pipe = redis_client.pipeline()
        pipe.zadd(key, {member: score})
        # Keep only the last N sessions (highest scores = most recent)
        # After adding new entry, remove oldest entries beyond EPISODIC_MEMORY_MAX_ENTRIES
        pipe.zremrangebyrank(key, 0, -(EPISODIC_MEMORY_MAX_ENTRIES + 1))
        pipe.execute()
    except Exception as e:
        logger.error(f"Episodic memory save error for {student_id}: {e}")


# ── 3. Semantic Memory ────────────────────────
async def save_semantic_memory(student_id: str, data: dict):
    """
    Save persistent facts about the student to Semantic Memory.
    Redis Hash, NO TTL — permanent storage.
    
    Expected fields in `data`:
        identity_traits, learning_style, career_goals,
        mastered_topics, struggling_topics, preferred_analogies,
        life_context, wax_voice_profile
    """
    key = SM_KEY.format(student_id=student_id)
    try:
        pipe = redis_client.pipeline()
        for field, value in data.items():
            pipe.hset(key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
        pipe.execute()
    except Exception as e:
        logger.error(f"Semantic memory save error for {student_id}: {e}")


# ── 4. Procedural Memory ──────────────────────
async def save_procedural_memory(student_id: str, data: dict):
    """
    Save how Wax should interact with this student to Procedural Memory.
    Redis Hash, NO TTL — permanent storage.
    
    Expected fields in `data`:
        explanation_depth, joke_frequency, encouragement_style,
        correction_style, trigger_phrases, motivation_levers
    """
    key = PM_KEY.format(student_id=student_id)
    try:
        pipe = redis_client.pipeline()
        for field, value in data.items():
            pipe.hset(key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
        pipe.execute()
    except Exception as e:
        logger.error(f"Procedural memory save error for {student_id}: {e}")


# ── 5. Observation Memory ───────────────────────
async def save_observation(student_id: str, observation: dict, ttl: int = OBSERVATION_MEMORY_TTL):
    """
    Save a single observation about the student.
    Redis Hash per observation, keyed by content hash. Default 90-day TTL.
    
    Expected fields in `observation`:
        content, category, confidence, valence (-1 to +1),
        arousal (0 to 1), source, date, consolidation_strength
    """
    try:
        # Generate deterministic hash from student_id + content + category
        hash_input = f"{student_id}:{observation.get('content','')}:{observation.get('category','')}"
        fact_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

        key = OM_KEY.format(student_id=student_id, hash=fact_hash)

        # Inject the computed hash into the stored record
        observation["fact_hash"] = fact_hash

        base_thermal = abs(observation.get("valence", 0)) * observation.get("arousal", 0) * 100
        observation["thermal_score"] = observation.get("thermal_score", max(base_thermal, 15))

        # TODO Phase 2: Add thermal decay cron — apply T(t) = T0 × e^(-λt)
        # Decay rates: struggles λ=0.05, victories λ=0.02, routine λ=0.15, sacred λ=0.0

        # Check if key already exists (same hash = same fact)
        existing_raw = redis_client.hgetall(key)
        if existing_raw:
            # Existing observation — append new layer
            existing = {}
            for field, value in existing_raw.items():
                field_str = field.decode("utf-8") if isinstance(field, bytes) else field
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                try:
                    existing[field_str] = json.loads(value_str)
                except json.JSONDecodeError:
                    existing[field_str] = value_str

            # Get existing layers array
            layers = existing.get("layers", [])

            # If old format (flat observation), convert first
            if not layers and existing.get("content"):
                layers = [{
                    "value": existing.get("content"),
                    "date": existing.get("date"),
                    "source": existing.get("source"),
                    "confidence": existing.get("confidence"),
                    "valence": existing.get("valence"),
                    "arousal": existing.get("arousal"),
                    "thermal_score": existing.get("thermal_score", 0),
                }]

            # Append new layer
            new_layer = {
                "value": observation.get("content"),
                "date": observation.get("date"),
                "source": observation.get("source"),
                "confidence": observation.get("confidence"),
                "valence": observation.get("valence", 0),
                "arousal": observation.get("arousal", 0),
                "thermal_score": observation.get("thermal_score", 0),
            }
            layers.append(new_layer)

            # Update the observation with layers
            observation["layers"] = layers
            raw_value = new_layer["value"]
            observation["surface_value"] = str(raw_value) if not isinstance(raw_value, str) else raw_value
            # Carry forward old consolidation strength if converting from flat format
            old_strength = existing.get("consolidation_strength", observation.get("consolidation_strength", 0.5))
            observation["consolidation_strength"] = old_strength + 0.1
        else:
            # First time — create layers array with single entry
            observation["layers"] = [{
                "value": observation.get("content"),
                "date": observation.get("date"),
                "source": observation.get("source"),
                "confidence": observation.get("confidence"),
                "valence": observation.get("valence", 0),
                "arousal": observation.get("arousal", 0),
                "thermal_score": observation.get("thermal_score", 0),
            }]
            content = observation.get("content", "")
            observation["surface_value"] = str(content) if not isinstance(content, str) else content
            observation["consolidation_strength"] = 0.5

        # Remove flat fact fields now stored inside layers array
        for flat_field in ["content", "date", "source", "confidence", "valence", "arousal"]:
            observation.pop(flat_field, None)

        # Write all fields
        pipe = redis_client.pipeline()
        for field, value in observation.items():
            pipe.hset(key, field, json.dumps(value) if not isinstance(value, (str, int, float)) else value)
        pipe.expire(key, ttl)
        pipe.execute()

        return fact_hash
    except Exception as e:
        logger.error(f"Observation save error for {student_id}: {e}")
        return None


# ── Load All Memory ───────────────────────────
async def load_all_memory(student_id: str) -> dict:
    """
    Load all five memory layers for a student and return as a dict.
    
    Returns:
        {
            "working_memory": dict,
            "episodic_memory": list,
            "semantic_memory": dict,
            "procedural_memory": dict,
            "observations": list of dicts
        }
    """
    result = {
        "working_memory": {},
        "episodic_memory": [],
        "semantic_memory": {},
        "procedural_memory": {},
        "observations": []
    }

    # 1. Working Memory
    try:
        key = WM_KEY.format(student_id=student_id)
        raw = redis_client.hgetall(key)
        if raw:
            for field, value in raw.items():
                field_str = field.decode("utf-8") if isinstance(field, bytes) else field
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                try:
                    result["working_memory"][field_str] = json.loads(value_str)
                except json.JSONDecodeError:
                    result["working_memory"][field_str] = value_str
    except Exception as e:
        logger.error(f"Working memory load error for {student_id}: {e}")

    # 2. Episodic Memory
    try:
        key = EM_KEY.format(student_id=student_id)
        raw_entries = redis_client.zrange(key, -EPISODIC_MEMORY_MAX_ENTRIES, -1)
        for entry in raw_entries:
            entry_str = entry.decode("utf-8") if isinstance(entry, bytes) else entry
            try:
                result["episodic_memory"].append(json.loads(entry_str))
            except json.JSONDecodeError:
                logger.warning(f"Corrupted episodic entry for {student_id}, skipping")
    except Exception as e:
        logger.error(f"Episodic memory load error for {student_id}: {e}")

    # 3. Semantic Memory
    try:
        key = SM_KEY.format(student_id=student_id)
        raw = redis_client.hgetall(key)
        if raw:
            for field, value in raw.items():
                field_str = field.decode("utf-8") if isinstance(field, bytes) else field
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                try:
                    result["semantic_memory"][field_str] = json.loads(value_str)
                except json.JSONDecodeError:
                    result["semantic_memory"][field_str] = value_str
    except Exception as e:
        logger.error(f"Semantic memory load error for {student_id}: {e}")

    # 4. Procedural Memory
    try:
        key = PM_KEY.format(student_id=student_id)
        raw = redis_client.hgetall(key)
        if raw:
            for field, value in raw.items():
                field_str = field.decode("utf-8") if isinstance(field, bytes) else field
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                try:
                    result["procedural_memory"][field_str] = json.loads(value_str)
                except json.JSONDecodeError:
                    result["procedural_memory"][field_str] = value_str
    except Exception as e:
        logger.error(f"Procedural memory load error for {student_id}: {e}")

    # 5. Observation Memory
    try:
        # Scan for all observation keys matching the pattern
        pattern = f"wax:om:{student_id}:*"
        cursor = 0
        observation_keys = []
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                observation_keys.extend(keys)
            if cursor == 0:
                break

        for obs_key in observation_keys:
            raw = redis_client.hgetall(obs_key)
            if raw:
                observation = {}
                for field, value in raw.items():
                    field_str = field.decode("utf-8") if isinstance(field, bytes) else field
                    value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                    try:
                        observation[field_str] = json.loads(value_str)
                    except json.JSONDecodeError:
                        observation[field_str] = value_str
                result["observations"].append(observation)
    except Exception as e:
        logger.error(f"Observation memory load error for {student_id}: {e}")

    # TODO Phase 3: Add thermal-weighted top-N filtering.
    # Currently returns all observations — fine for Phase 1 with low counts.
    # Future: score by (semantic_similarity × 0.4) + (thermal_score × 0.35) + (recency × 0.25)

    return result
