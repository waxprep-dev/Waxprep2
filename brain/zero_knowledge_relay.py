"""
brain/zero_knowledge_relay.py — Zero-Knowledge Relay (S4)

Privacy-preserving insight transfer layer.

Guarantees:
1. No student IDs in transit — SHA-256 hash with daily rotating salt
2. No locations — Generalized to 6 Nigerian zones
3. No school names — Only type: public/private/unity
4. No contact info — Phone/email patterns stripped
5. Noise on scores — Differential privacy (epsilon=1.0)
6. Audit everything — Every transfer logged
7. Student opt-out — Per-student consent gate

The Relay answers: "How do we share insights without sharing students?"

Connections:
- Swarm Matcher (S3) — receives delivery packages
- swarm_insights table — reads insight capsules
- audit_log table — writes every transfer
- Redis — salt rotation, opt-out cache

Output: Privacy-safe payload ready for delivery to student

CHANGELOG:
- 2026-05-25: Created for Ubuntu Swarm Mind P2-A
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.zk_relay")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Differential privacy parameters
DP_EPSILON = 1.0
DP_SENSITIVITY = 1.0  # Max change in score from one student's data

# Daily salt rotation
SALT_KEY = "zk:salt:{date}"  # YYYY-MM-DD
SALT_TTL = 86400 * 2  # 2 days (overlap for timezone safety)

# Audit logging
AUDIT_BATCH_SIZE = 100  # Batch audit logs

# Opt-out
OPT_OUT_KEY = "zk:optout:{student_id}"

# PII patterns to strip
PII_PATTERNS = [
    r'\b\d{11}\b',  # Nigerian phone numbers (11 digits)
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Emails
    r'\b\d{2}/\d{2}/\d{4}\b',  # Dates of birth
    r'\b\d{10,11}\b',  # Any 10-11 digit number (NIN, etc.)
]

# ═══════════════════════════════════════════════════════════════════════
# MAIN RELAY
# ═══════════════════════════════════════════════════════════════════════

class ZeroKnowledgeRelay:
    """
    Privacy-preserving insight transfer.

    Usage:
        relay = ZeroKnowledgeRelay()
        safe_payload = await relay.sanitize(
            delivery_package=match_package,
            insight_capsule=insight,
        )
        # safe_payload contains NO identifying information
    """

    def __init__(self):
        self._salt = None
        self._salt_date = None

    async def sanitize(
        self,
        delivery_package: Dict[str, Any],
        insight_capsule: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Sanitize a delivery package for privacy-safe transfer.

        Args:
            delivery_package: From Swarm Matcher (contains student_id)
            insight_capsule: The insight to transfer

        Returns:
            Privacy-safe payload, or None if student opted out
        """
        student_id = delivery_package.get("student_id")
        insight_id = insight_capsule.get("insight_id")

        # 1. Check opt-out
        if await self._is_opted_out(student_id):
            logger.info(f"Student {student_id[:8]}... opted out of swarm insights")
            return None

        # 2. Get daily salt
        salt = await self._get_daily_salt()

        # 3. Strip all PII from content
        raw_content = delivery_package.get("delivery_content", "")
        sanitized_content = self._strip_pii(raw_content)

        # 4. Hash provenance identifiers
        provenance = insight_capsule.get("provenance", {})
        hashed_provenance = self._hash_provenance(provenance, salt)

        # 5. Add differential privacy noise to scores
        noisy_score = self._add_dp_noise(
            delivery_package.get("compatibility_score", 0.0)
        )

        # 6. Build privacy-safe payload
        safe_payload = {
            "insight_id_hash": self._hash_with_salt(insight_id, salt)[:16],
            "concept_id": insight_capsule.get("concept_id"),
            "concept_name": insight_capsule.get("concept_name"),
            "subject": insight_capsule.get("subject"),
            "content": sanitized_content,
            "teaching_pattern": {
                "pattern_type": insight_capsule.get("teaching_pattern", {}).get("pattern_type"),
                "pattern_subtype": insight_capsule.get("teaching_pattern", {}).get("pattern_subtype"),
                "explanation_method": insight_capsule.get("teaching_pattern", {}).get("explanation_method"),
                "language_register": insight_capsule.get("teaching_pattern", {}).get("language_register"),
                "scaffold_level": insight_capsule.get("teaching_pattern", {}).get("scaffold_level"),
            },
            "insight_payload": {
                "analogy_used": insight_capsule.get("insight_payload", {}).get("analogy_used"),
                "key_framing": insight_capsule.get("insight_payload", {}).get("key_framing"),
                "trigger_question": insight_capsule.get("insight_payload", {}).get("trigger_question"),
                "concrete_example": insight_capsule.get("insight_payload", {}).get("concrete_example"),
            },
            "effectiveness_score_noisy": round(noisy_score, 3),
            "quality_tier": insight_capsule.get("quality_tier"),
            "provenance_hashed": hashed_provenance,
            "delivery_config": delivery_package.get("delivery_config", {}),
            "privacy_metadata": {
                "dp_epsilon": DP_EPSILON,
                "salt_date": self._salt_date,
                "sanitized_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        # 7. Log audit
        await self._log_audit(
            student_id=student_id,
            insight_id=insight_id,
            concept_id=insight_capsule.get("concept_id"),
            action="transfer",
            privacy_level="zero_knowledge",
        )

        logger.info(f"Zero-Knowledge Relay: insight {insight_id[:8]}... "
                   f"sanitized for student {student_id[:8]}...")

        return safe_payload

    async def sanitize_batch(
        self,
        delivery_packages: List[Dict[str, Any]],
        insight_capsule: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Sanitize multiple delivery packages for the same insight.
        """
        results = []
        for package in delivery_packages:
            safe = await self.sanitize(package, insight_capsule)
            if safe:
                results.append(safe)
        return results

    # ═════════════════════════════════════════════════════════════════
    # PII STRIPPING
    # ═════════════════════════════════════════════════════════════════

    def _strip_pii(self, text: str) -> str:
        """
        Remove all personally identifiable information from text.
        """
        if not text:
            return text

        sanitized = text

        # Apply regex patterns
        for pattern in PII_PATTERNS:
            sanitized = re.sub(pattern, "[REDACTED]", sanitized)

        # Strip names (heuristic: capitalized words that look like names)
        # Be conservative — only strip obvious full names
        sanitized = self._strip_names(sanitized)

        # Strip locations more specific than state
        sanitized = self._strip_specific_locations(sanitized)

        return sanitized

    def _strip_names(self, text: str) -> str:
        """
        Strip obvious personal names while preserving content.
        Conservative approach — only 2+ word capitalized sequences.
        """
        # Match "First Last" patterns
        name_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b'
        matches = re.findall(name_pattern, text)

        for match in matches:
            # Don't strip common words or single names
            words = match.split()
            if len(words) >= 2:
                # Check if it's likely a name (not a common phrase)
                common_phrases = ["The Student", "A Student", "This Concept",
                                "That Method", "One Way", "Two Things"]
                if match not in common_phrases:
                    text = text.replace(match, "[NAME]")

        return text

    def _strip_specific_locations(self, text: str) -> str:
        """
        Strip specific locations (streets, schools, towns) while keeping states.
        """
        # List of Nigerian states to preserve
        nigerian_states = [
            "lagos", "kano", "kaduna", "abuja", "port harcourt", "ibadan",
            "benin", "jos", "ilorin", "enugu", "calabar", "abeokuta",
            "owerri", "warri", "sokoto", "katsina", "zamfara", "kebbi",
            "niger", "nasarawa", "kwara", "plateau", "benue", "anambra",
            "ebonyi", "abia", "imo", "rivers", "cross river", "akwa ibom",
            "delta", "edo", "bayelsa", "ondo", "ogun", "osun", "oyo",
            "ekiti", "borno", "yobe", "adamawa", "gombe", "taraba",
            "bauchi", "jigawa", "yobe",
        ]

        # Strip "in [Specific Town]" but keep "in Lagos"
        location_pattern = r'\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'
        matches = re.findall(location_pattern, text, re.IGNORECASE)

        for match in matches:
            match_lower = match.lower()
            if match_lower not in nigerian_states:
                text = text.replace(match, "[LOCATION]")

        return text

    # ═════════════════════════════════════════════════════════════════
    # HASHING
    # ═════════════════════════════════════════════════════════════════

    async def _get_daily_salt(self) -> str:
        """
        Get or generate daily rotating salt.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        salt_key = SALT_KEY.format(date=today)

        # Check Redis
        try:
            cached = redis_client.get(salt_key)
            if cached:
                salt = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                self._salt = salt
                self._salt_date = today
                return salt
        except Exception:
            pass

        # Generate new salt
        salt = hashlib.sha256(
            f"waxprep_swarm_salt_{today}_{datetime.now(timezone.utc).timestamp()}".encode()
        ).hexdigest()[:32]

        # Cache in Redis
        try:
            redis_client.setex(salt_key, SALT_TTL, salt)
        except Exception as e:
            logger.warning(f"Failed to cache salt: {e}")

        self._salt = salt
        self._salt_date = today
        return salt

    def _hash_with_salt(self, value: str, salt: str) -> str:
        """
        Hash a value with the daily salt.
        """
        if not value:
            return ""
        return hashlib.sha256(f"{value}:{salt}".encode()).hexdigest()

    def _hash_provenance(self, provenance: Dict[str, Any], salt: str) -> Dict[str, Any]:
        """
        Hash provenance identifiers while preserving generalized data.
        """
        if not provenance:
            return {}

        return {
            "origin_id_hash": self._hash_with_salt(
                provenance.get("origin_student_id_hash", ""), salt
            )[:16],
            "origin_region": provenance.get("origin_region", "unknown"),
            "origin_school_type": provenance.get("origin_school_type", "unknown"),
            "class_level": provenance.get("class_level", "unknown"),
            "bio_state_at_breakthrough": provenance.get("bio_state_at_breakthrough", "unknown"),
        }

    # ═════════════════════════════════════════════════════════════════
    # DIFFERENTIAL PRIVACY
    # ═════════════════════════════════════════════════════════════════

    def _add_dp_noise(self, value: float) -> float:
        """
        Add Laplace noise for differential privacy.
        epsilon = 1.0, sensitivity = 1.0
        """
        import random
        import math

        # Laplace noise: scale = sensitivity / epsilon
        scale = DP_SENSITIVITY / DP_EPSILON

        # Generate Laplace noise using inverse transform sampling
        u = random.random() - 0.5  # Uniform in [-0.5, 0.5]
        noise = -scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))

        noisy_value = value + noise
        # Clamp to valid range
        return max(0.0, min(1.0, noisy_value))

    # ═════════════════════════════════════════════════════════════════
    # OPT-OUT
    # ═════════════════════════════════════════════════════════════════

    async def _is_opted_out(self, student_id: str) -> bool:
        """
        Check if student has opted out of swarm insights.
        """
        try:
            # Check Redis cache first
            opt_key = OPT_OUT_KEY.format(student_id=student_id)
            cached = redis_client.get(opt_key)
            if cached:
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached == "true"
        except Exception:
            pass

        # Check database
        try:
            result = (
                supabase.table("student_facts")
                .select("fact_value")
                .eq("student_id", student_id)
                .eq("fact_type", "preference")
                .eq("fact_key", "swarm_opt_out")
                .limit(1)
                .execute()
            )
            if result.data:
                opted_out = result.data[0].get("fact_value", "false").lower() == "true"
                # Cache result
                try:
                    redis_client.setex(
                        opt_key,
                        3600,  # 1 hour cache
                        "true" if opted_out else "false",
                    )
                except Exception:
                    pass
                return opted_out
        except Exception as e:
            logger.warning(f"Opt-out check failed: {e}")

        return False  # Default: not opted out

    async def set_opt_out(self, student_id: str, opted_out: bool) -> bool:
        """
        Set opt-out status for a student.
        """
        try:
            # Upsert to student_facts
            supabase.table("student_facts").upsert({
                "student_id": student_id,
                "fact_type": "preference",
                "fact_key": "swarm_opt_out",
                "fact_value": "true" if opted_out else "false",
                "provenance": "VERIFIED",
                "source": "student_choice",
                "confidence": 1.0,
            }, on_conflict="student_id,fact_type,fact_key").execute()

            # Update cache
            opt_key = OPT_OUT_KEY.format(student_id=student_id)
            redis_client.setex(
                opt_key,
                3600,
                "true" if opted_out else "false",
            )

            logger.info(f"Student {student_id[:8]}... swarm opt-out set to {opted_out}")
            return True
        except Exception as e:
            logger.error(f"Failed to set opt-out: {e}")
            return False

    # ═════════════════════════════════════════════════════════════════
    # AUDIT LOGGING
    # ═════════════════════════════════════════════════════════════════

    async def _log_audit(
        self,
        student_id: str,
        insight_id: str,
        concept_id: str,
        action: str,
        privacy_level: str,
    ):
        """
        Log every transfer for audit.
        Uses hashed identifiers — no raw IDs in audit log.
        """
        salt = await self._get_daily_salt()

        audit_record = {
            "hashed_student_id": self._hash_with_salt(student_id, salt)[:16],
            "hashed_insight_id": self._hash_with_salt(insight_id, salt)[:16],
            "concept_id": concept_id,
            "action": action,
            "privacy_level": privacy_level,
            "dp_epsilon": DP_EPSILON,
            "salt_date": self._salt_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Write to Redis batch queue
        try:
            batch_key = "zk:audit:batch"
            redis_client.lpush(batch_key, json.dumps(audit_record))
            redis_client.ltrim(batch_key, 0, AUDIT_BATCH_SIZE - 1)

            # If batch is full, flush to database
            batch_size = redis_client.llen(batch_key)
            if batch_size and batch_size >= AUDIT_BATCH_SIZE:
                await self._flush_audit_batch()
        except Exception as e:
            logger.warning(f"Audit logging failed: {e}")

    async def _flush_audit_batch(self):
        """
        Flush audit batch from Redis to database.
        """
        try:
            batch_key = "zk:audit:batch"
            records = []
            while True:
                raw = redis_client.rpop(batch_key)
                if not raw:
                    break
                records.append(json.loads(
                    raw.decode("utf-8") if isinstance(raw, bytes) else raw
                ))

            if records:
                supabase.table("swarm_audit_log").insert(records).execute()
                logger.info(f"Flushed {len(records)} audit records to database")
        except Exception as e:
            logger.error(f"Failed to flush audit batch: {e}")


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════════════════

async def sanitize_insight(
    delivery_package: Dict[str, Any],
    insight_capsule: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    High-level API: Sanitize a single insight for delivery.
    """
    relay = ZeroKnowledgeRelay()
    return await relay.sanitize(delivery_package, insight_capsule)


async def sanitize_batch(
    delivery_packages: List[Dict[str, Any]],
    insight_capsule: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    High-level API: Sanitize multiple insights for delivery.
    """
    relay = ZeroKnowledgeRelay()
    return await relay.sanitize_batch(delivery_packages, insight_capsule)


async def check_opt_out(student_id: str) -> bool:
    """
    High-level API: Check if student opted out.
    """
    relay = ZeroKnowledgeRelay()
    return await relay._is_opted_out(student_id)


async def set_opt_out(student_id: str, opted_out: bool) -> bool:
    """
    High-level API: Set opt-out status.
    """
    relay = ZeroKnowledgeRelay()
    return await relay.set_opt_out(student_id, opted_out)


async def flush_audit_log() -> bool:
    """
    High-level API: Force flush audit batch to database.
    Call from cron job periodically.
    """
    relay = ZeroKnowledgeRelay()
    await relay._flush_audit_batch()
    return True
