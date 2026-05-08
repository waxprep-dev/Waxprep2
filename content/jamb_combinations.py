"""
WaxPrep v2 — JAMB Subject Combinations
Official JAMB UTME subject combinations for the 2026/2027 session.

Source: Official JAMB 2026 Brochure
Verified: May 8, 2026

CRITICAL RULES:
    - Use of English is COMPULSORY for every course (always listed first)
    - Subject names MUST match the official JAMB list exactly
    - "Literature in English" — NOT "Literature" or "English Literature"
    - "Principles of Accounts" — NOT "Accounting" (that's the course name)
    - "Christian Religious Studies (CRS)" — official name includes CRS in parentheses
    - Trade subjects are NOT accepted for JAMB UTME (WAEC/NECO only)
    - Alternative electives are noted per course (any accepted option is valid)
"""

# ═══════════════════════════════════════════════
# JAMB SUBJECT COMBINATIONS
# ═══════════════════════════════════════════════
# Each course maps to:
#   - required: list of exact official subject names
#   - alternatives: dict mapping position to list of accepted alternatives
#     e.g., {"4th": ["Government", "Commerce", "Geography"]}
#   - notes: any university-specific variations or important context

JAMB_COMBINATIONS = {
    "medicine_and_surgery": {
        "display_name": "Medicine & Surgery",
        "category": "science",
        "required": [
            "Use of English",
            "Biology",
            "Chemistry",
            "Physics",
        ],
        "alternatives": {},
        "notes": "Non-negotiable at virtually all medical schools. All three electives are compulsory."
    },
    "law": {
        "display_name": "Law (LL.B)",
        "category": "arts",
        "required": [
            "Use of English",
            "Literature in English",
            "Government",
        ],
        "alternatives": {
            "4th": [
                "Christian Religious Studies (CRS)",
                "Islamic Studies (IRS)",
                "Economics",
            ]
        },
        "notes": "Most top law schools require Literature in English. UNILAG insists on it."
    },
    "accounting": {
        "display_name": "Accounting",
        "category": "commercial",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "Commerce",
                "Geography",
            ]
        },
        "notes": "Principles of Accounts is accepted at some universities instead of Economics."
    },
    "nursing_science": {
        "display_name": "Nursing Science",
        "category": "science",
        "required": [
            "Use of English",
            "Biology",
            "Chemistry",
            "Physics",
        ],
        "alternatives": {},
        "notes": "Same combination as Medicine & Surgery. All three electives are compulsory."
    },
    "computer_science": {
        "display_name": "Computer Science",
        "category": "science",
        "required": [
            "Use of English",
            "Mathematics",
            "Physics",
        ],
        "alternatives": {
            "4th": [
                "Chemistry",
                "Biology",
                "Economics",
            ]
        },
        "notes": "Computer Studies is now an official JAMB subject but most universities still require Mathematics and Physics."
    },
    "business_administration": {
        "display_name": "Business Administration",
        "category": "commercial",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "Commerce",
                "Geography",
            ]
        },
        "notes": ""
    },
    "pharmacy": {
        "display_name": "Pharmacy",
        "category": "science",
        "required": [
            "Use of English",
            "Biology",
            "Chemistry",
        ],
        "alternatives": {
            "4th": [
                "Physics",
                "Mathematics",
            ]
        },
        "notes": "Some universities accept Mathematics instead of Physics as the fourth subject."
    },
    "mass_communication": {
        "display_name": "Mass Communication",
        "category": "arts",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "Literature in English",
            ]
        },
        "notes": ""
    },
    "civil_engineering": {
        "display_name": "Civil Engineering",
        "category": "science",
        "required": [
            "Use of English",
            "Mathematics",
            "Physics",
            "Chemistry",
        ],
        "alternatives": {},
        "notes": "Same combination for all major engineering fields (Mechanical, Electrical, Chemical, etc.)"
    },
    "political_science": {
        "display_name": "Political Science",
        "category": "arts",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
            "Government",
        ],
        "alternatives": {},
        "notes": ""
    },
    "economics": {
        "display_name": "Economics",
        "category": "commercial",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "History",
                "Geography",
            ]
        },
        "notes": ""
    },
    "biochemistry": {
        "display_name": "Biochemistry",
        "category": "science",
        "required": [
            "Use of English",
            "Biology",
            "Chemistry",
        ],
        "alternatives": {
            "4th": [
                "Physics",
                "Mathematics",
            ]
        },
        "notes": "Some universities accept Mathematics instead of Physics."
    },
    "public_administration": {
        "display_name": "Public Administration",
        "category": "arts",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
            "Government",
        ],
        "alternatives": {},
        "notes": ""
    },
    "sociology": {
        "display_name": "Sociology",
        "category": "arts",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "Christian Religious Studies (CRS)",
                "Islamic Studies (IRS)",
            ]
        },
        "notes": ""
    },
    "english_language_and_literary_studies": {
        "display_name": "English Language & Literary Studies",
        "category": "arts",
        "required": [
            "Use of English",
            "Literature in English",
        ],
        "alternatives": {
            "3rd": [
                "Government",
                "History",
            ],
            "4th": [
                "Christian Religious Studies (CRS)",
                "Islamic Studies (IRS)",
                "Economics",
            ]
        },
        "notes": ""
    },
    "history_and_international_studies": {
        "display_name": "History & International Studies",
        "category": "arts",
        "required": [
            "Use of English",
            "History",
            "Government",
        ],
        "alternatives": {
            "4th": [
                "Christian Religious Studies (CRS)",
                "Islamic Studies (IRS)",
                "Literature in English",
            ]
        },
        "notes": ""
    },
    "petroleum_engineering": {
        "display_name": "Petroleum Engineering",
        "category": "science",
        "required": [
            "Use of English",
            "Mathematics",
            "Physics",
            "Chemistry",
        ],
        "alternatives": {},
        "notes": "Same as other engineering fields."
    },
    "banking_and_finance": {
        "display_name": "Banking & Finance",
        "category": "commercial",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "Commerce",
                "Geography",
            ]
        },
        "notes": ""
    },
    "marketing": {
        "display_name": "Marketing",
        "category": "commercial",
        "required": [
            "Use of English",
            "Mathematics",
            "Economics",
        ],
        "alternatives": {
            "4th": [
                "Government",
                "Commerce",
                "Geography",
            ]
        },
        "notes": ""
    },
    "architecture": {
        "display_name": "Architecture",
        "category": "science",
        "required": [
            "Use of English",
            "Mathematics",
            "Physics",
        ],
        "alternatives": {
            "4th": [
                "Geography",
                "Chemistry",
                "Art",
            ]
        },
        "notes": "Art (Fine Art) is accepted at some universities as the fourth subject."
    },
}

