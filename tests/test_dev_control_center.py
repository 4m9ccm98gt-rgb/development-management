import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev_control_center import app as dcc
from tools.ai_orchestrator import orchestrator as o
from scripts.dev_control_center.core import (
    ControlCenterConfigError,
    EntryPointChoice,
    GitHubState,
    RemoteRepo,
    RepoDefinition,
    RepoEntrypoints,
    RepoState,
    active_repo_definitions,
    apply_local_candidate,
    build_new_repo_setup_prompt,
    candidate_sha_is_valid,
    decide_lifecycle,
    discover_entrypoints,
    list_github_repositories,
    parse_github_repo,
    summarize_ci_state,
    suggest_test_command,
    unmanaged_github_repositories,
)

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_real_registry_has_explicit_branches_for_active_apps(self):
        items = active_repo_definitions(
            ROOT / "scripts" / "repo_types.toml",
            ROOT / "scripts" / "dev_control_center_repos.toml",
        )
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(all(item.branch for item in items))

    def test_missing_active_branch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            types = root / "types.toml"
            branches = root / "branches.toml"
            types.write_text('[types]\napp = "desktop"\n', encoding="utf-8")
            branches.write_text('[branches]\n', encoding="utf-8")
            with self.assertRaises(ControlCenterConfigError):
                active_repo_definitions(types, branches)


