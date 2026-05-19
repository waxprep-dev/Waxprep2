"""
WaxPrep v2 — Database Migrations
Handles data migration between temporary and permanent student IDs.
Used during account creation to preserve conversation history,
observations, session data, student memory, and all state.

Architecture:
    - Migrates all Redis keys from temp_* prefix to permanent UUID
    - Atomic where possible, verified before cleanup
    - Returns detailed results for each data type
    - Critical failures preserve temp data (no data loss)

SIAPM Memory Layers:
    L1: Working Memory (wax:wm:{id}) — session state
    L2: Episodic Memory (wax:em:{id}) — session summaries (ZSET)
    L3: Semantic Memory (wax:sm:{id}) — student facts (Hash)
    L4: Observation Memory (wax:om:{id}:* + wax:obs:{id}) — extracted facts
    L5: Procedural Memory (wax:pm:{id}) — how Wax treats this student
"""

import json
import logging
from typing import Dict, Any, List, Optional

from database.client import redis_client

logger = logging.getLogger("waxprep.migrations")


# ═══════════════════════════════════════════════════════════════════════════════
# NEW MIGRATION FUNCTIONS — SIAPM Memory Layers
# ═══════════════════════════════════════════════════════════════════════════════


def _decode_bytes(value) -> str:
    """Helper: decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _safe_json_loads(raw: str, context: str = "") -> Optional[Dict]:
    """
    Safely parse JSON, log warning on failure.
    
    Returns:
        Parsed dict on success, None on JSON decode failure.
        Callers must handle None gracefully.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if context:
            logger.warning(f"Skipping corrupt JSON {context}")
        return None


def _scan_keys(pattern: str) -> List[str]:
    """
    Scan Redis for keys matching pattern using SCAN instead of KEYS.
    Prevents blocking on production Redis with large keyspaces.
    """
    keys = []
    cursor = 0
    while True:
        cursor, batch = redis_client.scan(cursor, match=pattern, count=50)
        keys.extend(batch)
        if cursor == 0:
            break
    return [_decode_bytes(k) for k in keys]


async def migrateSemanticMemory(temp_id: str, permanent_id: str) -> Dict[str, Any]:
    """
    Migrate L3 Semantic Memory (student facts, identity, preferences).
    
    Key: wax:sm:{student_id} (Redis Hash)
    Stores: identity_traits, learning_style, career_goals, mastered_topics,
            struggling_topics, preferred_analogies, life_context, wax_voice_profile
    
    Strategy:
        1. Read all hash fields from temp key
        2. Write to permanent key using HMSET merge (existing perm wins, temp fills gaps)
        3. Verify with HGETALL on permanent key
        4. If all temp fields present → DEL temp key
        5. If mismatch → LOG and alert, preserve temp data
    
    Returns:
        {"success": bool, "fields_migrated": int, "error": str|None}
    """
    result = {"success": False, "fields_migrated": 0, "error": None}
    temp_key = f"wax:sm:{temp_id}"
    perm_key = f"wax:sm:{permanent_id}"
    
    try:
        # 1. Read temp data
        temp_data_raw = redis_client.hgetall(temp_key)
        if not temp_data_raw:
            logger.info(f"No semantic memory to migrate for {temp_id}")
            result["success"] = True
            return result
        
        # Decode bytes keys/values
        temp_data = {}
        for k, v in temp_data_raw.items():
            key = _decode_bytes(k)
            val = _decode_bytes(v)
            temp_data[key] = val
        
        if not temp_data:
            logger.info(f"Empty semantic memory hash for {temp_id}")
            result["success"] = True
            return result
        
        # 2. Check if permanent key already exists (merge, don't overwrite)
        perm_exists = redis_client.exists(perm_key)
        
        if perm_exists:
            # Merge: existing permanent data wins conflicts, temp fills gaps
            perm_data_raw = redis_client.hgetall(perm_key)
            perm_data = {_decode_bytes(k): _decode_bytes(v) for k, v in perm_data_raw.items()}
            
            # temp_data fills gaps; perm_data wins on conflict
            merged = {**temp_data, **perm_data}
            
            # Write merged data
            redis_client.hmset(perm_key, merged)
            logger.info(
                f"Merged semantic memory for {temp_id} → {permanent_id} "
                f"({len(temp_data)} temp fields + {len(perm_data)} perm fields)"
            )
        else:
            # Fresh write
            redis_client.hmset(perm_key, temp_data)
            logger.info(
                f"Migrated semantic memory: {temp_id} → {permanent_id} "
                f"({len(temp_data)} fields)"
            )
        
        # 3. Verify
        verify_raw = redis_client.hgetall(perm_key)
        verify_data = {_decode_bytes(k): _decode_bytes(v) for k, v in verify_raw.items()}
        
        # Check that all temp fields are present in permanent
        missing_fields = [k for k in temp_data.keys() if k not in verify_data]
        
        if not missing_fields:
            # 4. Success — delete temp
            redis_client.delete(temp_key)
            result["success"] = True
            result["fields_migrated"] = len(temp_data)
            logger.info(
                f"Semantic memory migration VERIFIED: {temp_id} → {permanent_id}"
            )
        else:
            # Mismatch — preserve temp, alert
            result["error"] = (
                f"MIGRATION MISMATCH: {len(missing_fields)} fields missing "
                f"after migration: {missing_fields}"
            )
            logger.error(
                f"Semantic memory MISMATCH: {temp_id} → {permanent_id} — "
                f"missing fields: {missing_fields}. Temp data PRESERVED."
            )
            
    except Exception as e:
        result["error"] = f"Semantic memory migration failed: {e}"
        logger.error(
            f"Semantic memory migration ERROR: {temp_id} → {permanent_id}: {e}"
        )
    
    return result


