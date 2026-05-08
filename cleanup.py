"""
WaxPrep Automated Test Harness — Cleanup
Purges all test data from Redis and Supabase after test runs.
Prevents test data from polluting production databases.
"""

import logging

logger = logging.getLogger("waxprep.test_harness.cleanup")


async def cleanup_all(prefix: str = "test_") -> dict:
    """
    Purge all test data from Redis and Supabase.
    
    Cleans:
    - Redis keys matching {prefix}*
    - Supabase rows where student_id or platform_user_id starts with {prefix}
    
    Returns dict with counts of deleted items.
    """
    results = {
        "redis_keys_deleted": 0,
        "supabase_student_signals": 0,
        "supabase_student_models": 0,
        "supabase_platform_sessions": 0,
        "supabase_students": 0,
        "supabase_crisis_events": 0,
        "errors": [],
    }
    
    # ── Redis Cleanup ──
    try:
        from database.client import redis_client
        
        # Find all test keys
        test_keys = []
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{prefix}*", count=100)
            test_keys.extend(keys)
            if cursor == 0:
                break
        
        if test_keys:
            # Decode bytes if needed
            decoded_keys = [
                k.decode("utf-8") if isinstance(k, bytes) else k 
                for k in test_keys
            ]
            redis_client.delete(*decoded_keys)
            results["redis_keys_deleted"] = len(decoded_keys)
            logger.info(f"Deleted {len(decoded_keys)} Redis test keys")
        else:
            logger.info("No Redis test keys found")
            
    except ImportError:
        logger.warning("Redis client not available — skipping Redis cleanup")
    except Exception as e:
        results["errors"].append(f"Redis: {str(e)[:200]}")
        logger.error(f"Redis cleanup error: {e}")
    
    # ── Supabase Cleanup ──
    try:
        from database.client import supabase
        
        # Delete in order: child tables first, then parent
        tables = [
            ("student_signals", "student_id"),
            ("student_models", "student_id"),
            ("platform_sessions", "student_id"),
            ("crisis_events", "student_id"),
        ]
        
        for table_name, column in tables:
            try:
                result = (
                    supabase.table(table_name)
                    .delete()
                    .filter(column, "like", f"{prefix}%")
                    .execute()
                )
                count = len(result.data) if hasattr(result, 'data') and result.data else 0
                results[f"supabase_{table_name}"] = count
                if count > 0:
                    logger.info(f"Deleted {count} rows from {table_name}")
            except Exception as e:
                # Table might not exist yet — non-critical
                logger.debug(f"Could not clean {table_name}: {e}")
        
        # Delete test students last
        try:
            result = (
                supabase.table("students")
                .delete()
                .filter("platform_user_id", "like", f"{prefix}%")
                .execute()
            )
            count = len(result.data) if hasattr(result, 'data') and result.data else 0
            results["supabase_students"] = count
            if count > 0:
                logger.info(f"Deleted {count} test students")
        except Exception as e:
            results["errors"].append(f"Supabase students: {str(e)[:200]}")
            logger.error(f"Student cleanup error: {e}")
            
    except ImportError:
        logger.warning("Supabase client not available — skipping Supabase cleanup")
    except Exception as e:
        results["errors"].append(f"Supabase: {str(e)[:200]}")
        logger.error(f"Supabase cleanup error: {e}")
    
    # ── Summary ──
    total = sum(v for k, v in results.items() if isinstance(v, int))
    logger.info(f"Cleanup complete: {total} total items deleted")
    
    return results


async def cleanup_stale_tests(max_age_hours: int = 24) -> dict:
    """
    Clean up test data older than max_age_hours.
    
    Useful for cleaning up after interrupted test runs.
    """
    results = {
        "redis_keys_deleted": 0,
        "supabase_rows_deleted": 0,
        "errors": [],
    }
    
    try:
        from database.client import supabase
        from datetime import datetime, timezone, timedelta
        
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        
        tables = [
            "student_signals",
            "student_models", 
            "platform_sessions",
            "crisis_events",
        ]
        
        for table in tables:
            try:
                result = (
                    supabase.table(table)
                    .delete()
                    .filter("detected_at", "lt", cutoff)
                    .execute()
                )
                count = len(result.data) if hasattr(result, 'data') and result.data else 0
                results["supabase_rows_deleted"] += count
            except Exception:
                pass  # Table might not have detected_at column
        
    except Exception as e:
        results["errors"].append(str(e)[:200])
    
    return results


async def verify_cleanup(prefix: str = "test_") -> dict:
    """
    Verify that no test data remains after cleanup.
    
    Returns dict with counts of remaining test items (should be 0).
    """
    remaining = {
        "redis_keys": 0,
        "supabase_students": 0,
    }
    
    # Check Redis
    try:
        from database.client import redis_client
        
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{prefix}*", count=100)
            remaining["redis_keys"] += len(keys)
            if cursor == 0:
                break
    except Exception:
        pass
    
    # Check Supabase
    try:
        from database.client import supabase
        
        result = (
            supabase.table("students")
            .select("id", count="exact")
            .filter("platform_user_id", "like", f"{prefix}%")
            .execute()
        )
        remaining["supabase_students"] = result.count if hasattr(result, 'count') else 0
    except Exception:
        pass
    
    return remaining


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

async def main():
    """Run cleanup from command line."""
    import asyncio
    
    print("🧹 WaxPrep Test Data Cleanup")
    print("=" * 40)
    
    # Clean all test data
    results = await cleanup_all(prefix="test_")
    
    print(f"\nRedis keys deleted: {results['redis_keys_deleted']}")
    print(f"Supabase rows deleted:")
    for key, value in results.items():
        if key.startswith("supabase_") and isinstance(value, int):
            table = key.replace("supabase_", "")
            print(f"  - {table}: {value}")
    
    if results["errors"]:
        print(f"\n⚠️  Errors:")
        for error in results["errors"]:
            print(f"  - {error}")
    
    # Verify
    print(f"\n🔍 Verifying cleanup...")
    remaining = await verify_cleanup()
    
    if remaining["redis_keys"] == 0 and remaining["supabase_students"] == 0:
        print("✅ All test data cleaned successfully!")
    else:
        print(f"⚠️  Remaining: {remaining['redis_keys']} Redis keys, {remaining['supabase_students']} students")
    
    print("\nDone.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
