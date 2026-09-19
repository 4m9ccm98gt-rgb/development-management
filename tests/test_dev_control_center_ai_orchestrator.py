from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.ai_orchestrator.orchestrator import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_REVIEW_MODEL,
    OrchestratorError,
    _active_api_billing_env,
    _agent_env,
    _candidate_branch,
    _claude_implementation_command,
    _codex_review_command,
    _diff_for_review,
    _enforce_billing_guard,
    _extract_json_object,
    _parse_codex_review,
    _read_prompt,
    _review_fingerprint,
    _slugify,
    _write_external_result,
)


class ReviewParsingTests(unittest.TestCase):
    def test_extracts_json_from_code_fence(self):
        value = _extract_json_object(
            """```json
{"verdict":"approve","summary":"ok","findings":[]}
```"""
        )
        self.assertEqual(value["verdict"], "approve")

    def test_parses_codex_json_review(self):
        review = _parse_codex_review(
            json.dumps(
                {"verdict": "approve", "summary": "clean", "findings": []}
            )
        )
        self.assertTrue(review.approved)
        self.assertEqual(review.summary, "clean")

    def test_approve_with_findings_fails_closed(self):
        with self.assertRaises(OrchestratorError):
            _parse_codex_review(
                json.dumps(
                    {
                        "verdict": "approve",
                        "summary": "contradictory",
                        "findings": [{"severity": "HIGH"}],
                    }
                )
            )

    def test_invalid_verdict_fails_closed(self):
        with self.assertRaises(OrchestratorError):
            _parse_codex_review(
                json.dumps(
                    {"verdict": "maybe", "summary": "", "findings": []}
                )
            )


class RoleBoundaryTests(unittest.TestCase):
    @mock.patch(
        "tools.ai_orchestrator.orchestrator._resolved_command",
        side_effect=lambda name: [name],
    )
    def test_claude_is_implementation_agent_with_edit_permission(self, _mock):
        command = _claude_implementation_command()
        self.assertEqual(command[0], "claude")
        self.assertIn("--permission-mode", command)
        self.assertEqual(command[command.index("--permission-mode") + 1], "acceptEdits")
        self.assertNotIn("plan", command)

    @mock.patch(
        "tools.ai_orchestrator.orchestrator._resolved_command",
        side_effect=lambda name: [name],
    )
    def test_codex_is_read_only_astra_reviewer(self, _mock):
        command = _codex_review_command(DEFAULT_REVIEW_MODEL)
        self.assertEqual(command[0], "codex")
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("-m", command)
        self.assertEqual(command[command.index("-m") + 1], "gpt-6-astra")

    def test_default_round_limit_is_two(self):
        self.assertEqual(DEFAULT_MAX_ROUNDS, 2)

    def test_implementation_prompt_names_codex_review(self):
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
        self.assertIn("Codex/Astra review", text)

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


class BillingGuardTests(unittest.TestCase):
    def test_billing_guard_passes_without_api_env(self):
        clean = {key: value for key, value in os.environ.items() if key not in {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        }}
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertEqual(_active_api_billing_env(), ())
            self.assertEqual(_enforce_billing_guard(False), ())

    def test_billing_guard_blocks_api_key_by_default(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "secret"}, clear=True):
            with self.assertRaises(OrchestratorError):
                _enforce_billing_guard(False)

    def test_billing_guard_can_be_explicitly_overridden(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret"}, clear=True):
            self.assertEqual(
                _enforce_billing_guard(True),
                ("ANTHROPIC_API_KEY",),
            )


class ExternalResultTests(unittest.TestCase):
    def test_writes_machine_readable_result_for_dcc(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "result.json"
            payload = {
                "status": "candidate_ready",
                "candidate_sha": "a" * 40,
                "claude_calls": 1,
                "codex_calls": 1,
            }
            _write_external_result(str(target), payload)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
            self.assertFalse((Path(tmp) / "result.json.tmp").exists())


class SafetyContractTests(unittest.TestCase):
    def test_agent_env_disables_git_push_without_mutating_repo_config(self):
        env = _agent_env()
        self.assertEqual(env["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "disabled://ai-orchestrator")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_candidate_branch_is_unique_and_sanitized(self):
        branch = _candidate_branch("日本語 task / unsafe chars", "20260918-220000")
        self.assertTrue(branch.startswith("ai-candidate/20260918-220000-"))
        self.assertNotIn(" ", branch)
        self.assertNotIn("/", branch.removeprefix("ai-candidate/"))

    def test_slugify_has_safe_fallback(self):
        self.assertEqual(_slugify("日本語だけ"), "task")

    def test_review_fingerprint_is_stable_and_changes_with_diff(self):
        first = _review_fingerprint("diff A")
        self.assertEqual(first, _review_fingerprint("diff A"))
        self.assertNotEqual(first, _review_fingerprint("diff B"))


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
