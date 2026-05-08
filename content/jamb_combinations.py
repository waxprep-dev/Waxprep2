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
