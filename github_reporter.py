"""
WaxPrep Automated Test Harness — GitHub Reporter
Auto-creates GitHub issues for test failures.
Groups similar failures into single issues to avoid spam.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


class GitHubReporter:
    """
    Creates GitHub issues for test failures automatically.
    
    Groups similar failures:
    - All domain rejection failures → one issue
    - All vulnerability deflection failures → one issue
    - All Student Model loading failures → one issue
    
    This prevents creating 200 issues for the same root cause.
    """
    
    def __init__(self, config):
        self.config = config
        self.token = config.GITHUB_TOKEN
        self.repo = config.GITHUB_REPO
        self.enabled = bool(self.token and self.repo)
        
        if not self.enabled:
            print("⚠️  GitHub reporter disabled — no token or repo configured")
    
    def create_issues(
        self,
        results: List[Any],
        failure_categories: Dict[str, int],
        report_url: str = "",
    ) -> List[str]:
        """
        Create GitHub issues for test failures.
        
        Groups failures by root cause, creates one issue per group.
        
        Returns list of issue URLs created.
        """
        if not self.enabled:
            return []
        
        issues_created = []
        
        # Group failures by category
        grouped = self._group_failures(results)
        
        for group_key, failures in grouped.items():
            if not failures:
                continue
            
            # Build issue title and body
            title = self._build_issue_title(group_key, failures)
            body = self._build_issue_body(group_key, failures, report_url)
            labels = self._get_labels(group_key)
            
            # Create the issue
            issue_url = self._create_github_issue(title, body, labels)
            if issue_url:
                issues_created.append(issue_url)
        
        return issues_created
    
    # ═══════════════════════════════════════════
    # FAILURE GROUPING
    # ═══════════════════════════════════════════
    
    def _group_failures(self, results: List[Any]) -> Dict[str, List[dict]]:
        """Group similar failures together."""
        groups = {
            "critical_safety": [],
            "emotional_vulnerability": [],
            "emotional_gratitude": [],
            "emotional_rupture": [],
            "domain_rejection": [],
            "student_model_not_loading": [],
            "teaching_quality": [],
            "factual_accuracy": [],
            "other": [],
        }
        
        for result in results:
            if hasattr(result, 'passed') and result.passed:
                continue
            
            for failure in getattr(result, 'failures', []):
                rule = failure.get("rule", "")
                severity = failure.get("severity", "MEDIUM")
                
                # Group by root cause
                if severity == "CRITICAL" and failure.get("category") == "safety":
                    groups["critical_safety"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif rule in ("vulnerability_redirected", "self_deprecation_dismissed"):
                    groups["emotional_vulnerability"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif rule == "gratitude_dismissed":
                    groups["emotional_gratitude"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif rule in ("cold_return_after_rupture", "ultimatum_not_acknowledged"):
                    groups["emotional_rupture"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif rule in ("rejected_domain_used", "explicitly_rejected_word_used"):
                    groups["domain_rejection"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif rule == "student_model_ignored":
                    groups["student_model_not_loading"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif failure.get("category") == "teaching":
                    groups["teaching_quality"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                elif failure.get("category") == "factual":
                    groups["factual_accuracy"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
                else:
                    groups["other"].append({
                        "scenario": getattr(result, 'scenario_id', 'unknown'),
                        "failure": failure,
                    })
        
        return groups
    
    # ═══════════════════════════════════════════
    # ISSUE BUILDERS
    # ═══════════════════════════════════════════
    
    def _build_issue_title(self, group_key: str, failures: List[dict]) -> str:
        """Build a descriptive issue title."""
        count = len(failures)
        
        titles = {
            "critical_safety": f"🔴 CRITICAL: {count} safety violation(s) detected",
            "emotional_vulnerability": f"🟠 {count} vulnerability deflection failure(s)",
            "emotional_gratitude": f"🟠 {count} gratitude dismissal failure(s)",
            "emotional_rupture": f"🟠 {count} rupture/return handling failure(s)",
            "domain_rejection": f"🟡 {count} domain rejection violation(s) — Student Model not respected",
            "student_model_not_loading": f"🟡 Student Model preferences not reaching AI prompt ({count} failures)",
            "teaching_quality": f"🟢 {count} teaching quality issue(s)",
            "factual_accuracy": f"🔴 CRITICAL: {count} factual accuracy failure(s) — Wax taught wrong information",
            "other": f"❓ {count} uncategorized failure(s)",
        }
        
        return titles.get(group_key, f"Test Failure: {group_key} ({count} occurrences)")
    
    def _build_issue_body(self, group_key: str, failures: List[dict], report_url: str) -> str:
        """Build a detailed issue body with examples and fix suggestions."""
        body = f"## Summary\n\n"
        body += f"**{len(failures)} failure(s)** detected in latest automated test run.\n\n"
        
        if report_url:
            body += f"📄 [Full test report]({report_url})\n\n"
        
        # Add the most informative examples
        body += f"## Examples\n\n"
        for i, item in enumerate(failures[:5]):
            failure = item["failure"]
            scenario = item["scenario"]
            body += f"### Example {i+1}\n\n"
            body += f"- **Scenario:** `{scenario}`\n"
            body += f"- **Rule:** `{failure.get('rule', 'unknown')}`\n"
            body += f"- **What happened:** {failure.get('message', 'No details')}\n"
            body += f"- **Severity:** {failure.get('severity', 'MEDIUM')}\n"
            body += f"- **Expected:** {failure.get('expected', 'Not specified')}\n"
            body += "\n"
        
        if len(failures) > 5:
            body += f"*...and {len(failures) - 5} more similar failures.*\n\n"
        
        # Add fix suggestions based on category
        body += f"## Suggested Fix\n\n"
        body += self._get_fix_suggestion(group_key)
        
        # Footer
        body += f"\n---\n"
        body += f"*Auto-created by WaxPrep Automated Test Harness v2*\n"
        body += f"*Run: `python continuous_runner.py --tier deep`*\n"
        
        return body
    
    def _get_fix_suggestion(self, group_key: str) -> str:
        """Get a fix suggestion based on failure category."""
        suggestions = {
            "critical_safety": (
                "Check the safety module (`brain/safety.py`). Ensure crisis keywords "
                "are being detected and AI is being bypassed. Check that the message "
                "pipeline has safety checks BEFORE AI processing."
            ),
            "emotional_vulnerability": (
                "Update the AI prompt (`ai/prompts.py`) to add a rule: "
                "'When a student asks existential questions (am I smart, am I good enough), "
                "do NOT redirect to the lesson. Acknowledge the question, offer a specific "
                "observation about their effort, then ask if they want to continue.'"
            ),
            "domain_rejection": (
                "The Student Model (`brain/student_model.py`) is saving domain preferences "
                "but the AI prompt may not be receiving them. Check:\n"
                "1. Is `to_prompt_context()` generating the LEARNING PROFILE section?\n"
                "2. Is it being injected into `context_str` before the AI call?\n"
                "3. Is the system prompt's 'use Nigerian examples' rule overriding the "
                "LEARNING PROFILE's domain preferences?"
            ),
            "student_model_not_loading": (
                "The Student Model pipeline has a break. Debug steps:\n"
                "1. Log `to_prompt_context()` output before each AI call\n"
                "2. Check Redis: `HGETALL student_model:{test_student_id}`\n"
                "3. Check if model is loading before AI call in `_handle_ai_conversation`\n"
                "4. Verify `_pending_model_update` is being passed correctly"
            ),
            "teaching_quality": (
                "Minor improvements needed in teaching delivery. Check for:\n"
                "- Walls of text (should be under 400 characters)\n"
                "- Multiple questions per message (should be one)\n"
                "- Missing Nigerian examples in teaching responses"
            ),
            "factual_accuracy": (
                "CRITICAL: Wax taught incorrect facts. Update the golden answers file "
                "(`test_harness/golden_answers.py`) with the correct information and "
                "add the wrong answer to the `wrong_answers` list to catch future occurrences."
            ),
        }
        
        return suggestions.get(group_key, "Investigate the failure patterns in the test report and identify the root cause.")
    
    def _get_labels(self, group_key: str) -> List[str]:
        """Get GitHub labels for the issue."""
        label_map = {
            "critical_safety": ["bug", "critical", "safety"],
            "emotional_vulnerability": ["bug", "high-priority", "emotional-intelligence"],
            "emotional_gratitude": ["bug", "high-priority", "emotional-intelligence"],
            "emotional_rupture": ["bug", "high-priority", "emotional-intelligence"],
            "domain_rejection": ["bug", "medium-priority", "student-model"],
            "student_model_not_loading": ["bug", "high-priority", "student-model"],
            "teaching_quality": ["improvement", "low-priority", "teaching"],
            "factual_accuracy": ["bug", "critical", "accuracy"],
            "other": ["bug", "needs-triage"],
        }
        
        return label_map.get(group_key, ["bug"])
    
    # ═══════════════════════════════════════════
    # GITHUB API
    # ═══════════════════════════════════════════
    
    def _create_github_issue(
        self, title: str, body: str, labels: List[str]
    ) -> Optional[str]:
        """
        Create a GitHub issue using the REST API.
        
        Requires GITHUB_TOKEN environment variable.
        Uses httpx for HTTP calls (already in dependencies).
        Returns the issue URL, or None if creation failed.
        """
        if not self.token:
            print("   ⚠️  No GitHub token — issue not created")
            return None
        
        try:
            import httpx
            
            url = f"https://api.github.com/repos/{self.repo}/issues"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            payload = {
                "title": title,
                "body": body,
                "labels": labels,
            }
            
            # Use sync client since this runs in an async context
            with httpx.Client(timeout=30) as client:
                response = client.post(url, json=payload, headers=headers)
                
                if response.status_code == 201:
                    data = response.json()
                    issue_url = data.get("html_url", "")
                    print(f"   ✅ Created: {issue_url}")
                    return issue_url
                else:
                    print(f"   ❌ GitHub API error: {response.status_code} — {response.text[:200]}")
                    return None
                    
        except ImportError:
            print("   ⚠️  httpx not available — issue not created")
            return None
        except Exception as e:
            print(f"   ❌ Failed to create issue: {e}")
            return None
    
    def create_summary_issue(
        self,
        summary: dict,
        report_url: str,
    ) -> Optional[str]:
        """
        Create a single summary issue with the overall test results.
        Useful for quick visibility without creating issues for every failure.
        """
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        pass_rate = summary.get("pass_rate", "N/A")
        
        title = f"📊 Test Run Summary: {pass_rate} pass rate ({passed}/{total})"
        
        body = f"## Automated Test Run Complete\n\n"
        body += f"| Metric | Value |\n"
        body += f"|--------|-------|\n"
        body += f"| Pass Rate | {pass_rate} |\n"
        body += f"| Passed | {passed} |\n"
        body += f"| Failed | {failed} |\n"
        body += f"| Total | {total} |\n"
        body += f"| Duration | {summary.get('duration_minutes', 0):.1f} min |\n\n"
        
        if report_url:
            body += f"📄 [Full Report]({report_url})\n"
        
        body += f"\n*Auto-generated by WaxPrep Test Harness v2*\n"
        
        labels = ["test-report", "automated"]
        
        return self._create_github_issue(title, body, labels)
