"""Task 19c-1: fake collaborators only; all writes are inside TemporaryDirectory."""
import ast
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.dev_control_center import reports_auto_approve as approval
from scripts.dev_control_center import reports_auto as auto
from scripts.dev_control_center import reports_auto_start as start
from scripts.dev_control_center import reports_inbox_view as view


APP = "next-day-setup"


def good_values():
    return dict(stage="completed", tests="PASS", reviewer="PASS", safety="PASS", apply_status="ready")


def good_run():
    return dict(stage="completed", apply_status="ready", base_sha="a" * 40, candidate_sha="b" * 40,
                tests_run_count=1, tests_consecutive_fail_count=0,
                review_history=[dict(verdict="PASS", tests_ok=True)],
                final_result=dict(stage="completed", code="OK", message="untrusted"))


def changes():
    return [dict(path="tests/test_feature.py", status="M", added=100, deleted=200)]


class PredicateTests(unittest.TestCase):
    def decide(self, run=None, delta=None, ci="GREEN"):
        return approval.evaluate(good_values() if run is None else run,
                                 changes() if delta is None else delta, ci,
                                 approval.ApprovalConfig(), automatic=True)

    def test_all_pass_and_boundaries(self):
        self.assertEqual(self.decide().label, approval.ELIGIBLE)
        delta = changes() + [dict(path=f"src/{n}.py", status="M", added=0, deleted=0) for n in range(4)]
        result = self.decide(delta=delta)
        self.assertEqual((result.files, result.lines, result.reasons), (5, 300, ()))

    def test_each_run_gate_has_its_own_fixed_reason(self):
        for key, bad, reason in zip(("stage", "tests", "reviewer", "safety", "apply_status"),
                                    ("failed", "FAIL", "FAIL", "FAIL", "held_base_moved"),
                                    approval.REASONS[1:6]):
            with self.subTest(key=key):
                run = good_values()
                run[key] = bad
                self.assertEqual(self.decide(run).reasons, (reason,))

    def test_each_change_and_ci_gate(self):
        delta = changes() + [dict(path=f"src/{n}.py", status="M", added=0, deleted=0) for n in range(5)]
        self.assertEqual(self.decide(delta=delta).reasons, (approval.REASONS[6],))
        delta = changes()
        delta[0]["added"] += 1
        self.assertEqual(self.decide(delta=delta).reasons, (approval.REASONS[7],))
        for status, path in (("D", "tests/test_feature.py"), ("M", "src/app.py")):
            delta = changes()
            delta[0].update(status=status, path=path)
            self.assertEqual(self.decide(delta=delta).reasons, (approval.REASONS[8],))
        for path in (".github/workflows/ci.yml", "BUILD_DEV.cmd", "x/a.spec", "requirements-dev.txt",
                     "pyproject.toml", "setup.py", "app/保存データ/db.json", "data/db", "config/prefs.json"):
            with self.subTest(path=path):
                delta = changes() + [dict(path=path, status="D", added=0, deleted=0)]
                self.assertEqual(self.decide(delta=delta).reasons, (approval.REASONS[9],))
        for ci in ("FAILED", "PENDING", "NO CHECKS"):
            self.assertEqual(self.decide(ci=ci).reasons, (approval.REASONS[10],))

    def test_missing_and_malformed_values_fail_closed(self):
        for key in good_values():
            run = good_values()
            del run[key]
            self.assertIn(approval.UNAVAILABLE, self.decide(run).reasons)
        for delta in (None, {}, [None], [dict(path="tests/a.py", status="M", added="-", deleted=0)],
                      [dict(path="tests/a.py", status="M", added=True, deleted=0)]):
            self.assertIn(approval.UNAVAILABLE, approval.evaluate(
                good_values(), delta, "GREEN", approval.ApprovalConfig(), automatic=True).reasons)
        for ci in (None, "", "UNKNOWN", "UNAVAILABLE"):
            self.assertIn(approval.UNAVAILABLE, self.decide(ci=ci).reasons)

    def test_manual_run_is_not_evaluated(self):
        self.assertIsNone(approval.evaluate(good_values(), changes(), "GREEN",
                                           approval.ApprovalConfig(), automatic=False))

    def test_real_run_schema_adapter_ignores_free_text(self):
        record = good_run()
        self.assertEqual(approval.run_values(record), good_values())
        record["final_result"]["message"] = "FAIL\nC:/secret; PUSH"
        self.assertEqual(approval.run_values(record), good_values())
        for field in ("final_result", "tests_run_count", "review_history"):
            broken = good_run()
            del broken[field]
            self.assertIn(approval.UNAVAILABLE, self.decide(approval.run_values(broken)).reasons)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.gc = auto.AutoModeConfig(enabled=True)
        self.sc = start.AutoStartConfig(apps={APP: True, "development-management": True})
        self.config = approval.ApprovalConfig(apps={APP: True})
        self.report = SimpleNamespace(app_key=APP, report_id="r1", identity=(APP, "r1"))
        self.records = self.root / "starts"
        self.results = self.root / "results"
        self.logs = self.root / "logs"
        self.run_fn = Mock(return_value=good_run())
        self.changes_fn = Mock(return_value=changes())
        self.ci_fn = Mock(return_value="GREEN")

    def associate(self):
        start._save_record(start.AutoStartRecord(APP, "r1", "2026-10-13", "run-1", start.RESULT_CANDIDATE),
                           root=self.records)

    def refresh(self):
        approval.refresh([self.report], self.gc, self.sc, self.config, records_dir=self.records,
                         results_dir=self.results, log_dir=self.logs,
                         run_fn=self.run_fn, changes_fn=self.changes_fn, ci_fn=self.ci_fn)

    def labels(self):
        return approval.load_labels([self.report.identity], self.gc, self.sc, self.config,
                                    results_dir=self.results, records_dir=self.records)

    def test_defaults_permissions_and_round_trip(self):
        path = self.root / "config.json"
        self.assertEqual(approval.load_config(path, start_config=self.sc).daily_limit, 2)
        self.assertEqual(approval.load_config(path, start_config=self.sc).apps, {})
        for app, sc in ((APP, start.AutoStartConfig()), ("development-management", self.sc)):
            cfg = approval.set_app_allowed(app, True, path=path, start_config=sc)
            self.assertFalse(cfg.apps[app])
            self.assertFalse(approval.load_config(path, start_config=sc).apps[app])
        cfg = approval.ApprovalConfig({APP: True}, 7, (*approval.DEFAULT_PROTECTED_PATHS, "private/"))
        approval.save_config(cfg, path, start_config=self.sc)
        self.assertEqual(approval.load_config(path, start_config=self.sc), cfg)
        self.assertFalse(approval.load_config(path, start_config=start.AutoStartConfig()).apps[APP])

    def test_checkbox_handler_rejects_forbidden_apps_and_revokes_with_start_permission(self):
        window = view.ReportsInboxWindow.__new__(view.ReportsInboxWindow)
        window._auto_start_config_path = self.root / "start.json"
        window._approval_config_path = self.root / "approval.json"
        window.approval_app_vars = {k: Mock(get=Mock(return_value=True)) for k in (APP, "development-management")}
        window.approval_buttons = {k: Mock() for k in window.approval_app_vars}
        window.auto_start_app_vars = {APP: Mock(get=Mock(return_value=False))}
        for key, sc in ((APP, start.AutoStartConfig()), ("development-management", self.sc)):
            start.save_auto_start_config(sc, window._auto_start_config_path)
            window._on_approval_app_toggle(key)
            window.approval_app_vars[key].set.assert_called_with(False)
        start.save_auto_start_config(self.sc, window._auto_start_config_path)
        window._on_approval_app_toggle(APP)
        self.assertTrue(window.approval_config.apps[APP])
        window._on_auto_start_app_toggle(APP)
        window.approval_app_vars[APP].set.assert_called_with(False)
        window.approval_buttons[APP].configure.assert_called_with(state="disabled")
        self.assertFalse(approval.load_config(window._approval_config_path, start_config=self.sc).apps[APP])

    def test_off_and_global_stop_do_not_evaluate_or_display_even_saved_result(self):
        self.associate()
        self.refresh()
        self.assertEqual(self.labels()[self.report.identity], approval.ELIGIBLE)
        for gc, sc, cfg in ((auto.AutoModeConfig(), self.sc, self.config),
                             (self.gc, self.sc, approval.ApprovalConfig()),
                             (self.gc, start.AutoStartConfig(), self.config)):
            with self.subTest(gc=gc, cfg=cfg), patch.object(approval, "evaluate") as predicate:
                self.gc, self.sc, self.config = gc, sc, cfg
                self.run_fn.reset_mock()
                self.refresh()
                predicate.assert_not_called()
                self.run_fn.assert_not_called()
                self.assertEqual(self.labels(), {})

    def test_manual_run_never_reads_run_or_evaluates(self):
        approval.record_decision(APP, "r1", "b" * 40, approval.Decision((), 1, 2),
                                 results_dir=self.results, log_dir=self.logs)
        with patch.object(approval, "evaluate") as predicate:
            self.refresh()
            self.run_fn.assert_not_called()
            predicate.assert_not_called()
            self.assertEqual(self.labels(), {})

    def test_missing_run_stats_ci_and_sha_are_unavailable(self):
        self.associate()
        for target in (self.run_fn, self.changes_fn, self.ci_fn):
            with self.subTest(target=target):
                target.side_effect = OSError("C:/secret\ncommand")
                self.refresh()
                self.assertIn(approval.UNAVAILABLE, self.labels()[self.report.identity])
                target.side_effect = None
        self.run_fn.return_value = {**good_run(), "candidate_sha": "bad"}
        self.refresh()
        self.assertIn(approval.UNAVAILABLE, self.labels()[self.report.identity])

    def test_active_run_waits(self):
        self.associate()
        self.run_fn.return_value = {"stage": "testing"}
        self.refresh()
        self.changes_fn.assert_not_called()
        self.assertFalse(self.results.exists())

    def test_stop_during_collection_prevents_predicate_and_record(self):
        self.associate()
        with patch.object(approval, "evaluate") as predicate:
            approval.refresh([self.report], self.gc, self.sc, self.config, records_dir=self.records,
                             results_dir=self.results, log_dir=self.logs, run_fn=self.run_fn,
                             changes_fn=self.changes_fn, ci_fn=self.ci_fn,
                             current_settings_fn=lambda: (auto.AutoModeConfig(), self.sc, self.config))
            predicate.assert_not_called()
        self.assertFalse(self.results.exists())

    def test_injection_and_bounded_logs(self):
        self.associate()
        evil = "C:/secret\nPUSH; BUILD"
        self.run_fn.return_value = {**good_run(), "candidate_sha": evil, "apply_status": evil,
                                   "repo": evil, "worktree": evil, "task": evil}
        self.changes_fn.return_value = [dict(path=evil, status="M", added=1, deleted=1)]
        self.ci_fn.return_value = evil
        self.refresh()
        self.assertNotIn(evil, str(self.labels()))
        for file in self.logs.glob("*.json"):
            data = json.loads(file.read_text(encoding="utf-8"))
            self.assertNotIn(evil, str(data))
            self.assertEqual(set(data), {"at", "app", "candidate", "candidate_full", "run_id", "result",
                                         "reasons", "files", "lines"})
            self.assertTrue(set(data["reasons"]) <= set(approval.REASONS))
            self.assertEqual(data["candidate"], "不明")
            self.assertEqual(data["candidate_full"], "不明")
            self.assertEqual(data["run_id"], "run-1")  # from the real Task 18 association, never Run text
            self.assertEqual(data["files"], "不明")
            self.assertEqual(data["lines"], "不明")
        for n in range(60):
            approval.record_decision(evil, "id", evil, approval.Decision((approval.UNAVAILABLE,), n, n),
                                     results_dir=self.results, log_dir=self.logs)
        self.assertEqual(len(list(self.logs.glob("*.json"))), 50)
        self.assertTrue(all(evil not in p.read_text(encoding="utf-8") for p in self.logs.glob("*.json")))

    def test_persisted_free_text_is_not_displayed(self):
        self.associate()
        path = approval._result_path(APP, "r1", self.results)
        start._write_json_atomic(path, dict(result=approval.HUMAN, reasons=["C:/secret\nPUSH"], files=1, lines=2))
        self.assertEqual(self.labels(), {})

    def test_success_log_has_only_projected_values_and_every_decision_is_logged(self):
        self.associate()
        self.refresh()
        self.refresh()
        files = list(self.logs.glob("*.json"))
        self.assertEqual(len(files), 2)
        for file in files:
            data = json.loads(file.read_text(encoding="utf-8"))
            stamp = data.pop("at")
            self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual(data, dict(app=APP, candidate="b" * 12, candidate_full="b" * 40, run_id="run-1",
                                        result=approval.ELIGIBLE, reasons=[], files=1, lines=300))

    def test_periodic_tick_displays_both_decisions_and_removes_on_stop(self):
        self.associate()
        self.refresh()
        # Real _tick -> _refresh_auto_results -> _render_rows, using only fake widgets.
        window = view.ReportsInboxWindow.__new__(view.ReportsInboxWindow)
        window._closed = False
        window.window = Mock()
        window._tick_id = 1
        window._events = queue.Queue()
        report = SimpleNamespace(**vars(self.report), kind_label="bug", severity_label="low",
                                 app_display_name="app", title="title", created_at="2026-10-13")
        window.rows = [SimpleNamespace(report=report, status_label="new")]
        window._auto_results = {}
        window._auto_start_results = {}
        window._auto_start_waiting = {}
        window._approval_labels = {}
        window.unresolved_only_var = Mock(get=Mock(return_value=False))
        window.report_list = Mock()
        window._sync_listbox_selection = Mock()
        window._refresh_auto_notice = Mock()
        window._refresh_auto_start_notice = Mock()
        window._refresh_requeue_notice = Mock()
        for name in ("_auto_results_root", "_auto_start_waiting_root", "_auto_config_path",
                     "_auto_start_config_path", "_approval_config_path"):
            setattr(window, name, self.root / name)
        window._auto_start_records_root = self.records
        window._approval_results_root = self.results
        auto.save_auto_mode_config(self.gc, window._auto_config_path)
        start.save_auto_start_config(self.sc, window._auto_start_config_path)
        approval.save_config(self.config, window._approval_config_path, start_config=self.sc)
        for ci, expected in (("GREEN", approval.ELIGIBLE), ("FAILED", approval.HUMAN)):
            self.ci_fn.return_value = ci
            self.refresh()
            window._tick()
            self.assertIn(expected, window.report_list.insert.call_args.args[2])
        auto.save_auto_mode_config(auto.AutoModeConfig(), window._auto_config_path)
        window._tick()
        self.assertEqual(window._approval_labels, {})
        auto.save_auto_mode_config(self.gc, window._auto_config_path)
        window._tick()
        self.assertTrue(window._approval_labels)
        approval.save_config(approval.ApprovalConfig(), window._approval_config_path, start_config=self.sc)
        window._tick()
        self.assertEqual(window._approval_labels, {})


