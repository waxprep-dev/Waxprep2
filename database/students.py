"""
WaxPrep v2 — Student Database Operations
Look up and create student records in Supabase.

FIXES APPLIED:
    1. Replaced print() with proper logging.
    2. Added duplicate check before creating student.
    3. Check platform session insert result; clean up orphaned student on failure.
    4. Documented lazy import of helpers.py.
    5. Added TODO for student profile caching (Phase 3).
    6. Added update field whitelist to prevent schema corruption.
"""

import logging
from database.client import supabase

logger = logging.getLogger("waxprep.database.students")

# Whitelist allowed fields for update_student() to prevent schema corruption
ALLOWED_UPDATE_FIELDS = {
    "name", "class_level", "target_exam", "subjects",
    "student_subject", "exam_date", "state", "language_preference",
    "subscription_tier", "is_trial_active", "onboarding_complete",
    "is_active", "current_state"
}


async def get_student_by_platform_id(platform: str, platform_user_id: str) -> dict | None:
    """
    Find a student by their platform and ID.
    Returns the student dict, or None if not found.
    
    TODO Phase 3: Cache student profiles in Redis (1-hour TTL).
    This function is called on every message — currently hits Supabase each time.
    Cache key: student_profile:{platform}:{platform_user_id}
    Invalidate in update_student().
    """
    try:
        # First, find the platform session
        session_result = (
            supabase.table("platform_sessions")
            .select("student_id")
            .eq("platform", platform)
            .eq("platform_user_id", platform_user_id)
            .execute()
        )

        if not session_result.data:
            return None

        student_id = session_result.data[0]["student_id"]

        # Then, get the student record
        student_result = (
            supabase.table("students")
            .select("*")
            .eq("id", student_id)
            .execute()
        )

        if student_result.data:
            return student_result.data[0]
        return None

    except Exception as e:
        logger.error(f"get_student_by_platform_id error: {e}")
        return None


async def create_student(
    platform: str,
    platform_user_id: str,
    name: str,
    pin: str,
    class_level: str = None,
    target_exam: str = None,
    subjects: list = None,
    student_subject: str = None,
    exam_date: str = None,
    student_state: str = None,
    language_preference: str = "english",
) -> dict | None:
    """
    Create a new student record and link their platform session.
    Returns the created student dict, or None on failure.
    """
    # Check if student already exists for this platform
    existing = await get_student_by_platform_id(platform, platform_user_id)
    if existing:
        logger.warning(f"Student already exists for {platform}:{platform_user_id}")
        return existing

    # Lazy import — helpers.py may import from database modules
    from helpers import generate_wax_id, generate_recovery_code, hash_pin

    wax_id = generate_wax_id()
    recovery_code = generate_recovery_code()
    pin_hash = hash_pin(pin)

    try:
        # Insert the student
        student_result = (
            supabase.table("students")
            .insert({
                "wax_id": wax_id,
                "name": name,
                "pin_hash": pin_hash,
                "recovery_code": recovery_code,
                "class_level": class_level,
                "target_exam": target_exam,
                "subjects": subjects or [],
                "student_subject": student_subject or "",
                "exam_date": exam_date,
                "state": student_state,
                "language_preference": language_preference,
                "subscription_tier": "free",
                "is_trial_active": True,
                "onboarding_complete": True,
                "terms_accepted": True,
                "is_active": True,
            })
            .execute()
        )

        if not student_result.data:
            logger.error("create_student: Insert returned no data")
            return None

        student = student_result.data[0]

        # Link the platform session
        session_result = supabase.table("platform_sessions").insert({
            "student_id": student["id"],
            "platform": platform,
            "platform_user_id": platform_user_id,
        }).execute()

        if not session_result.data:
            logger.error(f"Platform session insert failed for student {student['id']}")
            # Clean up the orphaned student record
            try:
                supabase.table("students").delete().eq("id", student["id"]).execute()
            except Exception as cleanup_error:
                logger.error(f"Failed to clean up orphaned student {student['id']}: {cleanup_error}")
            return None

        return student

    except Exception as e:
        logger.error(f"create_student error: {e}")
        return None


async def update_student(student_id: str, updates: dict) -> bool:
    """
    Update a student record.
    Returns True if successful, False otherwise.
    """
    # Validate updates dict — whitelist allowed fields
    filtered_updates = {k: v for k, v in updates.items() if k in ALLOWED_UPDATE_FIELDS}
    if len(filtered_updates) != len(updates):
        logger.warning(
            f"Filtered out invalid update fields: {set(updates.keys()) - ALLOWED_UPDATE_FIELDS}"
        )
    updates = filtered_updates

    try:
        result = (
            supabase.table("students")
            .update(updates)
            .eq("id", student_id)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"update_student error: {e}")
        return False
