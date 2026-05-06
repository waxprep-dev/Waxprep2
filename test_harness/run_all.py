"""
WaxPrep v2 — Test Harness Entry Point
Runs all student scenarios against the AI and generates a report.

Usage:
    python -m test_harness.run_all
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_harness.scenario_runner import run_all_scenarios
from test_harness.report_builder import build_report, print_report


# Sample student data for testing
TEST_STUDENT = {
    "id": "test-student-001",
    "name": "Test Student",
    "class_level": "SS3",
    "target_exam": "JAMB",
    "subjects": ["Mathematics", "English", "Physics", "Chemistry"],
    "state": "Lagos",
    "language_preference": "english",
    "current_streak": 5,
}


async def main():
    print("=" * 70)
    print("WAXPREP TEST HARNESS")
    print("Running all student scenarios...")
    print("=" * 70)
    
    # Run all scenarios
    results = await run_all_scenarios(TEST_STUDENT)
    
    # Build report
    report = build_report(results)
    
    # Print report
    print_report(report)
    
    # Save to file
    report_path = os.path.join(os.path.dirname(__file__), "test_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\n📄 Full report saved to: {report_path}")
    
    # Return exit code based on results
    if report["failed"] > 0:
        print("\n❌ SOME TESTS FAILED. Check the report for details.")
        sys.exit(1)
    else:
        print("\n✅ ALL TESTS PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
