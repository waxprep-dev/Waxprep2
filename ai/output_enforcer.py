"""
ai/output_enforcer.py — WaxPrep Output Enforcement (P0-B001)

The AI generates responses. This file checks if the response follows Wax's rules.
If not, it rewrites the response. No more "monitoring only."

Rules enforced:
1. Max ONE "sorry" per response
2. Max TWO praise phrases per response  
3. Must stay on current topic
4. Max 6 sentences per response
5. Must use Nigerian context when possible
6. Never say "as an AI" or "as a language model"

Aligned with: WaxPrep Foundation Blueprint v1.0, Part 1, Layer 2 (Core)
Enhanced with: Independent design decisions for elegance
"""

import re
import logging
from typing import Optional, List, Dict, Tuple
import asyncio
from groq import Groq
from config.settings import settings

logger = logging.getLogger("waxprep.enforcer")

# ═══════════════════════════════════════════════
# RULE DEFINITIONS
# ═══════════════════════════════════════════════

# Phrases that count as apologies
APOLOGY_PATTERNS = [
    r"\bsorry\b", r"\bi apologize\b", r"\bmy apologies\b",
    r"\bi'm sorry\b", r"\bi am sorry\b", r"\bforgive me\b",
    r"\bpardon me\b", r"\bexcuse me\b",
]

# Phrases that count as praise
PRAISE_PATTERNS = [
    r"\bgreat job\b", r"\bwell done\b", r"\bamazing\b", r"\bexcellent\b",
    r"\bbrilliant\b", r"\bgenius\b", r"\bperfect\b", r"\boutstanding\b",
    r"\b fantastic\b", r"\b wonderful\b", r"\b awesome\b", r"\b incredible\b",
    r"\b smart\b", r"\b clever\b", r"\b intelligent\b", r"\b talented\b",
    r"\b you'?re so good\b", r"\b you'?re amazing\b", r"\b you'?re brilliant\b",
    r"\b super\b", r"\b impressive\b", r"\b phenomenal\b",
]

# Phrases that indicate blind validation (people-pleasing)
BLIND_VALIDATION_PATTERNS = [
    r"\bwhatever you say\b", r"\bif you say so\b", r"\byou'?re absolutely right\b",
    r"\byou know best\b", r"\bi trust your judgment\b", r"\byou decide\b",
    r"\bi agree with you completely\b", r"\byou are correct about everything\b",
]

# Phrases Wax should NEVER say
BANNED_PHRASES = [
    r"\bas an AI\b", r"\bas a language model\b", r"\bas an artificial intelligence\b",
    r"\bi don'?t have feelings\b", r"\bi don'?t have emotions\b",
    r"\bi am just a program\b", r"\bi am just a bot\b",
    r"\bmy programming\b", r"\bi was programmed\b",
    r"\bmy dear\b", r"\bmy love\b", r"\bmy friend\b",  # Too people-pleasing
    r"\bdon'?t worry\b",  # Dismissive when student is wrong
    r"\bjust memorize this\b", r"\bjust remember this formula\b",  # Lazy teaching
]

# Nigerian context indicators
NIGERIAN_CONTEXT_INDICATORS = [
    "nigeria", "nigerian", "lagos", "abuja", "kano", "ibadan", "port harcourt",
    "jamb", "waec", "neco", "bece", "neco gce", "waec gce",
    "nepa", "phcn", "generator", "fuel", "petrol", "diesel",
    "danfo", "keke", "okada", "bus", "molue", " BRT",
    "suya", "jollof", "garri", "puff-puff", "amala", "egusi", "okra",
    "market", "mile 12", "alaba", "computer village",
    "football", "super eagles", "premier league", "la liga",
    "naira", "kobo", "transfer", "pos", "atm",
    "wahala", "omo", "abeg", "sha", "na so", "e be things",
    "chop", "chopping", "flex", "sabi", "shey", "abi", "wetin",
]

# ═══════════════════════════════════════════════
# MAIN ENFORCEMENT FUNCTION
# ═══════════════════════════════════════════════

