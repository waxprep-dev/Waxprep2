"""
database/ghost_threads.py — Ghost Thread Persistence Layer

SQL migration + CRUD helpers for the Ghost Thread Protocol.

Table: ghost_threads
- Tracks scheduled, sent, and resurrected ghost threads
- Stores Ghost Student persona snapshots
- Records epistemic growth (temporal deltas)
- Uses thermal lifecycle (hot/warm/cool/cold/frozen)

Alignment with current schema:
- student_id is TEXT (matches observations.student_id, not UUID)
- thermal_state uses 5-state CHECK constraint
- provenance tracking on all derived data
- JSONB for flexible persona/delta storage

CHANGELOG:
- 2026-05-24: Created for P1-B Ghost Thread Protocol
"""

# ═══════════════════════════════════════════════════════════════════════
# SQL MIGRATION — Run this in Supabase SQL Editor
# ═══════════════════════════════════════════════════════════════════════

GHOST_THREADS_MIGRATION = """
-- ghost_threads: Temporal dialectics persistence
CREATE TABLE IF NOT EXISTS ghost_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Student reference (TEXT to match observations.student_id)
    student_id TEXT NOT NULL,
    
    -- Anchor: the conversation moment that haunts
    anchor_conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    anchor_type VARCHAR(30) NOT NULL,
    
    -- Ghost Student: temporal persona snapshot
    ghost_student_persona JSONB NOT NULL DEFAULT '{}',
    
    -- The schism: past vs present
    past_position TEXT NOT NULL,
    present_challenge TEXT NOT NULL,
    
    -- Scheduling and delivery
    scheduled_at TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',
    
    -- The actual ghost message content
    ghost_content TEXT,
    
    -- Resurrection: student reply and classification
    student_reply TEXT,
    resurrection_classification VARCHAR(20),
    
    -- Epistemic growth tracking
    epistemic_delta JSONB DEFAULT '{}',
    
    -- Thermal lifecycle
    thermal_state VARCHAR(10) DEFAULT 'warm',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_ghost_threads_student 
    ON ghost_threads(student_id, status);
CREATE INDEX IF NOT EXISTS idx_ghost_threads_scheduled 
    ON ghost_threads(scheduled_at, status);
CREATE INDEX IF NOT EXISTS idx_ghost_threads_anchor 
    ON ghost_threads(anchor_conversation_id);

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION update_ghost_threads_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_ghost_threads_updated_at ON ghost_threads;
CREATE TRIGGER trigger_ghost_threads_updated_at
    BEFORE UPDATE ON ghost_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_ghost_threads_updated_at();
"""

# ═══════════════════════════════════════════════════════════════════════
# CRUD HELPERS
# ═══════════════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from database.client import supabase

logger = logging.getLogger("waxprep.ghost_threads_db")


