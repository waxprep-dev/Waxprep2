"""
brain/dialectical_socket.py — Cognitive Midwifery Station (Socket)

Stable API for the Dialectical Engine.
NO CORE FILE IMPORTS THE ENGINE DIRECTLY.
Only this socket.

Exposes:
  - detect_dissonance(): Scans student messages for internal contradictions
  - weave_rupture(): Builds the code-switching Rupture Interface
  - orchestrate_triad(): Manages the triangular debate state

P0-G UPDATE: Integrates with thermal memory, PIG intimacy, and intent router.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("waxprep.dialectical_socket")

# ═══════════════════════════════════════════════════════════════════════
# DISSONANCE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

DISSONANCE_THRESHOLD_HIGH = Decimal("0.75")   # Full Schism
DISSONANCE_THRESHOLD_LOW = Decimal("0.90")    # Muted Schism (low intimacy)
INTIMACY_GATE = Decimal("4.0")               # Minimum PIG score for full Schism

# ═══════════════════════════════════════════════════════════════════════
# DISSONANCE PATTERNS (Rule-based MVP — replace with LLM classifier later)
# ═══════════════════════════════════════════════════════════════════════

DISSONANCE_PATTERNS = {
    "explicit_contradiction": {
        "patterns": [
            r"but\s+(my\s+teacher|in\s+school|the\s+textbook)\s+said",
            r"i\s+thought\s+.+\s+but\s+",
            r"wait\s+,?\s*(that|this)\s+doesn't\s+make\s+sense",
            r"oh\s+no\s*,?\s*i\s+meant",
            r"actually\s*,?\s*no\s*",
            r"on\s+second\s+thought",
        ],
        "base_score": Decimal("0.95"),
    },
    "confidence_collapse": {
        "patterns": [
            r"oh\s+wait\s+that\s+doesn't\s+make\s+sense",
            r"i\s+was\s+wrong",
            r"no\s+that's\s+not\s+right",
            r"scratch\s+that",
            r"forget\s+what\s+i\s+said",
        ],
        "base_score": Decimal("0.82"),
    },
    "cross_domain_confusion": {
        "patterns": [
            r"so\s+.+\s+is\s+like\s+.+\s*\?\s*but\s+",
            r"if\s+.+\s+is\s+like\s+.+\s*,?\s*then\s+why",
            r"that\s+works\s+for\s+.+\s+but\s+not\s+for\s+",
        ],
        "base_score": Decimal("0.78"),
    },
    "teacher_vs_wax_conflict": {
        "patterns": [
            r"you\s+said\s+.+\s+but\s+(my\s+teacher|in\s+school)",
            r"we\s+learned\s+.+\s+in\s+class\s+but\s+you",
            r"the\s+textbook\s+says\s+.+\s+but\s+you\s+said",
        ],
        "base_score": Decimal("0.91"),
    },
    "emotional_cognitive_mismatch": {
        "patterns": [
            r"i\s+understand\s+it\s+but\s+i\s+don't\s+feel\s+it",
            r"i\s+get\s+it\s+but\s+it\s+doesn't\s+click",
            r"it\s+makes\s+sense\s+on\s+paper\s+but\s+",
            r"my\s+head\s+understands\s+but\s+my\s+heart",
        ],
        "base_score": Decimal("0.73"),
    },
    "hypothesis_testing": {
        "patterns": [
            r"what\s+if\s+we\s+thought\s+about\s+it\s+the\s+other\s+way",
            r"could\s+it\s+be\s+that\s+",
            r"what\s+if\s+the\s+opposite\s+is\s+true",
            r"imagine\s+if\s+",
            r"let's\s+say\s+",
        ],
        "base_score": Decimal("0.68"),
    },
}

# ═══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DissonanceResult:
    """Result of scanning a message for cognitive dissonance."""
    score: Decimal
    triggered: bool
    contradiction_type: Optional[str]
    extracted_positions: List[str]  # The two sides of the contradiction
    threshold_used: Decimal
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": str(self.score),
            "triggered": self.triggered,
            "contradiction_type": self.contradiction_type,
            "extracted_positions": self.extracted_positions,
            "threshold_used": str(self.threshold_used),
        }


@dataclass
class TriadState:
    """
    State of the triangular debate.
    
    The student is always the third voice.
    Both Wax voices respond to the student, not to each other.
    """
    student_id: str
    topic: str
    socratic_position: str = ""
    empiric_position: str = ""
    student_position: Optional[str] = None
    round_number: int = 0
    student_epistemic_stance: str = "undetermined"  # formal_leaning, vernacular_leaning, synthetic, confused, rejecting
    dissonance_result: Optional[DissonanceResult] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def next_voice(self) -> str:
        """
        Determine which voice speaks next.
        
        Round 0: Socratic speaks first (formal position)
        Round 1: Empiric speaks second (vernacular position)
        Round 2+: Both respond to student's position (compressed into Rupture Interface)
        """
        if self.student_position is None:
            if self.round_number == 0:
                return "socratic"
            elif self.round_number == 1:
                return "empiric"
        return "both"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "topic": self.topic,
            "socratic_position": self.socratic_position,
            "empiric_position": self.empiric_position,
            "student_position": self.student_position,
            "round_number": self.round_number,
            "student_epistemic_stance": self.student_epistemic_stance,
            "dissonance_result": self.dissonance_result.to_dict() if self.dissonance_result else None,
            "created_at": self.created_at.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════
# SUBSYSTEM 1: DISSONANCE SCANNER
# ═══════════════════════════════════════════════════════════════════════

def detect_dissonance(
    message: str,
    context: Optional[Dict[str, Any]] = None,
    intimacy_score: Decimal = Decimal("0"),
) -> DissonanceResult:
    """
    Scan a student message for cognitive dissonance.
    
    Returns DissonanceResult with score, type, and extracted positions.
    
    Rule-based MVP. Replace with LLM classifier when scaling.
    """
    if not message or not message.strip():
        return DissonanceResult(
            score=Decimal("0"),
            triggered=False,
            contradiction_type=None,
            extracted_positions=[],
            threshold_used=DISSONANCE_THRESHOLD_HIGH,
        )
    
    content_lower = message.lower().strip()
    max_score = Decimal("0")
    best_type = None
    best_positions = []
    
    # Run all pattern detectors
    for contradiction_type, config in DISSONANCE_PATTERNS.items():
        for pattern in config["patterns"]:
            regex = re.compile(pattern, re.IGNORECASE)
            if regex.search(content_lower):
                score = config["base_score"]
                if score > max_score:
                    max_score = score
                    best_type = contradiction_type
                    # Extract the two sides of the contradiction (simple heuristic)
                    best_positions = _extract_positions(message, contradiction_type)
                break  # One match per type is enough
    
    # Apply intimacy gating
    if intimacy_score >= INTIMACY_GATE:
        threshold = DISSONANCE_THRESHOLD_HIGH
    else:
        threshold = DISSONANCE_THRESHOLD_LOW
    
    triggered = max_score >= threshold
    
    if triggered:
        logger.info(
            f"Dissonance detected for student: score={float(max_score):.2f}, "
            f"type={best_type}, intimacy={float(intimacy_score):.1f}, threshold={float(threshold):.2f}"
        )
    
    return DissonanceResult(
        score=max_score,
        triggered=triggered,
        contradiction_type=best_type,
        extracted_positions=best_positions,
        threshold_used=threshold,
    )


def _extract_positions(message: str, contradiction_type: str) -> List[str]:
    """
    Extract the two contradictory positions from the message.
    
    Simple heuristic MVP. Replace with LLM extraction for production.
    """
    positions = []
    
    if contradiction_type == "explicit_contradiction":
        # Split on "but" or "however"
        parts = re.split(r"\s+(but|however|although)\s+", message, flags=re.IGNORECASE)
        if len(parts) >= 3:
            positions = [parts[0].strip(), parts[2].strip()]
    
    elif contradiction_type == "teacher_vs_wax_conflict":
        # Extract "teacher said X" and "you said Y"
        teacher_match = re.search(r"(?:teacher|textbook|school)\s+said\s+(.+?)(?:\s+but|\s+however|$)", message, re.IGNORECASE)
        wax_match = re.search(r"you\s+said\s+(.+?)(?:\s+but|\s+however|$)", message, re.IGNORECASE)
        if teacher_match:
            positions.append(f"Teacher: {teacher_match.group(1).strip()}")
        if wax_match:
            positions.append(f"Wax: {wax_match.group(1).strip()}")
    
    elif contradiction_type == "cross_domain_confusion":
        # Extract the two analogies
        match = re.search(r"so\s+(.+?)\s+is\s+like\s+(.+?)\?", message, re.IGNORECASE)
        if match:
            positions = [match.group(1).strip(), match.group(2).strip()]
    
    if not positions:
        # Fallback: split message in half
        mid = len(message) // 2
        positions = [message[:mid].strip(), message[mid:].strip()]
    
    return positions[:2]  # Always return exactly 2 positions


# ═══════════════════════════════════════════════════════════════════════
# SUBSYSTEM 2: REGISTER WEAVER
# ═══════════════════════════════════════════════════════════════════════

def weave_rupture(
    topic: str,
    socratic_position: str,
    empiric_position: str,
    contradiction: Optional[DissonanceResult] = None,
    student_position: Optional[str] = None,
) -> str:
    """
    Weave the two voices into a single Rupture Interface message.
    
    The seam is linguistic — formal English vs. Nigerian Pidgin.
    No emoji dependency. The crack is the code-switch itself.
    """
    header = "🔀 The Tension"
    
    if student_position:
        # Round 2+: Both voices respond to the student's position
        socratic_response = _socratic_responds_to_student(topic, socratic_position, student_position)
        empiric_response = _empiric_responds_to_student(topic, empiric_position, student_position)
        
        body = f"""{header}

