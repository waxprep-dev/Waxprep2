"""
WaxPrep v2 — Student Model
A living, adaptive profile of each student that learns from every interaction.

Phase 1 Categories:
    1. Teaching Style Preference — examples, definitions, stories, Socratic
    2. Example Domain Preferences — which references work for THIS student
       (with decay: stale preferences fade to neutral over time)
    3. Communication Style — formal, casual, Pidgin, code-switching
    4. Competence Map — what they've mastered, what they're struggling with

Architecture:
    - Redis Hashes for fast per-field access (atomic save via mapping=)
    - Supabase sync after session end (non-blocking, all fields synced)
    - Injected into prompt as LEARNING PROFILE section
    - Updates after session end only (not every message)
    - Confidence scoring on every inference
    - Gradual adaptation over 5 sessions (single session ≠ flip)
    - Domain decay: preferred domains fade after ~15-20 sessions without reinforcement

Privacy:
    - Encrypt sensitive fields before storage
    - Reset mechanism: student says "Forget what you know about me"
    - Model export for NDPR compliance
"""

import asyncio
import json
import logging
import random
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger("waxprep.student_model")

# ═══════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════

LEARNING_RATE = 0.2
DECAY_RATE = 0.05
DOMAIN_DECAY_RATE = 0.08  # ~8% chance per session for unreinforced preferred domains
MIN_SESSIONS_FOR_CONFIDENCE = 5  # Matches docstring: gradual adaptation over 5 sessions
MIN_SIGNALS_FOR_INFERENCE = 2
MAX_TRACKED_DOMAINS = 10
MAX_QUIZ_SCORES_PER_TOPIC = 5

TEACHING_STYLES = ["examples", "definitions", "stories", "socratic", "mixed"]

EXAMPLE_DOMAINS = [
    "transportation", "food_cooking", "market_commerce",
    "home_domestic", "technology", "school_classroom",
    "body_physical", "nature_environment",
    "religion_worship", "nollywood_media", "football_sports",
    "extended_family", "nysc_corper"
]

COMMUNICATION_LEVELS = ["formal_english", "casual_english", "pidgin_mixed", "full_pidgin"]
COMPETENCE_LEVELS = ["mastered", "in_progress", "struggling", "not_attempted"]

_SERIALIZED_FIELDS = [
    "teaching_style", "teaching_style_by_subject", "teaching_style_confidence",
    "teaching_style_signals", "teaching_style_sessions_observed",
    "example_domains", "domain_rejection_count", "complete_domain_avoidance",
    "communication_style", "communication_confidence", "communication_signals",
    "communication_sessions_observed",
    "last_formality_score", "abrupt_shift_detected",
    "competence_map", "last_quiz_scores",
    "recent_topics",
    "total_sessions", "total_interactions", "last_updated", "model_version",
]

_JSON_FIELDS = {
    "teaching_style", "teaching_style_by_subject", "example_domains",
    "communication_style", "competence_map", "last_quiz_scores",
    "recent_topics",
}

_FLOAT_FIELDS = {
    "teaching_style_confidence", "communication_confidence",
    "last_formality_score",
}

_INT_FIELDS = {
    "teaching_style_signals", "teaching_style_sessions_observed",
    "communication_signals", "communication_sessions_observed",
    "domain_rejection_count", "total_sessions", "total_interactions",
    "model_version",
}

_BOOL_FIELDS = {
    "complete_domain_avoidance", "abrupt_shift_detected",
}


# ═══════════════════════════════════════════════
# STUDENT MODEL CLASS
# ═══════════════════════════════════════════════

