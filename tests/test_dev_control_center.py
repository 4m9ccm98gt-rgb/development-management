from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
    build_debug_handoff_prompt,
    build_new_repo_setup_prompt,
    build_startup_prompt,
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

    def test_initial_ai_task_and_test_are_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            types = root / "types.toml"
            branches = root / "branches.toml"
            types.write_text('[types]\napp = "desktop"\n', encoding="utf-8")
            branches.write_text(
                '[branches]\n'
                'app = "main"\n\n'
                '[initial_ai_tasks]\n'
                'app = "Build a minimal demo"\n\n'
                '[initial_tests]\n'
                'app = "python -m unittest discover -s tests -v"\n',
                encoding="utf-8",
            )
            item = active_repo_definitions(types, branches, owner="example")[0]
            self.assertEqual(item.initial_ai_task, "Build a minimal demo")
            self.assertEqual(
                item.initial_test_command,
                "python -m unittest discover -s tests -v",
            )

    def test_management_and_shizen_are_active_registry_entries(self):
        items = {
            item.name: item
            for item in active_repo_definitions(
                ROOT / "scripts" / "repo_types.toml",
                ROOT / "scripts" / "dev_control_center_repos.toml",
            )
        }
        self.assertIn("development-management", items)
        self.assertEqual(items["development-management"].repo_type, "management")
        self.assertEqual(items["development-management"].branch, "main")
        self.assertIn("unittest discover", items["development-management"].initial_test_command)
        self.assertIn("shizen-launcher", items)
        self.assertEqual(items["shizen-launcher"].repo_type, "desktop")
        self.assertIn("PySide6", items["shizen-launcher"].initial_ai_task)
        self.assertIn("RUN_DEV.cmd", items["shizen-launcher"].initial_ai_task)

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

    def test_management_uses_run_and_skips_app_distribution_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SYNC_CLICK_ME.cmd").write_text("test", encoding="utf-8")
            (root / "RUN_DEV.cmd").write_text("test", encoding="utf-8")
            found = discover_entrypoints(root, "management")
            self.assertTrue(found.sync.ready)
            self.assertTrue(found.run.ready)
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
    def test_startup_handoff_uses_unified_orchestrator_route(self):
        text = build_startup_prompt(RepoDefinition("demo", "desktop", "main", owner="example"))
        self.assertIn("OPERATING_CONTRACT.md", text)
        self.assertIn("Claude", text)
        self.assertIn("GPT-6 Astra", text)
        self.assertIn("ChatGPTは実装担当にならず", text)
        self.assertIn("development-management自身も同じルート", text)
        self.assertNotIn("A — ChatGPT fast path", text)
        self.assertNotIn("T0", text)

    def test_debug_handoff_uses_b_path_and_local_candidate(self):
        text = build_debug_handoff_prompt(
            RepoDefinition("demo", "desktop", "main", owner="example"),
            Path(r"C:\repos\demo"),
            "b" * 40,
        )
        self.assertIn("B — Debug escape path", text)
        self.assertIn("b" * 40, text)
        self.assertIn("fast-forward push", text)

    def test_new_repo_setup_requests_central_registration_and_ai_handoff(self):
        remote = RemoteRepo("new-app", default_branch="main", owner="example")
        text = build_new_repo_setup_prompt(remote, Path(r"C:\repos\new-app"))
        self.assertIn("scripts/repo_types.toml", text)
        self.assertIn("scripts/dev_control_center_repos.toml", text)
        self.assertIn("[initial_ai_tasks]", text)
        self.assertIn("[initial_tests]", text)
        self.assertIn("Claude", text)
        self.assertIn("対象アプリ本体を実装・修正・検証しません", text)
        self.assertNotIn("A — ChatGPT fast path", text)


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
        self.assertIn('text="AI開発 — Claude実装 → Tests → Astraレビュー → local candidate"', build)
        self.assertIn('self.ai_task = tk.Text(ai_box, height=8, wrap="word")', build)
        self.assertIn('text="Managed Repositories"', build)
        self.assertIn('text="全状態更新"', build)
        self.assertIn('text="実機確認・配布"', build)
        self.assertNotIn('text="A: ChatGPT', build)
        self.assertNotIn('text="Bデバッグ指示"', build)
        self.assertNotIn('text="GitHub更新"', build)
        self.assertNotIn('text="STARTUP SET"', build)
        self.assertNotIn('self.sync_button.grid(', build)

    def test_gui_prefills_registered_initial_ai_task(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        select_start = text.index("    def _select_repo(self) -> None:")
        refresh_start = text.index("    def refresh_all(self) -> None:", select_start)
        select = text[select_start:refresh_start]
        self.assertIn("self.current.initial_ai_task", select)
        self.assertIn("self.current.initial_test_command", select)

    def test_gui_exposes_ai_orchestrator_with_machine_result_handoff(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def launch_ai_orchestrator", text)
        self.assertIn('"--result-file"', text)
        self.assertIn("apply_local_candidate(", text)
        self.assertIn("Claude実装 → Tests → Astraレビュー", text)
        self.assertIn("push / BUILD / UPDATEは行いません", text)

    def test_every_finished_action_refreshes_local_and_github_state(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
        poll_start = text.index("    def _poll(self) -> None:")
        state_start = text.index("    def _set_button_states(self) -> None:", poll_start)
        poll = text[poll_start:state_start]
        self.assertIn("self.refresh()", poll)
        self.assertIn("self.refresh_github()", poll)
        self.assertNotIn('if action == "sync"', poll)


class DocumentationRouteContractTests(unittest.TestCase):
    def test_entry_docs_use_unified_orchestrator_route(self):
        for name in ("OPERATING_CONTRACT.md", "AGENTS.md", "AI_STARTUP.md", "AI_OPERATING_MANUAL.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("Claude", text)
                self.assertIn("Astra", text)
                self.assertNotIn("ChatGPTがGitHub上で実装", text)
                self.assertNotIn("Codex + Claude", text)
                self.assertNotIn("Codexレビュー + Claudeレビュー", text)

    def test_development_has_formal_run_dev_entrypoint(self):
        text = (ROOT / "RUN_DEV.cmd").read_text(encoding="ascii")
        self.assertIn("DEV_CONTROL_CENTER.pyw", text)
        self.assertTrue(text.rstrip().endswith("exit /b"))


class SelfUpdateContractTests(unittest.TestCase):
    def test_sync_wrapper_supports_noninteractive_control_center_call(self):
        text = (ROOT / "SYNC_CLICK_ME.cmd").read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertIn("--no-pause", text)
        self.assertIn("NO_PAUSE_ARG=-NoPause", text)
        self.assertTrue(lines[-1].endswith("& exit /b"))


if __name__ == "__main__":
    unittest.main()
