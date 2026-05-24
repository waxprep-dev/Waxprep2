"""
brain/insight_distillery.py — Insight Distillery (S2)

Extracts the exact teaching element that caused a student's breakthrough.
Builds "Insight Capsules" — portable teaching patterns that can be
transferred to other students struggling with the same concept.

The Distillery answers: "What did Wax do that made understanding click?"

Pipeline:
1. Causal Attribution — What teaching action preceded the breakthrough?
2. Pattern Extraction — What TYPE of teaching worked?
3. Payload Distillation — The exact "lightning bolt" content
4. Quality Scoring — Is this insight swarm-eligible?
5. Provenance — Anonymized origin tracking

Connections:
- Breakthrough Seismograph (S1) — receives breakthrough signals
- Working Memory — reads what Wax taught in the session
- Dialectical Ledger — reads debate stances if dialectical
- Thermal Memory — reads which teaching approach was "hot"

Output: Insight Capsule (JSON) ready for swarm_insights table

CHANGELOG:
- 2026-05-25: Created for Ubuntu Swarm Mind P2-A
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.distillery")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Quality thresholds for swarm eligibility
MIN_EFFECTIVENESS_SCORE = 0.70  # Must score ≥ 0.70 to enter swarm
MAX_INSIGHTS_PER_CONCEPT = 100  # Cap insights per concept

# Teaching pattern taxonomy
TEACHING_PATTERNS = {
    "analogy": ["market_stall", "football", "food", "family", "transport", "nepa"],
    "scaffold": ["guided_discovery", "worked_example", "partial_completion", "hint_system"],
    "dialectical": ["socratic_question", "empiric_challenge", "triad_debate"],
    "visual": ["diagram", "chart", "equation_breakdown", "step_by_step"],
    "procedural": ["algorithm", "formula", "rule", "mnemonic"],
    "emotional": ["encouragement", "reframing", "normalization", "motivation"],
}

# Redis keys
LAST_TEACHING_ACTION_KEY = "distill:last_teaching:{student_id}"
SESSION_TEACHING_LOG_KEY = "distill:session_log:{student_id}:{session_id}"

# ═══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TeachingPattern:
    """The pattern of teaching that worked."""
    pattern_type: str  # analogy, scaffold, dialectical, etc.
    pattern_subtype: str  # market_stall, guided_discovery, etc.
    explanation_method: str  # concrete_first, abstract_first, mixed
    language_register: str  # formal, pidgin, mixed
    scaffold_level: str  # full_support, guided, minimal, independent


@dataclass
class InsightPayload:
    """The exact "lightning bolt" — what made understanding click."""
    analogy_used: Optional[str]
    key_framing: str  # The specific sentence or question
    trigger_question: Optional[str]
    concrete_example: Optional[str]
    visual_aid: Optional[str]


@dataclass
class Provenance:
    """Anonymized origin tracking."""
    origin_student_id_hash: str  # SHA-256 prefix, no raw ID
    origin_region: str  # Generalized Nigerian zone
    origin_school_type: str  # public, private, unity
    bio_state_at_breakthrough: str
    class_level: str


@dataclass
class InsightCapsule:
    """The complete portable teaching pattern."""
    insight_id: str
    concept_id: str
    concept_name: str
    subject: str
    
    breakthrough_type: str  # From seismograph
    teaching_pattern: TeachingPattern
    insight_payload: InsightPayload
    
    effectiveness_score: float
    quality_tier: str  # incubation, slow, fast, viral
    
    provenance: Provenance
    transfer_metadata: Dict[str, Any]
    
    created_at: str


# ═══════════════════════════════════════════════════════════════════════
# MAIN DISTILLERY
# ═══════════════════════════════════════════════════════════════════════

class InsightDistillery:
    """
    Extracts teaching insights from breakthrough moments.

    Usage:
        distillery = InsightDistillery(student_id, session_id)
        capsule = await distillery.distill(
            breakthrough_signal=seismo_reading,
            conversation_history=history,
            working_memory=wm,
            teaching_context=last_wax_response,
        )
        if capsule:
            # Save to swarm_insights table
            pass
    """

    def __init__(self, student_id: str, session_id: Optional[str] = None):
        self.student_id = student_id
        self.session_id = session_id or "unknown"

    async def distill(
        self,
        breakthrough_signal: Dict[str, Any],
        conversation_history: List[Dict[str, Any]],
        working_memory: Dict[str, Any],
        teaching_context: Optional[str] = None,
        student_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[InsightCapsule]:
        """
        Distill an Insight Capsule from a breakthrough moment.

        Args:
            breakthrough_signal: Output from BreakthroughSeismograph
            conversation_history: Last 10 messages in session
            working_memory: Current Working Memory snapshot
            teaching_context: Wax's last teaching response (if available)
            student_metadata: {class_level, school_type, region, bio_state}

        Returns:
            InsightCapsule if quality passes threshold, None otherwise
        """
        # 1. Causal Attribution — What did Wax teach?
        last_teaching = await self._get_last_teaching_action(conversation_history, teaching_context)
        if not last_teaching:
            logger.warning("No teaching action found for breakthrough attribution")
            return None

        # 2. Pattern Extraction — What TYPE of teaching?
        pattern = self._extract_teaching_pattern(last_teaching, working_memory)

        # 3. Payload Distillation — The exact lightning bolt
        payload = self._distill_payload(last_teaching, breakthrough_signal, working_memory)

        # 4. Quality Scoring — Is this good enough to share?
        effectiveness = self._score_effectiveness(
            breakthrough_signal, pattern, payload, working_memory
        )
        if effectiveness < MIN_EFFECTIVENESS_SCORE:
            logger.info(f"Insight below quality threshold: {effectiveness:.2f} < {MIN_EFFECTIVENESS_SCORE}")
            return None

        # 5. Provenance — Anonymized origin
        provenance = self._build_provenance(student_metadata or {})

        # 6. Transfer metadata
        transfer_meta = self._build_transfer_metadata(breakthrough_signal, working_memory)

        # Build capsule
        concept_id = working_memory.get("current_concept", "unknown").replace(" ", "_").lower()
        concept_name = working_memory.get("current_concept", "Unknown Concept")
        subject = working_memory.get("active_subject", "unknown")

        capsule = InsightCapsule(
            insight_id=f"insight_{hashlib.sha256(f'{self.student_id}:{concept_id}:{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:16]}",
            concept_id=concept_id,
            concept_name=concept_name,
            subject=subject,
            breakthrough_type=breakthrough_signal.get("dominant_pattern", "unknown"),
            teaching_pattern=pattern,
            insight_payload=payload,
            effectiveness_score=round(effectiveness, 3),
            quality_tier=self._determine_quality_tier(effectiveness),
            provenance=provenance,
            transfer_metadata=transfer_meta,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(f"Insight Capsule distilled: {capsule.insight_id} "
                   f"(score: {effectiveness:.2f}, tier: {capsule.quality_tier})")

        return capsule

    # ═════════════════════════════════════════════════════════════════
    # 1. CAUSAL ATTRIBUTION
    # ═════════════════════════════════════════════════════════════════

    async def _get_last_teaching_action(
        self,
        conversation_history: List[Dict[str, Any]],
        teaching_context: Optional[str],
    ) -> Optional[str]:
        """
        Find Wax's last teaching response before the breakthrough.
        """
        # If teaching_context is provided directly, use it
        if teaching_context:
            return teaching_context

        # Otherwise, scan conversation history for last assistant message
        if not conversation_history:
            # Try Redis cache
            try:
                cached = redis_client.get(
                    LAST_TEACHING_ACTION_KEY.format(student_id=self.student_id)
                )
                if cached:
                    return cached.decode("utf-8") if isinstance(cached, bytes) else cached
            except Exception:
                pass
            return None

        # Find last assistant message before the breakthrough
        for msg in reversed(conversation_history):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                # Filter out non-teaching responses (greetings, emotional support)
                if self._is_teaching_response(content):
                    return content

        return None

    def _is_teaching_response(self, text: str) -> bool:
        """Check if a response contains actual teaching content."""
        text_lower = text.lower()

        # Teaching indicators
        teaching_markers = [
            "because", "so", "therefore", "this means", "the idea is",
            "think of", "imagine", "for example", "let's", "try",
            "factor", "solve", "calculate", "equation", "formula",
            "remember", "notice", "see how", "what if", "how would",
            "step", "first", "then", "next", "finally",
        ]

        marker_count = sum(1 for m in teaching_markers if m in text_lower)
        return marker_count >= 2  # At least 2 teaching markers

    # ═════════════════════════════════════════════════════════════════
    # 2. PATTERN EXTRACTION
    # ═════════════════════════════════════════════════════════════════

    def _extract_teaching_pattern(
        self,
        teaching_text: str,
        working_memory: Dict[str, Any],
    ) -> TeachingPattern:
        """
        Extract what TYPE of teaching worked.
        """
        text_lower = teaching_text.lower()

        # Detect pattern type and subtype
        pattern_type = "procedural"  # Default
        pattern_subtype = "algorithm"

        # Check for analogies
        for ptype, subtypes in TEACHING_PATTERNS.items():
            for subtype in subtypes:
                if subtype in text_lower:
                    pattern_type = ptype
                    pattern_subtype = subtype
                    break
            if pattern_type != "procedural":
                break

        # Detect explanation method
        if any(w in text_lower for w in ["first", "start with", "imagine", "think of"]):
            explanation_method = "concrete_first"
        elif any(w in text_lower for w in ["abstract", "general", "formula", "theory"]):
            explanation_method = "abstract_first"
        else:
            explanation_method = "mixed"

        # Detect language register
        pidgin_markers = ["dey", "wetin", "na", "go", "don", "wan", "sabi", "abi", "o", "sha"]
        pidgin_count = sum(1 for m in pidgin_markers if m in text_lower)
        word_count = len(text_lower.split())

        if word_count > 0 and pidgin_count / word_count > 0.05:
            language_register = "pidgin"
        elif pidgin_count > 0:
            language_register = "mixed"
        else:
            language_register = "formal"

        # Detect scaffold level
        if any(w in text_lower for w in ["you try", "your turn", "now you", "practice"]):
            scaffold_level = "guided"
        elif any(w in text_lower for w in ["hint", "clue", "nudge", "almost"]):
            scaffold_level = "minimal"
        elif any(w in text_lower for w in ["watch", "see how", "let me show"]):
            scaffold_level = "full_support"
        else:
            scaffold_level = "independent"

        return TeachingPattern(
            pattern_type=pattern_type,
            pattern_subtype=pattern_subtype,
            explanation_method=explanation_method,
            language_register=language_register,
            scaffold_level=scaffold_level,
        )

    # ═════════════════════════════════════════════════════════════════
    # 3. PAYLOAD DISTILLATION
    # ═════════════════════════════════════════════════════════════════

    def _distill_payload(
        self,
        teaching_text: str,
        breakthrough_signal: Dict[str, Any],
        working_memory: Dict[str, Any],
    ) -> InsightPayload:
        """
        Extract the exact "lightning bolt" from the teaching text.
        """
        text_lower = teaching_text.lower()

        # Extract analogy
        analogy = None
        for ptype, subtypes in TEACHING_PATTERNS.items():
            if ptype == "analogy":
                for subtype in subtypes:
                    if subtype in text_lower:
                        # Find the sentence containing the analogy
                        sentences = teaching_text.split(".")
                        for sent in sentences:
                            if subtype in sent.lower():
                                analogy = sent.strip()
                                break
                    if analogy:
                        break
            if analogy:
                break

        # Extract key framing (the "aha" sentence)
        # Heuristic: look for sentences with strong pedagogical markers
        key_framing = self._extract_key_framing(teaching_text)

        # Extract trigger question
        trigger_question = None
        questions = re.findall(r'[^.!?]*\?', teaching_text)
        if questions:
            # Pick the question that most directly addresses the concept
            concept = working_memory.get("current_concept", "")
            for q in questions:
                if concept and concept.lower().replace("_", " ") in q.lower():
                    trigger_question = q.strip()
                    break
            if not trigger_question and questions:
                trigger_question = questions[-1].strip()  # Last question

        # Extract concrete example
        concrete_example = None
        example_markers = ["for example", "like", "imagine", "think of", "suppose"]
        sentences = teaching_text.split(".")
        for sent in sentences:
            if any(m in sent.lower() for m in example_markers):
                concrete_example = sent.strip()
                break

        # Extract visual aid reference
        visual_aid = None
        visual_markers = ["diagram", "chart", "picture", "see", "look at", "draw", "sketch"]
        for sent in sentences:
            if any(m in sent.lower() for m in visual_markers):
                visual_aid = sent.strip()
                break

        return InsightPayload(
            analogy_used=analogy,
            key_framing=key_framing,
            trigger_question=trigger_question,
            concrete_example=concrete_example,
            visual_aid=visual_aid,
        )

    def _extract_key_framing(self, text: str) -> str:
        """Extract the most pedagogically significant sentence."""
        sentences = [s.strip() for s in text.split(".") if s.strip()]

        # Score each sentence
        best_sentence = sentences[0] if sentences else text[:200]
        best_score = 0

        for sent in sentences:
            score = 0
            sent_lower = sent.lower()

            # Teaching markers
            teaching_words = ["because", "so", "therefore", "this means", "the key",
                            "remember", "notice", "see how", "what matters"]
            score += sum(1 for w in teaching_words if w in sent_lower) * 2

            # Conceptual depth markers
            depth_words = ["is", "are", "equals", "represents", "means", "shows"]
            score += sum(1 for w in depth_words if w in sent_lower)

            # Length penalty (too long = less "lightning bolt")
            words = len(sent.split())
            if words > 30:
                score -= (words - 30) * 0.5

            if score > best_score:
                best_score = score
                best_sentence = sent

        return best_sentence[:300]  # Cap length

    # ═════════════════════════════════════════════════════════════════
    # 4. QUALITY SCORING
    # ═════════════════════════════════════════════════════════════════

    def _score_effectiveness(
        self,
        breakthrough_signal: Dict[str, Any],
        pattern: TeachingPattern,
        payload: InsightPayload,
        working_memory: Dict[str, Any],
    ) -> float:
        """
        Score how effective this insight is for swarm transfer.
        """
        scores = []

        # 1. Breakthrough strength (0.0-1.0)
        composite = breakthrough_signal.get("composite_score", 0.0)
        scores.append(composite)

        # 2. Pattern specificity (0.0-1.0)
        # More specific patterns transfer better
        if pattern.pattern_type != "procedural" and pattern.pattern_subtype != "algorithm":
            scores.append(0.8)  # Non-generic pattern
        else:
            scores.append(0.5)  # Generic pattern

        # 3. Payload completeness (0.0-1.0)
        payload_fields = [
            payload.analogy_used,
            payload.key_framing,
            payload.trigger_question,
            payload.concrete_example,
        ]
        filled = sum(1 for f in payload_fields if f)
        scores.append(filled / 4)

        # 4. Concept clarity (0.0-1.0)
        concept = working_memory.get("current_concept", "")
        if concept and concept != "unknown":
            scores.append(0.9)
        else:
            scores.append(0.3)

        # 5. Language register match (0.0-1.0)
        # Pidgin insights are MORE valuable for transfer (cultural specificity)
        if pattern.language_register in ["pidgin", "mixed"]:
            scores.append(0.9)
        else:
            scores.append(0.7)

        # Weighted average
        weights = [0.30, 0.20, 0.20, 0.15, 0.15]
        effectiveness = sum(s * w for s, w in zip(scores, weights))

        return round(effectiveness, 3)

    def _determine_quality_tier(self, effectiveness: float) -> str:
        """Determine swarm spread tier based on effectiveness."""
        if effectiveness >= 0.95:
            return "viral"
        elif effectiveness >= 0.85:
            return "fast"
        elif effectiveness >= 0.75:
            return "slow"
        else:
            return "incubation"

    # ═════════════════════════════════════════════════════════════════
    # 5. PROVENANCE
    # ═════════════════════════════════════════════════════════════════

    def _build_provenance(self, student_metadata: Dict[str, Any]) -> Provenance:
        """
        Build anonymized provenance for privacy.
        """
        # Hash student ID with daily rotating salt
        salt = datetime.now(timezone.utc).strftime("%Y%m%d")
        id_hash = hashlib.sha256(
            f"{self.student_id}:{salt}".encode()
        ).hexdigest()[:16]

        # Generalize region to Nigerian zones
        region = student_metadata.get("region", "unknown")
        region_map = {
            "lagos": "south_west",
            "ibadan": "south_west",
            "abeokuta": "south_west",
            "kano": "north_west",
            "kaduna": "north_west",
            "sokoto": "north_west",
            "abuja": "north_central",
            "jos": "north_central",
            "ilorin": "north_central",
            "enugu": "south_east",
            "owerri": "south_east",
            "aba": "south_east",
            "port harcourt": "south_south",
            "calabar": "south_south",
            "warri": "south_south",
            "benin": "south_south",
        }
        generalized_region = region_map.get(region.lower(), "unknown")

        # School type generalization
        school_type = student_metadata.get("school_type", "unknown")
        if school_type not in ["public", "private", "unity"]:
            school_type = "public"  # Default

        return Provenance(
            origin_student_id_hash=id_hash,
            origin_region=generalized_region,
            origin_school_type=school_type,
            bio_state_at_breakthrough=student_metadata.get("bio_state", "evening_deep"),
            class_level=student_metadata.get("class_level", "unknown"),
        )

    # ═════════════════════════════════════════════════════════════════
    # 6. TRANSFER METADATA
    # ═════════════════════════════════════════════════════════════════

    def _build_transfer_metadata(
        self,
        breakthrough_signal: Dict[str, Any],
        working_memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build metadata to help match this insight to struggling students.
        """
        signals = breakthrough_signal.get("signals", [])

        # Extract failure pattern from signals
        failure_pattern = "unknown"
        for s in signals:
            if s.get("pattern_type") == "problem_solve_cascade":
                failure_pattern = "repeated_error"
            elif s.get("pattern_type") == "confidence_spike":
                failure_pattern = "confidence_rebuild"

        # Count attempts before breakthrough
        attempts = 1
        for s in signals:
            if s.get("pattern_type") == "problem_solve_cascade":
                attempts = s.get("evidence", {}).get("failure_count", 1) + 1

        return {
            "attempts_before_breakthrough": attempts,
            "prior_struggle_pattern": failure_pattern,
            "breakthrough_latency_minutes": working_memory.get("time_on_current_topic_minutes", 0),
            "concept_difficulty": working_memory.get("confusion_level", 0.5),
        }


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════════════════