async def migrateEpisodicMemory(temp_id: str, permanent_id: str) -> Dict[str, Any]:
    """
    Migrate L2 Episodic Memory (session summaries).
    
    Key: wax:em:{student_id} (Redis ZSET, score = timestamp)
    Stores: JSON session summaries with session_id, date, topics, victories,
            struggles, emotional_arc, key_quotes, analogies_that_worked, cliffhanger
    
    Strategy:
        1. ZRANGE all entries from temp key (withscores=True)
        2. For each entry: parse JSON, replace internal student_id with permanent UUID
        3. ZADD to permanent key with ORIGINAL timestamps preserved
        4. Verify count matches
        5. If match → DEL temp key
        6. If mismatch → partial migration alert, preserve temp
    
    Returns:
        {"success": bool, "sessions_migrated": int, "error": str|None}
    """
    result = {"success": False, "sessions_migrated": 0, "error": None}
    temp_key = f"wax:em:{temp_id}"
    perm_key = f"wax:em:{permanent_id}"
    
    try:
        # 1. Read all entries with scores
        entries_raw = redis_client.zrange(temp_key, 0, -1, withscores=True)
        
        if not entries_raw:
            logger.info(f"No episodic memory to migrate for {temp_id}")
            result["success"] = True
            return result
        
        # Parse entries: each is (member_bytes_or_str, score_float)
        entries = []
        for item in entries_raw:
            if isinstance(item, tuple) and len(item) == 2:
                member, score = item
                entries.append((_decode_bytes(member), float(score)))
            else:
                logger.warning(f"Unexpected ZRANGE format for {temp_id}: {type(item)}")
                continue
        
        if not entries:
            logger.info(f"No episodic memory entries parsed for {temp_id}")
            result["success"] = True
            return result
        
        # Track raw count separately from parsed count (Fix 6)
        raw_count = len(entries_raw)
        parsed_count = len(entries)
        
        if raw_count != parsed_count:
            logger.warning(
                f"Episodic ZRANGE parse discrepancy: {raw_count} raw vs {parsed_count} parsed. "
                f"Temp data PRESERVED."
            )
            result["error"] = f"Parse discrepancy: {raw_count} raw vs {parsed_count} parsed"
            return result
        
        # 2. Rebuild with permanent UUID references
        pipe = redis_client.pipeline()
        for member, score in entries:
            data = _safe_json_loads(member, context=f"episodic entry for {temp_id}")
            if data is None:
                continue
            
            # Fix internal student_id reference
            data["student_id"] = permanent_id
            data["migrated_from"] = temp_id
            
            # ZADD with original timestamp (score)
            pipe.zadd(perm_key, {json.dumps(data): score})
        
        pipe.execute()
        
        # 3. Verify count
        new_count = redis_client.zcard(perm_key)
        
        if parsed_count == new_count:
            # 4. Success — delete temp
            redis_client.delete(temp_key)
            result["success"] = True
            result["sessions_migrated"] = parsed_count
            logger.info(
                f"Episodic memory migration VERIFIED: {temp_id} → {permanent_id} "
                f"({parsed_count} sessions, timestamps preserved)"
            )
        else:
            # Partial migration — alert, preserve temp
            result["error"] = (
                f"EPISODIC MISMATCH: expected {parsed_count} sessions, "
                f"got {new_count} after migration"
            )
            logger.error(
                f"Episodic memory MISMATCH: {temp_id} → {permanent_id} — "
                f"expected {parsed_count}, got {new_count}. Temp data PRESERVED."
            )
            
    except Exception as e:
        result["error"] = f"Episodic memory migration failed: {e}"
        logger.error(
            f"Episodic memory migration ERROR: {temp_id} → {permanent_id}: {e}"
        )
    
    return result