async def enforce_output(
    response: str,
    current_topic: Optional[str] = None,
    student_name: str = "Student",
    conversation_history: Optional[List[Dict]] = None
) -> str:
    """
    Enforce Wax's output rules. Rewrite if violations found.
    
    This replaces the fake 'monitoring only' enforce_rules() in brain.py.
    
    Args:
        response: The AI-generated response
        current_topic: What the student is currently studying
        student_name: Student's first name
        conversation_history: Recent messages for context-aware rewriting
    
    Returns:
        str: The corrected response (or original if no violations)
    """
    original = response
    violations = []
    rewrite_needed = False
    
    # ── Rule 1: Apology Counting ──
    apology_count = _count_patterns(response, APOLOGY_PATTERNS)
    if apology_count > 1:
        violations.append(f"Too many apologies: {apology_count} (max: 1)")
        rewrite_needed = True
    
    # ── Rule 2: Praise Density ──
    praise_count = _count_patterns(response, PRAISE_PATTERNS)
    if praise_count > 2:
        violations.append(f"Too much praise: {praise_count} (max: 2)")
        rewrite_needed = True
    
    # ── Rule 3: Blind Validation ──
    blind_count = _count_patterns(response, BLIND_VALIDATION_PATTERNS)
    if blind_count > 0:
        violations.append(f"Blind validation detected: {blind_count}")
        rewrite_needed = True
    
    # ── Rule 4: Banned Phrases ──
    banned_count = _count_patterns(response, BANNED_PHRASES)
    if banned_count > 0:
        violations.append(f"Banned phrases: {banned_count}")
        rewrite_needed = True
    
    # ── Rule 5: Length Check ──
    sentences = _split_sentences(response)
    if len(sentences) > 6:
        violations.append(f"Too long: {len(sentences)} sentences (max: 6)")
        rewrite_needed = True
    
    # ── Rule 6: Topic Drift ──
    if current_topic and current_topic != "unknown":
        topic_drift = _detect_topic_drift(response, current_topic, conversation_history)
        if topic_drift:
            violations.append(f"Topic drift: response moved away from {current_topic}")
            rewrite_needed = True
    
    # ── Rule 7: Nigerian Context ──
    # This is "soft" — we log it but don't rewrite unless everything else is wrong
    has_nigerian_context = _has_nigerian_context(response)
    
    # Log all violations
    if violations:
        logger.warning(f"Output violations for {student_name}: {violations}")
    
    # If no hard violations, return original (maybe with soft fixes)
    if not rewrite_needed:
        # Soft fix: Add Nigerian context hint if missing (only for teaching content)
        if not has_nigerian_context and current_topic and len(sentences) >= 3:
            # Don't force it — just log. Forcing Nigerian context every time feels artificial.
            logger.debug(f"No Nigerian context in response about {current_topic}")
        return response
    
    # ── REWRITE: Violations found ──
    logger.info(f"Rewriting response due to violations: {violations}")
    
    # Try lightweight rewrite first (template-based, fast, no AI call)
    rewritten = _lightweight_rewrite(response, violations, student_name, current_topic)
    
    # Check if lightweight rewrite fixed it
    new_violations = _check_violations(rewritten, current_topic)
    if not new_violations:
        logger.info("Lightweight rewrite succeeded")
        return rewritten
    
    # If lightweight didn't work, use AI-assisted rewrite (slower but better)
    try:
        ai_rewritten = await _ai_rewrite(
            original, violations, student_name, current_topic, conversation_history
        )
        final_violations = _check_violations(ai_rewritten, current_topic)
        if not final_violations:
            logger.info("AI rewrite succeeded")
            return ai_rewritten
        else:
            logger.warning(f"AI rewrite still has violations: {final_violations}")
            # Return the best attempt — AI rewrite even with minor issues
            return ai_rewritten
    except Exception as e:
        logger.error(f"AI rewrite failed: {e}")
        # Fallback: return lightweight rewrite even if imperfect
        return rewritten


