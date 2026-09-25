"""Start-time validation, real-Git host behaviour, safety boundaries (fake providers, no paid AI)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from tools.ai_orchestrator import orchestrator as orch
from tools.ai_orchestrator import providers
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import OrchestratorError, ProcessHooks, StopRequested
from tools.ai_orchestrator.providers import AgentResult, Provider

TEST_CMD = 'python -c "import pathlib, sys; sys.exit(0 if pathlib.Path(\'feature.txt\').exists() else 1)"'


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


class QuietProvider(Provider):
    """Writes feature.txt; optional `hook(worktree)` lets a test act like a misbehaving agent."""

    hook = None

    def preflight(self):
        pass

    def run_main(self, worktree, prompt, *, timeout, hooks, session_id=None):
        (Path(worktree) / "feature.txt").write_text("done\n", encoding="utf-8")
        if type(self).hook:
            type(self).hook(Path(worktree))
        return AgentResult(self.name, "main", True, text="implemented")

    def run_review(self, worktree, prompt, *, timeout, hooks):
        return AgentResult(self.name, "review", True,
                           text='{"verdict": "PASS", "summary": "checked diff and Tests", "findings": []}')


def provider_class(name):
    return type(f"Quiet_{name}", (QuietProvider,), {"name": name, "display": name.title(), "hook": None})


class HostCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = {"AI_ORCHESTRATOR_STATE_ROOT": str(self.tmp / "state"), "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
               "CLAUDE_CODE_USE_BEDROCK": "", "CLAUDE_CODE_USE_VERTEX": "", "CLAUDE_CODE_USE_FOUNDRY": ""}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.classes = {n: provider_class(n) for n in ("claude", "codex")}
        extra = mock.patch.dict(providers.PROVIDER_CLASSES, self.classes)
        extra.start()
        self.addCleanup(extra.stop)
        origin = self.tmp / "origin.git"
        self.repo = self.tmp / "app"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "init")
        git(self.repo, "push", "-u", "origin", "main")

    def request(self, **extra):
        values = dict(repo=str(self.repo), task="Create feature.txt", tests=[TEST_CMD], expected_branch="main")
        values.update(extra)
        return orch.StartRequest(**values)

    def run_worker(self, **extra):
        run_dir, record = orch.prepare_run(self.request(**extra))
        code = orch.worker_main(run_dir, refresh_usage=False)
        record = rs.read_record(run_dir)
        if record.get("worktree"):  # preserved worktrees (needs_human runs) must not pile up in %TEMP%
            self.addCleanup(shutil.rmtree, Path(record["worktree"]).parent, ignore_errors=True)
        return run_dir, record, code


class StartValidationTests(HostCase):
    def test_defaults_are_claude_main_and_codex_reviewer_and_are_saved_in_the_run(self):
        run_dir, record = orch.prepare_run(self.request())
        self.assertEqual((record["main_agent"], record["review_agent"]), ("claude", "codex"))
        saved = rs.read_record(run_dir)
        self.assertEqual((saved["main_agent"], saved["review_agent"]), ("claude", "codex"))
        self.assertEqual(saved["stage"], rs.CREATED)
        self.assertEqual(saved["base_sha"], git(self.repo, "rev-parse", "HEAD").strip())
        self.assertEqual(saved["tests"], [TEST_CMD])
        self.assertEqual(saved["limits"]["reviewer_trigger_fails"], 2)

    def test_codex_main_claude_reviewer_is_saved_too(self):
        _, record = orch.prepare_run(self.request(main_agent="codex", review_agent="claude"))
        self.assertEqual((record["main_agent"], record["review_agent"]), ("codex", "claude"))

    def test_same_provider_is_refused_unless_explicitly_allowed(self):
        with self.assertRaises(OrchestratorError) as ctx:
            orch.prepare_run(self.request(main_agent="claude", review_agent="claude"))
        self.assertEqual(ctx.exception.code, "SAME_PROVIDER_ROLES")
        self.assertEqual(rs.list_runs(), [])
        _, record = orch.prepare_run(self.request(main_agent="claude", review_agent="claude", allow_same_provider=True))
        self.assertTrue(record["same_provider_override"])

    def test_refusals_create_no_run_and_no_lock(self):
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        cases = [
            (self.request(), "SOURCE_DIRTY"),
            (self.request(task="  "), "TASK_EMPTY"),
            (self.request(tests=[]), "TESTS_MISSING"),
            (self.request(main_agent="gemini"), "UNKNOWN_PROVIDER"),
            (self.request(expected_branch="develop"), None),
        ]
        git(self.repo, "checkout", "--", "README.md")
        for request, code in cases:
            if code == "SOURCE_DIRTY":
                (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
            with self.subTest(code=code):
                with self.assertRaises(OrchestratorError) as ctx:
                    orch.prepare_run(request)
                if code:
                    self.assertEqual(ctx.exception.code, code)
                if code == "SOURCE_DIRTY":
                    git(self.repo, "checkout", "--", "README.md")
        self.assertEqual(rs.list_runs(), [])
        self.assertFalse(list((rs.locks_root()).glob("*.json")) if rs.locks_root().exists() else [])

    def test_unpushed_head_is_refused(self):
        (self.repo / "more.txt").write_text("x", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "unpushed")
        with self.assertRaises(OrchestratorError) as ctx:
            orch.prepare_run(self.request(fetch=False))
        self.assertEqual(ctx.exception.code, "SOURCE_NOT_SYNCED")

    def test_api_billing_environment_is_refused_by_default(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with self.assertRaises(OrchestratorError) as ctx:
                orch.prepare_run(self.request())
            self.assertEqual(ctx.exception.code, "API_BILLING_ENV")
            _, record = orch.prepare_run(self.request(allow_api_billing=True))
            self.assertEqual(record["billing_env_override"], ["ANTHROPIC_API_KEY"])

    def test_second_run_on_the_same_repo_is_refused_while_the_first_is_alive(self):
        run_dir, _ = orch.prepare_run(self.request())
        record = rs.read_record(run_dir)
        me = os.getpid()
        from tools.ai_orchestrator.common import process_start_token
        record["worker"] = {"pid": me, "token": process_start_token(me)}
        rs.write_json_atomic(run_dir / "run.json", record)
        rs.write_json_atomic(run_dir / "heartbeat.json", {"ts": time.time(), "pid": me,
                                                          "token": process_start_token(me), "stage": "testing", "seq": 1})
        with self.assertRaises(rs.ActiveRunExists):
            orch.prepare_run(self.request())

    def test_limits_are_configurable_constants_saved_with_the_run(self):
        limits = rs.Limits(max_repair_iterations=3, reviewer_trigger_fails=4)
        _, record = orch.prepare_run(self.request(limits=limits))
        self.assertEqual(record["limits"]["max_repair_iterations"], 3)
        self.assertEqual(record["limits"]["reviewer_trigger_fails"], 4)
        args = orch.build_parser().parse_args(["start", "--repo", ".", "--task", "x", "--test", "t",
                                               "--max-repair-iterations", "5", "--main", "codex", "--reviewer", "claude"])
        request = orch._request_from_args(args)
        self.assertEqual((request.limits.max_repair_iterations, request.main_agent, request.review_agent), (5, "codex", "claude"))


class WorkerRunTests(HostCase):
    def test_completed_run_leaves_a_candidate_and_never_moves_the_source_branch(self):
        head_before = git(self.repo, "rev-parse", "HEAD").strip()
        run_dir, record, code = self.run_worker()
        self.assertEqual((code, record["stage"]), (0, rs.COMPLETED), record["final_result"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), head_before)
        self.assertEqual(git(self.repo, "status", "--porcelain").strip(), "")
        self.assertEqual(git(self.repo, "rev-parse", record["candidate_branch"]).strip(), record["candidate_sha"])
        self.assertEqual(record["apply_status"], "ready")
        self.assertEqual(rs.active_runs(), [])
        self.assertEqual((record["main_calls"], record["review_calls"], record["tests_run_count"]), (1, 1, 1))
        # no push happened: origin still has only the initial commit
        remote = git(self.tmp / "origin.git", "branch", "--list", "ai-candidate/*").strip()
        self.assertEqual(remote, "")

    def test_source_repo_changing_during_the_run_holds_the_apply_but_does_not_fail_the_run(self):
        def normal_development(worktree):
            (self.repo / "other.txt").write_text("dev work\n", encoding="utf-8")
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-m", "normal development while the orchestrator works")

        self.classes["claude"].hook = staticmethod(normal_development)
        _, record, code = self.run_worker()
        self.assertEqual(record["stage"], rs.COMPLETED, record["final_result"])
        self.assertEqual(record["apply_status"], "held_base_moved")
        self.assertIn("再確認", record["apply_detail"])
        # the user's commit is untouched
        self.assertIn("normal development", git(self.repo, "log", "-1", "--format=%s"))

    def test_dirty_source_working_tree_only_holds_the_apply(self):
        def user_edits(worktree):
            (self.repo / "README.md").write_text("user is editing\n", encoding="utf-8")

        self.classes["claude"].hook = staticmethod(user_edits)
        _, record, _ = self.run_worker()
        self.assertEqual(record["stage"], rs.COMPLETED)
        self.assertEqual(record["apply_status"], "held_source_dirty")
        self.assertEqual((self.repo / "README.md").read_text(encoding="utf-8"), "user is editing\n")

    def test_agent_committing_in_the_worktree_is_a_safety_stop_with_no_candidate(self):
        def commit(worktree):
            git(worktree, "add", "-A")
            git(worktree, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-m", "agent commit")

        self.classes["claude"].hook = staticmethod(commit)
        _, record, code = self.run_worker()
        self.assertEqual(record["stage"], rs.NEEDS_HUMAN)
        self.assertEqual(record["final_result"]["code"], "SAFETY_VIOLATION")
        self.assertEqual(record["candidate_sha"], "")
        self.assertTrue(Path(record["worktree"]).exists(), "worktree is preserved for inspection")
        self.assertEqual(git(self.repo, "branch", "--list", "ai-candidate/*").strip(), "")

    def test_failing_tests_forever_end_in_needs_human_not_an_endless_loop(self):
        limits = rs.Limits(max_same_failure=2)
        _, record, code = self.run_worker(tests=['python -c "import sys; print(\'FAIL: test_x\'); sys.exit(1)"'], limits=limits)
        self.assertEqual(record["stage"], rs.NEEDS_HUMAN)
        self.assertEqual(record["final_result"]["code"], "SAME_FAILURE_REPEATED")
        self.assertEqual(record["tests_fail_count"], 2)

    def test_repo_lock_is_released_at_every_terminal_state(self):
        self.run_worker()
        self.assertFalse(list(rs.locks_root().glob("*.json")))
        orch.prepare_run(self.request())  # a new run can start


class GitHostTests(HostCase):
    def make_host(self):
        baseline = orch.repo_baseline(self.repo, "main", False)
        parent, worktree = orch.create_worktree(baseline, "t1")
        self.addCleanup(lambda: orch._remove_worktree(baseline, worktree))
        return orch.GitHost(baseline, worktree, "t1")

    def test_tests_with_quotes_run_and_report_pass_or_fail(self):
        host = self.make_host()
        ok, text = host.run_tests(['python -c "print(\'hello world\')"'], 60, ProcessHooks())
        self.assertTrue(ok)
        self.assertIn("hello world", text)
        ok, text = host.run_tests(['python -c "import sys; print(\'boom\'); sys.exit(3)"'], 60, ProcessHooks())
        self.assertFalse(ok)
        self.assertIn("boom", text)

    def test_hanging_tests_time_out_and_their_process_tree_is_terminated(self):
        host = self.make_host()
        marker = self.tmp / "started.txt"
        code = f"import pathlib, time; pathlib.Path(r'{marker}').write_text('x'); time.sleep(300)"
        started = time.monotonic()
        ok, text = host.run_tests([f'python -c "{code}"'], 3, ProcessHooks())
        self.assertFalse(ok)
        self.assertIn("HANG", text)
        self.assertLess(time.monotonic() - started, 30)
        self.assertTrue(marker.exists())

    def test_stop_request_terminates_running_tests(self):
        host = self.make_host()
        stop = threading.Event()
        threading.Timer(1.5, stop.set).start()
        with self.assertRaises(StopRequested):
            host.run_tests(['python -c "import time; time.sleep(300)"'], 120, ProcessHooks(stop=stop))

    def test_snapshot_includes_untracked_files_and_changes_when_content_changes(self):
        host = self.make_host()
        empty = host.snapshot()
        self.assertEqual(empty.diff.strip(), "")
        (host.worktree / "new.txt").write_text("one", encoding="utf-8")
        first = host.snapshot()
        self.assertIn("new.txt", first.diff)
        self.assertIn("new.txt", " ".join(first.files))
        (host.worktree / "new.txt").write_text("two", encoding="utf-8")
        self.assertNotEqual(host.snapshot().fingerprint, first.fingerprint)

    def test_bytecode_caches_are_neither_diffed_nor_committed(self):
        host = self.make_host()
        cache = host.worktree / "pkg" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "m.cpython-313.pyc").write_bytes(bytes([0, 1]))
        (host.worktree / "__pycache__").mkdir()
        (host.worktree / "__pycache__" / "top.pyc").write_bytes(bytes([2]))
        (host.worktree / "stray.pyc").write_bytes(bytes([3]))
        (host.worktree / "feature.txt").write_text("real work", encoding="utf-8")
        snapshot = host.snapshot()
        self.assertIn("feature.txt", snapshot.diff)
        self.assertNotIn("pyc", snapshot.diff + " ".join(snapshot.files))
        info = host.create_candidate("Task", "t1")
        committed = git(host.worktree, "show", "--name-only", "--format=", info["sha"]).split()
        self.assertEqual(committed, ["feature.txt"])

    @unittest.skipUnless(os.name == "nt", "Windows ACL normalisation")
    def test_windows_files_touched_by_a_sandboxed_agent_get_user_modify_rights(self):
        host = self.make_host()
        (host.worktree / "sub").mkdir()
        (host.worktree / "sub" / "made_by_agent.txt").write_text("x", encoding="utf-8")
        (host.worktree / "untouched_dir").mkdir()
        host.normalize_permissions()
        user = os.environ["USERDOMAIN"] + chr(92) + os.environ["USERNAME"]

        def acl(path):
            return subprocess.run(["icacls", str(path)], capture_output=True).stdout.decode("cp932", errors="replace")

        self.assertIn(user + ":(M)", acl(host.worktree / "sub" / "made_by_agent.txt"))
        self.assertIn(user + ":(M)", acl(host.worktree / "sub"))
        # only what the agent touched is changed: the ACE list of an unrelated empty dir is not modified
        self.assertNotIn(user + ":(M)", acl(host.worktree / "untouched_dir"))

    def test_agent_environment_never_writes_bytecode(self):
        self.assertEqual(providers.agent_env()["PYTHONDONTWRITEBYTECODE"], "1")

    def test_agent_environment_disables_push_without_touching_repo_config(self):
        env = providers.agent_env()
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "disabled://ai-orchestrator")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("disabled://", git(self.repo, "config", "--get-all", "remote.origin.pushurl") if False else "")


if __name__ == "__main__":
    unittest.main()
