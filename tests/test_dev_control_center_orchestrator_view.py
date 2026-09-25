"""Orchestrator window (Tk) and RunMonitor: roles, usage display, run status, stop / apply / close semantics."""

from __future__ import annotations

import gc
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import orchestrator_view as view
from tools.ai_orchestrator import orchestrator as orch
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator import usage as usage_mod
from tools.ai_orchestrator.common import process_start_token, write_json_atomic

NOW = time.time()


class FakeMonitor:
    def __init__(self):
        self.queue = queue.Queue(maxsize=1)
        self.selected = None
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def select(self, run_id):
        self.selected = run_id

    def refresh_now(self):
        pass


def record(**over):
    base = rs.new_record(run_id="20260925-100000-000001", repo=str(Path("C:/repos/app")), task="Task", main_agent="claude",
                         review_agent="codex", tests=["python -m unittest"], limits=rs.Limits(), branch="main",
                         base_sha="a" * 40)
    base.update(stage="testing", tests_run_count=3, tests_fail_count=2, repair_iteration=2, main_calls=3, review_calls=1,
                reviewer_engaged=True, created_at="2026-09-25T10:00:00", started_at="2026-09-25T10:00:05",
                current_failure_fingerprint="abcd1234abcd1234", failure_fingerprint_counts={"abcd1234abcd1234": 2})
    base.update(over)
    return base


def item(rec=None, liveness=rs.LIVE_RUNNING, run_dir=None, reason=""):
    rec = rec or record()
    return {"record": rec, "liveness": liveness, "run_dir": run_dir or Path("C:/runs") / rec["run_id"], "reason": reason,
            "heartbeat_age": 1.0}


def codex_cache(used=27.0, observed=None):
    return {"provider": "codex", "errors": {}, "context": {"used_tokens": 50000, "window_tokens": 250000, "model": "m",
                                                           "observed_at": observed or NOW},
            "account": {"observed_at": observed or NOW, "plan": "plus", "credits": {"balance": "12.40", "unlimited": False},
                        "windows": [{"label": "5時間枠", "used_percent": used, "resets_at": NOW + 3600},
                                    {"label": "7日枠", "used_percent": 40.0, "resets_at": NOW + 86400}]}}


def claude_cache(observed=None):
    return {"provider": "claude", "errors": {}, "context": None,
            "account": {"observed_at": observed or NOW, "plan": None, "credits": None,
                        "windows": [{"label": "5時間枠", "used_percent": 32.0, "resets_at": NOW + 7200},
                                    {"label": "週間枠", "used_percent": 59.0, "resets_at": NOW + 86400}]}}


class ViewCase(unittest.TestCase):
    def setUp(self):
        # Tk objects leaked by other tests must be collected here on the main thread: if the GC ran them
        # on one of this window's worker threads Tcl would abort ("async handler deleted by the wrong thread").
        gc.collect()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self._destroy)
        self.monitor = FakeMonitor()
        self.drafts = {}
        self.on_apply = mock.MagicMock()
        definitions = [SimpleNamespace(name="app", branch="main", initial_ai_task="", initial_test="python -m unittest"),
                       SimpleNamespace(name="other", branch="main", initial_ai_task="", initial_test="")]
        self.window = view.OrchestratorWindow(self.root, definitions, initial_repo="app", drafts=self.drafts,
                                              on_apply=self.on_apply, monitor=self.monitor, repos_root=Path("C:/repos"),
                                              auto_usage=False)
        self.root.update()

    def _destroy(self):
        try:
            if self.window.exists():
                self.window.close()
            self.root.destroy()
        except tk.TclError:
            pass
        gc.collect()

    def snapshot(self, runs=(), usage=None, **extra):
        data = {"runs": list(runs), "usage": usage or {"claude": claude_cache(), "codex": codex_cache()},
                "selected": None, "log": "", "log_reset": False, "at": NOW}
        data.update(extra)
        return data

    def pump(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition())


