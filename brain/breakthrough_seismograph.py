"""
brain/circadian_socket.py — Circadian Teaching Cortex

The Circadian Teaching Cortex does not send messages at times.
It sends messages at STATES.

It reads the student's biological signals — message timing, response delays,
power gaps, data patterns — and decides what to teach, when, and how.

This is not a scheduler. It is a biological-state reader.

Architecture:
    1. BIOLOGICAL STATE DETECTOR — Infer state from signals, not clock
    2. CIRCADIAN PROFILE MANAGER — Learn and persist student rhythms
    3. PEDAGOGICAL ACTION GENERATOR — The RIGHT teaching for THIS state
    4. STATE TRANSITION TRACKER — Learn from behavior, update profile
    5. DEFERRED PLANTING QUEUE — Handle power/data outages gracefully

Connections:
    - PIG Engine (intimacy gating)
    - Ghost Thread Socket (follow-up mechanism)
    - Dialectical Socket (evening-deep activation)
    - Thermal Memory (state-driven thermal assignment)
    - State Socket (biological_state field)
    - Working Memory (topic persistence across states)

CHANGELOG:
    - 2026-05-24: Created — replaces primitive Night Whisper Protocol
"""

import json
import logging
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.circadian")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Biological state boundaries (Nigerian context-adjusted)
DAWN_START_HOUR = 5
DAWN_END_HOUR = 8
SCHOOL_START_HOUR = 8
SCHOOL_END_HOUR = 15
AFTER_SCHOOL_START_HOUR = 15
AFTER_SCHOOL_END_HOUR = 18
EVENING_START_HOUR = 18
EVENING_END_HOUR = 22
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 1  # 1 AM

# Power reliability thresholds
POWER_GAP_HOURS = 6  # Gap > 6h = likely power issue
POWER_RECOVERY_BOOST = 0.05  # Increment when no gap
POWER_DECAY_FACTOR = 0.95  # Decay when gap detected

# Engagement thresholds
FAST_RESPONSE_SECONDS = 120  # < 2 min = high engagement
PEAK_WINDOW_EXTENSION_MINUTES = 15  # Extend peak window by 15 min per fast response

# Dawn question difficulty
DAWN_QUESTION_MAX_WORDS = 15  # Must be answerable in one word/short phrase

# Redis keys
CIRCADIAN_PROFILE_PREFIX = "circadian:profile:{student_id}"
CIRCADIAN_STATE_PREFIX = "circadian:state:{student_id}"
DEFERRED_QUEUE_PREFIX = "circadian:deferred:{student_id}"

# ═══════════════════════════════════════════════════════════════════════
# BIOLOGICAL STATE ENUM
# ═══════════════════════════════════════════════════════════════════════

class BiologicalState(Enum):
    DAWN_HARVEST = "dawn_harvest"
    SCHOOL_STEALTH = "school_stealth"
    AFTER_SCHOOL_FLOOD = "after_school"
    EVENING_DEEP = "evening_deep"
    NIGHT_SURVIVAL = "night_survival"
    DARK = "dark"

    @classmethod
    def from_string(cls, value: str) -> "BiologicalState":
        """Safe conversion from string."""
        try:
            return cls(value)
        except ValueError:
            return cls.DARK


# ═══════════════════════════════════════════════════════════════════════
# CIRCADIAN PROFILE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CircadianProfile:
    """A student's biological rhythm fingerprint."""
    student_id: str
    typical_wake_time: str = "05:30:00"
    typical_sleep_time: str = "23:00:00"
    school_hours_start: str = "08:00:00"
    school_hours_end: str = "15:00:00"
    peak_engagement_start: str = "18:00:00"
    peak_engagement_end: str = "21:00:00"
    data_bundle_cycle: str = "daily"
    power_reliability_score: float = 0.60
    family_phone_competition: str = "high"
    last_known_state: str = "dark"
    last_state_change_at: Optional[str] = None
    state_transition_history: List[Dict[str, Any]] = field(default_factory=list)
    dawn_questions_answered: int = 0
    dawn_questions_correct: int = 0
    sleep_whispers_received: int = 0
    sleep_whispers_recalled_next_day: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for Supabase/Redis storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CircadianProfile":
        """Create from dict (handles missing fields)."""
        # Filter to only valid fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def get_peak_window(self) -> Tuple[time, time]:
        """Get peak engagement window as time objects."""
        return (
            time.fromisoformat(self.peak_engagement_start),
            time.fromisoformat(self.peak_engagement_end),
        )

    def get_school_hours(self) -> Tuple[time, time]:
        """Get school hours as time objects."""
        return (
            time.fromisoformat(self.school_hours_start),
            time.fromisoformat(self.school_hours_end),
        )


