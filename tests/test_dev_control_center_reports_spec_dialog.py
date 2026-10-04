"""Acceptance-criteria edit dialog (DCC Task 11): ReportSpecDialog is built Tk-free here, the
same technique test_dev_control_center_reports_inbox_view.py already uses for ReportsInboxWindow
-- reports_spec_dialog's own `tk`/`ttk` module references are swapped for a small fake widget set
for the duration of each test, so the dialog's real __init__ / _on_create code runs unmodified
against fakes instead of a live display. No real Tk, no real LOCALAPPDATA: every test that writes
a spec file points specs_dir at a temp folder.

DCC Task 14 adds a background AI investigation that starts in __init__; every test here goes
through make_dialog(), whose default investigate_fn is a harmless no-result stub, so no test
ever calls the real triage.investigate (no real AI, no subprocess). Tests that care about the
investigation inject their own fake investigate_fn (a plain function of
(report, *, stop_event) -> TriageOutcome), exactly like reports_triage.investigate's own
contract -- never the real AI.
"""
from __future__ import annotations

import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import reports_inbox as inbox
from scripts.dev_control_center import reports_spec_dialog as dialog_mod
from scripts.dev_control_center import reports_triage as triage


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
        self._after_calls: dict[int, object] = {}
        self._after_seq = 0
        self._handlers: dict = {}

    def title(self, _text):
        pass

    def geometry(self, _spec):
        pass

    def minsize(self, _w, _h):
        pass

    def configure(self, **_kwargs):
        pass

    def protocol(self, _name, _func):
        pass

    def bind(self, event, handler):
        self._handlers[event] = handler

    def after(self, _ms, func):
        self._after_seq += 1
        self._after_calls[self._after_seq] = func
        return self._after_seq

    def after_cancel(self, token):
        self._after_calls.pop(token, None)

    def winfo_exists(self):
        return not self._destroyed

    def destroy(self):
        """Real Tk fires <Destroy> on a widget whether it is destroyed directly or as part of
        a parent's own destroy() cascading down its whole widget tree; this fake mirrors that
        so tests can simulate "the parent window closed" without a real Tk hierarchy."""
        if self._destroyed:
            return
        handler = self._handlers.get("<Destroy>")
        self._destroyed = True
        if handler is not None:
            handler(None)


def _no_result_investigate(_report, *, stop_event):
    """Default stub for make_dialog(): harmless, instant, never the real AI."""
    return triage.TriageOutcome(None, "", False)


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

    def make_dialog(self, report=None, *, on_created=None, target_repo="next-day-setup",
                     investigate_fn=None):
        report = report or make_report()
        return dialog_mod.ReportSpecDialog(
            object(), report, target_repo=target_repo, on_created=on_created,
            investigate_fn=investigate_fn or _no_result_investigate)


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


