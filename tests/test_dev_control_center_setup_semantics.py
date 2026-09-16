from pathlib import Path
import unittest

from scripts.dev_control_center.app_setup import build_setup_prompt
from scripts.dev_control_center.core import EntryPointChoice, RepoDefinition, RepoEntrypoints

ROOT = Path(__file__).resolve().parents[1]


class SetupSemanticsTests(unittest.TestCase):
    def test_setup_prompt_reports_detected_lifecycle_gaps(self):
        definition = RepoDefinition("next-day-setup", "desktop", "main")
        entrypoints = RepoEntrypoints(
            sync=EntryPointChoice("MISSING"),
            run=EntryPointChoice("READY", Path("RUN_DEV.cmd")),
            build=EntryPointChoice("READY", Path("BUILD_EXE_CLICK_ME.cmd")),
            release=EntryPointChoice("READY", Path("UPDATE_SHARED_FOLDER.cmd")),
            release_label="UPDATE",
        )

        text = build_setup_prompt(definition, entrypoints)

        self.assertIn("標準ライフサイクルへSETUP", text)
        self.assertIn("PROJECT_BOOTSTRAP.md", text)
        self.assertIn("- SYNC: MISSING", text)
        self.assertIn("- RUN_DEV: READY", text)
        self.assertIn("- BUILD: READY", text)
        self.assertIn("- UPDATE: READY", text)
        self.assertIn("READYの正式入口は原則作り直さず", text)
        self.assertIn("SYNC_CLICK_ME.cmd", text)
        self.assertIn("完全40桁candidate SHA", text)
        self.assertNotIn("このあと私が変更内容を指示します", text)

    def test_launcher_uses_setup_semantics(self):
        text = (ROOT / "DEV_CONTROL_CENTER.pyw").read_text(encoding="utf-8")
        self.assertIn("scripts.dev_control_center.app_setup", text)


if __name__ == "__main__":
    unittest.main()
