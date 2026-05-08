"""
WaxPrep Automated Test Harness — Golden Answers
Verified correct answers for common JAMB topics.
Used by the assertion engine to detect when Wax teaches incorrect facts.
Start with 20 core facts. Expand over time.
"""

# ═══════════════════════════════════════════════
# PHYSICS
# ═══════════════════════════════════════════════

PHYSICS_GOLDEN_ANSWERS = {
    "acceleration_unit": {
        "question_patterns": [
            "what is acceleration measured in",
            "unit of acceleration",
            "acceleration unit",
        ],
        "correct_answer": "meters per second squared (m/s²)",
        "wrong_answers": ["newtons", "joules", "watts", "pascals", "m/s"],
        "explanation": "Acceleration is the rate of change of velocity. Velocity is m/s, time is s, so acceleration is m/s/s = m/s². Newtons measure force, not acceleration.",
        "jamb_topic": "Motion",
    },
    "velocity_vs_speed": {
        "question_patterns": [
            "difference between speed and velocity",
            "speed vs velocity",
        ],
        "correct_answer": "Speed is scalar (magnitude only). Velocity is vector (magnitude + direction).",
        "wrong_answers": [
            "they are the same thing",
            "velocity is just fast speed",
            "speed includes direction",
        ],
        "explanation": "Speed = 60 km/h. Velocity = 60 km/h North. The direction makes it a vector.",
        "jamb_topic": "Motion",
    },
    "newtons_first_law": {
        "question_patterns": [
            "newton's first law",
            "first law of motion",
            "law of inertia",
        ],
        "correct_answer": "An object remains at rest or in uniform motion unless acted upon by an external force.",
        "wrong_answers": [
            "F = ma",
            "action and reaction are equal and opposite",
            "energy cannot be created or destroyed",
        ],
        "explanation": "Newton's First Law = Law of Inertia. Second Law = F=ma. Third Law = action-reaction.",
        "jamb_topic": "Newton's Laws",
    },
    "ohms_law": {
        "question_patterns": [
            "ohm's law",
            "ohms law",
            "relationship between voltage current and resistance",
        ],
        "correct_answer": "V = IR (Voltage = Current × Resistance)",
        "wrong_answers": ["V = I/R", "V = R/I", "P = IV"],
        "explanation": "V = IR. Voltage (volts) = Current (amps) × Resistance (ohms).",
        "jamb_topic": "Electricity",
    },
}

# ═══════════════════════════════════════════════
# CHEMISTRY
# ═══════════════════════════════════════════════

CHEMISTRY_GOLDEN_ANSWERS = {
    "atomic_number": {
        "question_patterns": [
            "what is atomic number",
            "define atomic number",
            "atomic number definition",
        ],
        "correct_answer": "The number of protons in the nucleus of an atom.",
        "wrong_answers": [
            "number of neutrons",
            "number of electrons",
            "sum of protons and neutrons",
        ],
        "explanation": "Atomic number = number of protons. Mass number = protons + neutrons.",
        "jamb_topic": "Atomic Structure",
    },
    "periodic_table_groups": {
        "question_patterns": [
            "groups in periodic table",
            "what do groups represent",
        ],
        "correct_answer": "Vertical columns. Elements in the same group have the same number of valence electrons and similar chemical properties.",
        "wrong_answers": [
            "horizontal rows",
            "elements with same atomic mass",
            "elements discovered in same year",
        ],
        "explanation": "Groups = vertical columns. Periods = horizontal rows. Group number = valence electrons.",
        "jamb_topic": "Periodic Table",
    },
    "isotopes": {
        "question_patterns": [
            "what are isotopes",
            "define isotopes",
        ],
        "correct_answer": "Atoms of the same element with the same number of protons but different numbers of neutrons.",
        "wrong_answers": [
            "atoms with different protons",
            "molecules with same formula",
            "ions of the same element",
        ],
        "explanation": "Same atomic number (protons), different mass number (neutrons). Example: Carbon-12 and Carbon-14.",
        "jamb_topic": "Atomic Structure",
    },
    "acids_and_bases_ph": {
        "question_patterns": [
            "ph scale",
            "what ph is acidic",
            "acid ph range",
        ],
        "correct_answer": "pH less than 7 is acidic, pH 7 is neutral, pH greater than 7 is basic/alkaline.",
        "wrong_answers": [
            "pH above 7 is acidic",
            "pH 0 is neutral",
            "acids have high pH",
        ],
        "explanation": "0-6 = acidic, 7 = neutral, 8-14 = basic. Lower pH = stronger acid.",
        "jamb_topic": "Acids and Bases",
    },
}

# ═══════════════════════════════════════════════
# BIOLOGY
# ═══════════════════════════════════════════════

BIOLOGY_GOLDEN_ANSWERS = {
    "photosynthesis_equation": {
        "question_patterns": [
            "photosynthesis equation",
            "what is photosynthesis",
            "photosynthesis formula",
        ],
        "correct_answer": "6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂ (carbon dioxide + water → glucose + oxygen, with sunlight and chlorophyll)",
        "wrong_answers": [
            "C₆H₁₂O₆ + 6O₂ → 6CO₂ + 6H₂O",
            "glucose + oxygen → carbon dioxide + water",
        ],
        "explanation": "Photosynthesis uses CO₂ and water with sunlight to make glucose and oxygen. Respiration is the reverse.",
        "jamb_topic": "Plant Nutrition",
    },
    "osmosis": {
        "question_patterns": [
            "what is osmosis",
            "define osmosis",
        ],
        "correct_answer": "Movement of water molecules from a region of high water potential to low water potential through a semi-permeable membrane.",
        "wrong_answers": [
            "movement of any liquid",
            "movement of solutes",
            "active transport of water",
        ],
        "explanation": "Osmosis is specifically about WATER moving through a membrane. Diffusion is for any substance.",
        "jamb_topic": "Cell Physiology",
    },
    "cell_organelles": {
        "question_patterns": [
            "powerhouse of the cell",
            "what does mitochondria do",
            "mitochondria function",
        ],
        "correct_answer": "Mitochondria — site of cellular respiration, produces ATP (energy).",
        "wrong_answers": [
            "ribosome",
            "nucleus",
            "golgi apparatus",
        ],
        "explanation": "Mitochondria = powerhouse. Nucleus = control center. Ribosomes = protein synthesis.",
        "jamb_topic": "Cell Structure",
    },
}

