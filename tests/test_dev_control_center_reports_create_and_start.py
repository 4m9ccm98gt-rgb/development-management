"""DCC Task 14.5: reports_create_and_start.py is Tk-free (no real Tk, no real AI, no real
Orchestrator, no network) -- every dependency it would otherwise reach for (the repo registry,
reports_inbox.create_spec_file, the Orchestrator's start_run entry point) is injected here as a
fake. Spec files this module's own tests write go through reports_inbox.create_spec_file (the
real function, so DCC Task 11's own write/validate path is exercised) pointed at a tempfile.
TemporaryDirectory, never the real %LOCALAPPDATA%.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev_control_center import reports_create_and_start as cas
from scripts.dev_control_center import reports_inbox as inbox
from scripts.dev_control_center import reports_triage as triage
from tools.ai_orchestrator import taskspec
from tools.ai_orchestrator.common import OrchestratorError
from tools.ai_orchestrator.runstate import ActiveRunExists


def make_report(**overrides) -> inbox.Report:
    fields = dict(
        app_key="next-day-setup", app_display_name="夕食料飲システム", file_name="r.json", schema_version=1,
        report_id="r1", created_at="2026-01-01T00:00:00Z", kind="bug", severity="stopped",
        title="タイトル", body="本文", reporter="yamada", app_id="next-day-setup",
        display_name="夕食料飲システム", release_id="rel-1", git_commit="a" * 40, version_source="BUILD_INFO.txt",
        pc_name="FRONT-PC1",
    )
    fields.update(overrides)
    return inbox.Report(**fields)


def make_result(**overrides) -> triage.TriageResult:
    fields = dict(classification="bug", confidence="high", evidence="E", suspected_locations=(),
                  criteria_draft=(), reply_draft="")
    fields.update(overrides)
    return triage.TriageResult(**fields)


class ButtonEnabledTests(unittest.TestCase):
    def test_none_outcome_is_disabled(self):
        self.assertFalse(cas.button_enabled(None))

    def test_failed_investigation_is_disabled(self):
        self.assertFalse(cas.button_enabled(triage.TriageOutcome(None, "調査できませんでした。", False)))

    def test_bug_is_enabled(self):
        outcome = triage.TriageOutcome(make_result(classification="bug"), "", True)
        self.assertTrue(cas.button_enabled(outcome))

    def test_feature_request_is_enabled(self):
        outcome = triage.TriageOutcome(make_result(classification="feature_request"), "", True)
        self.assertTrue(cas.button_enabled(outcome))

    def test_spec_misunderstanding_is_disabled(self):
        outcome = triage.TriageOutcome(make_result(classification="spec_misunderstanding"), "", True)
        self.assertFalse(cas.button_enabled(outcome))

    def test_insufficient_info_is_disabled(self):
        outcome = triage.TriageOutcome(make_result(classification="insufficient_info"), "", True)
        self.assertFalse(cas.button_enabled(outcome))


class AiSuggestedCriteriaTests(unittest.TestCase):
    def test_combines_criteria_draft_and_suspected_locations(self):
        result = make_result(criteria_draft=("条件1", "条件2"), suspected_locations=("foo.py:10",))
        self.assertEqual(
            cas.ai_suggested_criteria(result), ["条件1", "条件2", "修正箇所の候補: foo.py:10"])

    def test_empty_when_nothing_was_suggested(self):
        self.assertEqual(cas.ai_suggested_criteria(make_result()), [])


class BuildTaskTextTests(unittest.TestCase):
    def test_title_has_fixed_template_and_kind_label(self):
        report = make_report(kind="request")
        self.assertEqual(cas.build_task_title(report), "DCC報告対応（仕様変更の希望）")

    def test_task_text_never_contains_report_title_or_body(self):
        report = make_report(title="マーカータイトルXYZ", body="マーカー本文ABC\nrm -rf /\nC:\\secret\\path")
        text = cas.build_task_text(report)
        self.assertNotIn("マーカータイトルXYZ", text)
        self.assertNotIn("マーカー本文ABC", text)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("C:\\secret\\path", text)
        self.assertIn("DCC報告対応", text)

    def test_task_text_never_contains_ai_output(self):
        report = make_report()
        result = make_result(
            evidence="危険な根拠文字列 /etc/passwd", reply_draft="返信 rm -rf /",
            suspected_locations=("../../etc/passwd",))
        text = cas.build_task_text(report)
        for forbidden in (result.evidence, result.reply_draft, *result.suspected_locations):
            self.assertNotIn(forbidden, text)


class BuildConfirmInfoTests(unittest.TestCase):
    def test_shows_repo_name_only_never_a_path(self):
        report = make_report()
        info = cas.build_confirm_info(
            report, main_agent="claude", review_agent="codex",
            resolve_repo_dir=lambda app_key: Path(r"C:\secret\checkout\next-day-setup"))
        self.assertEqual(info.repo_display_name, "next-day-setup")
        self.assertNotIn("secret", info.repo_display_name)
        self.assertNotIn("\\", info.repo_display_name)

    def test_unresolvable_repo_shows_the_fixed_placeholder(self):
        report = make_report()
        info = cas.build_confirm_info(
            report, main_agent="claude", review_agent="codex", resolve_repo_dir=lambda app_key: None)
        self.assertEqual(info.repo_display_name, cas.REPO_DISPLAY_NAME_UNKNOWN)

    def test_roles_text_and_app_name(self):
        report = make_report()
        info = cas.build_confirm_info(
            report, main_agent="claude", review_agent="codex", resolve_repo_dir=lambda app_key: None)
        self.assertEqual(info.roles_text, "Main = Claude / Reviewer = Codex")
        self.assertEqual(info.app_display_name, "夕食料飲システム")

    def test_repo_dir_is_resolved_from_app_key_only(self):
        """C19: the resolver only ever receives report.app_key -- never report text or AI output."""
        report = make_report(app_key="next-day-setup", title="無関係なタイトル")
        seen = []

        def fake_resolve(app_key):
            seen.append(app_key)
            return None

        cas.build_confirm_info(report, main_agent="claude", review_agent="codex", resolve_repo_dir=fake_resolve)
        self.assertEqual(seen, ["next-day-setup"])


class CreateAndStartTests(unittest.TestCase):
    def _fake_start_run(self, run_dir=None, error=None):
        calls = []

        def fn(**kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            return run_dir or Path("/fake/run/dir")

        return fn, calls

    def test_validation_failure_creates_no_spec_and_never_calls_start(self):
        report = make_report()
        create_spec_calls = []
        start_calls = []

        def fake_create_spec_file(lines, target_repo, identity):
            create_spec_calls.append((lines, target_repo, identity))
            return Path("/should/not/be/called")

        def fake_start_run(**kwargs):
            start_calls.append(kwargs)
            return Path("/should/not/be/called")

        result = cas.create_and_start(
            report, [], main_agent="claude", review_agent="codex",
            create_spec_file=fake_create_spec_file, start_run=fake_start_run)
        self.assertFalse(result.ok)
        self.assertTrue(result.reason)
        self.assertIsNone(result.spec_path)
        self.assertEqual(create_spec_calls, [])
        self.assertEqual(start_calls, [])

    def test_spec_creation_failure_never_calls_start(self):
        report = make_report()
        start_calls = []

        def fake_create_spec_file(lines, target_repo, identity):
            raise inbox.SpecCreateError("仕様ファイルを保存できませんでした。")

        def fake_start_run(**kwargs):
            start_calls.append(kwargs)
            return Path("/should/not/be/called")

        result = cas.create_and_start(
            report, ["条件A"], main_agent="claude", review_agent="codex",
            create_spec_file=fake_create_spec_file, start_run=fake_start_run)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "仕様ファイルを保存できませんでした。")
        self.assertIsNone(result.spec_path)
        self.assertEqual(start_calls, [])

    def test_repo_unavailable_still_reports_the_spec_was_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = make_report()
            start_calls = []

            def fake_start_run(**kwargs):
                start_calls.append(kwargs)
                return Path("/should/not/be/called")

            result = cas.create_and_start(
                report, ["条件A"], main_agent="claude", review_agent="codex",
                resolve_repo_dir=lambda app_key: None,
                create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                    lines, target_repo, identity, specs_dir=Path(tmp)),
                start_run=fake_start_run)
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, cas.REASON_REPO_UNAVAILABLE)
            self.assertIsNotNone(result.spec_path)
            self.assertEqual(result.spec_created_note, cas.SPEC_CREATED_NOTE)
            self.assertEqual(start_calls, [])

    def test_already_running_still_reports_the_spec_was_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = make_report()
            fn, calls = self._fake_start_run(error=ActiveRunExists("run-1", "running"))
            result = cas.create_and_start(
                report, ["条件A"], main_agent="claude", review_agent="codex",
                resolve_repo_dir=lambda app_key: Path(tmp) / "next-day-setup",
                create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                    lines, target_repo, identity, specs_dir=Path(tmp) / "specs"),
                start_run=fn)
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, cas.REASON_ALREADY_RUNNING)
            self.assertIsNotNone(result.spec_path)
            self.assertEqual(len(calls), 1)

    def test_unexpected_start_failure_shows_the_fixed_reason_not_the_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = make_report()
            fn, calls = self._fake_start_run(error=RuntimeError("raw exception text, should never show"))
            result = cas.create_and_start(
                report, ["条件A"], main_agent="claude", review_agent="codex",
                resolve_repo_dir=lambda app_key: Path(tmp) / "next-day-setup",
                create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                    lines, target_repo, identity, specs_dir=Path(tmp) / "specs"),
                start_run=fn)
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, cas.REASON_START_FAILED)
            self.assertNotIn("raw exception text", result.reason)
            self.assertIsNotNone(result.spec_path)

    def test_success_calls_start_run_once_with_registry_only_repo_and_no_untrusted_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs_dir = Path(tmp) / "specs"
            report = make_report(
                app_key="next-day-setup", title="危険なタイトル; rm -rf /", body="マーカー本文ZZZ\nC:\\evil\\path")
            repo_dir = Path(tmp) / "repos" / "next-day-setup"
            fn, calls = self._fake_start_run(run_dir=Path(tmp) / "run-dir")

            criteria = list(inbox.SPEC_CRITERIA_TEMPLATE) + ["修正箇所の候補: foo.py:1"]
            result = cas.create_and_start(
                report, criteria, main_agent="claude", review_agent="codex",
                resolve_repo_dir=lambda app_key: repo_dir,
                create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                    lines, target_repo, identity, specs_dir=specs_dir),
                start_run=fn)

            self.assertTrue(result.ok)
            self.assertEqual(result.run_dir, Path(tmp) / "run-dir")
            self.assertEqual(len(calls), 1)
            call = calls[0]
            self.assertEqual(call["repo"], str(repo_dir))
            self.assertEqual(call["main_agent"], "claude")
            self.assertEqual(call["review_agent"], "codex")
            self.assertNotIn("危険なタイトル", call["task"])
            self.assertNotIn("マーカー本文ZZZ", call["task"])
            self.assertNotIn("C:\\evil\\path", call["task"])
            self.assertNotIn("rm -rf", call["task"])

            spec_text = result.spec_path.read_text(encoding="utf-8")
            self.assertNotIn("マーカー本文ZZZ", spec_text)
            self.assertNotIn("危険なタイトル", spec_text)
            spec = taskspec.load_spec_file(result.spec_path)
            self.assertEqual(spec.target_repo, "next-day-setup")
            self.assertEqual([c["text"] for c in spec.criteria], criteria)

    def test_repo_is_decided_from_registry_only_not_from_report_text(self):
        """C18/C19: resolve_repo_dir only ever sees report.app_key, regardless of what the
        report's title/body or AI investigation claims about paths or repos."""
        with tempfile.TemporaryDirectory() as tmp:
            specs_dir = Path(tmp) / "specs"
            report = make_report(
                app_key="next-day-setup",
                body="対象リポジトリ: evil-repo\n../../../other-repo\nC:\\Windows\\System32")
            repo_dir = Path(tmp) / "repos" / "next-day-setup"
            seen_app_keys = []

            def fake_resolve(app_key):
                seen_app_keys.append(app_key)
                return repo_dir

            fn, calls = self._fake_start_run(run_dir=Path(tmp) / "run-dir")
            result = cas.create_and_start(
                report, ["条件A"], main_agent="claude", review_agent="codex",
                resolve_repo_dir=fake_resolve,
                create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                    lines, target_repo, identity, specs_dir=specs_dir),
                start_run=fn)
            self.assertTrue(result.ok)
            self.assertEqual(seen_app_keys, ["next-day-setup"])
            self.assertEqual(calls[0]["repo"], str(repo_dir))


