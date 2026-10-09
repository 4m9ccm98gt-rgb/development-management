"""DCC Task 17: automatic first-stage triage (reports_auto.py).

Every test here uses only fakes/temp dirs: investigate_fn, reports_config_fn and scan_fn are
always injected, never the real AI, real Orchestrator, real Tk, or the real %LOCALAPPDATA%. No
network. Output files live under tempfile.TemporaryDirectory() only.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev_control_center import reports_auto as auto
from scripts.dev_control_center import reports_inbox as inbox
from scripts.dev_control_center import reports_triage as triage


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


def make_triage_result(**overrides) -> triage.TriageResult:
    fields = dict(
        classification="bug", confidence="high", evidence="根拠",
        suspected_locations=("foo/bar.py",), criteria_draft=("再現しない",), reply_draft="返信",
    )
    fields.update(overrides)
    return triage.TriageResult(**fields)


class AutoModeConfigTests(unittest.TestCase):
    def test_default_config_is_all_off(self):
        config = auto.AutoModeConfig()
        self.assertFalse(config.enabled)
        self.assertEqual(config.apps, {})
        self.assertEqual(config.daily_limit, auto.DEFAULT_DAILY_LIMIT)

    def test_missing_file_loads_as_all_off_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no-such-config.json"
            config = auto.load_auto_mode_config(path)
            self.assertFalse(config.enabled)
            self.assertEqual(config.apps, {})

    def test_corrupt_file_degrades_to_defaults_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("not json{{{", encoding="utf-8")
            config = auto.load_auto_mode_config(path)
            self.assertFalse(config.enabled)

    def test_set_enabled_and_set_app_allowed_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            auto.set_enabled(True, path=path)
            auto.set_app_allowed("next-day-setup", True, path=path)
            config = auto.load_auto_mode_config(path)
            self.assertTrue(config.enabled)
            self.assertTrue(auto.app_allowed(config, "next-day-setup"))
            self.assertFalse(auto.app_allowed(config, "other-app"))

    def test_app_allowed_requires_both_global_switch_and_app_permission(self):
        both_off = auto.AutoModeConfig(enabled=False, apps={"a": False})
        global_only = auto.AutoModeConfig(enabled=True, apps={"a": False})
        app_only = auto.AutoModeConfig(enabled=False, apps={"a": True})
        both_on = auto.AutoModeConfig(enabled=True, apps={"a": True})
        self.assertFalse(auto.app_allowed(both_off, "a"))
        self.assertFalse(auto.app_allowed(global_only, "a"))
        self.assertFalse(auto.app_allowed(app_only, "a"))
        self.assertTrue(auto.app_allowed(both_on, "a"))


class DailyLimitTests(unittest.TestCase):
    def test_count_starts_at_zero_for_a_new_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            self.assertEqual(auto._read_daily_count("2026-02-01", path), 0)

    def test_increment_persists_and_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            auto._increment_daily_count("2026-02-01", path)
            auto._increment_daily_count("2026-02-01", path)
            self.assertEqual(auto._read_daily_count("2026-02-01", path), 2)

    def test_count_resets_on_a_new_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            auto._increment_daily_count("2026-02-01", path)
            self.assertEqual(auto._read_daily_count("2026-02-02", path), 0)

    def test_daily_limit_reached_compares_against_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            config = auto.AutoModeConfig(enabled=True, daily_limit=2)
            self.assertFalse(auto.daily_limit_reached(config, "2026-02-01", path=path))
            auto._increment_daily_count("2026-02-01", path)
            self.assertFalse(auto.daily_limit_reached(config, "2026-02-01", path=path))
            auto._increment_daily_count("2026-02-01", path)
            self.assertTrue(auto.daily_limit_reached(config, "2026-02-01", path=path))


class ClassifyOutcomeTests(unittest.TestCase):
    """C3: only classification / confidence / suspected_locations ever matter."""

    def test_failed_investigation_is_always_failed(self):
        outcome = triage.TriageOutcome(None, "調査できませんでした（トークンの上限を超えました）。")
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_FAILED)

    def test_high_confidence_bug_with_a_real_candidate_is_proceed(self):
        result = make_triage_result(classification="bug", confidence="high",
                                     suspected_locations=("foo/bar.py:123",))
        outcome = triage.TriageOutcome(result)
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_PROCEED)

    def test_bug_with_only_the_unconfirmed_placeholder_needs_a_human(self):
        result = make_triage_result(classification="bug", confidence="high",
                                     suspected_locations=("未確認",))
        outcome = triage.TriageOutcome(result)
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_NEEDS_HUMAN)

    def test_bug_with_no_candidates_needs_a_human(self):
        result = make_triage_result(classification="bug", confidence="high", suspected_locations=())
        outcome = triage.TriageOutcome(result)
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_NEEDS_HUMAN)

    def test_medium_or_low_confidence_bug_needs_a_human(self):
        for confidence in ("medium", "low"):
            result = make_triage_result(classification="bug", confidence=confidence,
                                         suspected_locations=("foo/bar.py",))
            outcome = triage.TriageOutcome(result)
            self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_NEEDS_HUMAN)

    def test_feature_request_needs_a_human(self):
        result = make_triage_result(classification="feature_request", confidence="high")
        outcome = triage.TriageOutcome(result)
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_NEEDS_HUMAN)

    def test_spec_misunderstanding_and_insufficient_info_are_not_applicable(self):
        for classification in ("spec_misunderstanding", "insufficient_info"):
            result = make_triage_result(classification=classification)
            outcome = triage.TriageOutcome(result)
            self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_NOT_APPLICABLE)

    def test_free_text_fields_never_influence_the_classification(self):
        """Path-like, command-like and newline-laced text in evidence/reply_draft/criteria_draft
        must not flip the outcome either way, regardless of how alarming it looks."""
        nasty = "../../etc/passwd; rm -rf /\n" + "x" * 50
        result = make_triage_result(
            classification="bug", confidence="high", suspected_locations=("foo/bar.py",),
            evidence=nasty, reply_draft=nasty, criteria_draft=(nasty,),
        )
        outcome = triage.TriageOutcome(result)
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_PROCEED)

    def test_nasty_text_inside_a_suspected_location_other_than_the_placeholder_still_counts(self):
        nasty_location = "C:\\Windows\\System32\\cmd.exe /c calc\n"
        result = make_triage_result(classification="bug", confidence="high",
                                     suspected_locations=(nasty_location,))
        outcome = triage.TriageOutcome(result)
        self.assertEqual(auto.classify_outcome(outcome), auto.OUTCOME_PROCEED)


class RunLogEntryTests(unittest.TestCase):
    def test_writes_one_file_with_the_fixed_fields_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "run_log"
            auto.write_run_log_entry(app_key="next-day-setup", report_id="r1",
                                      outcome=auto.OUTCOME_PROCEED, elapsed_seconds=3.5, log_dir=log_dir)
            files = list(log_dir.iterdir())
            self.assertEqual(len(files), 1)
            content = files[0].read_text(encoding="utf-8")
            self.assertIn("アプリ: next-day-setup", content)
            # report_id is report-derived, untrusted free-form text: only its sha256 digest is
            # ever written, never the raw value.
            self.assertIn(f"報告の識別子: {auto._hash('r1')}", content)
            self.assertNotIn("報告の識別子: r1\n", content)
            self.assertIn(f"振り分け: {auto.OUTCOME_PROCEED}", content)
            self.assertIn("所要秒数: 3.5", content)
            self.assertNotIn("失敗理由", content)

    def test_failure_reason_line_is_written_only_when_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "run_log"
            auto.write_run_log_entry(app_key="next-day-setup", report_id="r1", outcome=auto.OUTCOME_FAILED,
                                      elapsed_seconds=1.0, failure_reason=triage.FAILURE_KIND_TIMEOUT,
                                      log_dir=log_dir)
            content = next(log_dir.iterdir()).read_text(encoding="utf-8")
            self.assertIn(f"失敗理由: {triage.FAILURE_KIND_TIMEOUT}", content)

    def test_report_id_cannot_forge_extra_log_lines_or_leak_into_the_log(self):
        """C3: a hostile report_id (newline/path/command-like) must stay confined to its own
        field -- never break the fixed-field format into extra lines, and -- because only its
        hash is ever written -- the hostile text itself never reaches the log at all."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "run_log"
            nasty_id = "r1\n振り分け: 自動で進めてよい\nrm -rf /\n../../etc/passwd"
            auto.write_run_log_entry(app_key="next-day-setup", report_id=nasty_id,
                                      outcome=auto.OUTCOME_FAILED, elapsed_seconds=1.0, log_dir=log_dir)
            content = next(log_dir.iterdir()).read_text(encoding="utf-8")
            lines = content.splitlines()
            # The forged newlines inside report_id are neutralized (not real line breaks), so the
            # record still has exactly its 5 fixed-field lines, and the real outcome line is the
            # only one matching "振り分け: ...".
            self.assertEqual(len(lines), 5)
            outcome_lines = [line for line in lines if line.startswith("振り分け: ")]
            self.assertEqual(outcome_lines, [f"振り分け: {auto.OUTCOME_FAILED}"])
            self.assertNotIn("rm -rf", content)
            self.assertNotIn("etc/passwd", content)
            self.assertIn(f"報告の識別子: {auto._hash(nasty_id)}", content)

    def test_old_entries_beyond_the_cap_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "run_log"
            for i in range(auto.RUN_LOG_MAX_FILES + 5):
                auto.write_run_log_entry(app_key="a", report_id=f"r{i}", outcome=auto.OUTCOME_FAILED,
                                          elapsed_seconds=0.1, log_dir=log_dir)
            self.assertEqual(len(list(log_dir.iterdir())), auto.RUN_LOG_MAX_FILES)