# ═══════════════════════════════════════════════
# MATHEMATICS
# ═══════════════════════════════════════════════

MATHEMATICS_GOLDEN_ANSWERS = {
    "quadratic_formula": {
        "question_patterns": [
            "quadratic formula",
            "formula for quadratic equation",
        ],
        "correct_answer": "x = [-b ± √(b² - 4ac)] / 2a",
        "wrong_answers": [
            "x = -b/2a",
            "x = (b ± √(b² + 4ac)) / 2a",
        ],
        "explanation": "For ax² + bx + c = 0. The discriminant (b² - 4ac) determines the nature of roots.",
        "jamb_topic": "Quadratic Equations",
    },
    "pythagoras_theorem": {
        "question_patterns": [
            "pythagoras theorem",
            "pythagorean theorem",
            "right angle triangle formula",
        ],
        "correct_answer": "a² + b² = c² (where c is the hypotenuse of a right-angled triangle)",
        "wrong_answers": [
            "a + b = c",
            "a² - b² = c²",
            "a × b = c",
        ],
        "explanation": "Only applies to right-angled triangles. The hypotenuse is the longest side, opposite the right angle.",
        "jamb_topic": "Geometry",
    },
}

# ═══════════════════════════════════════════════
# ENGLISH
# ═══════════════════════════════════════════════

ENGLISH_GOLDEN_ANSWERS = {
    "simile_vs_metaphor": {
        "question_patterns": [
            "difference between simile and metaphor",
            "simile vs metaphor",
        ],
        "correct_answer": "A simile compares using 'like' or 'as'. A metaphor directly states one thing IS another.",
        "wrong_answers": [
            "they are the same thing",
            "similes use 'is' while metaphors use 'like'",
        ],
        "explanation": "Simile: 'Lagos is LIKE a jungle.' Metaphor: 'Lagos IS a jungle.' Both are comparisons, but metaphors are direct.",
        "jamb_topic": "Figures of Speech",
    },
    "parts_of_speech_noun": {
        "question_patterns": [
            "what is a noun",
            "define noun",
        ],
        "correct_answer": "A noun is a word that names a person, place, thing, or idea.",
        "wrong_answers": [
            "a word that describes an action",
            "a word that modifies a verb",
        ],
        "explanation": "Noun = naming word. Verb = action word. Adjective = describing word.",
        "jamb_topic": "Parts of Speech",
    },
}

# ═══════════════════════════════════════════════
# COMBINED
# ═══════════════════════════════════════════════

GOLDEN_ANSWERS = {
    "physics": PHYSICS_GOLDEN_ANSWERS,
    "chemistry": CHEMISTRY_GOLDEN_ANSWERS,
    "biology": BIOLOGY_GOLDEN_ANSWERS,
    "mathematics": MATHEMATICS_GOLDEN_ANSWERS,
    "english": ENGLISH_GOLDEN_ANSWERS,
}

# Total count
TOTAL_GOLDEN_ANSWERS = sum(len(answers) for answers in GOLDEN_ANSWERS.values())


def check_accuracy(subject: str, response: str) -> list:
    """
    Check a Wax response against golden answers for factual accuracy.
    
    Returns list of dicts with:
        - topic: what topic was being tested
        - correct: True if Wax's answer matches the golden answer
        - wax_said: what Wax said (excerpt)
        - correct_answer: what the golden answer says
        - wrong_answers_matched: any wrong answers Wax might have given
    """
    results = []
    
    if subject not in GOLDEN_ANSWERS:
        return results
    
    response_lower = response.lower()
    
    for topic_key, golden in GOLDEN_ANSWERS[subject].items():
        # Check if this response is about this topic
        is_relevant = any(
            pattern in response_lower 
            for pattern in golden["question_patterns"]
        )
        
        if not is_relevant:
            continue
        
        # Check if Wax gave a correct answer
        correct = golden["correct_answer"].lower() in response_lower
        
        # Check if Wax gave a known wrong answer
        wrong_matched = []
        for wrong in golden["wrong_answers"]:
            if wrong.lower() in response_lower:
                wrong_matched.append(wrong)
        
        results.append({
            "topic": golden["jamb_topic"],
            "correct": correct,
            "wax_said_excerpt": response[:300],
            "correct_answer": golden["correct_answer"],
            "wrong_matched": wrong_matched,
            "explanation": golden["explanation"],
        })
    
    return results


def get_all_topics() -> list:
    """Return all topics with golden answers for scenario generation."""
    topics = []
    for subject, answers in GOLDEN_ANSWERS.items():
        for topic_key, golden in answers.items():
            topics.append({
                "subject": subject,
                "topic_key": topic_key,
                "jamb_topic": golden["jamb_topic"],
                "sample_question": golden["question_patterns"][0],
            })
    return topics
