"""Focused tests for the DCC "AI安全停止" (AI safety stop) feature.

Scope: Issue #35, AI safety stop only. These tests never start a real
Orchestrator, Claude, or Codex process. They exercise scripts/dev_control_center/app.py
methods directly against a MagicMock stand-in for `self` (the established
pattern in tests/test_dev_control_center_utf8.py), plus one real
process-tree kill test using plain Python subprocesses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue as queue_module
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts.dev_control_center import app as dcc

ROOT = Path(__file__).resolve().parents[1]


def _pid_alive(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return str(pid) in result.stdout


class StopGatingTests(unittest.TestCase):
    """Requirement: safety stop only ever acts while AI Orchestrator is running."""

    def test_stop_is_noop_when_idle(self):
        ui = mock.MagicMock()
        ui.active_process = None
        ui.ai_stop_requested = False
        with mock.patch.object(dcc.messagebox, "askyesno") as askyesno, \
                mock.patch.object(dcc, "_terminate_ai_process_tree") as terminate:
            dcc.App.stop_ai_orchestrator(ui)
        askyesno.assert_not_called()
        terminate.assert_not_called()
        self.assertFalse(ui.ai_stop_requested)

    def test_stop_is_noop_when_busy_with_a_non_ai_action(self):
        ui = mock.MagicMock()
        fake_process = mock.MagicMock()
        ui.active_process = (fake_process, "repo-x", "build")
        ui.ai_stop_requested = False
        with mock.patch.object(dcc.messagebox, "askyesno") as askyesno, \
                mock.patch.object(dcc, "_terminate_ai_process_tree") as terminate:
            dcc.App.stop_ai_orchestrator(ui)
        askyesno.assert_not_called()
        terminate.assert_not_called()
        self.assertFalse(ui.ai_stop_requested)

    def test_stop_terminates_process_tree_and_sets_flag_when_confirmed(self):
        ui = mock.MagicMock()
        fake_process = mock.MagicMock()
        ui.active_process = (fake_process, "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        with mock.patch.object(dcc.messagebox, "askyesno", return_value=True) as askyesno, \
                mock.patch.object(dcc, "_terminate_ai_process_tree") as terminate:
            dcc.App.stop_ai_orchestrator(ui)
        askyesno.assert_called_once()
        terminate.assert_called_once_with(fake_process)
        self.assertTrue(ui.ai_stop_requested)
        ui.ai_stop_button.configure.assert_called_with(state="disabled")

    def test_stop_declines_without_terminating_when_user_cancels_confirmation(self):
        ui = mock.MagicMock()
        fake_process = mock.MagicMock()
        ui.active_process = (fake_process, "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        with mock.patch.object(dcc.messagebox, "askyesno", return_value=False), \
                mock.patch.object(dcc, "_terminate_ai_process_tree") as terminate:
            dcc.App.stop_ai_orchestrator(ui)
        terminate.assert_not_called()
        self.assertFalse(ui.ai_stop_requested)


class StopButtonStateTests(unittest.TestCase):
    """Requirement: the stop button is enabled only while an AI run is active."""

    def _apply(self, ui) -> None:
        # No repo selected: _apply_lifecycle_state sets ai_stop_button state
        # before its repo-specific (decide_lifecycle) branch, so this alone
        # exercises the new logic without stubbing Git/GitHub state.
        ui.current = None
        dcc.App._apply_lifecycle_state(ui)

    def test_disabled_when_idle(self):
        ui = mock.MagicMock()
        ui.active_process = None
        ui.ai_stop_requested = False
        self._apply(ui)
        ui.ai_stop_button.configure.assert_any_call(state="disabled")

    def test_disabled_when_busy_with_a_non_ai_action(self):
        ui = mock.MagicMock()
        ui.active_process = (mock.MagicMock(), "repo-x", "release")
        ui.ai_stop_requested = False
        self._apply(ui)
        ui.ai_stop_button.configure.assert_any_call(state="disabled")

    def test_disabled_while_running_but_run_dir_not_yet_captured(self):
        ui = mock.MagicMock()
        ui.active_process = (mock.MagicMock(), "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        ui.ai_context = {"repo_name": "repo-x"}  # run_dir marker not seen yet
        self._apply(ui)
        ui.ai_stop_button.configure.assert_any_call(state="disabled")

    def test_disabled_when_ai_context_is_none(self):
        ui = mock.MagicMock()
        ui.active_process = (mock.MagicMock(), "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        ui.ai_context = None
        self._apply(ui)
        ui.ai_stop_button.configure.assert_any_call(state="disabled")

    def test_enabled_once_run_dir_has_been_captured(self):
        ui = mock.MagicMock()
        ui.active_process = (mock.MagicMock(), "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        ui.ai_context = {"repo_name": "repo-x", "run_dir": Path("C:\\fake\\runs\\x")}
        self._apply(ui)
        ui.ai_stop_button.configure.assert_any_call(state="normal")

    def test_disabled_again_once_a_stop_has_been_requested(self):
        ui = mock.MagicMock()
        ui.active_process = (mock.MagicMock(), "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = True
        ui.ai_context = {"repo_name": "repo-x", "run_dir": Path("C:\\fake\\runs\\x")}
        self._apply(ui)
        ui.ai_stop_button.configure.assert_any_call(state="disabled")


class FinishAfterStopTests(unittest.TestCase):
    """Requirement: STOPPED reason, no candidate, busy already released."""

    def test_user_stop_reports_the_required_reason_and_skips_result_handling(self):
        ui = mock.MagicMock()
        ui.ai_stop_requested = True
        ui.ai_context = {
            "repo_name": "demo",
            "result_path": Path("does-not-matter.json"),
            "base_sha": "a" * 40,
        }
        with mock.patch.object(dcc.json, "loads") as loads_mock:
            dcc.App._finish_ai_orchestrator(ui, "demo", 1)
        loads_mock.assert_not_called()
        self.assertFalse(ui.ai_stop_requested)
        status_text = ui.ai_status_var.set.call_args.args[0]
        self.assertIn("ユーザーによる安全停止", status_text)
        banner_text = ui.banner_var.set.call_args.args[0]
        self.assertIn("ユーザーによる安全停止", banner_text)
        ui.selection.provenance.ai_result.assert_not_called()
        ui._reload_after.assert_called_once_with("demo")

    def test_user_stop_never_touches_files_run_and_worktree_info_preserved(self):
        ui = mock.MagicMock()
        ui.ai_stop_requested = True
        ui.ai_context = {
            "repo_name": "demo",
            "result_path": Path("does-not-matter.json"),
            "base_sha": "a" * 40,
        }
        with mock.patch.object(dcc.Path, "unlink") as unlink_mock, \
                mock.patch.object(dcc, "apply_local_candidate") as apply_candidate:
            dcc.App._finish_ai_orchestrator(ui, "demo", 1)
        unlink_mock.assert_not_called()
        apply_candidate.assert_not_called()

    def test_finish_after_stop_does_not_reacquire_busy_state(self):
        ui = mock.MagicMock()
        ui.active_process = None  # _end_process already released busy before this runs
        ui.ai_stop_requested = True
        ui.ai_context = {"repo_name": "demo", "result_path": Path("x.json")}
        dcc.App._finish_ai_orchestrator(ui, "demo", 1)
        self.assertIsNone(ui.active_process)

    def test_non_stop_failure_still_uses_the_original_error_path(self):
        """Regression: an ordinary (non-safety-stop) failure must be unaffected."""
        ui = mock.MagicMock()
        ui.ai_stop_requested = False
        ui.ai_context = {
            "repo_name": "demo",
            "result_path": Path("this-file-does-not-exist-anywhere.json"),
            "base_sha": "a" * 40,
        }
        with mock.patch.object(dcc.messagebox, "showerror") as showerror:
            dcc.App._finish_ai_orchestrator(ui, "demo", 1)
        showerror.assert_called_once()
        status_text = ui.ai_status_var.set.call_args.args[0]
        self.assertTrue(status_text.startswith("STOP:"))
        self.assertNotIn("ユーザーによる安全停止", status_text)


class SourceCandidateRemoteUnchangedTests(unittest.TestCase):
    """Requirement: source main / candidate / remote are never touched by a stop."""

    def test_stop_then_finish_never_applies_a_candidate_or_touches_git(self):
        ui = mock.MagicMock()
        fake_process = mock.MagicMock()
        ui.active_process = (fake_process, "demo", "ai_orchestrator")
        ui.ai_stop_requested = False
        ui.ai_context = {
            "repo_name": "demo",
            "result_path": Path("nonexistent-result.json"),
            "base_sha": "a" * 40,
        }
        with mock.patch.object(dcc.messagebox, "askyesno", return_value=True), \
                mock.patch.object(dcc, "_terminate_ai_process_tree") as terminate, \
                mock.patch.object(dcc, "apply_local_candidate") as apply_candidate:
            dcc.App.stop_ai_orchestrator(ui)
            # Simulate what _poll observes once the killed process has exited.
            dcc.App._finish_ai_orchestrator(ui, "demo", 1)

        terminate.assert_called_once_with(fake_process)
        apply_candidate.assert_not_called()
        ui.selection.provenance.ai_result.assert_not_called()
        self.assertFalse(ui.ai_stop_requested)

    @unittest.skipUnless(os.name == "nt", "taskkill process-tree behaviour is Windows-specific")
    def test_stop_issues_only_a_taskkill_never_a_git_or_worktree_command(self):
        ui = mock.MagicMock()
        fake_process = mock.MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 999999
        ui.active_process = (fake_process, "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        with mock.patch.object(dcc.messagebox, "askyesno", return_value=True), \
                mock.patch.object(dcc.subprocess, "run") as run_mock:
            dcc.App.stop_ai_orchestrator(ui)
        run_mock.assert_called_once()
        args = run_mock.call_args.args[0]
        self.assertEqual(args[0], "taskkill")
        joined = " ".join(args)
        self.assertNotIn("git", joined)
        self.assertNotIn("worktree", joined)


class WindowCloseIsADistinctActionTests(unittest.TestCase):
    """Requirement: window close and safety stop must not be the same code path."""

    def test_window_close_never_triggers_the_ai_process_tree_kill(self):
        ui = mock.MagicMock()
        with mock.patch.object(dcc, "_terminate_ai_process_tree") as terminate:
            dcc.App._on_close(ui)
        terminate.assert_not_called()
        ui.stop_ai_orchestrator.assert_not_called()
        ui.master.destroy.assert_called_once()

    def test_safety_stop_never_closes_the_window(self):
        ui = mock.MagicMock()
        fake_process = mock.MagicMock()
        ui.active_process = (fake_process, "repo-x", "ai_orchestrator")
        ui.ai_stop_requested = False
        with mock.patch.object(dcc.messagebox, "askyesno", return_value=True), \
                mock.patch.object(dcc, "_terminate_ai_process_tree"):
            dcc.App.stop_ai_orchestrator(ui)
        ui.master.destroy.assert_not_called()
        ui.selection.close.assert_not_called()


class TerminateProcessTreeTests(unittest.TestCase):
    """Requirement: Orchestrator AND its Claude/Codex-style child processes stop."""

    def test_noop_when_process_already_exited(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=10)
        with mock.patch.object(dcc.subprocess, "run") as run_mock:
            dcc._terminate_ai_process_tree(proc)
        run_mock.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "taskkill process-tree kill is Windows-specific")
    def test_kills_parent_and_grandchild_process(self):
        parent_script = (
            "import subprocess, sys, time;"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
            "print(p.pid, flush=True);"
            "time.sleep(60)"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", parent_script],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            line = ""
            while time.monotonic() < deadline and not line.strip():
                line = proc.stdout.readline()
            self.assertTrue(line.strip(), "grandchild PID was never printed")
            grandchild_pid = int(line.strip())
            self.assertTrue(_pid_alive(grandchild_pid))

            dcc._terminate_ai_process_tree(proc)

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and _pid_alive(grandchild_pid):
                time.sleep(0.1)
            self.assertFalse(_pid_alive(grandchild_pid), "grandchild survived the safety stop")
            self.assertIsNotNone(proc.poll(), "parent Orchestrator process survived the safety stop")
        finally:
            if proc.poll() is None:
                proc.kill()
            if proc.stdout is not None:
                proc.stdout.close()


class RunDirMarkerContractTests(unittest.TestCase):
    """The app's parser and the Orchestrator's printed marker must agree."""

    def test_orchestrator_prints_the_exact_marker_app_expects(self):
        text = (ROOT / "tools" / "ai_orchestrator" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn('print(f"[Preflight] run_dir={run_dir}", flush=True)', text)
        self.assertEqual(dcc._AI_RUN_DIR_MARKER, "[Preflight] run_dir=")


class RunDirMarkerCaptureTests(unittest.TestCase):
    """DCC learns the run's durable state directory from Orchestrator stdout."""

    def test_drain_ai_output_captures_run_dir_marker_into_context(self):
        ui = mock.MagicMock()
        ui.ai_context = {"repo_name": "demo"}
        ui.ai_output_queue = queue_module.Queue()
        for line in (
            "[Preflight] Checking CLI tools and billing guard...",
            "[Preflight] run_dir=C:\\fake\\runs\\20260924-120000-000000",
            "[Preflight] source repo verified",
        ):
            ui.ai_output_queue.put(line)
        dcc.App._drain_ai_output(ui)
        self.assertEqual(
            ui.ai_context["run_dir"],
            Path("C:\\fake\\runs\\20260924-120000-000000"),
        )

    def test_marker_is_ignored_when_there_is_no_active_context(self):
        ui = mock.MagicMock()
        ui.ai_context = None
        ui.ai_output_queue = queue_module.Queue()
        ui.ai_output_queue.put("[Preflight] run_dir=C:\\fake\\runs\\x")
        dcc.App._drain_ai_output(ui)  # must not raise

    def test_capturing_the_marker_immediately_reevaluates_lifecycle_state(self):
        ui = mock.MagicMock()
        ui.ai_context = {"repo_name": "demo"}
        ui.ai_output_queue = queue_module.Queue()
        ui.ai_output_queue.put("[Preflight] Checking CLI tools and billing guard...")
        ui.ai_output_queue.put("[Preflight] run_dir=C:\\fake\\runs\\20260924-120000-000000")
        dcc.App._drain_ai_output(ui)
        # Exactly the marker line triggers a re-evaluation, not every line.
        ui._apply_lifecycle_state.assert_called_once()

    def test_marker_capture_end_to_end_enables_the_real_stop_button(self):
        """Wires the real _apply_lifecycle_state onto the mock to prove the
        marker -> context update -> re-evaluation -> enabled-button chain
        actually works together, not just that each piece is called."""
        ui = mock.MagicMock()
        ui.active_process = (mock.MagicMock(), "demo", "ai_orchestrator")
        ui.ai_stop_requested = False
        ui.ai_context = {"repo_name": "demo"}
        ui.current = None
        ui._apply_lifecycle_state = lambda: dcc.App._apply_lifecycle_state(ui)
        ui.ai_output_queue = queue_module.Queue()
        ui.ai_output_queue.put("[Preflight] run_dir=C:\\fake\\runs\\20260924-120000-000000")

        ui.ai_stop_button.configure.assert_not_called()
        dcc.App._drain_ai_output(ui)

        ui.ai_stop_button.configure.assert_any_call(state="normal")


