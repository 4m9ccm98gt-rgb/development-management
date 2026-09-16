from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SyncWrapperContractTests(unittest.TestCase):
    def test_cmd_stops_reading_after_mutable_sync_returns(self):
        text = (ROOT / "SYNC_CLICK_ME.cmd").read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertIn("NO_PAUSE_ARG=-NoPause", text)
        self.assertTrue(lines[-1].endswith("& exit /b"))
        self.assertNotIn("SYNC SUCCEEDED.", text)
        self.assertNotIn("SYNC STOPPED.", text)

    def test_powershell_owns_pause_and_completion_status(self):
        text = (ROOT / "scripts" / "SYNC_CANDIDATE.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$NoPause", text)
        self.assertIn('Complete-Sync 0 "SYNC SUCCEEDED."', text)
        self.assertIn('Complete-Sync 1 "SYNC STOPPED."', text)
        self.assertIn("if (-not $NoPause)", text)
        self.assertIn("Expected SHA must be exactly 40 hexadecimal characters.", text)


if __name__ == "__main__":
    unittest.main()