class DiscoveryTests(unittest.TestCase):
    def test_nested_standard_entrypoints_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "python_app"
            app.mkdir()
            for name in (
                "SYNC_CLICK_ME.cmd",
                "RUN_DEV.cmd",
                "BUILD_EXE_CLICK_ME.cmd",
                "UPDATE_SHARED_FOLDER.cmd",
            ):
                (app / name).write_text("test", encoding="utf-8")
            found = discover_entrypoints(root, "desktop")
            self.assertTrue(found.sync.ready)
            self.assertTrue(found.run.ready)
            self.assertTrue(found.build.ready)
            self.assertTrue(found.release.ready)
            self.assertEqual(found.release_label, "UPDATE")

    def test_management_repo_ignores_template_build_and_has_no_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "templates" / "windows-python-app"
            template.mkdir(parents=True)
            (template / "BUILD_EXE_CLICK_ME.cmd").write_text("test", encoding="utf-8")
            (root / "RUN_DEV.cmd").write_text("test", encoding="utf-8")
            found = discover_entrypoints(root, "management")
            self.assertTrue(found.run.ready)
            self.assertEqual(found.run.path.name, "RUN_DEV.cmd")
            self.assertEqual(found.run.path.parent.name, root.name)
            self.assertEqual(found.build.state, "N/A")
            self.assertEqual(found.release.state, "N/A")

    def test_ambiguous_best_match_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("a", "b"):
                target = root / folder
                target.mkdir()
                (target / f"BUILD_{folder}_CLICK_ME.cmd").write_text("test", encoding="utf-8")
            found = discover_entrypoints(root, "desktop")
            self.assertEqual(found.build.state, "MULTIPLE")
            self.assertFalse(found.build.ready)

    def test_web_uses_deploy_as_release_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "DEPLOY_CLICK_ME.cmd").write_text("test", encoding="utf-8")
            found = discover_entrypoints(root, "web")
            self.assertTrue(found.release.ready)
            self.assertEqual(found.release_label, "DEPLOY")

    def test_git_repo_ignores_untracked_command_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            tracked = root / "BUILD_SAFE_CLICK_ME.cmd"
            tracked.write_text("tracked", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", tracked.name], check=True)
            untracked = root / "BUILD_EXE_CLICK_ME.cmd"
            untracked.write_text("untracked", encoding="utf-8")

            found = discover_entrypoints(root, "desktop")
            self.assertTrue(found.build.ready)
            self.assertEqual(found.build.path, tracked)


class ValidationTests(unittest.TestCase):
    def test_candidate_sha_requires_full_sha(self):
        self.assertTrue(candidate_sha_is_valid("a" * 40))
        self.assertFalse(candidate_sha_is_valid("abcdef1"))
        self.assertFalse(candidate_sha_is_valid("xyz1234"))
        self.assertFalse(candidate_sha_is_valid("abc"))

    def test_https_remote_parsing(self):
        self.assertEqual(
            parse_github_repo("https://github.com/example/demo.git"),
            "example/demo",
        )


class LocalAiCandidateTests(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return proc.stdout.strip()

    def test_applies_candidate_as_local_fast_forward_without_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            self._git(root, "config", "user.name", "Test")
            self._git(root, "config", "user.email", "test@example.invalid")
            self._git(root, "remote", "add", "origin", "https://github.com/example/demo.git")

            target = root / "demo.txt"
            target.write_text("base\n", encoding="utf-8")
            self._git(root, "add", "demo.txt")
            self._git(root, "commit", "-qm", "base")
            base = self._git(root, "rev-parse", "HEAD")

            self._git(root, "switch", "-qc", "ai-candidate/test")
            target.write_text("candidate\n", encoding="utf-8")
            self._git(root, "add", "demo.txt")
            self._git(root, "commit", "-qm", "candidate")
            candidate = self._git(root, "rev-parse", "HEAD")
            self._git(root, "switch", "-q", "main")

            definition = RepoDefinition("demo", "desktop", "main", owner="example")
            applied = apply_local_candidate(
                root,
                definition,
                base_sha=base,
                candidate_sha=candidate,
            )
            self.assertEqual(applied, candidate)
            self.assertEqual(self._git(root, "branch", "--show-current"), "main")
            self.assertEqual(self._git(root, "rev-parse", "HEAD"), candidate)
            self.assertEqual(self._git(root, "status", "--porcelain"), "")

    def test_rejects_candidate_if_source_head_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            self._git(root, "config", "user.name", "Test")
            self._git(root, "config", "user.email", "test@example.invalid")
            self._git(root, "remote", "add", "origin", "https://github.com/example/demo.git")
            (root / "demo.txt").write_text("base\n", encoding="utf-8")
            self._git(root, "add", "demo.txt")
            self._git(root, "commit", "-qm", "base")
            old_base = self._git(root, "rev-parse", "HEAD")
            (root / "demo.txt").write_text("moved\n", encoding="utf-8")
            self._git(root, "add", "demo.txt")
            self._git(root, "commit", "-qm", "moved")
            current = self._git(root, "rev-parse", "HEAD")
            definition = RepoDefinition("demo", "desktop", "main", owner="example")
            with self.assertRaises(RuntimeError):
                apply_local_candidate(
                    root,
                    definition,
                    base_sha=old_base,
                    candidate_sha=current,
                )

    def test_suggests_pytest_when_repo_has_pytest_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            self.assertEqual(suggest_test_command(root), "python -m pytest -q")

    def test_suggests_unittest_for_plain_tests_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            self.assertEqual(
                suggest_test_command(root),
                "python -m unittest discover -s tests -v",
            )


class GitHubDiscoveryTests(unittest.TestCase):
    def test_unmanaged_filters_managed_archived_and_forks(self):
        repos = [
            RemoteRepo("managed"),
            RemoteRepo("new-app", default_branch="main"),
            RemoteRepo("old-app", is_archived=True),
            RemoteRepo("forked", is_fork=True),
        ]
        result = unmanaged_github_repositories({"managed"}, repos)
        self.assertEqual([item.name for item in result], ["new-app"])

    @patch("scripts.dev_control_center.core._run_gh_json")
    def test_repo_list_parses_default_branch(self, run_json):
        run_json.return_value = [
            {
                "name": "new-app",
                "isArchived": False,
                "isFork": False,
                "defaultBranchRef": {"name": "main"},
            }
        ]
        result = list_github_repositories("example")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].full_name, "example/new-app")
        self.assertEqual(result[0].default_branch, "main")