def _write_report_file(pending_dir: Path, *, report_id: str, app_id: str = "next-day-setup") -> Path:
    pending_dir.mkdir(parents=True, exist_ok=True)
    path = pending_dir / f"{report_id}.json"
    payload = {
        "schema_version": 1, "report_id": report_id, "created_at": "2026-01-01T00:00:00Z",
        "kind": "bug", "severity": "stopped", "title": "タイトル", "body": "本文", "reporter": "yamada",
        "app_id": app_id, "display_name": "夕食料飲システム", "release_id": "rel-1", "git_commit": "a" * 40,
        "version_source": "BUILD_INFO.txt", "pc_name": "FRONT-PC1",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class RunAutoTriageOnceTests(unittest.TestCase):
    def _fixed_deps(self, tmp: Path):
        return dict(
            daily_count_path=tmp / "count.json", results_dir=tmp / "results", log_dir=tmp / "run_log",
        )

    # ------------------------------------------------------------------ C1
    def test_global_switch_off_never_calls_investigate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=False, apps={"next-day-setup": True})
            investigate = mock.Mock()
            outcome = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []),
                scan_fn=lambda apps: [], **self._fixed_deps(tmp),
            )
            investigate.assert_not_called()
            self.assertEqual(outcome.status, auto.STATUS_DISABLED)

    def test_app_permission_off_never_calls_investigate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": False})
            report = make_report()
            investigate = mock.Mock()
            outcome = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []),
                scan_fn=lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))],
                **self._fixed_deps(tmp),
            )
            investigate.assert_not_called()
            self.assertEqual(outcome.status, auto.STATUS_NOTHING_TO_DO)

    # ------------------------------------------------------------------ C2
    def test_only_allowed_app_reports_are_picked_and_never_investigated_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"allowed-app": True, "blocked-app": False})
            allowed_report = make_report(app_key="allowed-app", report_id="r-allowed")
            blocked_report = make_report(app_key="blocked-app", report_id="r-blocked")
            calls: list[str] = []

            def investigate(report):
                calls.append(report.report_id)
                return triage.TriageOutcome(make_triage_result())

            def scan_fn(apps):
                return [
                    inbox.AppInbox("allowed-app", "許可アプリ", True, "", (allowed_report,)),
                    inbox.AppInbox("blocked-app", "禁止アプリ", True, "", (blocked_report,)),
                ]

            deps = self._fixed_deps(tmp)
            first = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(first.status, auto.STATUS_RAN)
            self.assertEqual(calls, ["r-allowed"])

            second = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            # The only allowed report was already investigated; the blocked one is never eligible.
            self.assertEqual(second.status, auto.STATUS_NOTHING_TO_DO)
            self.assertEqual(calls, ["r-allowed"])

    # ------------------------------------------------------------------ C4
    def test_daily_limit_reached_stops_before_investigating_and_shows_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True}, daily_limit=1)
            report = make_report()
            investigate = mock.Mock(return_value=triage.TriageOutcome(make_triage_result()))
            deps = self._fixed_deps(tmp)
            scan_fn = lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            first = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(first.status, auto.STATUS_RAN)
            investigate.assert_called_once()

            second_report = make_report(report_id="r2")
            second = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []),
                scan_fn=lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (second_report,))],
                **deps,
            )
            self.assertEqual(second.status, auto.STATUS_LIMIT_REACHED)
            self.assertEqual(second.message, auto.LIMIT_REACHED_TEXT)
            investigate.assert_called_once()  # still only the first call

    # ------------------------------------------------------------------ C5
    def test_failed_investigation_is_recorded_with_the_fixed_reason_and_never_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            report = make_report()
            investigate = mock.Mock(return_value=triage.TriageOutcome(
                None, triage._SCREEN_MESSAGES[triage.FAILURE_KIND_TIMEOUT]))
            deps = self._fixed_deps(tmp)
            scan_fn = lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            first = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(first.status, auto.STATUS_RAN)
            self.assertEqual(first.record.outcome, auto.OUTCOME_FAILED)
            # The existing fixed reason is recorded as its allow-listed FAILURE_KIND_* code --
            # never the raw reason sentence itself.
            self.assertEqual(first.record.failure_reason, triage.FAILURE_KIND_TIMEOUT)

            second = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(second.status, auto.STATUS_NOTHING_TO_DO)
            investigate.assert_called_once()  # no retry

    def test_ai_unavailable_and_exception_failures_are_recorded_and_never_retried(self):
        """Reviewer finding 1: not just a normal TriageOutcome(None, ...) failure, but also an
        unexpected exception raised by investigate_fn itself (e.g. its own setup code failing
        before any TriageOutcome exists) must end in a fixed, recorded failure reason and never
        be retried."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})

            for label, report_id, investigate, expected_reason in (
                ("ai_unavailable", "r-unavailable", mock.Mock(return_value=triage.TriageOutcome(
                    None, triage._SCREEN_MESSAGES[triage.FAILURE_KIND_AI_UNAVAILABLE])),
                 triage.FAILURE_KIND_AI_UNAVAILABLE),
                ("raised_exception", "r-crashed", mock.Mock(side_effect=RuntimeError("secret detail")),
                 triage.FAILURE_KIND_OTHER),
            ):
                with self.subTest(label):
                    report = make_report(report_id=report_id)
                    deps = self._fixed_deps(tmp / label)
                    scan_fn = lambda apps: [
                        inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

                    first = auto.run_auto_triage_once(
                        config=config, investigate_fn=investigate,
                        reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
                    )
                    self.assertEqual(first.status, auto.STATUS_RAN)
                    self.assertEqual(first.record.outcome, auto.OUTCOME_FAILED)
                    self.assertEqual(first.record.failure_reason, expected_reason)
                    # The raw exception text must never be recorded anywhere.
                    result_text = auto._result_path(
                        report.app_key, report.report_id, root=deps["results_dir"]).read_text(encoding="utf-8")
                    self.assertNotIn("secret detail", result_text)
                    log_text = next((deps["log_dir"]).iterdir()).read_text(encoding="utf-8")
                    self.assertNotIn("secret detail", log_text)

                    second = auto.run_auto_triage_once(
                        config=config, investigate_fn=investigate,
                        reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
                    )
                    self.assertEqual(second.status, auto.STATUS_NOTHING_TO_DO)
                    investigate.assert_called_once()  # no retry

    # ------------------------------------------------------------------ Reviewer finding 2
    def test_switching_off_mid_scan_stops_before_investigating(self):
        """A human may toggle the master switch or an app's permission off while the (possibly
        slow) inbox scan is still running; the settings must be re-checked immediately before
        the one AI call this cycle would make, not just once at the top."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config_path = tmp / "config.json"
            auto.save_auto_mode_config(
                auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True}), path=config_path)
            report = make_report()
            investigate = mock.Mock()
            deps = self._fixed_deps(tmp)

            def scan_fn(apps):
                # Stands in for a human flipping the checkbox off while this (slow) scan runs.
                auto.set_enabled(False, path=config_path)
                return [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            outcome = auto.run_auto_triage_once(
                config_path=config_path, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            investigate.assert_not_called()
            self.assertEqual(outcome.status, auto.STATUS_DISABLED)

    def test_app_permission_switched_off_mid_scan_stops_before_investigating(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config_path = tmp / "config.json"
            auto.save_auto_mode_config(
                auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True}), path=config_path)
            report = make_report()
            investigate = mock.Mock()
            deps = self._fixed_deps(tmp)

            def scan_fn(apps):
                auto.set_app_allowed("next-day-setup", False, path=config_path)
                return [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            outcome = auto.run_auto_triage_once(
                config_path=config_path, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            investigate.assert_not_called()
            self.assertEqual(outcome.status, auto.STATUS_DISABLED)

    def test_stop_event_set_mid_scan_stops_before_investigating(self):
        """DCC closing (app.py's own stop event) must also abort before the AI call, not just
        the settings."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            report = make_report()
            investigate = mock.Mock()
            deps = self._fixed_deps(tmp)
            stop_event = threading.Event()

            def scan_fn(apps):
                stop_event.set()  # DCC is closing, found out mid-scan
                return [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            outcome = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate, stop_event=stop_event,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            investigate.assert_not_called()
            self.assertEqual(outcome.status, auto.STATUS_STOPPED)

    def test_in_memory_config_without_a_path_is_unaffected_by_recheck(self):
        """Callers that only ever hand in an in-memory config= (no config_path -- every other
        test in this file) must keep behaving exactly as before: there is no on-disk source to
        re-read, so the recheck is a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            report = make_report()
            investigate = mock.Mock(return_value=triage.TriageOutcome(make_triage_result()))
            deps = self._fixed_deps(tmp)
            scan_fn = lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            outcome = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(outcome.status, auto.STATUS_RAN)
            investigate.assert_called_once()

    # ------------------------------------------------------------------ Reviewer finding 3
    def test_report_id_is_hashed_not_raw_in_the_record_and_the_log_while_dedup_still_works(self):
        """A path-like/command-like/newline-laced report_id must never reach the stored record
        or the run log, even though it still uniquely identifies the report for dedup (C2)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            nasty_id = "../../etc/passwd; rm -rf /\nreport"
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            report = make_report(report_id=nasty_id)
            investigate = mock.Mock(return_value=triage.TriageOutcome(make_triage_result()))
            deps = self._fixed_deps(tmp)
            scan_fn = lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            first = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(first.status, auto.STATUS_RAN)

            result_text = auto._result_path(
                report.app_key, nasty_id, root=deps["results_dir"]).read_text(encoding="utf-8")
            self.assertNotIn("rm -rf", result_text)
            self.assertNotIn("etc/passwd", result_text)
            log_text = next((deps["log_dir"]).iterdir()).read_text(encoding="utf-8")
            self.assertNotIn("rm -rf", log_text)
            self.assertNotIn("etc/passwd", log_text)

            # Dedup (C2) still works: the same (nasty) identity is never investigated twice.
            second = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(second.status, auto.STATUS_NOTHING_TO_DO)
            investigate.assert_called_once()

    # ------------------------------------------------------------------ C3 (end-to-end)
    def test_nasty_free_text_never_reaches_the_record_or_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            nasty = "../../secret; rm -rf /\n$(whoami)"
            result = make_triage_result(classification="bug", confidence="high",
                                         suspected_locations=("foo/bar.py",),
                                         evidence=nasty, reply_draft=nasty, criteria_draft=(nasty,))
            report = make_report(body=nasty, title=nasty)
            investigate = mock.Mock(return_value=triage.TriageOutcome(result))
            deps = self._fixed_deps(tmp)
            scan_fn = lambda apps: [inbox.AppInbox("next-day-setup", "夕食料飲システム", True, "", (report,))]

            outcome = auto.run_auto_triage_once(
                config=config, investigate_fn=investigate,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn, **deps,
            )
            self.assertEqual(outcome.record.outcome, auto.OUTCOME_PROCEED)
            log_text = next((deps["log_dir"]).iterdir()).read_text(encoding="utf-8")
            self.assertNotIn("secret", log_text)
            self.assertNotIn("whoami", log_text)
            result_text = auto._result_path(report.app_key, report.report_id, root=deps["results_dir"]).read_text(
                encoding="utf-8")
            self.assertNotIn("secret", result_text)
            self.assertNotIn("whoami", result_text)

    # ------------------------------------------------------------------ C6
    def test_no_orchestrator_start_no_spec_file_and_report_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shared_root = tmp / "shared"
            pending = inbox.pending_dir(shared_root)
            report_path = _write_report_file(pending, report_id="r1")
            before = report_path.read_bytes()

            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            investigate = mock.Mock(return_value=triage.TriageOutcome(make_triage_result()))
            reports_cfg = inbox.ReportsConfig(
                [inbox.ConfiguredApp("next-day-setup", "夕食料飲システム", str(shared_root), "repo")], [])
            deps = self._fixed_deps(tmp)

            with mock.patch("tools.ai_orchestrator.orchestrator.start_run") as start_run, \
                 mock.patch.object(inbox, "create_spec_file") as create_spec_file:
                outcome = auto.run_auto_triage_once(
                    config=config, investigate_fn=investigate, reports_config_fn=lambda: reports_cfg,
                    scan_fn=inbox.scan_all, **deps,
                )
                start_run.assert_not_called()
                create_spec_file.assert_not_called()

            self.assertEqual(outcome.status, auto.STATUS_RAN)
            self.assertEqual(report_path.read_bytes(), before)
            specs_dir = tmp / "specs-should-not-exist"
            self.assertFalse(specs_dir.exists())

    # ------------------------------------------------------------------ C7 (fakes/temp only, sanity)
    def test_nothing_to_do_when_inbox_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = auto.AutoModeConfig(enabled=True, apps={"next-day-setup": True})
            outcome = auto.run_auto_triage_once(
                config=config, investigate_fn=mock.Mock(),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=lambda apps: [],
                **self._fixed_deps(tmp),
            )
            self.assertEqual(outcome.status, auto.STATUS_NOTHING_TO_DO)


class LoadAutoResultsTests(unittest.TestCase):
    def test_load_auto_results_maps_by_identity_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "results"
            record = auto.AutoTriageRecord("app", "r1", auto.OUTCOME_PROCEED, "2026-01-01T00:00:00Z", 1.2)
            auto._save_result(record, root=root)
            results = auto.load_auto_results([("app", "r1"), ("app", "r2")], root=root)
            self.assertEqual(set(results), {("app", "r1")})
            self.assertEqual(results[("app", "r1")].outcome, auto.OUTCOME_PROCEED)


if __name__ == "__main__":
    unittest.main()
