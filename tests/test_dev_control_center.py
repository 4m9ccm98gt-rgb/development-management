from pathlib import Path
import tempfile
import unittest

from scripts.dev_control_center.core import (
    ControlCenterConfigError,
    active_repo_definitions,
    candidate_sha_is_valid,
    discover_entrypoints,
    parse_github_repo,
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


class ValidationTests(unittest.TestCase):
    def test_candidate_sha_validation(self):
        self.assertTrue(candidate_sha_is_valid("abcdef1"))
        self.assertTrue(candidate_sha_is_valid("a" * 40))
        self.assertFalse(candidate_sha_is_valid("xyz1234"))
        self.assertFalse(candidate_sha_is_valid("abc"))

    def test_https_remote_parsing(self):
        self.assertEqual(
            parse_github_repo("https://github.com/example/demo.git"),
            "example/demo",
        )


if __name__ == "__main__":
    unittest.main()