class RunPersistenceOnSafetyStopTests(unittest.TestCase):
    """Requirement: status.json/result.json durably record the safety stop."""

    @staticmethod
    def _make_run_dir(tmp: str) -> Path:
        run_dir = Path(tmp) / "runs" / "20260924-120000-000000"
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(
            json.dumps(
                {
                    "stage": "implementation",
                    "round": 3,
                    "max_rounds": 30,
                    "claude_calls": 4,
                    "codex_calls": 2,
                    "detail": "Claude implementing...",
                    "updated_at": "2026-09-24T12:00:05",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "status": "running",
                    "version": "0.5-astra-design",
                    "run_id": run_dir.name,
                    "repo": "C:/repos/demo",
                    "base_sha": "a" * 40,
                    "source_branch": "main",
                    "worktree": str(run_dir / "worktree"),
                    "run_dir": str(run_dir),
                    "review_model": "gpt-6-astra",
                    "billing_env_override": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return run_dir

    def _finish_stopped(self, run_dir: Path) -> None:
        ui = mock.MagicMock()
        ui.ai_stop_requested = True
        ui.ai_context = {"repo_name": "demo", "result_path": Path("unused.json"), "run_dir": run_dir}
        dcc.App._finish_ai_orchestrator(ui, "demo", 1)

    def test_status_json_becomes_stopped_with_the_required_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            self._finish_stopped(run_dir)
            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "stopped")
            self.assertEqual(status["reason"], "ユーザーによる安全停止")

    def test_result_json_reason_is_the_required_safety_stop_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            self._finish_stopped(run_dir)
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["error"], "ユーザーによる安全停止")

    def test_existing_run_metadata_is_preserved_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            self._finish_stopped(run_dir)

            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["stage"], "implementation")
            self.assertEqual(status["round"], 3)
            self.assertEqual(status["max_rounds"], 30)
            self.assertEqual(status["claude_calls"], 4)
            self.assertEqual(status["codex_calls"], 2)

            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["run_id"], run_dir.name)
            self.assertEqual(result["worktree"], str(run_dir / "worktree"))
            self.assertEqual(result["base_sha"], "a" * 40)
            self.assertEqual(result["source_branch"], "main")
            self.assertEqual(result["review_model"], "gpt-6-astra")

    def test_missing_result_json_is_created_with_run_id_and_stopped_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "20260924-130000-000000"
            run_dir.mkdir(parents=True)
            (run_dir / "status.json").write_text(
                json.dumps({"stage": "preflight", "round": 0}), encoding="utf-8"
            )
            # result.json was never written by the killed process.
            self._finish_stopped(run_dir)
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["run_id"], run_dir.name)
            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["error"], "ユーザーによる安全停止")

    def test_worktree_directory_itself_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            worktree = run_dir / "worktree"
            worktree.mkdir()
            marker = worktree / "keep-me.txt"
            marker.write_text("still here", encoding="utf-8")
            self._finish_stopped(run_dir)
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_text(encoding="utf-8"), "still here")

    def test_candidate_is_not_applied_by_the_persistence_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            ui = mock.MagicMock()
            ui.ai_stop_requested = True
            ui.ai_context = {"repo_name": "demo", "result_path": Path("unused.json"), "run_dir": run_dir}
            with mock.patch.object(dcc, "apply_local_candidate") as apply_candidate:
                dcc.App._finish_ai_orchestrator(ui, "demo", 1)
            apply_candidate.assert_not_called()
            ui.selection.provenance.ai_result.assert_not_called()

    def test_normal_error_path_does_not_touch_run_dir_files(self):
        """Regression: an ordinary (non-safety-stop) failure is unaffected."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            before_status = (run_dir / "status.json").read_text(encoding="utf-8")
            before_result = (run_dir / "result.json").read_text(encoding="utf-8")

            ui = mock.MagicMock()
            ui.ai_stop_requested = False
            ui.ai_context = {
                "repo_name": "demo",
                "result_path": Path("this-file-does-not-exist-anywhere.json"),
                "run_dir": run_dir,
            }
            with mock.patch.object(dcc.messagebox, "showerror"):
                dcc.App._finish_ai_orchestrator(ui, "demo", 1)

            self.assertEqual((run_dir / "status.json").read_text(encoding="utf-8"), before_status)
            self.assertEqual((run_dir / "result.json").read_text(encoding="utf-8"), before_result)

    def test_normal_success_path_does_not_touch_run_dir_files_either(self):
        """Regression: a genuine candidate-ready completion is unaffected."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run_dir(tmp)
            before_status = (run_dir / "status.json").read_text(encoding="utf-8")
            before_result = (run_dir / "result.json").read_text(encoding="utf-8")

            result_path = Path(tmp) / "external-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "status": "candidate_ready",
                        "candidate_sha": "b" * 40,
                        "base_sha": "a" * 40,
                    }
                ),
                encoding="utf-8",
            )
            ui = mock.MagicMock()
            ui.ai_stop_requested = False
            ui.current = None
            ui.ai_context = {"repo_name": "demo", "result_path": result_path, "run_dir": run_dir}
            dcc.App._finish_ai_orchestrator(ui, "demo", 0)

            self.assertEqual((run_dir / "status.json").read_text(encoding="utf-8"), before_status)
            self.assertEqual((run_dir / "result.json").read_text(encoding="utf-8"), before_result)


