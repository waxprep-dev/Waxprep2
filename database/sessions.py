"""
database/sessions.py — Session Management

Tracks study sessions with start/end, topic coverage, emotional arcs,
and competence deltas. Integrates with SIAPM memory system.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from database.client import supabase

logger = logging.getLogger("waxprep.sessions")


# ═══════════════════════════════════════════════════════════════════════
# SESSION CRUD
# ═══════════════════════════════════════════════════════════════════════

async def start_session(student_id: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Start a new study session for a student.
    
    Returns the new session UUID.
    """
    if not student_id:
        return None
    
    try:
        # Get next session number
        result = supabase.rpc("get_next_session_number", {"p_student_id": student_id}).execute()
        next_number = result.data if result.data else 1
        
        session_data = {
            "student_id": student_id,
            "session_number": next_number,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        
        result = supabase.table("sessions").insert(session_data).execute()
        
        if result.data and len(result.data) > 0:
            session_id = result.data[0]["id"]
            logger.info(f"Session started for {student_id}: #{next_number} ({session_id})")
            return session_id
            
    except Exception as e:
        logger.error(f"Failed to start session for {student_id}: {e}")
    
    return None


async def end_session(
    student_id: str,
    session_id: str,
    ended_by: str = "student",
    topics_covered: Optional[List[str]] = None,
    emotional_arc: Optional[str] = None,
    summary: Optional[str] = None,
    competence_delta: Optional[Decimal] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    End a study session and record outcomes.
    
    Args:
        ended_by: 'student', 'system', 'timeout', or 'crash'
    """
    if not session_id or not student_id:
        return False
    
    try:
        update_data = {
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "ended_by": ended_by,
        }
        
        if topics_covered:
            update_data["topics_covered"] = topics_covered
        if emotional_arc:
            update_data["emotional_arc"] = emotional_arc
        if summary:
            update_data["summary"] = summary
        if competence_delta is not None:
            update_data["competence_delta"] = float(competence_delta)
        if metadata:
            # Merge with existing metadata
            existing = supabase.table("sessions").select("metadata").eq("id", session_id).execute()
            if existing.data:
                current_meta = existing.data[0].get("metadata", {})
                current_meta.update(metadata)
                update_data["metadata"] = current_meta
        
        result = (
            supabase.table("sessions")
            .update(update_data)
            .eq("id", session_id)
            .eq("student_id", student_id)
            .execute()
        )
        
        success = bool(result.data)
        if success:
            logger.info(f"Session ended for {student_id}: {session_id} (by {ended_by})")
        return success
        
    except Exception as e:
        logger.error(f"Failed to end session {session_id} for {student_id}: {e}")
    
    return False


async def get_active_session(student_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the student's currently active session (no ended_at).
    
    Returns None if no active session.
    """
    if not student_id:
        return None
    
    try:
        result = (
            supabase.table("sessions")
            .select("*")
            .eq("student_id", student_id)
            .is_("ended_at", "null")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        
        if result.data and len(result.data) > 0:
            return result.data[0]
            
    except Exception as e:
        logger.error(f"Failed to get active session for {student_id}: {e}")
    
    return None


async def get_session_history(student_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent completed sessions for a student.
    """
    if not student_id:
        return []
    
    try:
        result = (
            supabase.table("sessions")
            .select("*")
            .eq("student_id", student_id)
            .not_.is_("ended_at", "null")
            .order("ended_at", desc=True)
            .limit(limit)
            .execute()
        )
        
        return result.data or []
        
    except Exception as e:
        logger.error(f"Failed to get session history for {student_id}: {e}")
    
    return []


async def get_session_count(student_id: str) -> int:
    """
    Get total number of completed sessions for a student.
    """
    if not student_id:
        return 0
    
    try:
        result = (
            supabase.table("sessions")
            .select("id", count="exact")
            .eq("student_id", student_id)
            .execute()
        )
        
        return result.count or 0
        
    except Exception as e:
        logger.error(f"Failed to count sessions for {student_id}: {e}")
    
    return 0


# ═══════════════════════════════════════════════════════════════════════
# SESSION HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def ensure_active_session(student_id: str) -> Optional[str]:
    """
    Get or create an active session for a student.
    
    Called at the start of every message processing to ensure
    all memory writes have a valid session_id.
    """
    # Check for existing active session
    active = await get_active_session(student_id)
    if active:
        return active["id"]
    
    # Check for recent gap — if last session ended > 60 min ago, start new
    history = await get_session_history(student_id, limit=1)
    if history:
        last_session = history[0]
        ended_at = last_session.get("ended_at")
        if ended_at:
            ended_time = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
            gap_minutes = (datetime.now(timezone.utc) - ended_time).total_seconds() / 60
            if gap_minutes < 60:
                # Within gap threshold, consider this a continuation
                # (But we already checked active session, so this shouldn't happen)
                pass
    
    # Start new session
    return await start_session(student_id)


async def add_topic_to_session(session_id: str, topic: str) -> bool:
    """
    Add a topic to the current session's topics_covered array.
    """
    if not session_id or not topic:
        return False
    
    try:
        # Get current topics
        result = supabase.table("sessions").select("topics_covered").eq("id", session_id).execute()
        if not result.data:
            return False
        
        current_topics = result.data[0].get("topics_covered", []) or []
        
        if topic not in current_topics:
            current_topics.append(topic)
            
            update_result = (
                supabase.table("sessions")
                .update({"topics_covered": current_topics})
                .eq("id", session_id)
                .execute()
            )
            
            return bool(update_result.data)
            
    except Exception as e:
        logger.error(f"Failed to add topic to session {session_id}: {e}")
    
    return False


async def record_emotional_arc(session_id: str, arc: str) -> bool:
    """
    Record the emotional arc for a session.
    Format: "started_anxious,ended_confident" or similar.
    """
    if not session_id or not arc:
        return False
    
    try:
        result = (
            supabase.table("sessions")
            .update({"emotional_arc": arc})
            .eq("id", session_id)
            .execute()
        )
        return bool(result.data)
        
    except Exception as e:
        logger.error(f"Failed to record emotional arc for {session_id}: {e}")
    
    return False
