from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.ai_orchestrator.orchestrator import (
    OrchestratorError,
    _agent_env,
    _candidate_branch,
    _diff_for_review,
    _extract_json_object,
    _parse_review,
    _read_prompt,
    _slugify,
)


class ReviewParsingTests(unittest.TestCase):
    def test_extracts_json_from_code_fence(self):
        value = _extract_json_object(
            """```json
{"verdict":"approve","summary":"ok","findings":[]}
```"""
        )
        self.assertEqual(value["verdict"], "approve")

    def test_parses_claude_cli_json_wrapper(self):
        stdout = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": json.dumps(
                    {"verdict": "approve", "summary": "clean", "findings": []}
                ),
            }
        )
        review = _parse_review(stdout)
        self.assertTrue(review.approved)
        self.assertEqual(review.summary, "clean")

    def test_approve_with_findings_fails_closed(self):
        stdout = json.dumps(
            {
                "is_error": False,
                "result": json.dumps(
                    {
                        "verdict": "approve",
                        "summary": "contradictory",
                        "findings": [{"severity": "HIGH"}],
                    }
                ),
            }
        )
        with self.assertRaises(OrchestratorError):
            _parse_review(stdout)

    def test_invalid_verdict_fails_closed(self):
        stdout = json.dumps(
            {
                "is_error": False,
                "result": json.dumps(
                    {"verdict": "maybe", "summary": "", "findings": []}
                ),
            }
        )
        with self.assertRaises(OrchestratorError):
            _parse_review(stdout)


class SafetyContractTests(unittest.TestCase):
    def test_agent_env_disables_git_push_without_mutating_repo_config(self):
        env = _agent_env()
        self.assertEqual(env["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "disabled://ai-orchestrator")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_implementation_prompt_forbids_dangerous_boundaries(self):
        text = _read_prompt(
            "implement.md",
            {
                "TASK": "change demo behavior",
                "BASE_SHA": "a" * 40,
                "SOURCE_BRANCH": "main",
            },
        )
        self.assertIn("Do NOT commit", text)
        self.assertIn("Do NOT run BUILD", text)
        self.assertIn("Do NOT access or modify shared folders", text)
        self.assertIn("isolated Git worktree", text)

    def test_review_prompt_is_read_only_and_structured(self):
        text = _read_prompt(
            "review.md",
            {
                "TASK": "demo",
                "BASE_SHA": "a" * 40,
                "TEST_RESULTS": "PASS",
                "DIFF_STAT": "1 file changed",
                "DIFF": "diff --git a/a b/a",
            },
        )
        self.assertIn("Review only", text)
        self.assertIn("Do NOT edit/write files", text)
        self.assertIn('"verdict": "approve" | "changes_requested"', text)

    def test_candidate_branch_is_unique_and_sanitized(self):
        branch = _candidate_branch("日本語 task / unsafe chars", "20260918-220000")
        self.assertTrue(branch.startswith("ai-candidate/20260918-220000-"))
        self.assertNotIn(" ", branch)
        self.assertNotIn("/", branch.removeprefix("ai-candidate/"))

    def test_slugify_has_safe_fallback(self):
        self.assertEqual(_slugify("日本語だけ"), "task")


class DiffCoverageTests(unittest.TestCase):
    def test_staged_changes_are_included_in_review_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            target = root / "demo.txt"
            target.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "demo.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)

            target.write_text("after\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "demo.txt"], check=True)

            stat, diff = _diff_for_review(root)
            self.assertIn("demo.txt", stat)
            self.assertIn("+after", diff)
            self.assertIn("-before", diff)


if __name__ == "__main__":
    unittest.main()
