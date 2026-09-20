"""Regression tests: the only development entry is the DCC AI request field."""

from pathlib import Path
import unittest

from scripts.dev_control_center.core import active_repo_definitions

ROOT = Path(__file__).resolve().parents[1]

ENTRY_DOCS = (
    "OPERATING_CONTRACT.md",
    "README.md",
    "AGENTS.md",
    "AI_STARTUP.md",
    "AI_OPERATING_MANUAL.md",
    "AI_CHECKLIST.md",
    "STARTUP_HANDOFF_POLICY.md",
)
CODE_FILES = (
    "scripts/dev_control_center/app.py",
    "scripts/dev_control_center/app_setup.py",
    "scripts/dev_control_center/core.py",
    "tools/ai_orchestrator/orchestrator.py",
)
REVIVED_ROUTE_MARKERS = (
    "STARTUP SET",
    "startup_set",
    "startup_prompt",
    "debug_handoff",
    "build_setup_prompt",
    "A-path",
    "B-path",
    "B-debug",
    "A — ChatGPT",
    "B — Debug",
    "Debug escape",
    "fast path",
    "Bデバッグ",
    "ChatGPTがGitHub上で実装",
    "ChatGPT実装",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class SingleRouteTests(unittest.TestCase):
    def test_old_routes_are_absent_from_code_and_entry_docs(self):
        for rel in (*CODE_FILES, *ENTRY_DOCS):
            text = _read(rel)
            for marker in REVIVED_ROUTE_MARKERS:
                self.assertNotIn(marker, text, f"{rel} revives old route: {marker}")

    def test_contract_defines_single_route_and_docs_defer_to_it(self):
        contract = _read("OPERATING_CONTRACT.md")
        for phrase in ("AI依頼", "Claude", "GPT-6 Astra", "local candidate", "セットアップ開始"):
            self.assertIn(phrase, contract)
        for rel in ENTRY_DOCS[1:]:
            self.assertIn("OPERATING_CONTRACT.md", _read(rel), rel)

    def test_development_management_and_shizen_launcher_are_managed(self):
        items = {
            d.name: d
            for d in active_repo_definitions(
                ROOT / "scripts" / "repo_types.toml",
                ROOT / "scripts" / "dev_control_center_repos.toml",
            )
        }
        for name in ("development-management", "shizen-launcher"):
            self.assertIn(name, items)
            self.assertEqual(items[name].branch, "main")
            self.assertTrue(items[name].initial_ai_task)
            self.assertTrue(items[name].initial_test)
        self.assertIn("PySide6", items["shizen-launcher"].initial_ai_task)
        self.assertEqual(items["development-management"].repo_type, "management")

    def test_development_management_has_formal_run_dev_entry(self):
        run_dev = (ROOT / "RUN_DEV.cmd").read_text(encoding="ascii")
        self.assertIn("DEV_CONTROL_CENTER.pyw", run_dev)

    def test_new_repo_setup_targets_development_management_ai_field(self):
        text = _read("scripts/dev_control_center/app.py")
        self.assertIn("_start_new_repo_registration", text)
        self.assertIn('item.name == "development-management"', text)
        self.assertIn("initial_ai_task", text)
        self.assertIn("initial_test", text)
        self.assertNotIn("_copy_to_clipboard(build_new_repo_setup_prompt", text)


if __name__ == "__main__":
    unittest.main()
