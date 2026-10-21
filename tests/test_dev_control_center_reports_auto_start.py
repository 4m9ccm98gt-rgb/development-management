"""DCC Task 18: automatic second-stage start (reports_auto_start.py).

Every test here uses only fakes/temp dirs: reports_config_fn, scan_fn, resolve_repo_dir,
active_runs_fn, create_and_start_fn, run_lookup_fn and load_decision_fn are always injected --
never the real AI, real Orchestrator, real Tk, or the real %LOCALAPPDATA%. No network, no
subprocess. Output files live under tempfile.TemporaryDirectory() only.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev_control_center import reports_auto as auto
from scripts.dev_control_center import reports_auto_start as auto_start
from scripts.dev_control_center import reports_create_and_start as cas
from scripts.dev_control_center import reports_inbox as inbox
from tools.ai_orchestrator import taskspec


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


def save_triage_result(tmp: Path, report: inbox.Report, outcome: str) -> None:
    record = auto.AutoTriageRecord(report.app_key, report.report_id, outcome,
                                     "2026-01-01T00:00:00Z", 1.0)
    auto._save_result(record, root=tmp / "triage_results")


def _no_decision(_app_key: str, _report_id: str):
    return None


class AutoStartConfigTests(unittest.TestCase):
    def test_default_config_is_all_off(self):
        config = auto_start.AutoStartConfig()
        self.assertEqual(config.apps, {})
        self.assertEqual(config.daily_limit, auto_start.DEFAULT_DAILY_LIMIT)

    def test_missing_file_loads_as_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = auto_start.load_auto_start_config(Path(tmp) / "no-such-config.json")
            self.assertEqual(config.apps, {})

    def test_corrupt_file_degrades_to_defaults_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("not json{{{", encoding="utf-8")
            config = auto_start.load_auto_start_config(path)
            self.assertEqual(config.apps, {})

    def test_set_app_start_allowed_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            auto_start.set_app_start_allowed("next-day-setup", True, path=path)
            config = auto_start.load_auto_start_config(path)
            self.assertTrue(config.apps.get("next-day-setup"))

    def test_app_start_allowed_requires_both_global_switch_and_own_permission(self):
        both_off = auto.AutoModeConfig(enabled=False)
        start_off = auto_start.AutoStartConfig(apps={"a": False})
        start_on = auto_start.AutoStartConfig(apps={"a": True})
        self.assertFalse(auto_start.app_start_allowed(both_off, start_on, "a"))
        self.assertFalse(auto_start.app_start_allowed(auto.AutoModeConfig(enabled=True), start_off, "a"))
        self.assertTrue(auto_start.app_start_allowed(auto.AutoModeConfig(enabled=True), start_on, "a"))


class DailyLimitTests(unittest.TestCase):
    def test_daily_limit_reached_compares_against_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            config = auto_start.AutoStartConfig(daily_limit=2)
            self.assertFalse(auto_start.daily_limit_reached(config, "2026-02-01", path=path))
            auto_start._increment_daily_count("2026-02-01", path)
            self.assertFalse(auto_start.daily_limit_reached(config, "2026-02-01", path=path))
            auto_start._increment_daily_count("2026-02-01", path)
            self.assertTrue(auto_start.daily_limit_reached(config, "2026-02-01", path=path))


class RunAutoStartOnceTests(unittest.TestCase):
    def _fixed_deps(self, tmp: Path) -> dict:
        return dict(
            daily_count_path=tmp / "count.json", records_dir=tmp / "records", log_dir=tmp / "run_log",
            auto_results_root=tmp / "triage_results", waiting_dir=tmp / "waiting",
        )

    def _fake_create_and_start(self, calls, *, ok=True, reason="", run_dir=None):
        def fn(report, criteria_lines, **kwargs):
            calls.append((report.identity, criteria_lines, kwargs))
            return cas.StartResult(ok, reason, spec_path=Path("/fake/spec.json"),
                                    run_dir=run_dir if ok else None)
        return fn

    def _scan_fn(self, report):
        return lambda apps: [inbox.AppInbox(report.app_key, report.app_display_name, True, "", (report,))]

    # ------------------------------------------------------------------ C1
    def test_global_switch_off_never_calls_create_and_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            calls = []
            outcome = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=False),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, auto_start.STATUS_DISABLED)

    def test_app_permission_off_never_calls_create_and_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            calls = []
            outcome = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": False}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, auto_start.STATUS_NOTHING_TO_DO)

    # ------------------------------------------------------------------ C2
    def test_only_proceed_outcome_is_started_others_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            global_config = auto.AutoModeConfig(enabled=True)
            start_config = auto_start.AutoStartConfig(apps={"next-day-setup": True})
            for label, outcome in (
                ("needs_human", auto.OUTCOME_NEEDS_HUMAN), ("not_applicable", auto.OUTCOME_NOT_APPLICABLE),
                ("failed", auto.OUTCOME_FAILED),
            ):
                with self.subTest(label):
                    report = make_report(report_id=f"r-{label}")
                    deps = self._fixed_deps(tmp / label)
                    save_triage_result(tmp / label, report, outcome)
                    calls = []
                    result = auto_start.run_auto_start_once(
                        global_config=global_config, start_config=start_config,
                        reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                        create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                        **deps,
                    )
                    self.assertEqual(calls, [])
                    self.assertEqual(result.status, auto_start.STATUS_NOTHING_TO_DO)

            report = make_report(report_id="r-proceed")
            deps = self._fixed_deps(tmp / "proceed")
            save_triage_result(tmp / "proceed", report, auto.OUTCOME_PROCEED)
            calls = []
            result = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "proceed" / "repos" / app_key,
                active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(result.status, auto_start.STATUS_STARTED)

    def test_report_already_decided_by_a_human_is_never_auto_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            calls = []
            result = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                create_and_start_fn=self._fake_create_and_start(calls),
                load_decision_fn=lambda a, r: object(), **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(result.status, auto_start.STATUS_NOTHING_TO_DO)

    # ------------------------------------------------------------------ C3
    def test_started_once_is_never_started_again_even_if_it_later_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            global_config = auto.AutoModeConfig(enabled=True)
            start_config = auto_start.AutoStartConfig(apps={"next-day-setup": True})
            calls = []

            first = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(first.status, auto_start.STATUS_STARTED)
            self.assertEqual(len(calls), 1)

            second = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                load_decision_fn=_no_decision, run_lookup_fn=lambda run_id: None, **deps,
            )
            self.assertEqual(second.status, auto_start.STATUS_NOTHING_TO_DO)
            self.assertEqual(len(calls), 1)  # never started twice

    def test_a_failed_start_is_recorded_and_never_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            global_config = auto.AutoModeConfig(enabled=True)
            start_config = auto_start.AutoStartConfig(apps={"next-day-setup": True})
            calls = []

            first = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls, ok=False, reason=cas.REASON_START_FAILED),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(first.status, auto_start.STATUS_START_FAILED)
            self.assertEqual(first.record.result, auto_start.RESULT_NEEDS_HUMAN)
            self.assertEqual(len(calls), 1)

            second = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls, ok=False, reason=cas.REASON_START_FAILED),
                load_decision_fn=_no_decision, run_lookup_fn=lambda run_id: None, **deps,
            )
            self.assertEqual(second.status, auto_start.STATUS_NOTHING_TO_DO)
            self.assertEqual(len(calls), 1)  # no retry

    # ------------------------------------------------------------------ C4
    def test_daily_limit_reached_stops_before_starting_and_shows_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            global_config = auto.AutoModeConfig(enabled=True)
            start_config = auto_start.AutoStartConfig(apps={"next-day-setup": True}, daily_limit=0)
            calls = []

            outcome = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                **deps,
            )
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, auto_start.STATUS_LIMIT_REACHED)
            self.assertEqual(outcome.message, auto_start.LIMIT_REACHED_TEXT)

    # ------------------------------------------------------------------ C5
    def test_switching_off_mid_scan_stops_before_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            global_config_path = tmp / "global.json"
            start_config_path = tmp / "start.json"
            auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), path=global_config_path)
            auto_start.save_auto_start_config(
                auto_start.AutoStartConfig(apps={"next-day-setup": True}), path=start_config_path)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            calls = []

            def scan_fn(apps):
                auto.save_auto_mode_config(auto.AutoModeConfig(enabled=False), path=global_config_path)
                return [inbox.AppInbox(report.app_key, report.app_display_name, True, "", (report,))]

            outcome = auto_start.run_auto_start_once(
                global_config_path=global_config_path, start_config_path=start_config_path,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn,
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, auto_start.STATUS_DISABLED)

    def test_app_permission_switched_off_mid_scan_stops_before_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            global_config_path = tmp / "global.json"
            start_config_path = tmp / "start.json"
            auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), path=global_config_path)
            auto_start.save_auto_start_config(
                auto_start.AutoStartConfig(apps={"next-day-setup": True}), path=start_config_path)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            calls = []

            def scan_fn(apps):
                auto_start.set_app_start_allowed("next-day-setup", False, path=start_config_path)
                return [inbox.AppInbox(report.app_key, report.app_display_name, True, "", (report,))]

            outcome = auto_start.run_auto_start_once(
                global_config_path=global_config_path, start_config_path=start_config_path,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn,
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, auto_start.STATUS_DISABLED)

    def test_stop_event_set_mid_scan_stops_before_starting(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            stop_event = threading.Event()
            calls = []

            def scan_fn(apps):
                stop_event.set()
                return [inbox.AppInbox(report.app_key, report.app_display_name, True, "", (report,))]

            outcome = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=scan_fn,
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                stop_event=stop_event, **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, auto_start.STATUS_STOPPED)

    # ------------------------------------------------------------------ C6
    def test_busy_repo_waits_and_is_retried_once_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            global_config = auto.AutoModeConfig(enabled=True)
            start_config = auto_start.AutoStartConfig(apps={"next-day-setup": True})
            calls = []
            busy = {"value": True}

            first = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: Path(tmp) / "repos" / app_key,
                active_runs_fn=lambda repo: ["running"] if busy["value"] else [],
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(first.status, auto_start.STATUS_WAITING)
            self.assertEqual(calls, [])
            self.assertIsNone(auto_start.load_auto_start_record(
                report.app_key, report.report_id, root=deps["records_dir"]))
            # C6/仕様2: a busy target repo shows as RESULT_WAITING in the inbox -- a display-only
            # mark that never gates already_started (no record exists, so retry is still allowed).
            self.assertTrue(auto_start.is_waiting(
                report.app_key, report.report_id, root=deps["waiting_dir"]))

            busy["value"] = False
            second = auto_start.run_auto_start_once(
                global_config=global_config, start_config=start_config,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: Path(tmp) / "repos" / app_key,
                active_runs_fn=lambda repo: ["running"] if busy["value"] else [],
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(second.status, auto_start.STATUS_STARTED)
            self.assertEqual(len(calls), 1)
            self.assertFalse(auto_start.is_waiting(
                report.app_key, report.report_id, root=deps["waiting_dir"]))

    # ------------------------------------------------------------------ C3/C4/C5 (guard + reservation)
    def _fake_create_and_start_invoking_start_run(self, calls, started_real):
        """Unlike _fake_create_and_start, this fake actually calls kwargs["start_run"](...) --
        the same way the real reports_create_and_start.create_and_start does -- so the deep guard
        run_auto_start_once wires into that parameter is actually exercised. Still fully fake: no
        real Tk, AI, Orchestrator, or network -- `started_real` only ever receives a sentinel
        Path, never anything that touches a real repository."""
        from tools.ai_orchestrator.runstate import ActiveRunExists

        def fn(report, criteria_lines, **kwargs):
            calls.append(report.identity)
            try:
                run_dir = kwargs["start_run"](repo="x", task="t", main_agent="claude",
                                               review_agent="codex", spec=None)
            except ActiveRunExists:
                return cas.StartResult(False, cas.REASON_ALREADY_RUNNING, spec_path=Path("/fake/spec.json"))
            started_real.append(run_dir)
            return cas.StartResult(True, "", spec_path=Path("/fake/spec.json"), run_dir=run_dir)
        return fn

    def test_switching_off_during_spec_creation_stops_the_actual_start_and_is_retried_once_back_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            global_config_path = tmp / "global.json"
            start_config_path = tmp / "start.json"
            auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), path=global_config_path)
            auto_start.save_auto_start_config(
                auto_start.AutoStartConfig(apps={"next-day-setup": True}), path=start_config_path)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            calls: list = []
            started_real: list = []

            def create_and_start_fn(rep, criteria_lines, **kwargs):
                # Simulate create_and_start_fn's own spec-file creation/parsing taking long enough
                # for a human to flip the switch off before the real start_run would run.
                auto_start.set_app_start_allowed("next-day-setup", False, path=start_config_path)
                return self._fake_create_and_start_invoking_start_run(calls, started_real)(rep, criteria_lines, **kwargs)

            outcome = auto_start.run_auto_start_once(
                global_config_path=global_config_path, start_config_path=start_config_path,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=create_and_start_fn,
                start_run_fn=lambda **kw: Path("/fake/run-dir"),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(len(calls), 1)  # create_and_start_fn itself was invoked
            self.assertEqual(started_real, [])  # but the guard blocked the real start_run
            self.assertEqual(outcome.status, auto_start.STATUS_WAITING)
            # The reservation is undone, so the report is eligible again next cycle.
            self.assertIsNone(auto_start.load_auto_start_record(
                report.app_key, report.report_id, root=deps["records_dir"]))
            # Contention never consumes the day's quota.
            self.assertEqual(auto_start._read_daily_count(auto.today_str(), deps["daily_count_path"]), 0)

            # Re-enable and retry: this time the guard lets the real start_run through.
            auto_start.set_app_start_allowed("next-day-setup", True, path=start_config_path)
            second = auto_start.run_auto_start_once(
                global_config_path=global_config_path, start_config_path=start_config_path,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start_invoking_start_run(calls, started_real),
                start_run_fn=lambda **kw: Path("/fake/run-dir"),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(second.status, auto_start.STATUS_STARTED)
            self.assertEqual(len(started_real), 1)
            self.assertEqual(auto_start._read_daily_count(auto.today_str(), deps["daily_count_path"]), 1)

    def test_daily_limit_reached_mid_scan_stops_the_actual_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            start_config_path = tmp / "start.json"
            auto_start.save_auto_start_config(
                auto_start.AutoStartConfig(apps={"next-day-setup": True}, daily_limit=1),
                path=start_config_path)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            calls: list = []
            started_real: list = []

            def create_and_start_fn(rep, criteria_lines, **kwargs):
                # Simulate another process consuming the day's last slot while this cycle's spec
                # file was being created.
                auto_start._increment_daily_count(auto.today_str(), deps["daily_count_path"])
                return self._fake_create_and_start_invoking_start_run(calls, started_real)(rep, criteria_lines, **kwargs)

            outcome = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True), start_config_path=start_config_path,
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=create_and_start_fn,
                start_run_fn=lambda **kw: Path("/fake/run-dir"),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(started_real, [])
            self.assertEqual(outcome.status, auto_start.STATUS_WAITING)
            self.assertIsNone(auto_start.load_auto_start_record(
                report.app_key, report.report_id, root=deps["records_dir"]))
            self.assertEqual(auto_start._read_daily_count(auto.today_str(), deps["daily_count_path"]), 1)

    # ------------------------------------------------------------------ isolation (fakes-only)
    def test_default_collaborators_are_never_touched_when_fully_faked(self):
        """DCC Task 18/C10: every real collaborator (repo resolver, active-run check, Orchestrator
        start, run-stage lookup) must be fully overridable -- a complete, successful cycle must
        never fall through to any of the real ones when fakes are supplied for all of them."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)

            def _boom(*_a, **_k):
                raise AssertionError("a real default collaborator must never be called in tests")

            with mock.patch.object(auto_start, "_default_resolve_repo_dir", _boom), \
                 mock.patch.object(auto_start, "_default_active_runs", _boom), \
                 mock.patch.object(auto_start, "_default_create_and_start", _boom), \
                 mock.patch.object(auto_start, "_default_run_stage", _boom), \
                 mock.patch.object(auto_start, "_default_load_decision", _boom), \
                 mock.patch.object(cas, "_default_start_run", _boom):
                outcome = auto_start.run_auto_start_once(
                    global_config=auto.AutoModeConfig(enabled=True),
                    start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                    reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                    resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                    run_lookup_fn=lambda run_id: None, load_decision_fn=_no_decision,
                    create_and_start_fn=self._fake_create_and_start([], run_dir=Path("/fake/run-dir")),
                    **deps,
                )
            self.assertEqual(outcome.status, auto_start.STATUS_STARTED)

    # ------------------------------------------------------------------ C7
    def test_spec_file_has_fixed_reproduce_first_criteria_no_report_text_and_unconfirmed_ai_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            nasty = "../../etc/passwd; rm -rf /\nC:\\evil\\path\n危険なタイトル"
            report = make_report(title=nasty, body=nasty)
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            specs_dir = tmp / "specs"

            def real_create_and_start(rep, criteria_lines, **kwargs):
                return cas.create_and_start(
                    rep, criteria_lines, main_agent="claude", review_agent="codex",
                    resolve_repo_dir=kwargs["resolve_repo_dir"], task_text_fn=kwargs["task_text_fn"],
                    create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                        lines, target_repo, identity, specs_dir=specs_dir),
                    start_run=lambda **sr_kwargs: Path("/fake/run-dir"),
                )

            result = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key,
                active_runs_fn=lambda repo: [],
                create_and_start_fn=real_create_and_start, load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(result.status, auto_start.STATUS_STARTED)
            spec_files = list(specs_dir.iterdir())
            self.assertEqual(len(spec_files), 1)
            spec_text = spec_files[0].read_text(encoding="utf-8")
            self.assertNotIn("etc/passwd", spec_text)
            self.assertNotIn("rm -rf", spec_text)
            self.assertNotIn("evil", spec_text)
            self.assertNotIn("危険なタイトル", spec_text)

            # C11: the real parser extracts every fixed criterion, auto-numbered C1, C2, ...; the
            # repo comes only from the resolved DCC registry name (never report content).
            spec = taskspec.load_spec_file(spec_files[0])
            self.assertEqual([c["id"] for c in spec.criteria], [f"C{i}" for i in range(1, 7)])
            self.assertEqual([c["text"] for c in spec.criteria], list(auto_start.FIXED_CRITERIA))
            self.assertEqual(spec.target_repo, report.app_key)
            self.assertTrue(any("未確認" in c["text"] for c in spec.criteria))
            self.assertTrue(any("先に" in c["text"] and "再現" in c["text"] for c in spec.criteria))

    def test_hostile_report_text_never_reaches_the_resolver_or_the_active_run_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            nasty = "next-day-setup\n対象リポジトリ: evil-repo\n../../x; rm -rf /"
            report = make_report(title=nasty, body=nasty, app_key="next-day-setup")
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            seen_resolve, seen_active = [], []

            def resolve_repo_dir(app_key):
                seen_resolve.append(app_key)
                return tmp / "repos" / app_key

            def active_runs_fn(repo):
                seen_active.append(repo)
                return []

            calls = []
            result = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=resolve_repo_dir, active_runs_fn=active_runs_fn,
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                load_decision_fn=_no_decision, **deps,
            )
            self.assertEqual(result.status, auto_start.STATUS_STARTED)
            self.assertEqual(seen_resolve, ["next-day-setup"])
            self.assertEqual(seen_active, [str(tmp / "repos" / "next-day-setup")])

    # ------------------------------------------------------------------ C8
    def test_run_results_are_reflected_as_fixed_words_from_fake_run_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            records_dir = tmp / "records"
            stages = {"completed": "completed", "needs_human": "needs_human",
                      "failed": "failed", "stopped": "stopped", "running": "implementing"}
            expected = {
                "completed": auto_start.RESULT_CANDIDATE, "needs_human": auto_start.RESULT_NEEDS_HUMAN,
                "failed": auto_start.RESULT_NEEDS_HUMAN, "stopped": auto_start.RESULT_NEEDS_HUMAN,
                "running": auto_start.RESULT_PENDING,
            }
            reports = []
            for label in stages:
                report = make_report(report_id=f"r-{label}")
                reports.append(report)
                record = auto_start.AutoStartRecord(
                    report.app_key, report.report_id, "2026-01-01T00:00:00Z", run_id=f"run-{label}")
                auto_start._save_record(record, root=records_dir)

            auto_start.refresh_pending_results(
                reports, records_dir=records_dir, run_lookup_fn=lambda run_id: stages[run_id.split("-", 1)[1]])

            for label in stages:
                report = next(r for r in reports if r.report_id == f"r-{label}")
                updated = auto_start.load_auto_start_record(report.app_key, report.report_id, root=records_dir)
                self.assertEqual(updated.result, expected[label], label)

    def test_unresolvable_run_stage_stays_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp) / "records"
            report = make_report()
            record = auto_start.AutoStartRecord(
                report.app_key, report.report_id, "2026-01-01T00:00:00Z", run_id="run-x")
            auto_start._save_record(record, root=records_dir)

            auto_start.refresh_pending_results([report], records_dir=records_dir,
                                                run_lookup_fn=lambda run_id: None)
            updated = auto_start.load_auto_start_record(report.app_key, report.report_id, root=records_dir)
            self.assertEqual(updated.result, auto_start.RESULT_PENDING)

    # ------------------------------------------------------------------ C9
    def test_approval_push_build_update_are_never_called(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            calls = []

            with mock.patch("scripts.dev_control_center.candidate.approve") as approve, \
                 mock.patch("scripts.dev_control_center.candidate.push") as push, \
                 mock.patch("scripts.dev_control_center.candidate.run_dev") as run_dev, \
                 mock.patch("scripts.dev_control_center.release_update.plan") as release_plan:
                auto_start.run_auto_start_once(
                    global_config=auto.AutoModeConfig(enabled=True),
                    start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                    reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                    resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                    create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                    load_decision_fn=_no_decision, **deps,
                )
                approve.assert_not_called()
                push.assert_not_called()
                run_dev.assert_not_called()
                release_plan.assert_not_called()
            self.assertEqual(len(calls), 1)

    # ------------------------------------------------------------------ sanity
    def test_nothing_to_do_when_inbox_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            calls = []
            outcome = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=lambda apps: [],
                create_and_start_fn=self._fake_create_and_start(calls), load_decision_fn=_no_decision,
                **self._fixed_deps(tmp),
            )
            self.assertEqual(outcome.status, auto_start.STATUS_NOTHING_TO_DO)
            self.assertEqual(calls, [])


