"""Start preparation and Tests execution details that cost AI credits when wrong:
automatic source-branch preparation, repo default Tests, Windows quoting, 0-tests handling."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts.dev_control_center import app as dcc_app
from scripts.dev_control_center.core import load_repo_definitions
from tools.ai_orchestrator import orchestrator as orch
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import OrchestratorError, ProcessHooks
from tools.ai_orchestrator.review import (
    NO_TESTS_MARKER, RUNNER_NO_TESTS, RUNNER_UNAVAILABLE, classify_runner_problem, zero_tests_ran,
)
from tools.ai_orchestrator.taskspec import parse_spec_text

from ai_orchestrator_fakes import FakeHost, ScriptedProvider, make_recorder, review_json
from test_ai_orchestrator_host import HostCase, git

DM_ROOT = Path(__file__).resolve().parents[1]
NDS_TESTS = "python -m unittest discover -s tests -p test_*.py -q"


class SourcePreparationTests(HostCase):
    """DCC starts with prepare_source=True: a clean source repo is put on the latest main."""

    def commit(self, repo, name, text="x\n"):
        (repo / name).write_text(text, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", name)
        return git(repo, "rev-parse", "HEAD").strip()

    def push_from_other_clone(self, name):
        other = self.tmp / "other"
        if not other.exists():
            subprocess.run(["git", "clone", str(self.tmp / "origin.git"), str(other)], check=True, capture_output=True)
            git(other, "config", "user.email", "o@example.com")
            git(other, "config", "user.name", "o")
        git(other, "pull", "--ff-only")
        sha = self.commit(other, name)
        git(other, "push", "origin", "main")
        return sha

    def prepared(self, **extra):
        return orch.prepare_run(self.request(prepare_source=True, **extra))

    def test_clean_feature_branch_is_switched_back_to_main_and_synced(self):
        git(self.repo, "switch", "-c", "feature/old")
        self.commit(self.repo, "feature.md")
        origin_sha = self.push_from_other_clone("remote.md")
        run_dir, record = self.prepared()
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "main")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), origin_sha)
        self.assertEqual(record["base_sha"], origin_sha)
        self.assertEqual(record["source_branch"], "main")
        self.assertTrue(any("switched feature/old -> main" in a for a in record["source_preparation"]))
        self.assertTrue(any("fast-forwarded main" in a for a in record["source_preparation"]))
        # the old work branch is never deleted
        self.assertIn("feature/old", git(self.repo, "branch", "--list", "feature/old"))
        self.assertEqual(rs.read_record(run_dir)["source_preparation"], record["source_preparation"])

    def test_uncommitted_changes_stop_without_switching_or_pulling(self):
        git(self.repo, "switch", "-c", "feature/wip")
        (self.repo / "README.md").write_text("work in progress\n", encoding="utf-8")
        self.push_from_other_clone("remote.md")
        with self.assertRaises(OrchestratorError) as ctx:
            self.prepared()
        self.assertEqual(ctx.exception.code, "SOURCE_DIRTY")
        self.assertIn("README.md", str(ctx.exception))
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "feature/wip")
        self.assertEqual((self.repo / "README.md").read_text(encoding="utf-8"), "work in progress\n")
        self.assertEqual(git(self.repo, "stash", "list").strip(), "")
        self.assertEqual(rs.list_runs(), [])
        self.assertFalse(list(rs.locks_root().glob("*.json")) if rs.locks_root().exists() else [])

    def test_main_behind_origin_is_fast_forwarded(self):
        before = git(self.repo, "rev-parse", "HEAD").strip()
        origin_sha = self.push_from_other_clone("remote.md")
        _, record = self.prepared()
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), origin_sha)
        self.assertEqual(record["source_preparation"], [f"fast-forwarded main {before[:12]} -> {origin_sha[:12]}"])
        # a single merge parent chain: fast-forward, never a merge commit
        self.assertEqual(git(self.repo, "rev-list", "--merges", "HEAD").strip(), "")

    def test_diverged_main_stops_without_merge_or_reset(self):
        git(self.repo, "switch", "-c", "feature/x")
        git(self.repo, "switch", "main")
        local_sha = self.commit(self.repo, "local.md")
        self.push_from_other_clone("remote.md")
        git(self.repo, "switch", "feature/x")
        with self.assertRaises(OrchestratorError) as ctx:
            self.prepared()
        self.assertEqual(ctx.exception.code, "SOURCE_DIVERGED")
        self.assertEqual(git(self.repo, "rev-parse", "main").strip(), local_sha)
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "feature/x")  # not switched either
        self.assertEqual(rs.list_runs(), [])

    def test_unpushed_main_stops(self):
        self.commit(self.repo, "local.md")
        with self.assertRaises(OrchestratorError) as ctx:
            self.prepared()
        self.assertEqual(ctx.exception.code, "SOURCE_AHEAD")

    def test_in_progress_git_operation_and_detached_head_stop(self):
        git(self.repo, "switch", "--detach", "HEAD")
        with self.assertRaises(OrchestratorError) as ctx:
            self.prepared()
        self.assertEqual(ctx.exception.code, "SOURCE_DETACHED")
        git(self.repo, "switch", "main")
        marker = Path(git(self.repo, "rev-parse", "--absolute-git-dir").strip()) / "MERGE_HEAD"
        marker.write_text(git(self.repo, "rev-parse", "HEAD"), encoding="utf-8")
        self.addCleanup(marker.unlink, missing_ok=True)
        with self.assertRaises(OrchestratorError) as ctx:
            self.prepared()
        self.assertEqual(ctx.exception.code, "SOURCE_OPERATION_IN_PROGRESS")

    def test_not_a_git_repository_stops(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(OrchestratorError) as ctx:
            orch.prepare_run(self.request(repo=str(plain), prepare_source=True))
        self.assertEqual(ctx.exception.code, "NOT_A_GIT_REPO")

    def test_source_is_not_moved_while_another_run_holds_the_repo(self):
        self.prepared()  # first run: created, lock held (worker never started -> 'starting')
        git(self.repo, "switch", "-c", "feature/y")
        with mock.patch.object(rs, "inspect_run", return_value={"liveness": rs.LIVE_RUNNING}):
            with self.assertRaises(OrchestratorError):
                self.prepared()
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "feature/y")

    def test_without_prepare_source_the_existing_guards_are_unchanged(self):
        git(self.repo, "switch", "-c", "feature/z")
        with self.assertRaises(OrchestratorError) as ctx:
            orch.prepare_run(self.request(fetch=False))
        self.assertEqual(ctx.exception.code, "WRONG_BRANCH")
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "feature/z")

    def test_cli_exposes_prepare_source(self):
        args = orch.build_parser().parse_args(["start", "--repo", "r", "--task", "t", "--test", "x",
                                               "--expected-branch", "main", "--prepare-source"])
        self.assertTrue(orch._request_from_args(args).prepare_source)
        args = orch.build_parser().parse_args(["start", "--repo", "r", "--task", "t", "--test", "x"])
        self.assertFalse(orch._request_from_args(args).prepare_source)


class SpecFileTests(HostCase):
    """--spec-file / StartRequest.spec: fixed criteria bypass text extraction and the Reviewer
    criteria call entirely (Task 9)."""

    def test_spec_criteria_fill_run_json_and_are_saved_as_spec_json(self):
        spec = parse_spec_text('{"criteria": [{"id": "Z1", "text": "custom id kept"}, {"text": "auto numbered"}]}')
        run_dir, record = orch.prepare_run(self.request(spec=spec))
        self.assertEqual(record["criteria_source"], "spec")
        self.assertEqual(record["criteria"], [{"id": "Z1", "text": "custom id kept"},
                                               {"id": "C1", "text": "auto numbered"}])
        saved = json.loads((run_dir / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["criteria"], record["criteria"])
        self.assertIsNone(saved["target_repo"])
        self.assertEqual(rs.read_record(run_dir)["criteria_source"], "spec")

    def test_without_a_spec_criteria_source_and_spec_json_are_unchanged(self):
        run_dir, record = orch.prepare_run(self.request())
        self.assertEqual((record["criteria"], record["criteria_source"]), ([], ""))
        self.assertFalse((run_dir / "spec.json").exists())

    def test_cli_spec_file_argument_loads_into_the_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.json"
            spec_path.write_text('{"criteria": [{"text": "a"}], "target_repo": "r"}', encoding="utf-8")
            args = orch.build_parser().parse_args(
                ["start", "--task", "t", "--test", "x", "--spec-file", str(spec_path)])
            request = orch._request_from_args(args)
            self.assertEqual(request.spec.criteria, ({"id": "C1", "text": "a"},))
            self.assertEqual(request.spec.target_repo, "r")
            self.assertIsNone(request.repo)  # --repo is optional (Task 9: resolved from the registry)

    def test_cli_rejects_a_broken_spec_file_before_any_run_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.json"
            spec_path.write_text("{not json", encoding="utf-8")
            args = orch.build_parser().parse_args(
                ["start", "--repo", str(self.repo), "--task", "t", "--test", "x", "--spec-file", str(spec_path)])
            with self.assertRaises(OrchestratorError) as ctx:
                orch._request_from_args(args)
            self.assertEqual(ctx.exception.code, "SPEC_INVALID")
            self.assertEqual(rs.list_runs(), [])


class TargetRepoMismatchTests(HostCase):
    """The task's own "対象リポジトリ:" line, or the spec's target_repo, must agree with the
    repository that was actually selected (Task 9: two prior start-the-wrong-repo incidents)."""

    def test_mismatched_task_line_is_refused_before_any_run_or_lock(self):
        with self.assertRaises(OrchestratorError) as ctx:
            orch.prepare_run(self.request(task="対象リポジトリ: some-other-repo\nCreate feature.txt"))
        self.assertEqual(ctx.exception.code, "TASK_REPO_MISMATCH")
        self.assertIn("some-other-repo", str(ctx.exception))
        self.assertIn(self.repo.name, str(ctx.exception))
        self.assertEqual(rs.list_runs(), [])
        self.assertFalse(list(rs.locks_root().glob("*.json")) if rs.locks_root().exists() else [])

    def test_mismatched_spec_target_repo_is_refused(self):
        spec = parse_spec_text('{"criteria": [{"text": "a"}], "target_repo": "some-other-repo"}')
        with self.assertRaises(OrchestratorError) as ctx:
            orch.prepare_run(self.request(spec=spec))
        self.assertEqual(ctx.exception.code, "TASK_REPO_MISMATCH")
        self.assertEqual(rs.list_runs(), [])

    def test_matching_name_tolerates_width_case_and_trailing_bracket(self):
        task = f"対象リポジトリ：{self.repo.name.upper()}（本番）\nCreate feature.txt"
        run_dir, record = orch.prepare_run(self.request(task=task))
        self.assertEqual(Path(record["repo"]).name, self.repo.name)

    def test_marker_after_the_first_10_lines_is_not_checked(self):
        lines = [f"line {i}" for i in range(10)] + ["対象リポジトリ: some-other-repo"]
        task = "\n".join(lines) + "\nCreate feature.txt"
        run_dir, record = orch.prepare_run(self.request(task=task))  # no TASK_REPO_MISMATCH
        self.assertEqual(Path(record["repo"]).name, self.repo.name)

    def test_task_without_a_target_line_starts_as_before(self):
        run_dir, record = orch.prepare_run(self.request())
        self.assertEqual(Path(record["repo"]).name, self.repo.name)

    def test_leading_blank_lines_are_not_stripped_before_counting_the_first_10_lines(self):
        # 10 leading blank lines push a mismatched "対象リポジトリ:" line to line 11 of the
        # *original* text; task.strip() must not remove them first and shift it back to line 1.
        task = "\n" * 10 + "対象リポジトリ: some-other-repo\nCreate feature.txt"
        run_dir, record = orch.prepare_run(self.request(task=task))  # no TASK_REPO_MISMATCH
        self.assertEqual(Path(record["repo"]).name, self.repo.name)

    def test_cli_task_file_leading_blank_lines_are_not_stripped_either(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "task.md"
            task_path.write_text("\n" * 10 + "対象リポジトリ: some-other-repo\nCreate feature.txt", encoding="utf-8")
            args = orch.build_parser().parse_args(
                ["start", "--repo", str(self.repo), "--task-file", str(task_path), "--test", "x"])
            request = orch._request_from_args(args)
            run_dir, record = orch.prepare_run(request)  # no TASK_REPO_MISMATCH
            self.assertEqual(Path(record["repo"]).name, self.repo.name)


class RepoAutoResolutionTests(HostCase):
    """StartRequest.repo can be omitted: it is then resolved from the spec / task target against
    the registry (Task 9), the same check prepare_run runs for an explicit --repo (used by both
    DCC's start form and the CLI, since both call prepare_run)."""

    def registry(self, *names):
        return mock.patch.object(orch, "_registry_definitions", lambda: [SimpleNamespace(name=n) for n in names])

    def request_no_repo(self, **extra):
        return self.request(repo=None, **extra)

    def test_omitted_repo_is_resolved_from_the_task_line(self):
        with self.registry(self.repo.name), mock.patch.object(orch, "DM_ROOT", self.tmp / "development-management"):
            run_dir, record = orch.prepare_run(self.request_no_repo(
                task=f"対象リポジトリ: {self.repo.name}\nCreate feature.txt"))
        self.assertEqual(Path(record["repo"]).resolve(), self.repo.resolve())

    def test_omitted_repo_is_resolved_from_the_spec_target_repo_alone(self):
        spec = parse_spec_text('{"criteria": [{"text": "a"}], "target_repo": "%s"}' % self.repo.name)
        with self.registry(self.repo.name), mock.patch.object(orch, "DM_ROOT", self.tmp / "development-management"):
            run_dir, record = orch.prepare_run(self.request_no_repo(task="Create feature.txt", spec=spec))
        self.assertEqual(Path(record["repo"]).resolve(), self.repo.resolve())

    def test_omitted_repo_with_no_target_anywhere_is_unresolved(self):
        with self.registry(self.repo.name):
            with self.assertRaises(OrchestratorError) as ctx:
                orch.prepare_run(self.request_no_repo())
        self.assertEqual(ctx.exception.code, "TASK_REPO_UNRESOLVED")
        self.assertIn(self.repo.name, str(ctx.exception))  # candidates are listed
        self.assertEqual(rs.list_runs(), [])

    def test_omitted_repo_with_a_target_not_in_the_registry_is_unresolved(self):
        with self.registry(self.repo.name):
            with self.assertRaises(OrchestratorError) as ctx:
                orch.prepare_run(self.request_no_repo(task="対象リポジトリ: nothing-like-that\nCreate feature.txt"))
        self.assertEqual(ctx.exception.code, "TASK_REPO_UNRESOLVED")
        self.assertEqual(rs.list_runs(), [])

    def test_omitted_repo_with_an_ambiguous_target_is_unresolved(self):
        with self.registry("App", "APP"):
            with self.assertRaises(OrchestratorError) as ctx:
                orch.prepare_run(self.request_no_repo(task="対象リポジトリ: app\nCreate feature.txt"))
        self.assertEqual(ctx.exception.code, "TASK_REPO_UNRESOLVED")
        self.assertIn("App", str(ctx.exception))
        self.assertIn("APP", str(ctx.exception))
        self.assertEqual(rs.list_runs(), [])


class DefaultTestsTests(unittest.TestCase):
    def test_next_day_setup_default_tests_come_from_the_repo_registry(self):
        definitions = {d.name: d for d in load_repo_definitions(
            DM_ROOT / "scripts" / "repo_types.toml", DM_ROOT / "scripts" / "dev_control_center_repos.toml")}
        # the repo's official runner (its CI uses pytest); `python` resolves to the repo .venv in Tests
        self.assertEqual(definitions["next-day-setup"].initial_test, "python -m pytest -q")

    def app_stub(self, initial_test):
        definition = SimpleNamespace(name="next-day-setup", initial_test=initial_test)
        stub = SimpleNamespace(definitions=[definition], ai_drafts={}, orchestrator_window=None,
                               selection=mock.MagicMock())
        stub._configured_tests = lambda name: dcc_app.App._configured_tests(stub, name)
        return stub

    def test_configured_default_is_not_replaced_by_the_guessed_command(self):
        stub = self.app_stub(NDS_TESTS)
        dcc_app.App.on_request_suggestion(stub, "next-day-setup")
        stub.selection.submit_suggest.assert_not_called()
        dcc_app.App.on_suggestion(stub, "next-day-setup", "python -m pytest -q")
        self.assertEqual(stub.ai_drafts, {})  # the window falls back to the configured default

    def test_repo_without_a_configured_default_still_gets_a_suggestion(self):
        stub = self.app_stub("")
        dcc_app.App.on_request_suggestion(stub, "next-day-setup")
        stub.selection.submit_suggest.assert_called_once_with("next-day-setup")
        dcc_app.App.on_suggestion(stub, "next-day-setup", "python -m pytest -q")
        self.assertEqual(stub.ai_drafts["next-day-setup"].tests, "python -m pytest -q")


class WindowsCommandLineTests(unittest.TestCase):
    """What cmd.exe receives for a POSIX-style command line (pure function, any OS)."""

    def test_single_quoted_segments_become_double_quoted(self):
        cases = {
            "python -m unittest discover -s tests -p 'test_*.py' -q":
                'python -m unittest discover -s tests -p "test_*.py" -q',
            "python -m pytest -k 'a and not b' -q": 'python -m pytest -k "a and not b" -q',
            "python -m unittest -p'test_*.py'": 'python -m unittest -p"test_*.py"',
            "python x.py '' 'C:\\dir\\'": 'python x.py "" "C:\\dir\\\\"',
            "python a.py 'x' && python b.py '|'": 'python a.py "x" && python b.py "|"',
        }
        for given, expected in cases.items():
            with self.subTest(given=given):
                self.assertEqual(orch.windows_test_command_line(given), expected)

    def test_commands_without_posix_single_quotes_are_untouched(self):
        for command in (NDS_TESTS, 'python -m unittest discover -s tests -p "test_*.py" -q',
                        'python -c "print(\'hello world\')"', "python -m pytest \"tests/it's here\" -q",
                        "echo don't", "python -c 'print(\"x\")'", "python -c 'print(1)' %PATH%",
                        'python -c "print(\\"x\\")" \'y\''):
            with self.subTest(command=command):
                self.assertEqual(orch.windows_test_command_line(command), command)


@unittest.skipUnless(shutil.which("python"), "python on PATH is required, as for real Tests commands")
class TestsArgumentTests(HostCase):
    """The argv the test runner receives, through the real Tests execution path."""

    def make_host(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_sample.py").write_text(
            "import unittest\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertTrue(True)\n",
            encoding="utf-8")
        (self.repo / "argv.py").write_text("import json, sys\nprint('ARGV=' + json.dumps(sys.argv[1:]))\n",
                                           encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "tests")
        git(self.repo, "push")
        baseline = orch.repo_baseline(self.repo, "main", False)
        _, worktree = orch.create_worktree(baseline, "t1")
        self.addCleanup(lambda: orch._remove_worktree(baseline, worktree))
        return orch.GitHost(baseline, worktree, "t1")

    def test_pattern_argument_reaches_the_runner_unquoted_in_every_form(self):
        host = self.make_host()
        for pattern in ("test_*.py", "'test_*.py'", '"test_*.py"'):
            with self.subTest(pattern=pattern):
                ok, text = host.run_tests([f"python argv.py -s tests -p {pattern} -q"], 60, ProcessHooks())
                self.assertTrue(ok, text)
                argv = json.loads(text.split("ARGV=", 1)[1].splitlines()[0])
                self.assertEqual(argv, ["-s", "tests", "-p", "test_*.py", "-q"])
                ok, text = host.run_tests([f"python -m unittest discover -s tests -p {pattern} -q"], 60, ProcessHooks())
                self.assertTrue(ok, text)
                self.assertIn("Ran 1 test", text)

    def test_arguments_with_spaces_stay_single_arguments(self):
        host = self.make_host()
        ok, text = host.run_tests(["python argv.py -k 'a and b' \"c d\" e"], 60, ProcessHooks())
        self.assertTrue(ok, text)
        self.assertEqual(json.loads(text.split("ARGV=", 1)[1].splitlines()[0]), ["-k", "a and b", "c d", "e"])

    def test_zero_tests_is_never_a_pass_even_with_exit_code_0(self):
        host = self.make_host()
        ok, text = host.run_tests(["python -m unittest discover -s tests -p nomatch_*.py -q"], 60, ProcessHooks())
        self.assertFalse(ok)
        self.assertIn(NO_TESTS_MARKER, text)
        # a runner that exits 0 after running nothing
        ok, text = host.run_tests(['python -c "print(\'Ran 0 tests in 0.000s\'); print(\'OK\')"'], 60, ProcessHooks())
        self.assertFalse(ok)
        self.assertEqual(classify_runner_problem(text), RUNNER_NO_TESTS)



PROBE = ("python -c \"import os, sys, probe_mod; "
         "print('EXE=' + sys.executable); print('CWD=' + os.getcwd()); print('MOD=' + probe_mod.__file__); "
         "print('VENV=' + str(sys.prefix != sys.base_prefix))\"")


class RepoVenvTestsTests(HostCase):
    """Independent Tests use the source repo's git-ignored .venv interpreter, on the worktree's code."""

    def setUp(self):
        super().setUp()
        (self.repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        (self.repo / "probe_mod.py").write_text("WHERE = 'committed'\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "probe")
        git(self.repo, "push")

    def make_venv(self):
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.repo / ".venv")], check=True,
                       capture_output=True)

    def make_host(self):
        baseline = orch.repo_baseline(self.repo, "main", False)
        _, worktree = orch.create_worktree(baseline, "t1")
        self.addCleanup(lambda: orch._remove_worktree(baseline, worktree))
        return orch.GitHost(baseline, worktree, "t1")

    @staticmethod
    def values(text):
        return dict(line.split("=", 1) for line in text.splitlines() if line[:4] in ("EXE=", "CWD=", "MOD=", "VENV"))

    def test_repo_venv_python_runs_the_worktree_code(self):
        self.make_venv()
        host = self.make_host()
        source_status = git(self.repo, "status", "--porcelain", "--ignored")
        before = host.snapshot().fingerprint
        ok, text = host.run_tests([PROBE], 60, ProcessHooks())
        self.assertTrue(ok, text)
        found = self.values(text)
        venv = (self.repo / ".venv").resolve()
        self.assertEqual(found["VENV"], "True")
        self.assertTrue(Path(found["EXE"]).resolve().is_relative_to(venv), found["EXE"])
        self.assertEqual(Path(found["CWD"]).resolve(), host.worktree.resolve())
        self.assertTrue(Path(found["MOD"]).resolve().is_relative_to(host.worktree.resolve()), found["MOD"])
        self.assertIn("repo-local venv first on PATH", text)
        self.assertFalse((host.worktree / ".venv").exists())  # never copied into the worktree
        self.assertEqual(host.snapshot().fingerprint, before)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--ignored"), source_status)

    def test_without_a_repo_venv_python_comes_from_path_as_before(self):
        host = self.make_host()
        env, venv_bin = host.tests_env()
        self.assertIsNone(venv_bin)
        self.assertNotIn("AI_ORCHESTRATOR_TEST_VENV_BIN", env)
        ok, text = host.run_tests([PROBE], 60, ProcessHooks())
        self.assertTrue(ok, text)
        self.assertEqual(self.values(text)["VENV"], "False")
        self.assertNotIn("repo-local venv", text)

    def test_venv_is_only_added_to_the_tests_environment(self):
        self.make_venv()
        host = self.make_host()
        env, venv_bin = host.tests_env()
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(venv_bin))
        self.assertEqual(Path(env["VIRTUAL_ENV"]), self.repo.resolve() / ".venv")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")  # the agent safety overlay is kept
        from tools.ai_orchestrator.providers import agent_env

        self.assertNotIn(str(venv_bin), agent_env()["PATH"].split(os.pathsep)[:1])