class InvestigationThreadingTests(ReportSpecDialogCase):
    """DCC Task 14仕様1: investigation runs on a background thread; editing and 仕様ファイルを
    作る must stay usable even while a (fake) AI call never returns."""

    def test_editing_and_create_work_while_investigation_is_still_running(self):
        block = threading.Event()
        self.addCleanup(block.set)

        def never_returns(_report, *, stop_event):
            block.wait(5)
            return triage.TriageOutcome(None, "", False)

        with tempfile.TemporaryDirectory() as tmp:
            created = []
            d = self.make_dialog(on_created=created.append, investigate_fn=never_returns)
            self.assertTrue(d.create_button.instate(["!disabled"]))
            d.criteria_text.type("追加の条件")
            with mock.patch.object(inbox, "specs_root", return_value=Path(tmp)):
                d._on_create()
            self.assertEqual(len(created), 1)
            self.assertFalse(d.window.winfo_exists())

    def test_closing_the_dialog_stops_the_investigation_and_a_late_tick_touches_nothing(self):
        def waits_for_stop(_report, *, stop_event):
            stop_event.wait(5)
            return triage.TriageOutcome(None, "", False)

        d = self.make_dialog(investigate_fn=waits_for_stop)
        d._close()
        self.assertTrue(d._stop_event.is_set())
        self.assertFalse(d.window.winfo_exists())
        d._investigation_thread.join(timeout=5)
        d._tick()  # closed guard: must not touch any (destroyed) widget
        self.assertIsNone(d._triage_outcome)

    def test_a_parent_window_destroying_this_dialog_also_stops_the_investigation(self):
        """Review fix: ReportsInboxView.close() destroys its own Toplevel, which cascades down
        to this dialog's Toplevel without ever calling the dialog's own _close(). The dialog
        must still stop its background investigation and never touch a widget afterwards."""
        def waits_for_stop(_report, *, stop_event):
            stop_event.wait(5)
            return triage.TriageOutcome(None, "", False)

        d = self.make_dialog(investigate_fn=waits_for_stop)
        d.window.destroy()  # simulates the parent's destroy() cascading to this Toplevel
        self.assertTrue(d._stop_event.is_set())
        self.assertTrue(d._closed)
        d._investigation_thread.join(timeout=5)
        d._tick()  # closed guard: must not touch any (destroyed) widget
        self.assertIsNone(d._triage_outcome)


class TriageResultRenderingTests(ReportSpecDialogCase):
    def _settle(self, d):
        d._investigation_thread.join(timeout=5)
        d._tick()

    def test_successful_outcome_is_shown_and_enables_the_apply_button(self):
        result = triage.TriageResult(
            classification="bug", confidence="low", evidence="根拠E",
            suspected_locations=("foo/bar.py:XXX",), criteria_draft=("条件1", "条件2"),
            reply_draft="返信草案")
        outcome = triage.TriageOutcome(result, "", True)
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: outcome)
        self._settle(d)
        shown = d.triage_result_text.content
        self.assertIn("バグ", shown)
        self.assertIn("確信度は低め", shown)  # low-confidence bug gets an explicit callout
        self.assertIn("foo/bar.py:XXX", shown)
        self.assertIn("返信草案", shown)
        # criteria_draft itself is intentionally not duplicated into this read-only panel
        # (仕様5 lists only 仕分け/確信度/根拠/修正箇所の候補/返信の下書き); it reaches the
        # human through the editable criteria box, only after 受入条件の下書きを反映.
        self.assertNotIn("条件1", shown)
        self.assertTrue(d.apply_criteria_button.instate(["!disabled"]))

    def test_code_unavailable_outcome_says_so(self):
        result = triage.TriageResult("insufficient_info", "medium", "E", (), (), "返信")
        outcome = triage.TriageOutcome(result, "", False)
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: outcome)
        self._settle(d)
        self.assertIn("コードを読めなかった", d.triage_result_text.content)
        self.assertTrue(d.apply_criteria_button.instate(["disabled"]))  # no criteria_draft

    def test_code_unavailable_outcome_names_the_classified_reason(self):
        """DCC Task 14.3: when the AI investigation knows *why* no working folder was found
        (the app_key isn't registered, as happened for 夕食料飲システム), the dialog must show
        that fixed Japanese reason, not just the generic Task 14 note."""
        result = triage.TriageResult("insufficient_info", "medium", "E", (), (), "返信")
        outcome = triage.TriageOutcome(result, "", False, triage.CODE_UNAVAILABLE_REASON_NOT_REGISTERED)
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: outcome)
        self._settle(d)
        self.assertIn("このアプリがリポジトリに登録されていません", d.triage_result_text.content)

    def test_failed_outcome_shows_the_japanese_reason_and_leaves_the_template_usable(self):
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event:
                              triage.TriageOutcome(None, "調査できませんでした。", False))
        self._settle(d)
        self.assertEqual(d.triage_status_var.get(), "調査できませんでした。")
        self.assertTrue(d.apply_criteria_button.instate(["disabled"]))
        self.assertEqual(d.criteria_text.content, "\n".join(inbox.SPEC_CRITERIA_TEMPLATE))
        self.assertTrue(d.create_button.instate(["!disabled"]))

    def test_failed_outcome_with_code_unavailable_still_names_the_classified_reason(self):
        """DCC Task 14.3 review fix: when code_available is False *and* the AI call itself also
        failed (timeout / unavailable / unreadable output -- result is None), the dialog must
        still show the fixed-phrase reason, not silently drop it the way the generic failure
        message alone would. Must never include a path or exception text."""
        outcome = triage.TriageOutcome(
            None, "調査できませんでした。", False, triage.CODE_UNAVAILABLE_REASON_FOLDER_MISSING)
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: outcome)
        self._settle(d)
        self.assertEqual(d.triage_status_var.get(), "調査できませんでした。")
        shown = d.triage_result_text.content
        self.assertIn("リポジトリのフォルダが見つかりません", shown)
        self.assertNotIn("\\", shown)
        self.assertNotIn("/", shown)
        self.assertTrue(d.apply_criteria_button.instate(["disabled"]))

    def test_failed_outcome_with_code_available_shows_no_unavailable_note(self):
        """The opposite case: an AI-call failure with a working folder that *was* found must not
        gain a spurious "could not read the code" note."""
        outcome = triage.TriageOutcome(None, "調査が時間切れになりました。", True)
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: outcome)
        self._settle(d)
        self.assertEqual(d.triage_result_text.content, "")