# ═══════════════════════════════════════════════════════════════════════
# 1. CIRCADIAN PROFILE MANAGER
# ═══════════════════════════════════════════════════════════════════════

class CircadianProfileManager:
    """Load, create, and persist circadian profiles."""

    def __init__(self):
        self._cache_ttl = 3600  # 1 hour cache

    async def get_profile(self, student_id: str) -> CircadianProfile:
        """
        Get profile from cache, Supabase, or create default.
        """
        # Try Redis cache first
        cache_key = CIRCADIAN_PROFILE_PREFIX.format(student_id=student_id)
        try:
            cached = redis_client.get(cache_key)
            if cached:
                data = json.loads(cached.decode("utf-8") if isinstance(cached, bytes) else cached)
                return CircadianProfile.from_dict(data)
        except Exception as e:
            logger.debug(f"Cache miss for circadian profile {student_id}: {e}")

        # Try Supabase
        try:
            result = (
                supabase.table("circadian_profiles")
                .select("*")
                .eq("student_id", student_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                profile = CircadianProfile.from_dict(result.data[0])
                # Cache it
                try:
                    redis_client.setex(
                        cache_key,
                        self._cache_ttl,
                        json.dumps(profile.to_dict()),
                    )
                except Exception:
                    pass
                return profile
        except Exception as e:
            logger.warning(f"Supabase fetch failed for circadian profile {student_id}: {e}")

        # Create default Nigerian student profile
        profile = CircadianProfile(student_id=student_id)
        await self.save_profile(profile)
        return profile

    async def save_profile(self, profile: CircadianProfile) -> bool:
        """Persist profile to Supabase and cache."""
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        if not profile.created_at:
            profile.created_at = profile.updated_at

        try:
            # Upsert to Supabase
            supabase.table("circadian_profiles").upsert(
                profile.to_dict(),
                on_conflict="student_id",
            ).execute()

            # Update cache
            cache_key = CIRCADIAN_PROFILE_PREFIX.format(student_id=profile.student_id)
            redis_client.setex(
                cache_key,
                self._cache_ttl,
                json.dumps(profile.to_dict()),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save circadian profile: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════
# 2. BIOLOGICAL STATE DETECTOR
# ═══════════════════════════════════════════════════════════════════════

class BiologicalStateDetector:
    """Detect biological state from signals, not just clock time."""

    def __init__(self, profile_manager: CircadianProfileManager):
        self.profile_manager = profile_manager

    async def detect_state(
        self,
        student_id: str,
        current_message_time: Optional[datetime] = None,
        has_connectivity: bool = True,
    ) -> BiologicalState:
        """
        Detect biological state from multiple signals.

        Signals used:
        1. Clock time (base layer)
        2. School hours (contextual override)
        3. Power/connectivity gaps (reliability inference)
        4. Historical pattern (learned wake/sleep times)
        5. Recent message density (exam period detection)
        """
        if not has_connectivity:
            return BiologicalState.DARK

        now = current_message_time or datetime.now(timezone.utc)
        hour = now.hour

        # Get profile for personalized boundaries
        profile = await self.profile_manager.get_profile(student_id)
        school_start = time.fromisoformat(profile.school_hours_start).hour
        school_end = time.fromisoformat(profile.school_hours_end).hour

        # Override 1: School hours (if student is physically at school)
        if school_start <= hour < school_end:
            # But if they messaged during school, they have phone access
            return BiologicalState.SCHOOL_STEALTH

        # Override 2: Personalized wake/sleep boundaries
        wake_hour = time.fromisoformat(profile.typical_wake_time).hour
        sleep_hour = time.fromisoformat(profile.typical_sleep_time).hour

        # Dawn: between wake time and school start
        if wake_hour <= hour < school_start:
            return BiologicalState.DAWN_HARVEST

        # After school: between school end and evening start
        if school_end <= hour < EVENING_START_HOUR:
            return BiologicalState.AFTER_SCHOOL_FLOOD

        # Evening: peak engagement window
        peak_start = time.fromisoformat(profile.peak_engagement_start).hour
        peak_end = time.fromisoformat(profile.peak_engagement_end).hour
        if peak_start <= hour < peak_end:
            return BiologicalState.EVENING_DEEP

        # Night: after peak end until sleep time
        if peak_end <= hour or hour < wake_hour:
            # Check if it's "late night" (after midnight) vs "night survival"
            if hour >= NIGHT_START_HOUR or hour < 2:
                return BiologicalState.NIGHT_SURVIVAL
            # Between sleep time and late night = still evening transition
            return BiologicalState.EVENING_DEEP

        # Default
        return BiologicalState.AFTER_SCHOOL_FLOOD

    async def detect_connectivity_status(self, student_id: str) -> bool:
        """
        Detect if student likely has connectivity.
        Uses recent message patterns as proxy.
        """
        try:
            # Check last message time
            result = (
                supabase.table("conversations")
                .select("created_at")
                .eq("student_id", student_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                last_msg = datetime.fromisoformat(
                    result.data[0]["created_at"].replace("Z", "+00:00")
                )
                gap_hours = (datetime.now(timezone.utc) - last_msg).total_seconds() / 3600
                # If gap > 12 hours, assume connectivity issues
                if gap_hours > 12:
                    return False
            return True
        except Exception:
            return True  # Assume connected if we can't check


# ═══════════════════════════════════════════════════════════════════════
# 3. PEDAGOGICAL ACTION GENERATOR
# ═══════════════════════════════════════════════════════════════════════

class PedagogicalActionGenerator:
    """Generate the RIGHT teaching action for each biological state."""

    def __init__(
        self,
        profile_manager: CircadianProfileManager,
        pig_engine=None,
        ghost_socket=None,
    ):
        self.profile_manager = profile_manager
        self.pig_engine = pig_engine
        self.ghost_socket = ghost_socket

    async def generate_action(
        self,
        student_id: str,
        state: BiologicalState,
        current_topic: Optional[str] = None,
        last_session_summary: Optional[Dict[str, Any]] = None,
        working_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate complete pedagogical action for this state.

        Returns dict with:
        - action: str (what to do)
        - message_type: str (how to package it)
        - thermal_state: str (hot/warm/cool/cold)
        - content: str (the actual message)
        - delivery_config: dict (silent, timeout, follow-up)
        """
        generators = {
            BiologicalState.DAWN_HARVEST: self._generate_dawn_action,
            BiologicalState.SCHOOL_STEALTH: self._generate_school_action,
            BiologicalState.AFTER_SCHOOL_FLOOD: self._generate_afterschool_action,
            BiologicalState.EVENING_DEEP: self._generate_evening_action,
            BiologicalState.NIGHT_SURVIVAL: self._generate_night_action,
            BiologicalState.DARK: self._generate_dark_action,
        }

        generator = generators.get(state, self._generate_afterschool_action)
        return await generator(student_id, current_topic, last_session_summary, working_memory)

    async def _generate_dawn_action(
        self,
        student_id: str,
        topic: Optional[str],
        last_session: Optional[Dict],
        working_memory: Optional[Dict],
    ) -> Dict[str, Any]:
        """Dawn Harvest: Retrieval practice, one question, no explanation."""
        question = self._generate_dawn_question(topic, last_session)

        return {
            "action": "retrieval_practice",
            "message_type": "one_question_quiz",
            "thermal_state": "cool",
            "content": question,
            "delivery_config": {
                "silent": False,
                "expected_response_time_seconds": 60,
                "follow_up_if_no_response": None,
                "max_response_length": 5,  # One word or short phrase
            },
            "pedagogical_notes": "Do not explain. Just ask. The retrieval itself is the learning.",
        }

    async def _generate_school_action(
        self,
        student_id: str,
        topic: Optional[str],
        last_session: Optional[Dict],
        working_memory: Optional[Dict],
    ) -> Dict[str, Any]:
        """School Stealth: Micro-anchoring, plant a concept seed."""
        seed = self._generate_school_seed(topic)

        return {
            "action": "micro_anchoring",
            "message_type": "single_sentence_seed",
            "thermal_state": "warm",
            "content": seed,
            "delivery_config": {
                "silent": True,  # No notification sound
                "expected_response_time_seconds": 300,  # May reply during break
                "follow_up_if_no_response": None,
            },
            "pedagogical_notes": "Plant a seed. Don't water it. The student will water it tonight.",
        }

    async def _generate_afterschool_action(
        self,
        student_id: str,
        topic: Optional[str],
        last_session: Optional[Dict],
        working_memory: Optional[Dict],
    ) -> Dict[str, Any]:
        """After-School Flood: Emotional recovery or warm re-engagement."""
        # PIG-gated: high intimacy = re-engage, low = recover
        intimacy = 0.0
        if self.pig_engine:
            try:
                from brain.relational_intimacy import get_current_intimacy_score
                intimacy = await get_current_intimacy_score(student_id)
            except Exception:
                pass

        if intimacy >= 5.0:
            # High intimacy — warm re-entry
            content = self._generate_warm_reentry(topic, last_session)
            return {
                "action": "re_engagement",
                "message_type": "warm_continuity",
                "thermal_state": "hot",
                "content": content,
                "delivery_config": {
                    "silent": False,
                    "expected_response_time_seconds": 600,
                    "follow_up_if_no_response": "ghost_thread",
                },
                "pedagogical_notes": "Student trusts us. Re-engage immediately.",
            }

        # Low intimacy — emotional recovery
        return {
            "action": "emotional_recovery",
            "message_type": "low_pressure_invitation",
            "thermal_state": "warm",
            "content": "School done? Take your time. I'm here when you're ready.",
            "delivery_config": {
                "silent": False,
                "expected_response_time_seconds": 1800,  # 30 min
                "follow_up_if_no_response": None,
            },
            "pedagogical_notes": "Student is exhausted. Don't teach. Just be present.",
        }

    async def _generate_evening_action(
        self,
        student_id: str,
        topic: Optional[str],
        last_session: Optional[Dict],
        working_memory: Optional[Dict],
    ) -> Dict[str, Any]:
        """Evening Deep: Full teaching mode. All subsystems active."""
        return {
            "action": "deep_teaching",
            "message_type": "full_dialectical",
            "thermal_state": "hot",
            "content": None,  # Will be generated by Dialectical Engine
            "delivery_config": {
                "silent": False,
                "expected_response_time_seconds": 120,
                "follow_up_if_no_response": "ghost_thread",
            },
            "subsystems_active": ["dissonance_scanner", "triad_orchestrator", "ghost_thread"],
            "pedagogical_notes": "Golden window. All systems go. Dialectical debates welcome.",
        }

    async def _generate_night_action(
        self,
        student_id: str,
        topic: Optional[str],
        last_session: Optional[Dict],
        working_memory: Optional[Dict],
    ) -> Dict[str, Any]:
        """Night Survival: Consolidation priming. NOT new learning."""
        whisper = self._generate_sleep_whisper(topic)

        return {
            "action": "consolidation_prime",
            "message_type": "sleep_whisper",
            "thermal_state": "cold",
            "content": whisper,
            "delivery_config": {
                "silent": True,  # No notification sound
                "expected_response_time_seconds": None,  # No expectation
                "follow_up_if_no_response": "dawn_harvest_question",
                "do_not_disturb": True,
            },
            "pedagogical_notes": "Don't teach. Prime. The brain consolidates during sleep.",
        }

    async def _generate_dark_action(
        self,
        student_id: str,
        topic: Optional[str],
        last_session: Optional[Dict],
        working_memory: Optional[Dict],
    ) -> Dict[str, Any]:
        """Dark: Deferred planting. Queue until connectivity restored."""
        queued = self._generate_queued_content(topic)

        return {
            "action": "deferred_planting",
            "message_type": "queued_message",
            "thermal_state": "cold",
            "content": queued,
            "delivery_config": {
                "queue_until": "connectivity_restored",
                "expected_response_time_seconds": None,
            },
            "pedagogical_notes": "Student is dark. Plant the seed in soil, not in air.",
        }

    # ═════════════════════════════════════════════════════════════════
    # CONTENT GENERATORS
    # ═════════════════════════════════════════════════════════════════

    def _generate_dawn_question(
        self,
        topic: Optional[str],
        last_session: Optional[Dict],
    ) -> str:
        """Generate a single retrieval question for dawn."""
        if last_session and last_session.get("unfinished_problem"):
            return f"Before school: What was the next step in {last_session['unfinished_problem']}? One word."

        if topic:
            questions = {
                "physics": [
                    "Quick one: V = IR. What does R stand for?",
                    "Before you head out: What's the unit of resistance?",
                    "One word: Current flows from _____ to _____ potential.",
                ],
                "chemistry": [
                    "Quick: H2SO4 is called what? One word.",
                    "Before school: Acid + Base = ? Two words.",
                    "One word: pH below 7 is _____.",
                ],
                "biology": [
                    "Quick: Photosynthesis makes sugar from what? Two things.",
                    "Before you go: Mitochondria are the _____ of the cell.",
                    "One word: DNA stands for _____.",
                ],
                "mathematics": [
                    "Quick: a² - b² factors into what? Two terms.",
                    "Before school: Sum of angles in a triangle? One number.",
                    "One word: The quadratic formula gives us the _____.",
                ],
            }
            if topic.lower() in questions:
                return random.choice(questions[topic.lower()])

        return "Quick one before school: What did we learn about yesterday? One word answer."

    def _generate_school_seed(self, topic: Optional[str]) -> str:
        """Plant a concept seed for school observation."""
        seeds = {
            "physics": [
                "In physics today, watch how your teacher draws circuits. Notice which way the arrows point.",
                "When they do the Ohm's Law example, check: did they use V=IR or I=V/R?",
            ],
            "chemistry": [
                "When you do the titration practical, watch the color change carefully. That's the endpoint we talked about.",
                "In the lab today, see if the acid turns litmus red or blue. You know this.",
            ],
            "biology": [
                "Look at the leaf under the microscope today. Those tiny holes are stomata — like pores for breathing.",
                "When they show cell division, count the chromosomes. Are there 46 or 23 in the final cells?",
            ],
            "mathematics": [
                "In today's math class, see if your teacher uses the same factorization method we practiced. Is it faster or slower?",
                "When they do simultaneous equations, watch: do they use substitution or elimination?",
            ],
        }

        if topic and topic.lower() in seeds:
            return random.choice(seeds[topic.lower()])

        return "Today in class, look for one thing that connects to what we studied. Tell me later."

    def _generate_warm_reentry(
        self,
        topic: Optional[str],
        last_session: Optional[Dict],
    ) -> str:
        """Generate warm re-engagement after school."""
        if last_session and last_session.get("unfinished_problem"):
            return (
                f"Welcome back! We left off here: {last_session['unfinished_problem']}. "
                f"Ready to finish it, or need a break first?"
            )

        if topic:
            return f"School's done. Ready to pick up {topic.replace('_', ' ')} where we left off? No rush — I'm here."

        return "How was school? Ready to study, or need to decompress first?"

    def _generate_sleep_whisper(self, topic: Optional[str]) -> str:
        """Generate a consolidation whisper for sleep."""
        whispers = {
            "physics": [
                "Sleep on this: Current is the flow. Voltage is the push. Resistance is the fight. Your brain will sort it out tonight.",
                "Tonight's whisper: Power = Voltage × Current. P = VI. Simple. Dream in watts.",
            ],
            "chemistry": [
                "Tonight's whisper: Acids donate H+. Bases accept H+. Simple as that. Dream in molecules.",
                "Sleep on this: Mole = 6.02 × 10²³. Avogadro's number. Your brain loves patterns.",
            ],
            "biology": [
                "Before sleep: Photosynthesis turns light into sugar. Your body turns sugar into energy. Both are chemistry. Goodnight.",
                "Tonight's whisper: DNA unzips, copies, zips back. Every night in your cells. Sleep well.",
            ],
            "mathematics": [
                "Sleep whisper: Every quadratic has two roots. Sometimes real, sometimes imaginary. Both are true. Goodnight.",
                "Tonight: a² + 2ab + b² = (a+b)². Your brain will prove it while you sleep.",
            ],
        }

        if topic and topic.lower() in whispers:
            return random.choice(whispers[topic.lower()])

        return (
            "Don't answer now. Just hold this thought from today: "
            "what was the one thing that finally clicked? Sleep on it. We'll talk tomorrow."
        )

    def _generate_queued_content(self, topic: Optional[str]) -> str:
        """Generate content for when student comes back online."""
        if topic:
            return f"You're back! While you were away, I kept your {topic.replace('_', ' ')} notes warm. Ready to continue?"

        return "Welcome back! I kept your study space ready. What should we work on?"


# ═══════════════════════════════════════════════════════════════════════
# 4. STATE TRANSITION TRACKER
# ═══════════════════════════════════════════════════════════════════════

class StateTransitionTracker:
    """Learn student rhythms from behavior. Update profile."""

    def __init__(self, profile_manager: CircadianProfileManager):
        self.profile_manager = profile_manager

    async def record_message(
        self,
        student_id: str,
        message_time: datetime,
        response_time_seconds: Optional[float] = None,
        message_length: int = 0,
        is_first_of_day: bool = False,
        is_last_of_night: bool = False,
    ):
        """
        Record a message event and update the student's circadian profile.
        """
        profile = await self.profile_manager.get_profile(student_id)

        # Update wake time
        if is_first_of_day:
            profile.typical_wake_time = message_time.strftime("%H:%M:%S")

        # Update sleep time
        if is_last_of_night:
            profile.typical_sleep_time = message_time.strftime("%H:%M:%S")

        # Update engagement window
        if response_time_seconds and response_time_seconds < FAST_RESPONSE_SECONDS:
            self._extend_peak_window(profile, message_time.time())

        # Update power reliability
        self._update_power_reliability(profile, message_time)

        # Record transition
        transition = {
            "timestamp": message_time.isoformat(),
            "response_time": response_time_seconds,
            "message_length": message_length,
            "state": profile.last_known_state,
        }
        profile.state_transition_history.append(transition)
        # Keep only last 50 transitions
        profile.state_transition_history = profile.state_transition_history[-50:]

        # Save
        await self.profile_manager.save_profile(profile)

    def _extend_peak_window(self, profile: CircadianProfile, msg_time: time):
        """Extend peak engagement window if student is responsive."""
        current_start = time.fromisoformat(profile.peak_engagement_start)
        current_end = time.fromisoformat(profile.peak_engagement_end)

        # If message is within 1 hour of current window, extend
        msg_minutes = msg_time.hour * 60 + msg_time.minute
        start_minutes = current_start.hour * 60 + current_start.minute
        end_minutes = current_end.hour * 60 + current_end.minute

        if abs(msg_minutes - start_minutes) < 60:
            # Extend start earlier
            new_start = max(0, start_minutes - PEAK_WINDOW_EXTENSION_MINUTES)
            profile.peak_engagement_start = f"{new_start // 60:02d}:{new_start % 60:02d}:00"

        if abs(msg_minutes - end_minutes) < 60:
            # Extend end later
            new_end = min(1439, end_minutes + PEAK_WINDOW_EXTENSION_MINUTES)
            profile.peak_engagement_end = f"{new_end // 60:02d}:{new_end % 60:02d}:00"

    def _update_power_reliability(self, profile: CircadianProfile, message_time: datetime):
        """Update power reliability score based on message gaps."""
        if not profile.state_transition_history:
            return

        last_transition = profile.state_transition_history[-1]
        last_time = datetime.fromisoformat(last_transition["timestamp"].replace("Z", "+00:00"))
        gap_hours = (message_time - last_time).total_seconds() / 3600

        if gap_hours > POWER_GAP_HOURS:
            # Long gap = power issue
            profile.power_reliability_score *= POWER_DECAY_FACTOR
        else:
            # Normal gap = power OK
            profile.power_reliability_score = min(
                1.0,
                profile.power_reliability_score * (1 + POWER_RECOVERY_BOOST),
            )


# ═══════════════════════════════════════════════════════════════════════
# 5. DEFERRED PLANTING QUEUE
# ═══════════════════════════════════════════════════════════════════════

class DeferredPlantingQueue:
    """Queue messages when student has no connectivity."""

    def __init__(self):
        pass

    async def queue_message(
        self,
        student_id: str,
        content: str,
        action_type: str,
        thermal_state: str = "cold",
    ) -> bool:
        """Queue a message for later delivery."""
        try:
            queue_key = DEFERRED_QUEUE_PREFIX.format(student_id=student_id)
            message = {
                "content": content,
                "action_type": action_type,
                "thermal_state": thermal_state,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }
            redis_client.lpush(queue_key, json.dumps(message))
            # Set TTL to 7 days
            redis_client.expire(queue_key, int(timedelta(days=7).total_seconds()))
            return True
        except Exception as e:
            logger.error(f"Failed to queue deferred message: {e}")
            return False

    async def deliver_queued(self, student_id: str) -> List[Dict[str, Any]]:
        """Deliver all queued messages when student comes back online."""
        try:
            queue_key = DEFERRED_QUEUE_PREFIX.format(student_id=student_id)
            messages = []
            while True:
                raw = redis_client.rpop(queue_key)
                if not raw:
                    break
                msg = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                messages.append(msg)
            return messages
        except Exception as e:
            logger.error(f"Failed to deliver queued messages: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════
# 6. CIRCADIAN TEACHING CORTEX — Main API
# ═══════════════════════════════════════════════════════════════════════

class CircadianTeachingCortex:
    """
    Main API for the Circadian Teaching Cortex.

    Usage:
        cortex = CircadianTeachingCortex(student_id)
        state = await cortex.detect_current_state()
        action = await cortex.generate_pedagogical_action(state, topic="physics")
        # action contains the complete teaching strategy
    """

    def __init__(self, student_id: str):
        self.student_id = student_id
        self.profile_manager = CircadianProfileManager()
        self.state_detector = BiologicalStateDetector(self.profile_manager)
        self.action_generator = PedagogicalActionGenerator(
            profile_manager=self.profile_manager,
        )
        self.transition_tracker = StateTransitionTracker(self.profile_manager)
        self.deferred_queue = DeferredPlantingQueue()

    async def detect_current_state(self) -> BiologicalState:
        """Detect current biological state."""
        return await self.state_detector.detect_state(self.student_id)

    async def generate_pedagogical_action(
        self,
        state: Optional[BiologicalState] = None,
        current_topic: Optional[str] = None,
        last_session_summary: Optional[Dict[str, Any]] = None,
        working_memory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate complete pedagogical action."""
        if state is None:
            state = await self.detect_current_state()

        # Update last known state
        profile = await self.profile_manager.get_profile(self.student_id)
        if state.value != profile.last_known_state:
            profile.last_known_state = state.value
            profile.last_state_change_at = datetime.now(timezone.utc).isoformat()
            await self.profile_manager.save_profile(profile)

        return await self.action_generator.generate_action(
            student_id=self.student_id,
            state=state,
            current_topic=current_topic,
            last_session_summary=last_session_summary,
            working_memory=working_memory,
        )

    async def record_student_message(
        self,
        message_time: datetime,
        response_time_seconds: Optional[float] = None,
        message_length: int = 0,
    ):
        """Record a student message and learn from it."""
        # Detect if first message of day
        is_first = await self._is_first_message_of_day(message_time)
        # Detect if last message of night (heuristic: after 10 PM)
        is_last = message_time.hour >= 22

        await self.transition_tracker.record_message(
            student_id=self.student_id,
            message_time=message_time,
            response_time_seconds=response_time_seconds,
            message_length=message_length,
            is_first_of_day=is_first,
            is_last_of_night=is_last,
        )

    async def _is_first_message_of_day(self, message_time: datetime) -> bool:
        """Check if this is likely the first message of the day."""
        try:
            result = (
                supabase.table("conversations")
                .select("created_at")
                .eq("student_id", self.student_id)
                .gte("created_at", message_time.replace(hour=0, minute=0, second=0).isoformat())
                .lt("created_at", message_time.isoformat())
                .limit(1)
                .execute()
            )
            return not result.data  # No earlier messages today
        except Exception:
            return False

    async def queue_for_connectivity(self, content: str, action_type: str) -> bool:
        """Queue a message for when student regains connectivity."""
        return await self.deferred_queue.queue_message(
            self.student_id, content, action_type
        )

    async def deliver_deferred(self) -> List[Dict[str, Any]]:
        """Deliver queued messages when student is back online."""
        return await self.deferred_queue.deliver_queued(self.student_id)


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API FUNCTIONS (for handler.py)
# ═══════════════════════════════════════════════════════════════════════

async def get_circadian_state(student_id: str) -> str:
    """Get current biological state as string."""
    cortex = CircadianTeachingCortex(student_id)
    state = await cortex.detect_current_state()
    return state.value


async def get_pedagogical_action(
    student_id: str,
    current_topic: Optional[str] = None,
    working_memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Get complete pedagogical action for current state."""
    cortex = CircadianTeachingCortex(student_id)
    return await cortex.generate_pedagogical_action(
        current_topic=current_topic,
        working_memory=working_memory,
    )


async def record_message_for_learning(
    student_id: str,
    message_time: Optional[datetime] = None,
    response_time_seconds: Optional[float] = None,
    message_length: int = 0,
):
    """Record student message to learn their rhythm."""
    cortex = CircadianTeachingCortex(student_id)
    await cortex.record_student_message(
        message_time=message_time or datetime.now(timezone.utc),
        response_time_seconds=response_time_seconds,
        message_length=message_length,
    )
