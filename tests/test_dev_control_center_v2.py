from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.dev_control_center.core import (
    RemoteRepo,
    RepoDefinition,
    build_new_repo_setup_prompt,
    build_startup_prompt,
    list_github_repositories,
    summarize_ci_state,
    unmanaged_github_repositories,
)

ROOT = Path(__file__).resolve().parents[1]


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

    def test_no_checks_is_not_candidate_green(self):
        state, count = summarize_ci_state(
            {"check_runs": []},
            {"total_count": 0, "state": ""},
        )
        self.assertEqual(state, "NO CHECKS")
        self.assertEqual(count, 0)


class PromptTests(unittest.TestCase):
    def test_startup_set_keeps_stage_boundaries(self):
        text = build_startup_prompt(RepoDefinition("demo", "desktop", "main", owner="example"))
        self.assertIn("example/demo", text)
        self.assertIn("candidate branch: main", text)
        self.assertIn("③SYNC", text)
        self.assertIn("CI green", text)

    def test_new_repo_setup_requests_central_registration(self):
        remote = RemoteRepo("new-app", default_branch="main", owner="example")
        text = build_new_repo_setup_prompt(remote, Path(r"C:\repos\new-app"))
        self.assertIn("scripts/repo_types.toml", text)
        self.assertIn("scripts/dev_control_center_repos.toml", text)
        self.assertIn("READY / N/A / MISSING", text)


class SelfUpdateContractTests(unittest.TestCase):
    def test_sync_wrapper_supports_noninteractive_control_center_call(self):
        text = (ROOT / "SYNC_CLICK_ME.cmd").read_text(encoding="utf-8")
        self.assertIn("--no-pause", text)
        self.assertIn("if not defined NO_PAUSE pause", text)


if __name__ == "__main__":
    unittest.main()
