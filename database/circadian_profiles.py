"""
database/circadian_profiles.py — Circadian Profile Persistence

SQL migration and CRUD helpers for biological rhythm fingerprints.

Table: circadian_profiles
- Stores each student's learned biological rhythm
- Tracks power reliability, engagement windows, state history
- Measures sleep whisper effectiveness

Alignment:
- student_id is TEXT (matches observations.student_id)
- Uses thermal lifecycle concepts but stores as metadata
- JSONB for flexible state transition history

CHANGELOG:
- 2026-05-24: Created for Circadian Teaching Cortex
"""

# ═══════════════════════════════════════════════════════════════════════
# SQL MIGRATION
# ═══════════════════════════════════════════════════════════════════════

CIRCADIAN_PROFILES_MIGRATION = """
-- circadian_profiles: Biological rhythm fingerprint per student
CREATE TABLE IF NOT EXISTS circadian_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id TEXT NOT NULL UNIQUE,
    
    -- Inferred biological rhythms
    typical_wake_time TIME DEFAULT '05:30:00',
    typical_sleep_time TIME DEFAULT '23:00:00',
    school_hours_start TIME DEFAULT '08:00:00',
    school_hours_end TIME DEFAULT '15:00:00',
    peak_engagement_start TIME DEFAULT '18:00:00',
    peak_engagement_end TIME DEFAULT '21:00:00',
    
    -- Resource context
    data_bundle_cycle VARCHAR(20) DEFAULT 'daily' 
        CHECK (data_bundle_cycle IN ('daily', 'weekly', 'night_plan', 'pay_as_go')),
    power_reliability_score DECIMAL(3,2) DEFAULT 0.60,
    family_phone_competition VARCHAR(10) DEFAULT 'high' 
        CHECK (family_phone_competition IN ('high', 'medium', 'low')),
    
    -- State tracking
    last_known_state VARCHAR(20) DEFAULT 'dark',
    last_state_change_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Learning history
    state_transition_history JSONB DEFAULT '[]',
    dawn_questions_answered INT DEFAULT 0,
    dawn_questions_correct INT DEFAULT 0,
    sleep_whispers_received INT DEFAULT 0,
    sleep_whispers_recalled_next_day INT DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_circadian_profiles_state 
    ON circadian_profiles(last_known_state, last_state_change_at);
CREATE INDEX IF NOT EXISTS idx_circadian_profiles_student 
    ON circadian_profiles(student_id);

-- Update trigger
CREATE OR REPLACE FUNCTION update_circadian_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_circadian_profiles_updated_at ON circadian_profiles;
CREATE TRIGGER trigger_circadian_profiles_updated_at
    BEFORE UPDATE ON circadian_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_circadian_profiles_updated_at();
"""

# ═══════════════════════════════════════════════════════════════════════
# CRUD HELPERS
# ═══════════════════════════════════════════════════════════════════════

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from database.client import supabase

logger = logging.getLogger("waxprep.circadian_db")


async def create_profile(student_id: str) -> bool:
    """Create default profile for new student."""
    try:
        supabase.table("circadian_profiles").insert({
            "student_id": student_id,
            "typical_wake_time": "05:30:00",
            "typical_sleep_time": "23:00:00",
            "school_hours_start": "08:00:00",
            "school_hours_end": "15:00:00",
            "peak_engagement_start": "18:00:00",
            "peak_engagement_end": "21:00:00",
            "data_bundle_cycle": "daily",
            "power_reliability_score": 0.60,
            "family_phone_competition": "high",
            "last_known_state": "dark",
        }).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to create circadian profile: {e}")
        return False


async def get_profile(student_id: str) -> Optional[Dict[str, Any]]:
    """Fetch profile by student_id."""
    try:
        result = (
            supabase.table("circadian_profiles")
            .select("*")
            .eq("student_id", student_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to fetch circadian profile: {e}")
        return None


async def update_profile(student_id: str, updates: Dict[str, Any]) -> bool:
    """Update specific fields in profile."""
    try:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        supabase.table("circadian_profiles").update(updates).eq("student_id", student_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update circadian profile: {e}")
        return False


async def increment_counter(student_id: str, counter_name: str) -> bool:
    """Increment a counter field (dawn_questions_answered, etc.)."""
    valid_counters = [
        "dawn_questions_answered",
        "dawn_questions_correct",
        "sleep_whispers_received",
        "sleep_whispers_recalled_next_day",
    ]
    if counter_name not in valid_counters:
        logger.error(f"Invalid counter: {counter_name}")
        return False

    try:
        # Use RPC for atomic increment, or fetch-update
        profile = await get_profile(student_id)
        if not profile:
            return False

        current = profile.get(counter_name, 0)
        return await update_profile(student_id, {counter_name: current + 1})
    except Exception as e:
        logger.error(f"Failed to increment counter: {e}")
        return False


async def get_student_stats(student_id: str) -> Dict[str, Any]:
    """Get circadian learning statistics for a student."""
    profile = await get_profile(student_id)
    if not profile:
        return {"error": "No profile found"}

    dawn_total = profile.get("dawn_questions_answered", 0)
    dawn_correct = profile.get("dawn_questions_correct", 0)
    whispers_total = profile.get("sleep_whispers_received", 0)
    whispers_recalled = profile.get("sleep_whispers_recalled_next_day", 0)

    return {
        "dawn_accuracy": round(dawn_correct / max(dawn_total, 1), 2),
        "whisper_recall_rate": round(whispers_recalled / max(whispers_total, 1), 2),
        "power_reliability": profile.get("power_reliability_score", 0),
        "peak_engagement_window": f"{profile.get('peak_engagement_start')} - {profile.get('peak_engagement_end')}",
        "total_state_transitions": len(profile.get("state_transition_history", [])),
    }
