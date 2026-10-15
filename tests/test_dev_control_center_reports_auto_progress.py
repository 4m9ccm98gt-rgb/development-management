"""DCC Task 19c-2a: automatic RUN_DEV -> 自動承認 -> Task 19a's combined execution
(reports_auto_progress.py).

Every test here uses only fakes/temp dirs: reports_config_fn, scan_fn, resolve_repo_dir,
resolve_repo_definition, active_runs_fn, latest_candidate_fn and every stage function
(run_dev_fn/approve_fn/push_fn/build_fn/dry_run_fn) are always injected -- never the real Tk
screen, a real AI, the real Orchestrator, real RUN_DEV/push/BUILD/UPDATE, or the real
%LOCALAPPDATA%. No network, no subprocess, no git. Every path (daily count, attempted index,
decision results, Task 18 associations, the run log) lives under tempfile.TemporaryDirectory().
"""
from __future__ import annotations

import json
import queue
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import reports_auto as auto
from scripts.dev_control_center import reports_auto_approve as approve
from scripts.dev_control_center import reports_auto_progress as progress
from scripts.dev_control_center import reports_auto_start as start
from scripts.dev_control_center import reports_inbox as inbox

SHA = "a" * 40
SHA2 = "b" * 40
# Shares SHA's first 12 hex characters but is a different full SHA -- the old prefix-match
# would have accepted this as a match; the strict full-SHA check must reject it.
SHA_PREFIX_COLLISION = "a" * 12 + "f" * 28


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


def scan_fn_for(reports):
    by_app: dict = {}
    for r in reports:
        by_app.setdefault(r.app_key, []).append(r)

    def fn(apps_meta):
        return [inbox.AppInbox(app_key, display_name, True, "", tuple(by_app.get(app_key, ())))
                for app_key, display_name, _shared in apps_meta]
    return fn


def reports_config_for(app_keys):
    apps = [inbox.ConfiguredApp(app_key=k, display_name=k, shared_root="//share", source="repo") for k in app_keys]
    return lambda: inbox.ReportsConfig(apps, [])


def save_decision(results_dir: Path, app_key: str, report_id: str, sha: str, *, run_id="run-1",
                  files=1, lines=2, reasons=()) -> None:
    decision = approve.Decision(tuple(reasons), files, lines)
    approve.record_decision(app_key, report_id, sha, decision, run_id=run_id, results_dir=results_dir,
                            log_dir=results_dir.parent / "approve_run_log")


def save_association(records_dir: Path, app_key: str, report_id: str, run_id: str) -> None:
    record = start.AutoStartRecord(app_key, report_id, "2026-01-01T00:00:00Z", run_id, start.RESULT_CANDIDATE)
    start._save_record(record, root=records_dir)


def make_candidate(sha: str, run_id: str = "run-1"):
    return SimpleNamespace(sha=sha, run_id=run_id)


def make_definition(name: str = "next-day-setup", branch: str = "main"):
    return SimpleNamespace(name=name, branch=branch, repo_type="python", application_implemented=True)


def stage_spies(fail_at: str | None = None):
    calls: list[str] = []

    def mk(name: str):
        def fn(*_args, **_kwargs):
            calls.append(name)
            return name != fail_at
        return fn

    fns = dict(run_dev_fn=mk(progress.STAGE_RUN_DEV), approve_fn=mk(progress.STAGE_APPROVE),
               push_fn=mk(progress.STAGE_PUSH), build_fn=mk(progress.STAGE_BUILD),
               dry_run_fn=mk(progress.STAGE_DRY_RUN))
    return calls, fns


class Fixture:
    """One app ("next-day-setup"), one eligible report/candidate, every DCC-side dependency
    wired to a tmp-backed fake. Individual tests override whichever kwarg they need."""

    def __init__(self, tmp: Path, *, app_key="next-day-setup", report_id="r1", sha=SHA, run_id="run-1",
                files=1, lines=2, reasons=()):
        self.tmp = tmp
        self.app_key, self.report_id, self.sha, self.run_id = app_key, report_id, sha, run_id
        self.report = make_report(app_key=app_key, report_id=report_id)
        self.results_dir = tmp / "approve_results"
        self.records_dir = tmp / "assoc_records"
        self.log_dir = tmp / "progress_log"
        save_decision(self.results_dir, app_key, report_id, sha, run_id=run_id, files=files, lines=lines,
                     reasons=reasons)
        save_association(self.records_dir, app_key, report_id, run_id)
        self.repo_dir = tmp / "repo" / app_key
        self.definition = make_definition(name=app_key)
        self.candidate_obj = make_candidate(sha, run_id)
        self.state = progress.ProgressState(daily_count_path=tmp / "daily.json",
                                            attempted_index_path=tmp / "attempted.json")

    def kwargs(self, **overrides) -> dict:
        base = dict(
            state=self.state,
            global_config=auto.AutoModeConfig(enabled=True),
            start_config=start.AutoStartConfig(apps={self.app_key: True}),
            approve_config=approve.ApprovalConfig(apps={self.app_key: True}, daily_limit=2),
            today="2026-02-01",
            reports_config_fn=reports_config_for([self.app_key]),
            scan_fn=scan_fn_for([self.report]),
            records_dir=self.records_dir, results_dir=self.results_dir,
            resolve_repo_dir=lambda app_key, _r=self.repo_dir: _r,
            resolve_repo_definition=lambda name, _d=self.definition: _d,
            active_runs_fn=lambda repo: [],
            latest_candidate_fn=lambda repo, _c=self.candidate_obj: _c,
            log_dir=self.log_dir,
        )
        base.update(overrides)
        return base

    def log_entries(self) -> list[dict]:
        if not self.log_dir.is_dir():
            return []
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.log_dir.iterdir())]


