"""Main / Reviewer loop: state machine, Tests-FAIL trigger, review loop, limits, provider faults.

Providers and the worktree are fakes; the run record / stage machine are real.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.engine import Engine
from tools.ai_orchestrator.providers import ERR_AUTH, ERR_PROCESS, ERR_QUOTA, ERR_TRANSIENT
from tools.ai_orchestrator.review import failure_fingerprint

from ai_orchestrator_fakes import (
    FAIL_REVIEW, FakeHost, ScriptedProvider, error_result, make_recorder, review_json,
)

FAIL_A = (False, "FAIL: test_a (m.T)\nAssertionError: 1 != 2\nRan 1 test in 0.1s\nFAILED (failures=1)")
FAIL_B = (False, "FAIL: test_b (m.T)\nAssertionError: 3 != 4\nRan 1 test in 0.2s\nFAILED (failures=1)")
FAIL_C = (False, "ERROR: test_c (m.T)\nKeyError: 'x'\nFAILED (errors=1)")
PASS = (True, "OK\nRan 3 tests")


class EngineCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def build(self, tests, main_script, review_script=(review_json("PASS"),), *, main="claude", reviewer="codex",
              limits=None):
        self.rec = make_recorder(self.dir, main=main, reviewer=reviewer, limits=limits)
        self.rec.transition(rs.PREFLIGHT)  # the worker does this before handing over to the engine
        self.host = FakeHost(tests)
        self.main = ScriptedProvider(main, self.host, main_script)
        self.reviewer = ScriptedProvider(reviewer, self.host, (), review_script)
        self.engine = Engine(self.rec, self.host, self.main, self.reviewer, sleep=lambda s: None)
        return self.engine

    @property
    def record(self):
        return self.rec.record

    def stages(self):
        return [item["stage"] for item in self.record["stage_history"] if item["stage"] != rs.PREFLIGHT]


class RoleSelectionTests(EngineCase):
    def test_claude_main_codex_reviewer(self):
        self.build([PASS], [("+impl", "implemented")], main="claude", reviewer="codex")
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual((self.record["main_agent"], self.record["review_agent"]), ("claude", "codex"))
        self.assertEqual((len(self.main.main_prompts), len(self.reviewer.review_prompts)), (1, 1))
        self.assertEqual(self.main.name, "claude")
        self.assertEqual(self.reviewer.name, "codex")

    def test_codex_main_claude_reviewer(self):
        self.build([PASS], [("+impl", "implemented")], main="codex", reviewer="claude")
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual((self.record["main_agent"], self.record["review_agent"]), ("codex", "claude"))
        self.assertEqual(self.main.name, "codex")
        self.assertEqual(self.reviewer.name, "claude")

    def test_engine_source_never_names_a_provider(self):
        text = (Path(__file__).resolve().parents[1] / "tools/ai_orchestrator/engine.py").read_text(encoding="utf-8")
        body = text.split('"""', 2)[2]
        for word in ("claude", "codex", "Claude", "Codex"):
            self.assertNotIn(word, body.replace("Claude / Codex", ""), word)