class MarkerCaptureThenSafetyStopEndToEndTests(unittest.TestCase):
    """Requirement: once run_dir is captured, a stop always persists USER_SAFETY_STOP."""

    def test_full_flow_persists_user_safety_stop_after_run_dir_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "20260924-140000-000000"
            run_dir.mkdir(parents=True)
            (run_dir / "status.json").write_text(
                json.dumps({"stage": "preflight", "round": 0}), encoding="utf-8"
            )

            ui = mock.MagicMock()
            fake_process = mock.MagicMock()
            ui.active_process = (fake_process, "demo", "ai_orchestrator")
            ui.ai_stop_requested = False
            ui.ai_context = {"repo_name": "demo", "result_path": Path("unused.json")}
            ui.ai_output_queue = queue_module.Queue()
            ui.ai_output_queue.put(f"[Preflight] run_dir={run_dir}")

            # 1) Orchestrator announces its run_dir; DCC captures it.
            dcc.App._drain_ai_output(ui)
            self.assertEqual(ui.ai_context["run_dir"], run_dir)

            # 2) User requests the safety stop (now that run_dir is known).
            with mock.patch.object(dcc.messagebox, "askyesno", return_value=True), \
                    mock.patch.object(dcc, "_terminate_ai_process_tree"):
                dcc.App.stop_ai_orchestrator(ui)
            self.assertTrue(ui.ai_stop_requested)

            # 3) _poll observes the killed process and finalizes.
            dcc.App._finish_ai_orchestrator(ui, "demo", 1)

            status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "stopped")
            self.assertEqual(status["reason"], "ユーザーによる安全停止")
            result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["error"], "ユーザーによる安全停止")
            self.assertEqual(result["error_code"], "USER_SAFETY_STOP")


if __name__ == "__main__":
    unittest.main()
