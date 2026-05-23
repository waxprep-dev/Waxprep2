# Changes made:
# - Replaced record_message method to wire in Mind Mirror analysis (via brain.student_mind_mirror)
#   with fallback to _simple_mind_heuristic if Mind Mirror fails.
# - Also kept the earlier fix: reconstruct_from_history now uses the State Archaeologist.

"""
brain/state_cortex.py — Wax State Cortex
The 4-Dimensional Living State Architecture.

NO CORE FILE IMPORTS THIS DIRECTLY.
Only brain/state_socket.py talks to the Cortex.
"""

import json
import logging
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger("waxprep.state_cortex")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

class DecayConfig:
    """Half-life configuration per state component (in minutes)."""
    WAX_MODE = {
        "in_quiz": 10,
        "awaiting_response": 5,
        "in_emotional_support": 30,
        "teaching": 15,
        "chatting": 20,
        "onboarding": 60,
        "paused": 45,
        "ended": 5,
        "idle": 60,
    }
    
    STUDENT_MIND = {
        "confident": 20,
        "confused": 15,
        "frustrated": 25,
        "engaged": 30,
        "bored": 10,
        "curious": 20,
        "anxious": 20,
        "motivated": 25,
    }

# Probability precision
PRECISION = Decimal("0.001")


