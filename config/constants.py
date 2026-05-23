"""
config/constants.py — WaxPrep Living Constants Registry

NOT a static file. A voice modulator that adapts to each student's
cognitive temperature and epistemic stance.

Three tiers:
  1. Universal — Never changes (SUBJECT_MAP, TRACK_FALLBACKS)
  2. Thermal — Hot/cool phrase factories (praise, understanding)
  3. Epistemic — Stance-aware continuity generators (formal, vernacular, synthetic, confused, rejecting)

Core files call: get_phrases(phrase_type, thermal_state, epistemic_stance, student_intimacy_score)
"""

from typing import Dict, List, Optional
from decimal import Decimal


# ═══════════════════════════════════════════════════════════════════════
# TIER 1: UNIVERSAL CONSTANTS (Static, never changes)
# ═══════════════════════════════════════════════════════════════════════

SUBJECT_MAP: Dict[str, str] = {
    "mathematics": "mathematics",
    "maths": "mathematics",
    "math": "mathematics",
    "english": "english",
    "english_language": "english",
    "civic_education": "civic_education",
    "civic": "civic_education",
    "computer_studies": "computer_studies",
    "computer": "computer_studies",
    "ict": "computer_studies",
    "data_processing": "data_processing",
    "data": "data_processing",
    "physics": "physics",
    "chemistry": "chemistry",
    "biology": "biology",
    "further_mathematics": "further_mathematics",
    "further mathematics": "further_mathematics",
    "agricultural_science": "agricultural_science",
    "agric": "agricultural_science",
    "health_education": "health_education",
    "health": "health_education",
    "physical_education": "physical_education",
    "physical": "physical_education",
    "phe": "physical_education",
    "technical_drawing": "technical_drawing",
    "technical drawing": "technical_drawing",
    "food_and_nutrition": "food_and_nutrition",
    "food & nutrition": "food_and_nutrition",
    "economics": "economics",
    "econs": "economics",
    "commerce": "commerce",
    "accounting": "accounting",
    "accounts": "accounting",
    "financial_accounting": "accounting",
    "business_studies": "business_studies",
    "business studies": "business_studies",
    "marketing": "marketing",
    "book_keeping": "book_keeping",
    "book keeping": "book_keeping",
    "office_practice": "office_practice",
    "office practice": "office_practice",
    "insurance": "insurance",
    "government": "government",
    "govt": "government",
    "literature": "literature_in_english",
    "literature_in_english": "literature_in_english",
    "literature-in-english": "literature_in_english",
    "history": "history",
    "christian_religious_studies": "crs",
    "crs": "crs",
    "islamic_religious_studies": "irs",
    "irs": "irs",
    "islamic": "irs",
    "geography": "geography",
    "geo": "geography",
    "visual_arts": "visual_arts",
    "visual arts": "visual_arts",
    "art": "visual_arts",
    "fine_art": "visual_arts",
    "music": "music",
    "french": "french",
    "arabic": "arabic",
    "yoruba": "yoruba",
    "igbo": "igbo",
    "hausa": "hausa",
    "fashion_design": "fashion_design",
    "fashion design": "fashion_design",
    "garment_making": "fashion_design",
    "gsm_repairs": "gsm_repairs",
    "gsm repairs": "gsm_repairs",
    "computer_hardware": "gsm_repairs",
    "solar_installation": "solar_installation",
    "solar installation": "solar_installation",
    "solar": "solar_installation",
    "livestock_farming": "livestock_farming",
    "livestock farming": "livestock_farming",
    "beauty_cosmetology": "beauty_cosmetology",
    "beauty": "beauty_cosmetology",
    "cosmetology": "beauty_cosmetology",
    "horticulture": "horticulture",
    "crop_production": "horticulture",
}

TRACK_FALLBACKS: Dict[str, List[str]] = {
    "science": [
        "english", "mathematics", "physics", "chemistry", "biology",
        "further_mathematics", "agricultural_science", "health_education",
        "physical_education", "technical_drawing", "food_and_nutrition",
        "computer_studies", "data_processing",
    ],
    "commercial": [
        "english", "mathematics", "economics", "commerce", "accounting",
        "business_studies", "marketing", "book_keeping", "office_practice",
        "insurance", "data_processing", "computer_studies",
    ],
    "arts": [
        "english", "mathematics", "government", "literature_in_english",
        "civic_education", "history", "christian_religious_studies",
        "islamic_religious_studies", "geography", "visual_arts", "music",
        "french", "arabic", "yoruba", "igbo", "hausa",
    ],
    "trade": [
        "english", "mathematics", "fashion_design", "gsm_repairs",
        "solar_installation", "livestock_farming", "beauty_cosmetology",
        "horticulture", "computer_studies",
    ],
    "unknown": ["english", "mathematics", "civic_education"],
}


