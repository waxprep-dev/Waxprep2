"""
brain/relational_intimacy.py — Wax Pedagogical Intimacy Gradient (PIG)

The Relational Intimacy Stack (RIS) engine.
Detects when a student has formed a bond with Wax — not just learned from Wax.

NO CORE FILE IMPORTS THIS DIRECTLY.
Only brain/state_socket.py and brain/student_mind_mirror.py interact with PIG.
"""

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("waxprep.relational_intimacy")

# ═══════════════════════════════════════════════════════════════════════
# TIER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

TIER_WEIGHTS = {
    1: Decimal("3.0"),   # Vulnerability
    2: Decimal("2.5"),   # Generative Agency
    3: Decimal("2.0"),   # Affective Bonding
    4: Decimal("1.0"),   # Cognitive Momentum
}

TIER_NAMES = {
    1: "vulnerability",
    2: "generative_agency",
    3: "affective_bonding",
    4: "cognitive_momentum",
}

HALF_LIFE_DAYS = 7
CLIFF_THRESHOLD = Decimal("8.0")
COOLING_OFF_DAYS = 14


# ═══════════════════════════════════════════════════════════════════════
# DETECTION PATTERNS
# ═══════════════════════════════════════════════════════════════════════

# Tier 1: Vulnerability Signals
VULNERABILITY_PATTERNS = {
    "confession": [
        "i don't get this at all", "i'm so bad at", "i failed this last term",
        "i'm scared for", "i'm terrible at", "i always fail", "i never understand",
        "this is my worst subject", "i hate this subject", "i'm not smart enough",
        "i no sabi am at all", "i dey fail am always", "this thing dey fear me",
        "i no get am", "e dey hard me well well", "my brain no dey catch am",
    ],
    "help_seeking_unspecific": [
        "i need help", "help me", "i'm stuck", "i don't know where to start",
        "i'm lost", "i don't understand anything", "everything is confusing",
        "abeg help me", "i dey stranded", "i no know where to start",
    ],
    "emotional_disclosure": [
        "this makes me anxious", "i'm worried about", "my teacher said i'll fail",
        "i don't want to disappoint", "my parents will be angry", "i'm stressed",
        "i'm nervous", "i'm under pressure", "everyone expects me to",
        "i dey fear", "my mama go beat me", "teacher say i go fail",
        "i dey under pressure", "everybody dey expect am from me",
    ],
    "persistent_struggle": [
        "i tried 5 times", "i keep getting it wrong", "every time i try",
        "i've been on this for", "i've been trying for",
        "i don try am many times", "e no gree enter", "every time i try am",
    ],
}

# Tier 2: Generative Agency Signals
GENERATIVE_PATTERNS = {
    "feynman_echo": [
        r"so basically", r"so in other words", r"so what you're saying is",
        r"so it's like", r"so this means", r"let me see if i understand",
        r"na so e be say", r"so e mean say", r"so the thing be say",
    ],
    "application_leap": [
        r"would this work for", r"can we use this for", r"does this apply to",
        r"what about", r"how about", r"can we try",
        r"e go work for", r"we fit use am for", r"wetin about",
    ],
    "critical_challenge": [
        r"but my teacher said", r"but the textbook says", r"that doesn't make sense",
        r"i don't agree", r"are you sure", r"but what if",
        r"but my teacher talk say", r"but textbook talk say", r"you sure",
        r"i no agree", r"wetin if", r"but wait",
    ],
    "teaching_intent": [
        r"explain this so i can tell", r"i need to teach this to",
        r"how would i explain this to", r"help me understand so i can",
        r"explain am make i tell", r"i wan teach am give",
        r"how i go explain am give",
    ],
}