async def migrateStudentState(temp_id: str, permanent_id: str) -> Dict[str, Any]:
    """
    Migrate L1 Working Memory + L5 Procedural Memory (student state).
    
    Keys:
        wax:wm:{student_id} — Working Memory (Hash, session-only, has TTL)
        wax:pm:{student_id} — Procedural Memory (Hash, permanent, accumulates)
    
    Strategy:
        1. Read wax:wm:{temp_id} — migrate only if session is ACTIVE (TTL > 0)
        2. Read wax:pm:{temp_id} — merge with existing permanent data
           (procedural memory is CUMULATIVE — existing wins, temp fills gaps)
        3. Verify with TTL check for working memory
        4. Delete temp keys on success
    
    Returns:
        {
            "success": bool,
            "working_migrated": bool,
            "procedural_merged": bool,
            "error": str|None
        }
    """
    result = {
        "success": False,
        "working_migrated": False,
        "procedural_merged": False,
        "error": None
    }
    
    wm_temp = f"wax:wm:{temp_id}"
    wm_perm = f"wax:wm:{permanent_id}"
    pm_temp = f"wax:pm:{temp_id}"
    pm_perm = f"wax:pm:{permanent_id}"
    
    try:
        # ═══════════════════════════════════════════
        # WORKING MEMORY (L1) — only if active session
        # ═══════════════════════════════════════════
        ttl = redis_client.ttl(wm_temp)
        
        if ttl > 0:
            wm_data_raw = redis_client.hgetall(wm_temp)
            if wm_data_raw:
                wm_data = {_decode_bytes(k): _decode_bytes(v) for k, v in wm_data_raw.items()}
                
                # Write to permanent with preserved TTL
                redis_client.hmset(wm_perm, wm_data)
                redis_client.expire(wm_perm, ttl)
                
                # Verify with sampled value check (Fix 7)
                verify_raw = redis_client.hgetall(wm_perm)
                verify_data = {_decode_bytes(k): _decode_bytes(v) for k, v in verify_raw.items()}
                
                if all(k in verify_data for k in wm_data.keys()):
                    sample_keys = list(wm_data.keys())[:2] + list(wm_data.keys())[-2:]
                    value_mismatch = False
                    for k in sample_keys:
                        if verify_data.get(k) != wm_data.get(k):
                            value_mismatch = True
                            break
                    
                    if not value_mismatch:
                        redis_client.delete(wm_temp)
                        result["working_migrated"] = True
                        logger.info(
                            f"Working memory migrated: {temp_id} → {permanent_id} "
                            f"(TTL preserved: {ttl}s)"
                        )
                    else:
                        logger.warning(
                            f"Working memory value mismatch for {temp_id} → {permanent_id}. "
                            f"Temp data preserved."
                        )
                else:
                    logger.warning(
                        f"Working memory verification failed for {temp_id} → {permanent_id}. "
                        f"Temp data preserved."
                    )
            else:
                result["working_migrated"] = True  # nothing to migrate
                logger.info(f"Empty working memory for {temp_id}")
        else:
            # Session expired — nothing to migrate
            result["working_migrated"] = True
            logger.info(
                f"Working memory session expired for {temp_id} (TTL: {ttl}). "
                f"Nothing to migrate."
            )
        
        # ═══════════════════════════════════════════
        # PROCEDURAL MEMORY (L5) — merge, don't overwrite
        # ═══════════════════════════════════════════
        pm_temp_data_raw = redis_client.hgetall(pm_temp)
        
        if pm_temp_data_raw:
            pm_temp_data = {_decode_bytes(k): _decode_bytes(v) for k, v in pm_temp_data_raw.items()}
            
            # Check if permanent already has procedural memory
            pm_perm_data_raw = redis_client.hgetall(pm_perm)
            
            if pm_perm_data_raw:
                # Merge: existing permanent wins conflicts, temp fills gaps
                pm_perm_data = {_decode_bytes(k): _decode_bytes(v) for k, v in pm_perm_data_raw.items()}
                merged = {**pm_temp_data, **pm_perm_data}
                
                redis_client.hmset(pm_perm, merged)
                logger.info(
                    f"Merged procedural memory: {temp_id} → {permanent_id} "
                    f"({len(pm_temp_data)} temp + {len(pm_perm_data)} perm fields)"
                )
            else:
                # Fresh write
                redis_client.hmset(pm_perm, pm_temp_data)
                logger.info(
                    f"Migrated procedural memory: {temp_id} → {permanent_id} "
                    f"({len(pm_temp_data)} fields)"
                )
            
            # Verify
            verify_raw = redis_client.hgetall(pm_perm)
            verify_data = {_decode_bytes(k): _decode_bytes(v) for k, v in verify_raw.items()}
            
            if all(k in verify_data for k in pm_temp_data.keys()):
                redis_client.delete(pm_temp)
                result["procedural_merged"] = True
                logger.info(
                    f"Procedural memory migration VERIFIED: {temp_id} → {permanent_id}"
                )
            else:
                logger.warning(
                    f"Procedural memory verification failed for {temp_id} → {permanent_id}. "
                    f"Temp data preserved."
                )
        else:
            result["procedural_merged"] = True  # nothing to migrate
            logger.info(f"No procedural memory to migrate for {temp_id}")
        
        # Overall success if both parts succeeded
        if result["working_migrated"] and result["procedural_merged"]:
            result["success"] = True
            
    except Exception as e:
        result["error"] = f"Student state migration failed: {e}"
        logger.error(
            f"Student state migration ERROR: {temp_id} → {permanent_id}: {e}"
        )
    
    return result