class CiSummaryTests(unittest.TestCase):
    def test_green_when_all_checks_succeed(self):
        state, count = summarize_ci_state(
            {"check_runs": [
                {"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "skipped"},
            ]},
            {"total_count": 0, "state": ""},
        )
        self.assertEqual(state, "GREEN")
        self.assertEqual(count, 2)

    def test_pending_when_check_is_running(self):
        state, _ = summarize_ci_state(
            {"check_runs": [{"status": "in_progress", "conclusion": None}]},
            {"total_count": 0, "state": ""},
        )
        self.assertEqual(state, "PENDING")

    def test_failed_when_check_fails(self):
        state, _ = summarize_ci_state(
            {"check_runs": [{"status": "completed", "conclusion": "failure"}]},
            {"total_count": 0, "state": ""},
        )
        self.assertEqual(state, "FAILED")

    def test_no_checks_is_reported(self):
        state, count = summarize_ci_state(
            {"check_runs": []},
            {"total_count": 0, "state": ""},
        )
        self.assertEqual(state, "NO CHECKS")
        self.assertEqual(count, 0)

    def test_green_is_not_required_for_candidate(self):
        state = GitHubState(branch_sha="a" * 40, ci_state="FAILED")
        self.assertTrue(state.candidate_ready)

    def test_open_pr_does_not_invalidate_expected_branch_candidate(self):
        state = GitHubState(
            branch_sha="a" * 40,
            ci_state="GREEN",
            candidate_blocked_by_pr=True,
        )
        self.assertTrue(state.candidate_ready)


class LifecycleDecisionTests(unittest.TestCase):
    def setUp(self):
        self.definition = RepoDefinition("demo", "desktop", "main", owner="example")
        ready = EntryPointChoice("READY", Path("entry.cmd"))
        self.entrypoints = RepoEntrypoints(
            sync=ready,
            run=ready,
            build=ready,
            release=ready,
            release_label="UPDATE",
        )

    def repo_state(self, sha="a" * 40, **overrides):
        values = dict(
            exists=True,
            is_git_repo=True,
            branch="main",
            head=sha,
            origin_head=sha,
            origin_repo="example/demo",
            tracked_dirty=False,
            untracked_count=0,
            error="",
        )
        values.update(overrides)
        return RepoState(**values)

    def github_state(self, sha="a" * 40, **overrides):
        values = dict(branch_sha=sha, ci_state="GREEN")
        values.update(overrides)
        return GitHubState(**values)

    def test_restart_restores_branch_candidate_without_memory(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(),
            self.entrypoints,
            self.github_state(),
            explicit_candidate="",
        )
        self.assertEqual(decision.candidate_sha, "a" * 40)
        self.assertEqual(decision.candidate_source, "AUTO / branch HEAD")
        self.assertFalse(decision.sync_enabled)
        self.assertTrue(decision.run_enabled)
        self.assertTrue(decision.build_enabled)
        self.assertTrue(decision.release_enabled)

    def test_unrelated_open_pr_does_not_clear_synced_candidate(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(),
            self.entrypoints,
            self.github_state(candidate_blocked_by_pr=True),
            explicit_candidate="",
        )
        self.assertEqual(decision.candidate_sha, "a" * 40)
        self.assertFalse(decision.sync_enabled)
        self.assertTrue(decision.build_enabled)

    def test_sync_only_when_local_head_differs_from_candidate(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(sha="b" * 40),
            self.entrypoints,
            self.github_state(sha="a" * 40),
            explicit_candidate="",
        )
        self.assertTrue(decision.sync_enabled)
        self.assertFalse(decision.run_enabled)
        self.assertFalse(decision.build_enabled)
        self.assertFalse(decision.release_enabled)
        self.assertIn("SYNC", decision.banner)

    def test_busy_locks_all_lifecycle_actions(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(),
            self.entrypoints,
            self.github_state(),
            busy=True,
        )
        self.assertFalse(decision.sync_enabled)
        self.assertFalse(decision.run_enabled)
        self.assertFalse(decision.build_enabled)
        self.assertFalse(decision.release_enabled)

    def test_dirty_repo_fail_closes_every_action(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(tracked_dirty=True),
            self.entrypoints,
            self.github_state(),
        )
        self.assertFalse(decision.sync_enabled)
        self.assertFalse(decision.run_enabled)
        self.assertFalse(decision.build_enabled)
        self.assertFalse(decision.release_enabled)
        self.assertIn("安全条件NG", decision.banner)

    def test_wrong_branch_and_wrong_origin_fail_closed(self):
        for overrides in (
            {"branch": "feature/test"},
            {"origin_repo": "someone/else"},
        ):
            with self.subTest(overrides=overrides):
                decision = decide_lifecycle(
                    self.definition,
                    self.repo_state(**overrides),
                    self.entrypoints,
                    self.github_state(),
                )
                self.assertFalse(decision.sync_enabled)
                self.assertFalse(decision.run_enabled)
                self.assertFalse(decision.build_enabled)
                self.assertFalse(decision.release_enabled)

    def test_missing_entrypoint_disables_only_that_action(self):
        missing_build = RepoEntrypoints(
            sync=self.entrypoints.sync,
            run=self.entrypoints.run,
            build=EntryPointChoice("MISSING"),
            release=self.entrypoints.release,
            release_label="UPDATE",
        )
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(),
            missing_build,
            self.github_state(),
        )
        self.assertTrue(decision.run_enabled)
        self.assertFalse(decision.build_enabled)
        self.assertTrue(decision.release_enabled)
        self.assertIn("MISSING", decision.build_reason)

    def test_github_unavailable_requires_manual_candidate(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(),
            self.entrypoints,
            GitHubState(error="offline"),
            explicit_candidate="",
        )
        self.assertEqual(decision.candidate_sha, "")
        self.assertFalse(decision.sync_enabled)
        self.assertFalse(decision.run_enabled)
        self.assertIn("手入力", decision.banner)

    def test_valid_manual_candidate_is_preserved(self):
        manual = "c" * 40
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(sha=manual),
            self.entrypoints,
            self.github_state(sha="a" * 40),
            explicit_candidate=manual,
        )
        self.assertEqual(decision.candidate_sha, manual)
        self.assertEqual(decision.candidate_source, "MANUAL")
        self.assertTrue(decision.build_enabled)


    def test_in_progress_manual_candidate_is_not_overwritten(self):
        decision = decide_lifecycle(
            self.definition,
            self.repo_state(),
            self.entrypoints,
            self.github_state(),
            explicit_candidate="abc",
        )
        self.assertEqual(decision.candidate_sha, "abc")
        self.assertEqual(decision.candidate_source, "MANUAL")
        self.assertFalse(decision.sync_enabled)
        self.assertFalse(decision.run_enabled)
        self.assertIn("candidate", decision.banner)


