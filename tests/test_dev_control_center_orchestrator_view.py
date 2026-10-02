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

    def test_repo_default_tests_are_prefilled_editable_and_start_prepares_the_source(self):
        self.assertEqual(self.window.tests_var.get(), "python -m unittest")  # the repo's configured default
        self.window.tests_var.set("python -m unittest discover -s tests -p 'test_*.py' -q")  # user edit
        self.window.repo_var.set("other")
        self.window._on_repo_changed()
        self.assertEqual(self.window.tests_var.get(), "")
        self.window.repo_var.set("app")
        self.window._on_repo_changed()
        self.assertEqual(self.window.tests_var.get(), "python -m unittest discover -s tests -p 'test_*.py' -q")
        captured = []
        self.window.task_text.insert("1.0", "x")
        with mock.patch.object(orch, "start_run", side_effect=lambda r, **k: captured.append(r) or Path("C:/runs/r1")):
            self.window.start_run()
            self.pump(lambda: bool(captured))
        self.assertEqual(captured[0].tests, ["python -m unittest discover -s tests -p 'test_*.py' -q"])
        self.assertTrue(captured[0].prepare_source)
        self.assertFalse(captured[0].allow_no_tests)

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

    def test_source_preparation_is_shown_from_the_orchestrator_record(self):
        self.show(item(record(source_preparation=["switched chatgpt/x -> main (chatgpt/x is kept)"])))
        self.assertIn("switched chatgpt/x -> main", self.window.prep_var.get())
        self.assertIn("main@aaaaaaaaaaaa", self.window.prep_var.get())
        self.show(item(record(source_preparation=[])))
        self.assertIn("変更なし", self.window.prep_var.get())
        self.show(item(record(source_preparation=None)))
        self.assertIn("自動準備なし", self.window.prep_var.get())
        self.window.selected_run = None
        self.window.apply_snapshot(self.snapshot())
        self.assertEqual(self.window.prep_var.get(), "-")
        self.assertTrue(self.window.copy_button.instate(["disabled"]))

    def test_copy_log_puts_the_run_report_on_the_clipboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260925-100000-000001"
            run_dir.mkdir()
            rec = record(source_preparation=["switched feature -> main (feature is kept)"])
            write_json_atomic(run_dir / "run.json", rec)
            (run_dir / "events.log").write_text("10:00:00 [preflight] CLI・worktreeを準備中\n", encoding="utf-8")
            self.show(item(rec, run_dir=run_dir))  # task.md / worker.out / tests do not exist: skipped
            self.assertTrue(self.window.copy_button.instate(["!disabled"]))
            self.window.copy_run_log()
            copied = self.root.clipboard_get()
        self.assertIn("run id: 20260925-100000-000001", copied)
        self.assertIn("source_preparation: switched feature -> main", copied)
        self.assertIn("CLI・worktreeを準備中", copied)
        self.assertNotIn("## worker.out", copied)
        self.assertIn("コピーしました", self.window.notice_var.get())

    def test_open_run_folder_opens_only_the_selected_run_dir(self):
        run_dir = Path("C:/runs/20260925-100000-000001")
        self.show(item(run_dir=run_dir))
        if os.name == "nt":
            with mock.patch.object(view.os, "startfile", create=True) as opener:
                self.window.open_run_dir()
            opener.assert_called_once_with(str(run_dir))
        else:
            with mock.patch.object(view.subprocess, "Popen") as opener:
                self.window.open_run_dir()
            self.assertEqual(opener.call_args.args[0][-1], str(run_dir))

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


class RunListRowClickLogicTests(unittest.TestCase):
    """resolve_click_index is pure (Tk-free): a margin click, a scrolled-out row, or an empty
    list must never resolve to a row, regardless of what nearest() clamps to."""

    @staticmethod
    def _nearest(rows):
        def nearest(y):
            if not rows:
                return 0
            best = 0
            for i, (top, _height) in enumerate(rows):
                if y < top:
                    break
                best = i
            return best
        return nearest

    @staticmethod
    def _bbox(rows):
        def bbox(index):
            if index is None or not (0 <= index < len(rows)):
                return None
            top, height = rows[index]
            return (0, top, 200, height)
        return bbox

    def test_click_inside_a_row_resolves_to_that_row(self):
        rows = [(0, 20), (20, 20), (40, 20)]
        self.assertEqual(view.resolve_click_index(25, 3, self._nearest(rows), self._bbox(rows)), 1)

    def test_click_in_the_margin_below_the_last_row_resolves_to_nothing(self):
        rows = [(0, 20), (20, 20), (40, 20)]
        self.assertIsNone(view.resolve_click_index(5000, 3, self._nearest(rows), self._bbox(rows)))

    def test_click_on_an_empty_list_resolves_to_nothing(self):
        self.assertIsNone(view.resolve_click_index(10, 0, self._nearest([]), self._bbox([])))

    def test_a_scrolled_out_row_with_no_bbox_resolves_to_nothing(self):
        self.assertIsNone(view.resolve_click_index(10, 3, lambda _y: 0, lambda _i: None))


