"""DCC BUILD success judgement: the real (non-interactive) body, its return code, a freshly built artifact
stamped with the built SHA, and the candidate same-SHA gate. Real Git and real worker subprocesses."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts.dev_control_center import candidate as cf
from scripts.dev_control_center import entrypoints, provenance as p

# The body the manual BUILD.cmd would call. BODY_MODE (an explicit env switch set by the tests) picks a
# behaviour; the artifact gets BUILD_INFO.txt with the commit it was built from, like next-day-setup.
BODY = r'''
import os, pathlib, subprocess, sys
mode = os.environ.get("BODY_MODE", "ok")
root = pathlib.Path.cwd()
if mode == "pause" and os.name == "nt":
    subprocess.run(["cmd.exe", "/d", "/c", "pause"])  # must not wait: DCC gives the build no console input
if mode == "input":
    try:
        input("press enter")
    except EOFError:
        print("no console input: EOF")
if mode == "noop":
    sys.exit(0)                                       # "success" without building anything
if mode == "fail_early":
    sys.exit(3)                                       # e.g. PyInstaller failed before COLLECT
if mode == "change_input":
    (root / "source.py").write_text("changed during build", encoding="utf-8")
if mode == "commit":
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "moved"], check=True)
dist = root / "dist" / "App"
dist.mkdir(parents=True, exist_ok=True)
(dist / "App.exe").write_bytes(os.urandom(64))
sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
if mode == "wrong_sha":
    sha = "0" * 40
if mode != "no_info":
    tree = "clean" if not subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout else "DIRTY"
    (dist / "BUILD_INFO.txt").write_text(f"Git commit SHA: {sha}\nGit working tree: {tree}\n", encoding="utf-8")
if mode == "post_fail":
    sys.exit(4)                                       # artifact written, then an auxiliary step failed
print("DONE")
'''
INFO = {"file": "BUILD_INFO.txt", "sha_key": "Git commit SHA", "tree_key": "Git working tree"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class BuildCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dcc build ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "app"
        self.repo.mkdir()
        self.artifact = self.repo / "dist" / "App"
        self.entry = self.repo / "BUILD.cmd"
        # the manual launcher: its pause (and this marker) must never be reached by a DCC BUILD
        self.entry.write_text("@echo off\necho cmd>cmd_ran.txt\npython build.py\npause\n", encoding="ascii")
        (self.repo / "build.py").write_text(BODY, encoding="utf-8")
        (self.repo / "source.py").write_text("first", encoding="utf-8")
        (self.repo / ".gitignore").write_text("dist/\ncmd_ran.txt\n", encoding="ascii")
        (self.repo / "dcc_entrypoints.json").write_text(json.dumps(
            {"schema": 1, "build": {"script": "build.py", "build_info": INFO}}), encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        git(self.repo, "add", ".")
        git(self.repo, "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-qm", "fixture")
        self.head = git(self.repo, "rev-parse", "HEAD")
        scope = mock.patch.object(p, "state_root", return_value=self.root / "state")
        scope.start()
        self.addCleanup(scope.stop)

    def build(self, mode="ok", **kwargs):
        with mock.patch.dict(os.environ, {"BODY_MODE": mode}), mock.patch.object(p.processes, "forward", lambda t: None):
            return p.build(self.repo, self.entry, self.artifact, **kwargs)


class NonInteractiveTests(BuildCase):
    def test_pause_and_console_input_never_block_and_the_cmd_is_not_run(self):
        for mode in ("pause", "input"):
            with self.subTest(mode=mode):
                started = time.monotonic()
                record = self.build(mode)
                self.assertLess(time.monotonic() - started, 60)
                self.assertEqual((record["status"], record["returncode"]), ("ready", 0), record.get("reject_reasons"))
        self.assertFalse((self.repo / "cmd_ran.txt").exists())

    def test_next_day_setup_builds_through_build_exe_py_not_the_cmd(self):
        spec = entrypoints.build_specs()["next-day-setup"]
        self.assertEqual(spec["script"], "build_exe.py")
        self.assertEqual(spec["build_info"]["file"], "BUILD_INFO.txt")
        self.assertNotIn("build_exe_entry", json.dumps(spec))
        source = Path(__file__).resolve().parents[2] / "next-day-setup"
        if not (source / "build_exe.py").is_file():
            self.skipTest("next-day-setup checkout not present")
        command, cwd = entrypoints.plan_build(source)
        self.assertEqual(Path(command[-1]).name, "build_exe.py")
        self.assertEqual(Path(command[0]), source / ".venv" / "Scripts" / "python.exe")
        self.assertNotIn(".cmd", " ".join(command).lower())

    def test_missing_build_body_stops_before_start(self):
        with mock.patch.object(entrypoints, "build_specs", return_value={"app": {"script": "missing.py"}}):
            with self.assertRaises(ValueError) as ctx:
                entrypoints.plan_build(self.repo)
        self.assertIn("BUILD本体がありません", str(ctx.exception))


class SuccessJudgementTests(BuildCase):
    def test_successful_build_is_ready_refreshed_and_stamped_with_the_sha(self):
        record = self.build()
        self.assertEqual(record["status"], "ready", record.get("reject_reasons"))
        self.assertEqual(record["returncode"], 0)
        self.assertTrue(record["artifact_refreshed"] and record["inputs_stable"] and record["head_unchanged"])
        self.assertEqual(record["build_info_sha"], self.head)
        self.assertEqual(record["artifact_hash"], p.tree_hash(self.artifact))
        self.assertEqual(record["reject_reasons"], [])
        self.assertEqual(p.read_receipt(self.repo)["build_id"], record["build_id"])

    def test_failures_keep_their_nonzero_code_and_are_rejected(self):
        for mode, code in (("fail_early", 3), ("post_fail", 4)):
            with self.subTest(mode=mode):
                record = self.build(mode)
                self.assertEqual((record["status"], record["returncode"]), ("rejected", code))
                self.assertIn(f"returncode {code}", record["reject_reasons"])
                with self.assertRaises(ValueError):
                    p.read_receipt(self.repo)

    def test_old_artifact_left_behind_is_not_a_refresh(self):
        self.assertEqual(self.build()["status"], "ready")
        record = self.build("noop")                        # rc 0, but nothing was built
        self.assertFalse(record["artifact_refreshed"])
        self.assertEqual(record["status"], "rejected")
        record = self.build("fail_early")                  # a failed build leaves the old artifact
        self.assertFalse(record["artifact_refreshed"])

    def test_refresh_requires_files_written_by_this_build(self):
        self.build()
        before = p.artifact_stamp(self.artifact)
        (self.artifact / "App.exe").unlink()              # only removing parts is not a new artifact
        later = time.time_ns() + 10 * 1_000_000_000         # a build that started after these files were written
        self.assertFalse(p.artifact_refreshed(self.artifact, before, later, "BUILD_INFO.txt"))
        self.assertFalse(p.artifact_refreshed(self.artifact, before, later))
        (self.artifact / "BUILD_INFO.txt").write_text("rewritten", encoding="utf-8")
        self.assertTrue(p.artifact_refreshed(self.artifact, before, time.time_ns(), "BUILD_INFO.txt"))

    def test_build_info_must_name_the_built_sha(self):
        for mode in ("wrong_sha", "no_info"):
            with self.subTest(mode=mode):
                record = self.build(mode)
                self.assertEqual(record["status"], "rejected")
                self.assertTrue(any("BUILD_INFO.txt" in reason for reason in record["reject_reasons"]))

    def test_head_moving_during_the_build_is_rejected(self):
        record = self.build("commit")
        self.assertFalse(record["head_unchanged"])
        self.assertEqual(record["status"], "rejected")
        self.assertTrue(any("HEADが変化" in reason for reason in record["reject_reasons"]))

    def test_input_change_during_the_build_is_rejected(self):
        record = self.build("change_input")
        self.assertFalse(record["inputs_stable"])
        self.assertEqual(record["status"], "rejected")


class CandidateBuildTests(BuildCase):
    def gate(self, sha):
        return mock.patch.object(cf, "build_gate", return_value=SimpleNamespace(sha=sha))

    def test_candidate_build_rechecks_the_gate_and_binds_every_sha(self):
        with self.gate(self.head) as gate:
            record = self.build(expected_sha=self.head, candidate_run_id="r1", expected_branch="main")
        gate.assert_called_once_with(self.repo, "main")
        self.assertEqual(record["status"], "ready", record.get("reject_reasons"))
        self.assertEqual((record["candidate_sha"], record["base_head"], record["build_info_sha"]), (self.head,) * 3)

    def test_candidate_sha_mismatch_is_refused_before_building(self):
        self.assertEqual(self.build()["status"], "ready")
        previous = p.receipt_path(self.repo).read_text(encoding="utf-8")
        for gate_sha in ("f" * 40, None):
            with self.subTest(gate=gate_sha):
                patcher = self.gate(gate_sha) if gate_sha else mock.patch.object(cf, "build_gate", return_value=None)
                with patcher, self.assertRaises(ValueError):
                    self.build(expected_sha=self.head, expected_branch="main")
        self.assertEqual(p.receipt_path(self.repo).read_text(encoding="utf-8"), previous)  # nothing overwritten

    def test_update_refuses_an_artifact_whose_build_info_differs(self):
        good = {"candidate_sha": self.head, "base_head": self.head, "dirty": False,
                "build_info_file": "BUILD_INFO.txt", "build_info_sha": self.head}
        with mock.patch.object(p, "git", side_effect=lambda repo, *a: (f"{self.head}\trefs/heads/main" if a[0] == "ls-remote"
                                                                       else self.head)):
            p._require_candidate_artifact(self.repo, good, self.head, "main")
            with self.assertRaises(ValueError):
                p._require_candidate_artifact(self.repo, {**good, "build_info_sha": "0" * 40}, self.head, "main")


if __name__ == "__main__":
    unittest.main()