class TestsFailTriggerTests(EngineCase):
    def test_fail_1_is_repaired_by_main_alone(self):
        self.build([FAIL_A, PASS], [("+impl", "implemented"), ("+fix", "fixed it")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["tests_fail_count"], 1)
        self.assertEqual(self.record["main_calls"], 2)
        # the only Reviewer call is the mandatory final review
        self.assertEqual(self.record["review_calls"], 1)
        self.assertEqual([r["mode"] for r in self.record["review_history"]], ["final_review"])
        self.assertIn("Analyse and repair it yourself", self.main.main_prompts[1])

    def test_fail_2_brings_reviewer_before_the_next_repair(self):
        self.build([FAIL_A, FAIL_B, PASS], [("+a", "impl"), ("+b", "fix1"), ("+c", "fix2")],
                   [FAIL_REVIEW, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        modes = [(r["mode"], r["verdict"]) for r in self.record["review_history"]]
        self.assertEqual(modes, [("failure_analysis", "FAIL"), ("final_review", "PASS")])
        self.assertTrue(self.record["reviewer_engaged"])
        self.assertEqual(self.record["tests_fail_count"], 2)
        # order: main, tests(F), main, tests(F), reviewer, main, tests(P), reviewer
        self.assertEqual(self.record["main_calls"], 3)

    def test_reviewer_findings_are_handed_to_main_automatically(self):
        self.build([FAIL_A, FAIL_B, PASS], [("+a", "impl"), ("+b", "fix1"), ("+c", "fix2")],
                   [FAIL_REVIEW, review_json("PASS")])
        self.engine.run()
        third_main_prompt = self.main.main_prompts[2]
        self.assertIn("Handle the empty input in app.py", third_main_prompt)
        self.assertIn("empty input crashes", third_main_prompt)
        # the Reviewer saw the Tests failure history and the fingerprint
        self.assertIn("fp=", self.reviewer.review_prompts[0])
        self.assertIn("AssertionError", self.reviewer.review_prompts[0])

    def test_tests_are_rerun_after_every_repair(self):
        self.build([FAIL_A, FAIL_B, PASS], [("+a", "impl"), ("+b", "fix1"), ("+c", "fix2")],
                   [FAIL_REVIEW, review_json("PASS")])
        self.engine.run()
        stage_names = self.stages()
        for index, name in enumerate(stage_names):
            if name == rs.REPAIRING:
                self.assertEqual(stage_names[index + 1], rs.TESTING, stage_names)
        self.assertEqual(self.record["tests_run_count"], self.host.test_calls)
        self.assertEqual(self.host.test_calls, 3)


class FinalReviewTests(EngineCase):
    def test_tests_pass_always_gets_a_final_review(self):
        self.build([PASS], [("+a", "impl")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["review_calls"], 1)
        self.assertEqual(self.record["review_history"][0]["mode"], "final_review")
        self.assertIn("FINAL REVIEW", self.reviewer.review_prompts[0])

    def test_reviewer_fail_returns_to_repair_then_tests_then_review(self):
        self.build([PASS, PASS], [("+a", "impl"), ("+b", "review fix")], [FAIL_REVIEW, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.stages(), [rs.IMPLEMENTING, rs.TESTING, rs.REVIEWING, rs.REPAIRING, rs.TESTING,
                                         rs.REVIEWING, rs.FINALIZING, rs.COMPLETED])
        self.assertEqual(self.host.test_calls, 2)
        self.assertIn("Handle the empty input", self.main.main_prompts[1])

    def test_completed_requires_tests_review_and_safety_on_the_same_diff(self):
        self.build([PASS], [("+a", "impl")])
        self.engine.run()
        self.assertEqual(self.record["final_result"]["stage"], rs.COMPLETED)
        self.assertEqual(self.host.candidates, 1)
        self.assertEqual(self.record["candidate_sha"], "a" * 40)

    def test_reviewer_pass_with_blocking_findings_is_refused(self):
        bad = review_json("PASS", findings=[{"severity": "major", "problem": "x", "file": "a.py"}])
        self.build([PASS], [("+a", "impl")], [bad, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["review_calls"], 2)  # re-asked once, then a clean PASS

    def test_unparsable_reviewer_reply_ends_in_needs_human(self):
        self.build([PASS], [("+a", "impl")], ["not json at all"])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "REVIEW_UNPARSABLE")

    def test_reviewer_that_edits_the_worktree_is_a_safety_stop(self):
        self.build([PASS], [("+a", "impl")])
        self.reviewer.review_mutates = True
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "SAFETY_VIOLATION")
        self.assertEqual(self.host.candidates, 0)

    def test_pass_is_not_valid_while_tests_fail(self):
        self.build([FAIL_A, FAIL_B, PASS], [("+a", "impl"), ("+b", "f1"), ("+c", "f2")],
                   [review_json("PASS"), FAIL_REVIEW, review_json("PASS")])
        self.engine.run()
        self.assertEqual(self.record["review_history"][0]["verdict"], "FAIL")
        self.assertEqual(self.record["provider_errors"][0]["kind"], "protocol")

    def test_reviewer_needs_human_hands_back(self):
        self.build([PASS], [("+a", "impl")],
                   [review_json("NEEDS_HUMAN", needs_human_reason="TaskSpec contradicts itself")])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "REVIEWER_NEEDS_HUMAN")

    def test_no_changes_is_not_completion(self):
        self.build([PASS], [("", "nothing to do")])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "NO_CHANGES")


class LimitTests(EngineCase):
    def test_identical_failure_loop_stops(self):
        # every repair changes the diff but Tests keep failing the same way
        self.build([FAIL_A], [("+a", "impl"), ("+b", "f1"), ("+c", "f2"), ("+d", "f3"), ("+e", "f4")],
                   [FAIL_REVIEW])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "SAME_FAILURE_REPEATED")
        counts = self.record["failure_fingerprint_counts"]
        self.assertEqual(list(counts.values()), [3])
        self.assertLessEqual(self.host.test_calls, 3)

    def test_failure_fingerprint_ignores_durations_and_line_numbers(self):
        one = failure_fingerprint('File "a.py", line 10\nAssertionError: x\nRan 2 tests in 0.1s\nFAILED')
        two = failure_fingerprint('File "a.py", line 99\nAssertionError: x\nRan 2 tests in 7.3s\nFAILED')
        other = failure_fingerprint('File "a.py", line 99\nKeyError: y\nRan 2 tests in 7.3s\nFAILED')
        self.assertEqual(one, two)
        self.assertNotEqual(two[0], other[0])

    def test_max_repair_iterations_stops_safely(self):
        limits = rs.Limits(max_repair_iterations=2, max_same_failure=99, max_same_review=99)
        fails = [FAIL_A, FAIL_B, FAIL_C, (False, "FAIL: d"), (False, "FAIL: e")]
        self.build(fails, [("+1", "i"), ("+2", "a"), ("+3", "b"), ("+4", "c")], [FAIL_REVIEW], limits=limits)
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAX_REPAIR_ITERATIONS")
        self.assertEqual(self.record["repair_iteration"], 2)

    def test_repairs_that_change_nothing_stop_as_no_progress(self):
        limits = rs.Limits(max_same_failure=99)
        self.build([FAIL_A, FAIL_B, FAIL_C], [("+1", "i"), ("", "tried"), ("", "tried")], [FAIL_REVIEW], limits=limits)
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "NO_PROGRESS")

    def test_reviewer_and_main_looping_on_the_same_finding_stop(self):
        limits = rs.Limits(max_same_failure=99)
        self.build([PASS], [("+a", "i"), ("+b", "1"), ("+c", "2"), ("+d", "3")], [FAIL_REVIEW], limits=limits)
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "REVIEW_LOOP")
        self.assertEqual(self.record["review_calls"], 3)

    def test_max_review_rounds(self):
        limits = rs.Limits(max_review_rounds=1, max_same_review=99)
        self.build([PASS], [("+a", "i"), ("+b", "1")], [FAIL_REVIEW], limits=limits)
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAX_REVIEW_ROUNDS")

    def test_runtime_limit(self):
        ticks = iter(range(0, 10**6, 4000))
        self.build([PASS], [("+a", "impl")])
        self.engine._clock = lambda: next(ticks)
        self.engine._t0 = 0
        self.engine.limits = rs.Limits(max_runtime_minutes=1)
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAX_RUNTIME")


