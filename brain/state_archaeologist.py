"""
brain/state_archaeologist.py — Wax State Archaeologist

Reconstructs 4D StateVectors from message history after crashes, long gaps,
or cold starts. This is the "resurrection" layer.

NO CORE FILE IMPORTS THIS DIRECTLY.
Only brain/state_cortex.py calls the Archaeologist.
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

from brain.state_cortex import StateVector

logger = logging.getLogger("waxprep.state_archaeologist")


class StateArchaeologist:
    """
    Excavates conversation history and reconstructs probable state.
    
    Think of it as forensic analysis: given textual artifacts (messages),
    what was the cognitive field at the time of interruption?
    """
    
    # Confidence thresholds for reconstruction quality
    CONFIDENCE_HIGH = Decimal("0.7")
    CONFIDENCE_MEDIUM = Decimal("0.5")
    CONFIDENCE_LOW = Decimal("0.3")
    
    def __init__(self):
        self._pattern_cache: Dict[str, re.Pattern] = {}
    
    def _compile(self, pattern: str) -> re.Pattern:
        """Compile and cache regex patterns."""
        if pattern not in self._pattern_cache:
            self._pattern_cache[pattern] = re.compile(pattern, re.IGNORECASE)
        return self._pattern_cache[pattern]
    
    async def excavate(
        self,
        student_id: str,
        message_history: List[Dict[str, Any]],
        max_messages: int = 30,
    ) -> Tuple[StateVector, Decimal]:
        """
        Reconstruct a StateVector from message history.
        
        Returns: (reconstructed_vector, confidence_score)
        """
        if not message_history:
            logger.info(f"Archaeologist: No history for {student_id}, returning default")
            return StateVector.default(), Decimal("0.1")
        
        # Sort by time, take last N
        sorted_history = sorted(
            message_history,
            key=lambda m: m.get("created_at", ""),
        )[-max_messages:]
        
        logger.info(f"Archaeologist excavating {len(sorted_history)} messages for {student_id}")
        
        # Run all inference engines
        wax_modes = self._infer_wax_modes(sorted_history)
        student_mind = self._infer_student_mind(sorted_history)
        topology = self._infer_topology(sorted_history)
        env_context = self._infer_environment(sorted_history)
        
        # Calculate confidence based on data richness
        confidence = self._calculate_confidence(sorted_history, wax_modes, student_mind)
        
        # Build the reconstructed vector
        vector = StateVector(
            wax_mode=wax_modes,
            student_mind=student_mind,
            conversation_topology=topology,
            env_context=env_context,
            created_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
        )
        
        logger.info(
            f"Archaeologist reconstruction for {student_id}: "
            f"mode={vector.dominant_mode()[0]}, "
            f"mind={vector.dominant_mind_state()[0]}, "
            f"topology={topology}, "
            f"confidence={float(confidence):.0%}"
        )
        
        return vector, confidence
    
    def _infer_wax_modes(self, history: List[Dict[str, Any]]) -> Dict[str, Decimal]:
        """Infer wax mode probabilities from message patterns."""
        scores: Dict[str, Decimal] = {
            "idle": Decimal("0.1"),
            "chatting": Decimal("0.1"),
            "teaching": Decimal("0.1"),
            "in_quiz": Decimal("0.1"),
            "awaiting_response": Decimal("0.1"),
            "in_emotional_support": Decimal("0.1"),
            "onboarding": Decimal("0.1"),
            "paused": Decimal("0.1"),
            "ended": Decimal("0.1"),
        }
        
        # Weight recent messages more heavily
        total_weight = Decimal("0")
        
        for i, msg in enumerate(history):
            weight = Decimal(str((i + 1) / len(history)))  # 0.03 to 1.0
            role = msg.get("role", "")
            content = msg.get("content", "")
            content_lower = content.lower()
            
            if role == "assistant":
                # Quiz indicators
                if any(p in content_lower for p in [
                    "quiz", "question", "options", "a)", "b)", "c)", "d)",
                    "correct answer", "your answer", "tap your answer",
                ]):
                    scores["in_quiz"] += weight * Decimal("0.8")
                
                # Teaching indicators
                if any(p in content_lower for p in [
                    "let me explain", "think of it this way", "imagine",
                    "the idea is", "this means", "in other words",
                    "for example", "let's break it down",
                ]):
                    scores["teaching"] += weight * Decimal("0.6")
                
                # Emotional support indicators
                if any(p in content_lower for p in [
                    "i hear you", "that must be hard", "don't worry",
                    "you're doing great", "take a breath", "it's okay",
                    "i understand", "that sounds tough",
                ]):
                    scores["in_emotional_support"] += weight * Decimal("0.7")
                
                # Awaiting response indicators
                if content.strip().endswith("?"):
                    scores["awaiting_response"] += weight * Decimal("0.5")
                
                # Onboarding indicators
                if any(p in content_lower for p in [
                    "welcome to wax", "let's get you set up", "what's your name",
                    "what class are you", "what subjects", "create your account",
                ]):
                    scores["onboarding"] += weight * Decimal("0.9")
                
                # Session end indicators
                if any(p in content_lower for p in [
                    "take a break", "see you later", "good night", "goodbye",
                    "no wahala", "rest well", "come back when",
                ]):
                    scores["ended"] += weight * Decimal("0.8")
            
            elif role == "user":
                # Quiz engagement
                if any(p in content_lower for p in ["a", "b", "c", "d"]):
                    if len(content.strip()) <= 2:
                        scores["in_quiz"] += weight * Decimal("0.4")
                
                # Emotional signals
                if any(p in content_lower for p in [
                    "stressed", "worried", "scared", "tired", "overwhelmed",
                    "i can't do this", "i'm failing", "i'm not good enough",
                ]):
                    scores["in_emotional_support"] += weight * Decimal("0.5")
                
                # Continuation signals
                if any(p in content_lower for p in ["continue", "next", "more", "go on"]):
                    scores["chatting"] += weight * Decimal("0.3")
            
            total_weight += weight
        
        # Normalize
        if total_weight > 0:
            for mode in scores:
                scores[mode] = scores[mode] / total_weight
        
        # If no strong signal, default to chatting
        max_score = max(scores.values())
        if max_score < Decimal("0.2"):
            scores["chatting"] = Decimal("0.5")
        
        return StateVector._normalize(scores)
    
    def _infer_student_mind(self, history: List[Dict[str, Any]]) -> Dict[str, Decimal]:
        """Infer student cognitive/affective state from messages."""
        scores: Dict[str, Decimal] = {
            "neutral": Decimal("0.1"),
            "confident": Decimal("0.1"),
            "confused": Decimal("0.1"),
            "frustrated": Decimal("0.1"),
            "engaged": Decimal("0.1"),
            "bored": Decimal("0.1"),
            "curious": Decimal("0.1"),
            "anxious": Decimal("0.1"),
            "motivated": Decimal("0.1"),
        }
        
        total_weight = Decimal("0")
        
        for i, msg in enumerate(history):
            weight = Decimal(str((i + 1) / len(history)))
            role = msg.get("role", "")
            content = msg.get("content", "").lower()
            
            if role != "user":
                continue
            
            # Confusion signals
            confusion = [
                "don't understand", "confused", "stuck", "lost", "don't get",
                "huh", "wait", "what do you mean", "i don't see", "how come",
                "i'm lost", "this doesn't make sense", "explain again",
            ]
            if any(p in content for p in confusion):
                scores["confused"] += weight * Decimal("0.8")
            
            # Frustration signals
            frustration = [
                "this is hard", "i give up", "too difficult", "impossible",
                "i can't", "annoying", "stupid", "waste of time", "not working",
                "i'm done", "forget it", "this is useless",
            ]
            if any(p in content for p in frustration):
                scores["frustrated"] += weight * Decimal("0.9")
            
            # Engagement signals
            engagement = [
                "i get it", "that makes sense", "cool", "awesome", "interesting",
                "tell me more", "wow", "really", "nice one", "sharp",
                "e don enter", "i sabi am", "na so e be",
            ]
            if any(p in content for p in engagement):
                scores["engaged"] += weight * Decimal("0.7")
            
            # Curiosity signals
            curiosity = [
                "what if", "why", "how come", "what about", "can you explain",
                "what happens when", "i wonder", "is it true that",
            ]
            if any(p in content for p in curiosity):
                scores["curious"] += weight * Decimal("0.6")
            
            # Confidence signals
            confidence = [
                "i know", "easy", "simple", "i can do this", "got it",
                "no problem", "i understand", "makes sense", "clear",
            ]
            if any(p in content for p in confidence):
                scores["confident"] += weight * Decimal("0.6")
            
            # Boredom signals
            boredom = [
                "ok", "yeah", "sure", "whatever", "fine", "k",
                "same thing", "boring", "not interested", "next",
            ]
            if len(content) < 5 and any(p in content for p in boredom):
                scores["bored"] += weight * Decimal("0.7")
            
            # Anxiety signals
            anxiety = [
                "nervous", "worried", "scared", "what if i fail", "exam",
                "jamb", "waec", "neco", "i'm not ready", "i'll fail",
            ]
            if any(p in content for p in anxiety):
                scores["anxious"] += weight * Decimal("0.7")
            
            # Motivation signals
            motivation = [
                "let's do this", "i'm ready", "bring it on", "i want to learn",
                "help me", "teach me", "i need to know", "i must pass",
            ]
            if any(p in content for p in motivation):
                scores["motivated"] += weight * Decimal("0.6")
            
            total_weight += weight
        
        # Normalize
        if total_weight > 0:
            for state in scores:
                scores[state] = scores[state] / total_weight
        
        return StateVector._normalize(scores)
    
    def _infer_topology(self, history: List[Dict[str, Any]]) -> str:
        """Infer conversation topology from message flow."""
        if not history:
            return "opening"
        
        last_msg = history[-1]
        last_role = last_msg.get("role", "")
        last_content = last_msg.get("content", "").lower()
        
        # Check for explicit closing
        if last_role == "user" and any(p in last_content for p in [
            "bye", "good night", "goodnight", "i'm done", "later",
            "see you", "i dey go", "make i rest",
        ]):
            return "closing"
        
        # Check if assistant asked a question and student hasn't answered
        if len(history) >= 2:
            second_last = history[-2]
            if (second_last.get("role") == "assistant" and 
                second_last.get("content", "").strip().endswith("?") and
                last_role == "assistant"):
                # Student didn't answer, assistant sent another message
                return "recovering"
        
        # Check message count for depth
        user_msgs = [m for m in history if m.get("role") == "user"]
        if len(user_msgs) <= 2:
            return "opening"
        elif len(user_msgs) <= 5:
            return "deepening"
        else:
            # Check if topic shifted
            first_subject = self._extract_subject(history[0].get("content", ""))
            last_subject = self._extract_subject(last_content)
            if first_subject and last_subject and first_subject != last_subject:
                return "branching"
            return "deepening"
    
    def _infer_environment(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Infer environmental context from message timestamps and patterns."""
        env = {
            "time_of_day": self._get_time_of_day(),
            "network_quality": "unknown",
            "session_age_minutes": 0,
            "data_bundle_likely_active": True,
            "device_type": "unknown",
            "interrupted": False,
        }
        
        if not history:
            return env
        
        # Calculate session age
        try:
            first_time = datetime.fromisoformat(history[0].get("created_at", "").replace("Z", "+00:00"))
            last_time = datetime.fromisoformat(history[-1].get("created_at", "").replace("Z", "+00:00"))
            env["session_age_minutes"] = int((last_time - first_time).total_seconds() / 60)
        except Exception:
            pass
        
        # Detect network quality from message patterns
        short_msgs = sum(1 for m in history if len(m.get("content", "")) < 10)
        if len(history) > 0 and short_msgs / len(history) > 0.5:
            env["network_quality"] = "poor"  # Many short messages = bad network
        
        # Detect interruption (long gap in messages)
        if len(history) >= 2:
            gaps = []
            for i in range(1, len(history)):
                try:
                    t1 = datetime.fromisoformat(history[i-1].get("created_at", "").replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(history[i].get("created_at", "").replace("Z", "+00:00"))
                    gaps.append((t2 - t1).total_seconds())
                except Exception:
                    pass
            
            if gaps and max(gaps) > 300:  # 5+ minute gap
                env["interrupted"] = True
        
        return env
    
    def _calculate_confidence(
        self,
        history: List[Dict[str, Any]],
        wax_modes: Dict[str, Decimal],
        student_mind: Dict[str, Decimal],
    ) -> Decimal:
        """Calculate confidence score for the reconstruction."""
        confidence = Decimal("0.5")  # Base confidence
        
        # More messages = higher confidence
        msg_count = len(history)
        if msg_count >= 20:
            confidence += Decimal("0.2")
        elif msg_count >= 10:
            confidence += Decimal("0.1")
        
        # Clear dominant mode = higher confidence
        max_mode = max(wax_modes.values())
        if max_mode >= Decimal("0.5"):
            confidence += Decimal("0.15")
        elif max_mode >= Decimal("0.3"):
            confidence += Decimal("0.05")
        
        # Clear dominant mind = higher confidence
        max_mind = max(student_mind.values())
        if max_mind >= Decimal("0.5"):
            confidence += Decimal("0.1")
        
        # Recent activity = higher confidence
        if history:
            try:
                last_time = datetime.fromisoformat(history[-1].get("created_at", "").replace("Z", "+00:00"))
                hours_since = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600
                if hours_since < 1:
                    confidence += Decimal("0.05")
                elif hours_since > 24:
                    confidence -= Decimal("0.1")
            except Exception:
                pass
        
        return max(Decimal("0.1"), min(Decimal("0.95"), confidence))
    
    def _extract_subject(self, content: str) -> Optional[str]:
        """Extract subject mention from message content."""
        if not content:
            return None
        
        content_lower = content.lower()
        subjects = [
            "mathematics", "math", "english", "physics", "chemistry",
            "biology", "government", "economics", "commerce", "accounting",
            "literature", "crs", "irs", "geography", "history",
        ]
        
        for subject in subjects:
            if subject in content_lower:
                return subject
        return None
    
    def _get_time_of_day(self) -> str:
        """Determine current time of day in Nigeria (UTC+1)."""
        hour = (datetime.now(timezone.utc).hour + 1) % 24
        
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════

_archaeologist: Optional[StateArchaeologist] = None

def get_archaeologist() -> StateArchaeologist:
    """Get or create the singleton Archaeologist."""
    global _archaeologist
    if _archaeologist is None:
        _archaeologist = StateArchaeologist()
    return _archaeologist