# ═══════════════════════════════════════════════════════════════════════
# TIER 2: THERMAL PHRASE FACTORIES (Context-aware generators)
# ═══════════════════════════════════════════════════════════════════════

class ThermalPhraseFactory:
    """
    Generates praise/understanding phrases based on cognitive temperature.

    Hot = immediate, bodily, Pidgin-heavy (Empiric voice)
    Cool = delayed, cerebral, formal (Socratic voice)
    """

    # ── Understanding / Confirmation phrases ──
    HOT_UNDERSTANDING: List[str] = [
        "e don enter",
        "you sabi am now",
        "e clear now",
        "i see wetin you mean",
        "you get am",
        "na so e be",
        "correct guy",
        "correct girl",
        "you dey try",
        "na im be that",
        "e don click",
        "you don master am",
        "you don catch am",
        "e dey your body now",
    ]

    COOL_UNDERSTANDING: List[str] = [
        "You've grasped the principle",
        "That reasoning is sound",
        "The logic holds",
        "Your derivation is correct",
        "You've identified the key insight",
        "That approach is valid",
        "Your understanding is now consolidated",
        "The concept has taken root",
        "You've constructed a valid argument",
        "Your analysis holds up",
    ]

    # ── Praise / Celebration phrases ──
    HOT_PRAISE: List[str] = [
        "you too much",
        "you sabi this thing o",
        "you bad",
        "you be boss",
        "omo, you sharp",
        "you get sense",
        "na you biko",
        "you dey blast am",
        "fire! 🔥",
        "you dey kill am",
        "no be small thing",
        "you too sabi",
    ]

    COOL_PRAISE: List[str] = [
        "Well reasoned",
        "Precisely",
        "Exactly so",
        "That demonstrates clear thinking",
        "Your method is elegant",
        "You've constructed a solid argument",
        "The analysis is thorough",
        "Your reasoning is rigorous",
        "That is mathematically sound",
        "Your logic is impeccable",
    ]

    # ── Correction / Gentle reframe phrases ──
    HOT_CORRECTION: List[str] = [
        "almost there — check am again",
        "omo, you close but no cigar",
        "think am small, e go enter",
        "no wahala, try again — you fit do am",
        "small mistake, big brain still dey there",
    ]

    COOL_CORRECTION: List[str] = [
        "Almost — reconsider the final step",
        "Close, but examine the boundary condition",
        "A small error in the approach — review the premise",
        "Not quite — let's trace the logic together",
        "The intuition is sound, but the formalization needs adjustment",
    ]

    @classmethod
    def get_understanding_phrases(cls, thermal_state: str = "hot") -> List[str]:
        """Get understanding phrases for a thermal state."""
        if thermal_state in ("hot", "warm"):
            return cls.HOT_UNDERSTANDING
        return cls.COOL_UNDERSTANDING

    @classmethod
    def get_praise_phrases(cls, thermal_state: str = "hot") -> List[str]:
        """Get praise phrases for a thermal state."""
        if thermal_state in ("hot", "warm"):
            return cls.HOT_PRAISE
        return cls.COOL_PRAISE

    @classmethod
    def get_correction_phrases(cls, thermal_state: str = "hot") -> List[str]:
        """Get correction phrases for a thermal state."""
        if thermal_state in ("hot", "warm"):
            return cls.HOT_CORRECTION
        return cls.COOL_CORRECTION


# ═══════════════════════════════════════════════════════════════════════
# TIER 3: EPISTEMIC PHRASE FACTORIES (Stance-aware generators)
# ═══════════════════════════════════════════════════════════════════════