class ZeroTestsDetectionTests(unittest.TestCase):
    def test_runner_summaries(self):
        self.assertTrue(zero_tests_ran("----\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n"))
        self.assertTrue(zero_tests_ran("collected 0 items\n\n==== no tests ran in 0.01s ====\n"))
        self.assertFalse(zero_tests_ran("----\nRan 12 tests in 1.2s\n\nOK\n"))
        self.assertFalse(zero_tests_ran("===== 5 passed in 0.3s =====\n"))
        # nested output of an inner runner does not decide it: the last unittest summary does
        self.assertFalse(zero_tests_ran("Ran 0 tests in 0.0s\n...\nRan 40 tests in 3.0s\nOK\n"))

    def test_runner_unavailable_is_classified_but_ordinary_failures_are_not(self):
        self.assertEqual(classify_runner_problem("'pytest' is not recognized as an internal or external command,"),
                         RUNNER_UNAVAILABLE)
        self.assertEqual(classify_runner_problem(r"C:\Python313\python.exe: No module named pytest"), RUNNER_UNAVAILABLE)
        self.assertEqual(classify_runner_problem("bash: pytest: command not found"), RUNNER_UNAVAILABLE)
        self.assertEqual(classify_runner_problem("ModuleNotFoundError: No module named 'app'\nFAILED (errors=1)"), "")
        self.assertEqual(classify_runner_problem("FAIL: test_a\nAssertionError: 1 != 2"), "")