# Tier 3: Affective Bonding Signals
AFFECTIVE_PATTERNS = {
    "gratitude_with_name": [
        r"thanks wax", r"thank you wax", r"thanks waxprep", r"thank you waxprep",
        r"na you biko", r"you try well well", r"you sabi this thing",
    ],
    "warmth_humor": [
        r"wax you too much", r"you sabi this thing o", r"wax you dey try",
        r"🔥", r"💯", r"🙏", r"😂", r"😄", r"😊",
        r"you bad", r"you too much", r"you be boss",
    ],
    "personal_address": [
        r"^wax", r"^hey wax", r"^hi wax", r"^hello wax",
        r"^wax ", r"^wax,", r"^wax!",
        r"are you a robot", r"are you human", r"who are you",
        r"wetin be your name", r"you be robot",
    ],
    "return_greeting": [
        r"^hey wax", r"^hi wax", r"^hello wax", r"^good morning wax",
        r"^good afternoon wax", r"^good evening wax",
        r"^wax good morning", r"^wax good afternoon", r"^wax good evening",
    ],
}

# Tier 4: Cognitive Momentum Signals
COGNITIVE_PATTERNS = {
    "explicit_understanding": [
        "i get it", "i understand", "that makes sense", "now i understand",
        "it makes sense now", "i see what you mean", "i see now",
        "e don enter", "i sabi am now", "e clear now", "i see wetin you mean",
    ],
    "correct_quiz_answer": [],  # Detected separately via quiz system
    "back_and_forth": [],  # Detected separately via exchange counting
}


# ═══════════════════════════════════════════════════════════════════════
# INTIMACY EVENT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class IntimacyEvent:
    """A single relational intimacy event."""
    tier: int
    event_type: str
    text_snippet: str
    topic: Optional[str]
    timestamp: datetime
    confidence: Decimal
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "event_type": self.event_type,
            "text_snippet": self.text_snippet[:100],
            "topic": self.topic,
            "timestamp": self.timestamp.isoformat(),
            "confidence": str(self.confidence),
        }


# ═══════════════════════════════════════════════════════════════════════
# RELATIONAL INTIMACY STACK
# ═══════════════════════════════════════════════════════════════════════