# ═══════════════════════════════════════════════════════════════════════
# 4D STATE VECTOR
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class StateVector:
    """
    The 4-dimensional state of a Wax conversation.
    
    D1: Wax Mode — What Wax is doing (probabilistic weights)
    D2: Student Mind — Inferred cognitive/affective state
    D3: Conversation Topology — Where we are in discourse
    D4: Environmental Context — Time, network, device, data
    """
    
    # D1: Wax Mode (probabilistic, sum to 1.0)
    wax_mode: Dict[str, Decimal]
    
    # D2: Student Mind (inferred cognitive/affective state)
    student_mind: Dict[str, Decimal]
    
    # D3: Conversation Topology (discrete position)
    conversation_topology: str  # opening | deepening | closing | branching | merging | recovering
    
    # D4: Environmental Context
    env_context: Dict[str, Any]
    
    # Temporal metadata
    created_at: datetime
    last_updated: datetime
    version: int = 1
    
    def __post_init__(self):
        """Normalize probabilities and set defaults."""
        self.wax_mode = self._normalize(self.wax_mode)
        self.student_mind = self._normalize(self.student_mind)
        
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)
        if not self.last_updated:
            self.last_updated = datetime.now(timezone.utc)
    
    @staticmethod
    def _normalize(probs: Dict[str, Decimal]) -> Dict[str, Decimal]:
        """Normalize probabilities to sum to 1.0."""
        if not probs:
            return {}
        
        # Filter negative and clamp
        cleaned = {k: max(Decimal("0"), min(Decimal("1"), v)) 
                   for k, v in probs.items()}
        
        total = sum(cleaned.values())
        if total == 0:
            return cleaned
        
        # Normalize to sum to 1.0
        normalized = {}
        for k, v in cleaned.items():
            normalized[k] = (v / total).quantize(PRECISION, rounding=ROUND_HALF_UP)
        
        return normalized
    
    def current_effective_state(self) -> Dict[str, Decimal]:
        """Apply temporal decay to wax_mode components."""
        elapsed_minutes = (datetime.now(timezone.utc) - self.last_updated).total_seconds() / 60
        effective = {}
        
        for state, strength in self.wax_mode.items():
            half_life = DecayConfig.WAX_MODE.get(state, 10)
            if half_life <= 0:
                half_life = 10
            
            # Exponential decay: N = N0 * (0.5)^(t/t_half)
            decay_factor = Decimal("0.5") ** Decimal(str(elapsed_minutes / half_life))
            effective[state] = (strength * decay_factor).quantize(PRECISION)
        
        return effective
    
    def current_effective_mind(self) -> Dict[str, Decimal]:
        """Apply temporal decay to student_mind components."""
        elapsed_minutes = (datetime.now(timezone.utc) - self.last_updated).total_seconds() / 60
        effective = {}
        
        for state, strength in self.student_mind.items():
            half_life = DecayConfig.STUDENT_MIND.get(state, 20)
            if half_life <= 0:
                half_life = 20
            
            decay_factor = Decimal("0.5") ** Decimal(str(elapsed_minutes / half_life))
            effective[state] = (strength * decay_factor).quantize(PRECISION)
        
        return effective
    
    def dominant_mode(self) -> Tuple[str, Decimal]:
        """Return the highest-confidence wax mode after decay."""
        effective = self.current_effective_state()
        if not effective:
            return ("idle", Decimal("1.0"))
        
        dominant = max(effective, key=effective.get)
        return (dominant, effective[dominant])
    
    def dominant_mind_state(self) -> Tuple[str, Decimal]:
        """Return the highest-confidence student mind state after decay."""
        effective = self.current_effective_mind()
        if not effective:
            return ("neutral", Decimal("1.0"))
        
        dominant = max(effective, key=effective.get)
        return (dominant, effective[dominant])
    
    def is_in_superposition(self, threshold: Decimal = Decimal("0.3")) -> bool:
        """True if multiple modes are active above threshold."""
        effective = self.current_effective_state()
        strong_modes = [k for k, v in effective.items() if v >= threshold]
        return len(strong_modes) > 1
    
    def get_superposition_modes(self, threshold: Decimal = Decimal("0.3")) -> Dict[str, Decimal]:
        """Return all modes above threshold."""
        effective = self.current_effective_state()
        return {k: v for k, v in effective.items() if v >= threshold}
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON/Redis storage."""
        return {
            "wax_mode": {k: str(v) for k, v in self.wax_mode.items()},
            "student_mind": {k: str(v) for k, v in self.student_mind.items()},
            "conversation_topology": self.conversation_topology,
            "env_context": self.env_context,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "version": self.version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateVector":
        """Deserialize from dictionary."""
        wax_mode = {k: Decimal(v) for k, v in data.get("wax_mode", {}).items()}
        student_mind = {k: Decimal(v) for k, v in data.get("student_mind", {}).items()}
        
        return cls(
            wax_mode=wax_mode,
            student_mind=student_mind,
            conversation_topology=data.get("conversation_topology", "opening"),
            env_context=data.get("env_context", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else datetime.now(timezone.utc),
            version=data.get("version", 1),
        )
    
    @classmethod
    def default(cls) -> "StateVector":
        """Create a default state vector for new conversations."""
        return cls(
            wax_mode={"idle": Decimal("1.0")},
            student_mind={"neutral": Decimal("1.0")},
            conversation_topology="opening",
            env_context={
                "time_of_day": _get_time_of_day(),
                "network_quality": "unknown",
                "session_age_minutes": 0,
                "data_bundle_likely_active": True,
                "device_type": "unknown",
            },
            created_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
        )


# ═══════════════════════════════════════════════════════════════════════
# STATE CORTEX ENGINE
# ═══════════════════════════════════════════════════════════════════════

class StateCortex:
    """
    The living engine that manages 4D state vectors.
    
    Responsibilities:
    - Create and update StateVectors
    - Apply superposition shifts
    - Handle temporal decay
    - Persist to Redis and Supabase
    - Provide crash recovery hooks
    """
    
    def __init__(self):
        self._local_cache: Dict[str, StateVector] = {}
        self._message_counts: Dict[str, int] = {}
    
    async def get_vector(self, student_id: str) -> StateVector:
        """
        Retrieve the current StateVector for a student.
        Tries: local cache → Redis → Supabase → default
        """
        if not student_id:
            return StateVector.default()
        
        # 1. Local cache
        if student_id in self._local_cache:
            return self._local_cache[student_id]
        
        # 2. Redis
        try:
            from database.client import redis_client
            key = f"state_cortex:vector:{student_id}"
            raw = redis_client.get(key)
            if raw:
                data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                vector = StateVector.from_dict(data)
                self._local_cache[student_id] = vector
                return vector
        except Exception as e:
            logger.error(f"Redis vector read failed for {student_id}: {e}")
        
        # 3. Supabase
        try:
            from database.client import supabase
            result = supabase.table("state_vectors") \
                .select("*") \
                .eq("student_id", student_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            
            if result.data and len(result.data) > 0:
                data = result.data[0]
                vector_data = data.get("vector_data", {})
                vector = StateVector.from_dict(vector_data)
                self._local_cache[student_id] = vector
                return vector
        except Exception as e:
            logger.error(f"Supabase vector read failed for {student_id}: {e}")
        
        # 4. Default
        vector = StateVector.default()
        self._local_cache[student_id] = vector
        return vector
    
    async def update_vector(
        self,
        student_id: str,
        mode_updates: Optional[Dict[str, Decimal]] = None,
        mind_updates: Optional[Dict[str, Decimal]] = None,
        topology: Optional[str] = None,
        env_updates: Optional[Dict[str, Any]] = None,
        confidence: Decimal = Decimal("1.0"),
    ) -> StateVector:
        """
        Update a StateVector with new probability weights.
        
        This is the core superposition engine. Instead of replacing modes,
        it shifts probability weight toward the new mode while preserving
        existing context (superposition).
        """
        vector = await self.get_vector(student_id)
        
        # Update wax_mode with superposition
        if mode_updates:
            for mode, weight in mode_updates.items():
                # Shift existing probabilities toward new mode
                shift_factor = Decimal("0.3") * confidence  # How much to shift
                
                # Reduce all existing modes
                for existing_mode in vector.wax_mode:
                    vector.wax_mode[existing_mode] *= (Decimal("1") - shift_factor)
                
                # Add or boost the new mode
                if mode in vector.wax_mode:
                    vector.wax_mode[mode] += weight * shift_factor
                else:
                    vector.wax_mode[mode] = weight * shift_factor
                
                # Re-normalize
                vector.wax_mode = vector._normalize(vector.wax_mode)
        
        # Update student_mind with superposition
        if mind_updates:
            for state, weight in mind_updates.items():
                shift_factor = Decimal("0.2") * confidence
                
                for existing_state in vector.student_mind:
                    vector.student_mind[existing_state] *= (Decimal("1") - shift_factor)
                
                if state in vector.student_mind:
                    vector.student_mind[state] += weight * shift_factor
                else:
                    vector.student_mind[state] = weight * shift_factor
                
                vector.student_mind = vector._normalize(vector.student_mind)
        
        # Update topology
        if topology:
            vector.conversation_topology = topology
        
        # Update environmental context
        if env_updates:
            vector.env_context.update(env_updates)
            vector.env_context["time_of_day"] = _get_time_of_day()
        
        # Update timestamp
        vector.last_updated = datetime.now(timezone.utc)
        
        # Cache and persist
        self._local_cache[student_id] = vector
        await self._persist_vector(student_id, vector)
        
        return vector
    
    async def set_dominant_mode(
        self,
        student_id: str,
        mode: str,
        confidence: Decimal = Decimal("1.0"),
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StateVector:
        """
        Set a mode as dominant (high probability, clear intent).
        Use this when the intent is unambiguous (e.g., quiz start).
        """
        mode_updates = {mode: confidence}
        topology = "deepening" if mode in ("teaching", "in_quiz") else "opening"
        
        return await self.update_vector(
            student_id=student_id,
            mode_updates=mode_updates,
            topology=topology,
            env_updates=metadata or {},
            confidence=confidence,
        )
    
    async def record_message(
        self,
        student_id: str,
        role: str,
        content: str,
    ) -> StateVector:
        """
        Process a message and update the state vector with Mind Mirror analysis.
        """
        vector = await self.get_vector(student_id)
        
        # Get conversation history for context
        conversation_history = []
        try:
            from database.conversations import get_history
            conversation_history = await get_history(student_id)
        except Exception:
            pass
        
        # Run Mind Mirror analysis
        try:
            from brain.student_mind_mirror import get_mind_mirror
            mind_mirror = get_mind_mirror()
            analysis = await mind_mirror.analyze_message(
                student_id=student_id,
                role=role,
                content=content,
                conversation_history=conversation_history,
            )
            
            mind_updates = analysis.get("mind_updates", {})
            commitment_delta = analysis.get("commitment_delta", Decimal("0"))
            
            # Apply mind updates to vector
            if mind_updates:
                vector = await self.update_vector(
                    student_id=student_id,
                    mind_updates=mind_updates,
                )
            
            # Track commitment score separately (for account creation)
            if commitment_delta != Decimal("0"):
                current_commitment = Decimal(str(vector.env_context.get("commitment_score", "0")))
                new_commitment = max(Decimal("0"), min(Decimal("1"), current_commitment + commitment_delta))
                vector.env_context["commitment_score"] = str(new_commitment.quantize(Decimal("0.001")))
                vector = await self.update_vector(
                    student_id=student_id,
                    env_updates={"commitment_score": str(new_commitment)},
                )
                
        except Exception as e:
            logger.error(f"Mind Mirror analysis failed for {student_id}: {e}")
            # Fallback to simple heuristic
            mind_updates = self._simple_mind_heuristic(content)
            if mind_updates:
                vector = await self.update_vector(
                    student_id=student_id,
                    mind_updates=mind_updates,
                )
        
        # Update topology based on message patterns
        topology = None
        if role == "user":
            content_lower = content.lower()
            if any(s in content_lower for s in ["bye", "goodnight", "done", "later"]):
                topology = "closing"
            elif vector.conversation_topology == "opening" and len(content) > 10:
                topology = "deepening"
        elif role == "assistant":
            if "?" in content:
                topology = "deepening"
        
        if topology:
            vector = await self.update_vector(
                student_id=student_id,
                topology=topology,
            )
        
        # Increment message count for auto-snapshot
        self._message_counts[student_id] = self._message_counts.get(student_id, 0) + 1
        if self._message_counts[student_id] % 5 == 0:
            await self._snapshot_to_supabase(student_id, vector)
        
        return vector
    
    def _simple_mind_heuristic(self, content: str) -> Dict[str, Decimal]:
        """Fallback heuristic if Mind Mirror fails."""
        content_lower = content.lower()
        updates = {}
        
        confusion_signals = ["don't understand", "confused", "stuck", "lost", "don't get", "huh", "wait", "how"]
        if any(s in content_lower for s in confusion_signals):
            updates["confused"] = Decimal("0.7")
        
        frustration_signals = ["this is hard", "i give up", "too difficult", "impossible", "i can't", "annoying"]
        if any(s in content_lower for s in frustration_signals):
            updates["frustrated"] = Decimal("0.8")
        
        excitement_signals = ["i get it", "that makes sense", "oh wow", "cool", "awesome"]
        if any(s in content_lower for s in excitement_signals):
            updates["engaged"] = Decimal("0.7")
        
        curiosity_signals = ["what if", "why", "how come", "what about", "can you explain"]
        if any(s in content_lower for s in curiosity_signals):
            updates["curious"] = Decimal("0.6")
        
        confidence_signals = ["i know", "easy", "simple", "i can do this", "got it"]
        if any(s in content_lower for s in confidence_signals):
            updates["confident"] = Decimal("0.6")
        
        return updates
    
    async def get_context_string(self, student_id: str) -> str:
        """
        Generate a human-readable context string for AI prompt injection.
        This is what the Socket calls to enrich the AI's understanding.
        """
        vector = await self.get_vector(student_id)
        
        effective_modes = vector.current_effective_state()
        dominant_mode, mode_confidence = vector.dominant_mode()
        
        effective_mind = vector.current_effective_mind()
        dominant_mind, mind_confidence = vector.dominant_mind_state()
        
        # Build mode description
        mode_descriptions = {
            "idle": "just starting or returning after a break",
            "chatting": "in a normal conversation",
            "teaching": "actively teaching a concept",
            "in_quiz": "answering a quiz question",
            "in_emotional_support": "needing emotional support",
            "awaiting_response": "waiting for the student to answer a question",
            "onboarding": "being onboarded as a new student",
            "paused": "in a paused session",
            "ended": "in an ended session",
        }
        
        mode_desc = mode_descriptions.get(dominant_mode, "learning")
        
        parts = [f"[STATE] Wax is {mode_desc} (confidence: {float(mode_confidence):.0%})."]
        
        # Add superposition info if relevant
        if vector.is_in_superposition():
            superposition = vector.get_superposition_modes()
            modes_str = ", ".join([f"{k} ({float(v):.0%})" for k, v in superposition.items()])
            parts.append(f"[SUPERPOSITION] Multiple modes active: {modes_str}")
        
        # Add student mind state
        mind_desc = {
            "confident": "feeling confident",
            "confused": "seeming confused",
            "frustrated": "appearing frustrated",
            "engaged": "highly engaged",
            "bored": "seeming bored",
            "curious": "curious and asking questions",
            "anxious": "seeming anxious",
            "motivated": "motivated and ready",
            "neutral": "in a neutral state",
        }
        
        mind_str = mind_desc.get(dominant_mind, f"in a {dominant_mind} state")
        parts.append(f"[STUDENT MIND] Student is {mind_str} (confidence: {float(mind_confidence):.0%}).")
        
        # Add topology
        topology_desc = {
            "opening": "just getting started",
            "deepening": "digging deeper into the topic",
            "closing": "wrapping up",
            "branching": "exploring a related idea",
            "merging": "connecting back to the main topic",
            "recovering": "recovering from an interruption",
        }
        
        topo_desc = topology_desc.get(vector.conversation_topology, "in conversation")
        parts.append(f"[CONVERSATION] Currently {topo_desc}.")
        
        # Add environmental context
        env = vector.env_context
        env_parts = []
        if env.get("time_of_day"):
            env_parts.append(f"time: {env['time_of_day']}")
        if env.get("network_quality") and env["network_quality"] != "unknown":
            env_parts.append(f"network: {env['network_quality']}")
        if env.get("session_age_minutes", 0) > 0:
            env_parts.append(f"session age: {env['session_age_minutes']}min")
        
        if env_parts:
            parts.append(f"[ENVIRONMENT] {', '.join(env_parts)}.")
        
        return " ".join(parts)
    
    async def reconstruct_from_history(
        self,
        student_id: str,
        message_history: List[Dict[str, Any]],
    ) -> StateVector:
        """
        Archaeological reconstruction using the State Archaeologist.
        Called after crashes or long gaps.
        """
        logger.info(f"Initiating archaeological reconstruction for {student_id}")
        
        try:
            from brain.state_archaeologist import get_archaeologist
            archaeologist = get_archaeologist()
            vector, confidence = await archaeologist.excavate(
                student_id=student_id,
                message_history=message_history,
                max_messages=30,
            )
            
            # If confidence is too low, fall back to default with recovery marker
            if confidence < Decimal("0.3"):
                logger.warning(f"Low reconstruction confidence ({float(confidence):.0%}) for {student_id}, using default")
                vector = StateVector.default()
                vector.conversation_topology = "recovering"
            
            # Persist reconstructed state
            self._local_cache[student_id] = vector
            await self._persist_vector(student_id, vector)
            await self._snapshot_to_supabase(student_id, vector)
            
            return vector
            
        except Exception as e:
            logger.error(f"Archaeologist failed for {student_id}: {e}")
            # Ultimate fallback
            vector = StateVector.default()
            vector.conversation_topology = "recovering"
            self._local_cache[student_id] = vector
            return vector
    
    async def _persist_vector(self, student_id: str, vector: StateVector) -> None:
        """Persist vector to Redis."""
        try:
            from database.client import redis_client
            key = f"state_cortex:vector:{student_id}"
            redis_client.setex(key, 1800, json.dumps(vector.to_dict()))  # 30 min TTL
        except Exception as e:
            logger.error(f"Redis persist failed for {student_id}: {e}")
    
    async def _snapshot_to_supabase(self, student_id: str, vector: StateVector) -> None:
        """Snapshot vector to Supabase for warm backup."""
        try:
            from database.client import supabase
            supabase.table("state_vectors").insert({
                "student_id": student_id,
                "vector_data": vector.to_dict(),
                "dominant_mode": vector.dominant_mode()[0],
                "dominant_mind": vector.dominant_mind_state()[0],
                "conversation_topology": vector.conversation_topology,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.error(f"Supabase snapshot failed for {student_id}: {e}")
    
    async def get_commitment_score(self, student_id: str) -> Decimal:
        """
        Return the student's engagement commitment score.
        Used by the Socket for natural account creation timing.
        """
        vector = await self.get_vector(student_id)
        mind = vector.current_effective_mind()
        
        # Commitment is a composite of engagement, confidence, and curiosity
        # minus frustration and boredom
        engagement = mind.get("engaged", Decimal("0"))
        confidence = mind.get("confident", Decimal("0"))
        curiosity = mind.get("curious", Decimal("0"))
        frustration = mind.get("frustrated", Decimal("0"))
        boredom = mind.get("bored", Decimal("0"))
        
        commitment = (engagement * Decimal("0.4") + 
                     confidence * Decimal("0.3") + 
                     curiosity * Decimal("0.3") -
                     frustration * Decimal("0.5") -
                     boredom * Decimal("0.5"))
        
        return max(Decimal("0"), min(Decimal("1"), commitment)).quantize(PRECISION)


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════

_state_cortex: Optional[StateCortex] = None

def get_state_cortex() -> StateCortex:
    """Get or create the singleton StateCortex instance."""
    global _state_cortex
    if _state_cortex is None:
        _state_cortex = StateCortex()
    return _state_cortex


# ═══════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _get_time_of_day() -> str:
    """Determine time of day in Nigeria (UTC+1)."""
    hour = (datetime.now(timezone.utc).hour + 1) % 24  # Nigeria is UTC+1
    
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"
