"""
WaxPrep v2 — Student Database Operations
Look up and create student records in Supabase.
"""

from database.client import supabase


async def get_student_by_platform_id(platform: str, platform_user_id: str) -> dict | None:
    """
    Find a student by their platform and ID.
    Returns the student dict, or None if not found.
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
        print(f"get_student_by_platform_id error: {e}")
        return None


async def create_student(
    platform: str,
    platform_user_id: str,
    name: str,
    pin: str,
    class_level: str = None,
    target_exam: str = None,
    subjects: list = None,
    student_subject: str = None,  # FIXED: Added — the subject the student struggles with
    exam_date: str = None,
    student_state: str = None,
    language_preference: str = "english",
) -> dict | None:
    """
    Create a new student record and link their platform session.
    Returns the created student dict, or None on failure.
    """
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
                "student_subject": student_subject or "",  # FIXED: Now saved to database
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
            print("create_student: Insert returned no data")
            return None

        student = student_result.data[0]

        # Link the platform session
        supabase.table("platform_sessions").insert({
            "student_id": student["id"],
            "platform": platform,
            "platform_user_id": platform_user_id,
        }).execute()

        return student

    except Exception as e:
        print(f"create_student error: {e}")
        return None


async def update_student(student_id: str, updates: dict) -> bool:
    """
    Update a student record.
    Returns True if successful, False otherwise.
    """
    try:
        result = (
            supabase.table("students")
            .update(updates)
            .eq("id", student_id)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        print(f"update_student error: {e}")
        return False