class PromptTests(unittest.TestCase):
    def test_new_repo_setup_requests_central_registration(self):
        remote = RemoteRepo("new-app", default_branch="main", owner="example")
        text = build_new_repo_setup_prompt(remote, Path(r"C:\repos\new-app"))
        self.assertIn("scripts/repo_types.toml", text)
        self.assertIn("scripts/dev_control_center_repos.toml", text)
        self.assertIn("development-management", text)
        self.assertIn("[initial_ai_tasks]", text)
        self.assertIn("[initial_tests]", text)
        self.assertIn("https://github.com/example/new-app", text)


class DarkThemeContractTests(unittest.TestCase):
    def test_dcc_applies_dark_theme_before_building_widgets(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        init_start = text.index("    def __init__(self, master: tk.Tk) -> None:")
        build_start = text.index("    def _build(self) -> None:", init_start)
        init_text = text[init_start:build_start]
        self.assertIn("configure_dark_theme(master)", init_text)
        self.assertIn('style.theme_use("clam")', text)
        self.assertIn('DARK_BG = "#0f1419"', text)
        self.assertIn('DARK_FG = "#e6edf3"', text)

    def test_native_tk_widgets_receive_dark_styling(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        self.assertIn("configure_dark_listbox(self.repo_list)", text)
        self.assertIn("configure_dark_listbox(self.new_repo_list)", text)
        self.assertIn("configure_dark_text(self.ai_task)", text)
        self.assertIn("configure_dark_text(self.log)", text)


class UiLifecycleContractTests(unittest.TestCase):
    def test_gui_uses_pure_lifecycle_decision(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        self.assertIn("decide_lifecycle(", text)
        self.assertIn("self._apply_lifecycle_state()", text)

    def test_ai_development_is_the_primary_visible_route(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        build_start = text.index("    def _build(self) -> None:")
        select_start = text.index("    def _select_repo(self) -> None:", build_start)
        build = text[build_start:select_start]
        self.assertIn('text="AI開発 — Claude実装 → Verification → Final Review → local candidate"', build)
        self.assertIn('self.ai_task = tk.Text(ai_box, height=8, wrap="word")', build)
        self.assertIn('text="全状態更新"', build)
        self.assertIn('text="実機確認・配布"', build)
        self.assertNotIn('text="A: ChatGPT', build)
        self.assertNotIn('text="Bデバッグ指示"', build)
        self.assertNotIn('text="GitHub更新"', build)
        self.assertNotIn('text="STARTUP SET"', build)
        self.assertNotIn('self.sync_button.grid(', build)

    def test_gui_exposes_ai_orchestrator_with_machine_result_handoff(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def launch_ai_orchestrator", text)
        self.assertIn('"--result-file"', text)
        self.assertIn("apply_local_candidate(", text)
        self.assertIn("Claude実装 → Verification → Final Review", text)
        self.assertIn("push / BUILD / UPDATEは行いません", text)

    def test_every_finished_action_refreshes_local_and_github_state(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        poll_start = text.index("    def _poll(self) -> None:")
        state_start = text.index("    def _set_button_states(self) -> None:", poll_start)
        poll = text[poll_start:state_start]
        self.assertIn("self.refresh()", poll)
        self.assertIn("self.refresh_github()", poll)
        self.assertNotIn('if action == "sync"', poll)


class SelfUpdateContractTests(unittest.TestCase):
    def test_sync_wrapper_supports_noninteractive_control_center_call(self):
        text = (ROOT / "SYNC_CLICK_ME.cmd").read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertIn("--no-pause", text)
        self.assertIn("NO_PAUSE_ARG=-NoPause", text)
        self.assertTrue(lines[-1].endswith("& exit /b"))


_MISSING = object()


class ReviewRunFixture:
    """Builds a review_pending run_dir the way the Orchestrator preserves it."""

    HEAD = "a" * 40
    TESTS = ["python -m pytest tests/a.py", "python -m pytest tests/b.py"]

    def make(self, tmp, *, result=None, task="do the thing\n", request=None, write_task=True, write_request=True):
        tmp = Path(tmp)
        self.repo = tmp / "repo"
        run_dir = tmp / "runs" / "20260924-120000-000000"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "review_pending",
            "repo": str(self.repo),
            "source_branch": "main",
            "base_sha": self.HEAD,
            "tests": list(self.TESTS),
            "max_rounds": 30,
        }
        payload.update(result or {})
        payload = {key: value for key, value in payload.items() if value is not _MISSING}
        (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        if write_task:
            (run_dir / "task.md").write_text(task, encoding="utf-8")
        if write_request:
            body = {"request_id": "req-1"} if request is None else request
            (run_dir / "final-review-request.json").write_text(json.dumps(body), encoding="utf-8")
        return run_dir

    def inspect(self, run_dir, *, branch="main", head=None):
        return dcc.inspect_review_pending_run(str(run_dir), self.repo, branch, head or self.HEAD)


class InspectReviewPendingRunTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReviewRunFixture()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make(self, **kwargs):
        return self.fixture.make(self.temp.name, **kwargs)

    def test_review_pending_run_is_accepted_with_values_read_from_the_run(self):
        run_dir = self.make()
        plan = self.fixture.inspect(run_dir)
        self.assertTrue(plan.ok, plan.message)
        self.assertEqual(plan.run_dir, run_dir)
        self.assertEqual(plan.task, "do the thing")
        self.assertEqual(plan.tests, tuple(ReviewRunFixture.TESTS))
        self.assertEqual(plan.max_rounds, 30)
        self.assertEqual(plan.request_id, "req-1")

    def test_head_sha_is_compared_case_insensitively(self):
        run_dir = self.make(result={"base_sha": "A" * 40})
        self.assertTrue(self.fixture.inspect(run_dir, head="a" * 40).ok)
        self.assertTrue(self.fixture.inspect(run_dir, head="A" * 40).ok)

    def test_blank_run_dir_is_rejected(self):
        self.make()
        for text in ("", "   \n"):
            with self.subTest(text=text):
                plan = dcc.inspect_review_pending_run(text, self.fixture.repo, "main", ReviewRunFixture.HEAD)
                self.assertFalse(plan.ok)
                self.assertTrue(plan.message)

    def test_missing_result_json_is_rejected(self):
        run_dir = self.make()
        (run_dir / "result.json").unlink()
        self.assertFalse(self.fixture.inspect(run_dir).ok)

    def test_non_existing_run_dir_is_rejected(self):
        self.make()
        self.assertFalse(self.fixture.inspect(Path(self.temp.name) / "nope").ok)

    def test_result_json_that_is_not_json_is_rejected(self):
        run_dir = self.make()
        (run_dir / "result.json").write_text("{not json", encoding="utf-8")
        self.assertFalse(self.fixture.inspect(run_dir).ok)

    def test_result_json_that_is_not_an_object_is_rejected(self):
        run_dir = self.make()
        (run_dir / "result.json").write_text("[]", encoding="utf-8")
        self.assertFalse(self.fixture.inspect(run_dir).ok)

    def test_every_status_other_than_review_pending_is_rejected(self):
        for status in ("running", "stopped", "candidate_ready", "failed", ""):
            with self.subTest(status=status):
                plan = self.fixture.inspect(self.make(result={"status": status}))
                self.assertFalse(plan.ok)
                self.assertIn("review_pending", plan.message)

    def test_run_of_another_repo_is_rejected(self):
        run_dir = self.make(result={"repo": str(Path(self.temp.name) / "other-repo")})
        self.assertFalse(self.fixture.inspect(run_dir).ok)

    def test_run_of_another_branch_is_rejected(self):
        run_dir = self.make(result={"source_branch": "feature"})
        self.assertFalse(self.fixture.inspect(run_dir).ok)
        self.assertFalse(self.fixture.inspect(self.make(), branch="develop").ok)

    def test_base_sha_mismatch_with_local_head_is_rejected(self):
        run_dir = self.make(result={"base_sha": "b" * 40})
        self.assertFalse(self.fixture.inspect(run_dir).ok)

    def test_invalid_tests_are_rejected(self):
        for label, value in (
            ("missing", _MISSING),
            ("empty", []),
            ("string", "pytest"),
            ("non-string item", ["pytest", 3]),
            ("empty item", ["pytest", ""]),
        ):
            with self.subTest(tests=label):
                self.assertFalse(self.fixture.inspect(self.make(result={"tests": value})).ok)

    def test_invalid_max_rounds_are_rejected(self):
        for label, value in (("missing", _MISSING), ("string", "30"), ("bool", True), ("float", 30.5)):
            with self.subTest(max_rounds=label):
                self.assertFalse(self.fixture.inspect(self.make(result={"max_rounds": value})).ok)

    def test_zero_max_rounds_is_a_valid_saved_budget(self):
        plan = self.fixture.inspect(self.make(result={"max_rounds": 0}))
        self.assertTrue(plan.ok, plan.message)
        self.assertEqual(plan.max_rounds, 0)

    def test_missing_or_blank_task_is_rejected(self):
        self.assertFalse(self.fixture.inspect(self.make(write_task=False)).ok)
        self.assertFalse(self.fixture.inspect(self.make(task="  \n\n")).ok)

    def test_missing_request_or_request_id_is_rejected(self):
        self.assertFalse(self.fixture.inspect(self.make(write_request=False)).ok)
        self.assertFalse(self.fixture.inspect(self.make(request={"other": 1})).ok)
        self.assertFalse(self.fixture.inspect(self.make(request={"request_id": ""})).ok)
        self.assertFalse(self.fixture.inspect(self.make(request={"request_id": 7})).ok)

    def test_inspection_never_modifies_the_run(self):
        run_dir = self.make()
        before = {p.name: p.read_bytes() for p in run_dir.iterdir()}
        self.fixture.inspect(run_dir)
        self.assertEqual({p.name: p.read_bytes() for p in run_dir.iterdir()}, before)


class ParseReviewDecisionTests(unittest.TestCase):
    def decision(self, **overrides):
        body = {"request_id": "req-1", "verdict": "PASS", "summary": "looks good"}
        body.update(overrides)
        return body

    def test_all_three_verdicts_are_accepted_unchanged(self):
        for verdict in ("PASS", "FAIL", "PENDING"):
            with self.subTest(verdict=verdict):
                body = self.decision(verdict=verdict, extra="kept")
                parsed, error = dcc.parse_review_decision(json.dumps(body), "req-1")
                self.assertEqual(error, "")
                self.assertEqual(parsed, body)

    def test_rejections_return_no_decision_and_a_message(self):
        cases = {
            "empty": "",
            "whitespace": "  \n",
            "invalid json": "{not json",
            "array": "[]",
            "string": '"PASS"',
            "wrong request_id": json.dumps(self.decision(request_id="req-2")),
            "missing request_id": json.dumps({"verdict": "PASS", "summary": "ok"}),
            "lowercase verdict": json.dumps(self.decision(verdict="pass")),
            "unknown verdict": json.dumps(self.decision(verdict="OK")),
            "missing verdict": json.dumps({"request_id": "req-1", "summary": "ok"}),
            "empty summary": json.dumps(self.decision(summary="")),
            "blank summary": json.dumps(self.decision(summary="  ")),
            "non-string summary": json.dumps(self.decision(summary=5)),
            "missing summary": json.dumps({"request_id": "req-1", "verdict": "PASS"}),
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                parsed, error = dcc.parse_review_decision(text, "req-1")
                self.assertIsNone(parsed)
                self.assertTrue(error)


class BuildReviewResumeCommandTests(unittest.TestCase):
    def setUp(self):
        self.plan = dcc.ReviewResumePlan(
            True,
            "ok",
            run_dir=Path("C:/runs/20260924-120000-000000"),
            task="multi word task",
            tests=("python -m pytest tests/a.py", "python -m pytest tests/b.py"),
            max_rounds=12,
            request_id="req-1",
        )
        self.repo = Path("C:/repos/demo")
        self.result_path = Path("C:/tmp/result.json")
        self.decision_path = Path("C:/tmp/decision.json")
        self.command = dcc.build_review_resume_command(
            self.plan, self.repo, "main", self.result_path, self.decision_path
        )

    def test_command_targets_the_orchestrator_run_subcommand(self):
        self.assertEqual(self.command[0], sys.executable)
        self.assertEqual(
            Path(self.command[1]), dcc.DM_ROOT / "tools" / "ai_orchestrator" / "orchestrator.py"
        )
        self.assertEqual(self.command[2], "run")

    def test_command_carries_saved_task_tests_budget_and_resume_arguments(self):
        cmd = self.command
        self.assertEqual(cmd[cmd.index("--repo") + 1], str(self.repo))
        self.assertEqual(cmd[cmd.index("--expected-branch") + 1], "main")
        self.assertEqual(cmd[cmd.index("--task") + 1], "multi word task")
        tests = [cmd[i + 1] for i, item in enumerate(cmd) if item == "--test"]
        self.assertEqual(tests, list(self.plan.tests))
        self.assertEqual(cmd[cmd.index("--result-file") + 1], str(self.result_path))
        self.assertEqual(cmd[cmd.index("--max-rounds") + 1], "12")
        self.assertEqual(cmd[cmd.index("--resume-review") + 1], str(self.plan.run_dir))
        self.assertEqual(cmd[cmd.index("--final-review-decision") + 1], str(self.decision_path))
        self.assertNotIn("--no-fetch", cmd)

    def test_orchestrator_parser_accepts_the_command_and_sees_the_saved_values(self):
        args = o.build_parser().parse_args(self.command[2:])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.task, "multi word task")
        self.assertEqual(args.test, list(self.plan.tests))
        self.assertEqual(args.max_rounds, 12)
        self.assertEqual(args.resume_review, str(self.plan.run_dir))
        self.assertEqual(args.final_review_decision, str(self.decision_path))
        self.assertEqual(args.result_file, str(self.result_path))
        self.assertEqual(args.expected_branch, "main")


class SpawnAiProcessTests(unittest.TestCase):
    def test_child_uses_the_utf8_pipe_contract_and_hidden_window(self):
        with patch.object(dcc.subprocess, "Popen") as popen:
            process = dcc._spawn_ai_process(["python", "x.py"])
        self.assertIs(process, popen.return_value)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["python", "x.py"])
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["cwd"], dcc.DM_ROOT)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    unittest.main()