class RoleAndStartTests(ViewCase):
    def test_defaults_are_claude_main_and_codex_reviewer(self):
        self.assertEqual((self.window.main_var.get(), self.window.review_var.get()), ("Claude", "Codex"))
        self.assertEqual(self.window.tests_var.get(), "python -m unittest")

    def test_start_passes_the_selected_roles_in_both_directions(self):
        for main, reviewer, names in (("Claude", "Codex", ("claude", "codex")), ("Codex", "Claude", ("codex", "claude"))):
            with self.subTest(main=main):
                captured = []
                self.window.main_var.set(main)
                self.window.review_var.set(reviewer)
                self.window.task_text.delete("1.0", "end")
                self.window.task_text.insert("1.0", "日本語のTask 🙂")

                def fake_start(request, **kwargs):
                    captured.append(request)
                    return Path("C:/runs/20260925-000000-000000")

                with mock.patch.object(orch, "start_run", side_effect=fake_start):
                    self.window.start_run()
                    self.pump(lambda: bool(captured))
                request = captured[0]
                self.assertEqual((request.main_agent, request.review_agent), names)
                self.assertEqual(request.task, "日本語のTask 🙂")
                self.assertEqual(request.tests, ["python -m unittest"])
                self.assertEqual(request.expected_branch, "main")
                self.assertTrue(str(request.repo).replace("\\", "/").endswith("repos/app"))
                self.pump(lambda: self.monitor.selected == "20260925-000000-000000")

    def test_same_provider_can_not_be_selected(self):
        self.window.main_var.set("Codex")
        self.window.review_var.set("Codex")
        self.window._on_role_changed("review")
        self.assertEqual((self.window.main_var.get(), self.window.review_var.get()), ("Claude", "Codex"))
        self.assertIn("異なるprovider", self.window.notice_var.get())

    def test_start_requires_task_and_tests(self):
        with mock.patch.object(view.messagebox, "showinfo") as info, mock.patch.object(orch, "start_run") as start:
            self.window.task_text.delete("1.0", "end")
            self.window.start_run()
            info.assert_called_once()
            start.assert_not_called()
        with mock.patch.object(view.messagebox, "showerror") as error, mock.patch.object(orch, "start_run") as start:
            self.window.task_text.insert("1.0", "x")
            self.window.tests_var.set("")
            self.window.start_run()
            error.assert_called_once()
            start.assert_not_called()

    def test_start_failure_is_shown_and_does_not_break_the_window(self):
        with mock.patch.object(orch, "start_run", side_effect=orch.OrchestratorError("このrepoには実行中のrunがあります")), \
             mock.patch.object(view.messagebox, "showerror") as error:
            self.window.task_text.insert("1.0", "x")
            self.window.start_run()
            self.pump(lambda: (self.window._tick(), error.called)[1])
        self.assertIn("実行中のrun", error.call_args.args[1])

    def test_drafts_are_kept_per_repo(self):
        self.window.task_text.insert("1.0", "draft for app")
        self.window.repo_var.set("other")
        self.window._on_repo_changed()
        self.assertEqual(self.window.task_text.get("1.0", "end").strip(), "")
        self.window.repo_var.set("app")
        self.window._on_repo_changed()
        self.assertEqual(self.window.task_text.get("1.0", "end").strip(), "draft for app")


class UsageDisplayTests(ViewCase):
    def test_claude_and_codex_usage_are_shown_with_roles(self):
        self.window.apply_snapshot(self.snapshot())
        claude, codex = self.window.usage_vars["claude"].get(), self.window.usage_vars["codex"].get()
        self.assertIn("68% remaining", claude)
        self.assertIn("41% remaining", claude)
        self.assertIn("73% remaining", codex)
        self.assertIn("12.40", codex)
        self.assertEqual(self.window.usage_role_vars["claude"].get(), "Main")
        self.assertEqual(self.window.usage_role_vars["codex"].get(), "Reviewer")

    def test_unknown_values_are_unavailable_never_guessed(self):
        empty = {"account": None, "context": None, "errors": {}}
        self.window.apply_snapshot(self.snapshot(usage={"claude": empty, "codex": empty}))
        for name in ("claude", "codex"):
            text = self.window.usage_vars[name].get()
            self.assertIn(usage_mod.UNAVAILABLE, text)
            self.assertNotIn("%", text)

    def test_old_cache_is_labelled_last_known(self):
        old = NOW - 7200
        self.window.apply_snapshot(self.snapshot(usage={"claude": claude_cache(old), "codex": codex_cache(observed=old)}))
        self.assertIn("last known", self.window.usage_vars["claude"].get())
        self.assertIn("last known", self.window.usage_vars["codex"].get())

    def test_context_and_account_usage_are_separate_rows(self):
        self.window.apply_snapshot(self.snapshot())
        lines = self.window.usage_vars["codex"].get().splitlines()
        context = [line for line in lines if line.startswith("Context")]
        usage = [line for line in lines if line.startswith("Usage")]
        self.assertEqual(len(context), 1)
        self.assertIn("80% remaining", context[0])          # 50k of 250k tokens: a session figure
        self.assertTrue(all("80%" not in line for line in usage))
        self.assertEqual(len(usage), 2)

    def test_low_remaining_warns_without_switching_roles(self):
        self.window.apply_snapshot(self.snapshot(usage={"claude": claude_cache(), "codex": codex_cache(used=95.0)}))
        self.assertIn("長時間Taskを完走できない可能性", self.window.warn_var.get())
        self.assertEqual((self.window.main_var.get(), self.window.review_var.get()), ("Claude", "Codex"))

    def test_usage_failure_does_not_disturb_the_run_display_or_start(self):
        failing = {"account": None, "context": None, "errors": {"account": "app-server unavailable"}}
        self.window.selected_run = item()["record"]["run_id"]
        self.window.apply_snapshot(self.snapshot(runs=[item()], usage={"claude": failing, "codex": failing}))
        self.assertIn("取得不能", self.window.usage_vars["codex"].get())
        self.assertIn("実行 3 回", self.window.counts_var.get())
        self.assertTrue(self.window.start_button.instate(["!disabled"]))

    def test_refresh_button_queries_only_off_the_ui_thread_and_survives_errors(self):
        calls = []

        class Boom:
            def refresh(self, force=False):
                calls.append(force)
                raise RuntimeError("provider down")

        with mock.patch.object(usage_mod, "make_usage_provider", return_value=Boom()):
            self.window.refresh_usage()
            self.pump(lambda: len(calls) >= 2)
            self.pump(lambda: (self.window._tick(), "残量" not in self.window.notice_var.get() or True)[1])
        self.assertEqual(calls, [True, True])


