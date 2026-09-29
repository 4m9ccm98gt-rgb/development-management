"""Credit-saving guards of the Orchestrator loop (fake providers, no paid AI):

* a Main AI cut off at its turn limit never reaches Tests / the Reviewer half-finished,
* Reviewer calls and tokens are budgeted per run and stop the run before the next paid call,
* the acceptance criteria are fixed before implementation and later findings cannot add new demands,
* provider token usage is parsed and accumulated.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.ai_orchestrator import providers as p
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import CommandResult
from tools.ai_orchestrator.orchestrator import read_project_purpose
from tools.ai_orchestrator.providers import AgentResult
from tools.ai_orchestrator.review import ReviewParseError, apply_fixed_criteria, criteria_from_acceptance, parse_criteria, parse_review

from ai_orchestrator_fakes import FAIL_REVIEW, review_json
from test_ai_orchestrator_engine import FAIL_A, PASS, EngineCase

CRITERIA_REPLY = json.dumps({"criteria": ["empty input is handled", "existing output is unchanged"], "summary": "ok"})


def cut_off(session="cca665c9-155d-485d-8d47-9f73d026860a") -> AgentResult:
    return AgentResult("claude", "main", False, error_kind=p.ERR_PROCESS, error_detail="Claude reached max-turns",
                       max_turns=True, session_id=session)


class TurnLimitTests(EngineCase):
    def test_cut_off_main_is_resumed_before_tests_or_review(self):
        self.build([PASS], [("+partial", cut_off()), ("+rest", "finished")])
        self.main.supports_resume = True
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["main_calls"], 2)
        self.assertEqual(self.host.test_calls, 1)          # Tests ran once, on the finished work
        self.assertEqual(self.record["review_calls"], 1)   # and only the final review used the Reviewer

    def test_main_that_is_always_cut_off_stops_without_tests_or_reviewer(self):
        self.build([PASS], [("+partial", cut_off())])
        self.main.supports_resume = True
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAIN_TURN_LIMIT")
        self.assertEqual(self.record["main_calls"], 1 + rs.Limits().max_main_resumes)
        self.assertEqual((self.host.test_calls, self.record["review_calls"]), (0, 0))

    def test_provider_that_cannot_resume_stops_immediately_on_a_partial_diff(self):
        self.build([PASS], [("+partial", cut_off())])
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAIN_TURN_LIMIT")
        self.assertEqual((self.record["main_calls"], self.host.test_calls, self.record["review_calls"]), (1, 0, 0))

    def test_cut_off_repair_is_not_sent_to_tests_either(self):
        self.build([FAIL_A, PASS], [("+impl", "implemented"), ("+half", cut_off())])
        self.main.supports_resume = True
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAIN_TURN_LIMIT")
        self.assertEqual(self.host.test_calls, 1)          # only the run before the cut-off repair
        self.assertEqual(self.record["review_calls"], 0)


class BudgetTests(EngineCase):
    def test_reviewer_call_budget_stops_before_a_repair_that_could_not_be_reviewed(self):
        self.build([PASS], [("+a", "impl"), ("+b", "fix")], [FAIL_REVIEW], limits=rs.Limits(max_review_calls=1))
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "REVIEW_BUDGET")
        self.assertEqual(self.record["main_calls"], 1)     # no repair was paid for
        self.assertEqual(self.record["review_calls"], 1)

    def test_reviewer_token_budget(self):
        reply = AgentResult("codex", "review", True, text=FAIL_REVIEW, tokens=600)
        self.build([PASS], [("+a", "impl"), ("+b", "fix")], [reply], limits=rs.Limits(max_review_tokens=500))
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "REVIEW_BUDGET")
        self.assertEqual(self.record["review_tokens"], 600)
        self.assertEqual(self.record["main_calls"], 1)

    def test_tokens_are_accumulated_per_role_and_zero_means_unlimited(self):
        main = AgentResult("claude", "main", True, text="impl", tokens=1000)
        review = AgentResult("codex", "review", True, text=review_json("PASS"), tokens=400)
        self.build([PASS], [("+a", main)], [review], limits=rs.Limits(max_review_tokens=0, max_main_tokens=0))
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual((self.record["main_tokens"], self.record["review_tokens"]), (1000, 400))

    def test_main_token_budget_stops_before_the_next_main_call(self):
        main = AgentResult("claude", "main", True, text="impl", tokens=150)
        self.build([FAIL_A, PASS], [("+a", main)], limits=rs.Limits(max_main_tokens=100))
        self.assertEqual(self.engine.run(), rs.NEEDS_HUMAN)
        self.assertEqual(self.record["final_result"]["code"], "MAIN_BUDGET")
        self.assertEqual(self.record["main_calls"], 1)

    def test_defaults_bound_the_reviewer(self):
        limits = rs.Limits()
        self.assertLessEqual(limits.max_review_rounds, 4)
        self.assertGreater(limits.max_review_calls, 0)
        self.assertGreater(limits.max_review_tokens, 0)


class CriteriaTests(EngineCase):
    def test_task_acceptance_section_is_the_fixed_criteria_and_costs_no_reviewer_call(self):
        self.build([PASS], [("+a", "impl")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["criteria_source"], "task")
        self.assertEqual(self.record["criteria"], [{"id": "C1", "text": "works"}])
        self.assertEqual(self.record["review_calls"], 1)   # the final review only
        self.assertIn("C1: works", self.main.main_prompts[0])
        self.assertIn("C1: works", self.reviewer.review_prompts[0])

    def _without_acceptance(self, review_script):
        self.build([PASS], [("+a", "impl")], review_script)
        self.engine.task = "Implement feature X."          # no acceptance section
        return self.engine

    def test_reviewer_drafts_criteria_once_before_implementation(self):
        self._without_acceptance([CRITERIA_REPLY, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["criteria_source"], "reviewer")
        self.assertEqual([c["id"] for c in self.record["criteria"]], ["C1", "C2"])
        self.assertTrue(self.reviewer.review_prompts[0].startswith("# CRITERIA"))
        self.assertIn("C2: existing output is unchanged", self.main.main_prompts[0])   # Main knew before writing code
        self.assertEqual(self.record["review_calls"], 2)

    def test_unusable_criteria_fall_back_without_looping_on_paid_calls(self):
        self._without_acceptance(["not json at all", "still not json", review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["criteria_source"], "task_fallback")
        self.assertEqual(self.record["review_calls"], 3)   # 2 criteria attempts (max) + final review

    def test_criteria_survive_repairs_unchanged(self):
        self.build([PASS], [("+a", "impl"), ("+b", "fix")], [FAIL_REVIEW, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertIn("C1: works", self.main.main_prompts[1])
        self.assertEqual(self.record["criteria"], [{"id": "C1", "text": "works"}])

    def test_late_wish_that_is_not_a_criterion_cannot_fail_the_run(self):
        wish = review_json("FAIL", "nice to have", instructions="rename the helper", findings=[
            {"severity": "major", "category": "design", "file": "app.py", "problem": "helper name is unclear",
             "instruction": "rename it"}])
        self.build([PASS], [("+a", "impl"), ("+b", "unneeded")], [wish])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["main_calls"], 1)     # no repair was triggered by the wish
        entry = self.record["review_history"][0]
        self.assertEqual((entry["verdict"], entry["downgraded"]), ("PASS", 1))
        self.assertEqual(entry["findings"][0]["severity"], "minor")

    def test_evidenced_defect_still_fails_without_a_criterion(self):
        bug = review_json("FAIL", "crash", instructions="guard None", findings=[
            {"severity": "blocker", "category": "bug", "file": "app.py", "problem": "None crashes",
             "evidence": "app.py:10 dereferences x", "instruction": "guard None"}])
        self.build([PASS], [("+a", "impl"), ("+b", "fix")], [bug, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertEqual(self.record["main_calls"], 2)

    def test_re_review_only_confirms_previous_findings(self):
        self.build([PASS], [("+a", "impl"), ("+b", "fix")], [FAIL_REVIEW, review_json("PASS")])
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        first, second = self.reviewer.review_prompts
        self.assertIn("FINAL REVIEW", first)
        self.assertIn("(none: this is the first review)", first)
        self.assertIn("RE-REVIEW", second)
        self.assertIn("empty input crashes", second)

    def test_failure_analysis_findings_are_not_downgraded(self):
        analysis = review_json("FAIL", "root cause", instructions="fix parse()", findings=[
            {"severity": "major", "category": "requirement_gap", "problem": "parse() drops the last row",
             "instruction": "fix parse()"}])
        self.build([FAIL_A, FAIL_A, PASS], [("+a", "impl"), ("+b", "1"), ("+c", "2")], [analysis, review_json("PASS")])
        self.engine.limits = rs.Limits(max_same_failure=99)
        self.engine.run()
        self.assertIn("parse() drops the last row", self.main.main_prompts[2])


class PurposeTests(EngineCase):
    def test_project_purpose_reaches_main_and_reviewer(self):
        self.build([PASS], [("+a", "impl")])
        self.host.project_purpose = lambda: "翌日準備業務を支援する"
        self.assertEqual(self.engine.run(), rs.COMPLETED)
        self.assertIn("翌日準備業務を支援する", self.main.main_prompts[0])
        self.assertIn("翌日準備業務を支援する", self.reviewer.review_prompts[0])

    def test_purpose_failure_never_breaks_a_run(self):
        self.build([PASS], [("+a", "impl")])

        def boom():
            raise RuntimeError("unreadable")
        self.host.project_purpose = boom
        self.assertEqual(self.engine.run(), rs.COMPLETED)

    def test_reads_the_purpose_section_of_a_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.md").write_text("# app\n\n## 概要\n\n## 目的\nDo the thing.\n\n## 現在の状態\nx\n", encoding="utf-8")
            self.assertEqual(read_project_purpose("app", projects_dir=Path(tmp)), "Do the thing.")
            self.assertEqual(read_project_purpose("missing", projects_dir=Path(tmp)), "")


class ReviewHelperTests(unittest.TestCase):
    def test_criteria_from_acceptance_bullets(self):
        block = "## 受入条件\n- 休館日が出ない\n- 2日分表示される\n1. 既存の表示は変わらない\n\n"
        self.assertEqual([c["text"] for c in criteria_from_acceptance(block)],
                         ["休館日が出ない", "2日分表示される", "既存の表示は変わらない"])
        self.assertEqual(criteria_from_acceptance("## 受入条件\n自由文だけ"), [{"id": "C1", "text": "自由文だけ"}])
        self.assertEqual(criteria_from_acceptance("## 受入条件\n"), [])

    def test_parse_criteria_is_strict(self):
        self.assertEqual(len(parse_criteria(CRITERIA_REPLY)), 2)
        for bad in ('{"criteria": []}', '{"criteria": "x"}', "no json"):
            with self.assertRaises(ReviewParseError):
                parse_criteria(bad)

    def test_bug_without_evidence_is_downgraded(self):
        verdict = parse_review(review_json("FAIL", instructions="fix", findings=[
            {"severity": "major", "category": "bug", "problem": "maybe broken", "instruction": "fix"}]), failure_mode=False)
        new, dropped = apply_fixed_criteria(verdict, [{"id": "C1", "text": "x"}], final=True)
        self.assertEqual((new.verdict, len(dropped)), ("PASS", 1))

    def test_cited_criterion_keeps_the_fail(self):
        verdict = parse_review(review_json("FAIL", instructions="fix", findings=[
            {"severity": "major", "criterion": "c2", "problem": "C2 not met", "instruction": "fix"}]), failure_mode=False)
        new, dropped = apply_fixed_criteria(verdict, [{"id": "C1", "text": "a"}, {"id": "C2", "text": "b"}], final=True)
        self.assertEqual((new.verdict, dropped), ("FAIL", []))

    def test_no_criteria_means_no_enforcement(self):
        verdict = parse_review(FAIL_REVIEW, failure_mode=False)
        self.assertEqual(apply_fixed_criteria(verdict, [], final=True), (verdict, []))


class TokenParsingTests(unittest.TestCase):
    def test_claude_call_tokens(self):
        stream = "\n".join(json.dumps(i) for i in [
            {"type": "system", "subtype": "init", "model": "m", "session_id": "cca665c9-155d-485d-8d47-9f73d026860a"},
            {"type": "result", "subtype": "success", "is_error": False, "result": "OK",
             "session_id": "cca665c9-155d-485d-8d47-9f73d026860a",
             "usage": {"input_tokens": 10, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 99999,
                       "output_tokens": 30}}]) + "\n"
        result = p.ClaudeProvider.parse("main", CommandResult(("claude",), 0, stream, ""))
        self.assertEqual(result.tokens, 240)               # cache reads are not counted

    def test_codex_call_tokens_sum_every_turn(self):
        stream = "\n".join(json.dumps(i) for i in [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}},
            {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 5}}]) + "\n"
        result = p.CodexProvider.parse("review", CommandResult(("codex",), 0, stream, ""))
        self.assertEqual(result.tokens, 175)


if __name__ == "__main__":
    unittest.main()