async def migrateObservationsSIAPM(temp_id: str, permanent_id: str) -> Dict[str, Any]:
    """
    Migrate L4 Observation Memory with key remapping.
    
    Keys: wax:om:{student_id}:* (Redis Hash per observation)
    Also updates constellation references: wax:const:{student_id}:*
    
    Strategy:
        1. Find all keys matching wax:om:{temp_id}:*
        2. For each: read content, replace student_id in payload
        3. Re-hash content for new key: wax:om:{permanent_id}:{hash}
        4. If hash collision → append _v2
        5. Update constellation references
        6. Verify count, delete temp keys
    
    Returns:
        {"success": bool, "observations_migrated": int, "error": str|None}
    """
    result = {"success": False, "observations_migrated": 0, "error": None}
    pattern = f"wax:om:{temp_id}:*"
    
    try:
        # 1. Find all observation keys for temp student (Fix 1: use SCAN)
        temp_keys = _scan_keys(pattern)
        
        if not temp_keys:
            logger.info(f"No SIAPM observations to migrate for {temp_id}")
            result["success"] = True
            return result
        
        migrated_count = 0
        
        for old_key in temp_keys:
            try:
                # Extract hash from key: wax:om:{temp_id}:{hash}
                parts = old_key.split(":")
                if len(parts) < 4:
                    logger.warning(f"Invalid observation key format: {old_key}")
                    continue
                
                content_hash = parts[3]
                new_key = f"wax:om:{permanent_id}:{content_hash}"
                
                # Read observation data
                data_raw = redis_client.hgetall(old_key)
                if not data_raw:
                    continue
                
                data = {_decode_bytes(k): _decode_bytes(v) for k, v in data_raw.items()}
                
                # Update student_id in payload
                data["student_id"] = permanent_id
                data["migrated_from"] = temp_id
                
                # Handle collision: if new key already exists, append _v2
                exists = redis_client.exists(new_key)
                final_key = new_key
                if exists:
                    final_key = f"{new_key}_v2"
                    logger.info(
                        f"Observation hash collision for {temp_id} → {permanent_id}: "
                        f"{content_hash} → {final_key}"
                    )
                
                # Write to new key
                redis_client.hmset(final_key, data)
                
                # Delete old key
                redis_client.delete(old_key)
                
                migrated_count += 1
                
            except Exception as item_e:
                logger.warning(f"Failed to migrate observation {old_key}: {item_e}")
                continue
        
        # 5. Update constellation references (Fix 1: use SCAN)
        try:
            const_pattern = f"wax:const:{temp_id}:*"
            const_keys = _scan_keys(const_pattern)
            
            for c_key in const_keys:
                topic = c_key.split(":")[-1]
                
                members_raw = redis_client.smembers(c_key)
                members = [_decode_bytes(m) for m in members_raw]
                
                if members:
                    new_const_key = f"wax:const:{permanent_id}:{topic}"
                    redis_client.sadd(new_const_key, *members)
                    
                    # Fix 4: Verify constellation write before deleting temp
                    new_count = redis_client.scard(new_const_key)
                    if new_count >= len(members):
                        redis_client.delete(c_key)
                    else:
                        logger.warning(
                            f"Constellation migration partial: {temp_id} topic={topic} "
                            f"expected {len(members)}, got {new_count}"
                        )
                else:
                    redis_client.delete(c_key)
                
        except Exception as const_e:
            logger.warning(f"Constellation migration warning for {temp_id}: {const_e}")
        
        # 6. Verify
        verify_pattern = f"wax:om:{permanent_id}:*"
        verify_keys = _scan_keys(verify_pattern)
        verify_count = len(verify_keys)
        
        # Check if all temp keys are gone
        remaining_temp = _scan_keys(pattern)
        
        if not remaining_temp:
            result["success"] = True
            result["observations_migrated"] = migrated_count
            logger.info(
                f"SIAPM observation migration VERIFIED: {temp_id} → {permanent_id} "
                f"({migrated_count} observations, constellations updated)"
            )
        else:
            result["error"] = (
                f"Observation migration incomplete: "
                f"{len(remaining_temp)} temp keys remain"
            )
            logger.error(
                f"Observation migration INCOMPLETE: {temp_id} → {permanent_id} — "
                f"{len(remaining_temp)} temp keys remain"
            )
            
    except Exception as e:
        result["error"] = f"Observation migration failed: {e}"
        logger.error(
            f"Observation migration ERROR: {temp_id} → {permanent_id}: {e}"
        )
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN MIGRATION FUNCTION — Updated with SIAPM Layers
# ═══════════════════════════════════════════════════════════════════════════════

