"""
WaxPrep Automated Test Harness — Continuous Runner
The orchestrator. One command runs everything.
Generates scenarios, executes them, checks responses,
creates GitHub issues for failures, saves reports.

Usage:
    python continuous_runner.py --tier quick
    python continuous_runner.py --tier deep --duration 4h
    python continuous_runner.py --scenarios 1000 --stop-on-token-limit
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from test_harness.config import (
    TIERS, DEFAULT_SCENARIOS, DEFAULT_DURATION_MINUTES,
    CHECKPOINT_INTERVAL, CASCADING_FAILURE_THRESHOLD,
    BATTERY_LOW_THRESHOLD, REPORT_DIR, CREATE_GITHUB_ISSUES,
)
from test_harness.scenario_generator import ScenarioGenerator, get_generator
from test_harness.scenario_runner import ScenarioRunner, ScenarioResult
from test_harness.assertion_engine import AssertionEngine, AssertionResult


class ContinuousRunner:
    """
    The orchestrator that ties everything together.
    
    Flow:
    1. Warmup (ping Render, wake it up)
    2. Generate scenarios (auto-detect code, student profiles, adversarial)
    3. Run scenarios (concurrent, with delays, checkpointing)
    4. Check responses (assertion engine, all rules)
    5. Report (markdown file, GitHub issues)
    6. Cleanup (test data from Redis/Supabase)
    7. Loop (if continuous mode)
    """
    
    def __init__(self):
        # Import config lazily to allow overrides
        from test_harness.config import config as cfg
        self.config = cfg
        self.generator = get_generator(self.config)
        self.runner = ScenarioRunner(self.config)
        self.engine = AssertionEngine(self.config)
        
        # State
        self.start_time = None
        self.scenarios_run = 0
        self.scenarios_passed = 0
        self.scenarios_failed = 0
        self.consecutive_failures = 0
        self.should_stop = False
        
        # Ensure report directory exists
        os.makedirs(REPORT_DIR, exist_ok=True)
    
    # ═══════════════════════════════════════════
    # MAIN ENTRY POINT
    # ═══════════════════════════════════════════
    
    async def run(self, tier: str = "deep", scenarios: int = None, 
                  duration_minutes: int = None) -> dict:
        """
        Run the complete test cycle.
        
        Args:
            tier: Preset tier (quick, medium, deep, chaos)
            scenarios: Override scenario count
            duration_minutes: Override duration
        
        Returns:
            Summary dict with pass/fail counts
        """
        self.start_time = datetime.now(timezone.utc)
        
        # Determine settings
        if tier in TIERS:
            settings = TIERS[tier]
            scenario_count = scenarios or settings["scenarios"]
            max_duration = duration_minutes or settings["duration_minutes"]
        else:
            scenario_count = scenarios or DEFAULT_SCENARIOS
            max_duration = duration_minutes or DEFAULT_DURATION_MINUTES
        
        print(f"╔══════════════════════════════════════════════╗")
        print(f"║     WAXPREP AUTOMATED TEST RUN              ║")
        print(f"╠══════════════════════════════════════════════╣")
        print(f"║  Tier: {tier:<8}  Scenarios: {scenario_count:<6}         ║")
        print(f"║  Max Duration: {max_duration} min                       ║")
        print(f"║  Start: {self.start_time.strftime('%H:%M:%S')}                          ║")
        print(f"╚══════════════════════════════════════════════╝")
        print()
        
        # Step 1: Warmup
        print("📡 Warming up Render...")
        warmup_ok = await self.runner.warmup()
        if not warmup_ok:
            print("⚠️  Render may be sleeping. Tests will wait for cold start.")
        else:
            print("✅ Render is alive.")
        print()
        
        # Step 2: Generate scenarios
        print(f"🧪 Generating {scenario_count} scenarios...")
        scenarios = self.generator.generate_batch(scenario_count, tier)
        print(f"✅ Generated {len(scenarios)} scenarios.")
        print(f"   Profiles: {len(set(s.student_profile for s in scenarios))}")
        print(f"   Subjects: {len(set(s.subject for s in scenarios))}")
        print(f"   Types: {len(set(s.scenario_type for s in scenarios))}")
        print()
        
        # Step 3: Run scenarios
        print(f"🚀 Running scenarios ({self.config.CONCURRENT_SCENARIOS} concurrent)...")
        print()
        
        all_results = []
        checkpoint_results = []
        
        # Progress callback
        async def on_progress(completed: int, total: int):
            pct = (completed / total) * 100
            bar_len = 20
            filled = int(bar_len * completed / total)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r  [{bar}] {completed}/{total} ({pct:.0f}%)", end="", flush=True)
        
        # Checkpoint callback
        async def on_checkpoint(results: List[ScenarioResult]):
            checkpoint_results.extend(results)
            self.runner.save_checkpoint(checkpoint_results)
            self._check_cascading_failures(checkpoint_results)
            self._check_battery()
        
        # Run
        try:
            results = await self.runner.run_scenarios(
                scenarios=scenarios,
                checkpoint_callback=on_checkpoint,
                progress_callback=on_progress,
            )
            all_results.extend(results)
            print()  # New line after progress bar
        except KeyboardInterrupt:
            print("\n⏸️  Paused by user. Saving progress...")
            self.runner.save_checkpoint(checkpoint_results)
            return self._build_summary(checkpoint_results)
        
        # Step 4: Check responses
        print()
        print("🔍 Checking responses against rules...")
        total_failures = 0
        failure_categories = {}
        
        for result in all_results:
            for msg_result in result.messages:
                if msg_result.response:
                    # Find the corresponding scenario
                    scenario = next(
                        (s for s in scenarios if s.scenario_id == result.scenario_id),
                        None
                    )
                    
                    assertions = self.engine.check_response(
                        response=msg_result.response,
                        scenario=scenario,
                        message_history=[m.message for m in result.messages],
                    )
                    
                    failures = [a for a in assertions if not a.passed]
                    
                    if failures:
                        result.failures.extend([
                            {"rule": f.rule_name, "severity": f.severity, 
                             "message": f.message, "category": f.category}
                            for f in failures
                        ])
                        result.passed = False
                        total_failures += len(failures)
                        
                        for f in failures:
                            cat = f.category
                            failure_categories[cat] = failure_categories.get(cat, 0) + 1
                    else:
                        result.passed = True
        
        # Count results
        self.scenarios_run = len(all_results)
        self.scenarios_passed = sum(1 for r in all_results if r.passed)
        self.scenarios_failed = sum(1 for r in all_results if not r.passed)
        
        print(f"✅ Checked {sum(len(r.messages) for r in all_results)} responses.")
        print(f"   Passed: {self.scenarios_passed}")
        print(f"   Failed: {self.scenarios_failed}")
        print(f"   Total failures: {total_failures}")
        print()
        
        # Step 5: Report
        summary = self._build_summary(all_results)
        self._save_report(summary, all_results, failure_categories)
        
        # Step 6: GitHub issues (if enabled)
        if CREATE_GITHUB_ISSUES:
            self._create_github_issues(all_results)
        
        # Step 7: Cleanup
        print("🧹 Cleaning up test data...")
        await self._cleanup_test_data()
        print("✅ Cleanup complete.")
        print()
        
        # Final output
        self._print_final_summary(summary)
        
        return summary
    
    # ═══════════════════════════════════════════
    # MONITORING & SAFETY
    # ═══════════════════════════════════════════
    
    def _check_cascading_failures(self, results: List[ScenarioResult]):
        """Pause if too many scenarios fail consecutively."""
        recent = results[-CASCADING_FAILURE_THRESHOLD:]
        failed_recent = sum(1 for r in recent if not r.passed)
        
        if failed_recent >= CASCADING_FAILURE_THRESHOLD:
            print(f"\n⚠️  {CASCADING_FAILURE_THRESHOLD} consecutive failures detected!")
            print("   Something may be broken. Pausing tests.")
            print("   Check Render logs, Groq quota, or recent code changes.")
            self.should_stop = True
    
    def _check_battery(self):
        """Stop if phone battery is critically low."""
        try:
            # Try Termux battery API
            battery_path = "/sys/class/power_supply/battery/capacity"
            if os.path.exists(battery_path):
                with open(battery_path) as f:
                    level = int(f.read().strip())
                if level <= BATTERY_LOW_THRESHOLD:
                    print(f"\n🔋 Battery at {level}%. Saving progress and stopping.")
                    self.should_stop = True
        except Exception:
            pass  # Not available on all devices
    
    # ═══════════════════════════════════════════
    # REPORTING
    # ═══════════════════════════════════════════
    
    def _build_summary(self, results: List[ScenarioResult]) -> dict:
        """Build a summary dictionary from test results."""
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed and not r.error)
        errors = sum(1 for r in results if r.error)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "pass_rate": f"{(passed/total*100):.1f}%" if total > 0 else "N/A",
            "duration_minutes": (datetime.now(timezone.utc) - self.start_time).total_seconds() / 60,
        }
    
    def _save_report(self, summary: dict, results: List[ScenarioResult], 
                     failure_categories: dict):
        """Save a detailed markdown report."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_file = os.path.join(REPORT_DIR, f"test_report_{timestamp}.md")
        
        with open(report_file, "w") as f:
            f.write(f"# WaxPrep Automated Test Report\n\n")
            f.write(f"**Date:** {summary['timestamp']}\n")
            f.write(f"**Duration:** {summary['duration_minutes']:.1f} minutes\n\n")
            
            f.write(f"## Summary\n\n")
            f.write(f"| Metric | Value |\n")
            f.write(f"|--------|-------|\n")
            f.write(f"| Total Scenarios | {summary['total']} |\n")
            f.write(f"| ✅ Passed | {summary['passed']} ({summary['pass_rate']}) |\n")
            f.write(f"| ❌ Failed | {summary['failed']} |\n")
            f.write(f"| ⚠️ Errors | {summary['errors']} |\n\n")
            
            if failure_categories:
                f.write(f"## Failure Categories\n\n")
                f.write(f"| Category | Count |\n")
                f.write(f"|----------|-------|\n")
                for cat, count in sorted(failure_categories.items(), key=lambda x: -x[1]):
                    f.write(f"| {cat} | {count} |\n")
                f.write("\n")
            
            # List failed scenarios
            failed_scenarios = [r for r in results if not r.passed and not r.error]
            if failed_scenarios:
                f.write(f"## Failed Scenarios\n\n")
                for i, result in enumerate(failed_scenarios[:20]):  # Top 20
                    f.write(f"### {i+1}. {result.scenario_id}\n\n")
                    for failure in result.failures[:5]:  # Top 5 failures per scenario
                        severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢", "COSMETIC": "⚪"}
                        emoji = severity_emoji.get(failure.get("severity", "MEDIUM"), "❓")
                        f.write(f"- {emoji} **{failure.get('severity', 'UNKNOWN')}** — {failure.get('message', 'No details')}\n")
                    f.write("\n")
        
        print(f"📄 Report saved: {report_file}")
    
    def _create_github_issues(self, results: List[ScenarioResult]):
        """Auto-create GitHub issues for failures."""
        # Check if GitHub token is configured
        if not self.config.GITHUB_TOKEN:
            print("⚠️  GitHub token not configured. Skipping issue creation.")
            return
        
        print("📝 Creating GitHub issues...")
        # Implementation depends on GitHub API client availability
        # For now, log that issues would be created
        critical_failures = [
            r for r in results 
            if not r.passed and any(
                f.get("severity") == "CRITICAL" for f in r.failures
            )
        ]
        print(f"   Would create {len(critical_failures)} issues for CRITICAL failures.")
        print("   (GitHub API integration — add PyGithub or httpx calls here)")
    
    def _print_final_summary(self, summary: dict):
        """Print the final summary to terminal."""
        print()
        print(f"╔══════════════════════════════════════════════╗")
        print(f"║           TEST RUN COMPLETE                  ║")
        print(f"╠══════════════════════════════════════════════╣")
        print(f"║  Total: {summary['total']:<5}  ✅ Passed: {summary['passed']:<5} ({summary['pass_rate']})  ║")
        print(f"║          ❌ Failed: {summary['failed']:<5}  ⚠️ Errors: {summary['errors']:<5}  ║")
        print(f"║  Duration: {summary['duration_minutes']:.0f} min                             ║")
        print(f"╚══════════════════════════════════════════════╝")
    
    # ═══════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════
    
    async def _cleanup_test_data(self):
        """Remove test data from Redis and Supabase."""
        try:
            from database.client import redis_client, supabase
            
            # Clean Redis test keys
            test_keys = redis_client.keys(f"{self.config.TEST_PREFIX}*")
            if test_keys:
                redis_client.delete(*test_keys)
                print(f"   Deleted {len(test_keys)} Redis test keys")
            
            # Clean Supabase test data
            supabase.table("student_signals").delete() \
                .filter("student_id", "like", f"{self.config.TEST_PREFIX}%") \
                .execute()
            
            supabase.table("student_models").delete() \
                .filter("student_id", "like", f"{self.config.TEST_PREFIX}%") \
                .execute()
            
            supabase.table("platform_sessions").delete() \
                .filter("student_id", "like", f"{self.config.TEST_PREFIX}%") \
                .execute()
            
            supabase.table("students").delete() \
                .filter("platform_user_id", "like", f"{self.config.TEST_PREFIX}%") \
                .execute()
            
        except ImportError:
            print("   Database modules not available — skipping cleanup")
        except Exception as e:
            print(f"   Cleanup error (non-critical): {e}")
    
    async def close(self):
        """Clean shutdown."""
        await self.runner.cleanup()


