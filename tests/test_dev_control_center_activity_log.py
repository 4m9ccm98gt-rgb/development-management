"""DCC Task WF-6a: the shared activity record (scripts/dev_control_center/activity_log.py).

Every test here uses only tempfile.TemporaryDirectory() paths -- never the real %LOCALAPPDATA%,
no real screen, AI, Orchestrator, or network of any kind.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev_control_center import activity_log

# A real caller never hands append() a bare "x" -- every current site hashes its own identifier
# first (reports_auto._hash / reports_auto_start._hash, both sha256 hex digests). These tests use
# the same shape so target_id validation is exercised the way production code actually calls it.
_REPORT_ID = hashlib.sha256(b"report-1").hexdigest()
_REPORT_ID_2 = hashlib.sha256(b"report-2").hexdigest()


class AppendAndReadTests(unittest.TestCase):
    def test_append_then_read_recent_round_trips_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                 target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)
            activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_COMPLETE,
                                 target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID,
                                 result=activity_log.RESULT_PROCEED, path=path)
            entries = activity_log.read_recent(path=path)
            self.assertEqual(len(entries), 2)
            # newest first
            self.assertEqual(entries[0].action, activity_log.ACTION_COMPLETE)
            self.assertEqual(entries[0].result, activity_log.RESULT_PROCEED)
            self.assertEqual(entries[1].action, activity_log.ACTION_START)
            for entry in entries:
                self.assertEqual(entry.role, activity_log.ROLE_AUTO_TRIAGE)
                self.assertEqual(entry.target_type, activity_log.TARGET_REPORT)
                self.assertEqual(entry.target_id, _REPORT_ID)
                self.assertTrue(entry.timestamp)

    def test_missing_file_reads_as_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no-such-file.jsonl"
            self.assertEqual(activity_log.read_recent(path=path), [])

    def test_entry_contains_only_fixed_words_id_and_timestamp(self):
        """C1: every field written to disk is either a fixed word from this module's own
        vocabulary, the caller's own ID, or a timestamp -- never report/Task/AI free text, a
        path, or exception text."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            activity_log.append(
                role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_FAIL,
                target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID,
                result=activity_log.RESULT_FAILED, reason=activity_log.REASON_TIMEOUT, path=path,
            )
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw.strip())
            self.assertEqual(set(data.keys()), {"timestamp", "role", "action", "target_type",
                                                  "target_id", "result", "reason"})
            self.assertEqual(data["role"], activity_log.ROLE_AUTO_TRIAGE)
            self.assertEqual(data["action"], activity_log.ACTION_FAIL)
            self.assertEqual(data["target_type"], activity_log.TARGET_REPORT)
            self.assertEqual(data["target_id"], _REPORT_ID)
            self.assertEqual(data["result"], activity_log.RESULT_FAILED)
            self.assertEqual(data["reason"], activity_log.REASON_TIMEOUT)
            # Never a report body, AI free text, a path, or exception text anywhere in the file.
            for banned in ("C:\\", "/home/", "Traceback", "report body", "本文"):
                self.assertNotIn(banned, raw)

    def test_keeps_only_most_recent_500_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            for i in range(activity_log.MAX_ENTRIES + 10):
                run_id = f"20260101-000000-{i:06d}"
                activity_log.append(role=activity_log.ROLE_AUTO_START, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_RUN, target_id=run_id, path=path)
            entries = activity_log.read_recent(limit=activity_log.MAX_ENTRIES + 100, path=path)
            self.assertEqual(len(entries), activity_log.MAX_ENTRIES)
            # Newest-first: the most recently appended id is first, the oldest surviving id is last.
            self.assertEqual(entries[0].target_id, f"20260101-000000-{activity_log.MAX_ENTRIES + 9:06d}")
            self.assertEqual(entries[-1].target_id, f"20260101-000000-{10:06d}")

    def test_rejects_role_outside_fixed_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role="not-a-real-role", action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)
            self.assertEqual(activity_log.read_recent(path=path), [])

    def test_rejects_action_outside_fixed_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action="not-a-real-action",
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)

    def test_rejects_result_outside_fixed_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_COMPLETE,
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID,
                                     result="free text result", path=path)

    def test_rejects_reason_outside_fixed_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_FAIL,
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID,
                                     reason="the AI said something unexpected here", path=path)


class TargetIdValidationTests(unittest.TestCase):
    """C1: target_id must match the one fixed shape each TARGET_TYPES member allows -- never a
    path, free text, or control characters, regardless of length."""

    def test_rejects_a_filesystem_path_as_a_report_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT,
                                     target_id="C:\\private\\secret.txt", path=path)
            self.assertEqual(activity_log.read_recent(path=path), [])

    def test_rejects_free_text_as_a_report_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT,
                                     target_id="this is the report body text", path=path)

    def test_rejects_control_characters_in_a_report_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT,
                                     target_id=_REPORT_ID[:-1] + "\n", path=path)

    def test_rejects_a_report_id_used_as_a_run_id(self):
        """Each TARGET_TYPES member has its own id shape -- a valid id for one target type must
        not be accepted for another."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_START, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_RUN, target_id=_REPORT_ID, path=path)

    def test_rejects_a_non_empty_id_for_target_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_EXCLUDED,
                                     target_type=activity_log.TARGET_NONE, target_id="anything", path=path)

    def test_accepts_a_well_formed_plan_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            activity_log.append(role=activity_log.ROLE_AUTO_PLAN, action=activity_log.ACTION_START,
                                 target_type=activity_log.TARGET_PLAN_TASK, target_id="plan-1:task-1",
                                 path=path)
            entries = activity_log.read_recent(path=path)
            self.assertEqual(entries[0].target_id, "plan-1:task-1")

    def test_rejects_a_malicious_id_mixed_into_an_otherwise_valid_batch(self):
        """A run with several reports, some legitimate, one carrying a path instead of a hash,
        must fail on the one bad entry rather than silently accepting it."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                 target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT,
                                     target_id="../../etc/passwd", path=path)
            entries = activity_log.read_recent(path=path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].target_id, _REPORT_ID)