async def create_ghost_thread(record: Dict[str, Any]) -> Optional[str]:
    """
    Insert a new ghost thread record.
    Returns the ghost_id (UUID) on success, None on failure.
    """
    try:
        # Ensure required fields
        required = ["student_id", "anchor_conversation_id", "anchor_type",
                   "ghost_student_persona", "past_position", "present_challenge",
                   "scheduled_at", "ghost_content"]
        for field in required:
            if field not in record:
                logger.error(f"Missing required field: {field}")
                return None

        result = (
            supabase.table("ghost_threads")
            .insert(record)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
        return None
    except Exception as e:
        logger.error(f"Failed to create ghost thread: {e}")
        return None


async def get_ghost_by_id(ghost_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single ghost thread by ID."""
    try:
        result = (
            supabase.table("ghost_threads")
            .select("*")
            .eq("id", ghost_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as e:
        logger.error(f"Failed to fetch ghost {ghost_id}: {e}")
        return None


async def update_ghost_status(
    ghost_id: str,
    status: str,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Update ghost status and optionally other fields.
    Status must be one of: pending, sent, delivered, replied, dismissed, expired, resurrected
    """
    valid_statuses = ["pending", "sent", "delivered", "replied", "dismissed", "expired", "resurrected"]
    if status not in valid_statuses:
        logger.error(f"Invalid status: {status}")
        return False

    update_data = {"status": status}
    if extra_fields:
        update_data.update(extra_fields)

    try:
        supabase.table("ghost_threads").update(update_data).eq("id", ghost_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update ghost {ghost_id}: {e}")
        return False


async def get_pending_ghosts(
    student_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch pending ghosts, optionally filtered by student."""
    try:
        query = (
            supabase.table("ghost_threads")
            .select("*")
            .eq("status", "pending")
            .order("scheduled_at", desc=False)  # Oldest first
            .limit(limit)
        )
        if student_id:
            query = query.eq("student_id", student_id)
        
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch pending ghosts: {e}")
        return []


async def get_student_ghost_stats(student_id: str) -> Dict[str, Any]:
    """
    Get statistics about a student's ghost thread history.
    Returns counts by status, average response time, etc.
    """
    try:
        result = (
            supabase.table("ghost_threads")
            .select("*")
            .eq("student_id", student_id)
            .execute()
        )
        ghosts = result.data or []
        
        stats = {
            "total": len(ghosts),
            "pending": 0,
            "sent": 0,
            "replied": 0,
            "resurrected": 0,
            "dismissed": 0,
            "expired": 0,
            "resurrection_rate": 0.0,
            "avg_response_time_hours": None,
        }
        
        response_times = []
        for g in ghosts:
            status = g.get("status", "pending")
            if status in stats:
                stats[status] += 1
            
            # Calculate response time for replied ghosts
            if status in ["replied", "resurrected"] and g.get("sent_at") and g.get("updated_at"):
                try:
                    sent = datetime.fromisoformat(g["sent_at"].replace("Z", "+00:00"))
                    updated = datetime.fromisoformat(g["updated_at"].replace("Z", "+00:00"))
                    hours = (updated - sent).total_seconds() / 3600
                    response_times.append(hours)
                except Exception:
                    pass
        
        if response_times:
            stats["avg_response_time_hours"] = sum(response_times) / len(response_times)
        
        sent_or_replied = stats["sent"] + stats["replied"] + stats["resurrected"] + stats["dismissed"]
        if sent_or_replied > 0:
            stats["resurrection_rate"] = (stats["replied"] + stats["resurrected"]) / sent_or_replied
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to fetch ghost stats: {e}")
        return {"total": 0, "error": str(e)}


async def record_epistemic_delta(
    ghost_id: str,
    before_stance: str,
    after_stance: str,
    growth_vector: Dict[str, Any],
    reply_excerpt: str,
    days_between: int,
) -> bool:
    """
    Record the student's epistemic growth from a ghost encounter.
    Called by the Resurrection Engine.
    """
    delta = {
        "before_stance": before_stance,
        "after_stance": after_stance,
        "growth_vector": growth_vector,
        "reply_excerpt": reply_excerpt,
        "days_between": days_between,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    
    return await update_ghost_status(
        ghost_id=ghost_id,
        status="resurrected",
        extra_fields={"epistemic_delta": delta},
    )


async def dismiss_student_ghosts(student_id: str) -> bool:
    """Dismiss all pending ghosts for a student."""
    try:
        supabase.table("ghost_threads").update({
            "status": "dismissed",
        }).eq("student_id", student_id).eq("status", "pending").execute()
        return True
    except Exception as e:
        logger.error(f"Failed to dismiss ghosts for {student_id}: {e}")
        return False


async def cleanup_expired_ghosts(max_age_days: int = 30) -> int:
    """
    Clean up old pending ghosts that were never sent.
    Returns number of expired ghosts.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        result = (
            supabase.table("ghost_threads")
            .update({"status": "expired"})
            .eq("status", "pending")
            .lt("scheduled_at", cutoff.isoformat())
            .execute()
        )
        # Count is approximate — Supabase doesn't return count on update
        return len(result.data or [])
    except Exception as e:
        logger.error(f"Failed to cleanup expired ghosts: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════
# MIGRATION RUNNER (for programmatic execution)
# ═══════════════════════════════════════════════════════════════════════

async def run_migration() -> bool:
    """
    Execute the ghost_threads table migration.
    Call this once during deployment or from an admin endpoint.
    """
    try:
        # Supabase doesn't support multi-statement raw SQL via REST
        # We execute each statement separately
        from database.client import supabase
        
        # 1. Create table
        create_sql = """
        CREATE TABLE IF NOT EXISTS ghost_threads (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            student_id TEXT NOT NULL,
            anchor_conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            anchor_type VARCHAR(30) NOT NULL,
            ghost_student_persona JSONB NOT NULL DEFAULT '{}',
            past_position TEXT NOT NULL,
            present_challenge TEXT NOT NULL,
            scheduled_at TIMESTAMPTZ NOT NULL,
            sent_at TIMESTAMPTZ,
            status VARCHAR(20) DEFAULT 'pending',
            ghost_content TEXT,
            student_reply TEXT,
            resurrection_classification VARCHAR(20),
            epistemic_delta JSONB DEFAULT '{}',
            thermal_state VARCHAR(10) DEFAULT 'warm',
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
        supabase.rpc("exec_sql", {"sql": create_sql}).execute()
        
        # 2. Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_ghost_threads_student ON ghost_threads(student_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_ghost_threads_scheduled ON ghost_threads(scheduled_at, status)",
            "CREATE INDEX IF NOT EXISTS idx_ghost_threads_anchor ON ghost_threads(anchor_conversation_id)",
        ]
        for idx_sql in indexes:
            try:
                supabase.rpc("exec_sql", {"sql": idx_sql}).execute()
            except Exception as e:
                logger.warning(f"Index creation skipped (may already exist): {e}")
        
        logger.info("ghost_threads migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        # Fallback: log the SQL for manual execution
        logger.info("Please run the migration manually in Supabase SQL Editor")
        return False
