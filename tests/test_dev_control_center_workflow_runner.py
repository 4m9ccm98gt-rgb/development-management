"""DCC Task WF-2: workflow execution (workflow_runner.py).

Every test here uses only fakes/temp dirs: resolve_repo_dir, busy_fn, repo_run_blocked_fn,
create_and_start_fn, start_run_fn, run_lookup_fn and is_landed_fn are always injected -- never the
real Tk, AI, Orchestrator, candidate.py git plumbing, or the real %LOCALAPPDATA%. No network, no
subprocess, no git. Output files live under tempfile.TemporaryDirectory() only.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev_control_center import reports_auto as auto
from scripts.dev_control_center import reports_create_and_start as cas
from scripts.dev_control_center import workflow_plan as wf
from scripts.dev_control_center import workflow_runner as wr

KEYS = frozenset({"sample-repo"})
BODY = "対象リポジトリ: sample-repo\n\n## 受入条件\n- 正しい結果が表示されること\n\n## 範囲外\n- 実行\n"
TODAY = "2026-01-01"


def task(tid="T1", **fields):
    base = dict(task_id=tid, title="表示の修正", repo_key="sample-repo", body=BODY,
                depends_on=[], status="approved")
    base.update(fields)
    return base


def plan(*tasks, plan_id="Plan-1"):
    return dict(plan_id=plan_id, name="開発計画", revision=0, tasks=list(tasks))


class ConfigTests(unittest.TestCase):
    def test_default_config_is_all_off(self):
        config = wr.WorkflowRunnerConfig()
        self.assertEqual(config.plans, {})
        self.assertEqual(config.daily_limit, wr.DEFAULT_DAILY_LIMIT)

    def test_missing_file_loads_as_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = wr.load_workflow_runner_config(Path(tmp) / "no-such-config.json")
            self.assertEqual(config.plans, {})

    def test_corrupt_file_degrades_to_defaults_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("not json{{{", encoding="utf-8")
            config = wr.load_workflow_runner_config(path)
            self.assertEqual(config.plans, {})

    def test_set_plan_auto_run_allowed_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            wr.set_plan_auto_run_allowed("Plan-1", True, path=path)
            config = wr.load_workflow_runner_config(path)
            self.assertTrue(config.plans.get("Plan-1"))


class DailyLimitReachedReadOnlyCheckTests(unittest.TestCase):
    """wr.daily_limit_reached: workflow_plan_view.py's own read-only display check (DCC Task
    WF-3a), mirroring reports_auto.daily_limit_reached's convention -- never gates the real
    execution loop (WorkflowRunnerState.seed_startup's own strict read does that)."""

    def test_missing_file_is_not_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(wr.daily_limit_reached(TODAY, 1, path=Path(tmp) / "no-such-file.json"))

    def test_count_below_limit_is_not_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            path.write_text('{"date": "%s", "count": 1}' % TODAY, encoding="utf-8")
            self.assertFalse(wr.daily_limit_reached(TODAY, 2, path=path))

    def test_count_at_or_above_limit_is_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            path.write_text('{"date": "%s", "count": 2}' % TODAY, encoding="utf-8")
            self.assertTrue(wr.daily_limit_reached(TODAY, 2, path=path))

    def test_a_different_date_in_the_file_is_not_reached(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            path.write_text('{"date": "2025-01-01", "count": 99}', encoding="utf-8")
            self.assertFalse(wr.daily_limit_reached(TODAY, 1, path=path))

    def test_corrupt_file_degrades_to_not_reached_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "count.json"
            path.write_text("not json{{{", encoding="utf-8")
            self.assertFalse(wr.daily_limit_reached(TODAY, 1, path=path))

    def test_plan_auto_run_allowed_requires_both_global_switch_and_own_permission(self):
        both_off = auto.AutoModeConfig(enabled=False)
        plan_off = wr.WorkflowRunnerConfig(plans={"Plan-1": False})
        plan_on = wr.WorkflowRunnerConfig(plans={"Plan-1": True})
        self.assertFalse(wr.plan_auto_run_allowed(both_off, plan_on, "Plan-1"))
        self.assertFalse(wr.plan_auto_run_allowed(auto.AutoModeConfig(enabled=True), plan_off, "Plan-1"))
        self.assertTrue(wr.plan_auto_run_allowed(auto.AutoModeConfig(enabled=True), plan_on, "Plan-1"))


class WorkflowRunnerStateTests(unittest.TestCase):
    def test_seed_startup_succeeds_on_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = wr.WorkflowRunnerState(daily_count_path=Path(tmp) / "daily.json")
            self.assertTrue(state.seed_startup(TODAY))
            self.assertEqual(state.daily_count(TODAY), 0)

    # ------------------------------------------------------------------ C11
    def test_startup_blocked_until_corrupt_daily_count_file_is_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily_path = Path(tmp) / "daily.json"
            daily_path.write_text("not json{{{", encoding="utf-8")
            state = wr.WorkflowRunnerState(daily_count_path=daily_path)
            self.assertFalse(state.seed_startup(TODAY))
            self.assertFalse(state.startup_seeded)
            daily_path.unlink()
            self.assertTrue(state.seed_startup(TODAY))
            self.assertTrue(state.startup_seeded)

    # ------------------------------------------------------------------ C10 (count half)
    def test_record_daily_attempt_survives_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = wr.WorkflowRunnerState(daily_count_path=Path(tmp) / "daily.json")
            state.seed_startup(TODAY)
            with mock.patch.object(wr.start, "_write_json_atomic", side_effect=OSError("disk full")):
                total = state.record_daily_attempt(TODAY)
            self.assertEqual(total, 1)
            self.assertEqual(state.daily_count(TODAY), 1)


class RunWorkflowRunnerOnceTests(unittest.TestCase):
    def _save_plan(self, tmp: Path, p: dict) -> None:
        wf.save_plan(p, root=tmp / "plans", registered_keys=KEYS)

    def _load_plan(self, tmp: Path, plan_id="Plan-1") -> dict:
        return wf.load_plan(plan_id, root=tmp / "plans", registered_keys=KEYS)

    def _state(self, tmp: Path) -> wr.WorkflowRunnerState:
        return wr.WorkflowRunnerState(daily_count_path=tmp / "daily.json")

    def _fake_create_and_start(self, calls, *, ok=True, reason="", run_dir=None):
        def fn(shim, criteria_lines, **kwargs):
            calls.append((shim.app_key, shim.identity, criteria_lines, kwargs.get("main_agent"),
                         kwargs.get("review_agent"), kwargs["task_text_fn"](shim)))
            return cas.StartResult(ok, reason, run_dir=run_dir if ok else None)
        return fn

    def _run(self, tmp: Path, *, state, global_config=None, runner_config=None, global_config_path=None,
              runner_config_path=None, create_and_start_fn=None, busy_fn=None, repo_run_blocked_fn=None,
              reserve_fn=None, release_fn=None, run_lookup_fn=None, is_landed_fn=None, start_run_fn=None,
              today=TODAY, stop_event=None, default_main_agent=None, default_review_agent=None):
        return wr.run_workflow_runner_once(
            state=state, today=today, global_config=global_config, global_config_path=global_config_path,
            runner_config=runner_config, runner_config_path=runner_config_path,
            plans_root=tmp / "plans", registered_keys=KEYS, records_dir=tmp / "records", log_dir=tmp / "log",
            resolve_repo_dir=lambda k: tmp / "repos" / k,
            busy_fn=busy_fn if busy_fn is not None else (lambda n: False),
            repo_run_blocked_fn=repo_run_blocked_fn if repo_run_blocked_fn is not None else (lambda r: False),
            reserve_fn=reserve_fn, release_fn=release_fn,
            create_and_start_fn=create_and_start_fn, start_run_fn=start_run_fn,
            run_lookup_fn=run_lookup_fn, is_landed_fn=is_landed_fn, stop_event=stop_event,
            default_main_agent=default_main_agent, default_review_agent=default_review_agent,
        )

    # ------------------------------------------------------------------ C1
    def test_global_switch_off_never_calls_create_and_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            outcome = self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, wr.STATUS_DISABLED)

    def test_plan_permission_off_never_calls_create_and_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            outcome = self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}),
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, wr.STATUS_DONE)

    # ------------------------------------------------------------------ C2
    def test_approved_task_with_landed_deps_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task("T1", status="landed"), task("T2", depends_on=["T1"])))
            calls = []
            outcome = self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], ("Plan-1", "T2"))
            self.assertEqual(outcome.status, wr.STATUS_DONE)
            reloaded = self._load_plan(tmp)
            self.assertEqual(next(t for t in reloaded["tasks"] if t["task_id"] == "T2")["status"], "running")

    def test_unmet_dependency_or_wrong_status_does_not_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # T1 is not yet approved/landed; T2 depends on it and must not be picked.
            self._save_plan(tmp, plan(task("T1", status="proposed"), task("T2", depends_on=["T1"])))
            calls = []
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(calls, [])

    # ------------------------------------------------------------------ C3/C12
    def test_plan_paused_when_any_task_is_hot(self):
        for blocking_status in ("running", "candidate_ready", "failed", "needs_human"):
            with self.subTest(status=blocking_status):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp = Path(tmp)
                    self._save_plan(tmp, plan(task("T1", status=blocking_status), task("T2")))
                    calls = []
                    self._run(
                        tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                        runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                        create_and_start_fn=self._fake_create_and_start(calls))
                    self.assertEqual(calls, [])

    def test_human_reapproval_unpauses_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task("T1", status="failed")))
            calls = []
            cfg = dict(state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                      runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                      create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self._run(tmp, **cfg)
            self.assertEqual(calls, [])  # still paused
            p = self._load_plan(tmp)
            p = wf.apply_proposal(p, dict(plan_id="Plan-1", base_revision=p["revision"],
                                          ops=[{"op": "approve", "task_id": "T1"}]), actor="human",
                                  registered_keys=KEYS)[0]
            wf.save_plan(p, root=tmp / "plans", registered_keys=KEYS)
            self._run(tmp, **cfg)
            self.assertEqual(len(calls), 1)  # human reset to approved -- now it may start again

    # ------------------------------------------------------------------ C4
    def test_busy_repo_waits_then_starts_next_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            busy = [True]
            cfg = dict(state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                      runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                      repo_run_blocked_fn=lambda r: busy[0],
                      create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self._run(tmp, **cfg)
            self.assertEqual(calls, [])
            busy[0] = False
            self._run(tmp, **cfg)
            self.assertEqual(len(calls), 1)

    def test_unconfirmable_busy_check_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []

            def raiser(_repo):
                raise RuntimeError("cannot confirm")

            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}), repo_run_blocked_fn=raiser,
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(calls, [])

    # ------------------------------------------------------------------ C5
    def _fake_create_and_start_invoking_start_run(self, calls, started_real):
        from tools.ai_orchestrator.runstate import ActiveRunExists

        def fn(shim, criteria_lines, **kwargs):
            calls.append(shim.identity)
            try:
                run_dir = kwargs["start_run"](repo="x", task="t", main_agent="claude", review_agent="codex",
                                              spec=None)
            except ActiveRunExists:
                return cas.StartResult(False, cas.REASON_ALREADY_RUNNING)
            started_real.append(run_dir)
            return cas.StartResult(True, "", run_dir=run_dir)
        return fn

    def test_switch_flipped_during_start_aborts_and_is_retried_once_back_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            global_path = tmp / "global.json"
            runner_path = tmp / "runner.json"
            auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), path=global_path)
            wr.save_workflow_runner_config(wr.WorkflowRunnerConfig(plans={"Plan-1": True}), path=runner_path)
            self._save_plan(tmp, plan(task()))
            calls, started_real = [], []

            def create_and_start_fn(shim, criteria_lines, **kwargs):
                # Simulate create_and_start_fn's own spec-file creation taking long enough for a
                # human to flip the plan's permission off before the real start_run would run.
                wr.set_plan_auto_run_allowed("Plan-1", False, path=runner_path)
                return self._fake_create_and_start_invoking_start_run(calls, started_real)(shim, criteria_lines,
                                                                                            **kwargs)

            outcome = self._run(
                tmp, state=self._state(tmp), global_config_path=global_path, runner_config_path=runner_path,
                create_and_start_fn=create_and_start_fn, start_run_fn=lambda **kw: Path("/fake/run-dir"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(started_real, [])
            self.assertEqual(outcome.status, wr.STATUS_DONE)
            reloaded = self._load_plan(tmp)
            self.assertEqual(reloaded["tasks"][0]["status"], "approved")  # undone -- eligible again

            wr.set_plan_auto_run_allowed("Plan-1", True, path=runner_path)
            self._run(
                tmp, state=self._state(tmp), global_config_path=global_path, runner_config_path=runner_path,
                create_and_start_fn=self._fake_create_and_start_invoking_start_run(calls, started_real),
                start_run_fn=lambda **kw: Path("/fake/run-dir"))
            self.assertEqual(len(started_real), 1)
            reloaded2 = self._load_plan(tmp)
            self.assertEqual(reloaded2["tasks"][0]["status"], "running")

    # ------------------------------------------------------------------ C6
    def test_entry_point_called_once_with_body_derived_criteria_and_agent_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(main_ai="codex", reviewer_ai="claude")))
            calls = []
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")),
                default_main_agent="claude", default_review_agent="codex")
            self.assertEqual(len(calls), 1)
            app_key, identity, criteria_lines, main_agent, review_agent, text = calls[0]
            self.assertEqual(app_key, "sample-repo")
            self.assertEqual(identity, ("Plan-1", "T1"))
            self.assertEqual(criteria_lines, ["正しい結果が表示されること"])
            self.assertEqual(main_agent, "codex")
            self.assertEqual(review_agent, "claude")
            self.assertEqual(text, BODY)

    def test_entry_point_uses_default_agents_when_task_has_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")),
                default_main_agent="claude", default_review_agent="codex")
            self.assertEqual(calls[0][3], "claude")
            self.assertEqual(calls[0][4], "codex")

    # ------------------------------------------------------------------ C7
    def test_run_outcome_reflected_into_status_with_fixed_reason(self):
        cases = [
            ("completed", "OK", "candidate_ready", ""),
            ("needs_human", "REVIEWER_NEEDS_HUMAN", "needs_human", "REVIEWER_NEEDS_HUMAN"),
            ("failed", "TASK_BLOCKED", "failed", "TASK_BLOCKED"),
            ("stopped", "PROVIDER_QUOTA", "failed", "PROVIDER_QUOTA"),
        ]
        for stage, code, expected_status, expected_reason in cases:
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp = Path(tmp)
                    self._save_plan(tmp, plan(task(status="running")))
                    wr._save_record("Plan-1", "T1", run_id="run-1", reason="", candidate_sha="",
                                    root=tmp / "records")
                    self._run(
                        tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                        runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}),
                        run_lookup_fn=lambda _rid, _s=stage, _c=code: {
                            "stage": _s, "final_result": {"code": _c}, "candidate_sha": "a" * 40})
                    reloaded = self._load_plan(tmp)
                    self.assertEqual(reloaded["tasks"][0]["status"], expected_status)
                    record = wr._load_record("Plan-1", "T1", root=tmp / "records")
                    self.assertEqual(record["reason"], expected_reason)

    def test_unknown_reason_code_is_shape_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(status="running")))
            wr._save_record("Plan-1", "T1", run_id="run-1", reason="", candidate_sha="", root=tmp / "records")
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}),
                run_lookup_fn=lambda _rid: {"stage": "failed",
                                           "final_result": {"code": "この文は自由なAI出力です"}})
            record = wr._load_record("Plan-1", "T1", root=tmp / "records")
            self.assertEqual(record["reason"], wr.REASON_UNKNOWN)

    def test_unreadable_run_record_leaves_status_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(status="running")))
            wr._save_record("Plan-1", "T1", run_id="run-1", reason="", candidate_sha="", root=tmp / "records")

            def raiser(_rid):
                raise RuntimeError("cannot read")

            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}), run_lookup_fn=raiser)
            reloaded = self._load_plan(tmp)
            self.assertEqual(reloaded["tasks"][0]["status"], "running")

    # ------------------------------------------------------------------ C8
    def test_candidate_ready_becomes_landed_only_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(status="candidate_ready")))
            wr._save_record("Plan-1", "T1", run_id="run-1", reason="", candidate_sha="abc123",
                            root=tmp / "records")
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}),
                is_landed_fn=lambda *a: False)
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "candidate_ready")

            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}),
                is_landed_fn=lambda *a: True)
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "landed")

    def test_candidate_ready_unconfirmable_landed_check_stays_candidate_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(status="candidate_ready")))
            wr._save_record("Plan-1", "T1", run_id="run-1", reason="", candidate_sha="abc123",
                            root=tmp / "records")

            def raiser(*_a):
                raise RuntimeError("cannot confirm")

            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}), is_landed_fn=raiser)
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "candidate_ready")

    # ------------------------------------------------------------------ C9
    def test_daily_limit_reached_blocks_start_and_records_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            outcome = self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}, daily_limit=0),
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(calls, [])
            self.assertEqual(outcome.status, wr.STATUS_LIMIT_REACHED)
            self.assertEqual(outcome.message, wr.LIMIT_REACHED_TEXT)

    # ------------------------------------------------------------------ C9 boundary
    def test_daily_limit_of_one_boundary_first_start_succeeds_second_is_blocked(self):
        """Regression: the final pre-start guard (guarded_start_run) re-checks the daily limit
        *after* this attempt's own slot has already been reserved (record_daily_attempt happens
        before the real entry point is ever called, per C10). It must compare against this
        attempt's own reserved position, not against a fresh daily_count() read that already
        includes this same reservation -- otherwise daily_limit=1 would reject every single start,
        including the very first one of the day, not just a second one."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(), plan_id="Plan-1"))
            self._save_plan(tmp, plan(task(), plan_id="Plan-2"))
            state = self._state(tmp)
            calls, started_real = [], []
            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(
                    plans={"Plan-1": True, "Plan-2": True}, daily_limit=1),
                create_and_start_fn=self._fake_create_and_start_invoking_start_run(calls, started_real),
                start_run_fn=lambda **kw: Path("/fake/run-dir"))
            self.assertEqual(len(started_real), 1)  # the first start really reached start_run
            self.assertEqual(self._load_plan(tmp, "Plan-1")["tasks"][0]["status"], "running")
            self.assertEqual(self._load_plan(tmp, "Plan-2")["tasks"][0]["status"], "approved")

    # ------------------------------------------------------------------ C10
    def test_same_task_never_started_twice_even_after_genuine_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            cfg = dict(state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                      runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                      create_and_start_fn=self._fake_create_and_start(calls, ok=False, reason="何かの理由"))
            self._run(tmp, **cfg)
            self.assertEqual(len(calls), 1)
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "failed")
            self._run(tmp, **cfg)  # next cycle: plan is paused by the failed task
            self.assertEqual(len(calls), 1)

    def test_detail_record_save_failure_still_counts_the_daily_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            state = self._state(tmp)
            with mock.patch.object(wr.start, "_write_json_atomic", side_effect=OSError("disk full")):
                self._run(
                    tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                    runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                    create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self.assertEqual(len(calls), 1)
            self.assertEqual(state.daily_count(TODAY), 1)

    def test_daily_count_already_incremented_before_the_real_entry_point_runs(self):
        """The count must be reserved *before* the real start entry point is ever called (not only
        after it returns a clean outcome) so an abnormal exit from that entry point can never lose
        this attempt's place in the day's quota."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            state = self._state(tmp)
            observed = []

            def create_and_start_fn(shim, criteria_lines, **kwargs):
                observed.append(state.daily_count(TODAY))
                return cas.StartResult(True, "", run_dir=Path("/fake/run-1"))

            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=create_and_start_fn)
            self.assertEqual(observed, [1])

    def test_entry_point_exception_still_counts_and_fails_instead_of_staying_running(self):
        """A real create_and_start never raises (it always returns a StartResult) -- but an
        injected entry point might misbehave, and the task must not be left "running" forever with
        no run association and no path back to approved/failed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            state = self._state(tmp)
            calls = []

            def create_and_start_fn(shim, criteria_lines, **kwargs):
                calls.append(1)
                raise RuntimeError("a badly-behaved injected entry point")

            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=create_and_start_fn)
            self.assertEqual(len(calls), 1)
            self.assertEqual(state.daily_count(TODAY), 1)
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "failed")
            record = wr._load_record("Plan-1", "T1", root=tmp / "records")
            self.assertEqual(record["reason"], wr.REASON_START_FAILED)

    def test_reservation_contention_blocks_start_and_never_calls_the_entry_point(self):
        """Mirrors reports_auto_progress._process_candidate's own reserve_fn contract: a reservation
        contended by a concurrent manual operation (RUN_DEV/PUSH/BUILD) must stop the start
        entirely, leaving the task untouched for a later cycle."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            calls = []
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                reserve_fn=lambda repo_name: None,
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(calls, [])
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "approved")

    def test_reservation_is_released_even_when_the_entry_point_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            released = []

            def create_and_start_fn(shim, criteria_lines, **kwargs):
                raise RuntimeError("boom")

            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                reserve_fn=lambda repo_name: repo_name,
                release_fn=lambda repo_name, token: released.append((repo_name, token)),
                create_and_start_fn=create_and_start_fn)
            self.assertEqual(len(released), 1)
            self.assertEqual(released[0], ("sample-repo", "sample-repo"))

    def test_default_agents_are_not_silently_replaced_by_the_real_orchestrator_defaults(self):
        """providers.DEFAULT_MAIN_AGENT/DEFAULT_REVIEW_AGENT really are "claude"/"codex" -- using
        those same two values here would not prove default_main_agent/default_review_agent (DCC's
        own current role selection, app.py's _current_roles_snapshot) actually reached the entry
        point rather than the hardcoded Orchestrator fallback winning by coincidence."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))  # no main_ai/reviewer_ai override
            calls = []
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")),
                default_main_agent="codex", default_review_agent="claude")
            self.assertEqual(calls[0][3], "codex")
            self.assertEqual(calls[0][4], "claude")

    def test_real_create_and_start_entry_point_only_fakes_the_final_start_run(self):
        """A connection test against the real tools.ai_orchestrator wiring (DCC Task 18's own entry
        point), not the DI-faked create_and_start_fn every other test here uses: only the spec file
        location and the very last start_run call are redirected, so the spec file really gets
        written and parsed, and main_ai/reviewer_ai really flow through create_and_start's own
        keyword arguments end to end."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(main_ai="codex", reviewer_ai="claude")))
            from scripts.dev_control_center import reports_inbox as inbox

            started = []

            def fake_start_run(*, repo, task, main_agent, review_agent, spec):
                started.append((repo, main_agent, review_agent, list(spec.criteria)))
                return Path("/fake/run-dir")

            def create_and_start_fn(shim, criteria_lines, **kwargs):
                return cas.create_and_start(
                    shim, criteria_lines, main_agent=kwargs["main_agent"], review_agent=kwargs["review_agent"],
                    resolve_repo_dir=kwargs["resolve_repo_dir"], task_text_fn=kwargs["task_text_fn"],
                    create_spec_file=lambda c, k, ident: inbox.create_spec_file(c, k, ident, specs_dir=tmp / "specs"),
                    start_run=kwargs["start_run"],
                )

            outcome = self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=create_and_start_fn, start_run_fn=fake_start_run)
            self.assertEqual(outcome.status, wr.STATUS_DONE)
            self.assertEqual(len(started), 1)
            _repo, main_agent, review_agent, criteria = started[0]
            self.assertEqual(main_agent, "codex")
            self.assertEqual(review_agent, "claude")
            self.assertEqual(criteria[0]["text"], "正しい結果が表示されること")
            self.assertTrue((tmp / "specs").is_dir())
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "running")

    def test_shape_valid_but_undefined_reason_code_is_rejected(self):
        """Unlike test_unknown_reason_code_is_shape_checked (free-text, invalid shape), this code
        is shape-valid (uppercase + underscores) but simply not in _ALLOWED_REASONS -- the closed
        vocabulary must reject it on membership, not merely on shape."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task(status="running")))
            wr._save_record("Plan-1", "T1", run_id="run-1", reason="", candidate_sha="", root=tmp / "records")
            self._run(
                tmp, state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=False),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": False}),
                run_lookup_fn=lambda _rid: {"stage": "failed",
                                           "final_result": {"code": "DEFINITELY_NOT_A_REAL_CODE"}})
            record = wr._load_record("Plan-1", "T1", root=tmp / "records")
            self.assertEqual(record["reason"], wr.REASON_UNKNOWN)

    def test_run_association_recovers_after_a_temporary_save_failure(self):
        """A save failure right after starting must not strand the task "running" forever: this
        process's own in-memory association (WorkflowRunnerState.remember_run) survives the
        failure, and once storage recovers the next cycle both persists the association and
        resolves the Run to its real outcome -- never starting the task a second time."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            state = self._state(tmp)
            calls = []
            with mock.patch.object(wr.start, "_write_json_atomic", side_effect=OSError("disk full")):
                self._run(
                    tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                    runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                    create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self.assertEqual(len(calls), 1)
            self.assertIsNone(wr._load_record("Plan-1", "T1", root=tmp / "records"))
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "running")

            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                run_lookup_fn=lambda _rid: {"stage": "completed", "final_result": {"code": "OK"},
                                           "candidate_sha": "a" * 40},
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self.assertEqual(len(calls), 1)  # never started a second time
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "candidate_ready")
            self.assertIsNotNone(wr._load_record("Plan-1", "T1", root=tmp / "records"))

    def test_hot_record_prefers_latest_unsaved_memory_over_a_stale_prior_run_record(self):
        """Human-retry race (reviewer finding): a first run starts and then fails, leaving its own
        association persisted to disk. A human re-approves the task and a second run starts, but
        *this* run's own association save fails right after starting (unlike
        test_run_association_recovers_after_a_temporary_save_failure above, disk already holds a
        *stale* record from the earlier failed run instead of nothing at all). The next cycle must
        resolve the second run's own outcome -- never the stale first run's."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            state = self._state(tmp)
            calls = []

            # First run starts, then fails; its association is persisted normally.
            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                run_lookup_fn=lambda _rid: {"stage": "failed", "final_result": {"code": "TASK_BLOCKED"}})
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "failed")
            stale = wr._load_record("Plan-1", "T1", root=tmp / "records")
            self.assertEqual(stale["run_id"], "run-1")

            # Human re-approves; a second run starts under run-2, but its own association save
            # fails right after starting -- the stale run-1 record above must survive untouched.
            p = self._load_plan(tmp)
            p = wf.apply_proposal(p, dict(plan_id="Plan-1", base_revision=p["revision"],
                                          ops=[{"op": "approve", "task_id": "T1"}]), actor="human",
                                  registered_keys=KEYS)[0]
            wf.save_plan(p, root=tmp / "plans", registered_keys=KEYS)

            with mock.patch.object(wr.start, "_write_json_atomic", side_effect=OSError("disk full")):
                self._run(
                    tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                    runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                    create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-2")))
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "running")
            self.assertEqual(wr._load_record("Plan-1", "T1", root=tmp / "records")["run_id"], "run-1")

            # Next cycle: resolving the hot task must look up run-2 (this process's own in-memory
            # association), never the stale run-1 record still sitting on disk.
            seen_run_ids = []

            def run_lookup_fn(rid):
                seen_run_ids.append(rid)
                return {"stage": "completed", "final_result": {"code": "OK"}, "candidate_sha": "b" * 40}

            self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                run_lookup_fn=run_lookup_fn)
            self.assertEqual(seen_run_ids, ["run-2"])
            self.assertEqual(self._load_plan(tmp)["tasks"][0]["status"], "candidate_ready")
            self.assertEqual(wr._load_record("Plan-1", "T1", root=tmp / "records")["run_id"], "run-2")

    # ------------------------------------------------------------------ C11
    def test_startup_blocked_cycle_never_calls_create_and_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task()))
            daily_path = tmp / "daily.json"
            daily_path.write_text("not json{{{", encoding="utf-8")
            state = wr.WorkflowRunnerState(daily_count_path=daily_path)
            calls = []
            outcome = self._run(
                tmp, state=state, global_config=auto.AutoModeConfig(enabled=True),
                runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                create_and_start_fn=self._fake_create_and_start(calls))
            self.assertEqual(outcome.status, wr.STATUS_STARTUP_BLOCKED)
            self.assertEqual(calls, [])

    # ------------------------------------------------------------------ C12 (see also C3)
    def test_needs_human_pauses_until_human_cancels_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self._save_plan(tmp, plan(task("T1", status="needs_human"), task("T2")))
            calls = []
            cfg = dict(state=self._state(tmp), global_config=auto.AutoModeConfig(enabled=True),
                      runner_config=wr.WorkflowRunnerConfig(plans={"Plan-1": True}),
                      create_and_start_fn=self._fake_create_and_start(calls, run_dir=Path("/fake/run-1")))
            self._run(tmp, **cfg)
            self.assertEqual(calls, [])
            p = self._load_plan(tmp)
            p = wf.apply_proposal(p, dict(plan_id="Plan-1", base_revision=p["revision"],
                                          ops=[{"op": "cancel", "task_id": "T1"}]), actor="human",
                                  registered_keys=KEYS)[0]
            wf.save_plan(p, root=tmp / "plans", registered_keys=KEYS)
            self._run(tmp, **cfg)
            self.assertEqual(len(calls), 1)

    # ------------------------------------------------------------------ C13
    def test_approve_push_build_update_release_never_called(self):
        """Nothing in this module imports or calls candidate.approve/push, provenance.build, or
        release_update.plan -- the only side effects available to it are the injected
        resolve_repo_dir/busy_fn/repo_run_blocked_fn/create_and_start_fn/start_run_fn/run_lookup_fn/
        is_landed_fn callables, none of which this test wires to anything real."""
        import scripts.dev_control_center.workflow_runner as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("candidate.approve(", "candidate.push(", "provenance.build(", "release_update.plan("):
            self.assertNotIn(forbidden, source)


class DefaultRepoRunBlockedTests(unittest.TestCase):
    """wr._default_repo_run_blocked is the one place this module must distinguish "confirmed no
    runs for this repo" from "cannot tell" (C4) -- exercised directly here because every test in
    RunWorkflowRunnerOnceTests injects its own fake repo_run_blocked_fn instead."""

    def test_runs_root_never_created_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"  # deliberately never created
            with mock.patch("tools.ai_orchestrator.runstate.runs_root", return_value=root):
                self.assertFalse(wr._default_repo_run_blocked(str(Path(tmp) / "repo-a")))

    def test_enumeration_failure_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.write_text("not a directory", encoding="utf-8")  # .iterdir() raises NotADirectoryError
            with mock.patch("tools.ai_orchestrator.runstate.runs_root", return_value=root):
                self.assertTrue(wr._default_repo_run_blocked(str(Path(tmp) / "repo-a")))

    def test_unreadable_run_json_blocks_regardless_of_which_repo_is_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text("not json{{{", encoding="utf-8")
            with mock.patch("tools.ai_orchestrator.runstate.runs_root", return_value=root):
                self.assertTrue(wr._default_repo_run_blocked(str(Path(tmp) / "unrelated-repo")))

    def test_active_run_for_this_repo_blocks_but_another_repo_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tools.ai_orchestrator import runstate

            root = Path(tmp) / "runs"
            run_dir = root / "run-1"
            run_dir.mkdir(parents=True)
            repo_a = str(Path(tmp) / "repo-a")
            record = {"repo": repo_a, "stage": "implementing", "worker": None,
                     "created_at": runstate.now_iso()}
            runstate.write_json_atomic(run_dir / "run.json", record)
            with mock.patch("tools.ai_orchestrator.runstate.runs_root", return_value=root):
                self.assertTrue(wr._default_repo_run_blocked(repo_a))
                self.assertFalse(wr._default_repo_run_blocked(str(Path(tmp) / "repo-b")))

    def test_long_dead_run_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tools.ai_orchestrator import runstate

            root = Path(tmp) / "runs"
            run_dir = root / "run-1"
            run_dir.mkdir(parents=True)
            repo_a = str(Path(tmp) / "repo-a")
            # No worker ever registered, and long past STARTING_GRACE_SECONDS -- LIVE_LOST, which
            # (like runstate.active_runs) must never block a later start.
            record = {"repo": repo_a, "stage": "implementing", "worker": None,
                     "created_at": "2000-01-01T00:00:00"}
            runstate.write_json_atomic(run_dir / "run.json", record)
            with mock.patch("tools.ai_orchestrator.runstate.runs_root", return_value=root):
                self.assertFalse(wr._default_repo_run_blocked(repo_a))


if __name__ == "__main__":
    unittest.main()
