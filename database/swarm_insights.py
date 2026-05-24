"""
database/swarm_insights.py — Swarm Mind Persistence Layer

SQL migration and CRUD helpers for the Ubuntu Swarm Mind.

Tables:
1. swarm_insights — Insight capsules from S2 (Insight Distillery)
2. swarm_audit_log — Privacy audit trail from S4 (Zero-Knowledge Relay)
3. swarm_deliveries — Delivery tracking from S5 (Contagion Limiter)

Alignment:
- Uses TEXT student_id (matches observations table)
- JSONB for flexible pattern/payload storage
- Thermal lifecycle concepts in metadata
- Provenance tracking on all derived data

CHANGELOG:
- 2026-05-25: Created for Ubuntu Swarm Mind P2-A
"""

# ═══════════════════════════════════════════════════════════════════════
# SQL MIGRATION — Run this in Supabase SQL Editor
# ═══════════════════════════════════════════════════════════════════════

SWARM_MIGRATION = """
-- swarm_insights: Portable teaching patterns
CREATE TABLE IF NOT EXISTS swarm_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight_id VARCHAR(32) UNIQUE NOT NULL,
    
    -- Concept identification
    concept_id VARCHAR(100) NOT NULL,
    concept_name VARCHAR(200) NOT NULL,
    subject VARCHAR(50) NOT NULL,
    
    -- Breakthrough metadata
    breakthrough_type VARCHAR(30) NOT NULL,
    
    -- Teaching pattern (JSONB for flexibility)
    teaching_pattern JSONB NOT NULL DEFAULT '{}',
    
    -- The insight payload
    insight_payload JSONB NOT NULL DEFAULT '{}',
    
    -- Quality scoring
    effectiveness_score DECIMAL(4,3) NOT NULL,
    quality_tier VARCHAR(20) NOT NULL CHECK (quality_tier IN ('incubation', 'slow', 'fast', 'viral')),
    
    -- Anonymized provenance
    provenance JSONB NOT NULL DEFAULT '{}',
    
    -- Transfer metadata
    transfer_metadata JSONB NOT NULL DEFAULT '{}',
    
    -- Spread tracking
    delivery_count INT DEFAULT 0,
    acceptance_count INT DEFAULT 0,
    current_velocity_phase VARCHAR(20) DEFAULT 'incubation',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast matching
CREATE INDEX IF NOT EXISTS idx_swarm_insights_concept 
    ON swarm_insights(concept_id, effectiveness_score DESC);
CREATE INDEX IF NOT EXISTS idx_swarm_insights_subject 
    ON swarm_insights(subject, quality_tier);
CREATE INDEX IF NOT EXISTS idx_swarm_insights_tier 
    ON swarm_insights(quality_tier, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_swarm_insights_created 
    ON swarm_insights(created_at DESC);

-- swarm_audit_log: Privacy audit trail
CREATE TABLE IF NOT EXISTS swarm_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Hashed identifiers (no raw IDs)
    hashed_student_id VARCHAR(16) NOT NULL,
    hashed_insight_id VARCHAR(16) NOT NULL,
    
    -- Action details
    concept_id VARCHAR(100) NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('transfer', 'delivery', 'acceptance', 'opt_out', 'containment')),
    privacy_level VARCHAR(20) NOT NULL,
    
    -- Differential privacy metadata
    dp_epsilon DECIMAL(3,1) DEFAULT 1.0,
    salt_date DATE NOT NULL,
    
    -- Timestamp
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_swarm_audit_insight 
    ON swarm_audit_log(hashed_insight_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_swarm_audit_timestamp 
    ON swarm_audit_log(timestamp DESC);

-- swarm_deliveries: Delivery tracking
CREATE TABLE IF NOT EXISTS swarm_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- References (hashed for privacy)
    insight_id VARCHAR(32) NOT NULL,
    student_id TEXT NOT NULL,
    
    -- Delivery metadata
    concept_id VARCHAR(100) NOT NULL,
    compatibility_score DECIMAL(4,3),
    velocity_phase VARCHAR(20) DEFAULT 'incubation',
    
    -- Content (sanitized)
    delivery_content TEXT,
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'delivered', 'accepted', 'dismissed', 'expired')),
    sent_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_swarm_deliveries_student 
    ON swarm_deliveries(student_id, status);
CREATE INDEX IF NOT EXISTS idx_swarm_deliveries_insight 
    ON swarm_deliveries(insight_id, status);
CREATE INDEX IF NOT EXISTS idx_swarm_deliveries_concept 
    ON swarm_deliveries(concept_id, created_at DESC);

-- Update triggers
CREATE OR REPLACE FUNCTION update_swarm_insights_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_swarm_insights_updated_at ON swarm_insights;
CREATE TRIGGER trigger_swarm_insights_updated_at
    BEFORE UPDATE ON swarm_insights
    FOR EACH ROW
    EXECUTE FUNCTION update_swarm_insights_updated_at();

CREATE OR REPLACE FUNCTION update_swarm_deliveries_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_swarm_deliveries_updated_at ON swarm_deliveries;
CREATE TRIGGER trigger_swarm_deliveries_updated_at
    BEFORE UPDATE ON swarm_deliveries
    FOR EACH ROW
    EXECUTE FUNCTION update_swarm_deliveries_updated_at();
"""