# ═══════════════════════════════════════════════
# OFFICIAL JAMB SUBJECT LIST (2026)
# ═══════════════════════════════════════════════
# All 25 subjects currently offered by JAMB UTME.
# Used to validate that a student's subjects are real JAMB subjects.

OFFICIAL_JAMB_SUBJECTS = {
    # Sciences
    "Agricultural Science",
    "Biology",
    "Chemistry",
    "Computer Studies",
    "Geography",
    "Mathematics",
    "Physical & Health Education (PHE)",
    "Physics",
    # Commercial & Business
    "Commerce",
    "Economics",
    "Principles of Accounts",
    # Arts & Humanities
    "Arabic",
    "Art",
    "Christian Religious Studies (CRS)",
    "French",
    "Government",
    "Hausa",
    "History",
    "Igbo",
    "Islamic Studies (IRS)",
    "Literature in English",
    "Music",
    "Yoruba",
    "Home Economics",
    # Compulsory
    "Use of English",
}

# ═══════════════════════════════════════════════
# COURSE ALIASES
# ═══════════════════════════════════════════════
# Maps what students might type to the official course key.
# Case-insensitive matching is done in code.

COURSE_ALIASES = {
    "medicine": "medicine_and_surgery",
    "medicine and surgery": "medicine_and_surgery",
    "med": "medicine_and_surgery",
    "doctor": "medicine_and_surgery",
    "dentistry": "medicine_and_surgery",
    "dental": "medicine_and_surgery",
    "law": "law",
    "llb": "law",
    "lawyer": "law",
    "accounting": "accounting",
    "account": "accounting",
    "accounts": "accounting",
    "nursing": "nursing_science",
    "nurse": "nursing_science",
    "computer science": "computer_science",
    "comp sci": "computer_science",
    "cs": "computer_science",
    "business admin": "business_administration",
    "business administration": "business_administration",
    "biz admin": "business_administration",
    "pharmacy": "pharmacy",
    "pharm": "pharmacy",
    "mass communication": "mass_communication",
    "mass comm": "mass_communication",
    "journalism": "mass_communication",
    "engineering": "civil_engineering",
    "civil engineering": "civil_engineering",
    "mechanical engineering": "civil_engineering",
    "electrical engineering": "civil_engineering",
    "chemical engineering": "civil_engineering",
    "political science": "political_science",
    "pol sci": "political_science",
    "economics": "economics",
    "econs": "economics",
    "biochemistry": "biochemistry",
    "biochem": "biochemistry",
    "public administration": "public_administration",
    "public admin": "public_administration",
    "pa": "public_administration",
    "sociology": "sociology",
    "socio": "sociology",
    "english": "english_language_and_literary_studies",
    "english language": "english_language_and_literary_studies",
    "english and literary studies": "english_language_and_literary_studies",
    "history": "history_and_international_studies",
    "history and international studies": "history_and_international_studies",
    "international relations": "history_and_international_studies",
    "petroleum engineering": "petroleum_engineering",
    "petroleum": "petroleum_engineering",
    "banking and finance": "banking_and_finance",
    "banking": "banking_and_finance",
    "finance": "banking_and_finance",
    "marketing": "marketing",
    "architecture": "architecture",
    "architect": "architecture",
    "archi": "architecture",
}

