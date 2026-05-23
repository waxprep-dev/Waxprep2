"""
brain/student_mind_mirror.py — Wax Student Mind Mirror

Real-time cognitive and affective state modeling.
Updates the State Cortex with inferred student mental states after every message.

NO CORE FILE IMPORTS THIS DIRECTLY.
Only brain/state_cortex.py calls the Mind Mirror via record_message().
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("waxprep.student_mind_mirror")


class StudentMindMirror:
    """
    Models the student's internal cognitive and affective state.
    
    Think of this as Wax's "theory of mind" — what does Wax believe
    the student is thinking, feeling, and capable of right now?
    """
    
    # Emotional signal patterns (English + Pidgin + Nigerian context)
    EMOTION_SIGNALS = {
        "frustration": [
            "this is hard", "i give up", "too difficult", "impossible",
            "i can't", "annoying", "stupid", "waste of time", "not working",
            "i'm done", "forget it", "this is useless", "i don tire",
            "e no dey work", "this thing hard", "my head dey pain me",
            "i no understand", "e dey annoy me", "i wan give up",
        ],
        "confusion": [
            "don't understand", "confused", "stuck", "lost", "don't get",
            "huh", "wait", "what do you mean", "i don't see", "how come",
            "i'm lost", "this doesn't make sense", "explain again",
            "i no get am", "e dey confuse me", "wetin you mean",
            "i dey lost", "e no clear", "abeg explain",
        ],
        "engagement": [
            "i get it", "that makes sense", "cool", "awesome", "interesting",
            "tell me more", "wow", "really", "nice one", "sharp",
            "e don enter", "i sabi am", "na so e be", "correct",
            "i dey feel am", "e sweet me", "i like am", "more",
        ],
        "curiosity": [
            "what if", "why", "how come", "what about", "can you explain",
            "what happens when", "i wonder", "is it true that",
            "how e go be if", "wetin go happen", "why e be say",
            "tell me about", "i wan know", "i dey wonder",
        ],
        "confidence": [
            "i know", "easy", "simple", "i can do this", "got it",
            "no problem", "i understand", "makes sense", "clear",
            "i sabi am well well", "e easy", "no wahala", "i get am",
        ],
        "boredom": [
            "ok", "yeah", "sure", "whatever", "fine", "k",
            "same thing", "boring", "not interested", "next",
            "hmmm", "okay", "na so", "ehen", "make we move",
        ],
        "anxiety": [
            "nervous", "worried", "scared", "what if i fail", "exam",
            "jamb", "waec", "neco", "i'm not ready", "i'll fail",
            "i no go pass", "exam dey fear me", "i dey shake",
            "my mama go beat me", "i no wan fail", "pressure",
        ],
        "motivation": [
            "let's do this", "i'm ready", "bring it on", "i want to learn",
            "help me", "teach me", "i need to know", "i must pass",
            "i go pass", "nothing go stop me", "i dey ready", "make we go",
        ],
        "gratitude": [
            "thank you", "thanks", "appreciate", "you're the best",
            "god bless you", "you too much", "you sabi this thing",
            "na you biko", "i dey grateful", "you try",
        ],
    }
    
    # Learning Learning signal patterns
    LEARNING_SIGNALS = {
        "breakthrough": [
            "oh i see", "now i understand", "it makes sense now",
            "i get am now", "e don clear", "na im be that",
            "ahhh", "ooooh", "i see wetin you mean",
        ],
        "prerequisite_gap": [
            "i never do this before", "we no do am for class",
            "my teacher no teach us", "this one new",
            "i no sabi the basics", "from where we dey start",
        ],
        "careless_error": [
            "i forget", "i no see am", "small mistake", "i rush am",
            "my hand slip", "i no read am well", "i dey hurry",
        ],
        "deep_thinking": [
            "let me think", "give me time", "i dey think", "make i reason am",
            "hmmm", "wait make i see", "i need to understand",
        ],
    }
    
    def __init__(self):
        self._pattern_cache: Dict[str, re.Pattern] = {}
    
    def _compile(self, pattern: str) -> re.Pattern:
        """Compile and cache regex patterns."""
        if pattern not in self._pattern_cache:
            self._pattern_cache[pattern] = re.compile(
                r'\b' + re.escape(pattern.lower()) + r'\b',
                re.IGNORECASE
            )
        return self._pattern_cache[pattern]
    
    async def analyze_message(
        self,
        student_id: str,
        role: str,
        content: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a single message and return mind state updates.
        
        Returns: {
            "mind_updates": {"frustrated": 0.7, "engaged": 0.3},
            "learning_signals": {"breakthrough": True, "prerequisite_gap": False},
            "engagement_metrics": {"message_length": 45, "response_time_sec": 12},
            "commitment_delta": 0.05,
        }
        """
        if not content or not content.strip():
            return {
                "mind_updates": {},
                "learning_signals": {},
                "engagement_metrics": {},
                "commitment_delta": Decimal("0"),
            }
        
        content_lower = content.lower().strip()
        
        # Run all detection engines
        emotions = self._detect_emotions(content_lower)
        learning = self._detect_learning_signals(content_lower)
        engagement = self._calculate_engagement(content, conversation_history)
        commitment = self._calculate_commitment_delta(emotions, learning, engagement, role)
        
        # Convert emotions to mind_updates format for Cortex
        mind_updates = {}
        for emotion, detected in emotions.items():
            if detected:
                # Map emotions to mind states
                mind_map = {
                    "frustration": "frustrated",
                    "confusion": "confused",
                    "engagement": "engaged",
                    "curiosity": "curious",
                    "confidence": "confident",
                    "boredom": "bored",
                    "anxiety": "anxious",
                    "motivation": "motivated",
                    "gratitude": "engaged",  # Gratitude = engagement signal
                }
                mind_state = mind_map.get(emotion)
                if mind_state:
                    mind_updates[mind_state] = Decimal("0.7")
        
        result = {
            "mind_updates": mind_updates,
            "learning_signals": learning,
            "engagement_metrics": engagement,
            "commitment_delta": commitment,
        }
        
        logger.debug(
            f"MindMirror analysis for {student_id}: "
            f"emotions={list(emotions.keys())}, "
            f"learning={list(learning.keys())}, "
            f"commitment_delta={float(commitment):+.3f}"
        )
        
        return result
    
    def _detect_emotions(self, content: str) -> Dict[str, bool]:
        """Detect emotional signals in message content."""
        detected = {}
        
        for emotion, patterns in self.EMOTION_SIGNALS.items():
            found = any(
                self._compile(pattern).search(content) or pattern in content
                for pattern in patterns
            )
            detected[emotion] = found
        
        return detected
    
    def _detect_learning_signals(self, content: str) -> Dict[str, bool]:
        """Detect learning process signals."""
        detected = {}
        
        for signal, patterns in self.LEARNING_SIGNALS.items():
            found = any(pattern in content for pattern in patterns)
            detected[signal] = found
        
        return detected
    
    def _calculate_engagement(
        self,
        content: str,
        history: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Calculate engagement metrics from message and history."""
        metrics = {
            "message_length": len(content),
            "word_count": len(content.split()),
            "question_count": content.count("?"),
            "exclamation_count": content.count("!"),
            "has_emoji": bool(re.search(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]', content)),
            "has_pidgin": self._detect_pidgin(content),
            "response_time_sec": None,
        }
        
        # Calculate response time if history available
        if history and len(history) >= 2:
            last_assistant = None
            for msg in reversed(history[:-1]):
                if msg.get("role") == "assistant":
                    last_assistant = msg
                    break
            
            if last_assistant:
                try:
                    assistant_time = datetime.fromisoformat(
                        last_assistant.get("created_at", "").replace("Z", "+00:00")
                    )
                    current_time = datetime.now(timezone.utc)
                    response_time = (current_time - assistant_time).total_seconds()
                    metrics["response_time_sec"] = min(response_time, 3600)  # Cap at 1 hour
                except Exception:
                    pass
        
        return metrics
    
    def _detect_pidgin(self, content: str) -> bool:
        """Detect Nigerian Pidgin usage."""
        pidgin_markers = [
            "dey", "na", "wahala", "abeg", "omo", "sha", "nna", "abi",
            "wetin", "go", "come", "chop", "oya", "make", "e be", "wey",
            "sabi", "don", "no go", "no fit", "dey there", "how far",
            "i dey", "you dey", "e don", "na im", "no wahala",
        ]
        content_lower = content.lower()
        return any(marker in content_lower for marker in pidgin_markers)
    
    def _calculate_commitment_delta(
        self,
        emotions: Dict[str, bool],
        learning: Dict[str, bool],
        engagement: Dict[str, Any],
        role: str,
    ) -> Decimal:
        """
        Calculate how this message changes the student's commitment score.
        
        Commitment = likelihood the student will create an account.
        Positive = more likely. Negative = less likely.
        """
        if role != "user":
            return Decimal("0")
        
        delta = Decimal("0")
        
        # Positive signals
        if emotions.get("engagement"):
            delta += Decimal("0.05")
        if emotions.get("curiosity"):
            delta += Decimal("0.04")
        if emotions.get("motivation"):
            delta += Decimal("0.06")
        if emotions.get("gratitude"):
            delta += Decimal("0.03")
        if learning.get("breakthrough"):
            delta += Decimal("0.08")  # Biggest positive — they felt value
        if learning.get("deep_thinking"):
            delta += Decimal("0.03")
        
        # Negative signals
        if emotions.get("frustration"):
            delta -= Decimal("0.06")
        if emotions.get("confusion") and not emotions.get("engagement"):
            delta -= Decimal("0.03")  # Confused but not engaging = bad
        if emotions.get("boredom"):
            delta -= Decimal("0.05")
        if emotions.get("anxiety"):
            delta -= Decimal("0.02")  # Anxiety is complex — might still convert
        
        # Engagement metrics
        msg_len = engagement.get("message_length", 0)
        if msg_len > 100:
            delta += Decimal("0.02")  # Long message = investment
        elif msg_len < 10:
            delta -= Decimal("0.02")  # Very short = disengagement
        
        questions = engagement.get("question_count", 0)
        if questions > 0:
            delta += Decimal("0.02") * questions  # Asking questions = engagement
        
        response_time = engagement.get("response_time_sec")
        if response_time:
            if response_time < 30:
                delta += Decimal("0.02")  # Fast response = engaged
            elif response_time > 300:
                delta -= Decimal("0.02")  # Slow = maybe distracted
        
        # Clamp to reasonable range
        return max(Decimal("-0.2"), min(Decimal("0.2"), delta))
    
    async def get_longitudinal_profile(
        self,
        student_id: str,
        session_history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build a longitudinal learning profile from session history.
        
        This is used for adaptive difficulty and personalized teaching.
        """
        if not session_history:
            return {
                "learning_velocity": 0,  # concepts per session
                "average_engagement": 0.5,
                "frustration_rate": 0,
                "breakthrough_rate": 0,
                "preferred_time_of_day": "unknown",
                "attention_span_minutes": 15,
                "response_pattern": "unknown",
            }
        
        total_sessions = len(session_history)
        concepts_mastered = sum(s.get("concepts_mastered", 0) for s in session_history)
        concepts_struggled = sum(s.get("concepts_struggled", 0) for s in session_history)
        
        # Calculate velocity
        velocity = concepts_mastered / max(total_sessions, 1)
        
        # Calculate engagement average
        engagement_scores = [
            s.get("engagement_score", 0.5) for s in session_history if "engagement_score" in s
        ]
        avg_engagement = sum(engagement_scores) / max(len(engagement_scores), 1)
        
        # Calculate frustration rate
        frustration_count = sum(
            1 for s in session_history if s.get("emotional_arc", "").startswith("frustrated")
        )
        frustration_rate = frustration_count / max(total_sessions, 1)
        
        # Calculate breakthrough rate
        breakthrough_count = sum(
            1 for s in session_history if any(
                "breakthrough" in str(v).lower() for v in s.get("victories", [])
            )
        )
        breakthrough_rate = breakthrough_count / max(total_sessions, 1)
        
        # Detect preferred time
        hours = []
        for s in session_history:
            try:
                started = datetime.fromisoformat(s.get("started_at", "").replace("Z", "+00:00"))
                hours.append(started.hour)
            except Exception:
                pass
        
        preferred_time = "unknown"
        if hours:
            avg_hour = sum(hours) / len(hours)
            if 5 <= avg_hour < 12:
                preferred_time = "morning"
            elif 12 <= avg_hour < 17:
                preferred_time = "afternoon"
            elif 17 <= avg_hour < 21:
                preferred_time = "evening"
            else:
                preferred_time = "night"
        
        # Estimate attention span
        durations = [s.get("duration_minutes", 15) for s in session_history if s.get("duration_minutes")]
        attention_span = sum(durations) / max(len(durations), 1) if durations else 15
        
        # Detect response pattern
        response_times = []
        for s in session_history:
            rt = s.get("average_response_time_sec")
            if rt:
                response_times.append(rt)
        
        response_pattern = "unknown"
        if response_times:
            avg_rt = sum(response_times) / len(response_times)
            if avg_rt < 30:
                response_pattern = "fast_responder"
            elif avg_rt < 120:
                response_pattern = "thoughtful"
            else:
                response_pattern = "slow_responder"
        
        return {
            "learning_velocity": round(velocity, 2),
            "average_engagement": round(avg_engagement, 2),
            "frustration_rate": round(frustration_rate, 2),
            "breakthrough_rate": round(breakthrough_rate, 2),
            "preferred_time_of_day": preferred_time,
            "attention_span_minutes": round(attention_span),
            "response_pattern": response_pattern,
            "total_sessions": total_sessions,
            "concepts_mastered": concepts_mastered,
            "concepts_struggled": concepts_struggled,
        }


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════

_mind_mirror: Optional[StudentMindMirror] = None

def get_mind_mirror() -> StudentMindMirror:
    """Get or create the singleton StudentMindMirror."""
    global _mind_mirror
    if _mind_mirror is None:
        _mind_mirror = StudentMindMirror()
    return _mind_mirror
