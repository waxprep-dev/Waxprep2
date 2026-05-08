"""
WaxPrep v2 — JAMB Subject Checker
Compares a student's subjects against JAMB requirements for their desired course.

Part of the Teacher Memory Voice system — Wax uses this to proactively
guide students toward exam success, not just react to their questions.
"""

from content.jamb_combinations import (
    JAMB_COMBINATIONS,
    COURSE_ALIASES,
    COURSE_ALTERNATIVES,
    OFFICIAL_JAMB_SUBJECTS,
)


def resolve_course(user_input: str) -> str | None:
    """
    Convert what the student typed into an official course key.
    
    Handles:
    - "doctor" → "medicine_and_surgery"
    - "law" → "law"
    - "computer science" → "computer_science"
    - "Medicine and Surgery" → "medicine_and_surgery" (case-insensitive)
    
    Args:
        user_input: Raw text from the student
        
    Returns:
        Official course key, or None if no match found
    """
    normalized = user_input.strip().lower()
    
    # Direct alias match
    if normalized in COURSE_ALIASES:
        return COURSE_ALIASES[normalized]
    
    # Try matching against display names (case-insensitive)
    for key, data in JAMB_COMBINATIONS.items():
        if data["display_name"].lower() == normalized:
            return key
    
    # Try partial match — "medicine" appears in "medicine_and_surgery"
    for key, data in JAMB_COMBINATIONS.items():
        if normalized in key or normalized in data["display_name"].lower():
            return key
    
    return None


def normalize_subject_name(subject: str) -> str:
    """
    Normalize a student's subject to match official JAMB names.
    
    Handles common variations:
    - "english" → "Use of English"
    - "maths" / "math" → "Mathematics"
    - "literature" → "Literature in English"
    - "government" → "Government"
    - "crs" → "Christian Religious Studies (CRS)"
    
    Args:
        subject: Subject name as stored in student profile or typed by student
        
    Returns:
        Normalized subject name matching official JAMB list
    """
    subject_lower = subject.strip().lower()
    
    # Direct matches (case-insensitive against official list)
    for official in OFFICIAL_JAMB_SUBJECTS:
        if official.lower() == subject_lower:
            return official
    
    # Common variations
    variations = {
        "english": "Use of English",
        "english language": "Use of English",
        "use of english": "Use of English",
        "maths": "Mathematics",
        "math": "Mathematics",
        "mathematics": "Mathematics",
        "physics": "Physics",
        "chemistry": "Chemistry",
        "biology": "Biology",
        "economics": "Economics",
        "econs": "Economics",
        "government": "Government",
        "govt": "Government",
        "literature": "Literature in English",
        "literature in english": "Literature in English",
        "english literature": "Literature in English",
        "commerce": "Commerce",
        "accounting": "Principles of Accounts",
        "accounts": "Principles of Accounts",
        "principles of accounts": "Principles of Accounts",
        "financial accounting": "Principles of Accounts",
        "geography": "Geography",
        "history": "History",
        "crs": "Christian Religious Studies (CRS)",
        "christian religious studies": "Christian Religious Studies (CRS)",
        "irs": "Islamic Studies (IRS)",
        "islamic religious studies": "Islamic Studies (IRS)",
        "agric": "Agricultural Science",
        "agricultural science": "Agricultural Science",
        "computer": "Computer Studies",
        "computer studies": "Computer Studies",
        "ict": "Computer Studies",
        "french": "French",
        "arabic": "Arabic",
        "art": "Art",
        "fine art": "Art",
        "music": "Music",
        "hausa": "Hausa",
        "igbo": "Igbo",
        "yoruba": "Yoruba",
        "phe": "Physical & Health Education (PHE)",
        "physical and health education": "Physical & Health Education (PHE)",
        "physical & health education": "Physical & Health Education (PHE)",
        "home economics": "Home Economics",
    }
    
    if subject_lower in variations:
        return variations[subject_lower]
    
    # Return original if no match (caller should validate)
    return subject


def check_jamb_readiness(
    student_subjects: list[str],
    desired_course: str
) -> dict:
    """
    Compare a student's subjects against JAMB requirements.
    
    This is the core function of the JAMB Subject Checker.
    It tells the student whether their subjects match their dream course,
    and if not, what's missing and what alternatives exist.
    
    Args:
        student_subjects: List of subjects the student is taking
            (e.g., ["english", "mathematics", "physics", "chemistry"])
        desired_course: What the student wants to study
            (e.g., "medicine", "law", "computer science")
    
    Returns:
        Dictionary with:
        {
            "course_key": "medicine_and_surgery",
            "course_display": "Medicine & Surgery",
            "required": ["Use of English", "Biology", "Chemistry", "Physics"],
            "student_subjects_normalized": ["Use of English", "Mathematics", ...],
            "have": ["Use of English", "Chemistry", "Biology"],
            "missing": ["Physics"],
            "ready": False,
            "alternatives": ["pharmacy", "nursing_science", "biochemistry"],
            "notes": "Non-negotiable at virtually all medical schools."
        }
    """
    # Resolve course
    course_key = resolve_course(desired_course)
    
    if not course_key:
        return {
            "course_key": None,
            "course_display": desired_course,
            "error": "unknown_course",
            "message": f"I don't have JAMB data for '{desired_course}' yet. Can you try a different course name? Or I can look it up."
        }
    
    course_data = JAMB_COMBINATIONS[course_key]
    
    # Normalize all student subjects to official names
    normalized_subjects = []
    for subj in student_subjects:
        normalized = normalize_subject_name(subj)
        normalized_subjects.append(normalized)
    
    # Get required subjects
    required = course_data["required"]  # e.g., ["Use of English", "Biology", "Chemistry", "Physics"]
    alternatives = course_data.get("alternatives", {})
    
    # Check what the student has and what's missing
    have = []
    missing = []
    
    for position_idx, subject in enumerate(required):
        # position: 1st = Use of English, 2nd = first elective, 3rd = second elective, 4th = third elective
        position_label = ["1st", "2nd", "3rd", "4th"][position_idx]
        
        if subject in normalized_subjects:
            have.append(subject)
        elif position_label in alternatives:
            # This position has acceptable alternatives — check if student has any of them
            alt_options = alternatives[position_label]
            found_alternative = None
            for alt in alt_options:
                if alt in normalized_subjects:
                    found_alternative = alt
                    break
            
            if found_alternative:
                have.append(found_alternative)
            else:
                missing.append({
                    "position": position_label,
                    "preferred": subject,
                    "alternatives": alt_options,
                })
        else:
            # No alternatives — this subject is compulsory
            missing.append({
                "position": position_label,
                "preferred": subject,
                "alternatives": [],
            })
    
    ready = len(missing) == 0
    
    # Get alternatives if not ready
    alt_courses = []
    if not ready:
        alt_keys = COURSE_ALTERNATIVES.get(course_key, [])
        for alt_key in alt_keys:
            if alt_key in JAMB_COMBINATIONS:
                alt_courses.append({
                    "key": alt_key,
                    "display": JAMB_COMBINATIONS[alt_key]["display_name"],
                })
    
    return {
        "course_key": course_key,
        "course_display": course_data["display_name"],
        "category": course_data.get("category", "unknown"),
        "required": required,
        "student_subjects_normalized": normalized_subjects,
        "have": have,
        "missing": missing,
        "ready": ready,
        "alternatives": alt_courses,
        "notes": course_data.get("notes", ""),
    }