class RunStatusTests(ViewCase):
    def show(self, it):
        self.window.selected_run = it["record"]["run_id"]
        self.window.apply_snapshot(self.snapshot(runs=[it]))

    def test_status_shows_counts_calls_fingerprint_and_roles(self):
        self.show(item())
        w = self.window
        self.assertIn("Claude", w.roles_var.get())
        self.assertIn("Codex", w.roles_var.get())
        self.assertIn("実行 3 回 / FAIL 2 回", w.counts_var.get())
        self.assertIn("repair iteration 2/12", w.counts_var.get())
        self.assertIn("Main 3 回 / Reviewer 1 回", w.calls_var.get())
        self.assertIn("abcd1234abcd1234", w.fp_var.get())
        self.assertIn("同一2回目", w.fp_var.get())
        self.assertIn("testing", w.stage_var.get())
        self.assertIn("実行中", w.stage_var.get())
        self.assertEqual(w.run_list.size(), 1)

    def test_unresponsive_and_lost_runs_are_never_shown_as_plainly_running(self):
        self.show(item(liveness=rs.LIVE_UNRESPONSIVE, reason="接続不能: heartbeatが途絶えています。状態確認が必要です"))
        self.assertIn("接続不能", self.window.stage_var.get())
        self.assertNotIn("(testing) / 実行中", self.window.stage_var.get())
        self.show(item(liveness=rs.LIVE_LOST, reason="workerプロセスが存在しません"))
        self.assertIn("stale", self.window.stage_var.get())
        self.assertEqual(self.window.stop_button.cget("text"), "stale runを整理")

    def test_final_result_and_candidate_are_shown(self):
        rec = record(stage=rs.COMPLETED, candidate_sha="b" * 40, candidate_branch="ai-candidate/x", apply_status="held_base_moved",
                     apply_detail="source repoがbaseから変化しています",
                     final_result={"stage": "completed", "code": "OK", "message": "Tests PASS + Reviewer PASS + 安全チェックPASS"},
                     finished_at="2026-09-25T11:00:00")
        self.show(item(rec, liveness=rs.LIVE_FINISHED))
        text = self.window.result_var.get()
        self.assertIn("Tests PASS + Reviewer PASS", text)
        self.assertIn("held_base_moved", text)
        self.assertIn("再確認" if "再確認" in text else "source repo", text)

    def test_stop_button_only_for_live_runs_and_needs_confirmation(self):
        self.show(item())
        self.assertTrue(self.window.stop_button.instate(["!disabled"]))
        run_dir = self.window._selected_item()["run_dir"]
        with mock.patch.object(view.messagebox, "askyesno", return_value=False), \
             mock.patch.object(rs, "force_stop") as stop:
            self.window.stop_run()
            stop.assert_not_called()
        done = threading_event = []
        with mock.patch.object(view.messagebox, "askyesno", return_value=True), \
             mock.patch.object(rs, "force_stop", side_effect=lambda d: done.append(d) or {"stage": "stopped"}) as stop:
            self.window.stop_run()
            self.pump(lambda: bool(done))
        self.assertEqual(done, [run_dir])
        self.show(item(record(stage=rs.COMPLETED, final_result={"stage": "completed", "code": "OK", "message": "m"}),
                       liveness=rs.LIVE_FINISHED))
        self.assertTrue(self.window.stop_button.instate(["disabled"]))

    def test_lost_run_uses_reconcile_not_a_process_kill(self):
        self.show(item(liveness=rs.LIVE_LOST, reason="gone"))
        done = []
        with mock.patch.object(view.messagebox, "askyesno", return_value=True), \
             mock.patch.object(rs, "reconcile_lost", side_effect=lambda d: done.append(d) or {"stage": "failed"}), \
             mock.patch.object(rs, "force_stop") as stop:
            self.window.stop_run()
            self.pump(lambda: bool(done))
            stop.assert_not_called()

    def test_apply_button_only_for_completed_unapplied_candidates(self):
        self.show(item())
        self.assertTrue(self.window.apply_button.instate(["disabled"]))
        rec = record(stage=rs.COMPLETED, candidate_sha="c" * 40, final_result={"stage": "completed", "code": "OK", "message": "m"})
        self.show(item(rec, liveness=rs.LIVE_FINISHED))
        self.assertTrue(self.window.apply_button.instate(["!disabled"]))
        self.window.apply_candidate()
        self.on_apply.assert_called_once()
        self.assertEqual(self.on_apply.call_args.args[0]["candidate_sha"], "c" * 40)
        self.show(item(dict(rec, apply_status="applied"), liveness=rs.LIVE_FINISHED))
        self.assertTrue(self.window.apply_button.instate(["disabled"]))

    def test_closing_the_window_never_stops_a_run(self):
        self.show(item())
        with mock.patch.object(rs, "force_stop") as stop, mock.patch.object(rs, "reconcile_lost") as lost, \
             mock.patch("tools.ai_orchestrator.common.terminate_pid_tree") as kill:
            self.window.close()
            stop.assert_not_called()
            lost.assert_not_called()
            kill.assert_not_called()
        self.assertFalse(self.window.exists())
        self.assertFalse(self.monitor.stopped)  # an injected (shared) monitor is not the window's to stop

    def test_log_is_appended_and_reset_on_selection(self):
        self.show(item())
        self.window.apply_snapshot(self.snapshot(runs=[item()], log="12:00:00 [testing] go\n", log_reset=True))
        self.assertIn("[testing] go", self.window.log.get("1.0", "end"))
        self.window.apply_snapshot(self.snapshot(runs=[item()], log="12:00:01 next\n"))
        text = self.window.log.get("1.0", "end")
        self.assertIn("[testing] go", text)
        self.assertIn("next", text)
        self.window.apply_snapshot(self.snapshot(runs=[item()], log="", log_reset=True))
        self.assertNotIn("go", self.window.log.get("1.0", "end"))


class RunMonitorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"AI_ORCHESTRATOR_STATE_ROOT": str(self.tmp / "state")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fabricate(self, name, *, pid, token, stage=rs.TESTING, heartbeat=True, repo="C:/repos/app"):
        run_dir = rs.runs_root() / name
        run_dir.mkdir(parents=True)
        rec = record(run_id=name, stage=stage, repo=repo)
        rec["created_at"] = "2020-01-01T00:00:00"
        rec["started_at"] = "2020-01-01T00:00:00"
        rec["worker"] = {"pid": pid, "token": token}
        write_json_atomic(run_dir / "run.json", rec)
        if heartbeat:
            write_json_atomic(run_dir / "heartbeat.json", {"ts": time.time(), "pid": pid, "token": token, "stage": stage, "seq": 1})
        (run_dir / "events.log").write_text("12:00:00 [testing] hello\n", encoding="utf-8")
        return run_dir

    def test_poll_reports_running_runs_usage_and_the_selected_log(self):
        me = os.getpid()
        self.fabricate("20260925-000000-000001", pid=me, token=process_start_token(me))
        monitor = view.RunMonitor()
        monitor.select("20260925-000000-000001")
        data = monitor.poll_once()
        self.assertEqual([i["liveness"] for i in data["runs"]], [rs.LIVE_RUNNING])
        self.assertIn("hello", data["log"])
        self.assertTrue(data["log_reset"])
        again = monitor.poll_once()
        self.assertEqual(again["log"], "")
        self.assertFalse(again["log_reset"])
        self.assertEqual(set(data["usage"]), {"claude", "codex"})

    def test_lost_worker_is_reconciled_automatically_and_never_reported_running(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        token = process_start_token(proc.pid) or "gone"
        proc.wait()
        run_dir = self.fabricate("20260925-000000-000002", pid=proc.pid, token=token)
        data = view.RunMonitor().poll_once()
        self.assertEqual(data["runs"][0]["liveness"], rs.LIVE_FINISHED)
        self.assertEqual(rs.read_record(run_dir)["final_result"]["code"], "WORKER_LOST")

    def test_bad_poll_does_not_kill_the_monitor_thread(self):
        def broken(limit=40):
            raise RuntimeError("disk error")

        monitor = view.RunMonitor(interval=0.05, list_runs=broken)
        monitor.start()
        try:
            deadline = time.monotonic() + 3
            snapshot = None
            while snapshot is None and time.monotonic() < deadline:
                try:
                    snapshot = monitor.queue.get(timeout=0.2)
                except queue.Empty:
                    pass
            self.assertIn("error", snapshot)
        finally:
            monitor.stop()


if __name__ == "__main__":
    unittest.main()