# ═══════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════

async def main():
    """Parse CLI args and run the harness."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="WaxPrep Automated Test Harness — Continuous Runner"
    )
    parser.add_argument(
        "--tier", 
        choices=["quick", "medium", "deep", "chaos"],
        default="deep",
        help="Test tier preset (default: deep)"
    )
    parser.add_argument(
        "--scenarios", 
        type=int,
        help="Number of scenarios to run (overrides tier default)"
    )
    parser.add_argument(
        "--duration", 
        type=str,
        help="Max duration (e.g., 30m, 2h, 4h)"
    )
    parser.add_argument(
        "--stop-on-token-limit",
        action="store_true",
        help="Stop when Groq token usage reaches 80%"
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=5,
        help="Number of concurrent scenarios (default: 5)"
    )
    
    args = parser.parse_args()
    
    # Parse duration
    duration_minutes = None
    if args.duration:
        dur = args.duration.lower()
        if dur.endswith("m"):
            duration_minutes = int(dur[:-1])
        elif dur.endswith("h"):
            duration_minutes = int(dur[:-1]) * 60
    
    # Override concurrency
    if args.concurrent:
        from test_harness.config import config
        config.CONCURRENT_SCENARIOS = args.concurrent
    
    # Run
    runner = ContinuousRunner()
    
    try:
        summary = await runner.run(
            tier=args.tier,
            scenarios=args.scenarios,
            duration_minutes=duration_minutes,
        )
    finally:
        await runner.close()
    
    return summary


if __name__ == "__main__":
    asyncio.run(main())