# ═══════════════════════════════════════════════
# COURSE ALTERNATIVES (for mismatch handling)
# ═══════════════════════════════════════════════
# When a student's subjects don't match their dream course,
# Wax suggests alternatives in the same field with different requirements.

COURSE_ALTERNATIVES = {
    "medicine_and_surgery": [
        "pharmacy",
        "nursing_science",
        "biochemistry",
    ],
    "law": [
        "political_science",
        "public_administration",
        "sociology",
    ],
    "pharmacy": [
        "nursing_science",
        "biochemistry",
        "medicine_and_surgery",
    ],
    "civil_engineering": [
        "architecture",
        "computer_science",
        "petroleum_engineering",
    ],
    "computer_science": [
        "civil_engineering",
        "economics",
        "biochemistry",
    ],
}


# ═══════════════════════════════════════════════
# JAMB READINESS CHECKER
# ═══════════════════════════════════════════════

def resolve_course(raw_input: str) -> str | None:
    """
    Convert whatever the student typed into an official course key.
    
    Handles:
    - Direct matches: "medicine" → "medicine_and_surgery"
    - Alias matches: "doctor" → "medicine_and_surgery"
    - Case variations: "Law" → "law"
    - Extra whitespace: "  computer science  " → "computer science"
    
    Args:
        raw_input: What the student typed
        
    Returns:
        Official course key (e.g., "medicine_and_surgery") or None
    """
    cleaned = raw_input.strip().lower()
    
    # Direct alias match
    if cleaned in COURSE_ALIASES:
        return COURSE_ALIASES[cleaned]
    
    # Check if it's already a valid course key
    if cleaned in JAMB_COMBINATIONS:
        return cleaned
    
    # Partial match — check if any alias contains the input
    for alias, course_key in COURSE_ALIASES.items():
        if cleaned in alias or alias in cleaned:
            return course_key
    
    return None


