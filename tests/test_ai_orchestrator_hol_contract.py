from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORCH_PATH = ROOT / "tools" / "ai_orchestrator" / "orchestrator.py"


def load_orchestrator():
    spec = importlib.util.spec_from_file_location("hol_orchestrator_contract", ORCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("orchestrator import spec failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HolOrchestratorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = load_orchestrator()

    def test_orchestrator_source_compiles(self):
        text = ORCH_PATH.read_text(encoding="utf-8")
        compile(text, str(ORCH_PATH), "exec")

    def test_default_is_30_round_hol(self):
        self.assertEqual(self.o.DEFAULT_MAX_ROUNDS, 30)
        parser = self.o.build_parser()
        args = parser.parse_args([
            "run",
            "--repo",
            ".",
            "--task",
            "demo",
            "--test",
            "python -m unittest",
        ])
        self.assertEqual(args.max_rounds, 30)
        self.assertEqual(args.test_timeout, 600)

    def test_review_parser_accepts_safe_approved_alias(self):
        review = self.o._review_from_value(
            {
                "verdict": "approved",
                "summary": "ok",
                "findings": [],
            },
            "test",
        )
        self.assertTrue(review.approved)

    def test_review_parser_accepts_changes_required_alias(self):
        review = self.o._review_from_value(
            {
                "verdict": "changes_required",
                "summary": "needs work",
                "findings": [{"problem": "x"}],
            },
            "test",
        )
        self.assertFalse(review.approved)
        self.assertEqual(len(review.findings), 1)

    def test_large_diff_is_split_instead_of_rejected(self):
        text = "".join(f"line-{i:05d} " + ("x" * 100) + "\n" for i in range(2000))
        bundles = self.o._split_review_diff(text, limit=10_000)
        self.assertGreater(len(bundles), 1)
        self.assertEqual("".join(bundles), text)
        self.assertTrue(all(len(bundle) <= 10_200 for bundle in bundles))

    def test_max_turns_is_recoverable_signal(self):
        result = self.o.CommandResult(
            ("claude",),
            1,
            '{"is_error":true,"subtype":"error_max_turns"}',
            "",
        )
        self.assertTrue(self.o._looks_like_max_turns(result))

    def test_explicit_expected_branch_refspec_exists(self):
        text = ORCH_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'f"+refs/heads/{branch}:refs/remotes/origin/{branch}"',
            text,
        )
        self.assertIn("_fetch_expected_origin_branch(root, branch)", text)

    def test_role_specific_prompts_exist(self):
        prompts = ROOT / "tools" / "ai_orchestrator" / "prompts"
        expected = {
            "diagnose_tests.md": "DIAGNOSIS-ONLY",
            "diagnose_tests_astra.md": "independent reviewer",
            "evaluate_review.md": "REVIEW_EVALUATION",
            "reconsider_review.md": "REVIEWER_RECONSIDERATION",
            "blocking_repair.md": "BLOCKING_REPAIR_REQUEST",
            "repair_tests.md": "TEST_FAILURE_REPAIR",
        }
        for name, marker in expected.items():
            with self.subTest(name=name):
                text = (prompts / name).read_text(encoding="utf-8")
                self.assertIn(marker, text)

    def test_dcc_explicitly_launches_30_round_hol(self):
        text = (
            ROOT / "scripts" / "dev_control_center" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"--max-rounds"', text)
        self.assertIn('"30"', text)
        self.assertIn('"--test-timeout"', text)
        self.assertIn("HOL最大30round", text)

    def test_live_test_progress_and_hang_watchdog_are_present(self):
        text = ORCH_PATH.read_text(encoding="utf-8")
        self.assertIn("[Tests] still running", text)
        self.assertIn("HANG/TIMEOUT", text)
        self.assertIn("_terminate_process_tree", text)


if __name__ == "__main__":
    unittest.main()
