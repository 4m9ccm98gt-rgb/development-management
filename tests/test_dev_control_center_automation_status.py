"""DCC Task WF-6c: the read-only snapshot builder (scripts/dev_control_center/automation_status.py).

Every test here uses only tempfile.TemporaryDirectory() paths -- never the real %LOCALAPPDATA%,
no real screen, AI, Orchestrator, or network of any kind.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.dev_control_center import activity_log
from scripts.dev_control_center import automation_status as status
from scripts.dev_control_center import orchestrator_requeue as requeue
from scripts.dev_control_center import reports_auto as auto
from scripts.dev_control_center import reports_auto_approve as approve
from scripts.dev_control_center import reports_auto_progress as progress
from scripts.dev_control_center import reports_auto_start as start
from scripts.dev_control_center import reports_inbox as inbox
from scripts.dev_control_center import workflow_plan as wf
from scripts.dev_control_center import workflow_runner as runner

KEYS = frozenset({"sample-repo"})
PLAN_TASK_BODY = "対象リポジトリ: sample-repo\n\n## 受入条件\n- 正しい結果が表示されること\n\n## 範囲外\n- 実行\n"


def plan_task(tid="T1", **fields):
    base = dict(task_id=tid, title="表示の修正", repo_key="sample-repo", body=PLAN_TASK_BODY,
                depends_on=[], status="approved")
    base.update(fields)
    return base


def make_plan(*tasks, plan_id="Plan-1"):
    return dict(plan_id=plan_id, name="開発計画", revision=0, tasks=list(tasks))


class ClassifyTests(unittest.TestCase):
    """classify() is the one priority order every role's state uses -- pure, Tk-free."""

    def test_global_switch_off_wins_over_everything_else(self):
        state, reason = status.classify(global_enabled=False, permission_on=True, limit_reached=True, busy=True)
        self.assertEqual(state, status.STATE_STOPPED)
        self.assertEqual(reason, status.REASON_GLOBAL_OFF)

    def test_permission_off(self):
        state, reason = status.classify(global_enabled=True, permission_on=False, limit_reached=False)
        self.assertEqual(state, status.STATE_STOPPED)
        self.assertEqual(reason, status.REASON_PERMISSION_OFF)

    def test_daily_limit_reached(self):
        state, reason = status.classify(global_enabled=True, permission_on=True, limit_reached=True)
        self.assertEqual(state, status.STATE_STOPPED)
        self.assertEqual(reason, status.REASON_DAILY_LIMIT)

    def test_busy_is_waiting_not_stopped(self):
        state, reason = status.classify(global_enabled=True, permission_on=True, limit_reached=False, busy=True)
        self.assertEqual(state, status.STATE_WAITING)
        self.assertEqual(reason, status.REASON_BUSY)

    def test_everything_clear_but_not_running_is_waiting_not_started(self):
        """Reviewer finding 1: permission ON and the daily limit not reached must never, by
        themselves, read as 動いている -- only an explicit, separately-confirmed `running=True`
        (backed by that role's own already-existing state) does."""
        state, reason = status.classify(global_enabled=True, permission_on=True, limit_reached=False)
        self.assertEqual(state, status.STATE_WAITING)
        self.assertEqual(reason, status.REASON_NOT_STARTED)

    def test_running_flag_set_is_running_with_no_reason(self):
        state, reason = status.classify(
            global_enabled=True, permission_on=True, limit_reached=False, running=True)
        self.assertEqual(state, status.STATE_RUNNING)
        self.assertEqual(reason, status.REASON_NONE)

    def test_daily_limit_reached_wins_over_running(self):
        state, reason = status.classify(
            global_enabled=True, permission_on=True, limit_reached=True, running=True)
        self.assertEqual(state, status.STATE_STOPPED)
        self.assertEqual(reason, status.REASON_DAILY_LIMIT)


class HintForReasonTests(unittest.TestCase):
    def test_login_expired_hint(self):
        self.assertEqual(status.hint_for_reason(activity_log.REASON_LOGIN_EXPIRED), status.LOGIN_EXPIRED_HINT)

    def test_quota_limit_hint(self):
        self.assertEqual(status.hint_for_reason(activity_log.REASON_QUOTA_LIMIT), status.QUOTA_LIMIT_HINT)

    def test_other_reasons_have_no_hint(self):
        self.assertEqual(status.hint_for_reason(activity_log.REASON_CRASHED), "")
        self.assertEqual(status.hint_for_reason(""), "")


class BuildSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.activity_path = self.root / "activity.jsonl"
        self.paths = dict(
            activity_log_path=self.activity_path,
            triage_config_path=self.root / "triage_config.json",
            triage_daily_count_path=self.root / "triage_daily.json",
            triage_results_dir=self.root / "triage_results",
            start_config_path=self.root / "start_config.json",
            start_daily_count_path=self.root / "start_daily.json",
            approve_config_path=self.root / "approve_config.json",
            approve_daily_count_path=self.root / "approve_daily.json",
            requeue_config_path=self.root / "requeue_config.json",
            requeue_daily_count_path=self.root / "requeue_daily.json",
            workflow_runner_config_path=self.root / "runner_config.json",
            workflow_runner_daily_count_path=self.root / "runner_daily.json",
            reports_config_fn=lambda: inbox.ReportsConfig([], []),
            scan_fn=lambda apps: [],
        )

    def test_everything_off_by_default(self):
        snapshot = status.build_snapshot(**self.paths)
        self.assertFalse(snapshot.log_unreadable)
        self.assertEqual(snapshot.next_report_id, "")
        self.assertEqual(snapshot.not_running_reason, status.REASON_GLOBAL_OFF)
        self.assertEqual(len(snapshot.roles), 5)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(
            set(roles_by_name),
            {activity_log.ROLE_AUTO_TRIAGE, activity_log.ROLE_AUTO_START, activity_log.ROLE_AUTO_APPROVE,
             activity_log.ROLE_AUTO_RETRY, activity_log.ROLE_AUTO_PLAN},
        )
        for role in roles_by_name.values():
            self.assertEqual(role.state, status.STATE_STOPPED)
            self.assertEqual(role.reason, status.REASON_GLOBAL_OFF)
            self.assertEqual(role.last_activity_at, "")

    def test_role_with_permission_but_no_app_allowed_is_stopped_for_permission(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].state, status.STATE_STOPPED)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].reason, status.REASON_PERMISSION_OFF)

    def test_triage_permitted_with_no_target_is_waiting_not_started(self):
        """Reviewer finding 1: scan_fn here returns no reports at all (no target) -- permission
        being ON must not, by itself, be read as 動いている."""
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        auto.set_app_allowed("app1", True, path=self.paths["triage_config_path"])
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].state, status.STATE_WAITING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].reason, status.REASON_NOT_STARTED)

    def test_triage_mid_investigation_is_running(self):
        """自動調査's own cycle logs ACTION_START right before its (possibly slow) AI call and
        only logs ACTION_COMPLETE/ACTION_FAIL once that call returns -- an unmatched ACTION_START
        as the most recent 自動調査 entry is read-only, already-existing evidence that it is
        actually investigating a report right now."""
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        auto.set_app_allowed("app1", True, path=self.paths["triage_config_path"])
        activity_log.append(
            role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
            target_type=activity_log.TARGET_REPORT, target_id="0" * 64, path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].state, status.STATE_RUNNING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].reason, status.REASON_NONE)

    def test_triage_after_investigation_completes_is_waiting_again(self):
        """Once ACTION_COMPLETE/ACTION_FAIL is logged after the ACTION_START, 自動調査 is no
        longer "actually processing" and must drop back to 待機中, not stay 動いている."""
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        auto.set_app_allowed("app1", True, path=self.paths["triage_config_path"])
        activity_log.append(
            role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
            target_type=activity_log.TARGET_REPORT, target_id="0" * 64, path=self.activity_path)
        activity_log.append(
            role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_COMPLETE,
            target_type=activity_log.TARGET_REPORT, target_id="0" * 64,
            result=activity_log.RESULT_PROCEED, path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].state, status.STATE_WAITING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].reason, status.REASON_NOT_STARTED)

    def test_daily_limit_reached_stops_the_role(self):
        config = auto.AutoModeConfig(enabled=True, apps={"app1": True}, daily_limit=1)
        auto.save_auto_mode_config(config, self.paths["triage_config_path"])
        auto._increment_daily_count(auto.today_str(), self.paths["triage_daily_count_path"])
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].state, status.STATE_STOPPED)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].reason, status.REASON_DAILY_LIMIT)

    def test_auto_start_role_reflects_its_own_config_independent_of_triage(self):
        """自動開始 has no bracketed start/finish record under its own role (see
        _triage_is_processing's own docstring for why that check is 自動調査-only), so a
        permitted, eligible 自動開始 reads as 待機中, never 動いている."""
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        start_config = start.AutoStartConfig(apps={"app1": True})
        start._write_json_atomic(self.paths["start_config_path"], {
            "apps": start_config.apps, "daily_limit": start_config.daily_limit,
        })
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_START].state, status.STATE_WAITING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_START].reason, status.REASON_NOT_STARTED)
        # 自動調査 itself is still stopped: its own per-app permission was never turned on.
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].state, status.STATE_STOPPED)

    def test_requeue_role_uses_its_own_enabled_switch_as_permission(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        requeue.save_requeue_config(requeue.RequeueConfig(enabled=True, daily_limit=5), self.paths["requeue_config_path"])
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        # 自動再実行 also has no bracketed start/finish record under its own role -- permitted and
        # not daily-limited reads as 待機中, never 動いている (Reviewer finding 1).
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_RETRY].state, status.STATE_WAITING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_RETRY].reason, status.REASON_NOT_STARTED)

    def test_requeue_role_daily_limit_reached(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        requeue.save_requeue_config(requeue.RequeueConfig(enabled=True, daily_limit=1), self.paths["requeue_config_path"])
        self.paths["requeue_daily_count_path"].write_text(
            json.dumps({"date": auto.today_str(), "count": 1}), encoding="utf-8")
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_RETRY].state, status.STATE_STOPPED)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_RETRY].reason, status.REASON_DAILY_LIMIT)

    def test_workflow_runner_role_daily_limit_reached(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        runner.save_workflow_runner_config(
            runner.WorkflowRunnerConfig(plans={"plan1": True}, daily_limit=1),
            self.paths["workflow_runner_config_path"])
        self.paths["workflow_runner_daily_count_path"].write_text(
            json.dumps({"date": auto.today_str(), "count": 1}), encoding="utf-8")
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_PLAN].state, status.STATE_STOPPED)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_PLAN].reason, status.REASON_DAILY_LIMIT)

    def test_approve_role_depends_on_its_own_app_permission(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        start_config = start.AutoStartConfig(apps={"app1": True})
        start._write_json_atomic(self.paths["start_config_path"], {
            "apps": start_config.apps, "daily_limit": start_config.daily_limit,
        })
        approve.save_config(
            approve.ApprovalConfig(apps={"app1": True}), self.paths["approve_config_path"],
            start_config=start_config)
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        # 自動承認 only ever logs ACTION_COMPLETE (never ACTION_START) under its own role -- a
        # permitted, not-limited 自動承認 reads as 待機中, never 動いている (Reviewer finding 1).
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_APPROVE].state, status.STATE_WAITING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_APPROVE].reason, status.REASON_NOT_STARTED)

    def test_approve_role_is_never_affected_by_a_busy_repository(self):
        """Reviewer finding 1: reports_auto_approve.refresh never busy-gates (it only observes an
        already-finished Run) -- build_snapshot has no busy input for 自動承認 at all, so an
        otherwise-eligible approve role can never show 待機中 because of a repo operation
        elsewhere (there used to be an `any_busy` flag that incorrectly did exactly that)."""
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        start_config = start.AutoStartConfig(apps={"app1": True})
        start._write_json_atomic(self.paths["start_config_path"], {
            "apps": start_config.apps, "daily_limit": start_config.daily_limit,
        })
        approve.save_config(
            approve.ApprovalConfig(apps={"app1": True}), self.paths["approve_config_path"],
            start_config=start_config)
        self.assertNotIn("any_busy", status.build_snapshot.__kwdefaults__ or {})
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        # Never 止まっている/REASON_BUSY either way -- a busy repo elsewhere must never affect
        # this role; it is 待機中/REASON_NOT_STARTED, exactly like the no-busy-input case above.
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_APPROVE].state, status.STATE_WAITING)
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_APPROVE].reason, status.REASON_NOT_STARTED)

    def test_last_activity_time_result_and_reason_are_read_from_the_log(self):
        activity_log.append(
            role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_COMPLETE,
            target_type=activity_log.TARGET_REPORT,
            target_id="0" * 64, result=activity_log.RESULT_PROCEED, path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        triage = roles_by_name[activity_log.ROLE_AUTO_TRIAGE]
        self.assertTrue(triage.last_activity_at)
        self.assertEqual(triage.last_result, activity_log.RESULT_PROCEED)
        self.assertEqual(triage.last_reason, "")
        self.assertEqual(triage.hint, "")

    def test_login_expired_reason_produces_the_fixed_hint(self):
        activity_log.append(
            role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_FAIL,
            target_type=activity_log.TARGET_REPORT, target_id="0" * 64,
            result=activity_log.RESULT_FAILED, reason=activity_log.REASON_LOGIN_EXPIRED,
            path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_TRIAGE].hint, status.LOGIN_EXPIRED_HINT)

    def test_quota_limit_reason_produces_the_fixed_hint(self):
        activity_log.append(
            role=activity_log.ROLE_AUTO_START, action=activity_log.ACTION_FAIL,
            target_type=activity_log.TARGET_REPORT, target_id="1" * 64,
            result=activity_log.RESULT_FAILED, reason=activity_log.REASON_QUOTA_LIMIT,
            path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        roles_by_name = {r.role: r for r in snapshot.roles}
        self.assertEqual(roles_by_name[activity_log.ROLE_AUTO_START].hint, status.QUOTA_LIMIT_HINT)

    def test_recent_list_is_newest_first_and_capped(self):
        for i in range(status.MAX_RECENT + 10):
            activity_log.append(
                role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                target_type=activity_log.TARGET_RUN, target_id=f"2026010{i % 10}-000000-{i:06d}",
                path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        self.assertEqual(len(snapshot.recent), status.MAX_RECENT)
        self.assertEqual(snapshot.recent[0].target_id, "20260109-000000-000109")

    def test_empty_log_is_not_an_error(self):
        snapshot = status.build_snapshot(**self.paths)
        self.assertFalse(snapshot.log_unreadable)
        self.assertEqual(snapshot.recent, ())

    def test_missing_activity_log_file_is_not_an_error(self):
        missing = self.root / "does_not_exist.jsonl"
        paths = dict(self.paths, activity_log_path=missing)
        snapshot = status.build_snapshot(**paths)
        self.assertFalse(snapshot.log_unreadable)
        self.assertEqual(snapshot.recent, ())

    def test_corrupt_activity_log_sets_log_unreadable_and_never_raises(self):
        self.activity_path.write_text("not json\n", encoding="utf-8")
        snapshot = status.build_snapshot(**self.paths)
        self.assertTrue(snapshot.log_unreadable)
        self.assertEqual(snapshot.recent, ())
        # Role state (from config, independent of the broken log) still renders normally.
        self.assertEqual(len(snapshot.roles), 5)

    def test_corrupt_config_files_degrade_to_stopped_never_raise(self):
        self.paths["triage_config_path"].write_text("not json", encoding="utf-8")
        self.paths["start_config_path"].write_text("not json", encoding="utf-8")
        self.paths["approve_config_path"].write_text("not json", encoding="utf-8")
        self.paths["requeue_config_path"].write_text("not json", encoding="utf-8")
        self.paths["workflow_runner_config_path"].write_text("not json", encoding="utf-8")
        snapshot = status.build_snapshot(**self.paths)
        for role in snapshot.roles:
            self.assertEqual(role.state, status.STATE_STOPPED)

    def test_next_report_id_is_hashed_never_the_raw_report_id(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        auto.set_app_allowed("app1", True, path=self.paths["triage_config_path"])
        report = inbox.Report(
            app_key="app1", app_display_name="App", file_name="r.json", schema_version=1,
            report_id="SENSITIVE-RAW-ID", created_at="2026-01-01T00:00:00Z", kind="bug",
            severity="stopped", title="t", body="b", reporter="r", app_id="a",
            display_name="d", release_id="rel", git_commit="c" * 40, version_source="v",
            pc_name="pc",
        )
        paths = dict(self.paths, scan_fn=lambda apps: [_FakeInboxWrapper([report])],
                     load_decision_fn=lambda app_key, report_id: None)
        snapshot = status.build_snapshot(**paths)
        self.assertNotEqual(snapshot.next_report_id, "")
        self.assertNotIn("SENSITIVE-RAW-ID", snapshot.next_report_id)
        self.assertEqual(len(snapshot.next_report_id), 64)  # sha256 hex digest

    def test_no_eligible_report_is_empty_string(self):
        auto.set_enabled(True, path=self.paths["triage_config_path"])
        snapshot = status.build_snapshot(**self.paths)
        self.assertEqual(snapshot.next_report_id, "")

    def test_no_output_ever_contains_report_body_or_path_text(self):
        """C4: nothing automation_status ever returns may contain report body text, a path, or
        exception text -- only fixed words/ids/numbers/timestamps."""
        activity_log.append(
            role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_FAIL,
            target_type=activity_log.TARGET_REPORT, target_id="0" * 64,
            result=activity_log.RESULT_FAILED, reason=activity_log.REASON_TIMEOUT,
            path=self.activity_path)
        snapshot = status.build_snapshot(**self.paths)
        rendered = repr(snapshot)
        for banned in ("C:\\", "/home/", "Traceback", "本文", str(self.root)):
            self.assertNotIn(banned, rendered)


class WorkflowRunnerRoleStateTests(unittest.TestCase):
    """Reviewer finding 1: 計画の自動実行 must be judged from workflow_runner.plan_start_block_reason
    itself (the exact same read-only judgment the real start path uses), not a hand-rolled
    "permission on and not globally stopped" rule -- and busy must be scoped to the one
    repository the eligible task of a given plan would actually use, never a blanket flag.
    Every scenario here uses only tempfile.TemporaryDirectory() paths and a fake resolve_repo_dir/
    busy_fn/repo_run_blocked_fn -- never the real Orchestrator, filesystem outside tmp, or AI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plans_root = self.root / "plans"
        self.paths = dict(
            activity_log_path=self.root / "activity.jsonl",
            triage_config_path=self.root / "triage_config.json",
            triage_daily_count_path=self.root / "triage_daily.json",
            triage_results_dir=self.root / "triage_results",
            start_config_path=self.root / "start_config.json",
            start_daily_count_path=self.root / "start_daily.json",
            approve_config_path=self.root / "approve_config.json",
            approve_daily_count_path=self.root / "approve_daily.json",
            requeue_config_path=self.root / "requeue_config.json",
            requeue_daily_count_path=self.root / "requeue_daily.json",
            workflow_runner_config_path=self.root / "runner_config.json",
            workflow_runner_daily_count_path=self.root / "runner_daily.json",
            workflow_runner_plans_root=self.plans_root,
            workflow_runner_registered_keys=KEYS,
            reports_config_fn=lambda: inbox.ReportsConfig([], []),
            scan_fn=lambda apps: [],
        )
        auto.set_enabled(True, path=self.paths["triage_config_path"])

    def _save_plan(self, p: dict) -> None:
        wf.save_plan(p, root=self.plans_root, registered_keys=KEYS)

    def _enable_plan(self, plan_id="Plan-1") -> None:
        runner.save_workflow_runner_config(
            runner.WorkflowRunnerConfig(plans={plan_id: True}), self.paths["workflow_runner_config_path"])

    def _plan_role(self, snapshot) -> "status.RoleStatus":
        return {r.role: r for r in snapshot.roles}[activity_log.ROLE_AUTO_PLAN]

    def _resolve_repo_dir(self, repo_key: str) -> Path:
        return self.root / "repos" / repo_key

    def test_no_approved_task_is_waiting_not_running(self):
        self._save_plan(make_plan(plan_task("T1", status="landed")))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_WAITING)
        self.assertEqual(role.reason, status.REASON_NO_APPROVED)

    def test_plan_with_a_running_task_is_shown_as_running(self):
        self._save_plan(make_plan(plan_task("T1", status="running")))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_RUNNING)
        self.assertEqual(role.reason, status.REASON_NONE)

    def test_plan_paused_by_a_failed_task_is_waiting_not_stopped(self):
        self._save_plan(make_plan(plan_task("T1", status="failed")))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_WAITING)
        self.assertEqual(role.reason, status.REASON_PLAN_PAUSED)

    def test_an_unmet_dependency_is_waiting_not_running(self):
        # T0 must exist (save_plan validates every depends_on edge resolves to a real task) but
        # stay "held" -- neither landed (so T1's dependency stays unmet) nor approved/blocking.
        self._save_plan(make_plan(
            plan_task("T0", status="held"), plan_task("T1", status="approved", depends_on=["T0"])))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_WAITING)
        self.assertEqual(role.reason, status.REASON_DEPENDS_INCOMPLETE)

    def test_the_eligible_tasks_own_busy_repository_is_waiting_not_running(self):
        self._save_plan(make_plan(plan_task("T1", status="approved")))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: name == "sample-repo",
            workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_WAITING)
        self.assertEqual(role.reason, status.REASON_BUSY)

    def test_an_unrelated_repository_being_busy_never_blocks_this_plan(self):
        """Reviewer finding 1's central complaint: busy must be scoped to the eligible task's own
        repository -- a manual operation on a completely different repo must never make this
        role show 待機中/REASON_BUSY (it is still 待機中, but for REASON_NOT_STARTED: eligible,
        not yet actually started -- never 動いている just because it is merely startable)."""
        self._save_plan(make_plan(plan_task("T1", status="approved", repo_key="sample-repo")))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: name == "some-other-repo",
            workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_WAITING)
        self.assertEqual(role.reason, status.REASON_NOT_STARTED)

    def test_everything_clear_can_start_is_waiting_not_started(self):
        """Reviewer finding 1: an approved task that CAN start (eligible, no block) is not yet
        actually running -- it must read as 待機中/REASON_NOT_STARTED, not 動いている. Only a
        task whose own status is already "running" (see
        test_plan_with_a_running_task_is_shown_as_running) is 動いている."""
        self._save_plan(make_plan(plan_task("T1", status="approved")))
        self._enable_plan()
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_WAITING)
        self.assertEqual(role.reason, status.REASON_NOT_STARTED)

    def test_one_plan_can_start_another_plan_running_is_running(self):
        """Instruction 3: 対象なし/未開始/実行中 must be distinguishable even across multiple
        plans -- a second, merely-startable plan must never hide a first plan that is actually
        running (nor short-circuit the scan before it is reached)."""
        self._save_plan(make_plan(plan_task("T1", status="approved"), plan_id="Plan-1"))
        self._save_plan(make_plan(plan_task("T1", status="running"), plan_id="Plan-2"))
        runner.save_workflow_runner_config(
            runner.WorkflowRunnerConfig(plans={"Plan-1": True, "Plan-2": True}),
            self.paths["workflow_runner_config_path"])
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_RUNNING)
        self.assertEqual(role.reason, status.REASON_NONE)

    def test_an_unreadable_plan_file_degrades_to_stopped_never_raises(self):
        self._enable_plan()  # "Plan-1" is enabled but was never actually saved
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_STOPPED)

    def test_global_switch_off_wins_over_a_plan_that_could_otherwise_start(self):
        self._save_plan(make_plan(plan_task("T1", status="approved")))
        self._enable_plan()
        auto.set_enabled(False, path=self.paths["triage_config_path"])
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_STOPPED)
        self.assertEqual(role.reason, status.REASON_GLOBAL_OFF)

    def test_daily_limit_reached_wins_over_a_plan_that_could_otherwise_start(self):
        self._save_plan(make_plan(plan_task("T1", status="approved")))
        runner.save_workflow_runner_config(
            runner.WorkflowRunnerConfig(plans={"Plan-1": True}, daily_limit=1),
            self.paths["workflow_runner_config_path"])
        self.paths["workflow_runner_daily_count_path"].write_text(
            json.dumps({"date": auto.today_str(), "count": 1}), encoding="utf-8")
        snapshot = status.build_snapshot(
            **self.paths, workflow_runner_resolve_repo_dir=self._resolve_repo_dir,
            workflow_runner_busy_fn=lambda name: False, workflow_runner_repo_run_blocked_fn=lambda r: False)
        role = self._plan_role(snapshot)
        self.assertEqual(role.state, status.STATE_STOPPED)
        self.assertEqual(role.reason, status.REASON_DAILY_LIMIT)


class _FakeInboxWrapper:
    """Minimal stand-in for reports_inbox.AppInbox: all_reports() reads .reports off each item."""

    def __init__(self, reports):
        self.reports = reports


if __name__ == "__main__":
    unittest.main()