def normalize_subject_for_jamb(subject: str) -> str:
    """
    Convert WaxPrep's internal subject names to official JAMB subject names.
    
    WaxPrep stores "english" — JAMB requires "Use of English".
    WaxPrep stores "mathematics" — JAMB requires "Mathematics".
    
    Args:
        subject: Subject name as stored in WaxPrep (lowercase, underscores)
        
    Returns:
        Official JAMB subject name, or the original if no mapping exists
    """
    mapping = {
        "english": "Use of English",
        "english_language": "Use of English",
        "mathematics": "Mathematics",
        "maths": "Mathematics",
        "math": "Mathematics",
        "physics": "Physics",
        "chemistry": "Chemistry",
        "biology": "Biology",
        "economics": "Economics",
        "government": "Government",
        "literature_in_english": "Literature in English",
        "literature": "Literature in English",
        "commerce": "Commerce",
        "accounting": "Principles of Accounts",
        "accounts": "Principles of Accounts",
        "geography": "Geography",
        "history": "History",
        "agricultural_science": "Agricultural Science",
        "further_mathematics": "Mathematics",
        "civic_education": "Government",
        "crs": "Christian Religious Studies (CRS)",
        "christian_religious_studies": "Christian Religious Studies (CRS)",
        "irs": "Islamic Studies (IRS)",
        "islamic_religious_studies": "Islamic Studies (IRS)",
        "computer_studies": "Computer Studies",
        "ict": "Computer Studies",
        "yoruba": "Yoruba",
        "igbo": "Igbo",
        "hausa": "Hausa",
        "french": "French",
        "arabic": "Arabic",
        "music": "Music",
        "art": "Art",
        "visual_arts": "Art",
        "physical_education": "Physical & Health Education (PHE)",
        "health_education": "Physical & Health Education (PHE)",
        "food_and_nutrition": "Home Economics",
        "home_economics": "Home Economics",
    }
    
    normalized = subject.lower().strip().replace(" ", "_")
    return mapping.get(normalized, subject)


def check_jamb_readiness(
    student_subjects: list[str],
    desired_course: str
) -> dict:
    """
    Compare a student's subjects to JAMB requirements for their desired course.
    
    This is the core function that powers the JAMB Checker feature.
    
    Args:
        student_subjects: List of subject names as stored in WaxPrep
                         (e.g., ["english", "mathematics", "physics", "chemistry"])
        desired_course: What the student wants to study
                       (e.g., "medicine", "law", "engineering")
    
    Returns:
        dict with:
        {
            "course_key": str,           # Official course identifier
            "course_display": str,       # Human-readable course name
            "ready": bool,               # Whether student meets all requirements
            "required": list[str],       # All required subjects (JAMB names)
            "have": list[str],           # Subjects the student has (JAMB names)
            "missing": list[str],        # Required subjects the student lacks
            "alternatives_available": list[str],  # Flexible positions and their options
            "suggested_alternatives": list[str],  # Similar courses if not ready
            "notes": str,                # University-specific notes
            "category": str,             # "science", "commercial", or "arts"
        }
    """
    # Resolve the course
    course_key = resolve_course(desired_course)
    
    if not course_key:
        return {
            "course_key": None,
            "course_display": desired_course,
            "ready": False,
            "error": "unknown_course",
            "message": f"I don't have JAMB data for '{desired_course}' yet. Can you try a different course, or tell me the official name?"
        }
    
    course_data = JAMB_COMBINATIONS[course_key]
    required = course_data["required"]
    alternatives = course_data.get("alternatives", {})
    
    # Normalize student subjects to JAMB names
    jamb_subjects = []
    for subj in student_subjects:
        normalized = normalize_subject_for_jamb(subj)
        if normalized and normalized not in jamb_subjects:
            jamb_subjects.append(normalized)
    
    # Check what they have and what they're missing
    have = []
    missing = []
    
    for subject in required:
        if subject in jamb_subjects:
            have.append(subject)
        else:
            # Check if any alternative satisfies this requirement
            # Alternatives are keyed by position ("3rd", "4th")
            # For required subjects, check if any accepted alternative is present
            found_alternative = False
            for alt_list in alternatives.values():
                if any(alt in jamb_subjects for alt in alt_list):
                    if subject not in have:
                        have.append(subject)
                        found_alternative = True
                        break
            if not found_alternative:
                missing.append(subject)
    
    # Build alternatives summary for display
    alternatives_available = []
    for position, options in alternatives.items():
        alternatives_available.append({
            "position": position,
            "options": options,
            "student_has": [opt for opt in options if opt in jamb_subjects]
        })
    
    # Determine readiness
    ready = len(missing) == 0
    
    # Get suggested alternatives if not ready
    suggested = []
    if not ready:
        alt_courses = COURSE_ALTERNATIVES.get(course_key, [])
        for alt_key in alt_courses:
            if alt_key in JAMB_COMBINATIONS:
                alt_data = JAMB_COMBINATIONS[alt_key]
                # Check if student meets requirements for this alternative
                alt_missing = [s for s in alt_data["required"] if s not in jamb_subjects and s != "Use of English"]
                alt_ready = len(alt_missing) == 0
                suggested.append({
                    "course_key": alt_key,
                    "display_name": alt_data["display_name"],
                    "ready": alt_ready,
                    "missing_for_this": alt_missing
                })
    
    return {
        "course_key": course_key,
        "course_display": course_data["display_name"],
        "ready": ready,
        "required": required,
        "have": have,
        "missing": missing,
        "alternatives_available": alternatives_available,
        "suggested_alternatives": suggested,
        "notes": course_data.get("notes", ""),
        "category": course_data.get("category", "unknown"),
    }