class DecisionReCheckTests(unittest.TestCase):
    """DCC Task 17-fix (C3/C4/C5/C6): reports_auto_start's own decision check now goes through
    inbox.decision_or_unreadable_marker (not inbox.load_decision), so an unreadable decision
    record is excluded the same safe-side way reports_auto.py's own check is, and -- unlike before
    this task -- the decision is re-checked immediately before the real Orchestrator start, not
    just once when the eligible report was first chosen. Uses the real inbox decision functions
    (not the _no_decision fake every other test in this file injects), with inbox.decisions_root
    patched to a temp dir -- the same pattern tests/test_reports_inbox.py itself uses -- so the
    real %LOCALAPPDATA% is never touched (C8)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scope = mock.patch.object(inbox, "decisions_root", return_value=Path(self.tmp.name) / "decisions")
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def _fixed_deps(self, tmp: Path) -> dict:
        return dict(
            daily_count_path=tmp / "count.json", records_dir=tmp / "records", log_dir=tmp / "run_log",
            auto_results_root=tmp / "triage_results", waiting_dir=tmp / "waiting",
        )

    def _scan_fn(self, report):
        return lambda apps: [inbox.AppInbox(report.app_key, report.app_display_name, True, "", (report,))]

    def _fake_create_and_start(self, calls, *, run_dir=None):
        def fn(report, criteria_lines, **kwargs):
            calls.append(report.identity)
            return cas.StartResult(True, "", spec_path=Path("/fake/spec.json"), run_dir=run_dir)
        return fn

    def _fake_create_and_start_invoking_start_run(self, calls, started_real):
        """Same fake as RunAutoStartOnceTests._fake_create_and_start_invoking_start_run: actually
        calls kwargs["start_run"](...) so the deep guard is really exercised."""
        from tools.ai_orchestrator.runstate import ActiveRunExists

        def fn(report, criteria_lines, **kwargs):
            calls.append(report.identity)
            try:
                run_dir = kwargs["start_run"](repo="x", task="t", main_agent="claude",
                                               review_agent="codex", spec=None)
            except ActiveRunExists:
                return cas.StartResult(False, cas.REASON_ALREADY_RUNNING, spec_path=Path("/fake/spec.json"))
            started_real.append(run_dir)
            return cas.StartResult(True, "", spec_path=Path("/fake/spec.json"), run_dir=run_dir)
        return fn

    # ------------------------------------------------------------------ C3
    def test_unreadable_decision_record_excludes_the_report_from_automatic_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            path = inbox.decision_path(report.app_key, report.report_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not json{{{", encoding="utf-8")
            calls: list = []

            result = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                create_and_start_fn=self._fake_create_and_start(calls), **self._fixed_deps(tmp),
            )
            self.assertEqual(calls, [])
            self.assertEqual(result.status, auto_start.STATUS_NOTHING_TO_DO)

    # ------------------------------------------------------------------ C4
    def test_decision_recorded_during_spec_creation_stops_the_actual_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            deps = self._fixed_deps(tmp)
            calls: list = []
            started_real: list = []

            def create_and_start_fn(rep, criteria_lines, **kwargs):
                # A human records 見送る while this cycle's own spec-file creation is in flight --
                # the guard right before the real Orchestrator start must still catch it.
                inbox.save_decision(rep.app_key, rep.report_id, "skip")
                return self._fake_create_and_start_invoking_start_run(
                    calls, started_real)(rep, criteria_lines, **kwargs)

            outcome = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=create_and_start_fn,
                start_run_fn=lambda **kw: Path("/fake/run-dir"), **deps,
            )
            self.assertEqual(len(calls), 1)  # create_and_start_fn itself was invoked
            self.assertEqual(started_real, [])  # but the guard blocked the real start_run
            self.assertEqual(outcome.status, auto_start.STATUS_WAITING)
            self.assertIsNone(auto_start.load_auto_start_record(
                report.app_key, report.report_id, root=deps["records_dir"]))
            self.assertEqual(auto_start._read_daily_count(auto.today_str(), deps["daily_count_path"]), 0)

            # The decision now on record keeps the report out of the automatic target set on a
            # later cycle too -- not just this one aborted attempt (C1, via the same marker).
            second = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls),
                **deps,
            )
            self.assertEqual(len(calls), 1)  # create_and_start_fn never invoked again
            self.assertEqual(second.status, auto_start.STATUS_NOTHING_TO_DO)

    # ------------------------------------------------------------------ C6
    def test_automatic_start_never_writes_or_modifies_the_decision_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report = make_report()
            save_triage_result(tmp, report, auto.OUTCOME_PROCEED)
            calls: list = []

            result = auto_start.run_auto_start_once(
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=auto_start.AutoStartConfig(apps={"next-day-setup": True}),
                reports_config_fn=lambda: inbox.ReportsConfig([], []), scan_fn=self._scan_fn(report),
                resolve_repo_dir=lambda app_key: tmp / "repos" / app_key, active_runs_fn=lambda repo: [],
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-dir")),
                **self._fixed_deps(tmp),
            )
            self.assertEqual(result.status, auto_start.STATUS_STARTED)
            self.assertIsNone(inbox.load_decision(report.app_key, report.report_id))
            self.assertFalse(inbox.decision_path(report.app_key, report.report_id).exists())


class LoadAutoStartRecordsTests(unittest.TestCase):
    def test_load_auto_start_records_maps_by_identity_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "records"
            record = auto_start.AutoStartRecord("app", "r1", "2026-01-01T00:00:00Z", "run-1",
                                                  auto_start.RESULT_CANDIDATE)
            auto_start._save_record(record, root=root)
            results = auto_start.load_auto_start_records([("app", "r1"), ("app", "r2")], root=root)
            self.assertEqual(set(results), {("app", "r1")})
            self.assertEqual(results[("app", "r1")].result, auto_start.RESULT_CANDIDATE)


if __name__ == "__main__":
    unittest.main()
