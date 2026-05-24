# Changes made:
# - Fixed Decimal serialization bug in record_adjudication(): changed "confidence": Decimal("0.92") to "confidence": float(Decimal("0.92"))
#   to allow json.dumps() to serialize the fact_value correctly.

"""
brain/dialectical_ledger.py — Dialectical Ledger

Persists student adjudications from dialectical debates.
Writes to:
  - student_facts (semantic memory, fast retrieval)
  - memory_mutations (audit trail, event sourcing)

Generates ASCII Wisdom Graph after every 3rd debate.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from database.client import supabase, redis_client

logger = logging.getLogger("waxprep.dialectical_ledger")

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

DEBATE_COUNTER_KEY = "dialectical_debate_count:{student_id}"
STANCE_TYPES = ["formal_leaning", "vernacular_leaning", "synthetic", "confused", "rejecting", "undetermined"]
WISDOM_GRAPH_THRESHOLD = 3  # Generate graph after every N debates


# ═══════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def record_adjudication(
    student_id: str,
    topic: str,
    stance: str,
    contradiction_type: str,
    socratic_position: str,
    empiric_position: str,
    student_position: Optional[str] = None,
    round_count: int = 0,
) -> bool:
    """
    Record a student's epistemic stance after a dialectical debate.

    Writes to student_facts (semantic) and memory_mutations (audit).
    Returns True if both writes succeed.
    """
    if stance not in STANCE_TYPES:
        logger.warning(f"Unknown stance '{stance}' for student {student_id}, defaulting to 'undetermined'")
        stance = "undetermined"

    now = datetime.now(timezone.utc).isoformat()

    # ── 1. Write to student_facts (semantic memory) ──
    fact_value = json.dumps({
        "topic": topic,
        "stance": stance,
        "contradiction_type": contradiction_type,
        "socratic_position": socratic_position[:200],  # Truncate for storage
        "empiric_position": empiric_position[:200],
        "student_position": (student_position or "")[:200],
        "round_count": round_count,
        "debated_at": now,
    })

    try:
        fact_result = (
            supabase.table("student_facts")
            .insert({
                "student_id": student_id,
                "fact_type": "dialectical_adjudication",
                "fact_key": f"debate_{topic}_{now}",
                "fact_value": fact_value,
                "provenance": "DEMONSTRATED",
                "source": "dialectical_engine",
                "confidence": float(Decimal("0.92")),  # Fixed: Decimal → float for JSON serialization
                "first_observed_at": now,
                "last_confirmed_at": now,
                "confirmation_count": 1,
            })
            .execute()
        )
        fact_success = bool(fact_result.data)
    except Exception as e:
        logger.error(f"Failed to write adjudication to student_facts: {e}")
        fact_success = False

    # ── 2. Write to memory_mutations (audit trail) ──
    try:
        mutation_result = (
            supabase.table("memory_mutations")
            .insert({
                "student_id": student_id,
                "mutation_type": "dialectical_adjudication",
                "table_name": "student_facts",
                "record_id": fact_result.data[0]["id"] if fact_success else None,
                "old_value": None,
                "new_value": fact_value,
                "reason": f"Student took stance '{stance}' on topic '{topic}' after {round_count} rounds",
                "source": "dialectical_ledger",
                "thermal_state": "warm",  # Recently relevant
            })
            .execute()
        )
        mutation_success = bool(mutation_result.data)
    except Exception as e:
        logger.error(f"Failed to write adjudication to memory_mutations: {e}")
        mutation_success = False

    # ── 3. Increment debate counter in Redis ──
    counter_key = DEBATE_COUNTER_KEY.format(student_id=student_id)
    try:
        new_count = redis_client.incr(counter_key)
        redis_client.expire(counter_key, 86400 * 30)  # 30-day TTL
    except Exception as e:
        logger.error(f"Failed to increment debate counter in Redis: {e}")
        new_count = 0

    # ── 4. Check if Wisdom Graph threshold reached ──
    if new_count >= WISDOM_GRAPH_THRESHOLD and new_count % WISDOM_GRAPH_THRESHOLD == 0:
        await _generate_and_store_wisdom_graph(student_id)

    return fact_success and mutation_success


async def get_debate_history(student_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Retrieve recent adjudications for a student.
    Used by the Triad Orchestrator to adapt debate style.
    """
    try:
        result = (
            supabase.table("student_facts")
            .select("*")
            .eq("student_id", student_id)
            .eq("fact_type", "dialectical_adjudication")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [_parse_fact(row) for row in (result.data or [])]
    except Exception as e:
        logger.error(f"Failed to fetch debate history for {student_id}: {e}")
        return []


async def get_stance_distribution(student_id: str) -> Dict[str, int]:
    """
    Count how many times a student has taken each stance.
    Returns dict like {'formal_leaning': 5, 'vernacular_leaning': 3, ...}
    """
    history = await get_debate_history(student_id, limit=100)
    distribution = {stance: 0 for stance in STANCE_TYPES}
    for h in history:
        stance = h.get("stance", "undetermined")
        if stance in distribution:
            distribution[stance] += 1
    return distribution


# ═══════════════════════════════════════════════════════════════════════
# WISDOM GRAPH GENERATOR
# ═══════════════════════════════════════════════════════════════════════

async def _generate_and_store_wisdom_graph(student_id: str) -> bool:
    """
    Generate an ASCII Wisdom Graph after every 3rd debate.
    Stores in student_facts as fact_type='wisdom_graph'.
    Also returns the graph text for immediate sending to student.
    """
    history = await get_debate_history(student_id, limit=50)
    if not history:
        return False

    distribution = await get_stance_distribution(student_id)
    total = sum(distribution.values())

    # Build ASCII bar chart
    bars = []
    max_bar_width = 20
    for stance in ["formal_leaning", "vernacular_leaning", "synthetic", "confused", "rejecting"]:
        count = distribution.get(stance, 0)
        bar_len = int((count / max(total, 1)) * max_bar_width)
        bar = "█" * bar_len + "░" * (max_bar_width - bar_len)
        label = stance.replace("_", " ").title()
        bars.append(f"{label:18} │{bar}│ {count}")

    # Detect pattern
    dominant = max(distribution, key=distribution.get)
    pattern_text = _describe_pattern(dominant, distribution, total)

    # Recent topics
    recent_topics = [h.get("topic", "unknown") for h in history[:5]]
    topics_line = " → ".join(reversed(recent_topics))

    graph = f"""📊 Your Thinking Pattern (after {total} debates)

{bars[0]}
{bars[1]}
{bars[2]}
{bars[3]}
{bars[4]}

{pattern_text}

Recent debates: {topics_line}

Keep debating — the graph updates every 3 debates."""

    now = datetime.now(timezone.utc).isoformat()

    try:
        result = (
            supabase.table("student_facts")
            .insert({
                "student_id": student_id,
                "fact_type": "wisdom_graph",
                "fact_key": f"wisdom_graph_{total}",
                "fact_value": graph,
                "provenance": "DERIVED",
                "source": "dialectical_ledger",
                "confidence": float(Decimal("0.85")),  # Also fixed for consistency
                "first_observed_at": now,
                "last_confirmed_at": now,
                "confirmation_count": 1,
            })
            .execute()
        )
        success = bool(result.data)
        if success:
            logger.info(f"Wisdom Graph stored for student {student_id} (debate #{total})")
    except Exception as e:
        logger.error(f"Failed to store Wisdom Graph for {student_id}: {e}")
        success = False

    return success


def _describe_pattern(dominant: str, distribution: Dict[str, int], total: int) -> str:
    """Generate a personalized insight about the student's thinking pattern."""
    if total < 3:
        return "Not enough debates yet to see a clear pattern. Keep going!"

    vernacular_pct = (distribution.get("vernacular_leaning", 0) / total) * 100
    formal_pct = (distribution.get("formal_leaning", 0) / total) * 100
    synthetic_pct = (distribution.get("synthetic", 0) / total) * 100

    if dominant == "vernacular_leaning":
        if vernacular_pct > 70:
            return "🔥 Strong home-voice pattern. You trust your gut and lived experience. This is powerful — but watch out for moments when the formal view holds tools you need."
        else:
            return "You lean toward the home voice. Your intuition is sharp. Try mixing in the school voice when you hit a wall."

    elif dominant == "formal_leaning":
        if formal_pct > 70:
            return "📚 Strong school-voice pattern. You trust structure and definitions. This is solid — but watch out for moments when the formal view feels too far from your reality."
        else:
            return "You lean toward the school voice. Your discipline is strong. Try the home voice when you need to feel a concept, not just know it."

    elif dominant == "synthetic":
        if synthetic_pct > 50:
            return "🌉 Bridge-builder! You naturally weave both voices together. This is rare and powerful — you see systems AND people."
        else:
            return "You sometimes mix both voices. This is growing. Keep looking for the seam where formal and intuitive meet."

    elif dominant == "confused":
        return "🤔 You often feel pulled between both sides. This is NOT weakness — it means you're holding real complexity. The confusion IS the thinking."

    elif dominant == "rejecting":
        return "✋ You often reject both positions. This is critical thinking in action. Ask yourself: what third position are you reaching for?"

    return "Your pattern is emerging. Keep debating to make it clear."


# ═══════════════════════════════════════════════════════════════════════
# PARSER HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _parse_fact(row: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a student_facts row into a clean adjudication dict."""
    try:
        value = json.loads(row.get("fact_value", "{}"))
    except (json.JSONDecodeError, TypeError):
        value = {}

    return {
        "id": row.get("id"),
        "topic": value.get("topic", "unknown"),
        "stance": value.get("stance", "undetermined"),
        "contradiction_type": value.get("contradiction_type", "unknown"),
        "socratic_position": value.get("socratic_position", ""),
        "empiric_position": value.get("empiric_position", ""),
        "student_position": value.get("student_position", ""),
        "round_count": value.get("round_count", 0),
        "debated_at": value.get("debated_at", row.get("created_at")),
    }


# ═══════════════════════════════════════════════════════════════════════
# HIGH-LEVEL API
# ═══════════════════════════════════════════════════════════════════════

async def finalize_debate(
    student_id: str,
    triad_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Call this when a debate ends (student takes clear stance or timeout).

    Records adjudication + checks for Wisdom Graph generation.
    Returns dict with success status and any graph to send.
    """
    stance = triad_state.get("student_epistemic_stance", "undetermined")
    topic = triad_state.get("topic", "unknown")
    contradiction_type = (
        triad_state.get("dissonance_result", {}).get("contradiction_type", "unknown")
        if triad_state.get("dissonance_result")
        else "unknown"
    )
    socratic_position = triad_state.get("socratic_position", "")
    empiric_position = triad_state.get("empiric_position", "")
    student_position = triad_state.get("student_position")
    round_count = triad_state.get("round_number", 0)

    success = await record_adjudication(
        student_id=student_id,
        topic=topic,
        stance=stance,
        contradiction_type=contradiction_type,
        socratic_position=socratic_position,
        empiric_position=empiric_position,
        student_position=student_position,
        round_count=round_count,
    )

    # Check if we just hit a threshold and should send a graph
    counter_key = DEBATE_COUNTER_KEY.format(student_id=student_id)
    try:
        current_count = int(redis_client.get(counter_key) or 0)
    except Exception:
        current_count = 0

    graph = None
    if current_count > 0 and current_count % WISDOM_GRAPH_THRESHOLD == 0:
        # Regenerate to get the text
        history = await get_debate_history(student_id, limit=50)
        if history:
            distribution = await get_stance_distribution(student_id)
            total = sum(distribution.values())
            bars = []
            max_bar_width = 20
            for stance in ["formal_leaning", "vernacular_leaning", "synthetic", "confused", "rejecting"]:
                count = distribution.get(stance, 0)
                bar_len = int((count / max(total, 1)) * max_bar_width)
                bar = "█" * bar_len + "░" * (max_bar_width - bar_len)
                label = stance.replace("_", " ").title()
                bars.append(f"{label:18} │{bar}│ {count}")

            dominant = max(distribution, key=distribution.get)
            pattern_text = _describe_pattern(dominant, distribution, total)
            recent_topics = [h.get("topic", "unknown") for h in history[:5]]
            topics_line = " → ".join(reversed(recent_topics))

            graph = f"""📊 Your Thinking Pattern (after {total} debates)

{bars[0]}
{bars[1]}
{bars[2]}
{bars[3]}
{bars[4]}

{pattern_text}

Recent debates: {topics_line}

Keep debating — the graph updates every 3 debates."""

    return {
        "success": success,
        "stance_recorded": stance,
        "debate_number": current_count,
        "wisdom_graph": graph,
    }