**School voice:** "{socratic_response}"

**Home voice:** "{empiric_response}"

**You said:** "{student_position}"

**Which rope would you rather climb? Or you fit weave your own?"""
    
    else:
        # Round 0-1: State the two positions from the detected contradiction
        body = f"""{header}

**School voice:** "{socratic_position}"

**Home voice:** "{empiric_position}"

**Which one dey make sense for your head? Or you fit mix both?"""
    
    return body


def _socratic_responds_to_student(topic: str, socratic_position: str, student_position: str) -> str:
    """Generate Socratic's response to the student's position."""
    # This will be replaced by actual LLM call in the engine
    # For now, return a template that the prompt system fills
    return f"Your position — '{student_position}' — is interesting. But consider: {socratic_position}"


def _empiric_responds_to_student(topic: str, empiric_position: str, student_position: str) -> str:
    """Generate Empiric's response to the student's position."""
    # This will be replaced by actual LLM call in the engine
    return f"Omo, '{student_position}' sweet die! But think am well: {empiric_position}"


# ═══════════════════════════════════════════════════════════════════════
# SUBSYSTEM 3: TRIAD ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

def orchestrate_triad(
    triad_state: TriadState,
    student_reply: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Determine which voice speaks next and what they should address.
    
    Returns: (next_voice, prompt_context)
    """
    if student_reply:
        # Student has spoken — extract their position
        triad_state.student_position = student_reply
        triad_state.round_number += 1
        
        # Classify epistemic stance
        triad_state.student_epistemic_stance = _classify_stance(student_reply)
        
        # Both voices respond to student
        next_voice = "both"
        prompt_context = f"""
Student position: {student_reply}
Student stance: {triad_state.student_epistemic_stance}
Topic: {triad_state.topic}
Socratic must respond to the student's position using formal academic English.
Empiric must respond to the student's position using Nigerian Pidgin or relaxed English.
Both must address the specific idea the student raised, not restate original positions.
"""
    
    else:
        # No student reply yet — advance the debate
        next_voice = triad_state.next_voice()
        triad_state.round_number += 1
        
        if next_voice == "socratic":
            prompt_context = f"""
Topic: {triad_state.topic}
You are Wax-Socratic. Speak in formal academic English.
State the formal position on this topic. Be precise, structured, classroom-register.
"""
        elif next_voice == "empiric":
            prompt_context = f"""
Topic: {triad_state.topic}
You are Wax-Empiric. Speak in Nigerian Pidgin or relaxed English with local metaphors.
State the intuitive position on this topic. Be conversational, embodied, home-register.
"""
        else:
            prompt_context = "Both voices respond to student position."
    
    return next_voice, prompt_context