class ProviderFaultTests(EngineCase):
    def test_quota_is_never_retried_and_is_recorded(self):
        self.build([PASS], [("", error_result("claude", "main", ERR_QUOTA, "usage limit reached"))])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["main_calls"], 1)
        self.assertEqual(self.record["final_result"]["code"], "PROVIDER_QUOTA")
        self.assertEqual(self.record["quota_errors"][0]["provider"], "claude")

    def test_reviewer_quota_is_never_retried(self):
        self.build([PASS], [("+a", "impl")], [error_result("codex", "review", ERR_QUOTA, "usage limit")])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["review_calls"], 1)
        self.assertEqual(self.record["final_result"]["code"], "PROVIDER_QUOTA")

    def test_provider_process_error_is_saved_in_the_run(self):
        self.build([PASS], [("", error_result("claude", "main", ERR_PROCESS, "exited 3"))])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "PROVIDER_ERROR")
        error = self.record["provider_errors"][0]
        self.assertEqual((error["role"], error["kind"], error["detail"]), ("main", ERR_PROCESS, "exited 3"))

    def test_auth_error_needs_human_without_retry(self):
        self.build([PASS], [("", error_result("claude", "main", ERR_AUTH, "please login"))])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "PROVIDER_AUTH")
        self.assertEqual(self.record["main_calls"], 1)

    def test_transient_errors_are_retried_a_bounded_number_of_times(self):
        transient = error_result("claude", "main", ERR_TRANSIENT, "overloaded")
        self.build([PASS], [("", transient)])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["main_calls"], rs.Limits().max_provider_retries + 1)

    def test_transient_error_then_success_continues(self):
        transient = error_result("claude", "main", ERR_TRANSIENT, "another Claude Code process is refreshing")
        self.build([PASS], [("", transient), ("+a", "impl")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["main_calls"], 2)

    def test_blocked_task_is_handed_back(self):
        self.build([PASS], [("+a", "IMPLEMENTATION_STATUS: BLOCKED\nneed a decision")])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "TASK_BLOCKED")

    def test_worktree_safety_violation_stops(self):
        self.build([PASS], [("+a", "impl")])
        self.host.unsafe = True
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "SAFETY_VIOLATION")

    def test_usage_failure_never_stops_the_run(self):
        class Broken:
            name = "claude"

            def ingest(self, result):
                raise RuntimeError("usage backend down")

        self.build([PASS], [("+a", "impl")])
        self.engine.usage = {"claude": Broken()}
        self.assertEqual(self.engine.run(), rs.COMPLETED)


