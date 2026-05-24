"""
brain/contagion_limiter.py — Contagion Limiter (S5)

Epidemic-inspired spread control for the Ubuntu Swarm Mind.

Controls:
1. Quality Gate — Minimum effectiveness threshold for swarm entry
2. Velocity Control — 4 phases: incubation → slow → fast → viral
3. Anti-Flood — Max 2/hour, 5/day per student
4. Saturation Detection — Stop when 70% mastery reached
5. Automatic Containment — Pull back if acceptance rate drops

The Limiter answers: "How fast should this insight spread, and when should it stop?"

Connections:
- swarm_insights table (reads effectiveness scores, spread counts)
- ghost_threads table (tracks delivery and acceptance)
- Redis (velocity state, saturation counters, flood windows)

Output: Delivery authorization with velocity constraints

CHANGELOG:
- 2026-05-25: Created for Ubuntu Swarm Mind P2-A
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, List, Optional

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.contagion_limiter")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Quality gate
MIN_EFFECTIVENESS_FOR_SWARM = 0.70
MIN_ACCEPTANCE_RATE = 0.40  # 40% of recipients must engage

# Velocity phases
VELOCITY_PHASES = {
    "incubation": {"max_deliveries": 3, "min_acceptance": 0.60},
    "slow": {"max_deliveries": 10, "min_acceptance": 0.50},
    "fast": {"max_deliveries": 50, "min_acceptance": 0.40},
    "viral": {"max_deliveries": float("inf"), "min_acceptance": 0.0},
    "contained": {"max_deliveries": 0, "min_acceptance": 0.0},
}

# Anti-flood limits
MAX_PER_HOUR = 2
MAX_PER_DAY = 5
FLOOD_WINDOW_HOURS = 1
FLOOD_WINDOW_DAYS = 24

# Saturation
SATURATION_MASTERY_THRESHOLD = 0.70  # 70% of students mastered
SATURATION_SAMPLE_SIZE = 20  # Minimum students to check

# Redis keys
VELOCITY_STATE_KEY = "contagion:velocity:{insight_id}"
DELIVERY_COUNT_KEY = "contagion:delivered:{insight_id}"
ACCEPTANCE_TRACKING_KEY = "contagion:acceptance:{insight_id}"
STUDENT_FLOOD_KEY = "contagion:flood:{student_id}"
SATURATION_KEY = "contagion:saturation:{concept_id}"

# ═══════════════════════════════════════════════════════════════════════
# VELOCITY PHASE ENUM
# ═══════════════════════════════════════════════════════════════════════

class VelocityPhase(Enum):
    INCUBATION = "incubation"
    SLOW = "slow"
    FAST = "fast"
    VIRAL = "viral"
    CONTAINED = "contained"

    @classmethod
    def from_string(cls, value: str) -> "VelocityPhase":
        try:
            return cls(value)
        except ValueError:
            return cls.CONTAINED


# ═══════════════════════════════════════════════════════════════════════
# MAIN LIMITER
# ═══════════════════════════════════════════════════════════════════════

class ContagionLimiter:
    """
    Controls insight spread velocity and saturation.

    Usage:
        limiter = ContagionLimiter(insight_id, concept_id)
        
        # Check if we can deliver to a student
        auth = await limiter.authorize_delivery(student_id)
        if auth["authorized"]:
            # Deliver insight
            pass
        
        # Record acceptance after delivery
        await limiter.record_acceptance(student_id, accepted=True)
        
        # Check if we should advance velocity phase
        await limiter.evaluate_velocity_advancement()
    """

    def __init__(self, insight_id: str, concept_id: str):
        self.insight_id = insight_id
        self.concept_id = concept_id
        self.velocity_state_key = VELOCITY_STATE_KEY.format(insight_id=insight_id)
        self.delivery_count_key = DELIVERY_COUNT_KEY.format(insight_id=insight_id)
        self.acceptance_key = ACCEPTANCE_TRACKING_KEY.format(insight_id=insight_id)

    async def authorize_delivery(
        self,
        student_id: str,
        insight_effectiveness: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Check if delivery to this student is authorized.

        Returns dict with:
        - authorized: bool
        - reason: str (if not authorized)
        - phase: str (current velocity phase)
        - deliveries_remaining: int
        """
        # 1. Quality gate
        if insight_effectiveness < MIN_EFFECTIVENESS_FOR_SWARM:
            return {
                "authorized": False,
                "reason": f"Quality gate: {insight_effectiveness:.2f} < {MIN_EFFECTIVENESS_FOR_SWARM}",
                "phase": "contained",
                "deliveries_remaining": 0,
            }

        # 2. Get current velocity phase
        phase = await self._get_current_phase()

        # 3. Check velocity limits
        current_deliveries = await self._get_delivery_count()
        phase_config = VELOCITY_PHASES[phase.value]

        if current_deliveries >= phase_config["max_deliveries"]:
            # Check if we can advance
            can_advance = await self._evaluate_advancement()
            if not can_advance:
                return {
                    "authorized": False,
                    "reason": f"Velocity limit reached: {current_deliveries} deliveries in {phase.value} phase",
                    "phase": phase.value,
                    "deliveries_remaining": 0,
                }

        # 4. Check saturation
        if await self._is_saturated():
            return {
                "authorized": False,
                "reason": "Saturation: 70%+ of students have mastered this concept",
                "phase": "contained",
                "deliveries_remaining": 0,
            }

        # 5. Anti-flood check
        flood_check = await self._check_flood_limits(student_id)
        if not flood_check["allowed"]:
            return {
                "authorized": False,
                "reason": flood_check["reason"],
                "phase": phase.value,
                "deliveries_remaining": phase_config["max_deliveries"] - current_deliveries,
            }

        # 6. All checks passed
        remaining = phase_config["max_deliveries"] - current_deliveries
        if remaining < 0:
            remaining = 0

        return {
            "authorized": True,
            "reason": "Delivery authorized",
            "phase": phase.value,
            "deliveries_remaining": remaining,
        }

    async def record_delivery(self, student_id: str) -> bool:
        """
        Record that an insight was delivered to a student.
        """
        try:
            # Increment delivery count
            count = await self._get_delivery_count()
            redis_client.set(self.delivery_count_key, count + 1)

            # Record in acceptance tracking
            tracking = await self._get_acceptance_tracking()
            tracking["delivered_to"].append({
                "student_id": student_id,
                "delivered_at": datetime.now(timezone.utc).isoformat(),
                "accepted": None,  # Will be updated later
            })
            redis_client.setex(
                self.acceptance_key,
                int(timedelta(days=7).total_seconds()),
                json.dumps(tracking),
            )

            # Update student flood tracking
            await self._update_flood_tracking(student_id)

            return True
        except Exception as e:
            logger.error(f"Failed to record delivery: {e}")
            return False

    async def record_acceptance(self, student_id: str, accepted: bool) -> bool:
        """
        Record whether student accepted/engaged with the insight.
        """
        try:
            tracking = await self._get_acceptance_tracking()
            for record in tracking.get("delivered_to", []):
                if record.get("student_id") == student_id and record.get("accepted") is None:
                    record["accepted"] = accepted
                    record["accepted_at"] = datetime.now(timezone.utc).isoformat()
                    break

            redis_client.setex(
                self.acceptance_key,
                int(timedelta(days=7).total_seconds()),
                json.dumps(tracking),
            )

            # Evaluate if we should advance or contain
            await self._evaluate_velocity_advancement()

            return True
        except Exception as e:
            logger.error(f"Failed to record acceptance: {e}")
            return False

    # ═════════════════════════════════════════════════════════════════
    # VELOCITY CONTROL
    # ═════════════════════════════════════════════════════════════════

    async def _get_current_phase(self) -> VelocityPhase:
        """
        Get current velocity phase from Redis.
        """
        try:
            cached = redis_client.get(self.velocity_state_key)
            if cached:
                phase_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                return VelocityPhase.from_string(phase_str)
        except Exception:
            pass

        # Default: incubation
        redis_client.setex(
            self.velocity_state_key,
            int(timedelta(days=7).total_seconds()),
            VelocityPhase.INCUBATION.value,
        )
        return VelocityPhase.INCUBATION

    async def _set_phase(self, phase: VelocityPhase) -> bool:
        """
        Set velocity phase.
        """
        try:
            redis_client.setex(
                self.velocity_state_key,
                int(timedelta(days=7).total_seconds()),
                phase.value,
            )
            logger.info(f"Insight {self.insight_id[:8]}... velocity phase: {phase.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to set phase: {e}")
            return False

    async def _evaluate_advancement(self) -> bool:
        """
        Check if insight should advance to next velocity phase.
        """
        phase = await self._get_current_phase()
        if phase == VelocityPhase.VIRAL:
            return True  # Already at max
        if phase == VelocityPhase.CONTAINED:
            return False  # Contained, don't advance

        phase_config = VELOCITY_PHASES[phase.value]
        tracking = await self._get_acceptance_tracking()

        # Calculate acceptance rate
        delivered = tracking.get("delivered_to", [])
        if len(delivered) < 3:  # Need minimum sample
            return False

        accepted = sum(1 for d in delivered if d.get("accepted") is True)
        acceptance_rate = accepted / len(delivered)

        # Check if acceptance rate meets threshold for advancement
        if acceptance_rate >= phase_config["min_acceptance"]:
            # Advance to next phase
            next_phase = self._next_phase(phase)
            if next_phase:
                await self._set_phase(next_phase)
                return True

        # If acceptance rate is very low, contain
        if acceptance_rate < 0.20 and len(delivered) >= 5:
            await self._set_phase(VelocityPhase.CONTAINED)
            logger.warning(f"Insight {self.insight_id[:8]}... contained due to low acceptance "
                        f"({acceptance_rate:.2f})")

        return False

    async def _evaluate_velocity_advancement(self) -> bool:
        """
        Public API for velocity evaluation.
        """
        return await self._evaluate_advancement()

    def _next_phase(self, current: VelocityPhase) -> Optional[VelocityPhase]:
        """
        Get next velocity phase.
        """
        progression = {
            VelocityPhase.INCUBATION: VelocityPhase.SLOW,
            VelocityPhase.SLOW: VelocityPhase.FAST,
            VelocityPhase.FAST: VelocityPhase.VIRAL,
            VelocityPhase.VIRAL: None,
            VelocityPhase.CONTAINED: None,
        }
        return progression.get(current)

    # ═════════════════════════════════════════════════════════════════
    # DELIVERY COUNTING
    # ═════════════════════════════════════════════════════════════════

    async def _get_delivery_count(self) -> int:
        """
        Get number of deliveries for this insight.
        """
        try:
            count = redis_client.get(self.delivery_count_key)
            if count:
                return int(count.decode("utf-8") if isinstance(count, bytes) else count)
        except Exception:
            pass
        return 0

    async def _get_acceptance_tracking(self) -> Dict[str, Any]:
        """
        Get acceptance tracking data.
        """
        try:
            data = redis_client.get(self.acceptance_key)
            if data:
                return json.loads(
                    data.decode("utf-8") if isinstance(data, bytes) else data
                )
        except Exception:
            pass
        return {"delivered_to": []}

    # ═════════════════════════════════════════════════════════════════
    # ANTI-FLOOD
    # ═════════════════════════════════════════════════════════════════

    async def _check_flood_limits(self, student_id: str) -> Dict[str, Any]:
        """
        Check if student has received too many insights recently.
        """
        try:
            flood_key = STUDENT_FLOOD_KEY.format(student_id=student_id)
            flood_data = redis_client.get(flood_key)
            if not flood_data:
                return {"allowed": True, "reason": "No recent deliveries"}

            flood = json.loads(
                flood_data.decode("utf-8") if isinstance(flood_data, bytes) else flood_data
            )
            now = datetime.now(timezone.utc)

            # Count in last hour
            hour_ago = now - timedelta(hours=1)
            hour_count = sum(
                1 for t in flood.get("recent_deliveries", [])
                if datetime.fromisoformat(t.replace("Z", "+00:00")) > hour_ago
            )
            if hour_count >= MAX_PER_HOUR:
                return {
                    "allowed": False,
                    "reason": f"Anti-flood: {hour_count} insights in last hour (max {MAX_PER_HOUR})",
                }

            # Count in last day
            day_ago = now - timedelta(days=1)
            day_count = sum(
                1 for t in flood.get("recent_deliveries", [])
                if datetime.fromisoformat(t.replace("Z", "+00:00")) > day_ago
            )
            if day_count >= MAX_PER_DAY:
                return {
                    "allowed": False,
                    "reason": f"Anti-flood: {day_count} insights in last day (max {MAX_PER_DAY})",
                }

            return {"allowed": True, "reason": "Within flood limits"}
        except Exception as e:
            logger.warning(f"Flood check failed: {e}")
            return {"allowed": True, "reason": "Check failed, allowing"}  # Fail open

    async def _update_flood_tracking(self, student_id: str):
        """
        Update flood tracking for a student.
        """
        try:
            flood_key = STUDENT_FLOOD_KEY.format(student_id=student_id)
            flood_data = redis_client.get(flood_key)
            flood = {"recent_deliveries": []}
            if flood_data:
                flood = json.loads(
                    flood_data.decode("utf-8") if isinstance(flood_data, bytes) else flood_data
                )

            flood["recent_deliveries"].append(datetime.now(timezone.utc).isoformat())
            # Keep only last 30 entries
            flood["recent_deliveries"] = flood["recent_deliveries"][-30:]

            redis_client.setex(
                flood_key,
                int(timedelta(days=2).total_seconds()),
                json.dumps(flood),
            )
        except Exception as e:
            logger.warning(f"Failed to update flood tracking: {e}")

    # ═════════════════════════════════════════════════════════════════
    # SATURATION DETECTION
    # ═════════════════════════════════════════════════════════════════

    async def _is_saturated(self) -> bool:
        """
        Check if concept has reached saturation (70% mastery).
        """
        try:
            # Check Redis cache first
            sat_key = SATURATION_KEY.format(concept_id=self.concept_id)
            cached = redis_client.get(sat_key)
            if cached:
                is_saturated = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                return is_saturated == "true"
        except Exception:
            pass

        # Check database
        try:
            # Count students who have worked on this concept
            result = (
                supabase.table("working_memory_snapshots")
                .select("student_id, snapshot")
                .eq("snapshot->>current_concept", self.concept_id)
                .limit(SATURATION_SAMPLE_SIZE * 2)
                .execute()
            )

            if not result.data or len(result.data) < SATURATION_SAMPLE_SIZE:
                return False  # Not enough data

            # Count mastery
            mastered = 0
            total = 0
            seen_students = set()

            for row in result.data:
                student_id = row["student_id"]
                if student_id in seen_students:
                    continue
                seen_students.add(student_id)

                snapshot = row.get("snapshot", {})
                confusion = float(snapshot.get("confusion_level", 1.0))
                # Mastery = low confusion + high engagement
                if confusion < 0.3:
                    mastered += 1
                total += 1

                if total >= SATURATION_SAMPLE_SIZE:
                    break

            mastery_rate = mastered / total if total > 0 else 0

            # Cache result
            try:
                redis_client.setex(
                    sat_key,
                    int(timedelta(hours=6).total_seconds()),
                    "true" if mastery_rate >= SATURATION_MASTERY_THRESHOLD else "false",
                )
            except Exception:
                pass

            return mastery_rate >= SATURATION_MASTERY_THRESHOLD

        except Exception as e:
            logger.warning(f"Saturation check failed: {e}")
            return False  # Fail open (allow delivery if check fails)


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════════════════

async def authorize_delivery(
    insight_id: str,
    concept_id: str,
    student_id: str,
    insight_effectiveness: float = 0.0,
) -> Dict[str, Any]:
    """
    High-level API: Check if delivery is authorized.
    """
    limiter = ContagionLimiter(insight_id, concept_id)
    return await limiter.authorize_delivery(student_id, insight_effectiveness)


async def record_delivery(insight_id: str, concept_id: str, student_id: str) -> bool:
    """
    High-level API: Record a delivery.
    """
    limiter = ContagionLimiter(insight_id, concept_id)
    return await limiter.record_delivery(student_id)


async def record_acceptance(insight_id: str, concept_id: str, student_id: str, accepted: bool) -> bool:
    """
    High-level API: Record acceptance.
    """
    limiter = ContagionLimiter(insight_id, concept_id)
    return await limiter.record_acceptance(student_id, accepted)


async def get_velocity_phase(insight_id: str, concept_id: str) -> str:
    """
    High-level API: Get current velocity phase.
    """
    limiter = ContagionLimiter(insight_id, concept_id)
    phase = await limiter._get_current_phase()
    return phase.value
