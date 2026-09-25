"""Real detached worker processes, real Git, fake providers (no paid AI).

Covers: run continues after its client exits, re-attach and duplicate-start prevention,
stale / unresponsive detection, AI safe stop that kills only the run's own process tree,
and per-repo isolation of a stuck run.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

from tools.ai_orchestrator import orchestrator as orch
from tools.ai_orchestrator import providers
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import (
    pid_matches, process_start_token, read_json, write_json_atomic,
)

import ai_orchestrator_fake_providers as fakes

ROOT = Path(__file__).resolve().parents[1]
TEST_CMD = 'python -c "import pathlib, sys; sys.exit(0 if pathlib.Path(\'feature.txt\').exists() else 1)"'


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class LifecycleCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = {
            "AI_ORCHESTRATOR_STATE_ROOT": str(self.tmp / "state"),
            "AI_ORCHESTRATOR_EXTRA_PROVIDERS": str(ROOT / "tests" / "ai_orchestrator_fake_providers.py"),
            "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_USE_BEDROCK": "", "CLAUDE_CODE_USE_VERTEX": "", "CLAUDE_CODE_USE_FOUNDRY": "",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        extra = mock.patch.dict(providers.PROVIDER_CLASSES, {c.name: c for c in fakes.PROVIDERS})
        extra.start()
        self.addCleanup(extra.stop)
        self.repo = self.make_repo("app")
        self.started: list[Path] = []
        self.addCleanup(self.stop_everything)

    def make_repo(self, name: str) -> Path:
        origin = self.tmp / f"{name}-origin.git"
        repo = self.tmp / name
        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "init")
        git(repo, "push", "-u", "origin", "main")
        return repo

    def request(self, task="Create feature.txt", repo=None, **extra):
        return orch.StartRequest(repo=str(repo or self.repo), task=task, tests=[TEST_CMD],
                                 main_agent="fakemain", review_agent="fakereview", expected_branch="main", **extra)

    def start(self, task="Create feature.txt", repo=None) -> Path:
        run_dir = orch.start_run(self.request(task, repo))
        self.started.append(run_dir)
        return run_dir

    def stop_everything(self):
        for run_dir in self.started:
            try:
                info = rs.inspect_run(run_dir)
                if info["liveness"] in (rs.LIVE_RUNNING, rs.LIVE_UNRESPONSIVE, rs.LIVE_STARTING):
                    rs.force_stop(run_dir, wait=3)
            except Exception:  # noqa: BLE001 - cleanup only
                pass
        time.sleep(0.3)
        for run_dir in self.started:  # the isolated worktree lives in %TEMP%, outside the TemporaryDirectory
            try:
                shutil.rmtree(Path(read_json(run_dir / "run.json")["worktree"]).parent, ignore_errors=True)
            except Exception:  # noqa: BLE001 - cleanup only
                pass

    def wait_for(self, run_dir, predicate, timeout=60, message="condition"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = rs.inspect_run(run_dir)
            if predicate(info):
                return info
            time.sleep(0.25)
        self.fail(f"timed out waiting for {message}: {rs.inspect_run(run_dir)}")

    def wait_done(self, run_dir, timeout=90):
        return self.wait_for(run_dir, lambda i: i["liveness"] == rs.LIVE_FINISHED, timeout, "finish")


class DetachedRunTests(LifecycleCase):
    def test_full_run_by_a_detached_worker_ends_in_a_local_candidate(self):
        run_dir = self.start()
        record = self.wait_done(run_dir)["record"]
        self.assertEqual(record["stage"], rs.COMPLETED, record["final_result"])
        self.assertEqual((record["main_agent"], record["review_agent"]), ("fakemain", "fakereview"))
        self.assertEqual((record["main_calls"], record["review_calls"], record["tests_run_count"]), (1, 1, 1))
        self.assertTrue(record["candidate_branch"].startswith("ai-candidate/"))
        self.assertEqual(record["apply_status"], "ready")
        # the candidate exists in the source repo; the source branch itself was never moved
        branches = subprocess.run(["git", "-C", str(self.repo), "branch", "--list", "ai-candidate/*"],
                                  capture_output=True, text=True).stdout
        self.assertIn(record["candidate_branch"], branches)
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, record["base_sha"])
        self.assertFalse(Path(record["worktree"]).exists())
        # the repo lock is released at the end
        self.assertEqual(rs.active_runs(str(self.repo)), [])

    def test_worker_is_a_separate_process_that_outlives_the_client(self):
        script = textwrap.dedent(f"""
            import os, sys
            sys.path.insert(0, {str(ROOT)!r})
            from tools.ai_orchestrator import orchestrator as orch
            from tools.ai_orchestrator import providers
            import ai_orchestrator_fake_providers as fakes
            providers.PROVIDER_CLASSES.update({{c.name: c for c in fakes.PROVIDERS}})
            req = orch.StartRequest(repo={str(self.repo)!r}, task="Create feature.txt SLEEP", tests=[{TEST_CMD!r}],
                                    main_agent="fakemain", review_agent="fakereview", expected_branch="main")
            print(orch.start_run(req), flush=True)
            os._exit(0)   # the client (DCC stand-in) vanishes without any cleanup
        """)
        client = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "tests")}, timeout=90)
        self.assertEqual(client.returncode, 0, client.stderr)
        run_dir = Path(client.stdout.strip().splitlines()[-1])
        self.started.append(run_dir)
        info = self.wait_for(run_dir, lambda i: i["liveness"] == rs.LIVE_RUNNING, 30, "running worker")
        worker = info["record"]["worker"]
        self.assertNotEqual(worker["pid"], os.getpid())
        self.assertTrue(pid_matches(worker["pid"], worker["token"]))
        time.sleep(1.5)
        self.assertEqual(rs.inspect_run(run_dir)["liveness"], rs.LIVE_RUNNING)

    def test_restarted_client_finds_the_run_and_cannot_start_a_duplicate(self):
        run_dir = self.start("Create feature.txt SLEEP")
        self.wait_for(run_dir, lambda i: i["liveness"] == rs.LIVE_RUNNING, 30, "running")
        script = textwrap.dedent(f"""
            import json, sys
            sys.path.insert(0, {str(ROOT)!r})
            from tools.ai_orchestrator import orchestrator as orch, runstate as rs, providers
            import ai_orchestrator_fake_providers as fakes
            providers.PROVIDER_CLASSES.update({{c.name: c for c in fakes.PROVIDERS}})
            found = [(i["record"]["run_id"], i["liveness"], i["record"]["stage"], i["record"]["main_agent"],
                      i["record"]["tests_run_count"], i["record"]["tests_fail_count"]) for i in rs.active_runs({str(self.repo)!r})]
            req = orch.StartRequest(repo={str(self.repo)!r}, task="again", tests=["x"], main_agent="fakemain",
                                    review_agent="fakereview", expected_branch="main")
            try:
                orch.start_run(req)
                dup = "STARTED"
            except rs.ActiveRunExists as exc:
                dup = "REFUSED:" + exc.run_id
            print(json.dumps([found, dup]))
        """)
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT,
                             env={**os.environ, "PYTHONPATH": str(ROOT / "tests")}, timeout=90)
        self.assertEqual(out.returncode, 0, out.stderr)
        import json
        found, dup = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual([f[0] for f in found], [run_dir.name])
        self.assertEqual(found[0][1], rs.LIVE_RUNNING)
        self.assertEqual(found[0][3], "fakemain")
        self.assertEqual(dup, f"REFUSED:{run_dir.name}")
        self.assertEqual(len(rs.list_runs(repo=str(self.repo))), 1)  # nothing new was created


class StaleDetectionTests(LifecycleCase):
    def fabricate(self, *, pid, token, stage=rs.IMPLEMENTING, heartbeat_age=None, name="20260101-000001-000000"):
        run_dir = rs.runs_root() / name
        run_dir.mkdir(parents=True)
        record = rs.new_record(run_id=name, repo=str(self.repo), task="t", main_agent="fakemain",
                               review_agent="fakereview", tests=["x"], limits=rs.Limits())
        record["stage"] = stage
        record["created_at"] = "2020-01-01T00:00:00"
        record["worker"] = {"pid": pid, "token": token, "started_at": "2020-01-01T00:00:00"}
        write_json_atomic(run_dir / "run.json", record)
        if heartbeat_age is not None:
            write_json_atomic(run_dir / "heartbeat.json", {"ts": time.time() - heartbeat_age, "pid": pid, "token": token,
                                                           "stage": stage, "seq": 1})
        return run_dir

    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        token = process_start_token(proc.pid) or "gone"
        proc.wait()
        return proc.pid, token

    def test_dead_worker_is_never_reported_as_running(self):
        pid, token = self.dead_pid()
        run_dir = self.fabricate(pid=pid, token=token, heartbeat_age=1)  # fresh-looking heartbeat, dead process
        info = rs.inspect_run(run_dir)
        self.assertEqual(info["liveness"], rs.LIVE_LOST)
        self.assertNotIn(run_dir.name, [i["record"]["run_id"] for i in rs.active_runs()])

    def test_reused_pid_is_not_mistaken_for_the_worker(self):
        me = os.getpid()
        run_dir = self.fabricate(pid=me, token="not-my-start-time", heartbeat_age=1)
        self.assertEqual(rs.inspect_run(run_dir)["liveness"], rs.LIVE_LOST)

    def test_live_process_with_stale_heartbeat_is_unresponsive_not_running(self):
        me = os.getpid()
        run_dir = self.fabricate(pid=me, token=process_start_token(me), heartbeat_age=600)
        info = rs.inspect_run(run_dir)
        self.assertEqual(info["liveness"], rs.LIVE_UNRESPONSIVE)
        self.assertIn("接続不能", info["reason"])
        # unresponsive is treated as possibly alive: no duplicate start, no reclaiming the lock
        rs.acquire_repo_lock(str(self.repo), run_dir.name)
        with self.assertRaises(rs.ActiveRunExists):
            rs.acquire_repo_lock(str(self.repo), "someone-else")

    def test_lost_run_is_reconciled_and_the_repo_is_released(self):
        pid, token = self.dead_pid()
        run_dir = self.fabricate(pid=pid, token=token)
        rs.acquire_repo_lock(str(self.repo), run_dir.name)
        rs.acquire_repo_lock(str(self.repo), "new-run")  # holder is provably gone: reclaimed
        record = rs.read_record(run_dir)
        self.assertEqual(record["stage"], rs.FAILED)
        self.assertEqual(record["final_result"]["code"], "WORKER_LOST")

    def test_stuck_run_on_one_repo_does_not_lock_another_repo(self):
        me = os.getpid()
        run_dir = self.fabricate(pid=me, token=process_start_token(me), heartbeat_age=600)
        rs.acquire_repo_lock(str(self.repo), run_dir.name)
        other = self.make_repo("other")
        rs.acquire_repo_lock(str(other), "other-run")  # independent
        self.assertEqual([i["record"]["run_id"] for i in rs.active_runs(str(other))], [])


class SafeStopTests(LifecycleCase):
    def test_safe_stop_ends_only_this_runs_process_tree(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: bystander.poll() is None and bystander.kill())
        run_dir = self.start("Create feature.txt STREAM-CHILD")
        self.wait_for(run_dir, lambda i: i["liveness"] == rs.LIVE_RUNNING
                      and (run_dir.parent / run_dir.name / "x").parent.exists(), 30, "running")
        record = self.wait_for(run_dir, lambda i: bool(i["record"]["children"]) and bool(i["record"]["worktree"]),
                               30, "registered child")["record"]
        pids_file = Path(record["worktree"]).parent / "pids.txt"
        deadline = time.monotonic() + 20
        while not pids_file.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        child_pid, grand_pid = [int(x) for x in pids_file.read_text().split()]
        worker_pid = record["worker"]["pid"]
        self.assertTrue(alive(child_pid) and alive(grand_pid))

        final = rs.force_stop(run_dir)
        self.assertEqual(final["stage"], rs.STOPPED)
        self.assertTrue(final["stopped_by_user"])
        self.assertEqual(final["final_result"]["code"], "USER_SAFETY_STOP")
        self.assertIn("process_results", final["final_result"])
        time.sleep(1.0)
        self.assertFalse(alive(child_pid), "provider child must be gone")
        self.assertFalse(alive(grand_pid), "grandchild must be gone")
        self.assertFalse(alive(worker_pid), "worker must be gone")
        self.assertIsNone(bystander.poll(), "an unrelated python process must survive")
        self.assertTrue(alive(bystander.pid))
        self.assertTrue(Path(record["worktree"]).exists(), "the worktree is preserved for inspection")
        self.assertEqual(rs.active_runs(str(self.repo)), [])

    def test_forced_stop_of_an_uncooperative_worker_uses_verified_identity(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: bystander.poll() is None and bystander.kill())
        run_dir = self.start("Create feature.txt SLEEP")
        record = self.wait_for(run_dir, lambda i: i["liveness"] == rs.LIVE_RUNNING and i["record"]["worktree"],
                               30, "running")["record"]
        flag = Path(record["worktree"]).parent / "sleeping.flag"
        deadline = time.monotonic() + 20
        while not flag.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        worker_pid = record["worker"]["pid"]
        final = rs.force_stop(run_dir, wait=2)
        self.assertEqual(final["stage"], rs.STOPPED)
        self.assertTrue(final["final_result"].get("forced"))
        time.sleep(0.5)
        self.assertFalse(alive(worker_pid))
        self.assertTrue(alive(bystander.pid))

    def test_stop_never_touches_a_pid_whose_identity_does_not_match(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: bystander.poll() is None and bystander.kill())
        from tools.ai_orchestrator.common import terminate_pid_tree
        self.assertFalse(terminate_pid_tree(bystander.pid, "wrong-token"))
        time.sleep(0.3)
        self.assertIsNone(bystander.poll())


if __name__ == "__main__":
    unittest.main()