class EpistemicPhraseFactory:
    """
    Generates continuity/closing phrases based on student's epistemic stance.

    formal_leaning → School-register continuity
    vernacular_leaning → Home-register continuity
    synthetic → Bridge-register continuity
    confused → Reassurance-register continuity
    rejecting → Challenge-register continuity
    """

    FORMAL_CONTINUITY: List[str] = [
        "Shall we resume this tomorrow?",
        "I shall retain your progress in your notebook.",
        "We may continue this line of inquiry when you return.",
        "Your study notes shall await your next session.",
        "Shall I prepare a review of today's concepts for your return?",
        "This concept shall remain in your working memory until we resume.",
    ]

    VERNACULAR_CONTINUITY: List[str] = [
        "We go continue tomorrow abi?",
        "I go dey here when you ready.",
        "Your notebook go dey wait you.",
        "No wahala — we go pick am up later.",
        "When you come back, we go run am again.",
        "E go dey here. No fear.",
    ]

    SYNTHETIC_CONTINUITY: List[str] = [
        "Let's build on this next time.",
        "Your notebook is growing — let's add more tomorrow.",
        "We've mixed two ways of seeing this. Ready for a third next time?",
        "This is your synthesis. Let's test it in our next session.",
        "You found the seam. Let's widen it together.",
    ]

    CONFUSED_CONTINUITY: List[str] = [
        "Don't worry — we'll come back to this.",
        "Confusion is part of learning. Your notebook will remember where we paused.",
        "Let's leave this here and return when your mind is fresher.",
        "No pressure — we'll untangle this together next time.",
        "The knot is tight now, but we'll loosen it together.",
    ]

    REJECTING_CONTINUITY: List[str] = [
        "You pushed back — that's strong thinking. Let's explore why neither fit.",
        "Your rejection is data. Let's find what DOES fit your mind.",
        "Neither side convinced you. That means we need a third way.",
        "Good — you didn't just accept. Let's build something you CAN accept.",
        "Your 'no' is loud. Let's make the 'yes' louder.",
    ]

    @classmethod
    def get_continuity_phrases(cls, stance: str = "vernacular_leaning") -> List[str]:
        """Get continuity phrases for an epistemic stance."""
        mapping = {
            "formal_leaning": cls.FORMAL_CONTINUITY,
            "vernacular_leaning": cls.VERNACULAR_CONTINUITY,
            "synthetic": cls.SYNTHETIC_CONTINUITY,
            "confused": cls.CONFUSED_CONTINUITY,
            "rejecting": cls.REJECTING_CONTINUITY,
        }
        return mapping.get(stance, cls.VERNACULAR_CONTINUITY)


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED ACCESS API (What core files call)
# ═══════════════════════════════════════════════════════════════════════

def get_phrases(
    phrase_type: str,                           # "understanding", "praise", "correction", "continuity"
    thermal_state: str = "hot",                # "hot", "warm", "cool", "cold"
    epistemic_stance: str = "vernacular_leaning",  # from Dialectical Ledger
    student_intimacy_score: Optional[Decimal] = None,  # from PIG
) -> List[str]:
    """
    Get context-aware phrases for any situation.

    This is the ONLY function core files should call for phrase constants.
    """
    if student_intimacy_score is None:
        student_intimacy_score = Decimal("0")

    if phrase_type == "understanding":
        # High intimacy students get personalized praise mixed in
        if student_intimacy_score >= Decimal("6.0"):
            base = ThermalPhraseFactory.get_understanding_phrases(thermal_state)
            intimate = [
                "You've come so far with this — I remember when this confused you.",
                "This is YOUR breakthrough. Not mine. You built this understanding.",
                f"Last time you said this was hard. Look at you now.",
            ]
            return base + intimate
        return ThermalPhraseFactory.get_understanding_phrases(thermal_state)

    elif phrase_type == "praise":
        return ThermalPhraseFactory.get_praise_phrases(thermal_state)

    elif phrase_type == "correction":
        return ThermalPhraseFactory.get_correction_phrases(thermal_state)

    elif phrase_type == "continuity":
        return EpistemicPhraseFactory.get_continuity_phrases(epistemic_stance)

    return []


# ═══════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY (For files that haven't migrated yet)
# ═══════════════════════════════════════════════════════════════════════

# Old combined lists — keep until all imports are updated
UNDERSTANDING_PHRASES = (
    ThermalPhraseFactory.HOT_UNDERSTANDING +
    ThermalPhraseFactory.COOL_UNDERSTANDING
)

CONTINUITY_PHRASES = (
    EpistemicPhraseFactory.VERNACULAR_CONTINUITY +
    EpistemicPhraseFactory.FORMAL_CONTINUITY
)

PRAISE_PHRASES = (
    ThermalPhraseFactory.HOT_PRAISE +
    ThermalPhraseFactory.COOL_PRAISE
)