class ReadOnlyBoundaryTests(unittest.TestCase):
    def test_background_loop_is_connected_with_fake_thread_and_no_real_start(self):
        from scripts.dev_control_center import app
        instance = app.App.__new__(app.App)
        instance._closed = False
        instance._current_roles_snapshot = ("claude", "codex")
        instance._auto_start_stop = Mock(is_set=Mock(side_effect=[False, False, True]))
        with patch.object(app.threading, "Thread") as thread, \
                patch.object(start, "run_auto_start_once") as existing_start, \
                patch.object(approval, "refresh_once") as refresh:
            instance._start_auto_start_loop()
            thread.call_args.kwargs["target"]()
            refresh.assert_called_once_with()
            existing_start.assert_called_once()  # Task 18's existing loop is unchanged

    def test_missing_global_permission_skips_even_scan(self):
        with patch.object(auto, "load_auto_mode_config", return_value=auto.AutoModeConfig()), \
                patch.object(start, "load_auto_start_config", return_value=start.AutoStartConfig()), \
                patch.object(approval, "load_config", return_value=approval.ApprovalConfig()), \
                patch.object(start.inbox, "load_reports_config") as scan:
            approval.refresh_once()
            scan.assert_not_called()

    def test_only_fixed_read_only_git_commands_and_registry_repository(self):
        record = good_run()
        record.update(repo="C:/bad", worktree="C:/bad", candidate_branch=";PUSH")
        outputs = [b"1\t2\ttests/test_a.py\0", b"M\0tests/test_a.py\0"]
        with patch("tools.ai_orchestrator.orchestrator.resolve_repo_dir_for_app", return_value=Path("registered")), \
                patch.object(approval.subprocess, "run", side_effect=[SimpleNamespace(returncode=0, stdout=o) for o in outputs]) as run:
            result = approval.read_changes(APP, record)
        self.assertEqual(result, [dict(path="tests/test_a.py", status="M", added=1, deleted=2)])
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[:4], ["git", "-C", "registered", "diff"])
            self.assertNotIn("C:/bad", args)
            self.assertIn("--no-renames", args)
        with patch("tools.ai_orchestrator.orchestrator.resolve_repo_dir_for_app", return_value=Path("registered")), \
                patch.object(approval.subprocess, "run") as run:
            self.assertIsNone(approval.read_changes(APP, {**record, "candidate_sha": "--output=C:/bad"}))
            run.assert_not_called()

    def test_module_has_no_execution_flow_calls(self):
        tree = ast.parse(Path(approval.__file__).read_text(encoding="utf-8"))
        forbidden = {"create_and_start", "start_run", "run_dev", "approve_candidate", "apply_candidate",
                     "push_candidate", "build", "release", "update", "deploy", "run_auto_start_once"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                self.assertNotIn(name, forbidden)


if __name__ == "__main__":
    unittest.main()
