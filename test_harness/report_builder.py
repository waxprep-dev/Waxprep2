"""
WaxPrep v2 — Report Builder
Generates scored, formatted reports from test results.
"""

from datetime import datetime
from test_harness.failure_detector import detect_failures
from test_harness.student_profiles import get_student_profile


def build_report(scenario_results: list) -> dict:
    """
    Build a comprehensive test report from scenario results.
    
    Returns:
        {
            "timestamp": str,
            "total_scenarios": int,
            "passed": int,
            "failed": int,
            "average_score": float,
            "scenarios": [...],
            "summary": str,
        }
    """
    scenarios = []
    passed = 0
    failed = 0
    total_score = 0
    
    for result in scenario_results:
        student_type = result["student_type"]
        profile = get_student_profile(student_type) if student_type != "stress_test" else {"name": "Stress Test"}
        
        # Detect failures
        analysis = detect_failures(
            messages_sent=result["messages_sent"],
            responses_received=result["responses_received"],
            student_type=student_type,
            student_profile=profile,
        )
        
        total_score += analysis["score"]
        
        if analysis["verdict"] == "PASS":
            passed += 1
        else:
            failed += 1
        
        scenarios.append({
            "student_type": student_type,
            "student_name": profile.get("name", "Unknown"),
            "verdict": analysis["verdict"],
            "score": analysis["score"],
            "failures": analysis["failures"],
            "warnings": analysis["warnings"],
            "passes": analysis["passes"],
            "sample_exchange": _get_sample_exchange(result.get("conversation_log", [])),
        })
    
    total = len(scenario_results)
    avg_score = total_score / total if total > 0 else 0
    
    # Build summary
    if failed == 0:
        summary = f"✅ ALL {total} SCENARIOS PASSED — Average Score: {avg_score:.0f}/100"
    else:
        summary = f"⚠️ {failed}/{total} SCENARIOS FAILED — Average Score: {avg_score:.0f}/100"
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total_scenarios": total,
        "passed": passed,
        "failed": failed,
        "average_score": round(avg_score, 1),
        "scenarios": scenarios,
        "summary": summary,
    }


def print_report(report: dict):
    """Print a formatted report to console."""
    print("\n" + "=" * 70)
    print("WAXPREP AI BEHAVIOR TEST REPORT")
    print("=" * 70)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Scenarios: {report['total_scenarios']}")
    print(f"Passed: {report['passed']} | Failed: {report['failed']}")
    print(f"Average Score: {report['average_score']}/100")
    print("=" * 70)
    
    for s in report["scenarios"]:
        emoji = "✅" if s["verdict"] == "PASS" else "❌"
        print(f"\n{emoji} {s['student_name']} ({s['student_type']}) — Score: {s['score']}/100")
        
        if s["failures"]:
            print("  🔴 Failures:")
            for f in s["failures"]:
                print(f"     • {f}")
        
        if s["warnings"]:
            print("  🟡 Warnings:")
            for w in s["warnings"]:
                print(f"     • {w}")
        
        if s["passes"]:
            print("  🟢 Passes:")
            for p in s["passes"]:
                print(f"     • {p}")
        
        if s.get("sample_exchange"):
            print("  💬 Sample:")
            for ex in s["sample_exchange"]:
                print(f"     Student: {ex['student'][:80]}")
                print(f"     Wax:     {ex['wax'][:80]}")
                print()
    
    print("\n" + "=" * 70)
    print(report["summary"])
    print("=" * 70)


def _get_sample_exchange(conversation_log: list, max_samples: int = 2) -> list:
    """Get a few sample exchanges from the conversation."""
    if not conversation_log:
        return []
    samples = []
    # Get first, middle, and last
    indices = [0]
    if len(conversation_log) > 2:
        indices.append(len(conversation_log) // 2)
    if len(conversation_log) > 1:
        indices.append(len(conversation_log) - 1)
    
    for i in indices:
        if i < len(conversation_log):
            samples.append(conversation_log[i])
    
    return samples[:max_samples]