class RecordTests(EngineCase):
    def test_counters_history_and_fingerprints_are_recorded(self):
        self.build([FAIL_A, FAIL_B, PASS], [("+a", "impl"), ("+b", "fix1"), ("+c", "fix2")],
                   [FAIL_REVIEW, review_json("PASS")])
        self.engine.run()
        r = self.record
        self.assertEqual((r["main_calls"], r["review_calls"], r["tests_run_count"]), (3, 2, 3))
        self.assertEqual((r["tests_fail_count"], r["repair_iteration"]), (2, 2))
        self.assertEqual(len(r["failure_history"]), 2)
        self.assertEqual(len(r["repair_history"]), 2)
        self.assertEqual(len(r["review_history"]), 2)
        self.assertEqual(len(r["failure_fingerprint_counts"]), 2)
        self.assertIsNone(r["current_failure_fingerprint"])  # last Tests run passed
        self.assertTrue(r["finished_at"])
        self.assertEqual(r["final_result"]["stage"], rs.COMPLETED)
        self.assertTrue((self.rec.run_dir / "events.log").is_file())

    def test_illegal_stage_transition_is_rejected(self):
        rec = make_recorder(self.dir)
        with self.assertRaises(Exception):
            rec.transition(rs.COMPLETED)
        rec.transition(rs.PREFLIGHT)
        rec.transition(rs.IMPLEMENTING)
        with self.assertRaises(Exception):
            rec.transition(rs.REVIEWING)

    def test_terminal_stages_have_no_exit(self):
        for stage in rs.TERMINAL_STAGES:
            self.assertEqual(rs.ALLOWED_TRANSITIONS[stage], frozenset())

    def test_safe_stop_during_a_run(self):
        self.build([PASS], [("+a", "impl")])
        self.rec.stop_event.set()
        self.assertEqual(self.engine.run(), rs.STOPPED)
        self.assertTrue(self.record["stopped_by_user"])
        self.assertEqual(self.record["final_result"]["code"], "USER_SAFETY_STOP")
        self.assertEqual(self.host.candidates, 0)


if __name__ == "__main__":
    unittest.main()
