"""DCC window integration of the common UPDATE engine: dry-run first, the plan shown, execute only on a yes."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from scripts.dev_control_center import app as dcc
from scripts.dev_control_center.core import RepoState


def plan_body(**extra) -> dict:
    body = {"plan_id": "ab" * 32, "target": "\\\\server\\share\\App", "stop_reasons": [], "deletions": [],
            "acknowledge_orphans": False, "in_use_now": [], "estimated_execute_seconds": 12.5,
            "provenance": {"base_head": "c" * 40, "build_id": "d" * 32, "route": "working-tree"},
            "production": {"live_commit": "a" * 40, "manifest_trusted": False,
                           "trust_reasons": ["no DCC release manifest in the target yet"]},
            "summary": {"managed": 1134, "unchanged": 1088, "modified": 44, "new": 2, "drift_repaired": 0,
                        "deletion_candidates": 0, "retained": 3, "protected_live": 120, "backup_files": 44,
                        "backup_bytes": 16_500_000, "copied_bytes": 16_600_000}}
    body.update(extra)
    return body


class UiCase(unittest.TestCase):
    def setUp(self):
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
        self.root.update()
        self.addCleanup(self.cleanup)
        engine = patch.object(dcc.release_update, "engine_repo", return_value=True)
        engine.start()
        self.addCleanup(engine.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.plan_path = Path(tmp.name) / "plan.json"

    def cleanup(self):
        dcc.ACTIVE_OPERATIONS.clear()
        if not self.ui._closed:
            self.ui._on_close()

    def pump_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition())

    def write_plan(self, **extra) -> dict:
        body = plan_body(**extra)
        self.plan_path.write_text(json.dumps(body), encoding="utf-8")
        return body


class EngineUpdateUiTests(UiCase):
    def test_update_button_starts_only_the_read_only_dry_run(self):
        definition = self.ui.current
        state = RepoState(True, True, head="a" * 40, origin_repo=definition.full_name)
        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints",
                   return_value=MagicMock(release=MagicMock(ready=False, path=None))), \
             patch.object(dcc.filedialog, "askdirectory", return_value="C:/share") as ask, \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as launch, \
             patch.object(dcc.subprocess, "Popen") as popen:
            self.ui.launch("release")
            self.pump_until(lambda: launch.called)
        command, name, action = launch.call_args.args
        self.assertEqual((name, action), (definition.name, "update-dry-run"))
        self.assertIn("scripts.dev_control_center.release_update", command)
        self.assertEqual(command[command.index("scripts.dev_control_center.release_update") + 1], "plan")
        self.assertNotIn("execute", command)
        self.assertEqual(command[command.index("--target") + 1], str(Path("C:/share")))
        self.assertIn(definition.name, self.ui.lifecycle_after)      # the plan is shown when the dry-run ends
        ask.assert_called_once()
        popen.assert_not_called()

    def test_plan_is_shown_and_only_a_yes_executes_exactly_that_plan(self):
        body = self.write_plan()
        definition = self.ui.current
        with patch.object(dcc.messagebox, "askyesno", return_value=False) as ask, \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui._confirm_engine_plan(Path("repo"), definition, Path("t"), self.plan_path, 0)
        launch.assert_not_called()
        text = ask.call_args.args[1]
        for fragment in ("aaaaaaaaaaaa → 新BUILD: cccccccccccc", "変更なし 1088 / 更新 44 / 新規 2",
                         "44 files / 16,500,000 bytes（変更分のみ）", "未信頼", "plan: abababababab"):
            self.assertIn(fragment, text)
        with patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui._confirm_engine_plan(Path("repo"), definition, Path("t"), self.plan_path, 0)
        command, name, action = launch.call_args.args
        self.assertEqual(action, "release")
        self.assertEqual(command[command.index("scripts.dev_control_center.release_update") + 1], "execute")
        self.assertEqual(command[command.index("--plan") + 1], str(self.plan_path))
        self.assertTrue(body["plan_id"].startswith(command[command.index("--confirm") + 1]))

    def test_stop_reasons_are_shown_and_nothing_is_executed(self):
        self.write_plan(stop_reasons=["PATH_COLLISION _internal/x.dat: a folder is where the build has a file"])
        with patch.object(dcc.messagebox, "showwarning") as warn, \
             patch.object(dcc.messagebox, "askyesno") as ask, \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui._confirm_engine_plan(Path("repo"), self.ui.current, Path("t"), self.plan_path, 2)
        self.assertIn("PATH_COLLISION", warn.call_args.args[1])
        ask.assert_not_called()
        launch.assert_not_called()

    def test_deletion_candidates_can_only_be_left_in_place_with_a_new_dry_run(self):
        self.write_plan(stop_reasons=["DELETION_CANDIDATES ... _internal/old.dat"],
                        deletions=[{"path": "_internal/old.dat", "size": 3, "sha256": "0" * 64}])
        with patch.object(dcc.messagebox, "askyesno", return_value=True) as ask, \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as launch:
            self.ui._confirm_engine_plan(Path("repo"), self.ui.current, Path("t"), self.plan_path, 2)
        self.assertIn("_internal/old.dat", ask.call_args.args[1])
        self.assertIn("削除しません", ask.call_args.args[1])
        command, _, action = launch.call_args.args
        self.assertEqual(action, "update-dry-run")                    # never straight to execute
        self.assertIn("--acknowledge-orphans", command)

    def test_a_running_engine_update_can_not_be_stopped_from_the_window(self):
        name = self.ui.current.name
        token = object()
        self.ui.lifecycle_jobs[name] = token
        cancel = MagicMock()
        self.ui.lifecycle_cancellations[name] = cancel
        dcc.ACTIVE_OPERATIONS[id(token)] = (name, "release")
        with patch.object(dcc.messagebox, "showinfo") as info, patch.object(dcc.messagebox, "askyesno") as ask:
            self.ui.stop_lifecycle()
        info.assert_called_once()
        ask.assert_not_called()
        cancel.set.assert_not_called()

    def test_the_dry_run_callback_runs_after_the_worker_finished(self):
        name = self.ui.current.name
        seen = []
        token = object()
        self.ui.lifecycle_jobs[name] = token
        self.ui.lifecycle_after[name] = seen.append
        self.ui.lifecycle_events.put(("finished", token, name, "update-dry-run", 0))
        self.pump_until(lambda: seen == [0])
        self.assertNotIn(name, self.ui.lifecycle_after)


class RevertUiTests(UiCase):
    def revert_body(self) -> dict:
        body = {"plan_id": "cd" * 32, "target": "\\\\server\\share\\App", "release_commit": "c" * 40,
                "previous_commit": "a" * 40, "previous_version": "v1.4.0", "in_use_now": [],
                "summary": {"restore": 44, "remove": 2, "protected_live": 4061}}
        self.plan_path.write_text(json.dumps(body), encoding="utf-8")
        return body

    def test_the_revert_button_is_only_enabled_for_a_live_engine_release(self):
        with patch.object(self.ui, "_engine_release_live", return_value=False):
            self.ui._set_button_states()
            self.assertIn("disabled", self.ui.revert_button.state())
        with patch.object(self.ui, "_engine_release_live", return_value=True):
            self.ui._set_button_states()
            self.assertNotIn("disabled", self.ui.revert_button.state())

    def test_revert_starts_with_a_dry_run_and_executes_only_that_plan_on_yes(self):
        definition = self.ui.current
        with patch.object(self.ui, "_engine_release_live", return_value=True), \
             patch.object(dcc.filedialog, "askdirectory", return_value="C:/share"), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as launch:
            self.ui.revert_release()
        command, name, action = launch.call_args.args
        self.assertEqual(action, "revert-dry-run")
        self.assertEqual(command[command.index("scripts.dev_control_center.release_update") + 1], "revert-plan")
        self.assertIn(definition.name, self.ui.lifecycle_after)
        body = self.revert_body()
        with patch.object(dcc.messagebox, "askyesno", return_value=False) as ask, \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui._confirm_revert_plan(definition, self.plan_path, 0)
        launch.assert_not_called()
        for fragment in ("cccccccccccc を戻し", "aaaaaaaaaaaa v1.4.0", "戻す: 44", "削除: 2", "失効"):
            self.assertIn(fragment, ask.call_args.args[1])
        with patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle") as launch:
            self.ui._confirm_revert_plan(definition, self.plan_path, 0)
        command, _, action = launch.call_args.args
        self.assertEqual(action, "revert")
        self.assertTrue(body["plan_id"].startswith(command[command.index("--confirm") + 1]))

    def test_a_running_revert_can_not_be_stopped_from_the_window(self):
        name = self.ui.current.name
        token = object()
        self.ui.lifecycle_jobs[name] = token
        cancel = MagicMock()
        self.ui.lifecycle_cancellations[name] = cancel
        dcc.ACTIVE_OPERATIONS[id(token)] = (name, "revert")
        with patch.object(dcc.messagebox, "showinfo") as info:
            self.ui.stop_lifecycle()
        info.assert_called_once()
        cancel.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
