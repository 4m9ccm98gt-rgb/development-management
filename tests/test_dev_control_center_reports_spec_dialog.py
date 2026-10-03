"""Acceptance-criteria edit dialog (DCC Task 11): ReportSpecDialog is built Tk-free here, the
same technique test_dev_control_center_reports_inbox_view.py already uses for ReportsInboxWindow
-- reports_spec_dialog's own `tk`/`ttk` module references are swapped for a small fake widget set
for the duration of each test, so the dialog's real __init__ / _on_create code runs unmodified
against fakes instead of a live display. No real Tk, no real LOCALAPPDATA: every test that writes
a spec file points specs_dir at a temp folder.
"""
from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import reports_inbox as inbox
from scripts.dev_control_center import reports_spec_dialog as dialog_mod


def make_report(**overrides) -> inbox.Report:
    fields = dict(
        app_key="next-day-setup", app_display_name="夕食料飲システム", file_name="r.json", schema_version=1,
        report_id="r1", created_at="2026-01-01T00:00:00Z", kind="bug", severity="stopped",
        title="タイトル", body="本文", reporter="yamada", app_id="next-day-setup",
        display_name="夕食料飲システム", release_id="rel-1", git_commit="a" * 40, version_source="BUILD_INFO.txt",
        pc_name="FRONT-PC1",
    )
    fields.update(overrides)
    return inbox.Report(**fields)


class _FakeVar:
    def __init__(self, value=None, **_kwargs):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class _FakeTkWidget:
    def __init__(self, master=None, **_kwargs):
        self.master = master

    def pack(self, **_kwargs):
        pass

    def grid(self, **_kwargs):
        pass

    def configure(self, **_kwargs):
        pass


class _FakeButton(_FakeTkWidget):
    def __init__(self, master=None, *, command=None, text=None, **kwargs):
        super().__init__(master, **kwargs)
        self.command = command
        self.text = text
        self._disabled = False

    def state(self, states):
        for s in states:
            if s == "disabled":
                self._disabled = True
            elif s == "!disabled":
                self._disabled = False

    def instate(self, states):
        for s in states:
            if s == "disabled" and not self._disabled:
                return False
            if s == "!disabled" and self._disabled:
                return False
        return True


class _FakeText:
    def __init__(self, master=None, **_kwargs):
        self.content = ""
        self._handlers: dict = {}

    def configure(self, **_kwargs):
        pass

    def pack(self, **_kwargs):
        pass

    def grid(self, **_kwargs):
        pass

    def delete(self, _start, _end):
        self.content = ""

    def insert(self, _index, text):
        self.content += text

    def get(self, _start, _end):
        return self.content

    def bind(self, event, handler):
        self._handlers[event] = handler

    def type(self, text: str) -> None:
        """Test helper: append text the way a human typing would, then fire <KeyRelease> the
        same way the real dialog's binding would after each keystroke."""
        self.insert("end", text)
        handler = self._handlers.get("<KeyRelease>")
        if handler is not None:
            handler(None)


class _FakeToplevel:
    def __init__(self, master=None):
        self.master = master
        self._destroyed = False

    def title(self, _text):
        pass

    def geometry(self, _spec):
        pass

    def minsize(self, _w, _h):
        pass

    def configure(self, **_kwargs):
        pass

    def winfo_exists(self):
        return not self._destroyed

    def destroy(self):
        self._destroyed = True


_FAKE_TK_MODULE = SimpleNamespace(Toplevel=_FakeToplevel, StringVar=_FakeVar, Text=_FakeText, TclError=tk.TclError)
_FAKE_TTK_MODULE = SimpleNamespace(Frame=_FakeTkWidget, Label=_FakeTkWidget, Button=_FakeButton)


class ReportSpecDialogCase(unittest.TestCase):
    def setUp(self):
        tk_patch = mock.patch.object(dialog_mod, "tk", _FAKE_TK_MODULE)
        tk_patch.start()
        self.addCleanup(tk_patch.stop)
        ttk_patch = mock.patch.object(dialog_mod, "ttk", _FAKE_TTK_MODULE)
        ttk_patch.start()
        self.addCleanup(ttk_patch.stop)

    def make_dialog(self, report=None, *, on_created=None, target_repo="next-day-setup"):
        report = report or make_report()
        return dialog_mod.ReportSpecDialog(object(), report, target_repo=target_repo, on_created=on_created)


