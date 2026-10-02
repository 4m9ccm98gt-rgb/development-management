"""git_env_isolation: the helper strips Orchestrator's push-blocking GIT_CONFIG_* overlay for
tests that create and push to their own temporary git repos, and restores it afterward."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from git_env_isolation import isolate_git_env, restore_git_config_env, strip_git_config_env
from tools.ai_orchestrator import providers


class StripGitConfigEnvTests(unittest.TestCase):
    def test_strip_removes_only_git_config_override_variables(self):
        patcher = mock.patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_PARAMETERS": "'x'",
            "GIT_CONFIG_KEY_0": "remote.origin.pushurl", "GIT_CONFIG_VALUE_0": "disabled://ai-orchestrator",
            "UNRELATED_VAR": "kept",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

        removed = strip_git_config_env()

        self.assertEqual(removed, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_PARAMETERS": "'x'",
                                    "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
                                    "GIT_CONFIG_VALUE_0": "disabled://ai-orchestrator"})
        for name in removed:
            self.assertNotIn(name, os.environ)
        self.assertEqual(os.environ["UNRELATED_VAR"], "kept")

    def test_restore_puts_removed_variables_back(self):
        patcher = mock.patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

        removed = strip_git_config_env()
        self.assertNotIn("GIT_CONFIG_COUNT", os.environ)

        restore_git_config_env(removed)
        self.assertEqual(os.environ["GIT_CONFIG_COUNT"], "1")


class IsolateGitEnvTests(unittest.TestCase):
    def test_isolate_strips_during_use_and_restores_after_cleanup(self):
        patcher = mock.patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
            "GIT_CONFIG_VALUE_0": "disabled://ai-orchestrator",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

        probe = unittest.TestCase()  # a bare TestCase just to host addCleanup/doCleanups
        isolate_git_env(probe)

        self.assertNotIn("GIT_CONFIG_COUNT", os.environ)
        self.assertNotIn("GIT_CONFIG_KEY_0", os.environ)
        self.assertNotIn("GIT_CONFIG_VALUE_0", os.environ)

        probe.doCleanups()

        self.assertEqual(os.environ["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(os.environ["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")
        self.assertEqual(os.environ["GIT_CONFIG_VALUE_0"], "disabled://ai-orchestrator")


class AgentEnvPushRegressionTest(unittest.TestCase):
    """Reproduces the bug this helper fixes: a worker environment built by agent_env() blocks
    `git push origin`, including a test's push to its own temporary origin."""

    def test_push_to_a_temporary_origin_succeeds_once_the_agent_env_overlay_is_isolated(self):
        overlay = {k: v for k, v in providers.agent_env().items() if k.startswith("GIT_CONFIG_")}
        self.assertTrue(overlay)  # guards against agent_env() silently dropping the push-block overlay
        patcher = mock.patch.dict(os.environ, overlay)
        patcher.start()
        self.addCleanup(patcher.stop)

        isolate_git_env(self)

        with tempfile.TemporaryDirectory(prefix="git-env-isolation ") as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            repo = root / "repo"
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
            (repo / "a.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "x"], check=True)
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(origin)], check=True)
            result = subprocess.run(["git", "-C", str(repo), "push", "origin", "main"],
                                    capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
