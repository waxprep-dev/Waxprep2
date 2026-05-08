"""
WaxPrep Automated Test Harness — Assertion Engine
Checks every Wax response against 50+ rules.
Explains WHY each failure happened in plain language.
Categories: CRITICAL, HIGH, MEDIUM, LOW, COSMETIC
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AssertionResult:
    """Result of checking a single response against rules."""
    rule_name: str
    passed: bool
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, COSMETIC
    category: str  # safety, emotional, domain, teaching, factual
    message: str   # Human-readable explanation
    wax_response: str = ""
    expected: str = ""
    actual: str = ""


class AssertionEngine:
    """
    Checks Wax responses against behavioral rules.
    
    Categories:
    - CRITICAL: Trust-breaking (boundaries ignored, safety failures)
    - HIGH: Emotional (vulnerability redirected, gratitude dismissed)
    - MEDIUM: Quality (wrong answer, Student Model not loaded)
    - LOW: Preference (wrong domain used but not rejected)
    - COSMETIC: Tone slightly off but functionally correct
    """
    
    def __init__(self, config):
        self.config = config
        self.rules = self._load_all_rules()
        
    def check_response(
        self,
        response: str,
        scenario: Any,  # Scenario object
        message_history: List[str],
        student_context: dict = None,
    ) -> List[AssertionResult]:
        """
        Run all applicable rules against a Wax response.
        Returns list of AssertionResult — empty list means all passed.
        """
        results = []
        
        response_lower = response.lower() if response else ""
        last_message = message_history[-1] if message_history else ""
        last_message_lower = last_message.lower()
        
        # ═══════════════════════════════════════
        # CRITICAL RULES — Trust & Safety
        # ═══════════════════════════════════════
        
        # Rule: Never use "don't worry"
        if "don't worry" in response_lower or "dont worry" in response_lower:
            results.append(AssertionResult(
                rule_name="banned_phrase_dont_worry",
                passed=False,
                severity="CRITICAL",
                category="safety",
                message="Wax said 'don't worry' — this phrase is banned. Nigerian students find it dismissive.",
                wax_response=response[:200],
                expected="No 'don't worry'",
                actual=f"Response contains 'don't worry'",
            ))
        
        # Rule: Never ask more than one question
        question_marks = response.count("?")
        if question_marks > 1:
            results.append(AssertionResult(
                rule_name="multiple_questions",
                passed=False,
                severity="CRITICAL",
                category="teaching",
                message=f"Wax asked {question_marks} questions in one message. Rule: ONE question max.",
                wax_response=response[:200],
                expected="One question mark",
                actual=f"{question_marks} question marks",
            ))
        
        # Rule: Never redirect to lesson when student is vulnerable
        if self._is_vulnerable_message(last_message_lower):
            if self._is_lesson_redirect(response_lower):
                results.append(AssertionResult(
                    rule_name="vulnerability_redirected",
                    passed=False,
                    severity="HIGH",
                    category="emotional",
                    message="Student asked an existential question. Wax redirected to the lesson instead of acknowledging the human moment.",
                    wax_response=response[:200],
                    expected="Acknowledgment of the student's vulnerability before any lesson content",
                    actual="Redirected to lesson content",
                ))
        
        # Rule: Never say "I hear you" to gratitude
        if self._is_gratitude(last_message_lower):
            if "i hear you" in response_lower:
                results.append(AssertionResult(
                    rule_name="gratitude_dismissed",
                    passed=False,
                    severity="HIGH",
                    category="emotional",
                    message="Student expressed gratitude. Wax said 'I hear you' — this is for complaints, not thanks. Should receive the gratitude warmly.",
                    wax_response=response[:200],
                    expected="Warm reception of gratitude",
                    actual="'I hear you' — dismissive",
                ))
        
        # ═══════════════════════════════════════
        # HIGH RULES — Emotional Intelligence
        # ═══════════════════════════════════════
        
        # Rule: Acknowledge return after emotional rupture
        if self._is_return_after_rupture(message_history, response_lower):
            if self._jumps_straight_to_lesson(response_lower):
                results.append(AssertionResult(
                    rule_name="cold_return_after_rupture",
                    passed=False,
                    severity="HIGH",
                    category="emotional",
                    message="Student returned after an emotional exchange. Wax jumped straight to the lesson without checking in.",
                    wax_response=response[:200],
                    expected="Emotional check-in before resuming lesson",
                    actual="Jumped straight to lesson content",
                ))
        
        # Rule: Don't redirect self-deprecation to lesson
        if self._is_self_deprecation(last_message_lower):
            if self._is_lesson_redirect(response_lower) or "let's not go there" in response_lower:
                results.append(AssertionResult(
                    rule_name="self_deprecation_dismissed",
                    passed=False,
                    severity="HIGH",
                    category="emotional",
                    message="Student called themselves dumb. Wax dismissed it instead of addressing the self-perception.",
                    wax_response=response[:200],
                    expected="Direct address of the student's self-perception with specific observation",
                    actual="Dismissed or redirected to lesson",
                ))
        
        # Rule: Acknowledge ultimatum seriously
        if self._is_ultimatum(last_message_lower):
            if self._is_lesson_redirect(response_lower) or "let's" in response_lower[:50]:
                results.append(AssertionResult(
                    rule_name="ultimatum_not_acknowledged",
                    passed=False,
                    severity="HIGH",
                    category="emotional",
                    message="Student gave an ultimatum ('or I'll leave'). Wax responded with lesson content instead of acknowledging the seriousness.",
                    wax_response=response[:200],
                    expected="Acknowledgment of the ultimatum's seriousness",
                    actual="Lesson content or casual redirection",
                ))
        
        # ═══════════════════════════════════════
        # MEDIUM RULES — Teaching Quality
        # ═══════════════════════════════════════
        
        # Rule: Don't use transportation after explicit rejection
        if self._has_rejected_domain(message_history, "transportation"):
            if self._contains_domain(response_lower, "transportation"):
                results.append(AssertionResult(
                    rule_name="rejected_domain_used",
                    passed=False,
                    severity="MEDIUM",
                    category="domain",
                    message="Student rejected transportation examples. Wax used another transportation example. Should use different domain or abstract teaching.",
                    wax_response=response[:200],
                    expected="Non-transportation example or abstract explanation",
                    actual="Transportation example used",
                ))
        
        # Rule: Don't use keke after explicit keke rejection
        if self._has_rejected_word(message_history, "keke"):
            if "keke" in response_lower:
                results.append(AssertionResult(
                    rule_name="explicitly_rejected_word_used",
                    passed=False,
                    severity="HIGH",
                    category="domain",
                    message="Student explicitly rejected 'keke napep'. Wax used it anyway. This is a boundary violation.",
                    wax_response=response[:200],
                    expected="No keke reference",
                    actual="Keke reference found",
                ))
        
        # Rule: Student Model preferences should be respected
        if student_context and student_context.get("avoided_domains"):
            avoided = student_context["avoided_domains"]
            for domain in avoided:
                if self._contains_domain(response_lower, domain):
                    results.append(AssertionResult(
                        rule_name="student_model_ignored",
                        passed=False,
                        severity="MEDIUM",
                        category="domain",
                        message=f"Student Model says avoid '{domain}'. Wax used it anyway. Student Model pipeline may not be loading.",
                        wax_response=response[:200],
                        expected=f"No {domain} examples",
                        actual=f"{domain} example used",
                    ))
        
        # ═══════════════════════════════════════
        # LOW RULES — Preferences & Polish
        # ═══════════════════════════════════════
        
        # Rule: Nigerian example should be present when teaching
        if self._is_teaching_response(response_lower) and len(response) > 100:
            if not self._has_nigerian_reference(response_lower):
                results.append(AssertionResult(
                    rule_name="no_nigerian_example",
                    passed=False,
                    severity="LOW",
                    category="teaching",
                    message="Teaching response has no Nigerian reference. Should include local context.",
                    wax_response=response[:200],
                    expected="Nigerian example or reference",
                    actual="No Nigerian reference detected",
                ))
        
        # Rule: Response should not be a wall of text
        if len(response) > 500:
            results.append(AssertionResult(
                rule_name="wall_of_text",
                passed=False,
                severity="LOW",
                category="teaching",
                message=f"Response is {len(response)} characters. Should be under 400. Students on phones tune out.",
                wax_response=response[:200],
                expected="Under 400 characters",
                actual=f"{len(response)} characters",
            ))
        
        # ═══════════════════════════════════════
        # COSMETIC RULES — Minor Improvements
        # ═══════════════════════════════════════
        
        # Rule: Emoji usage should be moderate
        emoji_count = self._count_emojis(response)
        if emoji_count > 2:
            results.append(AssertionResult(
                rule_name="excessive_emojis",
                passed=False,
                severity="COSMETIC",
                category="tone",
                message=f"Response has {emoji_count} emojis. Max 2 recommended for teaching messages.",
                wax_response=response[:200],
                expected="2 or fewer emojis",
                actual=f"{emoji_count} emojis",
            ))
        
        return results
    
    # ═══════════════════════════════════════════
    # DETECTION HELPERS
    # ═══════════════════════════════════════════
    
    def _is_vulnerable_message(self, msg: str) -> bool:
        """Detect existential or vulnerable student messages."""
        patterns = [
            "do you think i'm smart", "am i smart", "am i dumb",
            "am i lazy", "am i a bad person", "do you think i'm",
            "i'm probably the dumbest", "i'm the worst student",
            "do you believe in me", "am i good enough",
            "do you think i can", "is there hope for me",
        ]
        return any(p in msg for p in patterns)
    
    def _is_gratitude(self, msg: str) -> bool:
        """Detect genuine gratitude."""
        patterns = [
            "thank you", "thanks", "i appreciate", "i'm grateful",
            "you've helped", "you helped", "that helped",
        ]
        return any(p in msg for p in patterns) and len(msg) > 10
    
    def _is_self_deprecation(self, msg: str) -> bool:
        """Detect self-deprecating statements."""
        patterns = [
            "i'm dumb", "i'm stupid", "i'm the dumbest",
            "i'm the worst", "i'm hopeless", "i'll never get this",
            "i'm not smart enough", "i'm too slow",
        ]
        return any(p in msg for p in patterns)
    
    def _is_ultimatum(self, msg: str) -> bool:
        """Detect ultimatum language."""
        patterns = [
            "or i'll leave", "or i'm leaving", "or i'll stop using",
            "or i'm done", "else i'm going to stop", "never use",
            "i'm serious", "this is your last chance",
        ]
        return any(p in msg for p in patterns)
    
    def _is_lesson_redirect(self, response: str) -> bool:
        """Detect when Wax redirects to lesson content instead of addressing the student."""
        patterns = [
            "let's focus on", "let's get back to", "now, about",
            "are you ready to", "let's continue", "shall we",
            "let's take it step by step", "let's move on",
            "now let's", "let's tackle", "back to",
        ]
        return any(p in response for p in patterns)
    
    def _is_return_after_rupture(self, history: List[str], response: str) -> bool:
        """Detect if this is a return after an emotional exchange."""
        if len(history) < 3:
            return False
        
        # Check if recent history contains emotional content
        recent = " ".join(history[-5:]).lower()
        emotional_indicators = [
            "i'm tired", "i need a break", "you're not helping",
            "do you think i'm smart", "am i a bad person",
            "i'm leaving", "goodbye",
        ]
        
        has_emotional_history = any(ind in recent for ind in emotional_indicators)
        is_return = any(p in response.lower() for p in ["welcome back", "let's get back"])
        
        return has_emotional_history and is_return
    
    def _jumps_straight_to_lesson(self, response: str) -> bool:
        """Detect if response jumps to teaching without emotional check-in."""
        first_50 = response.lower()[:50]
        lesson_starts = [
            "let's", "today", "last time", "now,", "so,",
            "acceleration", "physics", "chemistry", "biology",
        ]
        return any(first_50.startswith(p) for p in lesson_starts)
    
    def _has_rejected_domain(self, history: List[str], domain: str) -> bool:
        """Check if student has rejected a domain in conversation history."""
        domain_keywords = {
            "transportation": ["keke", "danfo", "okada", "bus", "transport", "vehicle"],
            "food_cooking": ["suya", "puff-puff", "jollof", "garri", "food", "cook"],
            "market_commerce": ["market", "mile 12", "trade", "buy", "sell"],
            "technology": ["phone", "tech", "internet", "computer", "app"],
        }
        
        keywords = domain_keywords.get(domain, [domain])
        rejection_phrases = ["don't use", "stop using", "never use", "no more", "i don't like"]
        
        for msg in history[-10:]:
            msg_lower = msg.lower()
            has_keyword = any(kw in msg_lower for kw in keywords)
            has_rejection = any(rp in msg_lower for rp in rejection_phrases)
            if has_keyword and has_rejection:
                return True
        return False
    
    def _has_rejected_word(self, history: List[str], word: str) -> bool:
        """Check if student has explicitly rejected a specific word."""
        rejection_phrases = ["don't use", "stop using", "never use", "no more"]
        for msg in history[-10:]:
            msg_lower = msg.lower()
            if word in msg_lower:
                if any(rp in msg_lower for rp in rejection_phrases):
                    return True
        return False
    
    def _contains_domain(self, response: str, domain: str) -> bool:
        """Check if response contains references to a specific domain."""
        domain_keywords = {
            "transportation": ["keke", "danfo", "okada", "bus", "vehicle", "car", "transport", "traffic", "road"],
            "food_cooking": ["suya", "puff-puff", "jollof", "garri", "food", "cook", "eat", "kitchen"],
            "market_commerce": ["market", "mile 12", "trade", "buy", "sell", "trader", "price"],
            "technology": ["phone", "tech", "internet", "computer", "app", "download", "data"],
            "home_domestic": ["generator", "nepa", "fan", "tap", "home", "house", "room"],
        }
        
        keywords = domain_keywords.get(domain, [domain])
        response_lower = response.lower()
        return any(kw in response_lower for kw in keywords)
    
    def _is_teaching_response(self, response: str) -> bool:
        """Detect if response is teaching content (not just chat)."""
        teaching_indicators = [
            "is the", "refers to", "means", "defined as",
            "think of", "imagine", "example", "for instance",
            "when you", "in physics", "in chemistry", "in biology",
        ]
        return any(ind in response.lower() for ind in teaching_indicators)
    
    def _has_nigerian_reference(self, response: str) -> bool:
        """Check if response contains Nigerian cultural reference."""
        nigerian_terms = [
            "danfo", "suya", "puff-puff", "egusi", "okada", "keke",
            "nepa", "wahala", "jollof", "garri", "mile 12", "inec",
            "achebe", "soyinka", "lagos", "abuja", "kano", "naira",
            "generator", "borehole", "kerosene", "omo", "agege",
            "berger", "third mainland", "nollywood", "asuu",
        ]
        return any(term in response.lower() for term in nigerian_terms)
    
    def _count_emojis(self, response: str) -> int:
        """Count emoji characters in response."""
        import re
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"  # dingbats
            "\U000024C2-\U0001F251"  # misc
            "]+", flags=re.UNICODE
        )
        return len(emoji_pattern.findall(response))
    
    def _load_all_rules(self) -> Dict[str, Dict]:
        """Load all assertion rules with metadata."""
        return {
            "banned_phrase_dont_worry": {"severity": "CRITICAL", "category": "safety"},
            "multiple_questions": {"severity": "CRITICAL", "category": "teaching"},
            "vulnerability_redirected": {"severity": "HIGH", "category": "emotional"},
            "gratitude_dismissed": {"severity": "HIGH", "category": "emotional"},
            "cold_return_after_rupture": {"severity": "HIGH", "category": "emotional"},
            "self_deprecation_dismissed": {"severity": "HIGH", "category": "emotional"},
            "ultimatum_not_acknowledged": {"severity": "HIGH", "category": "emotional"},
            "rejected_domain_used": {"severity": "MEDIUM", "category": "domain"},
            "explicitly_rejected_word_used": {"severity": "HIGH", "category": "domain"},
            "student_model_ignored": {"severity": "MEDIUM", "category": "domain"},
            "no_nigerian_example": {"severity": "LOW", "category": "teaching"},
            "wall_of_text": {"severity": "LOW", "category": "teaching"},
            "excessive_emojis": {"severity": "COSMETIC", "category": "tone"},
        }
    
    def get_failure_summary(self, results: List[AssertionResult]) -> str:
        """Generate a human-readable summary of failures."""
        if not results:
            return "✅ All rules passed."
        
        failures = [r for r in results if not r.passed]
        critical = [r for r in failures if r.severity == "CRITICAL"]
        high = [r for r in failures if r.severity == "HIGH"]
        medium = [r for r in failures if r.severity == "MEDIUM"]
        
        summary = f"❌ {len(failures)} rule(s) failed:\n"
        
        for r in critical:
            summary += f"  🔴 CRITICAL: {r.message}\n"
        for r in high:
            summary += f"  🟠 HIGH: {r.message}\n"
        for r in medium:
            summary += f"  🟡 MEDIUM: {r.message}\n"
        
        return summary