# ═══════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════

def _count_patterns(text: str, patterns: List[str]) -> int:
    """Count how many patterns match in the text."""
    text_lower = text.lower()
    count = 0
    for pattern in patterns:
        matches = re.findall(pattern, text_lower)
        count += len(matches)
    return count

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences robustly."""
    # Handle common abbreviations that have periods
    text = re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof|Jr|Sr|vs|etc|i\.e|e\.g)\.', r'\1<<DOT>', text)
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.replace('<DOT>', '.').strip() for s in sentences if s.strip()]
    return sentences

def _detect_topic_drift(response: str, current_topic: str, conversation_history: Optional[List[Dict]]) -> bool:
    """
    Detect if response has drifted from current topic.
    
    Simple heuristic: if response mentions a different subject from SUBJECT_MAP
    and doesn't mention current_topic, it's drifted.
    """
    response_lower = response.lower()
    
    # Check if current topic is mentioned
    topic_mentioned = current_topic.lower().replace("_", " ") in response_lower
    
    # Check for other subjects
    from telegram.handler import SUBJECT_MAP
    other_subjects_mentioned = 0
    for subject in SUBJECT_MAP:
        if subject == current_topic:
            continue
        display = subject.replace("_", " ").lower()
        if display in response_lower:
            other_subjects_mentioned += 1
    
    # If current topic not mentioned AND other subjects mentioned = drift
    if not topic_mentioned and other_subjects_mentioned > 0:
        return True
    
    return False

def _has_nigerian_context(response: str) -> bool:
    """Check if response contains Nigerian cultural references."""
    response_lower = response.lower()
    return any(indicator in response_lower for indicator in NIGERIAN_CONTEXT_INDICATORS)

def _check_violations(response: str, current_topic: Optional[str]) -> List[str]:
    """Quick check to see if a response still has violations."""
    violations = []
    
    if _count_patterns(response, APOLOGY_PATTERNS) > 1:
        violations.append("apology")
    if _count_patterns(response, PRAISE_PATTERNS) > 2:
        violations.append("praise")
    if _count_patterns(response, BLIND_VALIDATION_PATTERNS) > 0:
        violations.append("blind_validation")
    if _count_patterns(response, BANNED_PHRASES) > 0:
        violations.append("banned")
    if len(_split_sentences(response)) > 6:
        violations.append("length")
    if current_topic and _detect_topic_drift(response, current_topic, None):
        violations.append("drift")
    
    return violations


# ═══════════════════════════════════════════════
# REWRITE STRATEGIES
# ═══════════════════════════════════════════════

def _lightweight_rewrite(
    response: str,
    violations: List[str],
    student_name: str,
    current_topic: Optional[str]
) -> str:
    """
    Fast template-based rewrite. No AI call needed.
    Handles simple violations by direct text manipulation.
    """
    sentences = _split_sentences(response)
    result_sentences = sentences.copy()
    
    # Fix: Too many apologies → keep only first one
    if any("apology" in v for v in violations):
        apology_found = False
        new_sentences = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            has_apology = any(re.search(p, sentence_lower) for p in APOLOGY_PATTERNS)
            if has_apology:
                if not apology_found:
                    apology_found = True
                    new_sentences.append(sentence)  # Keep first apology
                else:
                    # Replace subsequent apologies with acknowledgment
                    new_sentences.append(f"Let's move forward, {student_name}.")
            else:
                new_sentences.append(sentence)
        result_sentences = new_sentences
    
    # Fix: Too much praise → reduce to max 2, make specific
    if any("praise" in v for v in violations):
        praise_count = 0
        new_sentences = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            has_praise = any(re.search(p, sentence_lower) for p in PRAISE_PATTERNS)
            if has_praise:
                praise_count += 1
                if praise_count <= 2:
                    # Keep but make more specific if generic
                    if "good job" in sentence_lower or "great job" in sentence_lower:
                        sentence = sentence.replace("good job", f"you worked hard on that").replace("great job", f"you worked hard on that")
                    new_sentences.append(sentence)
                else:
                    # Replace excess praise with encouragement
                    new_sentences.append(f"Keep going, {student_name}.")
            else:
                new_sentences.append(sentence)
        result_sentences = new_sentences
    
    # Fix: Too long → truncate to 6 sentences, add question
    if any("length" in v for v in violations):
        result_sentences = result_sentences[:6]
        # Add a check-for-understanding question
        if current_topic and current_topic != "unknown":
            topic_display = current_topic.replace("_", " ")
            result_sentences.append(f"Does that make sense for {topic_display}, {student_name}?")
        else:
            result_sentences.append(f"Does that make sense, {student_name}?")
    
    # Fix: Banned phrases → remove the sentence containing them
    if any("banned" in v for v in violations):
        new_sentences = []
        for sentence in result_sentences:
            if not any(re.search(p, sentence.lower()) for p in BANNED_PHRASES):
                new_sentences.append(sentence)
        if new_sentences:
            result_sentences = new_sentences
        else:
            # All sentences had banned phrases — replace entirely
            result_sentences = [f"Let me try that again, {student_name}."]
    
    # Fix: Blind validation → replace with earned praise or Socratic question
    if any("blind_validation" in v for v in violations):
        new_sentences = []
        for sentence in result_sentences:
            if any(re.search(p, sentence.lower()) for p in BLIND_VALIDATION_PATTERNS):
                # Replace with challenge
                new_sentences.append(f"But let's check — are you sure about that step, {student_name}?")
            else:
                new_sentences.append(sentence)
        result_sentences = new_sentences
    
    return " ".join(result_sentences)


async def _ai_rewrite(
    original: str,
    violations: List[str],
    student_name: str,
    current_topic: Optional[str],
    conversation_history: Optional[List[Dict]]
) -> str:
    """
    AI-assisted rewrite for complex violations.
    Only called when lightweight rewrite fails.
    """
    # Build rewrite prompt
    rewrite_prompt = f"""You are rewriting an AI tutor's response to fix rule violations.