class RunOnceTests(unittest.TestCase):
    # ------------------------------------------------------------------ C1
    def test_global_switch_off_calls_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            outcome = progress.run_auto_progress_once(**fx.kwargs(global_config=auto.AutoModeConfig(enabled=False), **fns))
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, progress.STATUS_DISABLED)

    def test_app_permission_off_calls_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            outcome = progress.run_auto_progress_once(
                **fx.kwargs(approve_config=approve.ApprovalConfig(apps={fx.app_key: False}, daily_limit=2), **fns))
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, progress.STATUS_DONE)

    # ------------------------------------------------------------------ C2
    def test_needs_human_candidate_never_progresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp), reasons=(approve.REASONS[1],))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])

    def test_eligible_candidate_progresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE,
                                     progress.STAGE_PUSH, progress.STAGE_BUILD, progress.STAGE_DRY_RUN])

    # ------------------------------------------------------------------ C3
    def test_stages_called_in_order_once_each_with_shared_body_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            recorded = {}

            def run_dev_fn(repo_dir, branch, sha):
                recorded["run_dev"] = (repo_dir, branch, sha)
                return True

            def approve_fn(candidate_obj, sha):
                recorded["approve"] = (candidate_obj, sha)
                return True

            def push_fn(repo_dir, branch, sha):
                recorded["push"] = (repo_dir, branch, sha)
                return True

            def build_fn(repo_dir, definition, candidate_obj):
                recorded["build"] = (repo_dir, definition, candidate_obj)
                return True

            def dry_run_fn(repo_dir, definition, candidate_obj):
                recorded["dry_run"] = (repo_dir, definition, candidate_obj)
                return True

            outcome = progress.run_auto_progress_once(**fx.kwargs(
                run_dev_fn=run_dev_fn, approve_fn=approve_fn, push_fn=push_fn, build_fn=build_fn, dry_run_fn=dry_run_fn))
            self.assertEqual(outcome.status, progress.STATUS_DONE)
            self.assertEqual(recorded["run_dev"], (fx.repo_dir, fx.definition.branch, fx.sha))
            self.assertEqual(recorded["approve"], (fx.candidate_obj, fx.sha))
            self.assertEqual(recorded["push"], (fx.repo_dir, fx.definition.branch, fx.sha))
            self.assertEqual(recorded["build"], (fx.repo_dir, fx.definition, fx.candidate_obj))
            self.assertEqual(recorded["dry_run"], (fx.repo_dir, fx.definition, fx.candidate_obj))
            entries = fx.log_entries()
            self.assertTrue(any(e["state"] == progress.STATE_RELEASE_READY for e in entries))

    # ------------------------------------------------------------------ C4
    def test_each_stage_failure_stops_the_chain_and_records_it(self):
        with tempfile.TemporaryDirectory() as tmp_root:
            for fail_stage, expected_calls in (
                (progress.STAGE_RUN_DEV, [progress.STAGE_RUN_DEV]),
                (progress.STAGE_APPROVE, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE]),
                (progress.STAGE_PUSH, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH]),
                (progress.STAGE_BUILD, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH,
                                        progress.STAGE_BUILD]),
                (progress.STAGE_DRY_RUN, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH,
                                          progress.STAGE_BUILD, progress.STAGE_DRY_RUN]),
            ):
                with self.subTest(fail_stage=fail_stage):
                    tmp = Path(tmp_root) / fail_stage.replace("-", "_")
                    tmp.mkdir()
                    fx = Fixture(tmp)
                    calls, fns = stage_spies(fail_at=fail_stage)
                    progress.run_auto_progress_once(**fx.kwargs(**fns))
                    self.assertEqual(calls, expected_calls)
                    entries = fx.log_entries()
                    final = entries[-1]
                    self.assertEqual(final["state"], progress.STATE_NEEDS_HUMAN)
                    self.assertEqual(final["failed_stage"], fail_stage)

    def test_unexpected_exception_stops_and_records_needs_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))

            def boom(*_a, **_k):
                raise RuntimeError("boom")

            progress.run_auto_progress_once(**fx.kwargs(run_dev_fn=boom))
            entries = fx.log_entries()
            self.assertEqual(entries[-1]["state"], progress.STATE_NEEDS_HUMAN)
            self.assertEqual(entries[-1]["failed_stage"], progress.STAGE_RUN_DEV)

    def test_exception_at_each_stage_stops_chain_records_failed_stage_and_releases(self):
        """Finding 5: an exception must never lose the stages already completed, and the stage
        that was actually in progress when it raised must be the recorded failed_stage -- never
        an empty string and never {} for the stages that already succeeded."""
        with tempfile.TemporaryDirectory() as tmp_root:
            for fail_stage, expected_calls in (
                (progress.STAGE_RUN_DEV, []),
                (progress.STAGE_APPROVE, [progress.STAGE_RUN_DEV]),
                (progress.STAGE_PUSH, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE]),
                (progress.STAGE_BUILD, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH]),
                (progress.STAGE_DRY_RUN, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH,
                                          progress.STAGE_BUILD]),
            ):
                with self.subTest(fail_stage=fail_stage):
                    tmp = Path(tmp_root) / ("exc_" + fail_stage.replace("-", "_"))
                    tmp.mkdir()
                    fx = Fixture(tmp)
                    calls: list[str] = []

                    def mk(name):
                        def fn(*_a, **_k):
                            if name == fail_stage:
                                raise RuntimeError("boom")
                            calls.append(name)
                            return True
                        return fn

                    fns = dict(run_dev_fn=mk(progress.STAGE_RUN_DEV), approve_fn=mk(progress.STAGE_APPROVE),
                              push_fn=mk(progress.STAGE_PUSH), build_fn=mk(progress.STAGE_BUILD),
                              dry_run_fn=mk(progress.STAGE_DRY_RUN))
                    released = []

                    def reserve(repo_name):
                        return object()

                    def release(repo_name, token):
                        released.append(repo_name)

                    progress.run_auto_progress_once(**fx.kwargs(reserve_fn=reserve, release_fn=release, **fns))
                    self.assertEqual(calls, expected_calls)
                    entries = fx.log_entries()
                    final = entries[-1]
                    self.assertEqual(final["state"], progress.STATE_NEEDS_HUMAN)
                    self.assertEqual(final["failed_stage"], fail_stage)
                    for stage_name in expected_calls:
                        self.assertEqual(final["stages"].get(stage_name), progress.RESULT_OK)
                    self.assertEqual(final["stages"].get(fail_stage), progress.RESULT_FAIL)
                    self.assertEqual(len(released), 1)  # reservation released even though it raised

    # ------------------------------------------------------------------ C5
    def test_sha_change_after_approve_stops_before_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            changed = make_candidate(SHA2, fx.run_id)
            state_counter = {"n": 0}

            def latest(_repo):
                state_counter["n"] += 1
                # Calls: #1 _select_candidate, #2 pre-RUN_DEV, #3 pre-APPROVE, #4 pre-PUSH.
                return fx.candidate_obj if state_counter["n"] <= 3 else changed

            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(latest_candidate_fn=latest, **fns))
            self.assertEqual(calls, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE])
            self.assertEqual(fx.log_entries()[-1]["failed_stage"], progress.STAGE_PUSH)

    def test_sha_change_after_push_stops_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            changed = make_candidate(SHA2, fx.run_id)
            state_counter = {"n": 0}

            def latest(_repo):
                state_counter["n"] += 1
                # Calls: #1 select, #2 pre-RUN_DEV, #3 pre-APPROVE, #4 pre-PUSH, #5 pre-BUILD.
                return fx.candidate_obj if state_counter["n"] <= 4 else changed

            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(latest_candidate_fn=latest, **fns))
            self.assertEqual(calls, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH])
            self.assertEqual(fx.log_entries()[-1]["failed_stage"], progress.STAGE_BUILD)

    def test_sha_change_after_build_stops_before_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            changed = make_candidate(SHA2, fx.run_id)
            state_counter = {"n": 0}

            def latest(_repo):
                state_counter["n"] += 1
                # Calls: #1 select, #2..#5 pre-RUN_DEV/APPROVE/PUSH/BUILD, #6 pre-DRY_RUN.
                return fx.candidate_obj if state_counter["n"] <= 5 else changed

            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(latest_candidate_fn=latest, **fns))
            self.assertEqual(calls, [progress.STAGE_RUN_DEV, progress.STAGE_APPROVE, progress.STAGE_PUSH,
                                     progress.STAGE_BUILD])
            self.assertEqual(fx.log_entries()[-1]["failed_stage"], progress.STAGE_DRY_RUN)

    # ------------------------------------------------------------------ C6
    def test_boundary_reread_stops_mid_chain_when_switch_turns_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            global_path = tmp / "global.json"
            start_path = tmp / "start.json"
            approve_path = tmp / "approve.json"
            auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), global_path)
            start.save_auto_start_config(start.AutoStartConfig(apps={fx.app_key: True}), start_path)
            approve.save_config(approve.ApprovalConfig(apps={fx.app_key: True}, daily_limit=2), approve_path,
                               start_config=start.load_auto_start_config(start_path))

            def run_dev_fn(*_a, **_k):
                auto.set_enabled(False, path=global_path)  # turned OFF while this stage was "running"
                return True

            calls, fns = stage_spies()
            fns["run_dev_fn"] = run_dev_fn
            progress.run_auto_progress_once(**fx.kwargs(
                global_config=None, start_config=None, approve_config=None,
                global_config_path=global_path, start_config_path=start_path, approve_config_path=approve_path,
                **fns))
            self.assertEqual(calls, [])  # approve_fn (the fake dict) never ran
            self.assertEqual(fx.log_entries()[-1]["failed_stage"], progress.STAGE_APPROVE)

    def test_boundary_before_run_dev_blocks_when_switch_turns_off_during_reservation_wait(self):
        """Finding 3: RUN_DEV itself must be gated too -- not just the stages after it. Simulates
        the permission being switched off in the gap between the reservation succeeding and
        RUN_DEV's own boundary check running."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            global_path = tmp / "global.json"
            start_path = tmp / "start.json"
            approve_path = tmp / "approve.json"
            auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), global_path)
            start.save_auto_start_config(start.AutoStartConfig(apps={fx.app_key: True}), start_path)
            approve.save_config(approve.ApprovalConfig(apps={fx.app_key: True}, daily_limit=2), approve_path,
                               start_config=start.load_auto_start_config(start_path))

            def reserve(repo_name):
                auto.set_enabled(False, path=global_path)  # turned OFF right after the reservation lands
                return object()

            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(
                global_config=None, start_config=None, approve_config=None,
                global_config_path=global_path, start_config_path=start_path, approve_config_path=approve_path,
                reserve_fn=reserve, **fns))
            self.assertEqual(calls, [])  # run_dev_fn never ran
            self.assertEqual(fx.log_entries()[-1]["failed_stage"], progress.STAGE_RUN_DEV)

    def test_next_cycle_after_off_during_wait_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            # Cycle 1: busy -> waits, nothing runs, nothing marked attempted.
            progress.run_auto_progress_once(**fx.kwargs(active_runs_fn=lambda repo: ["busy"], **fns))
            self.assertEqual(calls, [])
            self.assertFalse(fx.state.has_attempted(fx.app_key, fx.sha))
            # Cycle 2: global switch now OFF -> still nothing runs.
            progress.run_auto_progress_once(**fx.kwargs(global_config=auto.AutoModeConfig(enabled=False), **fns))
            self.assertEqual(calls, [])

    # ------------------------------------------------------------------ C7
    def test_daily_limit_reached_blocks_and_records_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            fx.state.seed_startup("2026-02-01")
            fx.state.record_daily_attempt("2026-02-01")
            calls, fns = stage_spies()
            outcome = progress.run_auto_progress_once(**fx.kwargs(
                approve_config=approve.ApprovalConfig(apps={fx.app_key: True}, daily_limit=1), **fns))
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, progress.STATUS_LIMIT_REACHED)
            self.assertEqual(outcome.message, progress.LIMIT_REACHED_TEXT)
            self.assertTrue(any(e["state"] == progress.LIMIT_REACHED_TEXT for e in fx.log_entries()))

    # ------------------------------------------------------------------ C8
    def test_same_candidate_never_runs_twice_success_or_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(len(calls), 5)
            progress.run_auto_progress_once(**fx.kwargs(**fns))  # second cycle, same SHA
            self.assertEqual(len(calls), 5)  # unchanged: no second attempt

    def test_same_sha_from_a_different_report_never_runs_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            other_report_id = "r2"
            save_decision(fx.results_dir, fx.app_key, other_report_id, fx.sha)
            save_association(fx.records_dir, fx.app_key, other_report_id, "run-2")
            other_report = make_report(app_key=fx.app_key, report_id=other_report_id)
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(scan_fn=scan_fn_for([fx.report]), **fns))
            self.assertEqual(len(calls), 5)
            progress.run_auto_progress_once(**fx.kwargs(scan_fn=scan_fn_for([other_report]), **fns))
            self.assertEqual(len(calls), 5)  # same SHA, different report: still not re-run

    def test_failed_candidate_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies(fail_at=progress.STAGE_BUILD)
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(len(calls), 4)
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(len(calls), 4)  # no automatic retry

    # ------------------------------------------------------------------ C9
    def test_save_failures_never_allow_retry_or_exceed_limit_across_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            with mock.patch.object(progress.start, "_write_json_atomic", side_effect=OSError("disk full")):
                progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(len(calls), 5)
            self.assertTrue(fx.state.has_attempted(fx.app_key, fx.sha))  # memory remembers despite the save failure
            self.assertEqual(fx.state.daily_count("2026-02-01"), 1)
            # A later cycle (writes working again) must still not re-run the same candidate.
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(len(calls), 5)

    def test_reservation_release_happens_even_on_mid_chain_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            released = []

            def reserve(repo_name):
                return object()

            def release(repo_name, token):
                released.append((repo_name, token))

            def boom(*_a, **_k):
                raise RuntimeError("boom")

            progress.run_auto_progress_once(**fx.kwargs(reserve_fn=reserve, release_fn=release, run_dev_fn=boom))
            self.assertEqual(len(released), 1)

    def _two_candidate_setup(self, tmp: Path):
        """Second-candidate helper for the save-failure-isolation tests below: the same app's
        live candidate "moves on" between cycle 1 and cycle 2 (as a real repo would after the
        first candidate finishes), so each cycle has exactly one eligible, unattempted SHA."""
        app_key = "next-day-setup"
        results_dir, records_dir, log_dir = tmp / "results", tmp / "records", tmp / "log"
        definition = make_definition(name=app_key)
        repo_dir = tmp / "repo" / app_key
        save_decision(results_dir, app_key, "r1", SHA, run_id="run-1")
        save_association(records_dir, app_key, "r1", "run-1")
        save_decision(results_dir, app_key, "r2", SHA2, run_id="run-2")
        save_association(records_dir, app_key, "r2", "run-2")
        report_a, report_b = make_report(app_key=app_key, report_id="r1"), make_report(app_key=app_key, report_id="r2")
        candidate_a, candidate_b = make_candidate(SHA, "run-1"), make_candidate(SHA2, "run-2")

        def kwargs_for(report, candidate_obj, state, reserve_fn, release_fn, **fns):
            return dict(
                state=state, global_config=auto.AutoModeConfig(enabled=True),
                start_config=start.AutoStartConfig(apps={app_key: True}),
                approve_config=approve.ApprovalConfig(apps={app_key: True}, daily_limit=2),
                today="2026-02-01", reports_config_fn=reports_config_for([app_key]), scan_fn=scan_fn_for([report]),
                records_dir=records_dir, results_dir=results_dir, resolve_repo_dir=lambda k, _r=repo_dir: _r,
                resolve_repo_definition=lambda n, _d=definition: _d, active_runs_fn=lambda repo: [],
                latest_candidate_fn=lambda repo, _c=candidate_obj: _c, log_dir=log_dir,
                reserve_fn=reserve_fn, release_fn=release_fn, **fns)

        return report_a, report_b, candidate_a, candidate_b, kwargs_for

    def test_daily_count_save_failure_isolated_never_exceeds_limit_or_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report_a, report_b, candidate_a, candidate_b, kwargs_for = self._two_candidate_setup(tmp)
            state = progress.ProgressState(daily_count_path=tmp / "daily.json", attempted_index_path=tmp / "attempted.json")
            reserved, released = [], []

            def reserve(repo_name):
                reserved.append(repo_name)
                return object()

            def release(repo_name, token):
                released.append(repo_name)

            real_write = start._write_json_atomic

            def failing_daily_write(path, payload, *a, **kw):
                if path == state._daily_count_path:
                    raise OSError("disk full")
                return real_write(path, payload, *a, **kw)

            with mock.patch.object(progress.start, "_write_json_atomic", side_effect=failing_daily_write):
                calls_a, fns_a = stage_spies()
                progress.run_auto_progress_once(**kwargs_for(report_a, candidate_a, state, reserve, release, **fns_a))
                self.assertEqual(len(calls_a), 5)
                self.assertEqual(state.daily_count("2026-02-01"), 1)
                self.assertFalse(state._daily_count_path.exists())  # the persisted mirror never landed

                calls_b, fns_b = stage_spies()
                progress.run_auto_progress_once(**kwargs_for(report_b, candidate_b, state, reserve, release, **fns_b))
                self.assertEqual(len(calls_b), 5)
                self.assertEqual(state.daily_count("2026-02-01"), 2)

                # Third cycle: in-memory limit (2) is already reached despite the file never
                # having been written -- it must still block, and the same SHA must not re-run.
                calls_c, fns_c = stage_spies()
                outcome_c = progress.run_auto_progress_once(
                    **kwargs_for(report_a, candidate_a, state, reserve, release, **fns_c))
                self.assertEqual(calls_c, [])
                self.assertEqual(outcome_c.status, progress.STATUS_LIMIT_REACHED)

            self.assertEqual(len(reserved), 2)
            self.assertEqual(len(released), 2)  # released every time despite the save failure

    def test_attempted_index_save_failure_isolated_never_retries_or_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report_a, report_b, candidate_a, candidate_b, kwargs_for = self._two_candidate_setup(tmp)
            state = progress.ProgressState(daily_count_path=tmp / "daily.json", attempted_index_path=tmp / "attempted.json")
            reserved, released = [], []

            def reserve(repo_name):
                reserved.append(repo_name)
                return object()

            def release(repo_name, token):
                released.append(repo_name)

            real_write = start._write_json_atomic

            def failing_attempted_write(path, payload, *a, **kw):
                if path == state._attempted_index_path:
                    raise OSError("disk full")
                return real_write(path, payload, *a, **kw)

            with mock.patch.object(progress.start, "_write_json_atomic", side_effect=failing_attempted_write):
                calls_a, fns_a = stage_spies()
                progress.run_auto_progress_once(**kwargs_for(report_a, candidate_a, state, reserve, release, **fns_a))
                self.assertEqual(len(calls_a), 5)
                self.assertTrue(state.has_attempted("next-day-setup", SHA))
                self.assertFalse(state._attempted_index_path.exists())  # mirror never landed

                # Re-offering the same candidate (as if nothing had been persisted) must still
                # not re-run it: the in-memory marker is authoritative.
                calls_retry, fns_retry = stage_spies()
                progress.run_auto_progress_once(
                    **kwargs_for(report_a, candidate_a, state, reserve, release, **fns_retry))
                self.assertEqual(calls_retry, [])

                calls_b, fns_b = stage_spies()
                progress.run_auto_progress_once(**kwargs_for(report_b, candidate_b, state, reserve, release, **fns_b))
                self.assertEqual(len(calls_b), 5)
                self.assertEqual(state.daily_count("2026-02-01"), 2)

            # The retry attempt never reserved at all: has_attempted blocks it in
            # _select_candidate, before _process_candidate (and therefore reserve_fn) ever runs.
            self.assertEqual(len(reserved), 2)
            self.assertEqual(len(released), 2)  # released every time despite the save failure

    def test_terminal_log_save_failure_isolated_never_affects_counters_or_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            report_a, report_b, candidate_a, candidate_b, kwargs_for = self._two_candidate_setup(tmp)
            state = progress.ProgressState(daily_count_path=tmp / "daily.json", attempted_index_path=tmp / "attempted.json")
            log_dir = tmp / "log"
            reserved, released = [], []

            def reserve(repo_name):
                reserved.append(repo_name)
                return object()

            def release(repo_name, token):
                released.append(repo_name)

            real_write = start._write_json_atomic

            def failing_log_write(path, payload, *a, **kw):
                if path.parent == log_dir:
                    raise OSError("disk full")
                return real_write(path, payload, *a, **kw)

            with mock.patch.object(progress.start, "_write_json_atomic", side_effect=failing_log_write):
                calls_a, fns_a = stage_spies()
                progress.run_auto_progress_once(**kwargs_for(report_a, candidate_a, state, reserve, release, **fns_a))
                self.assertEqual(len(calls_a), 5)
                self.assertFalse(any(log_dir.iterdir())) if log_dir.is_dir() else None  # the record never landed
                self.assertTrue(state.has_attempted("next-day-setup", SHA))
                self.assertEqual(state.daily_count("2026-02-01"), 1)

                calls_b, fns_b = stage_spies()
                progress.run_auto_progress_once(**kwargs_for(report_b, candidate_b, state, reserve, release, **fns_b))
                self.assertEqual(len(calls_b), 5)
                self.assertEqual(state.daily_count("2026-02-01"), 2)

                calls_c, fns_c = stage_spies()
                outcome_c = progress.run_auto_progress_once(
                    **kwargs_for(report_a, candidate_a, state, reserve, release, **fns_c))
                self.assertEqual(calls_c, [])
                self.assertEqual(outcome_c.status, progress.STATUS_LIMIT_REACHED)

            self.assertEqual(len(reserved), 2)
            self.assertEqual(len(released), 2)  # released every time despite the log write failing

    # ------------------------------------------------------------------ C10
    def test_startup_blocked_until_corrupt_daily_count_file_is_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            daily_path = tmp / "daily.json"
            daily_path.write_text("not json{{{", encoding="utf-8")
            state = progress.ProgressState(daily_count_path=daily_path, attempted_index_path=tmp / "attempted.json")
            calls, fns = stage_spies()
            outcome = progress.run_auto_progress_once(**fx.kwargs(state=state, **fns))
            self.assertEqual(outcome.status, progress.STATUS_STARTUP_BLOCKED)
            self.assertEqual(calls, [])
            self.assertFalse(state.startup_seeded)
            daily_path.unlink()  # fixed -- a later cycle must succeed
            outcome2 = progress.run_auto_progress_once(**fx.kwargs(state=state, **fns))
            self.assertNotEqual(outcome2.status, progress.STATUS_STARTUP_BLOCKED)
            self.assertTrue(state.startup_seeded)

    def test_startup_blocked_until_corrupt_attempted_index_is_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            attempted_path = tmp / "attempted.json"
            attempted_path.write_text(json.dumps({"entries": [1, 2, 3]}), encoding="utf-8")
            state = progress.ProgressState(daily_count_path=tmp / "daily.json", attempted_index_path=attempted_path)
            calls, fns = stage_spies()
            outcome = progress.run_auto_progress_once(**fx.kwargs(state=state, **fns))
            self.assertEqual(outcome.status, progress.STATUS_STARTUP_BLOCKED)
            self.assertEqual(calls, [])

    # ------------------------------------------------------------------ C11
    def test_missing_association_is_needs_human_not_a_normal_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            # Overwrite with no association saved at all.
            shutil.rmtree(fx.records_dir)
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))
            self.assertFalse(fx.state.has_attempted(fx.app_key, fx.sha))

    def test_empty_run_id_association_is_needs_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            save_association(fx.records_dir, fx.app_key, fx.report_id, "")  # run_id missing
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    def test_stale_decision_while_candidate_changed_is_needs_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            different = make_candidate(SHA2, "run-DIFFERENT")  # live candidate no longer matches the association
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(latest_candidate_fn=lambda repo: different, **fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    def test_decision_sha_mismatch_is_needs_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            # The live candidate's SHA no longer matches what the stored decision was computed for.
            mismatched = make_candidate(SHA2, fx.run_id)
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(latest_candidate_fn=lambda repo: mismatched, **fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    def test_decision_payload_missing_is_needs_human(self):
        """Finding 4: a report this app is permitted for, but that Task 19c-1 has not (yet, or
        never will) written a decision for, must never be a silent "not a candidate" skip."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            shutil.rmtree(fx.results_dir)  # no decision file at all for this report
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))
            self.assertFalse(fx.state.has_attempted(fx.app_key, fx.sha))

    def test_decision_payload_malformed_is_needs_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            path = approve._result_path(fx.app_key, fx.report_id, fx.results_dir)
            start._write_json_atomic(path, {"this": "is not a valid decision payload"})
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    def test_legacy_decision_without_full_sha_or_run_id_is_needs_human(self):
        """A decision recorded before candidate_full/run_id existed (or written by some other
        caller without them) must never be treated as still applicable, even though
        _payload_decision considers it well-formed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            path = approve._result_path(fx.app_key, fx.report_id, fx.results_dir)
            start._write_json_atomic(path, {"app": fx.app_key, "candidate": fx.sha[:12], "result": approve.ELIGIBLE,
                                            "reasons": [], "files": 1, "lines": 2})
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    def test_decision_with_colliding_short_sha_prefix_is_needs_human(self):
        """The old prefix-match (`sha.startswith(decision.candidate)`) would have accepted this:
        SHA_PREFIX_COLLISION shares SHA's first 12 hex characters but is a different full SHA.
        The strict full-SHA equality check must reject it."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp, sha=SHA)
            save_decision(fx.results_dir, fx.app_key, fx.report_id, SHA_PREFIX_COLLISION, run_id=fx.run_id)
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))  # live candidate is still SHA
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    def test_decision_run_id_mismatch_is_needs_human(self):
        """The decision's own full SHA matches the live candidate, but it was computed against a
        different run_id -- must still be rejected, not just a SHA-level check."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fx = Fixture(tmp)
            save_decision(fx.results_dir, fx.app_key, fx.report_id, fx.sha, run_id="run-OTHER")
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(calls, [])
            self.assertTrue(any(e["state"] == progress.STATE_NEEDS_HUMAN for e in fx.log_entries()))

    # ------------------------------------------------------------------ C12
    def test_busy_repo_waits_and_runs_next_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(active_runs_fn=lambda repo: ["busy-run"], **fns))
            self.assertEqual(calls, [])
            progress.run_auto_progress_once(**fx.kwargs(active_runs_fn=lambda repo: [], **fns))
            self.assertEqual(len(calls), 5)

    def test_unconfirmable_active_run_check_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))

            def boom(_repo):
                raise RuntimeError("cannot confirm")

            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(active_runs_fn=boom, **fns))
            self.assertEqual(calls, [])

    def test_reservation_conflict_blocks_and_next_cycle_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(reserve_fn=lambda repo_name: None, **fns))
            self.assertEqual(calls, [])
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertEqual(len(calls), 5)

    def test_one_app_busy_does_not_block_another_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            busy_app, free_app = "next-day-setup", "menu-sheet-generator"
            fx_busy = Fixture(tmp / "busy", app_key=busy_app)
            fx_free = Fixture(tmp / "free", app_key=free_app)
            reports = [fx_busy.report, fx_free.report]

            def resolve_repo_dir(app_key):
                return fx_busy.repo_dir if app_key == busy_app else fx_free.repo_dir

            def resolve_repo_definition(name):
                return fx_busy.definition if name == busy_app else fx_free.definition

            def latest_candidate(repo):
                return fx_busy.candidate_obj if repo == fx_busy.repo_dir else fx_free.candidate_obj

            def active_runs(repo):
                return ["busy"] if repo == str(fx_busy.repo_dir) else []

            calls, fns = stage_spies()
            # Both apps' decisions/associations were saved under their own Fixture's dirs above;
            # _select_candidate looks them up per-report via results_dir/records_dir, so either
            # fixture's directories work as long as both reports were saved somewhere findable.
            # Save the free app's decision/association under the busy fixture's own dirs too, so
            # one results_dir/records_dir pair covers both reports for this cycle.
            save_decision(fx_busy.results_dir, free_app, fx_free.report_id, fx_free.sha, run_id=fx_free.run_id)
            save_association(fx_busy.records_dir, free_app, fx_free.report_id, fx_free.run_id)
            progress.run_auto_progress_once(
                state=progress.ProgressState(daily_count_path=tmp / "daily.json",
                                             attempted_index_path=tmp / "attempted.json"),
                global_config=auto.AutoModeConfig(enabled=True),
                start_config=start.AutoStartConfig(apps={busy_app: True, free_app: True}),
                approve_config=approve.ApprovalConfig(apps={busy_app: True, free_app: True}, daily_limit=2),
                today="2026-02-01", reports_config_fn=reports_config_for([busy_app, free_app]),
                scan_fn=scan_fn_for(reports), records_dir=fx_busy.records_dir, results_dir=fx_busy.results_dir,
                resolve_repo_dir=resolve_repo_dir, resolve_repo_definition=resolve_repo_definition,
                active_runs_fn=active_runs, latest_candidate_fn=latest_candidate, log_dir=tmp / "log", **fns)
            self.assertEqual(len(calls), 5)

    # ------------------------------------------------------------------ C13
    def test_record_is_fixed_words_and_numbers_only_and_marked_auto_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            entries = fx.log_entries()
            self.assertTrue(entries)
            allowed_states = {progress.STATE_IN_PROGRESS, progress.STATE_RELEASE_READY, progress.STATE_NEEDS_HUMAN,
                              progress.LIMIT_REACHED_TEXT}
            allowed_results = {progress.RESULT_OK, progress.RESULT_FAIL}
            for entry in entries:
                self.assertEqual(set(entry.keys()),
                                 {"at", "kind", "app", "candidate", "state", "stages", "failed_stage", "files", "lines"})
                self.assertEqual(entry["kind"], progress.RECORD_KIND)
                self.assertIn(entry["state"], allowed_states)
                for stage_name, result in entry["stages"].items():
                    self.assertIn(stage_name, progress.STAGES)
                    self.assertIn(result, allowed_results)
                self.assertIsInstance(entry["files"], int)
                self.assertIsInstance(entry["lines"], int)

    # ------------------------------------------------------------------ C14
    def test_release_is_never_called(self):
        # RELEASE/execute is simply not one of the 5 known stages -- the chain structurally
        # cannot reach it; this only confirms the success path still stops at the dry-run plan.
        self.assertNotIn("RELEASE", progress.STAGES)
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(Path(tmp))
            calls, fns = stage_spies()
            progress.run_auto_progress_once(**fx.kwargs(**fns))
            self.assertNotIn("RELEASE", calls)
            self.assertEqual(calls[-1], progress.STAGE_DRY_RUN)  # the chain stops at the plan, never beyond


class ProgressStateTests(unittest.TestCase):
    # ------------------------------------------------------------------ C9/C10 (unit-level)
    def test_seed_startup_succeeds_on_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = progress.ProgressState(daily_count_path=tmp / "d.json", attempted_index_path=tmp / "a.json")
            self.assertTrue(state.seed_startup("2026-02-01"))
            self.assertEqual(state.daily_count("2026-02-01"), 0)

    def test_record_daily_attempt_survives_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = progress.ProgressState(daily_count_path=tmp / "d.json", attempted_index_path=tmp / "a.json")
            state.seed_startup("2026-02-01")
            with mock.patch.object(progress.start, "_write_json_atomic", side_effect=OSError("disk full")):
                total = state.record_daily_attempt("2026-02-01")
            self.assertEqual(total, 1)
            self.assertEqual(state.daily_count("2026-02-01"), 1)

    def test_mark_attempted_survives_write_failure_and_is_remembered(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = progress.ProgressState(daily_count_path=tmp / "d.json", attempted_index_path=tmp / "a.json")
            state.seed_startup("2026-02-01")
            with mock.patch.object(progress.start, "_write_json_atomic", side_effect=OSError("disk full")):
                state.mark_attempted("app", SHA)
            self.assertTrue(state.has_attempted("app", SHA))


class DefaultStageAdaptersTests(unittest.TestCase):
    """Finding 7: the default stage runners must go through exactly the same plain functions the
    manual DCC buttons call underneath their own subprocess wrapper -- never a re-assembled
    command, never a new execution path. Every external effect (git, subprocess, filesystem
    writes under provenance/release_update) is mocked; nothing here touches a real repo."""

    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = Path(self.tmp_ctx.name)
        self.repo_dir = self.tmp / "repo"
        self.definition = make_definition(name="next-day-setup")  # has a real provenance.PROFILES entry
        self.candidate_obj = make_candidate(SHA, "run-1")

    def test_default_run_dev_calls_candidate_run_dev(self):
        from scripts.dev_control_center import candidate
        with mock.patch.object(candidate, "run_dev", return_value=0) as run_dev:
            self.assertTrue(progress._default_run_dev(self.repo_dir, self.definition.branch, SHA))
        run_dev.assert_called_once_with(self.repo_dir, self.definition.branch, SHA)

    def test_default_run_dev_nonzero_returncode_is_failure(self):
        from scripts.dev_control_center import candidate
        with mock.patch.object(candidate, "run_dev", return_value=1):
            self.assertFalse(progress._default_run_dev(self.repo_dir, self.definition.branch, SHA))

    def test_default_approve_calls_candidate_approve(self):
        from scripts.dev_control_center import candidate
        with mock.patch.object(candidate, "approve") as approve_fn:
            self.assertTrue(progress._default_approve(self.candidate_obj, SHA))
        approve_fn.assert_called_once_with(self.candidate_obj, SHA)

    def test_default_push_calls_candidate_push(self):
        from scripts.dev_control_center import candidate
        with mock.patch.object(candidate, "push") as push_fn:
            self.assertTrue(progress._default_push(self.repo_dir, self.definition.branch, SHA))
        push_fn.assert_called_once_with(self.repo_dir, self.definition.branch, SHA)

    def test_default_build_calls_provenance_build_with_manual_shared_body(self):
        from scripts.dev_control_center import provenance, entrypoints as machine_entries, core
        entry_choice = core.EntryPointChoice(state="READY", path=self.repo_dir / "entry.py")
        entries = SimpleNamespace(build=entry_choice)
        with mock.patch.object(machine_entries, "supported", return_value=True), \
                mock.patch.object(core, "discover_entrypoints", return_value=entries), \
                mock.patch.object(provenance, "build", return_value={"status": "ready"}) as build_fn:
            self.assertTrue(progress._default_build(self.repo_dir, self.definition, self.candidate_obj))
        build_fn.assert_called_once()
        args, kwargs = build_fn.call_args
        self.assertEqual(args[0], self.repo_dir)
        self.assertEqual(args[1], entry_choice.path)
        self.assertEqual(kwargs["expected_sha"], self.candidate_obj.sha)
        self.assertEqual(kwargs["candidate_run_id"], self.candidate_obj.run_id)
        self.assertEqual(kwargs["expected_branch"], self.definition.branch)

    def test_default_build_returns_false_when_no_profile_or_not_ready(self):
        from scripts.dev_control_center import provenance, entrypoints as machine_entries, core
        other_definition = make_definition(name="an-app-with-no-profile")
        self.assertFalse(progress._default_build(self.repo_dir, other_definition, self.candidate_obj))
        entry_choice = core.EntryPointChoice(state="NOT_FOUND")
        entries = SimpleNamespace(build=entry_choice)
        with mock.patch.object(machine_entries, "supported", return_value=True), \
                mock.patch.object(core, "discover_entrypoints", return_value=entries), \
                mock.patch.object(provenance, "build") as build_fn:
            self.assertFalse(progress._default_build(self.repo_dir, self.definition, self.candidate_obj))
        build_fn.assert_not_called()

    def test_default_dry_run_calls_release_update_plan_with_manual_shared_body(self):
        from scripts.dev_control_center import provenance, release_update
        from scripts.dev_control_center import candidate as candidate_flow
        with mock.patch.object(candidate_flow, "_read_json", return_value={"target": "C:/dist"}), \
                mock.patch.object(provenance, "production_record_path", return_value=self.tmp / "prod.json"), \
                mock.patch.object(release_update, "plans_dir", return_value=self.tmp), \
                mock.patch.object(release_update, "plan", return_value={}) as plan_fn:
            self.assertTrue(progress._default_dry_run(self.repo_dir, self.definition, self.candidate_obj))
        plan_fn.assert_called_once()
        args, kwargs = plan_fn.call_args
        self.assertEqual(args[0], self.repo_dir)
        self.assertEqual(args[1], Path("C:/dist"))
        self.assertEqual(kwargs["branch"], self.definition.branch)

    def test_default_dry_run_false_when_no_production_target_or_stop_reasons(self):
        from scripts.dev_control_center import provenance, release_update
        from scripts.dev_control_center import candidate as candidate_flow
        with mock.patch.object(candidate_flow, "_read_json", return_value={}):
            self.assertFalse(progress._default_dry_run(self.repo_dir, self.definition, self.candidate_obj))
        with mock.patch.object(candidate_flow, "_read_json", return_value={"target": "C:/dist"}), \
                mock.patch.object(provenance, "production_record_path", return_value=self.tmp / "prod.json"), \
                mock.patch.object(release_update, "plans_dir", return_value=self.tmp), \
                mock.patch.object(release_update, "plan", return_value={"stop_reasons": ["some reason"]}):
            self.assertFalse(progress._default_dry_run(self.repo_dir, self.definition, self.candidate_obj))


class AutoProgressAppWiringTests(unittest.TestCase):
    """Findings 2/6: the real DCC process (app.py) must re-read the actual per-app/global config
    on every boundary check (never a frozen snapshot), and its auto-progress background thread
    must share one atomic reservation with the manual RUN_DEV/push/BUILD/UPDATE buttons. Fakes
    only: threading.Thread and run_auto_progress_once are both mocked, so no real Tk widget, AI,
    Orchestrator, or subprocess runs."""

    def test_loop_passes_all_three_config_paths_and_shares_atomic_reservation(self):
        from scripts.dev_control_center import app, reports_auto, reports_auto_approve, reports_auto_start
        from scripts.dev_control_center import reports_auto_progress as progress_mod

        instance = app.App.__new__(app.App)
        instance._closed = False
        instance._auto_progress_stop = mock.Mock(is_set=mock.Mock(side_effect=[False, True]))
        instance._auto_progress_state = mock.Mock()
        instance._repo_name_busy = mock.Mock(return_value=False)
        app.ACTIVE_OPERATIONS.clear()
        try:
            with mock.patch.object(app.threading, "Thread") as thread, \
                    mock.patch.object(progress_mod, "run_auto_progress_once") as run_once:
                instance._start_auto_progress_loop()
                thread.call_args.kwargs["target"]()

            run_once.assert_called_once()
            kwargs = run_once.call_args.kwargs
            self.assertEqual(kwargs["global_config_path"], reports_auto.auto_mode_config_path())
            self.assertEqual(kwargs["start_config_path"], reports_auto_start.auto_start_config_path())
            self.assertEqual(kwargs["approve_config_path"], reports_auto_approve.config_path())

            reserve_fn, release_fn = kwargs["reserve_fn"], kwargs["release_fn"]
            token = reserve_fn("some-repo")
            self.assertIsNotNone(token)
            # The manual side's own atomic helper must see this same reservation (shared dict,
            # shared lock) -- a conflicting manual reservation for the same repo must fail.
            self.assertIsNone(app._reserve_active_operation("some-repo", "manual-test"))
            release_fn("some-repo", token)
            self.assertIsNotNone(app._reserve_active_operation("some-repo", "manual-test"))
        finally:
            app.ACTIVE_OPERATIONS.clear()

    def test_reserve_active_operation_is_atomic_check_and_insert(self):
        from scripts.dev_control_center import app

        app.ACTIVE_OPERATIONS.clear()
        try:
            token = app._reserve_active_operation("repo-x", "manual")
            self.assertIsNotNone(token)
            self.assertIsNone(app._reserve_active_operation("repo-x", "auto-progress"))  # already reserved
            app._release_active_operation(token)
            self.assertIsNotNone(app._reserve_active_operation("repo-x", "auto-progress"))
        finally:
            app.ACTIVE_OPERATIONS.clear()


class PreparedOperationSharesTheAtomicReservationTests(unittest.TestCase):
    """Review finding: the manual approve/discard/combined-run path (`App._prepare_operation`,
    reached from `approve_candidate`/`discard_candidate`/`launch`) was inserting its own "-check"
    token into ACTIVE_OPERATIONS unconditionally, never checking it against an existing
    reservation first -- so it could never see the Task 19c-2a auto-progress background thread's
    own "auto-progress" reservation (or vice versa) as busy. This drives the real
    `App._prepare_operation` method (not a re-implemented stand-in): only `threading.Thread`'s
    target is pumped inline via the app's own `_drain_lifecycle_events`, no real Tk widget,
    subprocess, or network."""

    def setUp(self):
        from scripts.dev_control_center import app

        self.app_mod = app
        app.ACTIVE_OPERATIONS.clear()
        self.addCleanup(app.ACTIVE_OPERATIONS.clear)
        self.ui = app.App.__new__(app.App)
        self.ui.lifecycle_events = queue.Queue()
        self.logged: list[str] = []
        self.ui._log = lambda text: self.logged.append(text)
        self.ui.banner_var = mock.Mock()
        self.ui._set_button_states = lambda: None

    def pump_until(self, condition, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.ui._drain_lifecycle_events()
            time.sleep(0.01)
        self.assertTrue(condition())

    def test_refused_while_the_auto_progress_reservation_holds_the_repo(self):
        repo_name = "prep-op-app"
        auto_token = self.app_mod._reserve_active_operation(repo_name, "auto-progress")
        self.assertIsNotNone(auto_token)

        work, ready = mock.Mock(), mock.Mock()
        self.ui._prepare_operation(repo_name, "approve", work, ready)

        # The conflicting reservation must refuse this call before `work` ever starts -- not
        # merely insert a second, unchecked "-check" entry alongside the auto-progress one.
        work.assert_not_called()
        ready.assert_not_called()
        self.assertTrue(any("競合する操作があるため開始しません" in line for line in self.logged))
        self.assertEqual(self.app_mod.ACTIVE_OPERATIONS, {id(auto_token): (repo_name, "auto-progress")})

    def test_on_error_runs_when_the_reservation_is_refused(self):
        repo_name = "prep-op-app"
        auto_token = self.app_mod._reserve_active_operation(repo_name, "auto-progress")
        self.assertIsNotNone(auto_token)

        on_error = mock.Mock()
        self.ui._prepare_operation(repo_name, "build", mock.Mock(), mock.Mock(), on_error=on_error)
        on_error.assert_called_once()

    def test_resumes_once_the_auto_progress_reservation_is_released(self):
        repo_name = "prep-op-app"
        auto_token = self.app_mod._reserve_active_operation(repo_name, "auto-progress")
        self.ui._prepare_operation(repo_name, "discard", mock.Mock(), mock.Mock())
        self.app_mod._release_active_operation(auto_token)

        work, ready = mock.Mock(return_value="ok"), mock.Mock()
        self.ui._prepare_operation(repo_name, "discard", work, ready)
        self.pump_until(lambda: ready.call_count == 1)
        work.assert_called_once()
        ready.assert_called_once_with("ok")
        self.assertEqual(self.app_mod.ACTIVE_OPERATIONS, {})


if __name__ == "__main__":
    unittest.main()