class StudentModel:
    """A living profile of a single student."""
    
    def __init__(self, student_id: str):
        self.student_id = student_id
        self.redis_key = f"student_model:{student_id}"
        
        # Category 1: Teaching Style
        self.teaching_style: Dict[str, float] = {}
        self.teaching_style_by_subject: Dict[str, Dict[str, float]] = {}
        self.teaching_style_confidence: float = 0.0
        self.teaching_style_signals: int = 0
        self.teaching_style_sessions_observed: int = 0
        
        # Category 2: Example Domains
        self.example_domains: Dict[str, str] = {}
        self.domain_rejection_count: int = 0
        self.complete_domain_avoidance: bool = False
        
        # Category 3: Communication
        self.communication_style: Dict[str, float] = {}
        self.communication_confidence: float = 0.0
        self.communication_signals: int = 0
        self.communication_sessions_observed: int = 0
        self.last_formality_score: float = 0.5
        self.abrupt_shift_detected: bool = False
        
        # Category 4: Competence
        self.competence_map: Dict[str, Dict[str, str]] = {}
        self.last_quiz_scores: Dict[str, List[float]] = {}
        
        # Topic Coherence
        self.recent_topics: List[str] = []
        
        # Metadata
        self.total_sessions: int = 0
        self.total_interactions: int = 0
        self.last_updated: Optional[str] = None
        self.model_version: int = 2  # v2: added decay, fixed confidence, split counters


    # ═══════════════════════════════════════════
    # CATEGORY 1: TEACHING STYLE
    # ═══════════════════════════════════════════
    
    def update_teaching_style(self, session_signals: dict) -> None:
        """
        Update teaching style preferences with new signals.
        
        Confidence is based on sessions OBSERVED, not total signals.
        One session with 5 signals = 1 observation, not 5.
        """
        signals = session_signals.get("teaching_style", {})
        if not signals:
            return
        
        # Decay existing preferences
        for style in self.teaching_style:
            self.teaching_style[style] *= (1 - DECAY_RATE)
        
        # Apply new signals
        for style, signal_strength in signals.items():
            if style not in TEACHING_STYLES:
                continue
            if style not in self.teaching_style:
                self.teaching_style[style] = 0.0
            self.teaching_style[style] += LEARNING_RATE * signal_strength
            self.teaching_style[style] = max(0.0, min(1.0, self.teaching_style[style]))
        
        # Normalize
        total = sum(self.teaching_style.values())
        if total > 0:
            for style in self.teaching_style:
                self.teaching_style[style] /= total
        
        self.teaching_style_signals += len(signals)
        self.teaching_style_sessions_observed += 1
        
        # Confidence: based on SESSIONS observed, not total signals
        if self.teaching_style_sessions_observed >= MIN_SIGNALS_FOR_INFERENCE:
            self.teaching_style_confidence = min(
                1.0,
                self.teaching_style_sessions_observed / MIN_SESSIONS_FOR_CONFIDENCE
            )
        
        # Per-subject teaching style
        subject = session_signals.get("subject")
        if subject:
            if subject not in self.teaching_style_by_subject:
                self.teaching_style_by_subject[subject] = {}
            for style, signal_strength in signals.items():
                if style not in TEACHING_STYLES:
                    continue
                if style not in self.teaching_style_by_subject[subject]:
                    self.teaching_style_by_subject[subject][style] = 0.0
                self.teaching_style_by_subject[subject][style] += LEARNING_RATE * signal_strength
                self.teaching_style_by_subject[subject][style] = max(
                    0.0, min(1.0, self.teaching_style_by_subject[subject][style])
                )
    
    def get_preferred_teaching_style(self, subject: str = None) -> str:
        """Get preferred teaching style. Returns 'mixed' if confidence is low."""
        styles = self.teaching_style
        
        if subject and subject in self.teaching_style_by_subject:
            subject_styles = self.teaching_style_by_subject[subject]
            if subject_styles and len(subject_styles) >= MIN_SIGNALS_FOR_INFERENCE:
                styles = subject_styles
        
        # Require 5 sessions of observation before trusting the model
        if not styles or self.teaching_style_confidence < 0.6:
            return "mixed"
        
        return max(styles, key=styles.get)
    
    # ═══════════════════════════════════════════
    # CATEGORY 2: EXAMPLE DOMAINS
    # ═══════════════════════════════════════════
    
    def update_example_domains(self, session_signals: dict) -> None:
        """
        Update domain preferences with decay.
        
        - Preferred domains are reinforced by positive signals
        - Avoided domains stay avoided FOREVER (explicit boundaries)
        - Preferred domains without reinforcement decay to neutral over time
        """
        signals = session_signals.get("example_domains", {})
        
        # Process new signals
        if signals:
            for domain, status in signals.items():
                if domain not in EXAMPLE_DOMAINS and domain not in self.example_domains:
                    continue
                
                old_status = self.example_domains.get(domain, "neutral")
                
                if status == "preferred":
                    self.example_domains[domain] = "preferred"
                    self.domain_rejection_count = 0
                elif status == "avoided":
                    # Don't override a preference with avoidance — only if not preferred
                    if old_status != "preferred":
                        self.example_domains[domain] = "avoided"
                    self.domain_rejection_count += 1
                elif status == "neutral":
                    if domain not in self.example_domains:
                        self.example_domains[domain] = "neutral"
        
        # Decay unreinforced preferred domains
        self._decay_domains()
        
        # Check if too many domains are avoided
        tracked = len(self.example_domains)
        avoided = sum(1 for v in self.example_domains.values() if v == "avoided")
        if tracked > 0 and avoided / tracked > 0.7:
            self.complete_domain_avoidance = True
    
    def _decay_domains(self) -> None:
        """
        Decay domain preferences that haven't been reinforced recently.
        
        Preferred domains that haven't received a signal in recent sessions
        gradually revert to 'neutral'. Avoided domains stay avoided — those
        are explicit boundaries, not fading preferences.
        
        At DOMAIN_DECAY_RATE (8%), a domain fades after ~15-20 sessions
        without reinforcement.
        """
        domains_to_decay = []
        for domain, status in self.example_domains.items():
            if status == "preferred":
                domains_to_decay.append(domain)
        
        for domain in domains_to_decay:
            if random.random() < DOMAIN_DECAY_RATE:
                self.example_domains[domain] = "neutral"
                logger.debug(
                    f"Domain '{domain}' decayed to neutral for {self.student_id}"
                )
    
    def should_ask_for_reference(self) -> bool:
        """Check if we should ask the student what domains work for them."""
        return self.domain_rejection_count >= 2
    
    def get_preferred_domains(self) -> List[str]:
        """Get preferred domains first, then neutral. Avoided domains excluded."""
        preferred = [d for d, s in self.example_domains.items() if s == "preferred"]
        neutral = [d for d, s in self.example_domains.items() if s == "neutral"]
        return preferred + neutral
    
    def get_avoided_domains(self) -> List[str]:
        """Get domains the student has explicitly rejected."""
        return [d for d, s in self.example_domains.items() if s == "avoided"]
    
    # ═══════════════════════════════════════════
    # CATEGORY 3: COMMUNICATION STYLE
    # ═══════════════════════════════════════════
    
    def update_communication_style(self, session_signals: dict) -> None:
        """
        Update communication preferences.
        
        Confidence based on sessions observed, not total signals.
        """
        signals = session_signals.get("communication", {})
        if not signals:
            return
        
        # Decay existing preferences
        for level in self.communication_style:
            self.communication_style[level] *= (1 - DECAY_RATE)
        
        # Apply new signals
        for level, signal_strength in signals.items():
            if level not in COMMUNICATION_LEVELS:
                continue
            if level not in self.communication_style:
                self.communication_style[level] = 0.0
            self.communication_style[level] += LEARNING_RATE * signal_strength
            self.communication_style[level] = max(0.0, min(1.0, self.communication_style[level]))
        
        # Normalize
        total = sum(self.communication_style.values())
        if total > 0:
            for level in self.communication_style:
                self.communication_style[level] /= total
        
        # Track formality shifts
        formality = session_signals.get("formality_score")
        if formality is not None:
            if abs(formality - self.last_formality_score) > 0.3:
                self.abrupt_shift_detected = True
            else:
                self.abrupt_shift_detected = False
            self.last_formality_score = formality
        
        self.communication_signals += len(signals)
        self.communication_sessions_observed += 1
        
        # Confidence: based on SESSIONS observed
        if self.communication_sessions_observed >= MIN_SIGNALS_FOR_INFERENCE:
            self.communication_confidence = min(
                1.0,
                self.communication_sessions_observed / MIN_SESSIONS_FOR_CONFIDENCE
            )
    
    def get_preferred_communication(self) -> str:
        """Get preferred communication style. Default 'casual_english' if unsure."""
        if not self.communication_style or self.communication_confidence < 0.6:
            return "casual_english"
        return max(self.communication_style, key=self.communication_style.get)
    
    # ═══════════════════════════════════════════
    # CATEGORY 4: COMPETENCE MAP
    # ═══════════════════════════════════════════
    
    def update_competence(self, session_signals: dict) -> None:
        """
        Update competence map with quiz scores.
        
        Only quiz scores can trigger 'mastered' or 'struggling'.
        Self-reported understanding sets 'in_progress' only.
        """
        signals = session_signals.get("competence", {})
        if not signals:
            return
        
        for topic_key, data in signals.items():
            parts = topic_key.split(":", 1)
            subject = parts[0] if len(parts) > 1 else "unknown"
            topic = parts[1] if len(parts) > 1 else topic_key
            
            if subject not in self.competence_map:
                self.competence_map[subject] = {}
            
            new_level = data.get("level")
            score = data.get("score")
            
            # Only apply level if it's from quiz data or explicit
            if new_level and new_level in COMPETENCE_LEVELS:
                # Self-reported "mastered" is not mastery — downgrade to in_progress
                if new_level == "mastered" and (score is None or score < 0.9):
                    new_level = "in_progress"
                self.competence_map[subject][topic] = new_level
            
            if score is not None:
                score_key = f"{subject}:{topic}"
                if score_key not in self.last_quiz_scores:
                    self.last_quiz_scores[score_key] = []
                self.last_quiz_scores[score_key].append(score)
                
                # Keep only recent scores
                if len(self.last_quiz_scores[score_key]) > MAX_QUIZ_SCORES_PER_TOPIC:
                    self.last_quiz_scores[score_key] = (
                        self.last_quiz_scores[score_key][-MAX_QUIZ_SCORES_PER_TOPIC:]
                    )
                
                # True mastery: 3+ recent scores averaging >= 0.8
                recent = self.last_quiz_scores[score_key][-3:]
                if len(recent) >= 3:
                    avg_score = sum(recent) / len(recent)
                    if avg_score >= 0.9:
                        self.competence_map[subject][topic] = "mastered"
                    elif avg_score < 0.5:
                        self.competence_map[subject][topic] = "struggling"
                    elif avg_score >= 0.6:
                        self.competence_map[subject][topic] = "in_progress"
    
    def get_topic_level(self, subject: str, topic: str) -> str:
        """Get the mastery level for a specific topic."""
        return self.competence_map.get(subject, {}).get(topic, "not_attempted")
    
    def get_mastered_topics(self, subject: str = None) -> List[str]:
        """Get all mastered topics, optionally filtered by subject."""
        mastered = []
        subjects = [subject] if subject else self.competence_map.keys()
        for subj in subjects:
            if subj in self.competence_map:
                for topic, level in self.competence_map[subj].items():
                    if level == "mastered":
                        mastered.append(f"{subj}:{topic}")
        return mastered
    
    def get_struggling_topics(self, subject: str = None) -> List[str]:
        """Get all struggling topics, optionally filtered by subject."""
        struggling = []
        subjects = [subject] if subject else self.competence_map.keys()
        for subj in subjects:
            if subj in self.competence_map:
                for topic, level in self.competence_map[subj].items():
                    if level == "struggling":
                        struggling.append(f"{subj}:{topic}")
        return struggling
    
    # ═══════════════════════════════════════════
    # SERIALIZATION
    # ═══════════════════════════════════════════
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to a dictionary for storage."""
        data = {}
        for field in _SERIALIZED_FIELDS:
            data[field] = getattr(self, field, None)
        return data
    
    @classmethod
    def from_dict(cls, student_id: str, data: Dict[str, Any]) -> "StudentModel":
        """
        Create a StudentModel from a dictionary with type validation.
        
        Ensures all fields have the correct types, using the field-type
        maps to convert strings to appropriate Python types.
        """
        model = cls(student_id)
        
        for field in _SERIALIZED_FIELDS:
            if field not in data:
                continue
            
            value = data[field]
            
            if field in _JSON_FIELDS:
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        value = {} if field != "recent_topics" else []
                elif not isinstance(value, (dict, list)):
                    value = {} if field != "recent_topics" else []
                    
            elif field in _FLOAT_FIELDS:
                if isinstance(value, str):
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        value = 0.0
                elif not isinstance(value, (int, float)):
                    value = 0.0
                else:
                    value = float(value)
                    
            elif field in _INT_FIELDS:
                if isinstance(value, str):
                    try:
                        value = int(float(value))
                    except (ValueError, TypeError):
                        value = 0
                elif not isinstance(value, int):
                    value = int(value) if isinstance(value, float) else 0
                    
            elif field in _BOOL_FIELDS:
                if isinstance(value, str):
                    value = value.lower() == "true"
                elif not isinstance(value, bool):
                    value = bool(value)
                    
            elif field == "last_updated":
                if value and not isinstance(value, str):
                    value = str(value)
            
            setattr(model, field, value)
        
        return model
    
    def to_prompt_context(self) -> str:
        """Format the model as a LEARNING PROFILE section for the AI prompt."""
        parts = []
        
        preferred_style = self.get_preferred_teaching_style()
        if self.teaching_style_confidence >= 0.6 and preferred_style != "mixed":
            parts.append(f"Teaching: prefers {preferred_style}")
        
        preferred_domains = self.get_preferred_domains()[:3]
        avoided_domains = self.get_avoided_domains()[:3]
        if preferred_domains:
            parts.append(f"Examples: use {', '.join(preferred_domains)}")
        if avoided_domains:
            parts.append(f"Avoid: {', '.join(avoided_domains)}")
        if self.complete_domain_avoidance:
            parts.append(
                "EXAMPLES: Student rejects most examples. Use abstract definitions."
            )
        
        preferred_comm = self.get_preferred_communication()
        if self.communication_confidence >= 0.6:
            comm_map = {
                "formal_english": "Formal English",
                "casual_english": "Casual English",
                "pidgin_mixed": "Mix of English and Pidgin",
                "full_pidgin": "Nigerian Pidgin",
            }
            parts.append(f"Language: {comm_map.get(preferred_comm, preferred_comm)}")
        
        struggling = self.get_struggling_topics()[:3]
        mastered = self.get_mastered_topics()[:3]
        if struggling:
            parts.append(f"Struggling: {', '.join(struggling)}")
        if mastered:
            parts.append(f"Mastered: {', '.join(mastered)}")
        
        if not parts:
            return ""
        
        return "LEARNING PROFILE:\n" + "\n".join(f"- {p}" for p in parts)
    
    def reset(self) -> None:
        """Completely reset the model. Preserves student_id."""
        old_id = self.student_id
        self.__init__(old_id)


# ═══════════════════════════════════════════════
# MODEL LOADER & SAVER
# ═══════════════════════════════════════════════

async def load_student_model(student_id: str) -> StudentModel:
    """
    Load a student's model from Redis, fallback to Supabase.
    
    On Supabase fallback, repopulates Redis cache.
    Type conversion is handled by StudentModel.from_dict.
    """
    model = StudentModel(student_id)
    
    # Try Redis first
    try:
        from database.client import redis_client
        
        raw = redis_client.hgetall(model.redis_key)
        if raw:
            data = {}
            for key, value in raw.items():
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                data[key_str] = value_str
            
            model = StudentModel.from_dict(student_id, data)
            return model
        
    except Exception as e:
        logger.error(f"Redis model load failed for {student_id}: {e}")
    
    # Fallback to Supabase
    try:
        from database.client import supabase
        
        result = (
            supabase.table("student_models")
            .select("*")
            .eq("student_id", student_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        
        if result.data:
            row = result.data[0]
            data = {}
            for field in _SERIALIZED_FIELDS:
                value = row.get(field)
                if value is not None:
                    data[field] = value
            
            model = StudentModel.from_dict(student_id, data)
            
            # Repopulate Redis cache
            await save_student_model(model)
            
            return model
            
    except Exception as e:
        logger.error(f"Supabase model load failed for {student_id}: {e}")
    
    return model


async def save_student_model(model: StudentModel) -> bool:
    """
    Save a student's model to Redis atomically.
    Syncs to Supabase asynchronously.
    
    Note: total_sessions is managed by brain/state.py's _on_session_ended
    via save_student_memory. total_interactions counts every model save.
    """
    model.last_updated = datetime.now(timezone.utc).isoformat()
    model.total_interactions += 1  # Counts every model update
    
    try:
        from database.client import redis_client
        
        data = model.to_dict()
        
        # Build flat dict with all values as strings (atomic save)
        flat_data = {}
        for key, value in data.items():
            if value is None:
                flat_data[key] = ""
            elif isinstance(value, (dict, list)):
                flat_data[key] = json.dumps(value)
            elif isinstance(value, bool):
                flat_data[key] = "true" if value else "false"
            elif isinstance(value, (float, int)):
                flat_data[key] = str(value)
            else:
                flat_data[key] = str(value)
        
        # Atomic multi-field update — no partial reads possible
        redis_client.hset(model.redis_key, mapping=flat_data)
        redis_client.expire(model.redis_key, 2592000)  # 30 days
        
        # Sync to Supabase asynchronously (non-blocking)
        asyncio.ensure_future(_sync_to_supabase(model, data))
        
        return True
        
    except Exception as e:
        logger.error(f"Redis model save failed for {model.student_id}: {e}")
        return False


async def _sync_to_supabase(model: StudentModel, data: Dict[str, Any]) -> None:
    """
    Sync model to Supabase. Non-blocking.
    
    Builds upsert dict dynamically from ALL serialized fields.
    No field is left behind — full durable backup.
    """
    try:
        from database.client import supabase
        
        # Build upsert dynamically from ALL _SERIALIZED_FIELDS
        upsert_data = {"student_id": model.student_id}
        for field in _SERIALIZED_FIELDS:
            value = data.get(field)
            if value is not None:
                upsert_data[field] = value
        upsert_data["updated_at"] = model.last_updated
        
        supabase.table("student_models").upsert(upsert_data).execute()
        
    except Exception as e:
        logger.error(f"Supabase model sync failed for {model.student_id}: {e}")


async def delete_student_model(student_id: str) -> None:
    """Delete a student's model from both Redis and Supabase."""
    try:
        from database.client import redis_client, supabase
        
        redis_client.delete(f"student_model:{student_id}")
        supabase.table("student_models").delete().eq("student_id", student_id).execute()
        
    except Exception as e:
        logger.error(f"Model deletion failed for {student_id}: {e}")