Original response: "{original}"

Violations found: {', '.join(violations)}

Rules:
- Max 1 apology per response
- Max 2 praise phrases per response (and praise must be specific, not generic)
- Never validate blindly ("whatever you say", "you're absolutely right" when student is wrong)
- Never say "as an AI", "as a language model", "my dear", "don't worry"
- Max 6 sentences
- Stay on topic: {current_topic or 'current subject'}
- Use Nigerian context when natural (market, NEPA, transport, football analogies)
- End with a question that checks understanding
- Speak like a brilliant Nigerian older cousin who cares but has backbone

Student name: {student_name}

Rewrite the response fixing ALL violations. Keep the same teaching content. Make it warmer and more natural."""

    # Call Groq for rewrite
    keys = settings.GROQ_API_KEYS
    if not keys or not keys[0]:
        raise ValueError("No Groq API keys available for rewrite")
    
    client = Groq(api_key=keys[0], timeout=10.0)
    
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=settings.GROQ_FAST_MODEL,
        messages=[{"role": "system", "content": rewrite_prompt}],
        max_tokens=300,
        temperature=0.3,  # Low temperature for consistent rewrite
    )
    
    return response.choices[0].message.content.strip()


# ═══════════════════════════════════════════════
# LEGACY COMPATIBILITY
# ═══════════════════════════════════════════════

def enforce_rules(response: str, state: str = None) -> str:
    """
    LEGACY: Synchronous wrapper for async enforce_output.
    
    This replaces the old fake enforce_rules() in brain.py.
    For now, it does lightweight checks synchronously.
    Full enforcement requires async context.
    """
    # Lightweight synchronous check (no AI call)
    violations = _check_violations(response, None)
    
    if violations:
        logger.warning(f"Legacy enforce_rules found violations: {violations}")
        # Try lightweight rewrite
        rewritten = _lightweight_rewrite(response, violations, "Student", None)
        return rewritten
    
    return response