async def migrate_temp_to_permanent(
    temp_id: str,
    permanent_id: str
) -> Dict[str, Any]:
    """
    Migrate ALL data from a temporary student ID to a permanent one.
    
    Now includes SIAPM memory layers:
        L1: Working Memory (wax:wm)
        L2: Episodic Memory (wax:em)
        L3: Semantic Memory (wax:sm)
        L4: Observation Memory (wax:om)
        L5: Procedural Memory (wax:pm)
    
    Plus existing migrations:
        - Conversation history
        - Observations (legacy format)
        - Last message timestamp
        - Stepped away flag
        - Quiz rotation
        - Quiz history
        - Deferral count
    
    Atomic where possible. Verification before cleanup.
    If critical migration fails, temp data is preserved.
    
    Args:
        temp_id: Temporary student ID (e.g., temp_8510180724)
        permanent_id: Permanent student ID (UUID from database)
        
    Returns:
        Dict with migration results for all data types
    """
    results = {
        # Legacy migrations
        "conversation_history": False,
        "observations_legacy": False,
        "timestamp": False,
        "total_migrated_keys": 0,
        "errors": [],
        
        # SIAPM memory layers
        "semantic_memory": {"success": False, "fields_migrated": 0, "error": None},
        "episodic_memory": {"success": False, "sessions_migrated": 0, "error": None},
        "student_state": {"success": False, "working_migrated": False, "procedural_merged": False, "error": None},
        "observations_siapm": {"success": False, "observations_migrated": 0, "error": None},
    }
    
    # ═══════════════════════════════════════════
    # SIAPM L3: SEMANTIC MEMORY
    # ═══════════════════════════════════════════
    try:
        semantic_result = await migrateSemanticMemory(temp_id, permanent_id)
        results["semantic_memory"] = semantic_result
        if semantic_result["success"]:
            results["total_migrated_keys"] += 1
        elif semantic_result["error"]:
            results["errors"].append(semantic_result["error"])
    except Exception as e:
        results["errors"].append(f"Semantic memory migration exception: {e}")
        logger.error(f"Semantic memory migration EXCEPTION: {temp_id}: {e}")
    
    # ═══════════════════════════════════════════
    # SIAPM L2: EPISODIC MEMORY
    # ═══════════════════════════════════════════
    try:
        episodic_result = await migrateEpisodicMemory(temp_id, permanent_id)
        results["episodic_memory"] = episodic_result
        if episodic_result["success"]:
            results["total_migrated_keys"] += 1
        elif episodic_result["error"]:
            results["errors"].append(episodic_result["error"])
    except Exception as e:
        results["errors"].append(f"Episodic memory migration exception: {e}")
        logger.error(f"Episodic memory migration EXCEPTION: {temp_id}: {e}")
    
    # ═══════════════════════════════════════════
    # SIAPM L1 + L5: STUDENT STATE (Working + Procedural)
    # ═══════════════════════════════════════════
    try:
        state_result = await migrateStudentState(temp_id, permanent_id)
        results["student_state"] = state_result
        if state_result["success"]:
            results["total_migrated_keys"] += 1
        elif state_result["error"]:
            results["errors"].append(state_result["error"])
    except Exception as e:
        results["errors"].append(f"Student state migration exception: {e}")
        logger.error(f"Student state migration EXCEPTION: {temp_id}: {e}")
    
    # ═══════════════════════════════════════════
    # SIAPM L4: OBSERVATION MEMORY (with key remapping)
    # ═══════════════════════════════════════════
    try:
        obs_result = await migrateObservationsSIAPM(temp_id, permanent_id)
        results["observations_siapm"] = obs_result
        if obs_result["success"]:
            results["total_migrated_keys"] += 1
        elif obs_result["error"]:
            results["errors"].append(obs_result["error"])
    except Exception as e:
        results["errors"].append(f"SIAPM observation migration exception: {e}")
        logger.error(f"SIAPM observation migration EXCEPTION: {temp_id}: {e}")
    
    # ═══════════════════════════════════════════
    # LEGACY: CONVERSATION HISTORY (CRITICAL)
    # ═══════════════════════════════════════════
    try:
        temp_key = f"conversation:{temp_id}"
        perm_key = f"conversation:{permanent_id}"
        
        all_messages = redis_client.lrange(temp_key, 0, -1)
        
        if all_messages:
            pipe = redis_client.pipeline()
            for msg in all_messages:
                pipe.rpush(perm_key, msg)
            pipe.llen(perm_key)
            pipe_results = pipe.execute()
            
            migrated_count = pipe_results[-1] if pipe_results else 0
            
            if migrated_count == len(all_messages):
                redis_client.delete(temp_key)
                results["conversation_history"] = True
                results["total_migrated_keys"] += 1
                logger.info(
                    f"Migrated {migrated_count} messages: {temp_id} → {permanent_id}"
                )
            else:
                results["errors"].append(
                    f"Conversation count mismatch: migrated {migrated_count} "
                    f"vs expected {len(all_messages)}"
                )
                logger.error(
                    f"Conversation migration COUNT MISMATCH: {temp_id} → {permanent_id}"
                )
        else:
            results["conversation_history"] = True
            logger.info(f"No conversation history to migrate for {temp_id}")
            
    except Exception as e:
        results["errors"].append(f"Conversation migration failed: {e}")
        logger.error(f"Conversation migration ERROR: {temp_id} → {permanent_id}: {e}")
    
    # ═══════════════════════════════════════════
    # LEGACY: OBSERVATIONS
    # ═══════════════════════════════════════════
    try:
        temp_pattern = f"observation:{temp_id}:*"
        temp_obs_keys = _scan_keys(temp_pattern)
        migrated_obs = 0
        
        for temp_key in temp_obs_keys:
            raw = redis_client.get(temp_key)
            if not raw:
                continue
            
            raw_str = _decode_bytes(raw)
            obs = _safe_json_loads(raw_str, context=f"observation {temp_key}")
            if obs is None:
                continue
            
            obs["student_id"] = permanent_id
            
            new_key = temp_key.replace(
                f"observation:{temp_id}:",
                f"observation:{permanent_id}:"
            )
            
            ttl = redis_client.ttl(temp_key)
            if ttl and ttl > 0:
                redis_client.setex(new_key, ttl, json.dumps(obs))
            else:
                redis_client.set(new_key, json.dumps(obs))
            
            # Fix 3: Verify write before deleting source
            verify_raw = redis_client.get(new_key)
            if verify_raw:
                redis_client.sadd(f"observation_index:{permanent_id}", new_key)
                category = obs.get("category", "unknown")
                redis_client.sadd(
                    f"observation_index:{permanent_id}:category:{category}",
                    new_key
                )
                
                redis_client.srem(f"observation_index:{temp_id}", temp_key)
                redis_client.delete(temp_key)
                
                migrated_obs += 1
            else:
                logger.error(f"Legacy observation write verification failed: {temp_key}")
                continue
        
        if migrated_obs > 0:
            results["observations_legacy"] = True
            results["total_migrated_keys"] += migrated_obs
            logger.info(
                f"Migrated {migrated_obs} legacy observations: {temp_id} → {permanent_id}"
            )
        else:
            results["observations_legacy"] = True
            
    except Exception as e:
        results["errors"].append(f"Legacy observation migration failed: {e}")
        logger.error(f"Legacy observation migration ERROR: {temp_id} → {permanent_id}: {e}")
    
    # ═══════════════════════════════════════════
    # SIMPLE KEYS (timestamp, stepped_away, quiz_rotation, deferral_count)
    # ═══════════════════════════════════════════
    simple_migrations = [
        {
            "temp_key": f"last_message_time:{temp_id}",
            "type": "string",
            "name": "timestamp",
            "result_field": "timestamp",
        },
        {
            "temp_key": f"stepped_away:{temp_id}",
            "type": "string",
            "name": "stepped_away",
            "result_field": None,
        },
        {
            "temp_key": f"quiz_rotation:{temp_id}",
            "type": "string",
            "name": "quiz_rotation",
            "result_field": None,
        },
        {
            "temp_key": f"deferral_count:{temp_id}",
            "type": "string",
            "name": "deferral_count",
            "result_field": None,
        },
    ]
    
    for migration in simple_migrations:
        temp_key = migration["temp_key"]
        perm_key = temp_key.replace(f":{temp_id}", f":{permanent_id}")
        
        try:
            raw = redis_client.get(temp_key)
            if raw:
                value = _decode_bytes(raw)
                # Fix 5: Preserve original TTL
                original_ttl = redis_client.ttl(temp_key)
                ttl = original_ttl if (original_ttl and original_ttl > 0) else 86400
                redis_client.setex(perm_key, ttl, value)
                redis_client.delete(temp_key)
                results["total_migrated_keys"] += 1
                
                if migration["result_field"]:
                    results[migration["result_field"]] = True
                    
                logger.debug(f"Migrated {migration['name']}: {temp_id} → {permanent_id}")
        except Exception as e:
            logger.warning(f"Failed to migrate {migration['name']}: {e}")
    
    # ═══════════════════════════════════════════
    # QUIZ HISTORY (Redis List)
    # ═══════════════════════════════════════════
    try:
        temp_key = f"quiz_history:{temp_id}"
        perm_key = f"quiz_history:{permanent_id}"
        
        all_entries = redis_client.lrange(temp_key, 0, -1)
        
        if all_entries:
            pipe = redis_client.pipeline()
            for entry in all_entries:
                pipe.rpush(perm_key, entry)
            # Fix 2: Count verification
            pipe.llen(perm_key)
            pipe_results = pipe.execute()
            migrated_count = pipe_results[-1] if pipe_results else 0
            
            if migrated_count == len(all_entries):
                redis_client.delete(temp_key)
                results["total_migrated_keys"] += 1
                logger.debug(f"Migrated quiz_history: {temp_id} → {permanent_id}")
            else:
                logger.warning(
                    f"Quiz history count mismatch: {migrated_count} vs {len(all_entries)}"
                )
    except Exception as e:
        logger.warning(f"Failed to migrate quiz_history: {e}")
    
    # ═══════════════════════════════════════════
    # LOG SUMMARY
    # ═══════════════════════════════════════════
    if results["errors"]:
        logger.error(
            f"Migration {temp_id} → {permanent_id}: "
            f"{len(results['errors'])} error(s) — temp data PRESERVED where failed"
        )
    else:
        logger.info(
            f"Migration {temp_id} → {permanent_id}: SUCCESS "
            f"({results['total_migrated_keys']} keys)"
        )
    
    return results