class TemplateAndSummaryTests(ReportSpecDialogCase):
    def test_criteria_box_starts_with_the_three_line_template(self):
        d = self.make_dialog()
        self.assertEqual(d.criteria_text.content, "\n".join(inbox.SPEC_CRITERIA_TEMPLATE))

    def test_summary_shows_kind_app_title_and_is_read_only_in_content(self):
        report = make_report(kind="request", title="画面が遅い", body="詳しい手順...")
        d = self.make_dialog(report)
        summary = d.summary_text.content
        self.assertIn("仕様変更の希望", summary)
        self.assertIn("夕食料飲システム", summary)
        self.assertIn("画面が遅い", summary)
        self.assertIn("詳しい手順", summary)

    def test_consultation_report_also_gets_the_same_template(self):
        report = make_report(kind="request")
        d = self.make_dialog(report)
        self.assertEqual(d.criteria_text.content, "\n".join(inbox.SPEC_CRITERIA_TEMPLATE))


class ValidationTests(ReportSpecDialogCase):
    def test_empty_criteria_shows_a_japanese_reason_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = []
            d = self.make_dialog(on_created=created.append)
            d.criteria_text.delete("1.0", "end")
            with mock.patch.object(inbox, "specs_root", return_value=Path(tmp)):
                d._on_create()
            self.assertTrue(d.notice_var.get())
            self.assertEqual(created, [])
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertTrue(d.window.winfo_exists())  # dialog stays open on failure

    def test_too_many_lines_shows_a_japanese_reason_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = []
            d = self.make_dialog(on_created=created.append)
            d.criteria_text.delete("1.0", "end")
            d.criteria_text.insert("1.0", "\n".join(f"条件{i}" for i in range(21)))
            with mock.patch.object(inbox, "specs_root", return_value=Path(tmp)):
                d._on_create()
            self.assertTrue(d.notice_var.get())
            self.assertEqual(created, [])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_a_too_long_line_shows_a_japanese_reason_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = []
            d = self.make_dialog(on_created=created.append)
            d.criteria_text.delete("1.0", "end")
            d.criteria_text.insert("1.0", "x" * 1001)
            with mock.patch.object(inbox, "specs_root", return_value=Path(tmp)):
                d._on_create()
            self.assertTrue(d.notice_var.get())
            self.assertEqual(created, [])
            self.assertEqual(list(Path(tmp).iterdir()), [])


class LiveValidationTests(ReportSpecDialogCase):
    """Review fix: the create button must reflect validity as the human types, not only after
    they press it (previously create_button stayed enabled while the box held invalid input)."""

    def test_the_valid_template_starts_with_the_create_button_enabled_and_no_notice(self):
        d = self.make_dialog()
        self.assertTrue(d.create_button.instate(["!disabled"]))
        self.assertEqual(d.notice_var.get(), "")

    def test_clearing_all_criteria_disables_the_button_and_shows_a_japanese_notice(self):
        d = self.make_dialog()
        d.criteria_text.delete("1.0", "end")
        d.criteria_text.type("")  # fires <KeyRelease> on the now-empty box
        self.assertTrue(d.create_button.instate(["disabled"]))
        self.assertTrue(d.notice_var.get())

    def test_restoring_valid_input_re_enables_the_button(self):
        d = self.make_dialog()
        d.criteria_text.delete("1.0", "end")
        d.criteria_text.type("")
        self.assertTrue(d.create_button.instate(["disabled"]))
        d.criteria_text.type("条件A")
        self.assertTrue(d.create_button.instate(["!disabled"]))
        self.assertEqual(d.notice_var.get(), "")

    def test_too_many_lines_disables_the_button_while_typed(self):
        d = self.make_dialog()
        d.criteria_text.delete("1.0", "end")
        d.criteria_text.type("\n".join(f"条件{i}" for i in range(21)))
        self.assertTrue(d.create_button.instate(["disabled"]))
        self.assertTrue(d.notice_var.get())


class SuccessAndFailureTests(ReportSpecDialogCase):
    def test_confirming_writes_a_spec_file_and_calls_on_created_then_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = []
            report = make_report(body="一意なマーカーABCDEF")
            d = self.make_dialog(report, on_created=created.append)
            with mock.patch.object(inbox, "specs_root", return_value=Path(tmp)):
                d._on_create()
            self.assertEqual(len(created), 1)
            path = created[0]
            spec = inbox.taskspec.load_spec_file(path)
            self.assertEqual(spec.target_repo, "next-day-setup")
            self.assertNotIn("一意なマーカーABCDEF", path.read_text(encoding="utf-8"))
            self.assertFalse(d.window.winfo_exists())  # dialog closes on success

    def test_write_failure_shows_a_japanese_message_without_path_or_exception_text(self):
        report = make_report()
        d = self.make_dialog(report)
        with mock.patch.object(inbox, "create_spec_file",
                                side_effect=inbox.SpecCreateError("仕様ファイルを保存できませんでした。")):
            d._on_create()
        self.assertEqual(d.notice_var.get(), "仕様ファイルを保存できませんでした。")
        self.assertTrue(d.window.winfo_exists())


if __name__ == "__main__":
    unittest.main()
