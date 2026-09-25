"""Phase 1 acceptance: direct development, separated UI, build/release integrity."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch, MagicMock

from scripts.dev_control_center import app as dcc
from scripts.dev_control_center import orchestrator_view as orch_view, provenance as p
from scripts.dev_control_center.core import RepoDefinition, RepoState


class BuildReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dcc phase1 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "menu-sheet-generator"
        self.repo.mkdir()
        self.artifact = self.repo / "publish"
        self.target = self.root / "target"
        self.target.mkdir()
        self.entry = self.repo / "BUILD_RELEASE.cmd"
        self.entry.write_text("@echo off\nif not exist publish mkdir publish\necho new>publish\\app.exe\nexit /b 0\n", encoding="ascii")
        (self.repo / "UPDATE.cmd").write_text("@echo off\nexit /b 0\n", encoding="ascii")
        (self.repo / "source.py").write_text("first", encoding="utf-8")
        (self.repo / ".gitignore").write_text("publish/\nsecret.ini\n", encoding="ascii")
        (self.repo / "dcc_entrypoints.json").write_text(json.dumps({"schema": 1, "build": {"script": "build_body.py"}}), encoding="utf-8")
        (self.repo / "build_body.py").write_text("from pathlib import Path\np=Path('publish');p.mkdir(exist_ok=True)\n(p/'app.exe').write_text('new')\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        p.git(self.repo, "add", ".")
        p.git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.scope = patch.object(p, "state_root", return_value=self.root / "state")
        self.scope.start(); self.addCleanup(self.scope.stop)

    def fake_build(self, mutation=None, rc=0):
        def execute(*_args, **_kwargs):
            self.artifact.mkdir(exist_ok=True)
            (self.artifact / "app.exe").write_bytes(b"artifact")
            if mutation:
                mutation()
            return rc
        with patch.object(p.processes, "stream", side_effect=execute):
            return p.build(self.repo, self.entry, self.artifact)

    def test_dirty_build_has_hashes_and_no_source_content(self):
        (self.repo / "source.py").write_text("PRIVATE INPUT CONTENT", encoding="utf-8")
        record = self.fake_build()
        self.assertEqual(record["status"], "ready")
        self.assertTrue(record["dirty"])
        for key in ("repo", "base_head", "started_at", "finished_at", "build_id", "artifact", "artifact_hash"):
            self.assertTrue(record[key])
        self.assertNotIn("PRIVATE INPUT CONTENT", p.receipt_path(self.repo).read_text(encoding="utf-8"))
        self.assertEqual(p.read_receipt(self.repo), record)

    def test_input_change_during_build_rejects_artifact(self):
        record = self.fake_build(lambda: (self.repo / "source.py").write_text("changed", encoding="utf-8"))
        self.assertEqual(record["status"], "rejected")
        with self.assertRaises(ValueError):
            p.read_receipt(self.repo)

    def test_failure_invalidates_previous_success(self):
        self.fake_build()
        self.assertEqual(self.fake_build(rc=1)["status"], "rejected")
        with self.assertRaises(ValueError):
            p.read_receipt(self.repo)

    def test_old_artifact_and_false_success_do_not_count_as_a_build(self):
        self.fake_build()
        with patch.object(p.processes, "stream", return_value=0):
            record = p.build(self.repo, self.entry, self.artifact)
        self.assertEqual(record["status"], "rejected")
        self.assertFalse(record["artifact_refreshed"])

    def test_ignored_build_settings_can_be_monitored_without_recording_contents(self):
        (self.repo / ".dcc-build-inputs.json").write_text('["secret.ini"]', encoding="utf-8")
        setting = self.repo / "secret.ini"
        setting.write_text("SECRET", encoding="ascii")
        self.fake_build()
        setting.write_text("OTHER SECRET", encoding="ascii")
        with self.assertRaises(ValueError):
            p.read_receipt(self.repo)

    def test_release_passes_exact_target_and_validates_again(self):
        self.fake_build()
        request = p.release_snapshot(self.repo, self.target)
        self.assertIn(str(self.target.resolve()), request["command"])
        with patch.object(p.processes, "stream", return_value=0) as launch:
            self.assertEqual(p.release(self.repo, request), 0)
            launch.assert_called_once_with(request["command"], cwd=dcc.DM_ROOT, emit=p.processes.forward)

    def short_form(self, path: Path) -> Path:
        """The Windows 8.3 spelling of an existing path (same entity, different notation)."""
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024):
            self.skipTest("8.3 short names unavailable")
        short = Path(buffer.value)
        if str(short) == str(path.resolve()):
            self.skipTest("8.3 short names disabled on this volume")
        return short

    def released(self, request):
        with patch.object(p.processes, "stream", return_value=0) as launch:
            result = p.release(self.repo, request)
        return result, launch

    def test_update_records_one_canonical_target_everywhere(self):
        self.fake_build()
        request = p.release_snapshot(self.repo, self.target)
        canonical = self.target.resolve()
        stat = canonical.stat()
        self.assertEqual(request["target"], str(canonical))
        self.assertIn(str(canonical), request["command"])
        self.assertEqual(request["target_identity"], [stat.st_dev, stat.st_ino])
        self.assertEqual(request["destination_detail"], str(canonical))

    @unittest.skipUnless(os.name == "nt", "8.3 short paths are Windows only")
    def test_short_path_and_long_path_of_the_same_target_are_equivalent(self):
        self.fake_build()
        short = self.short_form(self.target)
        long_request = p.release_snapshot(self.repo, self.target)
        short_request = p.release_snapshot(self.repo, short)
        self.assertEqual(short_request, long_request)
        self.assertEqual(short_request["target"], str(self.target.resolve()))
        for label, request in (("short-confirmed", short_request), ("long-confirmed", long_request)):
            with self.subTest(label):
                result, launch = self.released(request)
                self.assertEqual(result, 0)
                launch.assert_called_once()
        # the confirmed request revalidates through either spelling of the target
        for spelled in (self.target, short):
            self.assertEqual(p.release_snapshot(self.repo, spelled), long_request)

    def test_a_genuinely_different_target_still_refuses_update(self):
        self.fake_build()
        request = p.release_snapshot(self.repo, self.target)
        other = self.root / "other-target"
        other.mkdir()
        with patch.object(p.processes, "stream") as launch:
            with self.assertRaises(ValueError):
                p.release(self.repo, dict(request, target=str(other)))
            launch.assert_not_called()

    def test_other_confirmed_conditions_still_refuse_update(self):
        self.fake_build()
        request = p.release_snapshot(self.repo, self.target)
        for key, value in (("entry_hash", "0" * 64), ("adapter_hash", "0" * 64), ("target_identity", [0, 0]),
                           ("command", ["other"]), ("destination_detail", "elsewhere")):
            with self.subTest(key), patch.object(p.processes, "stream") as launch:
                with self.assertRaises(ValueError):
                    p.release(self.repo, dict(request, **{key: value}))
                launch.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "junctions are Windows only")
    def test_link_targets_are_still_rejected_before_normalisation(self):
        self.fake_build()
        junction = self.root / "junction"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(self.target)], capture_output=True)
        if made.returncode != 0:
            self.skipTest("cannot create a junction")
        with self.assertRaises(ValueError):
            p.release_snapshot(self.repo, junction)

    def test_changed_artifact_script_input_or_target_refuses_update(self):
        for what in ("artifact", "script", "input", "target"):
            with self.subTest(what=what):
                self.fake_build()
                request = p.release_snapshot(self.repo, self.target)
                if what == "artifact":
                    (self.artifact / "app.exe").write_text("tampered")
                elif what == "script":
                    (self.repo / "UPDATE.cmd").write_text("changed")
                elif what == "input":
                    (self.repo / "source.py").write_text("new source")
                else:
                    self.target.rename(self.root / "old-target")
                with patch.object(p.processes, "stream") as launch:
                    with self.assertRaises((ValueError, OSError)):
                        p.release(self.repo, request)
                    launch.assert_not_called()

    def test_same_output_cannot_be_built_or_updated_twice(self):
        with p.output_lock(self.artifact):
            with self.assertRaises((ValueError, OSError)):
                with p.output_lock(self.artifact):
                    self.fail("lock acquired twice")

    def test_unregistered_release_adapter_fails_closed(self):
        with self.assertRaises(ValueError):
            p.release_command(self.root / "unknown", self.artifact, self.target)

    @unittest.skipUnless(os.name == "nt", "Windows CMD integration")
    def test_noninteractive_body_build_with_spaces_in_path(self):
        (self.repo / "source.py").write_text("dirty", encoding="utf-8")
        self.assertEqual(p.build(self.repo, self.entry, self.artifact)["status"], "ready")


class UiTests(unittest.TestCase):
    def setUp(self):
        # UI geometry and click tests must not start unrelated network workers.
        # Coordinator/selection integration has its own dedicated regression suite.
        for target, name in ((dcc.App, "scan_remote_repos"), (dcc.App, "check_self_update"), (dcc.SelectionState, "_fire")):
            mocked = patch.object(target, name)
            mocked.start()
            self.addCleanup(mocked.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        dcc.ACTIVE_OPERATIONS.clear()
        self.ui = dcc.App(self.root)
        self.root.geometry("1080x720")
        self.root.update()
        self.addCleanup(self.cleanup)

    def pump_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition())

    def cleanup(self):
        dcc.ACTIVE_OPERATIONS.clear()
        if not self.ui._closed:
            self.ui._on_close()

    def test_main_buttons_visible_at_minimum_size_and_ai_is_separate(self):
        self.assertFalse(hasattr(self.ui, "ai_panel"))
        for name in ("run_button", "build_button", "release_button", "orchestrator_button"):
            button = getattr(self.ui, name)
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty() - self.root.winfo_rooty() + button.winfo_height(), 720)
            self.assertLessEqual(button.winfo_rootx() - self.root.winfo_rootx() + button.winfo_width(), 1080)
        with patch.object(orch_view.RunMonitor, "start"), patch.object(orch_view.OrchestratorWindow, "_refresh_free_usage"):
            self.ui.open_orchestrator()
            self.root.update()
            window = self.ui.orchestrator_window
            self.assertTrue(window.exists())
            self.assertTrue(window.start_button.winfo_ismapped())
            self.assertTrue(window.stop_button.winfo_ismapped())
            self.ui.open_orchestrator()
            self.assertIs(self.ui.orchestrator_window, window)  # focused, not duplicated
            window.close()
            self.root.update()
            self.assertFalse(window.exists())
        # closing the window only closes the view; the main screen is untouched
        self.assertTrue(self.ui.run_button.winfo_ismapped())

    def test_orchestrator_never_locks_main_operations(self):
        name = self.ui.current.name
        self.assertFalse(self.ui._repo_busy())
        # a run of the same repo (or any Orchestrator state) is not a DCC operation
        self.assertNotIn("ai_orchestrator", [action for _, action in dcc.ACTIVE_OPERATIONS.values()])
        dcc.ACTIVE_OPERATIONS[999] = ("different-repo", "run")
        self.assertFalse(self.ui._repo_busy())
        dcc.ACTIVE_OPERATIONS[999] = (name, "run")
        self.assertTrue(self.ui._repo_busy())

    def test_closing_dcc_is_never_blocked_by_or_stops_an_orchestrator_run(self):
        with patch.object(dcc.messagebox, "showinfo") as info, \
             patch("tools.ai_orchestrator.runstate.force_stop") as stop, \
             patch("tools.ai_orchestrator.common.terminate_pid_tree") as kill:
            self.ui._on_close()
            info.assert_not_called()
            stop.assert_not_called()
            kill.assert_not_called()
        self.assertTrue(self.ui._closed)

    def test_running_runs_are_detected_at_startup_and_shown_on_the_button(self):
        record = {"run_id": "r1", "repo": str(Path("C:/repos") / self.ui.current.name), "stage": "testing"}
        items = [{"record": record, "liveness": "running"}]
        with patch("tools.ai_orchestrator.runstate.active_runs", return_value=items):
            self.ui._badge_stop.clear()
            self.ui._start_orchestrator_badge()
            self.pump_until(lambda: (self.ui._drain_orchestrator_badge(), self.ui.orchestrator_button_var.get())[1] != "AI Orchestrator")
        self.assertIn("実行中 1", self.ui.orchestrator_button_var.get())
        self.assertIn("実行中のrunを検出", self.ui.log.get("1.0", "end"))

    def test_run_rechecks_dirty_repo_and_uses_existing_entrypoint_without_candidate(self):
        definition = self.ui.current
        state = RepoState(True, True, branch="feature/work", head="a" * 40,
                          origin_repo=definition.full_name, tracked_dirty=True)
        entry = MagicMock(ready=True, path=Path("RUN_DEV.cmd"))
        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints", return_value=MagicMock(run=entry)), \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui.candidate_var.set("")
            self.ui.launch("run")
            self.pump_until(lambda: launch.called)
            launch.assert_called_once()
            self.assertIn("scripts.dev_control_center.entrypoints", launch.call_args.args[0])
            self.assertEqual(launch.call_args.args[1:], (definition.name, "run"))

    def test_update_requires_confirmation_and_cancellation_never_spawns(self):
        definition = self.ui.current
        state = RepoState(True, True, head="a" * 40, origin_repo=definition.full_name, tracked_dirty=True)
        record = {"build_id": "id", "base_head": "a" * 40, "dirty": True,
                  "artifact": "artifact", "artifact_hash": "hash"}
        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints", return_value=MagicMock()), \
             patch.object(p, "read_receipt", return_value=record), \
             patch.object(p, "release_snapshot", return_value={"receipt": record, "target": "target"}), \
             patch.object(dcc.filedialog, "askdirectory", return_value="target"), \
             patch.object(dcc.messagebox, "askyesno", return_value=False) as ask, \
             patch.object(dcc.subprocess, "Popen") as launch:
            self.ui.launch("release")
            deadline = time.monotonic() + 3
            while not ask.called and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            ask.assert_called_once()
            launch.assert_not_called()

    def test_dirty_build_without_candidate_launches_existing_build_through_recorder(self):
        definition = self.ui.current
        state = RepoState(True, True, branch="feature/work", head="a" * 40,
                          origin_repo=definition.full_name, tracked_dirty=True)
        entry = MagicMock(ready=True, path=Path("BUILD.cmd"))
        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints", return_value=MagicMock(build=entry)), \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui.candidate_var.set("")
            self.ui.launch("build")
            self.pump_until(lambda: launch.called)
            launch.assert_called_once()
            command = launch.call_args.args[0]
            self.assertIn("scripts.dev_control_center.provenance", command)
            self.assertEqual(command[command.index("--entry") + 1], str(entry.path))
            self.assertNotIn("--candidate", command)


if __name__ == "__main__":
    unittest.main()