def get_course_display_name(course_input: str) -> str:
    """
    Get the human-readable display name for a course.
    
    Args:
        course_input: Raw student input or course key
        
    Returns:
        Display name like "Medicine & Surgery" or the original input if unknown
    """
    course_key = resolve_course(course_input)
    if course_key and course_key in JAMB_COMBINATIONS:
        return JAMB_COMBINATIONS[course_key]["display_name"]
    return course_input


def get_all_courses_by_category(category: str = None) -> list[dict]:
    """
    Get all courses, optionally filtered by category.
    
    Args:
        category: "science", "commercial", "arts", or None for all
        
    Returns:
        List of course dicts with keys: course_key, display_name, category, required
    """
    courses = []
    for key, data in JAMB_COMBINATIONS.items():
        if category is None or data.get("category") == category:
            courses.append({
                "course_key": key,
                "display_name": data["display_name"],
                "category": data.get("category", "unknown"),
                "required": data["required"],
                "notes": data.get("notes", ""),
            })
    return courses


def suggest_courses_from_subjects(student_subjects: list[str]) -> list[dict]:
    """
    Suggest courses that match a student's existing subjects.
    
    Useful when a student says "I don't know what to study."
    Analyzes all known courses and returns ones where the student
    meets at least 3 out of 4 requirements.
    
    Args:
        student_subjects: List of WaxPrep subject names
        
    Returns:
        List of matching courses, sorted by best match first
    """
    jamb_subjects = []
    for subj in student_subjects:
        normalized = normalize_subject_for_jamb(subj)
        if normalized and normalized not in jamb_subjects:
            jamb_subjects.append(normalized)
    
    matches = []
    for course_key, data in JAMB_COMBINATIONS.items():
        required = data["required"]
        matched = [s for s in required if s in jamb_subjects]
        score = len(matched)
        total = len(required)
        
        if score >= 3:  # Need at least 3 matches to suggest
            matches.append({
                "course_key": course_key,
                "display_name": data["display_name"],
                "category": data.get("category", "unknown"),
                "match_score": score,
                "total_required": total,
                "have": matched,
                "missing": [s for s in required if s not in jamb_subjects],
                "notes": data.get("notes", ""),
            })
    
    # Sort by match score (highest first), then by total required (fewer requirements = easier to match)
    matches.sort(key=lambda x: (-x["match_score"], x["total_required"]))
    return matches


def validate_jamb_subjects(subjects: list[str]) -> dict:
    """
    Check if a student's subjects are valid JAMB subjects.
    
    Args:
        subjects: List of WaxPrep subject names
        
    Returns:
        dict with valid subjects, invalid subjects, and suggestions
    """
    valid = []
    invalid = []
    
    for subj in subjects:
        jamb_name = normalize_subject_for_jamb(subj)
        if jamb_name in OFFICIAL_JAMB_SUBJECTS:
            if jamb_name not in valid:
                valid.append(jamb_name)
        else:
            invalid.append(subj)
    
    return {
        "valid": valid,
        "invalid": invalid,
        "total_valid": len(valid),
        "total_invalid": len(invalid),
        "all_valid": len(invalid) == 0,
    }
