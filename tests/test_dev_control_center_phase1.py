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

from scripts.dev_control_center import app as dcc, provenance as p
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
        self.assertIn(str(self.target), request["command"])
        with patch.object(p.processes, "stream", return_value=0) as launch:
            self.assertEqual(p.release(self.repo, request), 0)
            launch.assert_called_once_with(request["command"], cwd=dcc.DM_ROOT, emit=p.processes.forward)

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
        self.ui._on_close()

    def test_main_buttons_visible_at_minimum_size_and_ai_is_separate(self):
        self.assertFalse(self.ui.ai_panel.winfo_ismapped())
        for name in ("run_button", "build_button", "release_button", "orchestrator_button"):
            button = getattr(self.ui, name)
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty() - self.root.winfo_rooty() + button.winfo_height(), 720)
            self.assertLessEqual(button.winfo_rootx() - self.root.winfo_rootx() + button.winfo_width(), 1080)
        self.ui.open_orchestrator()
        self.root.update()
        child = self.ui.orchestrator_app
        self.assertTrue(child.ai_panel.winfo_ismapped())
        child._on_close()
        self.assertEqual(child.master.state(), "withdrawn")
        self.assertTrue(self.ui.run_button.winfo_ismapped())
        self.ui.open_orchestrator()
        self.assertIs(self.ui.orchestrator_app, child)

    def test_other_repo_ai_does_not_lock_main_and_same_repo_does(self):
        name = self.ui.current.name
        dcc.ACTIVE_OPERATIONS[999] = ("different-repo", "ai_orchestrator")
        self.assertFalse(self.ui._repo_busy())
        dcc.ACTIVE_OPERATIONS[999] = (name, "ai_orchestrator")
        self.assertTrue(self.ui._repo_busy())
        # review_pending and provider errors end the process and release the lock.
        dcc.ACTIVE_OPERATIONS.clear()
        self.assertFalse(self.ui._repo_busy())

    def test_pending_and_provider_failure_release_lock_without_modal_error(self):
        for status, rc in (("review_pending", 0), ("stopped", 1)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                result = Path(temp) / "result.json"
                result.write_text(json.dumps({"status": status, "error": "quota", "run_dir": temp}), encoding="utf-8")
                process = MagicMock()
                process.poll.return_value = rc
                name = self.ui.current.name
                self.ui.ai_context = {"result_path": result}
                self.ui._begin_process(process, name, "ai_orchestrator")
                with patch.object(dcc.messagebox, "showerror") as error, \
                     patch.object(self.ui, "_reload_after"), patch.object(self.ui, "_refresh_review_plan"):
                    self.ui._poll()
                    error.assert_not_called()
                self.assertFalse(self.ui._repo_busy())
                self.assertNotIn(id(self.ui), dcc.ACTIVE_OPERATIONS)

    def test_close_never_implicitly_stops_ai(self):
        dcc.ACTIVE_OPERATIONS[999] = (self.ui.current.name, "ai_orchestrator")
        with patch.object(dcc.messagebox, "showinfo"), patch.object(dcc, "_terminate_ai_process_tree") as stop:
            self.ui._on_close()
            stop.assert_not_called()
            self.assertTrue(self.root.winfo_exists())

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
