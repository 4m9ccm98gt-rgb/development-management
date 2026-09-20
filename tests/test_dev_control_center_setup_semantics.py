from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupSemanticsTests(unittest.TestCase):
    def test_launcher_uses_setup_semantics(self):
        text = (ROOT / "DEV_CONTROL_CENTER.pyw").read_text(encoding="utf-8")
        self.assertIn("scripts.dev_control_center.app_setup", text)

    def test_windows_template_uses_current_sync_contract(self):
        cmd = (ROOT / "templates" / "windows-python-app" / "SYNC_CLICK_ME.cmd").read_text(encoding="utf-8")
        ps1 = (ROOT / "templates" / "windows-python-app" / "scripts" / "SYNC_CANDIDATE.ps1").read_text(encoding="utf-8")
        cmd_lines = [line.strip() for line in cmd.splitlines() if line.strip()]

        self.assertIn("<owner>/<repo>", cmd)
        self.assertIn("<candidate-branch>", cmd)
        self.assertIn("NO_PAUSE_ARG=-NoPause", cmd)
        self.assertTrue(cmd_lines[-1].endswith("& exit /b"))
        self.assertIn("[switch]$NoPause", ps1)
        self.assertIn("Expected SHA must be exactly 40 hexadecimal characters.", ps1)
        self.assertIn('Complete-Sync 0 "SYNC SUCCEEDED."', ps1)

    def test_central_bootstrap_sync_is_fail_closed(self):
        text = (ROOT / "scripts" / "BOOTSTRAP_REPO_SYNC.ps1").read_text(encoding="utf-8")

        self.assertIn("Expected SHA must be exactly 40 hexadecimal characters.", text)
        self.assertIn("Wrong repository.", text)
        self.assertIn("No automatic switch will be performed.", text)
        self.assertIn("Tracked working-tree changes exist. Nothing was changed.", text)
        self.assertIn("Refusing to rewrite local work.", text)
        self.assertIn('"merge", "--ff-only"', text)
        self.assertNotIn("reset --hard", text)
        self.assertNotIn("git stash", text)

    def test_setup_ui_has_one_time_bootstrap_sync_path(self):
        text = (ROOT / "scripts" / "dev_control_center" / "app_setup.py").read_text(encoding="utf-8")

        self.assertIn('self.entrypoints.sync.state == "MISSING"', text)
        self.assertIn('text="SYNC (初回)" if missing_sync else "SYNC"', text)
        self.assertIn("BOOTSTRAP_REPO_SYNC.ps1", text)
        self.assertIn("中央bootstrap SYNC", text)


if __name__ == "__main__":
    unittest.main()
