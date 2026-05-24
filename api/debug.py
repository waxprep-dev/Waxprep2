"""
api/debug.py — Diagnostic Endpoint for Schema Introspection

FIXED: Uses sample-row inference instead of information_schema 
(Supabase REST blocks system views).
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

ADMIN_API_KEYS = os.getenv("WAX_DEBUG_API_KEYS", "wax-debug-2026-change-me").split(",")

# All tables to check — includes blueprint names AND known aliases
TRACKED_TABLES = [
    "students", "conversations", "sessions",
    "working_memory_snapshots", "session_summaries",
    "student_facts", "teaching_preferences",
    "observations", "blocked_outputs",
    "relational_intimacy_events", "memory_mutations",
    "relational_intimacy_current",
    # Blueprint tables that might not exist
    "quizzes", "competence_map", "achievements",
    "activity_log", "safety_events",
    # Possible alias tables (from error hints)
    "questions", "malpractice_events", "crisis_events",
]


async def _discover_table_schema(table_name: str) -> Dict[str, Any]:
    """
    Discover schema by fetching a sample row and inspecting keys.
    This works because Supabase REST returns JSON with all column names as keys.
    """
    try:
        result = (
            supabase.table(table_name)
            .select("*")
            .limit(1)
            .execute()
        )
        
        if result.data and len(result.data) > 0:
            row = result.data[0]
            columns = []
            for key, value in row.items():
                py_type = type(value).__name__ if value is not None else "null"
                type_map = {
                    "str": "text", "int": "integer", "float": "numeric",
                    "bool": "boolean", "dict": "jsonb", "list": "jsonb/array",
                    "NoneType": "unknown", "datetime": "timestamptz",
                }
                columns.append({
                    "name": key,
                    "inferred_type": type_map.get(py_type, py_type),
                    "sample_value": str(value)[:50] if value is not None else None,
                })
            return {
                "exists": True,
                "has_data": True,
                "columns": columns,
                "column_count": len(columns),
            }
        else:
            return {
                "exists": True,
                "has_data": False,
                "columns": [],
                "column_count": 0,
                "note": "Table exists but empty. Schema unknown until data is inserted.",
            }
            
    except Exception as e:
        error_str = str(e)
        if "Could not find" in error_str or "PGRST205" in error_str:
            return {
                "exists": False,
                "has_data": False,
                "columns": [],
                "column_count": 0,
                "error": "Table does not exist in schema",
            }
        else:
            return {
                "exists": "unknown",
                "has_data": False,
                "columns": [],
                "column_count": 0,
                "error": error_str,
            }


async def _get_table_stats(table_name: str) -> Dict[str, Any]:
    """Get row count for a table."""
    try:
        result = (
            supabase.table(table_name)
            .select("*", count="exact")
            .limit(0)
            .execute()
        )
        return {
            "row_count": result.count if hasattr(result, "count") else "unknown",
        }
    except Exception as e:
        return {
            "row_count": "error",
            "error": str(e),
        }


@router.get("/schema")
async def debug_schema(key: str = Query(..., description="Admin API key")):
    """Full schema discovery via sample-row inference."""
    if key not in ADMIN_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    tables = []
    for table_name in TRACKED_TABLES:
        schema = await _discover_table_schema(table_name)
        stats = await _get_table_stats(table_name)
        
        tables.append({
            "name": table_name,
            **schema,
            **stats,
        })
    
    # Redis status
    try:
        info = redis_client.info()
        redis_status = {
            "connected": True,
            "version": info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "total_keys": redis_client.dbsize(),
        }
    except Exception as e:
        redis_status = {"connected": False, "error": str(e)}
    
    return JSONResponse(content={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": "sample_row_inference",
        "database": {"tables": tables},
        "redis": redis_status,
    })


@router.get("/health")
async def debug_health(key: str = Query(..., description="Admin API key")):
    """Quick health check."""
    if key not in ADMIN_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    checks = {}
    try:
        supabase.table("students").select("count", count="exact").limit(0).execute()
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