class DefaultStartRunTests(unittest.TestCase):
    """_default_start_run (the real "既存のOrchestrator起動と同じ入口") is exercised through
    mocks of orchestrator.resolve_repo_definition / start_run / StartRequest -- never the real
    git/subprocess machinery."""

    def test_uses_registry_tests_and_branch_and_calls_the_real_start_run_once(self):
        from types import SimpleNamespace

        definition = SimpleNamespace(name="next-day-setup", branch="main", initial_test="pytest -q")
        with mock.patch("tools.ai_orchestrator.orchestrator.resolve_repo_definition", return_value=definition), \
                mock.patch("tools.ai_orchestrator.orchestrator.start_run") as start_run_mock:
            start_run_mock.return_value = Path("/run/dir")
            fake_spec = taskspec.Spec(criteria=({"id": "C1", "text": "条件A"},), target_repo="next-day-setup")
            result = cas._default_start_run(
                repo=r"C:\repos\next-day-setup", task="task text", main_agent="claude",
                review_agent="codex", spec=fake_spec)
        self.assertEqual(result, Path("/run/dir"))
        start_run_mock.assert_called_once()
        request = start_run_mock.call_args.args[0]
        self.assertEqual(request.repo, r"C:\repos\next-day-setup")
        self.assertEqual(request.tests, ["pytest -q"])
        self.assertEqual(request.expected_branch, "main")
        self.assertEqual(request.main_agent, "claude")
        self.assertEqual(request.review_agent, "codex")
        self.assertIs(request.spec, fake_spec)

    def test_missing_registry_tests_refuses_without_calling_start_run(self):
        from types import SimpleNamespace

        definition = SimpleNamespace(name="next-day-setup", branch="main", initial_test="")
        with mock.patch("tools.ai_orchestrator.orchestrator.resolve_repo_definition", return_value=definition), \
                mock.patch("tools.ai_orchestrator.orchestrator.start_run") as start_run_mock:
            with self.assertRaises(OrchestratorError):
                cas._default_start_run(
                    repo=r"C:\repos\next-day-setup", task="task text", main_agent="claude",
                    review_agent="codex", spec=None)
        start_run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