NO_TESTS = (False, "$ python -m unittest discover -s tests -p 'test_*.py' -q\n\n"
                   "----------------------------------------------------------------------\n"
                   "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n" + NO_TESTS_MARKER)
FAIL_A = (False, "FAIL: test_a (m.T)\nAssertionError: 1 != 2\nRan 1 test in 0.1s\nFAILED (failures=1)")
PASS = (True, "OK\nRan 3 tests")


class RepeatedRunnerFailureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def build(self, tests, main_script, review_script=(review_json("PASS"),)):
        from tools.ai_orchestrator.engine import Engine

        self.rec = make_recorder(self.dir)
        self.rec.transition(rs.PREFLIGHT)
        self.host = FakeHost(tests)
        self.main = ScriptedProvider("claude", self.host, main_script)
        self.reviewer = ScriptedProvider("codex", self.host, (), review_script)
        return Engine(self.rec, self.host, self.main, self.reviewer, sleep=lambda s: None)

    def test_repeated_zero_tests_stops_before_reviewer_and_further_repairs(self):
        engine = self.build([NO_TESTS], [("+a", "impl"), ("+b", "fix1"), ("+c", "fix2"), ("+d", "fix3")],
                            [review_json("FAIL", "x", instructions="y")] * 3)
        self.assertEqual(engine.run(), rs.NEEDS_HUMAN)
        record = self.rec.record
        self.assertEqual(record["final_result"]["code"], "TEST_RUNNER_PROBLEM")
        # implementation + exactly one repair; the Reviewer is never asked to analyse a runner problem
        self.assertEqual((record["main_calls"], record["review_calls"], self.host.test_calls), (2, 0, 2))
        self.assertEqual([f["runner_problem"] for f in record["failure_history"]], [RUNNER_NO_TESTS] * 2)
        self.assertIn("IMPLEMENTATION_STATUS: BLOCKED", self.main.main_prompts[1])
        self.assertIn("test command / runner problem", self.main.main_prompts[1])

    def test_one_zero_tests_run_that_the_repair_fixes_still_completes(self):
        engine = self.build([NO_TESTS, PASS], [("+a", "impl"), ("+b", "registered the tests")])
        self.assertEqual(engine.run(), rs.COMPLETED)

    def test_ordinary_failures_keep_the_existing_flow(self):
        engine = self.build([FAIL_A, PASS], [("+a", "impl"), ("+b", "fix")])
        self.assertEqual(engine.run(), rs.COMPLETED)
        self.assertEqual(self.rec.record["failure_history"][0]["runner_problem"], "")
        self.assertNotIn("runner problem", self.main.main_prompts[1])

    def test_a_runner_problem_after_an_ordinary_failure_is_not_counted_as_repeated(self):
        engine = self.build([FAIL_A, NO_TESTS, PASS], [("+a", "impl"), ("+b", "f1"), ("+c", "f2")],
                            [review_json("FAIL", "x", instructions="y"), review_json("PASS")])
        self.assertEqual(engine.run(), rs.COMPLETED)


if __name__ == "__main__":
    unittest.main()