class RelationalIntimacyStack:
    """
    Tracks the student's relational bond with Wax.
    
    This is NOT engagement tracking. This is relationship tracking.
    A student can be highly engaged (many correct answers) with zero intimacy.
    A student can have low engagement but high intimacy (few messages, but vulnerable).
    """
    
    def __init__(self, student_id: str):
        self.student_id = student_id
        self.events: List[IntimacyEvent] = []
        self.half_life_days = HALF_LIFE_DAYS
        self.cliff_threshold = CLIFF_THRESHOLD
        self.cooling_off_days = COOLING_OFF_DAYS
        self.last_cliff_prompt: Optional[datetime] = None
        self.declined_cliff_count: int = 0
        self.account_created: bool = False
    
    def add_event(self, tier: int, event_type: str, text_snippet: str,
                  topic: Optional[str] = None, confidence: Decimal = Decimal("1.0")) -> None:
        """Add a new intimacy event."""
        if tier not in TIER_WEIGHTS:
            logger.warning(f"Invalid tier {tier} for {self.student_id}")
            return
        
        event = IntimacyEvent(
            tier=tier,
            event_type=event_type,
            text_snippet=text_snippet,
            topic=topic,
            timestamp=datetime.now(timezone.utc),
            confidence=confidence,
        )
        
        self.events.append(event)
        
        # Keep only last 50 events to prevent unbounded growth
        if len(self.events) > 50:
            self.events = self.events[-50:]
        
        logger.debug(
            f"PIG event for {self.student_id}: "
            f"tier={tier} ({TIER_NAMES[tier]}), "
            f"type={event_type}, "
            f"score={float(self._event_score(event)):.2f}"
        )
    
    def _event_score(self, event: IntimacyEvent) -> Decimal:
        """Calculate the score for a single event with time decay."""
        weight = TIER_WEIGHTS[event.tier]
        age_days = (datetime.now(timezone.utc) - event.timestamp).total_seconds() / 86400
        decay = Decimal("0.5") ** Decimal(str(age_days / self.half_life_days))
        return (weight * event.confidence * decay).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def current_score(self) -> Decimal:
        """Calculate the total intimacy score with time decay."""
        if not self.events:
            return Decimal("0")
        
        total = sum(self._event_score(e) for e in self.events)
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    def is_ready_for_cliff(self) -> bool:
        """
        Determine if the student is ready for the cliff-edge prompt.
        
        Rules:
        1. Score >= threshold
        2. At least one Tier 1 or Tier 2 event in last 10 interactions
        3. Not in cooling-off period
        4. Account not already created
        """
        if self.account_created:
            return False
        
        # Check cooling-off period
        if self.last_cliff_prompt:
            days_since = (datetime.now(timezone.utc) - self.last_cliff_prompt).total_seconds() / 86400
            if days_since < self.cooling_off_days:
                return False
        
        # Check score threshold
        score = self.current_score()
        if score < self.cliff_threshold:
            return False
        
        # Check depth gate: must have Tier 1 or Tier 2 in last 10 events
        recent_events = self.events[-10:]
        has_deep_event = any(e.tier <= 2 for e in recent_events)
        if not has_deep_event:
            return False
        
        return True
    
    def record_cliff_prompt(self, declined: bool = False) -> None:
        """Record that a cliff-edge prompt was shown."""
        self.last_cliff_prompt = datetime.now(timezone.utc)
        if declined:
            self.declined_cliff_count += 1
    
    def record_account_creation(self) -> None:
        """Record successful account creation."""
        self.account_created = True
    
    def get_recent_events_summary(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get summary of recent events for debugging."""
        return [e.to_dict() for e in self.events[-n:]]
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "student_id": self.student_id,
            "events": [e.to_dict() for e in self.events],
            "half_life_days": self.half_life_days,
            "cliff_threshold": str(self.cliff_threshold),
            "last_cliff_prompt": self.last_cliff_prompt.isoformat() if self.last_cliff_prompt else None,
            "declined_cliff_count": self.declined_cliff_count,
            "account_created": self.account_created,
            "current_score": str(self.current_score()),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RelationalIntimacyStack":
        """Deserialize from dictionary."""
        stack = cls(data.get("student_id", "unknown"))
        stack.half_life_days = data.get("half_life_days", HALF_LIFE_DAYS)
        stack.cliff_threshold = Decimal(str(data.get("cliff_threshold", CLIFF_THRESHOLD)))
        stack.declined_cliff_count = data.get("declined_cliff_count", 0)
        stack.account_created = data.get("account_created", False)
        
        if data.get("last_cliff_prompt"):
            try:
                stack.last_cliff_prompt = datetime.fromisoformat(data["last_cliff_prompt"].replace("Z", "+00:00"))
            except Exception:
                pass
        
        for e_data in data.get("events", []):
            try:
                event = IntimacyEvent(
                    tier=e_data["tier"],
                    event_type=e_data["event_type"],
                    text_snippet=e_data.get("text_snippet", ""),
                    topic=e_data.get("topic"),
                    timestamp=datetime.fromisoformat(e_data["timestamp"].replace("Z", "+00:00")),
                    confidence=Decimal(str(e_data.get("confidence", "1.0"))),
                )
                stack.events.append(event)
            except Exception:
                pass
        
        return stack


# ═══════════════════════════════════════════════════════════════════════
# DETECTION ENGINE
# ═══════════════════════════════════════════════════════════════════════

class IntimacyDetector:
    """
    Detects relational intimacy markers in messages.
    
    This is the pattern-matching layer that feeds events into the stack.
    """
    
    def __init__(self):
        self._compiled_patterns: Dict[str, re.Pattern] = {}
    
    def _compile(self, pattern: str) -> re.Pattern:
        """Compile and cache regex patterns."""
        if pattern not in self._compiled_patterns:
            self._compiled_patterns[pattern] = re.compile(pattern, re.IGNORECASE)
        return self._compiled_patterns[pattern]
    
    def detect(self, role: str, content: str, topic: Optional[str] = None) -> List[Tuple[int, str, str, Decimal]]:
        """
        Detect all intimacy markers in a message.
        
        Returns: List of (tier, event_type, matched_text, confidence)
        """
        if not content or not content.strip():
            return []
        
        content_lower = content.lower().strip()
        detected = []
        
        # Only detect from user messages (student's signals)
        if role != "user":
            return []
        
        # Tier 1: Vulnerability
        for event_type, patterns in VULNERABILITY_PATTERNS.items():
            for pattern in patterns:
                if pattern in content_lower:
                    detected.append((1, event_type, pattern, Decimal("0.9")))
                    break  # One match per event type
        
        # Tier 2: Generative Agency
        for event_type, patterns in GENERATIVE_PATTERNS.items():
            for pattern in patterns:
                regex = self._compile(pattern)
                if regex.search(content):
                    # Critical challenge gets higher confidence
                    conf = Decimal("0.95") if event_type == "critical_challenge" else Decimal("0.85")
                    detected.append((2, event_type, pattern, conf))
                    break
        
        # Tier 3: Affective Bonding
        for event_type, patterns in AFFECTIVE_PATTERNS.items():
            for pattern in patterns:
                regex = self._compile(pattern)
                if regex.search(content):
                    # Personal address gets higher confidence if at start of message
                    conf = Decimal("0.9")
                    if event_type == "personal_address" and content_lower.startswith("wax"):
                        conf = Decimal("0.95")
                    detected.append((3, event_type, pattern, conf))
                    break
        
        # Tier 4: Cognitive Momentum
        for event_type, patterns in COGNITIVE_PATTERNS.items():
            for pattern in patterns:
                if pattern in content_lower:
                    detected.append((4, event_type, pattern, Decimal("0.8")))
                    break
        
        return detected
    
    def detect_exchange_depth(self, history: List[Dict[str, Any]]) -> Optional[Tuple[int, str, str, Decimal]]:
        """
        Detect if this message represents deep back-and-forth on one topic.
        
        Returns Tier 4 event if 3+ exchanges on same topic.
        """
        if not history or len(history) < 6:
            return None
        
        # Count recent exchanges on same topic
        recent = history[-6:]
        topic_mentions = {}
        
        for msg in recent:
            content = msg.get("content", "").lower()
            # Simple topic extraction — can be enhanced
            for subject in ["physics", "chemistry", "biology", "mathematics", "math", "english", "government", "economics"]:
                if subject in content:
                    topic_mentions[subject] = topic_mentions.get(subject, 0) + 1
        
        # If 3+ messages mention same topic, it's a deep exchange
        for topic, count in topic_mentions.items():
            if count >= 3:
                return (4, "back_and_forth", f"3+ exchanges on {topic}", Decimal("0.7"))
        
        return None


# ═══════════════════════════════════════════════════════════════════════
# MANAGER (Persistence Layer)
# ═══════════════════════════════════════════════════════════════════════

class IntimacyManager:
    """
    Manages RelationalIntimacyStack persistence.
    
    Loads from Redis/Supabase, saves after updates.
    """
    
    def __init__(self):
        self._local_cache: Dict[str, RelationalIntimacyStack] = {}
    
    async def get_stack(self, student_id: str) -> RelationalIntimacyStack:
        """Load or create stack for a student."""
        if not student_id:
            return RelationalIntimacyStack("unknown")
        
        # Local cache
        if student_id in self._local_cache:
            return self._local_cache[student_id]
        
        # Try Redis
        try:
            from database.client import redis_client
            key = f"pig:stack:{student_id}"
            raw = redis_client.get(key)
            if raw:
                data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                stack = RelationalIntimacyStack.from_dict(data)
                self._local_cache[student_id] = stack
                return stack
        except Exception as e:
            logger.error(f"Redis PIG load failed for {student_id}: {e}")
        
        # Create new
        stack = RelationalIntimacyStack(student_id)
        self._local_cache[student_id] = stack
        return stack
    
    async def save_stack(self, student_id: str, stack: RelationalIntimacyStack) -> None:
        """Persist stack to Redis and Supabase."""
        self._local_cache[student_id] = stack
        
        # Redis
        try:
            from database.client import redis_client
            key = f"pig:stack:{student_id}"
            redis_client.setex(key, 86400 * 30, json.dumps(stack.to_dict()))  # 30 days
        except Exception as e:
            logger.error(f"Redis PIG save failed for {student_id}: {e}")
        
        # Supabase (async, fire-and-forget)
        try:
            from database.client import supabase
            supabase.table("relational_intimacy_stacks").upsert({
                "student_id": student_id,
                "stack_data": stack.to_dict(),
                "current_score": float(stack.current_score()),
                "ready_for_cliff": stack.is_ready_for_cliff(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="student_id").execute()
        except Exception as e:
            logger.error(f"Supabase PIG save failed for {student_id}: {e}")
    
    async def process_message(
        self,
        student_id: str,
        role: str,
        content: str,
        topic: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> RelationalIntimacyStack:
        """
        Process a message and update the intimacy stack.
        
        This is the main entry point called by the Mind Mirror.
        """
        stack = await self.get_stack(student_id)
        
        # Run detection
        detector = IntimacyDetector()
        detected = detector.detect(role, content, topic)
        
        # Add detected events
        for tier, event_type, text_snippet, confidence in detected:
            stack.add_event(tier, event_type, text_snippet, topic, confidence)
        
        # Check for exchange depth
        if history:
            depth_event = detector.detect_exchange_depth(history)
            if depth_event:
                tier, event_type, text_snippet, confidence = depth_event
                stack.add_event(tier, event_type, text_snippet, topic, confidence)
        
        # Save
        await self.save_stack(student_id, stack)
        
        return stack


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════

_manager: Optional[IntimacyManager] = None

def get_intimacy_manager() -> IntimacyManager:
    """Get or create the singleton IntimacyManager."""
    global _manager
    if _manager is None:
        _manager = IntimacyManager()
    return _manager


async def process_message_for_intimacy(
    student_id: str,
    role: str,
    content: str,
    topic: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> RelationalIntimacyStack:
    """
    Convenience function: process a message through PIG.
    
    Called by Mind Mirror after every message analysis.
    """
    manager = get_intimacy_manager()
    return await manager.process_message(student_id, role, content, topic, history)


async def should_trigger_cliff_edge(student_id: str) -> Tuple[bool, Decimal, Optional[str]]:
    """
    Check if cliff-edge prompt should fire for this student.
    
    Returns: (should_trigger, current_score, reason_if_not)
    """
    manager = get_intimacy_manager()
    stack = await manager.get_stack(student_id)
    
    score = stack.current_score()
    
    if stack.account_created:
        return (False, score, "Account already created")
    
    if stack.last_cliff_prompt:
        days_since = (datetime.now(timezone.utc) - stack.last_cliff_prompt).total_seconds() / 86400
        if days_since < COOLING_OFF_DAYS:
            return (False, score, f"In cooling-off period ({days_since:.1f} days since last prompt)")
    
    if score < CLIFF_THRESHOLD:
        return (False, score, f"Score {float(score):.1f} below threshold {float(CLIFF_THRESHOLD):.1f}")
    
    recent_events = stack.events[-10:]
    has_deep = any(e.tier <= 2 for e in recent_events)
    if not has_deep:
        return (False, score, "No Tier 1 or Tier 2 events in last 10 interactions")
    
    return (True, score, None)
