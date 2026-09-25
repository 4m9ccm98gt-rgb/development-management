"""Real hidden subprocess / Tk integration; no production builds or deploys."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from scripts.dev_control_center import app, entrypoints, processes, provenance


class TransportTests(unittest.TestCase):
    def test_stdout_stderr_partial_utf8_and_exit_code_arrive_before_exit(self):
        received = threading.Event()
        chunks = []
        result = []

        def emit(text):
            chunks.append(text)
            if "途中" in "".join(chunks):
                received.set()

        command = [processes.console_python(), "-u", "-c",
                   "import sys,time;print('途中',end='',flush=True);time.sleep(1);print('stderr',file=sys.stderr,flush=True);sys.exit(7)"]
        thread = threading.Thread(target=lambda: result.append(processes.stream(command, cwd=Path.cwd(), emit=emit)))
        thread.start()
        self.assertTrue(received.wait(3))
        self.assertTrue(thread.is_alive(), "output was buffered until process exit")
        thread.join(5)
        self.assertEqual(result, [7])
        self.assertIn("stderr", "".join(chunks))

    @unittest.skipUnless(os.name == "nt", "Windows console assertion")
    def test_parent_and_inherited_child_have_no_console(self):
        inner = "import ctypes; print('CHILD_CONSOLE',ctypes.windll.kernel32.GetConsoleWindow(),flush=True)"
        outer = ("import subprocess,sys,ctypes;print('PARENT_CONSOLE',ctypes.windll.kernel32.GetConsoleWindow(),flush=True);"
                 "subprocess.run([sys.executable,'-u','-c'," + repr(inner) + "])")
        chunks = []
        rc = processes.stream([processes.console_python(), "-u", "-c", outer], cwd=Path.cwd(), emit=chunks.append)
        self.assertEqual(rc, 0)
        self.assertIn("PARENT_CONSOLE 0", "".join(chunks))
        self.assertIn("CHILD_CONSOLE 0", "".join(chunks))

    def test_unknown_manual_cmd_is_not_a_machine_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "unknown"
            repo.mkdir()
            (repo / "RUN_DEV.cmd").write_text("pause\n", encoding="ascii")
            self.assertFalse(entrypoints.supported(repo, "run"))
            with self.assertRaises(ValueError):
                entrypoints.run(repo)

    def test_beverage_build_preserves_clean_gate_before_tests_and_packaging(self):
        calls = []
        def check(command, cwd, env=None):
            calls.append(command)
            if "--check-clean" in command:
                raise subprocess.CalledProcessError(3, command)
        with patch.object(entrypoints, "_venv", return_value=Path("python.exe")), patch.object(entrypoints, "_check", side_effect=check):
            with self.assertRaises(subprocess.CalledProcessError):
                entrypoints.build(Path("beverage-inventory-ordering-system"))
        self.assertEqual(len(calls), 3)
        self.assertIn("--check-clean", calls[-1])

    def test_powershell_is_noninteractive(self):
        self.assertIn("-NonInteractive", processes.powershell(Path("build.ps1")))


class RealDccBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dcc background ")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.repo = self.folder / "menu-sheet-generator"
        self.repo.mkdir()
        self.manual = self.repo / "BUILD_RELEASE.cmd"
        self.manual.write_text("@echo off\necho MANUAL>invoked.txt\npause\nexit /b 19\n", encoding="ascii")
        (self.repo / "RUN_DEV.cmd").write_text("@echo off\npause\n", encoding="ascii")
        (self.repo / "dcc_entrypoints.json").write_text(json.dumps({"schema": 1, "build": {"script": "body.py"}}), encoding="utf-8")
        (self.repo / ".gitignore").write_text("publish/\n", encoding="ascii")
        (self.repo / "body.py").write_text("print('initial')", encoding="utf-8")
        provenance.git(self.folder, "init", "-q", str(self.repo))
        provenance.git(self.repo, "remote", "add", "origin", "https://github.com/4m9ccm98gt-rgb/menu-sheet-generator.git")
        provenance.git(self.repo, "add", ".")
        provenance.git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        for mocked in (patch.object(app, "REPOS_ROOT", self.folder),
                       patch.dict(os.environ, {"LOCALAPPDATA": str(self.folder / "state")}),
                       patch.object(app.App, "scan_remote_repos"), patch.object(app.App, "check_self_update"),
                       patch.object(app.SelectionState, "_fire"), patch.object(app.App, "_reload_after")):
            mocked.start(); self.addCleanup(mocked.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.ui = app.App(self.root)
        self.index = next(i for i, d in enumerate(self.ui.definitions) if d.name == self.repo.name)
        self.select(self.index)
        self.root.update()
        self.addCleanup(self.cleanup)

    def select(self, index):
        self.ui.repo_list.selection_clear(0, "end")
        self.ui.repo_list.selection_set(index)
        self.ui._select_repo()

    def cleanup(self):
        for cancel in self.ui.lifecycle_cancellations.values():
            cancel.set()
        deadline = time.monotonic() + 8
        while app.ACTIVE_OPERATIONS and time.monotonic() < deadline:
            self.root.update(); time.sleep(0.01)
        self.ui._on_close()

    def pump(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.root.update(); time.sleep(0.005)
        self.assertTrue(predicate(), self.ui.log.get("1.0", "end"))

    def logs(self):
        return self.ui.log.get("1.0", "end")

    def configure_body(self, rc=0, delay=0.8):
        self.repo.joinpath("body.py").write_text(
            "import sys,time,os\nfrom pathlib import Path\n"
            "if os.name=='nt':\n import ctypes\n print('CONSOLE',ctypes.windll.kernel32.GetConsoleWindow(),flush=True)\n"
            "print('BUILD_STARTED',flush=True)\nprint('日本語 stderr',file=sys.stderr,flush=True)\n"
            f"time.sleep({delay})\np=Path('publish');p.mkdir(exist_ok=True)\n(p/'app.exe').write_text('artifact')\nsys.exit({rc})\n", encoding="utf-8")

    def test_click_build_keeps_tk_responsive_streams_logs_and_bypasses_pause(self):
        self.configure_body()
        original = self.manual.read_bytes()
        ticks = []
        def tick():
            ticks.append(time.monotonic())
            self.root.after(20, tick)
        tick()
        before = time.monotonic()
        self.ui.launch("build")
        self.assertLess(time.monotonic() - before, 0.2)
        self.pump(lambda: "BUILD_STARTED" in self.logs())
        self.assertIn(self.repo.name, self.ui.lifecycle_jobs)
        self.assertIn("日本語 stderr", self.logs())
        if os.name == "nt":
            self.assertIn("CONSOLE 0", self.logs())
        self.assertTrue(self.ui._repo_busy())
        self.select(next(i for i, d in enumerate(self.ui.definitions) if d.name == "next-day-setup"))
        self.assertFalse(self.ui._repo_busy())
        self.root.geometry("1080x720+25+25")
        self.ui._start_lifecycle([processes.console_python(), "-u", "-c", "print('OTHER_REPO')"], "next-day-setup", "run")
        self.pump(lambda: not app.ACTIVE_OPERATIONS)
        self.assertIn("BUILD 成功 rc=0", self.logs())
        self.assertIn("OTHER_REPO", self.logs())
        self.assertGreater(len(ticks), 20)
        self.assertEqual(original, self.manual.read_bytes())
        self.assertFalse((self.repo / "invoked.txt").exists())
        self.assertEqual(provenance.read_receipt(self.repo)["status"], "ready")

    def test_failed_build_reports_nonzero_rc_and_is_not_deployable(self):
        self.configure_body(rc=7, delay=0.1)
        self.ui.launch("build")
        self.pump(lambda: "BUILD 失敗 rc=7" in self.logs())
        self.assertFalse(app.ACTIVE_OPERATIONS)
        with self.assertRaises(ValueError):
            provenance.read_receipt(self.repo)

    def test_explicit_stop_terminates_hidden_build_tree(self):
        self.configure_body(delay=30)
        self.ui.launch("build")
        self.pump(lambda: "BUILD_STARTED" in self.logs())
        with patch.object(app.messagebox, "askyesno", return_value=True):
            self.ui.stop_lifecycle()
        self.pump(lambda: not app.ACTIVE_OPERATIONS)
        self.assertIn("BUILD 停止 rc=", self.logs())
        with self.assertRaises(ValueError):
            provenance.read_receipt(self.repo)


if __name__ == "__main__":
    unittest.main()