async def distill_insight(
    student_id: str,
    breakthrough_signal: Dict[str, Any],
    conversation_history: List[Dict[str, Any]],
    working_memory: Dict[str, Any],
    teaching_context: Optional[str] = None,
    student_metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    High-level API: Distill an Insight Capsule from a breakthrough.

    Returns dict representation of InsightCapsule, or None if below threshold.
    """
    distillery = InsightDistillery(student_id, session_id)
    capsule = await distillery.distill(
        breakthrough_signal=breakthrough_signal,
        conversation_history=conversation_history,
        working_memory=working_memory,
        teaching_context=teaching_context,
        student_metadata=student_metadata,
    )

    if not capsule:
        return None

    # Convert dataclass to dict for JSON serialization
    return {
        "insight_id": capsule.insight_id,
        "concept_id": capsule.concept_id,
        "concept_name": capsule.concept_name,
        "subject": capsule.subject,
        "breakthrough_type": capsule.breakthrough_type,
        "teaching_pattern": {
            "pattern_type": capsule.teaching_pattern.pattern_type,
            "pattern_subtype": capsule.teaching_pattern.pattern_subtype,
            "explanation_method": capsule.teaching_pattern.explanation_method,
            "language_register": capsule.teaching_pattern.language_register,
            "scaffold_level": capsule.teaching_pattern.scaffold_level,
        },
        "insight_payload": {
            "analogy_used": capsule.insight_payload.analogy_used,
            "key_framing": capsule.insight_payload.key_framing,
            "trigger_question": capsule.insight_payload.trigger_question,
            "concrete_example": capsule.insight_payload.concrete_example,
            "visual_aid": capsule.insight_payload.visual_aid,
        },
        "effectiveness_score": float(capsule.effectiveness_score),
        "quality_tier": capsule.quality_tier,
        "provenance": {
            "origin_student_id_hash": capsule.provenance.origin_student_id_hash,
            "origin_region": capsule.provenance.origin_region,
            "origin_school_type": capsule.provenance.origin_school_type,
            "bio_state_at_breakthrough": capsule.provenance.bio_state_at_breakthrough,
            "class_level": capsule.provenance.class_level,
        },
        "transfer_metadata": capsule.transfer_metadata,
        "created_at": capsule.created_at,
    }