class _FakeRunListbox:
    """A Listbox stand-in exposing only what the click handlers touch — no real Tk widget."""

    def __init__(self, rows):
        self.rows = rows
        self.selection = None
        self.focused = False

    def size(self):
        return len(self.rows)

    def nearest(self, y):
        if not self.rows:
            return 0
        best = 0
        for i, (top, _height) in enumerate(self.rows):
            if y < top:
                break
            best = i
        return best

    def bbox(self, index):
        if index is None or not (0 <= index < len(self.rows)):
            return None
        top, height = self.rows[index]
        return (0, top, 200, height)

    def selection_clear(self, _start, _end):
        self.selection = None

    def selection_set(self, index):
        self.selection = index

    def focus_set(self):
        self.focused = True

    def curselection(self):
        return (self.selection,) if self.selection is not None else ()


class _FakeOrchestratorWindow:
    """Stands in for the bits of OrchestratorWindow that _on_run_click / _on_run_selected touch."""

    def __init__(self, rows, run_ids):
        self.run_list = _FakeRunListbox(rows)
        self.run_items = [{"record": {"run_id": rid}} for rid in run_ids]
        self.selected_run = None
        self.monitor_selected = []
        self.render_count = 0

    def _render_selected(self):
        self.render_count += 1

    _on_run_selected = view.OrchestratorWindow._on_run_selected

    class _Monitor:
        def __init__(self, outer):
            self.outer = outer

        def select(self, run_id):
            self.outer.monitor_selected.append(run_id)

    @property
    def monitor(self):
        return self._Monitor(self)


class RunListClickWiringTests(unittest.TestCase):
    """The bound handlers themselves, exercised against a fake Listbox (no real window)."""

    def test_clicking_a_row_selects_that_run_and_renders_once(self):
        win = _FakeOrchestratorWindow([(0, 20), (20, 20), (40, 20)], ["r0", "r1", "r2"])
        result = view.OrchestratorWindow._on_run_click(win, SimpleNamespace(y=25))
        self.assertEqual(result, "break")
        self.assertEqual(win.selected_run, "r1")
        self.assertEqual(win.monitor_selected, ["r1"])
        self.assertEqual(win.render_count, 1)
        self.assertTrue(win.run_list.focused)

    def test_margin_click_leaves_the_selection_untouched(self):
        win = _FakeOrchestratorWindow([(0, 20), (20, 20), (40, 20)], ["r0", "r1", "r2"])
        win.selected_run = "r0"
        result = view.OrchestratorWindow._on_run_click(win, SimpleNamespace(y=9000))
        self.assertEqual(result, "break")
        self.assertEqual(win.selected_run, "r0")
        self.assertEqual(win.monitor_selected, [])
        self.assertEqual(win.render_count, 0)

    def test_drag_motion_always_breaks_without_touching_selection(self):
        win = _FakeOrchestratorWindow([(0, 20), (20, 20)], ["r0", "r1"])
        win.selected_run = "r0"
        result = view.OrchestratorWindow._on_run_drag(win, SimpleNamespace(y=25))
        self.assertEqual(result, "break")
        self.assertEqual(win.selected_run, "r0")
        self.assertEqual(win.render_count, 0)


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



class CharacterMoodTests(ViewCase):
    def test_character_follows_the_selected_run(self):
        character = self.window.character
        self.assertTrue(character.available)
        self.assertEqual(character.mood, "idle")
        self.window.apply_snapshot(self.snapshot(runs=[item()]))
        self.assertEqual(character.mood, "test")
        self.window.apply_snapshot(self.snapshot(runs=[item(record(stage=rs.NEEDS_HUMAN), liveness=rs.LIVE_FINISHED)]))
        self.assertEqual(character.mood, "error")
        self.window.apply_snapshot(self.snapshot(runs=[item(record(stage=rs.COMPLETED), liveness=rs.LIVE_FINISHED)]))
        self.assertEqual(character.mood, "done")

    def test_closing_the_window_stops_the_character(self):
        character = self.window.character
        self.window.close()
        self.assertTrue(character._destroyed)
        self.assertIsNone(character._after_id)


if __name__ == "__main__":
    unittest.main()
