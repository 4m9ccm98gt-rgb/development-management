"""Cancellation, scan parity, GitHub fetch parity and timing-helper tests (core layer)."""

from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scripts.dev_control_center import core
from scripts.dev_control_center.core import (
    SKIP_DIR_NAMES,
    SCRIPT_SUFFIXES,
    Cancelled,
    RepoDefinition,
    discover_entrypoints,
    fetch_github_state,
    inspect_repo,
)
from scripts.dev_control_center.loader import Coordinator
from scripts.dev_control_center.timing import HeartbeatMonitor, Timing

DEF = RepoDefinition("demo", "desktop", "main", owner="o")
SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


class SubprocessCancelTests(unittest.TestCase):
    def test_cancel_terminates_child_well_under_timeout(self):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(Cancelled):
            core._run_process(SLEEPER, timeout=25, cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)

    def test_timeout_with_cancel_event_raises_runtime_error(self):
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            core._run_process(SLEEPER, timeout=1, cancel=threading.Event())
        self.assertLess(time.monotonic() - started, 6)

    def test_cancel_none_behaves_as_before_and_cancel_event_matches(self):
        args = [sys.executable, "-c", "print('hi')"]
        plain = core._run_process(args)
        polled = core._run_process(args, cancel=threading.Event())
        self.assertEqual((plain.returncode, plain.stdout.strip()),
                         (polled.returncode, polled.stdout.strip()))

    def test_close_kills_registered_children(self):
        holder = {}

        def run():
            try:
                core._run_process(SLEEPER, timeout=25, cancel=threading.Event())
            except Exception as exc:  # noqa: BLE001
                holder["exc"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 5
        while not core._CHILDREN and time.monotonic() < deadline:
            time.sleep(0.01)
        core.kill_registered_children()
        thread.join(10)
        self.assertFalse(thread.is_alive())

    def test_inspect_repo_git_timeout_is_a_stop_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            with patch.object(core.subprocess, "run",
                              side_effect=subprocess.TimeoutExpired("git", 15)):
                state = inspect_repo(root, DEF)
        self.assertIn("timed out", state.error)
        self.assertFalse(state.safe_for_lifecycle(DEF))

    def test_inspect_repo_with_cancel_matches_plain_on_real_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            self.assertEqual(inspect_repo(root, DEF), inspect_repo(root, DEF, threading.Event()))


def _old_iter_scripts(repo_root: Path, max_depth: int = 3) -> list[Path]:
    """The pre-change non-Git behaviour: full rglob, then post-filter."""
    found = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCRIPT_SUFFIXES:
            continue
        rel = path.relative_to(repo_root)
        if len(rel.parts) - 1 > max_depth:
            continue
        if any(part in SKIP_DIR_NAMES for part in rel.parts):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.relative_to(repo_root).as_posix().lower())


class ScanTests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        for rel in (
            "RUN_DEV.cmd", "notes.txt", "a/x.bat", "a/b/c/ok.cmd", "a/b/c/d/too_deep.cmd",
            "node_modules/pkg/skip.cmd", "build/skip2.cmd", "a/.git/hook.cmd", "z/dist/y.cmd",
            "z/keep.CMD", "a/b/c/d/e/deeper.cmd",
        ):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")

    def test_walk_matches_old_rglob_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            self.assertEqual(core._iter_scripts(root), _old_iter_scripts(root))
            self.assertEqual(core._iter_scripts(root, cancel=threading.Event()),
                             _old_iter_scripts(root))
            names = {p.name for p in core._iter_scripts(root)}
            self.assertEqual(names, {"RUN_DEV.cmd", "x.bat", "ok.cmd", "keep.CMD"})

    def test_pruned_walk_does_not_enter_skipped_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            visited = [p.parent for p in core._filesystem_scripts(root)]
            self.assertFalse(any("node_modules" in v.parts for v in visited))

    def test_scan_cancel_returns_promptly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(300):
                (root / f"d{i}").mkdir()
                (root / f"d{i}" / "f.txt").write_text("x", encoding="utf-8")
            cancel = threading.Event()
            cancel.set()
            started = time.monotonic()
            with self.assertRaises(Cancelled):
                discover_entrypoints(root, "desktop", cancel=cancel)
            self.assertLess(time.monotonic() - started, 2)

    def test_discover_entrypoints_unchanged_without_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "RUN_DEV.cmd").write_text("x", encoding="utf-8")
            self.assertTrue(discover_entrypoints(root, "desktop").run.ready)


BRANCH_OK = {"commit": {"sha": "a" * 40}}


class FakeRunner:
    def __init__(self, table):
        self.table = table
        self.calls: list[str] = []

    def __call__(self, args, cancel=None):
        joined = " ".join(args)
        for marker, outcome in (
            ("/branches/", self.table.get("branch", BRANCH_OK)),
            ("pr list", self.table.get("pr", [])),
            ("check-runs", self.table.get("checks", {"check_runs": []})),
            ("/status", self.table.get("status", {"total_count": 0, "state": "success"})),
        ):
            if marker in joined:
                self.calls.append(marker)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(joined)


