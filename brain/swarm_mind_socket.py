"""
brain/swarm_mind_socket.py — Swarm Mind Orchestrator

Central nervous system for the Ubuntu Swarm Mind.

Wires all 5 subsystems into a single pipeline:
    Student Message → S1 → S2 → S3 → S4 → S5 → Delivery Package

Provides ONE clean API for telegram/handler.py:
    process_message() — handles everything

Connections:
- S1: Breakthrough Seismograph (breakthrough_seismograph.py)
- S2: Insight Distillery (insight_distillery.py)
- S3: Swarm Matcher (swarm_matcher.py)
- S4: Zero-Knowledge Relay (zero_knowledge_relay.py)
- S5: Contagion Limiter (contagion_limiter.py)

Also connects to:
- Student Mind Mirror (cognitive state vectors)
- Circadian Teaching Cortex (bio-state for matching)
- PIG Engine (intimacy score for delivery weighting)
- Working Memory (current concept, session context)

Output: List of delivery packages or None

CHANGELOG:
- 2026-05-25: Created for Ubuntu Swarm Mind P2-A
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.swarm_orchestrator")

# ═══════════════════════════════════════════════════════════════════════
# SUBSYSTEM IMPORTS (with graceful degradation)
# ═══════════════════════════════════════════════════════════════════════

try:
    from brain.breakthrough_seismograph import detect_breakthrough
    _S1_AVAILABLE = True
except ImportError:
    _S1_AVAILABLE = False
    logger.warning("S1 Breakthrough Seismograph not available")

try:
    from brain.insight_distillery import distill_insight
    _S2_AVAILABLE = True
except ImportError:
    _S2_AVAILABLE = False
    logger.warning("S2 Insight Distillery not available")

try:
    from brain.swarm_matcher import find_matches_for_insight, find_insights_for_student
    _S3_AVAILABLE = True
except ImportError:
    _S3_AVAILABLE = False
    logger.warning("S3 Swarm Matcher not available")

try:
    from brain.zero_knowledge_relay import sanitize_insight, check_opt_out
    _S4_AVAILABLE = True
except ImportError:
    _S4_AVAILABLE = False
    logger.warning("S4 Zero-Knowledge Relay not available")

try:
    from brain.contagion_limiter import authorize_delivery, record_delivery, record_acceptance
    _S5_AVAILABLE = True
except ImportError:
    _S5_AVAILABLE = False
    logger.warning("S5 Contagion Limiter not available")

# ═══════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

class SwarmMindOrchestrator:
    """
    Central orchestrator for the Ubuntu Swarm Mind.

    Usage:
        swarm = SwarmMindOrchestrator()
        
        # On every student message
        result = await swarm.process_message(
            student_id="student_123",
            message_text="I get it now! 2x + 3 = 7 means x = 2!",
            mind_mirror_state={"confidence": 0.85, "emotion": "excited"},
            conversation_history=[...],
            working_memory={"current_concept": "linear_equations", ...},
        )
        
        if result and result.get("breakthrough_detected"):
            # Insight was extracted and matched to struggling students
            pass
    """

    def __init__(self):
        self.available = all([_S1_AVAILABLE, _S2_AVAILABLE, _S3_AVAILABLE,
                             _S4_AVAILABLE, _S5_AVAILABLE])
        if not self.available:
            missing = []
            if not _S1_AVAILABLE: missing.append("S1")
            if not _S2_AVAILABLE: missing.append("S2")
            if not _S3_AVAILABLE: missing.append("S3")
            if not _S4_AVAILABLE: missing.append("S4")
            if not _S5_AVAILABLE: missing.append("S5")
            logger.warning(f"Swarm Mind partially available. Missing: {', '.join(missing)}")

    async def process_message(
        self,
        student_id: str,
        message_text: str,
        mind_mirror_state: Dict[str, Any],
        conversation_history: List[Dict[str, Any]],
        working_memory: Dict[str, Any],
        response_time_seconds: Optional[float] = None,
        is_correct_answer: bool = False,
        student_metadata: Optional[Dict[str, Any]] = None,
        teaching_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a student message through the full swarm pipeline.

        Returns dict with:
        - breakthrough_detected: bool
        - insight_capsule: dict (if breakthrough)
        - matches: list (if insight extracted)
        - deliveries: list (if matches found)
        - errors: list (if any subsystem failed)
        """
        result = {
            "breakthrough_detected": False,
            "insight_capsule": None,
            "matches": [],
            "deliveries": [],
            "errors": [],
        }

        if not self.available:
            result["errors"].append("Swarm Mind not fully available")
            return result

        # ═════════════════════════════════════════════════════════════════
        # STAGE 1: Breakthrough Detection (S1)
        # ═════════════════════════════════════════════════════════════════
        try:
            previous_message = None
            if len(conversation_history) >= 2:
                # Get last student message before this one
                for msg in reversed(conversation_history[:-1]):
                    if msg.get("role") == "user":
                        previous_message = msg.get("content")
                        break

            seismo_result = await detect_breakthrough(
                student_id=student_id,
                message_text=message_text,
                mind_mirror_state=mind_mirror_state,
                response_time_seconds=response_time_seconds,
                is_correct_answer=is_correct_answer,
                current_concept=working_memory.get("current_concept"),
                previous_message_text=previous_message,
            )

            result["breakthrough_detected"] = seismo_result.get("breakthrough_detected", False)
            result["seismograph_reading"] = seismo_result

            if not result["breakthrough_detected"]:
                logger.debug(f"No breakthrough detected for {student_id[:8]}...")
                return result

            logger.info(f"Breakthrough detected for {student_id[:8]}... "
                       f"(score: {seismo_result.get('composite_score', 0):.2f}, "
                       f"pattern: {seismo_result.get('dominant_pattern', 'unknown')})")

        except Exception as e:
            logger.error(f"S1 Breakthrough Seismograph failed: {e}")
            result["errors"].append(f"S1: {str(e)}")
            return result

        # ═════════════════════════════════════════════════════════════════
        # STAGE 2: Insight Distillation (S2)
        # ═════════════════════════════════════════════════════════════════
        try:
            # Build student metadata
            meta = student_metadata or {}
            # Add bio-state from circadian cortex
            try:
                from brain.circadian_socket import get_circadian_state
                bio_state = await get_circadian_state(student_id)
                meta["bio_state"] = bio_state
            except Exception:
                meta["bio_state"] = "evening_deep"

            # Add PIG score
            try:
                from brain.relational_intimacy import get_current_intimacy_score
                pig_score = await get_current_intimacy_score(student_id)
                meta["pig_score"] = pig_score
            except Exception:
                meta["pig_score"] = 3.0

            # Get session ID from working memory
            session_id = working_memory.get("session_id", "unknown")

            insight_capsule = await distill_insight(
                student_id=student_id,
                breakthrough_signal=seismo_result,
                conversation_history=conversation_history[-10:],  # Last 10 messages
                working_memory=working_memory,
                teaching_context=teaching_context,
                student_metadata=meta,
                session_id=session_id,
            )

            if not insight_capsule:
                logger.info(f"Insight below quality threshold for {student_id[:8]}...")
                result["errors"].append("S2: Insight below quality threshold")
                return result

            result["insight_capsule"] = insight_capsule
            logger.info(f"Insight distilled: {insight_capsule['insight_id'][:16]}... "
                       f"(score: {insight_capsule['effectiveness_score']:.2f}, "
                       f"tier: {insight_capsule['quality_tier']})")

        except Exception as e:
            logger.error(f"S2 Insight Distillery failed: {e}")
            result["errors"].append(f"S2: {str(e)}")
            return result

        # ═════════════════════════════════════════════════════════════════
        # STAGE 3: Swarm Matching (S3)
        # ═════════════════════════════════════════════════════════════════
        try:
            matches = await find_matches_for_insight(
                insight_capsule=insight_capsule,
                max_matches=10,
            )

            if not matches:
                logger.info(f"No swarm matches for insight {insight_capsule['insight_id'][:16]}...")
                result["errors"].append("S3: No matches found")
                return result

            result["matches"] = matches
            logger.info(f"Swarm Matcher: {len(matches)} matches for insight "
                       f"{insight_capsule['insight_id'][:16]}...")

        except Exception as e:
            logger.error(f"S3 Swarm Matcher failed: {e}")
            result["errors"].append(f"S3: {str(e)}")
            return result

        # ═════════════════════════════════════════════════════════════════
        # STAGE 4: Zero-Knowledge Sanitization (S4)
        # ═════════════════════════════════════════════════════════════════
        try:
            sanitized_deliveries = []
            for match in matches:
                safe_payload = await sanitize_insight(
                    delivery_package=match,
                    insight_capsule=insight_capsule,
                )
                if safe_payload:
                    sanitized_deliveries.append({
                        "student_id": match["student_id"],
                        "payload": safe_payload,
                        "compatibility_score": match["compatibility_score"],
                    })

            if not sanitized_deliveries:
                logger.info("All deliveries sanitized to None (opt-out or error)")
                result["errors"].append("S4: All deliveries sanitized")
                return result

            result["sanitized_deliveries"] = sanitized_deliveries

        except Exception as e:
            logger.error(f"S4 Zero-Knowledge Relay failed: {e}")
            result["errors"].append(f"S4: {str(e)}")
            return result

        # ═════════════════════════════════════════════════════════════════
        # STAGE 5: Contagion Limiting (S5)
        # ═════════════════════════════════════════════════════════════════
        try:
            final_deliveries = []
            for delivery in sanitized_deliveries:
                auth = await authorize_delivery(
                    insight_id=insight_capsule["insight_id"],
                    concept_id=insight_capsule["concept_id"],
                    student_id=delivery["student_id"],
                    insight_effectiveness=insight_capsule["effectiveness_score"],
                )

                if auth["authorized"]:
                    # Record delivery for tracking
                    await record_delivery(
                        insight_id=insight_capsule["insight_id"],
                        concept_id=insight_capsule["concept_id"],
                        student_id=delivery["student_id"],
                    )

                    final_deliveries.append({
                        "student_id": delivery["student_id"],
                        "payload": delivery["payload"],
                        "phase": auth["phase"],
                        "deliveries_remaining": auth["deliveries_remaining"],
                    })
                else:
                    logger.debug(f"Delivery blocked for {delivery['student_id'][:8]}...: "
                               f"{auth['reason']}")

            result["deliveries"] = final_deliveries
            logger.info(f"Contagion Limiter: {len(final_deliveries)} authorized deliveries "
                       f"for insight {insight_capsule['insight_id'][:16]}...")

        except Exception as e:
            logger.error(f"S5 Contagion Limiter failed: {e}")
            result["errors"].append(f"S5: {str(e)}")
            return result

        # ═════════════════════════════════════════════════════════════════
        # PERSIST INSIGHT TO DATABASE
        # ═════════════════════════════════════════════════════════════════
        try:
            await self._persist_insight(insight_capsule)
        except Exception as e:
            logger.warning(f"Failed to persist insight: {e}")

        return result

    async def process_student_struggle(
        self,
        student_id: str,
        current_concept: Optional[str] = None,
        max_insights: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Proactive: Find insights for a struggling student.
        Called by cron job.
        """
        if not _S3_AVAILABLE:
            return []

        try:
            insights = await find_insights_for_student(
                student_id=student_id,
                current_concept=current_concept,
                max_insights=max_insights,
            )

            if not insights:
                return []

            # Sanitize and limit each insight
            deliveries = []
            for insight in insights:
                # Build synthetic delivery package
                package = {
                    "student_id": student_id,
                    "insight_id": insight.get("insight_id"),
                    "compatibility_score": 0.8,  # High score since we matched proactively
                    "delivery_content": "",  # Will be built by relay
                    "delivery_config": {
                        "framed_as": "let me try a different approach",
                        "include_origin": False,
                        "thermal_state": "warm",
                        "expect_reply": False,
                    },
                }

                if _S4_AVAILABLE:
                    safe = await sanitize_insight(package, insight)
                    if safe:
                        deliveries.append({
                            "student_id": student_id,
                            "payload": safe,
                        })

            return deliveries

        except Exception as e:
            logger.error(f"Proactive struggle processing failed: {e}")
            return []

    async def record_insight_acceptance(
        self,
        insight_id: str,
        concept_id: str,
        student_id: str,
        accepted: bool,
    ) -> bool:
        """
        Record whether a student accepted an insight.
        """
        if not _S5_AVAILABLE:
            return False

        try:
            return await record_acceptance(
                insight_id=insight_id,
                concept_id=concept_id,
                student_id=student_id,
                accepted=accepted,
            )
        except Exception as e:
            logger.error(f"Failed to record acceptance: {e}")
            return False

    async def _persist_insight(self, insight_capsule: Dict[str, Any]) -> bool:
        """
        Persist insight capsule to swarm_insights table.
        """
        try:
            # Convert to database format
            db_record = {
                "insight_id": insight_capsule["insight_id"],
                "concept_id": insight_capsule["concept_id"],
                "concept_name": insight_capsule["concept_name"],
                "subject": insight_capsule["subject"],
                "breakthrough_type": insight_capsule["breakthrough_type"],
                "teaching_pattern": insight_capsule.get("teaching_pattern", {}),
                "insight_payload": insight_capsule.get("insight_payload", {}),
                "effectiveness_score": float(insight_capsule["effectiveness_score"]),
                "quality_tier": insight_capsule["quality_tier"],
                "provenance": insight_capsule.get("provenance", {}),
                "transfer_metadata": insight_capsule.get("transfer_metadata", {}),
                "created_at": insight_capsule.get("created_at", datetime.now(timezone.utc).isoformat()),
            }

            supabase.table("swarm_insights").upsert(
                db_record,
                on_conflict="insight_id",
            ).execute()

            return True
        except Exception as e:
            logger.error(f"Failed to persist insight: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API (for telegram/handler.py)
# ═══════════════════════════════════════════════════════════════════════

async def process_message(
    student_id: str,
    message_text: str,
    mind_mirror_state: Dict[str, Any],
    conversation_history: List[Dict[str, Any]],
    working_memory: Dict[str, Any],
    response_time_seconds: Optional[float] = None,
    is_correct_answer: bool = False,
    student_metadata: Optional[Dict[str, Any]] = None,
    teaching_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    High-level API: Process a student message through the full swarm pipeline.

    This is the ONE function telegram/handler.py calls.
    """
    swarm = SwarmMindOrchestrator()
    return await swarm.process_message(
        student_id=student_id,
        message_text=message_text,
        mind_mirror_state=mind_mirror_state,
        conversation_history=conversation_history,
        working_memory=working_memory,
        response_time_seconds=response_time_seconds,
        is_correct_answer=is_correct_answer,
        student_metadata=student_metadata,
        teaching_context=teaching_context,
    )


async def find_insights_for_struggling_student(
    student_id: str,
    current_concept: Optional[str] = None,
    max_insights: int = 3,
) -> List[Dict[str, Any]]:
    """
    High-level API: Proactively find insights for a struggling student.
    Called by cron job.
    """
    swarm = SwarmMindOrchestrator()
    return await swarm.process_student_struggle(
        student_id=student_id,
        current_concept=current_concept,
        max_insights=max_insights,
    )


async def record_acceptance(
    insight_id: str,
    concept_id: str,
    student_id: str,
    accepted: bool,
) -> bool:
    """
    High-level API: Record insight acceptance.
    """
    swarm = SwarmMindOrchestrator()
    return await swarm.record_insight_acceptance(
        insight_id=insight_id,
        concept_id=concept_id,
        student_id=student_id,
        accepted=accepted,
    )


def is_swarm_available() -> bool:
    """
    Check if all swarm subsystems are available.
    """
    return all([_S1_AVAILABLE, _S2_AVAILABLE, _S3_AVAILABLE,
                _S4_AVAILABLE, _S5_AVAILABLE])
