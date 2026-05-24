"""
brain/swarm_matcher.py — Swarm Matcher (S3)

Matches struggling students to proven insights from the swarm.

The Matcher answers: "Which student needs THIS insight, right now?"

Pipeline:
1. Detect Struggling Students — Find students stuck on the same concept
2. Fetch Recent Insights — Get swarm insights for this concept
3. Score Compatibility — Match struggle pattern, profile, bio-state
4. Select Best Match — Pick the highest-scoring insight per student
5. Build Delivery Package — Format for Zero-Knowledge Relay

Connections:
- swarm_insights table (insight capsules)
- students table (profiles, regions, class levels)
- Working Memory (current concept, confusion level)
- Circadian Profiles (bio-state, engagement windows)
- PIG Engine (intimacy score for matching weight)

Output: List of match recommendations ready for S4 (Zero-Knowledge Relay)

CHANGELOG:
- 2026-05-25: Created for Ubuntu Swarm Mind P2-A
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.swarm_matcher")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Struggle detection thresholds
STRUGGLE_CONFUSION_THRESHOLD = 0.6  # Confusion level ≥ 0.6
STRUGGLE_FAILURE_THRESHOLD = 2  # 2+ consecutive failures
MIN_TIME_SINCE_LAST_INSIGHT_HOURS = 2  # Don't flood

# Compatibility scoring weights
WEIGHT_STRUGGLE_PATTERN = 0.30  # Same type of struggle
WEIGHT_CLASS_LEVEL = 0.20  # Same class/year
WEIGHT_REGION = 0.15  # Same Nigerian zone
WEIGHT_BIO_STATE = 0.15  # Compatible bio-state
WEIGHT_LANGUAGE = 0.10  # Language register match
WEIGHT_SCHOOL_TYPE = 0.10  # Public/private/unity

# Matching constraints
MAX_MATCHES_PER_INSIGHT = 10  # Don't overshare one insight
MAX_INSIGHTS_PER_STUDENT_DAY = 5  # Anti-flood
MAX_INSIGHTS_PER_STUDENT_HOUR = 2  # Anti-flood

# Redis keys
MATCHED_INSIGHTS_KEY = "swarm:matched:{student_id}"
STUDENT_STRUGGLE_KEY = "swarm:struggle:{student_id}"

# ═══════════════════════════════════════════════════════════════════════
# MAIN MATCHER
# ═══════════════════════════════════════════════════════════════════════

class SwarmMatcher:
    """
    Matches struggling students to proven insights.

    Usage:
        matcher = SwarmMatcher()
        matches = await matcher.find_matches_for_insight(insight_capsule)
        for match in matches:
            # Send to Zero-Knowledge Relay
            pass
    """

    def __init__(self):
        pass

    async def find_matches_for_insight(
        self,
        insight_capsule: Dict[str, Any],
        max_matches: int = MAX_MATCHES_PER_INSIGHT,
    ) -> List[Dict[str, Any]]:
        """
        Find the best struggling students for a given insight.

        Args:
            insight_capsule: The insight to match (from S2)
            max_matches: Maximum students to match

        Returns:
            List of match dicts with student_id, compatibility_score, delivery_config
        """
        concept_id = insight_capsule.get("concept_id")
        if not concept_id or concept_id == "unknown":
            logger.warning("Cannot match insight without concept_id")
            return []

        # 1. Find struggling students on this concept
        struggling_students = await self._find_struggling_students(concept_id)
        if not struggling_students:
            logger.info(f"No struggling students found for concept: {concept_id}")
            return []

        # 2. Score compatibility for each student
        scored_matches = []
        for student in struggling_students:
            score = await self._score_compatibility(student, insight_capsule)
            if score > 0.5:  # Minimum viable match
                scored_matches.append({
                    "student": student,
                    "compatibility_score": score,
                })

        # 3. Sort by score, take top N
        scored_matches.sort(key=lambda x: x["compatibility_score"], reverse=True)
        top_matches = scored_matches[:max_matches]

        # 4. Build delivery packages
        deliveries = []
        for match in top_matches:
            delivery = await self._build_delivery_package(
                match["student"],
                insight_capsule,
                match["compatibility_score"],
            )
            if delivery:
                deliveries.append(delivery)

        logger.info(f"Swarm Matcher: {len(deliveries)} matches for insight "
                   f"{insight_capsule.get('insight_id', 'unknown')[:8]}...")
        return deliveries

    async def find_insights_for_student(
        self,
        student_id: str,
        current_concept: Optional[str] = None,
        max_insights: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find the best insights for a struggling student.
        Called by cron job for proactive delivery.
        """
        # Get student's current struggle context
        struggle_context = await self._get_student_struggle_context(student_id)
        if not struggle_context:
            return []

        concept = current_concept or struggle_context.get("concept_id")
        if not concept:
            return []

        # Fetch swarm insights for this concept
        insights = await self._fetch_swarm_insights(concept)
        if not insights:
            return []

        # Score each insight for this student
        scored = []
        for insight in insights:
            score = await self._score_compatibility_for_insight(
                student_id, struggle_context, insight
            )
            if score > 0.5:
                scored.append({
                    "insight": insight,
                    "score": score,
                })

        # Sort, take top N, check frequency limits
        scored.sort(key=lambda x: x["score"], reverse=True)
        filtered = await self._apply_frequency_limits(student_id, scored)
        return filtered[:max_insights]

    # ═════════════════════════════════════════════════════════════════
    # 1. STRUGGLING STUDENT DETECTION
    # ═════════════════════════════════════════════════════════════════

    async def _find_struggling_students(self, concept_id: str) -> List[Dict[str, Any]]:
        """
        Find students currently struggling with a concept.
        Uses multiple signals from Working Memory and conversations.
        """
        students = []

        # Method 1: Working Memory snapshots with high confusion
        try:
            result = (
                supabase.table("working_memory_snapshots")
                .select("student_id, snapshot")
                .eq("snapshot->>current_concept", concept_id)
                .gte("snapshot->>confusion_level", str(STRUGGLE_CONFUSION_THRESHOLD))
                .limit(50)
                .execute()
            )
            for row in result.data or []:
                snapshot = row.get("snapshot", {})
                students.append({
                    "student_id": row["student_id"],
                    "confusion_level": float(snapshot.get("confusion_level", 0.0)),
                    "concept_id": concept_id,
                    "source": "working_memory",
                })
        except Exception as e:
            logger.warning(f"Working Memory struggle query failed: {e}")

        # Method 2: Recent conversations with struggle markers
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            result = (
                supabase.table("conversations")
                .select("student_id, content, message_metadata")
                .gte("created_at", cutoff.isoformat())
                .execute()
            )
            for row in result.data or []:
                metadata = row.get("message_metadata", {}) or {}
                # Check if this message shows struggle on our concept
                if metadata.get("current_concept") == concept_id:
                    if metadata.get("confusion_level", 0) >= STRUGGLE_CONFUSION_THRESHOLD:
                        students.append({
                            "student_id": row["student_id"],
                            "confusion_level": metadata.get("confusion_level", 0.0),
                            "concept_id": concept_id,
                            "source": "conversation",
                        })
        except Exception as e:
            logger.warning(f"Conversation struggle query failed: {e}")

        # Method 3: Redis struggle tracking
        try:
            redis_pattern = STUDENT_STRUGGLE_KEY.format(student_id="*")
            keys = redis_client.keys(redis_pattern)
            for key in keys:
                student_id = key.decode("utf-8").split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                data = redis_client.get(key)
                if data:
                    struggle_data = json.loads(
                        data.decode("utf-8") if isinstance(data, bytes) else data
                    )
                    if struggle_data.get("concept_id") == concept_id:
                        students.append({
                            "student_id": student_id,
                            "confusion_level": struggle_data.get("confusion_level", 0.0),
                            "concept_id": concept_id,
                            "source": "redis",
                        })
        except Exception as e:
            logger.warning(f"Redis struggle scan failed: {e}")

        # Deduplicate by student_id, keep highest confusion
        seen = {}
        for s in students:
            sid = s["student_id"]
            if sid not in seen or s["confusion_level"] > seen[sid]["confusion_level"]:
                seen[sid] = s

        return list(seen.values())

    async def _get_student_struggle_context(self, student_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full struggle context for a student.
        """
        try:
            # Get Working Memory
            result = (
                supabase.table("working_memory_snapshots")
                .select("snapshot")
                .eq("student_id", student_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                wm = result.data[0].get("snapshot", {})
                return {
                    "student_id": student_id,
                    "concept_id": wm.get("current_concept"),
                    "confusion_level": wm.get("confusion_level", 0.0),
                    "active_subject": wm.get("active_subject"),
                    "engagement_trajectory": wm.get("engagement_trajectory", "stable"),
                }
        except Exception as e:
            logger.warning(f"Could not get struggle context: {e}")

        # Fallback: check Redis
        try:
            data = redis_client.get(STUDENT_STRUGGLE_KEY.format(student_id=student_id))
            if data:
                return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        except Exception:
            pass

        return None

    # ═════════════════════════════════════════════════════════════════
    # 2. INSIGHT FETCHING
    # ═════════════════════════════════════════════════════════════════

    async def _fetch_swarm_insights(
        self,
        concept_id: str,
        min_effectiveness: float = 0.70,
        max_age_hours: int = 168,  # 7 days
    ) -> List[Dict[str, Any]]:
        """
        Fetch swarm insights for a concept.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            result = (
                supabase.table("swarm_insights")
                .select("*")
                .eq("concept_id", concept_id)
                .gte("effectiveness_score", min_effectiveness)
                .gte("created_at", cutoff.isoformat())
                .order("effectiveness_score", desc=True)
                .limit(50)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch swarm insights: {e}")
            return []

    # ═════════════════════════════════════════════════════════════════
    # 3. COMPATIBILITY SCORING
    # ═════════════════════════════════════════════════════════════════

    async def _score_compatibility(
        self,
        student: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Score how well an insight matches a struggling student.
        """
        scores = []

        # Get student profile
        student_profile = await self._get_student_profile(student["student_id"])

        # 1. Struggle pattern match (0.0-1.0)
        struggle_match = self._score_struggle_pattern_match(student, insight)
        scores.append(("struggle_pattern", struggle_match, WEIGHT_STRUGGLE_PATTERN))

        # 2. Class level match (0.0-1.0)
        class_match = self._score_class_level_match(student_profile, insight)
        scores.append(("class_level", class_match, WEIGHT_CLASS_LEVEL))

        # 3. Region match (0.0-1.0)
        region_match = self._score_region_match(student_profile, insight)
        scores.append(("region", region_match, WEIGHT_REGION))

        # 4. Bio-state compatibility (0.0-1.0)
        bio_match = await self._score_bio_state_match(student["student_id"], insight)
        scores.append(("bio_state", bio_match, WEIGHT_BIO_STATE))

        # 5. Language register match (0.0-1.0)
        lang_match = self._score_language_match(student_profile, insight)
        scores.append(("language", lang_match, WEIGHT_LANGUAGE))

        # 6. School type match (0.0-1.0)
        school_match = self._score_school_type_match(student_profile, insight)
        scores.append(("school_type", school_match, WEIGHT_SCHOOL_TYPE))

        # Calculate weighted composite
        total_weight = sum(w for _, _, w in scores)
        if total_weight == 0:
            return 0.0

        composite = sum(s * w for _, s, w in scores) / total_weight

        # Log detailed scoring for debugging
        detail = {name: round(score, 2) for name, score, _ in scores}
        logger.debug(f"Match score for {student['student_id'][:8]}: "
                    f"composite={composite:.2f}, details={detail}")

        return round(composite, 3)

    async def _score_compatibility_for_insight(
        self,
        student_id: str,
        struggle_context: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Score an insight for a specific student (reverse direction).
        Used by cron job proactive matching.
        """
        # Build synthetic student dict
        student = {
            "student_id": student_id,
            "confusion_level": struggle_context.get("confusion_level", 0.0),
            "concept_id": struggle_context.get("concept_id"),
        }
        return await self._score_compatibility(student, insight)

    def _score_struggle_pattern_match(
        self,
        student: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Match student's struggle pattern to insight's breakthrough pattern.
        """
        transfer_meta = insight.get("transfer_metadata", {})
        prior_struggle = transfer_meta.get("prior_struggle_pattern", "unknown")

        # High confusion = repeated_error pattern
        student_confusion = student.get("confusion_level", 0.0)
        if student_confusion >= 0.8 and prior_struggle == "repeated_error":
            return 1.0
        if student_confusion >= 0.6 and prior_struggle == "repeated_error":
            return 0.8
        if student_confusion >= 0.5 and prior_struggle == "confidence_rebuild":
            return 0.7

        # Default: moderate match
        return 0.5

    def _score_class_level_match(
        self,
        student_profile: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Match class level (JSS1, SS2, etc.).
        """
        student_class = student_profile.get("class_level", "unknown")
        insight_class = insight.get("provenance", {}).get("class_level", "unknown")

        if student_class == insight_class:
            return 1.0

        # Allow adjacent levels
        level_order = ["jss1", "jss2", "jss3", "ss1", "ss2", "ss3", "year1", "year2"]
        try:
            s_idx = level_order.index(student_class.lower())
            i_idx = level_order.index(insight_class.lower())
            diff = abs(s_idx - i_idx)
            if diff == 1:
                return 0.8
            if diff == 2:
                return 0.5
        except ValueError:
            pass

        return 0.3

    def _score_region_match(
        self,
        student_profile: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Match Nigerian region (south_west, north_central, etc.).
        """
        student_region = student_profile.get("state", "unknown")
        # Map state to region
        region_map = {
            "lagos": "south_west", "ibadan": "south_west", "abeokuta": "south_west",
            "ogun": "south_west", "ondo": "south_west", "ekiti": "south_west",
            "kano": "north_west", "kaduna": "north_west", "sokoto": "north_west",
            "katsina": "north_west", "kebbi": "north_west", "zamfara": "north_west",
            "abuja": "north_central", "jos": "north_central", "ilorin": "north_central",
            "niger": "north_central", "nasarawa": "north_central", "kwara": "north_central",
            "benue": "north_central", "plateau": "north_central",
            "enugu": "south_east", "owerri": "south_east", "aba": "south_east",
            "anambra": "south_east", "ebonyi": "south_east", "abia": "south_east",
            "imo": "south_east",
            "port harcourt": "south_south", "calabar": "south_south", "warri": "south_south",
            "rivers": "south_south", "cross river": "south_south", "akwa ibom": "south_south",
            "delta": "south_south", "edo": "south_south", "bayelsa": "south_south",
        }
        student_region = region_map.get(student_region.lower(), "unknown")

        insight_region = insight.get("provenance", {}).get("origin_region", "unknown")

        if student_region == insight_region:
            return 1.0
        if student_region != "unknown" and insight_region != "unknown":
            return 0.6  # Different region but both known
        return 0.4

    async def _score_bio_state_match(
        self,
        student_id: str,
        insight: Dict[str, Any],
    ) -> float:
        """
        Match biological state compatibility.
        Insights from 'evening_deep' work best delivered in 'evening_deep'.
        """
        try:
            from brain.circadian_socket import get_circadian_state
            current_state = await get_circadian_state(student_id)
        except Exception:
            current_state = "evening_deep"  # Default

        insight_state = insight.get("provenance", {}).get("bio_state_at_breakthrough", "evening_deep")

        # Same state = perfect match
        if current_state == insight_state:
            return 1.0

        # Compatible transitions
        compatible_pairs = [
            ("evening_deep", "after_school"),  # Similar cognitive load
            ("after_school", "evening_deep"),
            ("dawn_harvest", "school_stealth"),  # Both low-pressure
            ("night_survival", "dawn_harvest"),  # Sleep-adjacent
        ]
        if (current_state, insight_state) in compatible_pairs:
            return 0.8

        # Incompatible: don't deliver night insights in morning
        incompatible_pairs = [
            ("dawn_harvest", "night_survival"),
            ("school_stealth", "night_survival"),
        ]
        if (current_state, insight_state) in incompatible_pairs:
            return 0.2

        return 0.6  # Neutral

    def _score_language_match(
        self,
        student_profile: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Match language register (pidgin vs formal).
        Pidgin insights are MORE valuable for Nigerian students.
        """
        # Default to mixed (most common)
        student_lang = student_profile.get("language_preference", "mixed")
        insight_lang = insight.get("teaching_pattern", {}).get("language_register", "formal")

        # Exact match
        if student_lang == insight_lang:
            return 1.0

        # Mixed matches everything reasonably well
        if student_lang == "mixed" or insight_lang == "mixed":
            return 0.8

        # Formal-pidgin mismatch is still OK (students code-switch)
        return 0.6

    def _score_school_type_match(
        self,
        student_profile: Dict[str, Any],
        insight: Dict[str, Any],
    ) -> float:
        """
        Match school type (public/private/unity).
        """
        student_school = student_profile.get("school_type", "public")
        insight_school = insight.get("provenance", {}).get("origin_school_type", "public")

        if student_school == insight_school:
            return 1.0
        return 0.7  # Reasonable cross-match

    # ═════════════════════════════════════════════════════════════════
    # 4. STUDENT PROFILE FETCHING
    # ═════════════════════════════════════════════════════════════════

    async def _get_student_profile(self, student_id: str) -> Dict[str, Any]:
        """
        Fetch student profile from database.
        """
        try:
            result = (
                supabase.table("students")
                .select("class_level, state, language_preference, school_type, target_exam")
                .eq("id", student_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning(f"Could not fetch student profile: {e}")

        # Fallback: try by platform_user_id if id doesn't work
        try:
            result = (
                supabase.table("students")
                .select("class_level, state, language_preference, school_type, target_exam")
                .eq("platform_user_id", student_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception:
            pass

        return {}

    # ═════════════════════════════════════════════════════════════════
    # 5. DELIVERY PACKAGE BUILDING
    # ═════════════════════════════════════════════════════════════════

    async def _build_delivery_package(
        self,
        student: Dict[str, Any],
        insight: Dict[str, Any],
        compatibility_score: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Build a delivery package for the Zero-Knowledge Relay.
        """
        student_id = student["student_id"]

        # Check frequency limits
        if not await self._check_frequency_limits(student_id):
            return None

        # Build package
        package = {
            "student_id": student_id,
            "insight_id": insight["insight_id"],
            "concept_id": insight["concept_id"],
            "concept_name": insight["concept_name"],
            "subject": insight["subject"],
            "compatibility_score": compatibility_score,
            "delivery_content": self._format_delivery_content(insight),
            "delivery_config": {
                "framed_as": "let me try a different approach",
                "include_origin": False,  # Never reveal another student was involved
                "thermal_state": "warm",  # Gentle delivery
                "expect_reply": False,  # No pressure
            },
            "provenance_snapshot": {
                "origin_region": insight.get("provenance", {}).get("origin_region"),
                "origin_school_type": insight.get("provenance", {}).get("origin_school_type"),
                "class_level": insight.get("provenance", {}).get("class_level"),
            },
            "matched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Track this match
        await self._track_matched_insight(student_id, insight["insight_id"])

        return package

    def _format_delivery_content(self, insight: Dict[str, Any]) -> str:
        """
        Format the insight for delivery.
        NEVER reveals it came from another student.
        """
        payload = insight.get("insight_payload", {})

        # Build natural teaching message
        parts = []

        # Key framing first
        key_framing = payload.get("key_framing", "")
        if key_framing:
            parts.append(key_framing)

        # Analogy if available
        analogy = payload.get("analogy_used", "")
        if analogy:
            parts.append(f"Think of it this way: {analogy}")

        # Trigger question
        question = payload.get("trigger_question", "")
        if question:
            parts.append(question)

        # Concrete example
        example = payload.get("concrete_example", "")
        if example:
            parts.append(f"For example: {example}")

        # Join with natural flow
        content = " ".join(parts)

        # Add gentle framing
        return f"Let me try a different approach. {content}"

    async def _check_frequency_limits(self, student_id: str) -> bool:
        """
        Check if student has received too many insights recently.
        """
        try:
            # Check Redis for recent deliveries
            recent_key = MATCHED_INSIGHTS_KEY.format(student_id=student_id)
            recent_data = redis_client.get(recent_key)
            if recent_data:
                recent = json.loads(
                    recent_data.decode("utf-8") if isinstance(recent_data, bytes) else recent_data
                )
                now = datetime.now(timezone.utc)

                # Count in last hour
                hour_ago = now - timedelta(hours=1)
                hour_count = sum(
                    1 for t in recent
                    if datetime.fromisoformat(t.replace("Z", "+00:00")) > hour_ago
                )
                if hour_count >= MAX_INSIGHTS_PER_STUDENT_HOUR:
                    return False

                # Count in last day
                day_ago = now - timedelta(days=1)
                day_count = sum(
                    1 for t in recent
                    if datetime.fromisoformat(t.replace("Z", "+00:00")) > day_ago
                )
                if day_count >= MAX_INSIGHTS_PER_STUDENT_DAY:
                    return False

            return True
        except Exception as e:
            logger.warning(f"Frequency limit check failed: {e}")
            return True  # Allow if check fails

    async def _track_matched_insight(self, student_id: str, insight_id: str):
        """
        Track that this insight was matched to this student.
        """
        try:
            recent_key = MATCHED_INSIGHTS_KEY.format(student_id=student_id)
            recent_data = redis_client.get(recent_key)
            recent = []
            if recent_data:
                recent = json.loads(
                    recent_data.decode("utf-8") if isinstance(recent_data, bytes) else recent_data
                )

            recent.append(datetime.now(timezone.utc).isoformat())
            # Keep only last 30 entries
            recent = recent[-30:]

            redis_client.setex(
                recent_key,
                int(timedelta(days=7).total_seconds()),
                json.dumps(recent),
            )
        except Exception as e:
            logger.warning(f"Failed to track matched insight: {e}")

    async def _apply_frequency_limits(
        self,
        student_id: str,
        scored_insights: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Filter insights by frequency limits.
        """
        filtered = []
        for item in scored_insights:
            if await self._check_frequency_limits(student_id):
                filtered.append(item)
            else:
                break  # Stop once limit reached
        return filtered


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════════════════

async def find_matches_for_insight(
    insight_capsule: Dict[str, Any],
    max_matches: int = 10,
) -> List[Dict[str, Any]]:
    """
    High-level API: Find struggling students for an insight.
    """
    matcher = SwarmMatcher()
    return await matcher.find_matches_for_insight(insight_capsule, max_matches)


async def find_insights_for_student(
    student_id: str,
    current_concept: Optional[str] = None,
    max_insights: int = 3,
) -> List[Dict[str, Any]]:
    """
    High-level API: Find insights for a struggling student.
    Called by cron job.
    """
    matcher = SwarmMatcher()
    return await matcher.find_insights_for_student(student_id, current_concept, max_insights)
