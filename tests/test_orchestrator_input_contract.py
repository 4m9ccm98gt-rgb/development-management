"""docs/orchestrator_input_contract.md must stay true to the Orchestrator's real input parsing.

The contract is what GPT / Claude / Codex read instead of the Orchestrator source, so its
worked example, its JSON spec example, its repo table and its limits are run through the same
functions DCC and prepare_run use. If the parsing changes, these tests fail until the contract
document is updated with it.
"""

from pathlib import Path
import json
import re
import unittest

from scripts.dev_control_center.core import active_repo_definitions
from tools.ai_orchestrator import review, taskspec

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "orchestrator_input_contract.md"


def _contract() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _section(text: str, heading_prefix: str) -> str:
    """From the line starting with heading_prefix up to the next "## " heading that is not
    inside a ``` fenced block (the worked example itself contains "## " headings)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading_prefix))
    fence = None
    for end in range(start + 1, len(lines)):
        line = lines[end]
        marker = re.match(r"^(`{3,})", line)
        if marker:
            if fence is None:
                fence = marker.group(1)
            elif line.strip() == fence:
                fence = None
            continue
        if fence is None and line.startswith("## "):
            return "\n".join(lines[start:end]) + "\n"
    return "\n".join(lines[start:]) + "\n"


def _fenced(section: str, lang: str) -> str:
    match = re.search(r"^```" + lang + r"\n(.*?)^```\s*$", section, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"no ```{lang} block found")
    return match.group(1)


def _registry():
    return {d.name: d for d in active_repo_definitions(
        ROOT / "scripts" / "repo_types.toml", ROOT / "scripts" / "dev_control_center_repos.toml")}


class WorkedExampleTests(unittest.TestCase):
    def setUp(self):
        self.example = _fenced(_section(_contract(), "## 6. 完成例"), "text")

    def test_target_repo_line_resolves_to_a_registered_repo(self):
        name = taskspec.extract_target_repo_name(self.example)
        self.assertIsNotNone(name)
        self.assertIn(name, _registry())

    def test_acceptance_bullets_become_fixed_criteria_exactly(self):
        block = review.extract_acceptance(self.example)
        criteria = review.criteria_from_acceptance(block)
        bullets = [line[2:].strip() for line in _section(self.example, "## 受入条件").splitlines()
                   if line.startswith("- ")]
        self.assertTrue(bullets)
        self.assertEqual([c["text"] for c in criteria], bullets)
        self.assertEqual([c["id"] for c in criteria], [f"C{i}" for i in range(1, len(bullets) + 1)])

    def test_acceptance_word_appears_only_in_its_heading(self):
        hits = [line for line in self.example.splitlines()
                if re.search(r"受入条件|受け入れ条件|acceptance", line, re.IGNORECASE)]
        self.assertEqual(hits, ["## 受入条件"])

    def test_example_does_not_ask_the_main_ai_to_commit_or_push(self):
        for word in ("commit", "push", "コミット", "プッシュ", "BUILD", "UPDATE"):
            self.assertNotIn(word, self.example)


class SpecExampleTests(unittest.TestCase):
    def test_json_example_is_a_valid_spec(self):
        spec = taskspec.parse_spec_text(_fenced(_section(_contract(), "## 4. 仕様ファイル"), "json"))
        self.assertIn(spec.target_repo, _registry())
        self.assertTrue(spec.criteria)

    def test_documented_limits_match_the_code(self):
        text = _section(_contract(), "## 4. 仕様ファイル")
        self.assertIn(f"1〜{taskspec.MAX_SPEC_CRITERIA}件", text)
        self.assertIn(f"{taskspec.MAX_CRITERION_CHARS}文字", text)
        self.assertIn(f"{review.MAX_CRITERIA}件まで", _section(_contract(), "## 2. Task本文の書式"))

    def test_mixed_explicit_and_auto_ids_can_collide_as_documented(self):
        bad = json.dumps({"criteria": [{"id": "C1", "text": "a"}, {"text": "b"}]})
        with self.assertRaises(taskspec.SpecError):
            taskspec.parse_spec_text(bad)


class RepoTableTests(unittest.TestCase):
    def test_repo_table_lists_exactly_the_selectable_repos_with_their_default_tests(self):
        table = _section(_contract(), "### 選べるrepo名と既定のTests")
        rows = {}
        for line in table.splitlines():
            m = re.match(r"^\| ([a-z0-9-]+) \| (.+) \|$", line)
            if m:
                rows[m.group(1)] = m.group(2).strip()
        registry = _registry()
        self.assertEqual(set(rows), set(registry))
        for name, definition in registry.items():
            if definition.initial_test:
                self.assertEqual(rows[name], f"`{definition.initial_test}`", name)
            else:
                self.assertTrue(rows[name].startswith("なし"), name)


if __name__ == "__main__":
    unittest.main()