class ApplyCriteriaDraftTests(ReportSpecDialogCase):
    def _dialog_with_draft(self, criteria_draft=("AIの条件A",)):
        result = triage.TriageResult("bug", "high", "E", (), criteria_draft, "返信")
        outcome = triage.TriageOutcome(result, "", True)
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: outcome)
        d._investigation_thread.join(timeout=5)
        d._tick()
        return d

    def test_apply_replaces_the_untouched_template_without_asking(self):
        d = self._dialog_with_draft()
        with mock.patch.object(dialog_mod, "messagebox") as mb:
            d._apply_criteria_draft()
            mb.askyesno.assert_not_called()
        self.assertEqual(d.criteria_text.content, "AIの条件A")

    def test_apply_asks_before_overwriting_human_edits_and_keeps_them_on_decline(self):
        d = self._dialog_with_draft()
        d.criteria_text.delete("1.0", "end")
        d.criteria_text.type("人が書いた条件")
        with mock.patch.object(dialog_mod, "messagebox") as mb:
            mb.askyesno.return_value = False
            d._apply_criteria_draft()
            mb.askyesno.assert_called_once()
        self.assertEqual(d.criteria_text.content, "人が書いた条件")

    def test_apply_replaces_human_edits_after_confirmation(self):
        d = self._dialog_with_draft()
        d.criteria_text.delete("1.0", "end")
        d.criteria_text.type("人が書いた条件")
        with mock.patch.object(dialog_mod, "messagebox") as mb:
            mb.askyesno.return_value = True
            d._apply_criteria_draft()
        self.assertEqual(d.criteria_text.content, "AIの条件A")

    def test_apply_asks_even_when_the_box_was_edited_to_empty_and_keeps_it_empty_on_decline(self):
        """Review fix: deleting every line is still a human edit away from the template, so it
        must go through the same overwrite confirmation as any other edit -- the previous
        `if current and ...` guard skipped confirmation for this exact case because an empty
        list is falsy."""
        d = self._dialog_with_draft()
        d.criteria_text.delete("1.0", "end")
        with mock.patch.object(dialog_mod, "messagebox") as mb:
            mb.askyesno.return_value = False
            d._apply_criteria_draft()
            mb.askyesno.assert_called_once()
        self.assertEqual(d.criteria_text.content, "")

    def test_apply_does_nothing_when_there_is_no_criteria_draft(self):
        d = self._dialog_with_draft(criteria_draft=())
        original = d.criteria_text.content
        d._apply_criteria_draft()
        self.assertEqual(d.criteria_text.content, original)


if __name__ == "__main__":
    unittest.main()
