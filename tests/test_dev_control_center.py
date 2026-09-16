from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev_control_center.core import (
    ControlCenterConfigError,
    GitHubState,
    RemoteRepo,
    RepoDefinition,
    active_repo_definitions,
    build_debug_handoff_prompt,
    build_new_repo_setup_prompt,
    build_startup_prompt,
    candidate_sha_is_valid,
    discover_entrypoints,
    list_github_repositories,
    parse_github_repo,
    summarize_ci_state,
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

    def test_open_pr_blocks_auto_candidate(self):
        state = GitHubState(
            branch_sha="a" * 40,
            ci_state="GREEN",
            candidate_blocked_by_pr=True,
        )
        self.assertFalse(state.candidate_ready)


class PromptTests(unittest.TestCase):
    def test_startup_set_uses_a_path_without_old_tiers(self):
        text = build_startup_prompt(RepoDefinition("demo", "desktop", "main", owner="example"))
        self.assertIn("A — ChatGPT fast path", text)
        self.assertIn("OPERATING_CONTRACT.md", text)
        self.assertIn("完全40桁candidate SHA", text)
        self.assertNotIn("T0", text)
        self.assertNotIn("CI green", text)

    def test_debug_handoff_uses_b_path_and_local_candidate(self):
        text = build_debug_handoff_prompt(
            RepoDefinition("demo", "desktop", "main", owner="example"),
            Path(r"C:\repos\demo"),
            "b" * 40,
        )
        self.assertIn("B — Debug escape path", text)
        self.assertIn("b" * 40, text)
        self.assertIn("fast-forward push", text)

    def test_new_repo_setup_requests_central_registration(self):
        remote = RemoteRepo("new-app", default_branch="main", owner="example")
        text = build_new_repo_setup_prompt(remote, Path(r"C:\repos\new-app"))
        self.assertIn("scripts/repo_types.toml", text)
        self.assertIn("scripts/dev_control_center_repos.toml", text)
        self.assertIn("A — ChatGPT fast path", text)


class SelfUpdateContractTests(unittest.TestCase):
    def test_sync_wrapper_supports_noninteractive_control_center_call(self):
        text = (ROOT / "SYNC_CLICK_ME.cmd").read_text(encoding="utf-8")
        self.assertIn("--no-pause", text)
        self.assertIn("if not defined NO_PAUSE pause", text)


if __name__ == "__main__":
    unittest.main()
