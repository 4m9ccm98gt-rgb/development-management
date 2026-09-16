from pathlib import Path
import tempfile
import unittest

from scripts.dev_control_center.core import discover_entrypoints, parse_github_repo


class LifecycleSetupTests(unittest.TestCase):
    def test_origin_hostname_cannot_be_spoofed(self):
        self.assertEqual(parse_github_repo('https://evilgithub.com/example/app.git'), '')
        self.assertEqual(parse_github_repo('https://example.invalid/github.com/example/app.git'), '')

    def test_unimplemented_app_remains_missing_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = discover_entrypoints(Path(tmp), 'desktop', application_implemented=False)
            self.assertEqual(result.run.state, 'MISSING')
            self.assertEqual(result.build.state, 'N/A')
            self.assertEqual(result.release.state, 'N/A')

    def test_existing_update_and_deploy_names_are_reused(self):
        for kind, name in [('desktop', 'UPDATE.cmd'), ('web', 'DEPLOY.cmd')]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / name).write_text('@echo off')
                result = discover_entrypoints(root, kind)
                self.assertEqual(result.release.state, 'READY')
                self.assertEqual(result.release.path.name, name)

    def test_source_services_do_not_require_binary_builds(self):
        for kind in ['web', 'service']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.assertEqual(discover_entrypoints(root, kind).build.state, 'N/A')
                (root / 'BUILD_EXE_CLICK_ME.cmd').touch()
                self.assertEqual(discover_entrypoints(root, kind).build.state, 'READY')

    def test_missing_and_ambiguous_lifecycles_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = discover_entrypoints(root, 'desktop')
            for action in ['sync', 'run', 'build', 'release']:
                self.assertEqual(getattr(result, action).state, 'MISSING')
            for folder in ['one', 'two']:
                (root / folder).mkdir()
                for name in ['SYNC_CLICK_ME.cmd', 'RUN_DEV.cmd', 'BUILD_EXE_CLICK_ME.cmd', 'UPDATE.cmd']:
                    (root / folder / name).touch()
            result = discover_entrypoints(root, 'desktop')
            for action in ['sync', 'run', 'build', 'release']:
                self.assertEqual(getattr(result, action).state, 'MULTIPLE')


if __name__ == '__main__':
    unittest.main()
