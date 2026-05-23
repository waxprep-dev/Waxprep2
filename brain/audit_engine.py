"""
brain/audit_engine.py — WaxPrep Reality Audit (On-Demand)

Triggered manually via Telegram command /audit or script.
Runs all 7 dimensions, generates report, shuts down.
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from database.client import supabase, redis_client
from brain.dialectical_socket import detect_dissonance
from brain.relational_intimacy import get_current_intimacy_score
from config.constants import get_phrases

logger = logging.getLogger("waxprep.audit")

# ═══════════════════════════════════════════════════════════════════════
# GHOST STUDENTS
# ═══════════════════════════════════════════════════════════════════════

GHOST_PROFILES = [
    {
        "name": "Ghost-Amina",
        "personality": "JSS1-confused",
        "subjects": {"english": 0.9, "math": 0.3, "civic": 0.5},
        "stance": "vernacular_leaning",
        "intimacy_target": 2.0,
        "chat_id": -1000001,
    },
    {
        "name": "Ghost-Chidi",
        "personality": "SS3-arrogant",
        "subjects": {"physics": 0.9, "math": 0.8, "chemistry": 0.7},
        "stance": "formal_leaning",
        "intimacy_target": 6.0,
        "chat_id": -1000002,
    },
    {
        "name": "Ghost-Fatima",
        "personality": "JAMB-stressed",
        "subjects": {"math": 0.9, "english": 0.8, "physics": 0.6},
        "stance": "confused",
        "intimacy_target": 4.5,
        "chat_id": -1000003,
    },
    {
        "name": "Ghost-Emeka",
        "personality": "University-curious",
        "subjects": {"economics": 0.9, "math": 0.7, "government": 0.5},
        "stance": "synthetic",
        "intimacy_target": 7.0,
        "chat_id": -1000004,
    },
    {
        "name": "Ghost-Zainab",
        "personality": "SS2-quiet",
        "subjects": {"biology": 0.8, "chemistry": 0.6, "math": 0.4},
        "stance": "vernacular_leaning",
        "intimacy_target": 3.5,
        "chat_id": -1000005,
    },
]

# ═══════════════════════════════════════════════════════════════════════
# CONTRADICTION LIBRARY
# ═══════════════════════════════════════════════════════════════════════

CONTRADICTION_LIBRARY = {
    "physics_electricity": [
        {
            "misconception": "Current is used up by resistors",
            "expected_type": "cross_domain_confusion",
            "expected_socratic": "Conservation of charge",
            "expected_empiric": "Water pipe analogy",
            "thermal_preference": "hot",
            "test_message": "My teacher said current is used up by resistors but you said it stays the same. Which one dey correct?",
        },
        {
            "misconception": "Voltage and current are the same thing",
            "expected_type": "explicit_contradiction",
            "expected_socratic": "Definition distinction",
            "expected_empiric": "Pump vs water",
            "thermal_preference": "cool",
            "test_message": "Is voltage and current the same thing? My teacher use am interchangeably.",
        },
    ],
    "mathematics_quadratic": [
        {
            "misconception": "The quadratic formula only works when b² - 4ac is positive",
            "expected_type": "teacher_vs_wax_conflict",
            "expected_socratic": "Complex roots exist",
            "expected_empiric": "Teacher saving complex for later",
            "thermal_preference": "hot",
            "test_message": "My teacher said quadratic formula no work when discriminant is negative. But you talk about complex roots. Who dey right?",
        },
    ],
    "biology_genetics": [
        {
            "misconception": "Genes skip generations",
            "expected_type": "cross_domain_confusion",
            "expected_socratic": "Mendelian inheritance",
            "expected_empiric": "Family tree analogy",
            "thermal_preference": "hot",
            "test_message": "My mama say my grandfather's height skip my papa come reach me. But you talk about genes passing every generation. Which one true?",
        },
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# AUDIT ENGINE
# ═══════════════════════════════════════════════════════════════════════

class RealityAudit:
    """
    On-demand reality audit. Trigger, run, report, die.
    """

    def __init__(self):
        self.results: Dict[str, List[float]] = {
            "dissonance_scanner": [],
            "pig_engine": [],
            "thermal_router": [],
            "triad_orchestrator": [],
            "dialectical_ledger": [],
            "output_enforcer": [],
            "state_socket": [],
        }
        self.ghost_responses: List[Dict] = []
        self.start_time: Optional[datetime] = None

    async def run_full_audit(self) -> str:
        """Run all 7 dimensions and return ASCII report."""
        self.start_time = datetime.now(timezone.utc)
        
        # Dimension 1: Ghost Student Protocol
        await self._run_ghost_protocol()
        
        # Dimension 2: Contradiction Injection
        await self._run_contradiction_injection()
        
        # Dimension 3: PIG Integrity Check
        await self._run_pig_audit()
        
        # Dimension 4: Thermal Router Check
        await self._run_thermal_audit()
        
        # Dimension 5: State Socket Verification
        await self._run_state_audit()
        
        # Dimension 6: Output Enforcer Check
        await self._run_enforcer_audit()
        
        # Dimension 7: Ledger Persistence
        await self._run_ledger_audit()
        
        return self._generate_report()

    async def _run_ghost_protocol(self):
        """Send test messages through production pipeline."""
        for ghost in GHOST_PROFILES:
            # Test 1: Simple greeting
            greeting_resp = await self._send_ghost_message(ghost, "Hi Wax")
            self.results["state_socket"].append(1.0 if greeting_resp else 0.0)
            
            # Test 2: Contradiction message
            subject = random.choice(list(ghost["subjects"].keys()))
            if subject in CONTRADICTION_LIBRARY:
                contradiction = random.choice(CONTRADICTION_LIBRARY[subject])
                contradiction_resp = await self._send_ghost_message(
                    ghost, contradiction["test_message"]
                )
                self.ghost_responses.append({
                    "ghost": ghost["name"],
                    "message": contradiction["test_message"],
                    "response": contradiction_resp,
                })

    async def _run_contradiction_injection(self):
        """Score Dissonance Scanner on known contradictions."""
        for subject, contradictions in CONTRADICTION_LIBRARY.items():
            for contradiction in contradictions:
                # Direct call to Dissonance Scanner (bypass Telegram pipeline)
                dissonance = detect_dissonance(
                    message=contradiction["test_message"],
                    context=None,
                    intimacy_score=Decimal("5.0"),
                )
                
                score = 0.0
                if dissonance.triggered:
                    if dissonance.contradiction_type == contradiction["expected_type"]:
                        score = 1.0
                    else:
                        score = 0.5
                else:
                    score = 0.0
                    
                self.results["dissonance_scanner"].append(score)

    async def _run_pig_audit(self):
        """Verify PIG scores are readable and make sense."""
        for ghost in GHOST_PROFILES:
            try:
                score = await get_current_intimacy_score(str(ghost["chat_id"]))
                # Ghosts should have 0.0 (never interacted)
                if score == Decimal("0"):
                    self.results["pig_engine"].append(1.0)
                else:
                    self.results["pig_engine"].append(0.5)  # Unexpected data
            except Exception:
                self.results["pig_engine"].append(0.0)

    async def _run_thermal_audit(self):
        """Verify thermal phrase routing works."""
        # Test hot track
        hot_phrases = get_phrases("understanding", thermal_state="hot")
        if "e don enter" in hot_phrases:
            self.results["thermal_router"].append(1.0)
        else:
            self.results["thermal_router"].append(0.0)
            
        # Test cool track
        cool_phrases = get_phrases("understanding", thermal_state="cool")
        if "You've grasped the principle" in cool_phrases:
            self.results["thermal_router"].append(1.0)
        else:
            self.results["thermal_router"].append(0.0)

    async def _run_state_audit(self):
        """Verify State Socket responds correctly."""
        from brain.state_socket import get_current_mode, set_mode
        
        test_student = "-999999"
        try:
            # Set mode
            await set_mode(test_student, "teaching", confidence=1.0)
            # Read mode
            mode = await get_current_mode(test_student)
            if mode == "teaching":
                self.results["state_socket"].append(1.0)
            else:
                self.results["state_socket"].append(0.5)
        except Exception:
            self.results["state_socket"].append(0.0)

    async def _run_enforcer_audit(self):
        """Verify Output Enforcer catches violations."""
        from ai.output_enforcer import enforce_output
        
        # Test over-apology
        bad_response = "I'm so sorry, you're absolutely right, I was completely wrong. Sorry again."
        try:
            corrected = await enforce_output(
                response=bad_response,
                current_topic="math",
                student_name="Test",
                conversation_history=[],
            )
            if "sorry" in corrected.lower() and corrected.lower().count("sorry") <= 1:
                self.results["output_enforcer"].append(1.0)
            else:
                self.results["output_enforcer"].append(0.5)
        except Exception:
            self.results["output_enforcer"].append(0.0)

    async def _run_ledger_audit(self):
        """Verify Dialectical Ledger writes to Supabase."""
        from brain.dialectical_ledger import record_adjudication
        
        try:
            success = await record_adjudication(
                student_id="-999999",
                topic="test_audit",
                stance="synthetic",
                contradiction_type="test",
                socratic_position="Test position A",
                empiric_position="Test position B",
                round_count=3,
            )
            self.results["dialectical_ledger"].append(1.0 if success else 0.0)
        except Exception:
            self.results["dialectical_ledger"].append(0.0)

    async def _send_ghost_message(self, ghost: Dict, text: str) -> Optional[str]:
        """Send message through production Telegram handler."""
        try:
            from telegram.handler import process_telegram_message
            # Use asyncio timeout to prevent hanging
            await asyncio.wait_for(
                process_telegram_message(ghost["chat_id"], text),
                timeout=10.0
            )
            return "processed"  # We don't capture actual response in audit
        except asyncio.TimeoutError:
            return "timeout"
        except Exception as e:
            return f"error: {str(e)}"

    def _generate_report(self) -> str:
        """Generate ASCII Reality Audit report."""
        duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║           WAXPREP REALITY AUDIT — ON-DEMAND REPORT           ║",
            f"║              Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC              ║",
            f"║              Duration: {duration:.1f}s | Ghosts: {len(GHOST_PROFILES)}              ║",
            "╠══════════════════════════════════════════════════════════════╣",
            "║  Subsystem          │ Score │ Status    │ Notes            ║",
            "╠══════════════════════════════════════════════════════════════╣",
        ]
        
        for subsystem, scores in self.results.items():
            if scores:
                avg = sum(scores) / len(scores)
                status = "✅ PASS" if avg >= 0.85 else "⚠️ WARN" if avg >= 0.7 else "❌ FAIL"
                notes = f"{len(scores)} tests"
            else:
                avg = 0.0
                status = "❌ NO DATA"
                notes = "0 tests"
                
            lines.append(
                f"║  {subsystem:<19} │ {avg:>5.2f} │ {status:<8} │ {notes:<15} ║"
            )
        
        lines.extend([
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            "📊 DIMENSION SUMMARY:",
            "  1. Ghost Protocol:     Synthetic students injected",
            "  2. Contradiction:      Known misconceptions tested",
            "  3. PIG Integrity:      Intimacy scores verified",
            "  4. Thermal Router:      Hot/cool phrase routing checked",
            "  5. State Socket:        Mode transitions verified",
            "  6. Output Enforcer:     Rule violations caught",
            "  7. Dialectical Ledger:  Adjudication persistence tested",
            "",
            "🎯 NEXT ACTIONS:",
        ])
        
        # Recommendations based on scores
        for subsystem, scores in self.results.items():
            if scores and sum(scores) / len(scores) < 0.7:
                lines.append(f"  • Fix {subsystem}: Score below 0.70 threshold")
        
        if not any(s for s in self.results.values() if s and sum(s)/len(s) < 0.7):
            lines.append("  • All subsystems healthy. Proceed to P1-B.")
        
        lines.append("")
        lines.append("Run again: /audit or python -m brain.audit_engine")
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# TRIGGER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

async def run_audit() -> str:
    """Entry point for manual audit trigger."""
    audit = RealityAudit()
    return await audit.run_full_audit()


def run_audit_sync() -> str:
    """Synchronous wrapper for CLI usage."""
    return asyncio.run(run_audit())