class BrokenRecordTests(unittest.TestCase):
    """C2: an unreadable/corrupt record must raise, never silently degrade to an empty read."""

    def test_read_recent_raises_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            path.write_text("not json at all{{{\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_on_valid_json_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            path.write_text(json.dumps({"timestamp": "2026-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_when_file_is_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            path.mkdir()
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_on_invalid_utf8_bytes(self):
        """Reviewer finding 1: a file that cannot even be decoded must still raise
        ActivityLogError, not an uncaught UnicodeDecodeError."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            path.write_bytes(b"\xff\xfe\x00not valid utf-8\x80\x81\n")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_on_an_extra_unknown_field(self):
        """Reviewer finding 2: an unknown field (e.g. a smuggled report body) must be rejected,
        never silently accepted alongside the known ones."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            record = {
                "timestamp": "2026-01-01T00:00:00Z", "role": activity_log.ROLE_AUTO_TRIAGE,
                "action": activity_log.ACTION_START, "target_type": activity_log.TARGET_REPORT,
                "target_id": _REPORT_ID, "result": activity_log.RESULT_NONE,
                "reason": activity_log.REASON_NONE, "body": "the report's free text body",
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_on_a_non_string_field_type(self):
        """Reviewer finding 2: a field of the wrong JSON type must not be coerced with str() --
        it must be rejected outright."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            record = {
                "timestamp": "2026-01-01T00:00:00Z", "role": activity_log.ROLE_AUTO_TRIAGE,
                "action": activity_log.ACTION_START, "target_type": activity_log.TARGET_REPORT,
                "target_id": _REPORT_ID, "result": activity_log.RESULT_NONE,
                "reason": ["not", "a", "string"],
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_on_a_malformed_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            record = {
                "timestamp": "not-a-timestamp", "role": activity_log.ROLE_AUTO_TRIAGE,
                "action": activity_log.ACTION_START, "target_type": activity_log.TARGET_REPORT,
                "target_id": _REPORT_ID, "result": activity_log.RESULT_NONE,
                "reason": activity_log.REASON_NONE,
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_read_recent_raises_on_a_path_smuggled_in_as_a_report_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            record = {
                "timestamp": "2026-01-01T00:00:00Z", "role": activity_log.ROLE_AUTO_TRIAGE,
                "action": activity_log.ACTION_START, "target_type": activity_log.TARGET_REPORT,
                "target_id": "C:\\Users\\me\\secret.txt", "result": activity_log.RESULT_NONE,
                "reason": activity_log.REASON_NONE,
            }
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_append_raises_rather_than_overwrite_a_corrupt_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            path.write_text("garbage\n", encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)
            # The corrupt file must still be there, unreplaced by a single fresh entry.
            self.assertEqual(path.read_text(encoding="utf-8"), "garbage\n")

    def test_append_raises_when_the_existing_file_is_not_valid_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            path.write_bytes(b"\xff\xfe\x00garbage\x80\x81\n")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)

    def test_read_recent_raises_on_deeply_nested_json_instead_of_recursion_error(self):
        """Reviewer finding (repair 2): a line so deeply nested that json.loads itself raises
        RecursionError must still surface as the module's own fixed ActivityLogError, not an
        uncaught RecursionError that would crash whatever automatic process is reading."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            deeply_nested = "[" * 100000 + "]" * 100000 + "\n"
            path.write_text(deeply_nested, encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.read_recent(path=path)

    def test_append_raises_on_deeply_nested_existing_line_instead_of_recursion_error(self):
        """Same as above, but on the re-read append() does of its own existing file before it
        appends the new entry (the path the reviewer traced into reports_auto/_log_activity)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            deeply_nested = "[" * 100000 + "]" * 100000 + "\n"
            path.write_text(deeply_nested, encoding="utf-8")
            with self.assertRaises(activity_log.ActivityLogError):
                activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                     target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID, path=path)
            # The corrupt file must still be there, unreplaced.
            self.assertEqual(path.read_text(encoding="utf-8"), deeply_nested)

    def test_read_recent_raises_activity_log_error_when_exists_raises_os_error(self):
        """Reviewer finding (repair 2): Path.exists() itself can raise OSError/PermissionError
        (e.g. a locked parent directory on Windows); read_recent must convert that to
        ActivityLogError too, not leak the raw OSError."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with mock.patch.object(Path, "exists", side_effect=PermissionError("denied")):
                with self.assertRaises(activity_log.ActivityLogError):
                    activity_log.read_recent(path=path)


class RealIoFailureTests(unittest.TestCase):
    """Reviewer finding 1: real I/O failures (directory creation, atomic replace) must convert to
    ActivityLogError, not leak a raw OSError/PermissionError to the caller."""

    def test_append_raises_activity_log_error_when_the_directory_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "activity.jsonl"
            with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
                with self.assertRaises(activity_log.ActivityLogError):
                    activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                         target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID,
                                         path=path)
            self.assertFalse(path.exists())

    def test_append_raises_activity_log_error_when_the_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.jsonl"
            with mock.patch.object(os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(activity_log.ActivityLogError):
                    activity_log.append(role=activity_log.ROLE_AUTO_TRIAGE, action=activity_log.ACTION_START,
                                         target_type=activity_log.TARGET_REPORT, target_id=_REPORT_ID,
                                         path=path)
            # No half-written file left behind by the failed replace.
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(tmp).glob(".tmp-*.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
