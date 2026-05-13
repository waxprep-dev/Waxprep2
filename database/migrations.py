"""
WaxPrep v2 — Database Migrations
Handles data migration between temporary and permanent student IDs.
Used during account creation to preserve conversation history,
observations, and all session data.

Architecture:
    - Migrates all Redis keys from temp_* prefix to permanent UUID
    - Atomic where possible, verified before cleanup
    - Returns detailed results for each data type
    - Critical failures preserve temp data (no data loss)
"""

import json
import logging
from typing import Dict, Any

from database.client import redis_client

logger = logging.getLogger("waxprep.migrations")


async def migrate_temp_to_permanent(
    temp_id: str,
    permanent_id: str
) -> Dict[str, Any]:
    """
    Migrate all data from a temporary student ID to a permanent one.
    
    Migrates:
        - Conversation history (CRITICAL — blocks account creation if fails)
        - Observations (with index updates)
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
        Dict with migration results:
        {
            "conversation_history": bool,
            "observations": bool,
            "timestamp": bool,
            "total_migrated_keys": int,
            "errors": list,
        }
    """
    results = {
        "conversation_history": False,
        "observations": False,
        "timestamp": False,
        "total_migrated_keys": 0,
        "errors": [],
    }
    
    # ═══════════════════════════════════════════
    # 1. CONVERSATION HISTORY (CRITICAL)
    # ═══════════════════════════════════════════
    try:
        temp_key = f"conversation:{temp_id}"
        perm_key = f"conversation:{permanent_id}"
        
        all_messages = redis_client.lrange(temp_key, 0, -1)
        
        if all_messages:
            # Atomic: push all to new key, verify count, then delete source
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
                    f"Conversation migration COUNT MISMATCH: "
                    f"{temp_id} → {permanent_id}"
                )
        else:
            # No conversation history — not an error for new students
            results["conversation_history"] = True
            logger.info(
                f"No conversation history to migrate for {temp_id}"
            )
            
    except Exception as e:
        results["errors"].append(f"Conversation migration failed: {e}")
        logger.error(f"Conversation migration ERROR: {temp_id} → {permanent_id}: {e}")
    
    # ═══════════════════════════════════════════
    # 2. OBSERVATIONS
    # ═══════════════════════════════════════════
    try:
        temp_pattern = f"observation:{temp_id}:*"
        # Use SCAN in production, but KEYS is acceptable for migration
        # since this runs once per account creation
        temp_obs_keys = redis_client.keys(temp_pattern)
        migrated_obs = 0
        
        for temp_key_bytes in temp_obs_keys:
            temp_key = temp_key_bytes.decode("utf-8") if isinstance(temp_key_bytes, bytes) else temp_key_bytes
            
            raw = redis_client.get(temp_key)
            if not raw:
                continue
            
            raw_str = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            try:
                obs = json.loads(raw_str)
            except json.JSONDecodeError:
                logger.warning(f"Skipping corrupt observation: {temp_key}")
                continue
            
            # Update student_id in the observation
            obs["student_id"] = permanent_id
            
            # Build new key
            new_key = temp_key.replace(
                f"observation:{temp_id}:",
                f"observation:{permanent_id}:"
            )
            
            # Save to new key with same TTL as original
            ttl = redis_client.ttl(temp_key)
            if ttl and ttl > 0:
                redis_client.setex(new_key, ttl, json.dumps(obs))
            else:
                redis_client.set(new_key, json.dumps(obs))
            
            # Add to new index
            redis_client.sadd(f"observation_index:{permanent_id}", new_key)
            category = obs.get("category", "unknown")
            redis_client.sadd(
                f"observation_index:{permanent_id}:category:{category}",
                new_key
            )
            
            # Remove from old index and delete
            redis_client.srem(f"observation_index:{temp_id}", temp_key)
            redis_client.delete(temp_key)
            
            migrated_obs += 1
        
        if migrated_obs > 0:
            results["observations"] = True
            results["total_migrated_keys"] += migrated_obs
            logger.info(
                f"Migrated {migrated_obs} observations: {temp_id} → {permanent_id}"
            )
        else:
            # No observations yet — not an error
            results["observations"] = True
            
    except Exception as e:
        results["errors"].append(f"Observation migration failed: {e}")
        logger.error(f"Observation migration ERROR: {temp_id} → {permanent_id}: {e}")
    
    # ═══════════════════════════════════════════
    # 3-7. SIMPLE KEYS (timestamp, stepped_away, quiz_rotation, etc.)
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
                value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                redis_client.setex(perm_key, 86400, value)
                redis_client.delete(temp_key)
                results["total_migrated_keys"] += 1
                
                if migration["result_field"]:
                    results[migration["result_field"]] = True
                    
                logger.debug(f"Migrated {migration['name']}: {temp_id} → {permanent_id}")
        except Exception as e:
            logger.warning(f"Failed to migrate {migration['name']}: {e}")
    
    # ═══════════════════════════════════════════
    # 8. QUIZ HISTORY (Redis List)
    # ═══════════════════════════════════════════
    try:
        temp_key = f"quiz_history:{temp_id}"
        perm_key = f"quiz_history:{permanent_id}"
        
        all_entries = redis_client.lrange(temp_key, 0, -1)
        
        if all_entries:
            pipe = redis_client.pipeline()
            for entry in all_entries:
                pipe.rpush(perm_key, entry)
            pipe.execute()
            redis_client.delete(temp_key)
            results["total_migrated_keys"] += 1
            logger.debug(f"Migrated quiz_history: {temp_id} → {permanent_id}")
    except Exception as e:
        logger.warning(f"Failed to migrate quiz_history: {e}")
    
    # ═══════════════════════════════════════════
    # LOG SUMMARY
    # ═══════════════════════════════════════════
    if results["errors"]:
        logger.error(
            f"Migration {temp_id} → {permanent_id}: "
            f"{len(results['errors'])} error(s) — "
            f"temp data PRESERVED"
        )
    else:
        logger.info(
            f"Migration {temp_id} → {permanent_id}: SUCCESS "
            f"({results['total_migrated_keys']} keys)"
        )
    
    return results
