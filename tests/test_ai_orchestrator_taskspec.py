"""Fixed-format TaskSpec JSON: parsing, validation and the task-text "対象リポジトリ:" line.

Pure functions only; no git, no AI, no filesystem beyond a single temp spec file.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.ai_orchestrator.taskspec import SpecError, extract_target_repo_name, load_spec_file, parse_spec_text


class ParseSpecTests(unittest.TestCase):
    def test_ids_are_assigned_in_order_when_missing_and_kept_when_given(self):
        spec = parse_spec_text('{"schema_version": 1, "criteria": '
                                '[{"text": "a"}, {"id": "X9", "text": "b"}, {"text": "c"}]}')
        self.assertEqual([c["id"] for c in spec.criteria], ["C1", "X9", "C2"])
        self.assertEqual([c["text"] for c in spec.criteria], ["a", "b", "c"])
        self.assertIsNone(spec.target_repo)

    def test_explicit_id_colliding_with_a_later_auto_numbered_id_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": [{"id": "C1", "text": "a"}, {"text": "b"}]}')

    def test_explicit_id_colliding_with_an_earlier_auto_numbered_id_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": [{"text": "a"}, {"id": "C1", "text": "b"}]}')

    def test_schema_version_other_than_1_is_refused(self):
        for bad in ("2", '"1"', "true"):
            with self.subTest(bad=bad):
                with self.assertRaises(SpecError):
                    parse_spec_text('{"schema_version": %s, "criteria": [{"text": "a"}]}' % bad)

    def test_schema_version_1_is_accepted_and_omitted_defaults_to_1(self):
        spec = parse_spec_text('{"schema_version": 1, "criteria": [{"text": "a"}]}')
        self.assertEqual(len(spec.criteria), 1)
        spec = parse_spec_text('{"criteria": [{"text": "a"}]}')
        self.assertEqual(len(spec.criteria), 1)

    def test_target_repo_is_read_and_stripped(self):
        spec = parse_spec_text('{"criteria": [{"text": "a"}], "target_repo": "  development-management  "}')
        self.assertEqual(spec.target_repo, "development-management")

    def test_unknown_fields_are_ignored(self):
        spec = parse_spec_text('{"criteria": [{"text": "a"}], "unknown_field": 123}')
        self.assertEqual(len(spec.criteria), 1)

    def test_to_record_round_trips_as_plain_json_types(self):
        import json
        spec = parse_spec_text('{"criteria": [{"text": "a"}], "target_repo": "r"}')
        record = spec.to_record()
        self.assertEqual(json.loads(json.dumps(record)), record)

    def test_broken_json_is_refused_in_japanese(self):
        with self.assertRaises(SpecError) as ctx:
            parse_spec_text("{not json")
        self.assertEqual(ctx.exception.code, "SPEC_INVALID")
        self.assertIn("仕様ファイルが不正です", str(ctx.exception))

    def test_missing_criteria_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"target_repo": "r"}')

    def test_empty_criteria_array_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": []}')

    def test_more_than_twenty_criteria_is_refused(self):
        items = ",".join('{"text": "c%d"}' % i for i in range(21))
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": [%s]}' % items)

    def test_twenty_criteria_is_accepted(self):
        items = ",".join('{"text": "c%d"}' % i for i in range(20))
        spec = parse_spec_text('{"criteria": [%s]}' % items)
        self.assertEqual(len(spec.criteria), 20)

    def test_whitespace_only_text_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": [{"text": "   "}]}')

    def test_text_over_1000_chars_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": [{"text": "%s"}]}' % ("x" * 1001))

    def test_text_at_1000_chars_is_accepted(self):
        spec = parse_spec_text('{"criteria": [{"text": "%s"}]}' % ("x" * 1000))
        self.assertEqual(len(spec.criteria[0]["text"]), 1000)

    def test_duplicate_id_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": [{"id": "C1", "text": "a"}, {"id": "C1", "text": "b"}]}')

    def test_criteria_item_that_is_not_an_object_is_refused(self):
        with self.assertRaises(SpecError):
            parse_spec_text('{"criteria": ["just a string"]}')

    def test_load_spec_file_reads_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text('{"criteria": [{"text": "日本語の条件"}]}', encoding="utf-8")
            spec = load_spec_file(path)
            self.assertEqual(spec.criteria[0]["text"], "日本語の条件")

    def test_load_spec_file_missing_is_refused(self):
        with self.assertRaises(SpecError):
            load_spec_file(Path(tempfile.mkdtemp()) / "missing.json")

    def test_load_spec_file_invalid_utf8_is_refused_in_japanese(self):
        # A UnicodeDecodeError must become the same SpecError as any other unreadable file:
        # a raw exception here would reach the DCC start form uncaught (DCC Task 10).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_bytes(b"\xff\xfe\x00broken")
            with self.assertRaises(SpecError) as ctx:
                load_spec_file(path)
            self.assertIn("仕様ファイルを読み込めません", str(ctx.exception))


class ExtractTargetRepoNameTests(unittest.TestCase):
    def test_half_width_colon(self):
        self.assertEqual(extract_target_repo_name("対象リポジトリ: development-management\n次の行"), "development-management")

    def test_full_width_colon(self):
        self.assertEqual(extract_target_repo_name("対象リポジトリ：development-management"), "development-management")

    def test_trailing_bracket_note_is_stripped(self):
        self.assertEqual(extract_target_repo_name("対象リポジトリ: development-management（DCC）"),
                         "development-management")
        self.assertEqual(extract_target_repo_name("対象リポジトリ: development-management (DCC)"),
                         "development-management")

    def test_no_marker_line_returns_none(self):
        self.assertIsNone(extract_target_repo_name("ただの依頼文です。\n対象について特に書いていません。"))

    def test_marker_after_line_10_is_not_seen(self):
        lines = [f"line {i}" for i in range(10)] + ["対象リポジトリ: development-management"]
        self.assertIsNone(extract_target_repo_name("\n".join(lines)))

    def test_marker_within_first_10_lines_is_seen(self):
        lines = [f"line {i}" for i in range(9)] + ["対象リポジトリ: development-management"]
        self.assertEqual(extract_target_repo_name("\n".join(lines)), "development-management")

    def test_empty_name_after_marker_is_none(self):
        self.assertIsNone(extract_target_repo_name("対象リポジトリ: \n次の行"))


if __name__ == "__main__":
    unittest.main()
