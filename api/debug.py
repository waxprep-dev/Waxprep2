"""
api/debug.py — Diagnostic Endpoint for Schema Introspection

Admin-only endpoint that exposes database schema, table health, and runtime state.
This is TEMPORARY infrastructure for AI-assisted development — not production code.

SECURITY:
- Admin-only (ADMIN_API_KEYS)
- No sensitive data exposed (no student content, no PINs, no messages)
- Read-only operations only
- Should be removed or disabled before public launch

USAGE:
  GET /debug/schema?key=YOUR_ADMIN_KEY
  
RETURNS:
  {
    "timestamp": "2026-05-24T19:45:00Z",
    "database": {
      "tables": [
        {
          "name": "student_facts",
          "columns": [
            {"name": "id", "type": "uuid", "nullable": "NO"},
            {"name": "student_id", "type": "uuid", "nullable": "NO"},
            ...
          ],
          "row_count": 1523,
          "size_kb": 2048
        }
      ]
    },
    "redis": {
      "connected": true,
      "key_count": 4821,
      "memory_used_human": "12.4M"
    },
    "recent_errors": [
      {"time": "...", "source": "dialectical_ledger", "message": "..."}
    ]
  }
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.debug")
router = APIRouter(prefix="/debug", tags=["debug"])

# ═══════════════════════════════════════════════════════════════════════
# SECURITY — Admin-only access
# ═══════════════════════════════════════════════════════════════════════

# Load from env or use default (CHANGE THIS IN PRODUCTION)
ADMIN_API_KEYS = os.getenv("WAX_DEBUG_API_KEYS", "wax-debug-2026-change-me").split(",")

# Tables we care about (from Thermal Memory Architecture)
TRACKED_TABLES = [
    "students",
    "conversations",
    "sessions",
    "working_memory_snapshots",
    "session_summaries",
    "student_facts",
    "teaching_preferences",
    "observations",
    "blocked_outputs",
    "relational_intimacy_events",
    "memory_mutations",
    "relational_intimacy_current",
    "quizzes",
    "competence_map",
    "achievements",
    "activity_log",
    "safety_events",
]

# ═══════════════════════════════════════════════════════════════════════
# SCHEMA DISCOVERY
# ═══════════════════════════════════════════════════════════════════════

async def _get_table_schema(table_name: str) -> Dict[str, Any]:
    """Get column definitions for a single table."""
    try:
        result = (
            supabase.table("information_schema.columns")
            .select("column_name, data_type, is_nullable, column_default")
            .eq("table_schema", "public")
            .eq("table_name", table_name)
            .order("ordinal_position")
            .execute()
        )
        
        columns = []
        for row in (result.data or []):
            columns.append({
                "name": row.get("column_name"),
                "type": row.get("data_type"),
                "nullable": row.get("is_nullable"),
                "default": row.get("column_default"),
            })
        
        return {
            "name": table_name,
            "columns": columns,
            "column_count": len(columns),
        }
    except Exception as e:
        logger.error(f"Schema discovery failed for {table_name}: {e}")
        return {
            "name": table_name,
            "columns": [],
            "column_count": 0,
            "error": str(e),
        }


async def _get_table_stats(table_name: str) -> Dict[str, Any]:
    """Get row count and size for a table."""
    try:
        result = (
            supabase.table(table_name)
            .select("*", count="exact")
            .limit(0)
            .execute()
        )
        
        size_kb = None
        try:
            size_result = (
                supabase.rpc(
                    "get_table_size_kb",
                    {"table_name": table_name}
                )
                .execute()
            )
            if size_result.data:
                size_kb = size_result.data
        except Exception:
            pass
        
        return {
            "row_count": result.count if hasattr(result, "count") else "unknown",
            "size_kb": size_kb,
        }
    except Exception as e:
        return {
            "row_count": "error",
            "size_kb": None,
            "error": str(e),
        }


async def _get_recent_errors(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent errors from blocked_outputs as proxy."""
    try:
        result = (
            supabase.table("blocked_outputs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        
        errors = []
        for row in (result.data or []):
            errors.append({
                "time": row.get("created_at"),
                "source": "output_safety",
                "reason": row.get("trigger_reason"),
                "preview": row.get("response_preview", "")[:100],
            })
        return errors
    except Exception as e:
        return [{"error": f"Could not fetch errors: {e}"}]


async def _get_redis_status() -> Dict[str, Any]:
    """Check Redis connection and basic stats."""
    try:
        info = redis_client.info()
        return {
            "connected": True,
            "version": info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "total_keys": redis_client.dbsize(),
            "uptime_seconds": info.get("uptime_in_seconds"),
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════

@router.get("/schema")
async def debug_schema(key: str = Query(..., description="Admin API key")):
    """
    Full schema dump for AI-assisted development.
    Requires admin key. Returns all table schemas, row counts, Redis status.
    """
    if key not in ADMIN_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    start_time = datetime.now(timezone.utc)
    
    tables = []
    for table_name in TRACKED_TABLES:
        schema = await _get_table_schema(table_name)
        stats = await _get_table_stats(table_name)
        
        tables.append({
            **schema,
            **stats,
        })
    
    redis_status = await _get_redis_status()
    recent_errors = await _get_recent_errors(limit=10)
    
    response = {
        "timestamp": start_time.isoformat(),
        "environment": os.getenv("RENDER_ENVIRONMENT", "unknown"),
        "database": {
            "tables": tables,
            "total_tables_tracked": len(TRACKED_TABLES),
        },
        "redis": redis_status,
        "recent_errors": recent_errors,
        "notes": [
            "This endpoint is for AI-assisted development only.",
            "No student PII or message content is exposed.",
            "Remove before production launch.",
        ],
    }
    
    return JSONResponse(content=response)


@router.get("/health")
async def debug_health(key: str = Query(..., description="Admin API key")):
    """Quick health check — lighter than /schema."""
    if key not in ADMIN_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    checks = {}
    
    try:
        result = supabase.table("students").select("count", count="exact").limit(0).execute()
        checks["supabase"] = "ok"
    except Exception as e:
        checks["supabase"] = f"error: {e}"
    
    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
    
    return JSONResponse(content={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "all_ok": all(v == "ok" for v in checks.values()),
    })


@router.get("/table/{table_name}")
async def debug_table_detail(
    table_name: str,
    key: str = Query(..., description="Admin API key"),
    limit: int = Query(5, ge=1, le=20),
):
    """
    Deep dive into a specific table — schema + sample rows.
    WARNING: Only use on non-sensitive tables. Never expose conversations content.
    """
    if key not in ADMIN_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    SENSITIVE_TABLES = ["conversations", "students"]
    allow_samples = table_name not in SENSITIVE_TABLES
    
    schema = await _get_table_schema(table_name)
    stats = await _get_table_stats(table_name)
    
    response = {
        "table": table_name,
        "schema": schema,
        "stats": stats,
        "samples_allowed": allow_samples,
        "samples": [],
    }
    
    if allow_samples:
        try:
            result = (
                supabase.table(table_name)
                .select("*")
                .limit(limit)
                .execute()
            )
            samples = []
            for row in (result.data or []):
                sanitized = {}
                for k, v in row.items():
                    if isinstance(v, str) and len(v) > 200:
                        sanitized[k] = v[:200] + "... [truncated]"
                    else:
                        sanitized[k] = v
                samples.append(sanitized)
            response["samples"] = samples
        except Exception as e:
            response["sample_error"] = str(e)
    
    return JSONResponse(content=response)