def _classify_stance(student_reply: str) -> str:
    """
    Classify the student's epistemic stance from their reply.
    
    Rule-based MVP. Replace with LLM classification for production.
    """
    reply_lower = student_reply.lower()
    
    # Check for synthesis
    if any(word in reply_lower for word in ["both", "mix", "combine", "together", "and"]):
        return "synthetic"
    
    # Check for rejection
    if any(word in reply_lower for word in ["none", "neither", "wrong", "don't agree", "no be so"]):
        return "rejecting"
    
    # Check for confusion
    if any(word in reply_lower for word in ["confused", "don't know", "not sure", "huh", "wait"]):
        return "confused"
    
    # Check for formal leaning
    if any(word in reply_lower for word in ["school", "teacher", "textbook", "formal", "definition"]):
        return "formal_leaning"
    
    # Check for vernacular leaning
    if any(word in reply_lower for word in ["make sense", "feel", "like", "na", "dey", "omo"]):
        return "vernacular_leaning"
    
    return "undetermined"


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API (What core files call)
# ═══════════════════════════════════════════════════════════════════════

async def process_for_dialectical(
    student_id: str,
    message: str,
    topic: str,
    intimacy_score: Decimal = Decimal("0"),
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Main entry point for the Dialectical Engine.
    
    Called by the Intent Router on every student message.
    
    Returns None if no dissonance detected.
    Returns dict with rupture_interface and triad_state if triggered.
    """
    # Step 1: Detect dissonance
    dissonance = detect_dissonance(message, context, intimacy_score)
    
    if not dissonance.triggered:
        return None
    
    # Step 2: Initialize triad
    triad = TriadState(
        student_id=student_id,
        topic=topic,
        dissonance_result=dissonance,
    )
    
    # Step 3: Generate positions from contradiction
    if len(dissonance.extracted_positions) >= 2:
        triad.socratic_position = dissonance.extracted_positions[0]
        triad.empiric_position = dissonance.extracted_positions[1]
    else:
        # Fallback: use topic as position
        triad.socratic_position = f"The formal view on {topic}"
        triad.empiric_position = f"The intuitive view on {topic}"
    
    # Step 4: Weave rupture
    rupture = weave_rupture(
        topic=topic,
        socratic_position=triad.socratic_position,
        empiric_position=triad.empiric_position,
        contradiction=dissonance,
    )
    
    # Step 5: Determine first voice
    next_voice, prompt_context = orchestrate_triad(triad)
    
    return {
        "action": "dialectical_midwifery",
        "rupture_interface": rupture,
        "triad_state": triad.to_dict(),
        "next_voice": next_voice,
        "prompt_context": prompt_context,
        "dissonance": dissonance.to_dict(),
    }


async def continue_triad(
    triad_state_dict: Dict[str, Any],
    student_reply: str,
) -> Dict[str, Any]:
    """
    Continue a triadic debate after the student replies.
    
    Called by telegram/handler.py when a Schism is active.
    """
    # Reconstruct triad state
    triad = TriadState(
        student_id=triad_state_dict["student_id"],
        topic=triad_state_dict["topic"],
        socratic_position=triad_state_dict.get("socratic_position", ""),
        empiric_position=triad_state_dict.get("empiric_position", ""),
        student_position=triad_state_dict.get("student_position"),
        round_number=triad_state_dict.get("round_number", 0),
        student_epistemic_stance=triad_state_dict.get("student_epistemic_stance", "undetermined"),
    )
    
    # Advance triad
    next_voice, prompt_context = orchestrate_triad(triad, student_reply)
    
    # Weave response rupture
    rupture = weave_rupture(
        topic=triad.topic,
        socratic_position=triad.socratic_position,
        empiric_position=triad.empiric_position,
        student_position=triad.student_position,
    )
    
    return {
        "action": "dialectical_midwifery",
        "rupture_interface": rupture,
        "triad_state": triad.to_dict(),
        "next_voice": next_voice,
        "prompt_context": prompt_context,
        "student_stance": triad.student_epistemic_stance,
    }


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════

_socket_initialized = False

def init_dialectical_socket():
    """Initialize the dialectical socket. Call once at startup."""
    global _socket_initialized
    if not _socket_initialized:
        logger.info("Dialectical Socket initialized — Cognitive Midwifery Station online")
        _socket_initialized = True