PR = [{"number": 7, "title": "t", "headRefName": "f", "headRefOid": "b" * 40,
       "baseRefName": "main", "isDraft": False, "url": "u"}]


class FetchParityTests(unittest.TestCase):
    def fetch(self, **table):
        runner = FakeRunner(table)
        return fetch_github_state(DEF, runner=runner), runner

    def test_no_pr_uses_branch_sha(self):
        state, runner = self.fetch()
        self.assertEqual((state.branch_sha, state.ci_sha, state.ci_target), ("a" * 40, "a" * 40, "main"))
        self.assertFalse(state.candidate_blocked_by_pr)
        self.assertEqual(runner.calls, ["/branches/", "pr list", "check-runs", "/status"])

    def test_pr_present_targets_pr_head_and_blocks_nothing_else(self):
        state, runner = self.fetch(pr=PR)
        self.assertEqual((state.ci_sha, state.ci_target), ("b" * 40, "PR #7"))
        self.assertTrue(state.candidate_blocked_by_pr)
        self.assertLess(runner.calls.index("pr list"), runner.calls.index("check-runs"))

    def test_pr_failure_means_no_pr(self):
        state, _ = self.fetch(pr=RuntimeError("boom"))
        self.assertIsNone(state.latest_pr)
        self.assertEqual(state.ci_sha, "a" * 40)

    def test_branch_failure_or_bad_sha_is_error(self):
        self.assertTrue(self.fetch(branch=RuntimeError("nope"))[0].error)
        self.assertTrue(self.fetch(branch={"commit": {"sha": "zz"}})[0].error)
        self.assertTrue(self.fetch(branch=[1])[0].error)

    def test_ci_failures_are_unavailable(self):
        for table in ({"checks": RuntimeError("x")}, {"status": RuntimeError("y")},
                      {"checks": RuntimeError("x"), "status": RuntimeError("y")}):
            state, _ = self.fetch(**table)
            self.assertEqual(state.ci_state, "UNAVAILABLE")
            self.assertEqual(state.branch_sha, "a" * 40)

    def test_malformed_payloads_do_not_crash(self):
        state, _ = self.fetch(checks="junk", status=None, pr={"x": 1})
        self.assertEqual(state.ci_state, "NO CHECKS")

    def test_cancel_propagates_instead_of_becoming_a_github_error(self):
        with self.assertRaises(Cancelled):
            self.fetch(branch=Cancelled())
        with self.assertRaises(Cancelled):
            self.fetch(checks=Cancelled())


class TimingTests(unittest.TestCase):
    def test_silent_when_disabled(self):
        lines = []
        timing = Timing(enabled=False, sink=lines.append)
        with timing.span("x"):
            pass
        timing.event("e", a=1)
        timing.record("y", 1.0)
        self.assertEqual(lines, [])
        self.assertEqual(timing.summary(), {})

    def test_records_spans_events_and_marks_when_enabled(self):
        ticks = iter([0.0, 0.25, 1.0, 1.5])
        lines = []
        timing = Timing(enabled=True, sink=lines.append, clock=lambda: next(ticks))
        with timing.span("gh:api"):
            pass
        timing.mark("m")
        self.assertEqual(timing.since_mark("m", record_as="shown"), 0.5)
        timing.event("repo-scope-cancel", repo="A", pending=1, running=2)
        self.assertAlmostEqual(timing.summary()["gh:api"]["max_ms"], 250.0)
        self.assertTrue(any("repo-scope-cancel" in line and "running=2" in line for line in lines))

    def test_heartbeat_lag_statistics_with_fake_clock(self):
        monitor = HeartbeatMonitor(0.05)
        for now in (0.0, 0.05, 0.10, 0.30, 0.35):
            monitor.beat(now)
        stats = monitor.stats()
        self.assertAlmostEqual(stats["max"], 0.15)
        self.assertEqual(stats["beats"], 4.0)

    def test_heartbeat_stays_responsive_while_a_worker_is_blocked(self):
        """Proxy check only (not a claim about the user's machine)."""
        coordinator = Coordinator()
        gate = threading.Event()
        coordinator.submit(("A", "local"), lambda cancel: gate.wait(5), pool="LOCAL", epoch=1)
        monitor = HeartbeatMonitor(0.02)
        end = time.perf_counter() + 0.5
        try:
            while time.perf_counter() < end:
                monitor.beat(time.perf_counter())
                time.sleep(0.02)
        finally:
            gate.set()
            coordinator.close()
        self.assertLess(monitor.stats()["max"], 0.25)


if __name__ == "__main__":
    unittest.main()