# ═══════════════════════════════════════════════════════════════════════
# CRUD HELPERS
# ═══════════════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from database.client import supabase

logger = logging.getLogger("waxprep.swarm_db")


async def create_insight(record: Dict[str, Any]) -> Optional[str]:
    """
    Insert a new insight capsule.
    Returns insight_id on success, None on failure.
    """
    try:
        required = ["insight_id", "concept_id", "concept_name", "subject",
                   "breakthrough_type", "effectiveness_score", "quality_tier"]
        for field in required:
            if field not in record:
                logger.error(f"Missing required field: {field}")
                return None

        result = (
            supabase.table("swarm_insights")
            .insert(record)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]["insight_id"]
        return None
    except Exception as e:
        logger.error(f"Failed to create insight: {e}")
        return None


async def get_insight_by_id(insight_id: str) -> Optional[Dict[str, Any]]:
    """Fetch insight by ID."""
    try:
        result = (
            supabase.table("swarm_insights")
            .select("*")
            .eq("insight_id", insight_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to fetch insight: {e}")
        return None


async def get_insights_by_concept(
    concept_id: str,
    min_effectiveness: float = 0.70,
    max_age_days: int = 7,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch insights for a concept."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        result = (
            supabase.table("swarm_insights")
            .select("*")
            .eq("concept_id", concept_id)
            .gte("effectiveness_score", min_effectiveness)
            .gte("created_at", cutoff.isoformat())
            .order("effectiveness_score", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch insights: {e}")
        return []


async def update_insight_spread(
    insight_id: str,
    delivery_count: Optional[int] = None,
    acceptance_count: Optional[int] = None,
    velocity_phase: Optional[str] = None,
) -> bool:
    """Update spread tracking for an insight."""
    try:
        updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if delivery_count is not None:
            updates["delivery_count"] = delivery_count
        if acceptance_count is not None:
            updates["acceptance_count"] = acceptance_count
        if velocity_phase:
            updates["current_velocity_phase"] = velocity_phase

        supabase.table("swarm_insights").update(updates).eq("insight_id", insight_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update insight spread: {e}")
        return False


async def create_delivery(record: Dict[str, Any]) -> Optional[str]:
    """Create a delivery record."""
    try:
        required = ["insight_id", "student_id", "concept_id"]
        for field in required:
            if field not in record:
                logger.error(f"Missing required field: {field}")
                return None

        result = (
            supabase.table("swarm_deliveries")
            .insert(record)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
        return None
    except Exception as e:
        logger.error(f"Failed to create delivery: {e}")
        return None


async def update_delivery_status(
    delivery_id: str,
    status: str,
    sent_at: Optional[str] = None,
    accepted_at: Optional[str] = None,
) -> bool:
    """Update delivery status."""
    valid_statuses = ["pending", "sent", "delivered", "accepted", "dismissed", "expired"]
    if status not in valid_statuses:
        logger.error(f"Invalid status: {status}")
        return False

    try:
        updates = {"status": status}
        if sent_at:
            updates["sent_at"] = sent_at
        if accepted_at:
            updates["accepted_at"] = accepted_at

        supabase.table("swarm_deliveries").update(updates).eq("id", delivery_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update delivery: {e}")
        return False


async def get_student_deliveries(
    student_id: str,
    status: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Get delivery history for a student."""
    try:
        query = (
            supabase.table("swarm_deliveries")
            .select("*")
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)

        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch deliveries: {e}")
        return []


async def create_audit_record(record: Dict[str, Any]) -> bool:
    """Create an audit log record."""
    try:
        supabase.table("swarm_audit_log").insert(record).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to create audit record: {e}")
        return False


async def get_audit_batch(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent audit records."""
    try:
        result = (
            supabase.table("swarm_audit_log")
            .select("*")
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to fetch audit log: {e}")
        return []


async def get_swarm_stats() -> Dict[str, Any]:
    """Get overall swarm statistics."""
    try:
        # Total insights
        insights_result = supabase.table("swarm_insights").select("id", count="exact").execute()
        total_insights = insights_result.count or 0

        # Total deliveries
        deliveries_result = supabase.table("swarm_deliveries").select("id", count="exact").execute()
        total_deliveries = deliveries_result.count or 0

        # Accepted deliveries
        accepted_result = (
            supabase.table("swarm_deliveries")
            .select("id", count="exact")
            .eq("status", "accepted")
            .execute()
        )
        total_accepted = accepted_result.count or 0

        # Acceptance rate
        acceptance_rate = round(total_accepted / max(total_deliveries, 1), 3)

        # Velocity distribution
        velocity_result = (
            supabase.table("swarm_insights")
            .select("quality_tier, count")
            .execute()
        )

        return {
            "total_insights": total_insights,
            "total_deliveries": total_deliveries,
            "total_accepted": total_accepted,
            "acceptance_rate": acceptance_rate,
            "velocity_distribution": velocity_result.data or [],
        }
    except Exception as e:
        logger.error(f"Failed to get swarm stats: {e}")
        return {"error": str(e)}
