"""DCC Task WF-3a: workflow_plan_view.py (the human-facing window over WF-1's plan data and
WF-2's executor permission).

Pure helpers (sanitize_text, display_title, truncate_for_display, task_row_line,
plan_is_paused, build_status_copy_text) are tested Tk-free. The window itself
(WorkflowPlanWindowCase and its subclasses) never constructs a real Tk widget either:
workflow_plan_view's `tk`/`ttk` module references are swapped for a small fake widget set
(below), the same technique test_dev_control_center_reports_inbox_view.py already uses for
ReportsInboxWindow, so the window's real construction/operation code runs unmodified against
fakes instead of a live display. Every plan/records/runner-config path is a per-test temp
folder; nothing here ever touches the real %LOCALAPPDATA%.
"""
from __future__ import annotations

import inspect
import json
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import app as dcc
from scripts.dev_control_center import workflow_plan as wf
from scripts.dev_control_center import workflow_plan_view as view
from scripts.dev_control_center import workflow_runner as wr

KEYS = frozenset({"sample-repo"})
BODY = "対象リポジトリ: sample-repo\n\n## 受入条件\n- 正しい結果が表示されること\n\n## 範囲外\n- 実行\n"


def task(tid="T1", **fields):
    base = dict(task_id=tid, title="表示の修正", repo_key="sample-repo", body=BODY,
                depends_on=[], status="proposed")
    base.update(fields)
    return base


def plan(*tasks):
    return dict(plan_id="Plan-1", name="開発計画", revision=0, tasks=list(tasks))


# --------------------------------------------------------------------------- pure helper tests

class PureHelperTests(unittest.TestCase):
    def test_sanitize_text_neutralizes_control_chars_but_keeps_newline_tab(self):
        out = view.sanitize_text("a\x00\x07b\tc\nd")
        self.assertNotIn("\x00", out)
        self.assertNotIn("\x07", out)
        self.assertIn("\t", out)
        self.assertIn("\n", out)

    def test_display_title_collapses_newlines_and_caps_length(self):
        out = view.display_title("line1\nline2\tline3" + "x" * 200)
        self.assertNotIn("\n", out)
        self.assertNotIn("\t", out)
        self.assertLessEqual(len(out), view.TITLE_DISPLAY_MAX + len(view.TRUNCATION_MARK))

    def test_display_title_strips_control_characters_and_truncates(self):
        nasty = "タイトル\x1b[31m\x00" + "A" * 500
        out = view.display_title(nasty)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x00", out)
        self.assertIn(view.TRUNCATION_MARK, out)

    def test_truncate_for_display_caps_lines_and_total(self):
        huge = "A" * 10_000
        out = view.truncate_for_display(huge, max_line_chars=100, max_chars=1_000_000)
        self.assertLess(len(out), len(huge))
        self.assertIn(view.TRUNCATION_MARK, out)

    def test_task_row_line_includes_order_status_and_depends(self):
        t = dict(task_id="T2", title="表示修正", repo_key="sample-repo", status="needs_human",
                  depends_on=["T1"], main_ai="claude", reviewer_ai="codex")
        line = view.task_row_line(3, t)
        self.assertTrue(line.startswith("3."))
        self.assertIn("人の確認が必要", line)
        self.assertIn("T1", line)
        self.assertIn("T2", line)
        self.assertIn("sample-repo", line)

    def test_task_row_line_sanitizes_a_nasty_title(self):
        t = dict(task_id="T9", title="x" * 300 + "\x1b[31m\x00", repo_key="sample-repo",
                  status="proposed", depends_on=[])
        line = view.task_row_line(1, t)
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\x00", line)

    def test_every_fixed_status_has_a_japanese_label(self):
        for status in wf.STATUSES:
            self.assertTrue(view.status_label(status), status)

    def test_plan_is_paused_true_only_for_failed_or_needs_human(self):
        for status, expected in (("failed", True), ("needs_human", True),
                                  ("running", False), ("proposed", False), ("approved", False)):
            with self.subTest(status=status):
                self.assertEqual(view.plan_is_paused(plan(task(status=status))), expected)

    def test_build_status_copy_text_excludes_body_but_includes_list_and_format(self):
        p = plan(task(tid="T1", title="機密タイトル"))
        text = view.build_status_copy_text(p, last_result_fn=lambda *_a: "(なし)")
        self.assertNotIn(BODY, text)
        self.assertNotIn("受入条件", text)
        self.assertIn("T1", text)
        self.assertIn("機密タイトル", text)
        self.assertIn(p["plan_id"], text)
        self.assertIn("add_task", text)
        self.assertIn("insert_after", text)
        self.assertIn("set_depends_on", text)
        self.assertIn("approve はここでは使えません", text)


# --------------------------------------------------------------------------- DCC Task WF-4a: C1

class ValidateNewPlanNameTests(unittest.TestCase):
    def test_empty_or_whitespace_only_gets_the_exact_fixed_text(self):
        for raw in ("", "   ", "\t\n"):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(view.validate_new_plan_name(raw), view.NEW_PLAN_NAME_EMPTY_TEXT)

    def test_too_long_or_disallowed_characters_get_a_fixed_reason(self):
        for raw in ("あ" * 81, "計画/名前", "計画\x07名前"):
            with self.subTest(raw=raw[:20]):
                self.assertEqual(view.validate_new_plan_name(raw), view.NEW_PLAN_NAME_INVALID_TEXT)

    def test_a_normal_name_is_accepted(self):
        self.assertIsNone(view.validate_new_plan_name("  新しい計画  "))


# --------------------------------------------------------------------------- DCC Task WF-4a: C2

class StartBlockReasonTextTests(unittest.TestCase):
    def test_every_fixed_code_has_a_non_empty_label(self):
        for code in view.START_BLOCK_LABELS:
            text = view.start_block_reason_text(wr.PlanStartBlockReason(code))
            self.assertTrue(text, code)

    def test_task_id_is_appended_when_present(self):
        text = view.start_block_reason_text(wr.PlanStartBlockReason(wr.START_BLOCK_PAUSED, "T1"))
        self.assertIn("T1", text)
        self.assertIn(view.START_BLOCK_LABELS[wr.START_BLOCK_PAUSED], text)

    def test_repo_busy_gets_the_orchestrator_hint_and_others_do_not(self):
        busy_text = view.start_block_reason_text(wr.PlanStartBlockReason(wr.START_BLOCK_REPO_BUSY))
        self.assertIn(view.START_BLOCK_REPO_BUSY_HINT_TEXT, busy_text)
        other_text = view.start_block_reason_text(wr.PlanStartBlockReason(wr.START_BLOCK_CAN_START))
        self.assertNotIn(view.START_BLOCK_REPO_BUSY_HINT_TEXT, other_text)

    # ------------------------------------------------------------------ DCC Task WF-4a: C5
    def test_output_is_only_ever_the_fixed_label_task_id_and_hint_nothing_else(self):
        """Closed composition: for every fixed code and an arbitrary-looking task_id, the output
        is exactly label (+task_id) (+hint) -- never an AI's output, a Task body, a path or
        exception text, since start_block_reason_text never reads anything else."""
        for code, label in view.START_BLOCK_LABELS.items():
            for task_id in (None, "T1"):
                with self.subTest(code=code, task_id=task_id):
                    text = view.start_block_reason_text(wr.PlanStartBlockReason(code, task_id))
                    expected = label
                    if task_id:
                        expected = f"{expected}（{task_id}）"
                    if code == wr.START_BLOCK_REPO_BUSY:
                        expected = f"{expected}。{view.START_BLOCK_REPO_BUSY_HINT_TEXT}"
                    self.assertEqual(text, expected)


# --------------------------------------------------------------------------- source-scan test (C8)

class NeverCallsDeploymentOrApprovalOpsTests(unittest.TestCase):
    def test_source_never_references_build_update_release_push_or_candidate_approval(self):
        source = Path(view.__file__).read_text(encoding="utf-8")
        forbidden = (
            "import candidate", "release_update", "processes.", "machine_entries",
            "approve_candidate", "push_candidate", "discard_candidate", "push_build_dry_run",
            ".build(", ".push(", ".approve(", "candidate_flow", "entrypoints",
        )
        for token in forbidden:
            self.assertNotIn(token, source, token)


# --------------------------------------------------------------------------- fake Tk widget set

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
        self.bindings = {}

    def pack(self, **_kwargs):
        pass

    def grid(self, **_kwargs):
        pass

    def columnconfigure(self, *_args, **_kwargs):
        pass

    def rowconfigure(self, *_args, **_kwargs):
        pass

    def configure(self, **_kwargs):
        pass

    def bind(self, sequence, func, **_kwargs):
        self.bindings[sequence] = func


class _FakeButton(_FakeTkWidget):
    def __init__(self, master=None, *, command=None, text=None, **kwargs):
        super().__init__(master, **kwargs)
        self.command = command
        self.text = text
        self._disabled = False

    def instate(self, states):
        for s in states:
            if s == "disabled" and not self._disabled:
                return False
            if s == "!disabled" and self._disabled:
                return False
        return True

    def state(self, states):
        for s in states:
            if s == "disabled":
                self._disabled = True
            elif s == "!disabled":
                self._disabled = False


class _FakeCombobox(_FakeTkWidget):
    def __init__(self, master=None, *, textvariable=None, state=None, width=None, **kwargs):
        super().__init__(master, **kwargs)
        self.textvariable = textvariable
        self._values = []

    def __setitem__(self, key, value):
        if key == "values":
            self._values = list(value)
        else:
            raise KeyError(key)

    def __getitem__(self, key):
        if key == "values":
            return self._values
        raise KeyError(key)


class _FakeListbox(_FakeTkWidget):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.items: list = []
        self.selection = None
        self.focused = False

    def delete(self, _start, _end):
        self.items = []

    def insert(self, _index, value):
        self.items.append(value)

    def get(self, _start, _end):
        return tuple(self.items)

    def size(self):
        return len(self.items)

    def selection_clear(self, _start, _end):
        self.selection = None

    def selection_set(self, index):
        self.selection = index

    def focus_set(self):
        self.focused = True

    def nearest(self, _y):
        return 0

    def bbox(self, _index):
        return None


class _FakeText(_FakeTkWidget):
    """Mirrors enough of a real tk.Text's own modified-flag behaviour (edit_modified()/the
    <<Modified>> virtual event) that WorkflowImportDialog's change detection -- deliberately
    input-method-agnostic, see workflow_plan_view._on_text_modified -- runs unmodified against
    this fake: any insert/delete flips the flag False->True and fires a bound "<<Modified>>"
    handler exactly like a real Text widget does for a keystroke, a paste or a programmatic
    edit alike; resetting the flag back to False (which the handler itself does) fires the same
    event again, same as real Tk, and is harmless since the handler no-ops when already False."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.content = ""
        self._modified = False

    def delete(self, _start, _end):
        self.content = ""
        self._set_modified(True)

    def insert(self, _index, text):
        self.content += text
        self._set_modified(True)

    def get(self, _start, _end):
        return self.content

    def edit_modified(self, value=None):
        if value is None:
            return self._modified
        self._set_modified(bool(value))

    def _set_modified(self, value: bool) -> None:
        if value == self._modified:
            return
        self._modified = value
        handler = self.bindings.get("<<Modified>>")
        if handler is not None:
            handler(None)


class _FakeToplevel:
    def __init__(self, master=None):
        self.master = master
        self._destroyed = False
        self._after_calls: dict[int, object] = {}
        self._after_seq = 0
        self._clipboard = ""

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

    def after(self, _ms, func):
        self._after_seq += 1
        self._after_calls[self._after_seq] = func
        return self._after_seq

    def after_cancel(self, token):
        self._after_calls.pop(token, None)

    def winfo_exists(self):
        return not self._destroyed

    def deiconify(self):
        pass

    def lift(self):
        pass

    def destroy(self):
        self._destroyed = True

    def clipboard_clear(self):
        self._clipboard = ""

    def clipboard_append(self, text):
        self._clipboard += text


_FAKE_TK_MODULE = SimpleNamespace(
    Toplevel=_FakeToplevel, BooleanVar=_FakeVar, StringVar=_FakeVar,
    Listbox=_FakeListbox, Text=_FakeText, TclError=tk.TclError,
)
_FAKE_TTK_MODULE = SimpleNamespace(
    Frame=_FakeTkWidget, LabelFrame=_FakeTkWidget, Label=_FakeTkWidget, Entry=_FakeTkWidget,
    Button=_FakeButton, Checkbutton=_FakeTkWidget, Combobox=_FakeCombobox,
)


class WorkflowPlanWindowCase(unittest.TestCase):
    def setUp(self):
        popup_patch = mock.patch.object(dcc, "configure_combobox_popup")
        self.popup_colors = popup_patch.start()
        self.addCleanup(popup_patch.stop)
        tk_patch = mock.patch.object(view, "tk", _FAKE_TK_MODULE)
        tk_patch.start()
        self.addCleanup(tk_patch.stop)
        ttk_patch = mock.patch.object(view, "ttk", _FAKE_TTK_MODULE)
        ttk_patch.start()
        self.addCleanup(ttk_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.plans_root = root / "plans"
        self.runner_config_path = root / "runner_config.json"
        self.daily_count_path = root / "daily_count.json"
        self.records_dir = root / "records"
        self.master = object()
        self.window = None
        self.addCleanup(self._destroy)

    def _destroy(self):
        if self.window is not None and self.window.exists():
            self.window.close()

    def make_window(self, **overrides):
        # plan_start_block_reason_fn defaults to a side-effect-free fake (DCC Task WF-4a):
        # _render_plan calls it on every select_plan/_tick, and the real wr.plan_start_block_reason
        # would otherwise fall back to auto.load_auto_mode_config(None) and the real Orchestrator
        # repo registry -- reading the actual user's %LOCALAPPDATA% config from every window test
        # that does not care about this notice at all (reviewer finding). Tests that *do* exercise
        # the notice (StartReasonNoticeTests, StartReasonNoticeIsolationTests) override this.
        kwargs = dict(
            plans_root=self.plans_root, registered_keys=KEYS,
            runner_config_path=self.runner_config_path, daily_count_path=self.daily_count_path,
            records_dir=self.records_dir,
            plan_start_block_reason_fn=lambda *_a, **_k: wr.PlanStartBlockReason(wr.START_BLOCK_CAN_START),
        )
        kwargs.update(overrides)
        self.window = view.WorkflowPlanWindow(self.master, **kwargs)
        return self.window

    def save(self, p):
        wf.save_plan(p, root=self.plans_root, registered_keys=KEYS)


# --------------------------------------------------------------------------- C1/C2: list & detail

class ComboboxThemeTests(WorkflowPlanWindowCase):
    def test_popup_colors_are_applied_on_creation_and_each_theme_change(self):
        window = self.make_window()
        self.popup_colors.assert_called_once_with(window.plan_combo)
        for _ in range(2):  # dark -> light -> dark, without rebuilding the window
            window.plan_combo.bindings["<<ThemeChanged>>"](None)
        self.assertEqual(self.popup_colors.call_args_list,
                         [mock.call(window.plan_combo)] * 3)

class ListAndDetailRenderingTests(WorkflowPlanWindowCase):
    def test_list_shows_order_status_and_depends_for_a_real_plan(self):
        p = plan(task("T1", title="最初のタスク"),
                 task("T2", title="2番目", depends_on=["T1"], status="approved"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        lines = window.task_list.get(0, "end")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("1."))
        self.assertIn("提案", lines[0])
        self.assertTrue(lines[1].startswith("2."))
        self.assertIn("承認済み", lines[1])
        self.assertIn("T1", lines[1])

    def test_window_renders_a_nasty_title_safely_even_bypassing_wf_validation(self):
        nasty_title = "x" * 300 + "\x1b[31m\x00"
        fixed_plan = plan(task("T1", title=nasty_title))

        def fake_load(_pid, **_kw):
            return fixed_plan

        window = self.make_window(load_plan_fn=fake_load)
        window.select_plan("Plan-1")
        line = window.task_list.get(0, "end")[0]
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\x00", line)
        self.assertLess(len(line), 250)

    def test_selecting_a_task_shows_its_body_read_only(self):
        p = plan(task("T1", body=BODY))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        window.select_task("T1")
        self.assertIn("受入条件", window.detail_text.get("1.0", "end"))


class PlanEnumerationSafetyTests(WorkflowPlanWindowCase):
    def test_window_excludes_an_invalid_plan_id_from_a_real_plan_folder(self):
        good = plan(task("T1"))
        self.save(good)  # creates self.plans_root for real via wf.save_plan
        bad_id = "../" + "x" * 100 + "\x00"
        (self.plans_root / "forged.json").write_text(
            json.dumps({"plan_id": bad_id, "name": "不正な計画"}), encoding="utf-8")
        window = self.make_window()
        values = window.plan_combo["values"]
        self.assertEqual(len(values), 1)
        self.assertNotIn(bad_id, "".join(values))
        self.assertIn(good["plan_id"], values[0])


# --------------------------------------------------------------------------- C3: human operations

class HumanTaskOperationTests(WorkflowPlanWindowCase):
    OP_CASES = (
        ("approve", "_on_approve", "proposed", "approve"),
        ("hold", "_on_hold", "proposed", "hold"),
        ("cancel", "_on_cancel", "proposed", "cancel"),
        ("retry", "_on_retry", "failed", "approve"),
    )

    def _setup_plan(self, status, **window_kwargs):
        p = plan(task("T1", status=status))
        self.save(p)
        window = self.make_window(**window_kwargs)
        window.select_plan(p["plan_id"])
        window.select_task("T1")
        return window, p

    def test_buttons_enabled_disabled_by_status(self):
        cases = {
            "proposed": dict(approve=True, hold=True, cancel=True, retry=False),
            "approved": dict(approve=False, hold=True, cancel=True, retry=False),
            "held": dict(approve=True, hold=False, cancel=True, retry=False),
            "failed": dict(approve=False, hold=False, cancel=True, retry=True),
            "needs_human": dict(approve=False, hold=False, cancel=True, retry=True),
            "running": dict(approve=False, hold=False, cancel=False, retry=False),
            "candidate_ready": dict(approve=False, hold=False, cancel=False, retry=False),
            "landed": dict(approve=False, hold=False, cancel=False, retry=False),
            "cancelled": dict(approve=False, hold=False, cancel=False, retry=False),
        }
        for status, expect in cases.items():
            with self.subTest(status=status):
                window, _p = self._setup_plan(status)
                self.assertEqual(window.approve_button.instate(["!disabled"]), expect["approve"])
                self.assertEqual(window.hold_button.instate(["!disabled"]), expect["hold"])
                self.assertEqual(window.cancel_button.instate(["!disabled"]), expect["cancel"])
                self.assertEqual(window.retry_button.instate(["!disabled"]), expect["retry"])
                window.close()

    def test_confirm_cancelled_calls_nothing_for_every_operation(self):
        for label, method_name, start_status, _op in self.OP_CASES:
            with self.subTest(label=label):
                calls = []
                window, _p = self._setup_plan(
                    start_status, apply_proposal_fn=lambda *a, **k: calls.append((a, k)))
                with mock.patch.object(view.messagebox, "askyesno", return_value=False):
                    getattr(window, method_name)()
                self.assertEqual(calls, [])
                window.close()

    def test_confirmed_operation_calls_apply_with_human_actor_and_expected_op(self):
        for label, method_name, start_status, expected_op in self.OP_CASES:
            with self.subTest(label=label):
                calls = []

                def fake_apply(plan_id, proposal, *, actor, root, registered_keys, _calls=calls):
                    _calls.append((plan_id, proposal, actor))
                    return dict(plan_id=plan_id, name="x", revision=1,
                                tasks=[task("T1", status="approved")]), {}

                window, p = self._setup_plan(start_status, apply_proposal_fn=fake_apply)
                with mock.patch.object(view.messagebox, "askyesno", return_value=True):
                    getattr(window, method_name)()
                self.assertEqual(len(calls), 1)
                plan_id, proposal, actor = calls[0]
                self.assertEqual(plan_id, p["plan_id"])
                self.assertEqual(actor, "human")
                self.assertEqual(proposal["ops"], [{"op": expected_op, "task_id": "T1"}])
                window.close()


# --------------------------------------------------------------------------- C4: automatic run permission

class AutoRunPermissionTests(WorkflowPlanWindowCase):
    def test_initial_value_is_off(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        self.assertFalse(window.auto_run_var.get())

    def test_toggle_on_confirmed_calls_the_wf2_setter(self):
        p = plan(task("T1"))
        self.save(p)
        calls = []

        def fake_set(plan_id, allowed, *, path):
            calls.append((plan_id, allowed, path))

        window = self.make_window(set_plan_auto_run_fn=fake_set)
        window.select_plan(p["plan_id"])
        window.auto_run_var.set(True)
        with mock.patch.object(view.messagebox, "askyesno", return_value=True) as ask:
            window._on_auto_run_toggle()
        self.assertEqual(calls, [(p["plan_id"], True, self.runner_config_path)])
        confirm_text = ask.call_args[0][1]
        self.assertIn("PUSH", confirm_text)
        self.assertIn("BUILD", confirm_text)

    def test_toggle_on_cancelled_reverts_and_calls_nothing(self):
        p = plan(task("T1"))
        self.save(p)
        calls = []
        window = self.make_window(set_plan_auto_run_fn=lambda *a, **k: calls.append(1))
        window.select_plan(p["plan_id"])
        window.auto_run_var.set(True)
        with mock.patch.object(view.messagebox, "askyesno", return_value=False):
            window._on_auto_run_toggle()
        self.assertFalse(window.auto_run_var.get())
        self.assertEqual(calls, [])

    def test_toggle_off_needs_no_confirmation(self):
        p = plan(task("T1"))
        self.save(p)
        wr.set_plan_auto_run_allowed(p["plan_id"], True, path=self.runner_config_path)
        calls = []
        window = self.make_window(set_plan_auto_run_fn=lambda *a, **k: calls.append(1))
        window.select_plan(p["plan_id"])
        self.assertTrue(window.auto_run_var.get())
        window.auto_run_var.set(False)
        with mock.patch.object(view.messagebox, "askyesno") as ask:
            window._on_auto_run_toggle()
            ask.assert_not_called()
        self.assertEqual(calls, [1])


# --------------------------------------------------------------------------- C5: pause / daily-limit notices

class PauseAndDailyLimitNoticeTests(WorkflowPlanWindowCase):
    def test_paused_notice_appears_via_tick_when_a_task_becomes_failed(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        self.assertEqual(window.pause_notice_var.get(), "")
        p["tasks"][0]["status"] = "failed"
        self.save(p)
        window._tick()
        self.assertEqual(window.pause_notice_var.get(), view.PAUSED_TEXT)

    def test_daily_limit_notice_appears_via_tick(self):
        p = plan(task("T1"))
        self.save(p)
        wr.save_workflow_runner_config(wr.WorkflowRunnerConfig(daily_limit=1), self.runner_config_path)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        self.assertEqual(window.limit_notice_var.get(), "")
        self.daily_count_path.write_text(
            json.dumps({"date": view._today_str(), "count": 1}), encoding="utf-8")
        window._tick()
        self.assertEqual(window.limit_notice_var.get(), wr.LIMIT_REACHED_TEXT)


# --------------------------------------------------------------------------- C6: manager state copy

class StatusCopyTests(WorkflowPlanWindowCase):
    def test_copy_status_sends_tasks_and_format_but_never_the_body(self):
        p = plan(task("T1", title="機密タイトル", body=BODY))
        self.save(p)
        captured = []
        window = self.make_window(copy_to_clipboard=captured.append)
        window.select_plan(p["plan_id"])
        window._on_copy_status()
        self.assertEqual(len(captured), 1)
        text = captured[0]
        self.assertNotIn(BODY, text)
        self.assertNotIn("受入条件", text)
        self.assertIn("機密タイトル", text)
        self.assertIn("T1", text)
        self.assertIn("add_task", text)
        self.assertIn("approve はここでは使えません", text)

    def test_copy_status_without_clipboard_override_uses_window_clipboard(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        window._on_copy_status()
        self.assertIn("T1", window.window._clipboard)

    def test_last_result_restricts_a_forged_record_to_the_fixed_reason_vocabulary(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        record_path = wr._record_path(p["plan_id"], "T1", root=self.records_dir)
        record_path.parent.mkdir(parents=True, exist_ok=True)

        unknown_cases = [
            ("path-like", {"reason": "C:/secret/.env"}),
            ("control-chars", {"reason": "bad\x00\x1b[31mvalue"}),
            ("too-long", {"reason": "x" * 5000}),
            ("non-string", {"reason": 12345}),
        ]
        for label, record in unknown_cases:
            with self.subTest(label=label):
                record_path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(window._last_result_word(p["plan_id"], "T1"), wr.REASON_UNKNOWN)

        # A top-level JSON value that is not even an object: reports_auto_start._read_json
        # already discards it to None, which this window must still render as "no result".
        record_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        self.assertEqual(window._last_result_word(p["plan_id"], "T1"), view.NO_RESULT_WORD)

    def test_last_result_keeps_a_known_allowed_reason_word(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        record_path = wr._record_path(p["plan_id"], "T1", root=self.records_dir)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps({"reason": "GIT_FAILED"}), encoding="utf-8")
        self.assertEqual(window._last_result_word(p["plan_id"], "T1"), "GIT_FAILED")

    def test_last_result_defaults_to_no_result_word_when_empty_or_missing(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        self.assertEqual(window._last_result_word(p["plan_id"], "T1"), view.NO_RESULT_WORD)
        record_path = wr._record_path(p["plan_id"], "T1", root=self.records_dir)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps({"reason": ""}), encoding="utf-8")
        self.assertEqual(window._last_result_word(p["plan_id"], "T1"), view.NO_RESULT_WORD)

    def test_copy_status_never_leaks_a_forged_result_word(self):
        p = plan(task("T1"))
        self.save(p)
        record_path = wr._record_path(p["plan_id"], "T1", root=self.records_dir)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps({"reason": "/etc/passwd\x00" + "y" * 500}), encoding="utf-8")
        captured = []
        window = self.make_window(copy_to_clipboard=captured.append)
        window.select_plan(p["plan_id"])
        window._on_copy_status()
        text = captured[0]
        self.assertNotIn("/etc/passwd", text)
        self.assertIn(wr.REASON_UNKNOWN, text)


# --------------------------------------------------------------------------- C7: load-failure resilience

class LoadFailureResilienceTests(WorkflowPlanWindowCase):
    def test_tick_reschedules_after_a_plan_fails_to_load(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        self.assertEqual(window.load_notice_var.get(), "")

        def failing_load(*_a, **_k):
            raise wf.WorkflowStorageError("WORKFLOW_STORAGE_ERROR")

        window._load_plan_fn = failing_load
        before = window._tick_id
        window._tick()
        self.assertEqual(window.load_notice_var.get(), view.LOAD_FAILED_TEXT)
        self.assertIsNotNone(window._tick_id)
        self.assertNotEqual(window._tick_id, before)
        # And a further tick keeps rescheduling (never stops on repeated failure).
        before2 = window._tick_id
        window._tick()
        self.assertNotEqual(window._tick_id, before2)

    def test_invalid_plan_id_through_the_real_wf1_loader_shows_fixed_notice_and_keeps_ticking(self):
        # load_plan_fn is left at its default (the real workflow_plan.load_plan): a plan_id that
        # violates WF-1's own identifier contract makes _plan_path raise WorkflowError before
        # load_plan's own try/except even starts, which is a different exception class than the
        # WorkflowStorageError raised above -- both must still produce the fixed notice and never
        # stop the periodic update.
        window = self.make_window()
        bad_id = "../" + "x" * 100
        window.select_plan(bad_id)
        self.assertIsNone(window.plan)
        self.assertEqual(window.load_notice_var.get(), view.LOAD_FAILED_TEXT)

        before = window._tick_id
        window._tick()
        self.assertEqual(window.load_notice_var.get(), view.LOAD_FAILED_TEXT)
        self.assertIsNotNone(window._tick_id)
        self.assertNotEqual(window._tick_id, before)
        before2 = window._tick_id
        window._tick()
        self.assertNotEqual(window._tick_id, before2)


class PlanSwitchFailureIsolationTests(WorkflowPlanWindowCase):
    def test_failed_switch_to_plan_b_clears_state_and_never_touches_plan_a(self):
        plan_a = plan(task("T1", status="proposed"))
        self.save(plan_a)
        auto_calls = []
        apply_calls = []
        copied = []
        window = self.make_window(
            set_plan_auto_run_fn=lambda *a, **k: auto_calls.append((a, k)),
            apply_proposal_fn=lambda *a, **k: apply_calls.append((a, k)),
            copy_to_clipboard=copied.append)
        window.select_plan(plan_a["plan_id"])
        self.assertIsNotNone(window.plan)
        window.select_task("T1")
        self.assertTrue(window.approve_button.instate(["!disabled"]))

        # plan B was never saved -- the real (unmocked) wf.load_plan fails with
        # WorkflowStorageError, exactly like a real missing/corrupt plan file would.
        window.select_plan("plan-" + "0" * 16)

        self.assertIsNone(window.plan)
        self.assertEqual(window.load_notice_var.get(), view.LOAD_FAILED_TEXT)
        self.assertIsNone(window.selected_task_id)
        for button in (window.approve_button, window.hold_button,
                       window.cancel_button, window.retry_button):
            self.assertFalse(button.instate(["!disabled"]))
        self.assertFalse(window.auto_run_var.get())

        # Every control that could still act on plan A's own data/permission must now be inert.
        window.auto_run_var.set(True)
        with mock.patch.object(view.messagebox, "askyesno", return_value=True):
            window._on_auto_run_toggle()
        self.assertEqual(auto_calls, [])

        window._on_approve()
        self.assertEqual(apply_calls, [])

        window._on_copy_status()
        self.assertEqual(copied, [])


# --------------------------------------------------------------------------- plan creation

class PlanCreationTests(WorkflowPlanWindowCase):
    def test_creating_a_plan_generates_a_fixed_format_id_and_selects_it(self):
        window = self.make_window()
        window.new_plan_name_var.set("新しい計画")
        window._on_create_plan()
        self.assertIsNotNone(window.plan)
        self.assertEqual(window.plan["name"], "新しい計画")
        self.assertRegex(window.plan["plan_id"], r"^plan-[0-9a-f]{16}$")
        self.assertEqual(window.plan["tasks"], [])

    # ------------------------------------------------------------------ DCC Task WF-4a: C1
    def test_empty_name_shows_fixed_reason_and_creates_nothing(self):
        window = self.make_window()
        window.new_plan_name_var.set("")
        window._on_create_plan()
        self.assertIsNone(window.plan)
        self.assertEqual(window.create_plan_notice_var.get(), view.NEW_PLAN_NAME_EMPTY_TEXT)

    def test_whitespace_only_name_shows_fixed_reason_and_creates_nothing(self):
        window = self.make_window()
        window.new_plan_name_var.set("   ")
        window._on_create_plan()
        self.assertIsNone(window.plan)
        self.assertEqual(window.create_plan_notice_var.get(), view.NEW_PLAN_NAME_EMPTY_TEXT)

    def test_too_long_name_shows_fixed_reason_and_creates_nothing(self):
        window = self.make_window()
        window.new_plan_name_var.set("あ" * 81)
        window._on_create_plan()
        self.assertIsNone(window.plan)
        self.assertEqual(window.create_plan_notice_var.get(), view.NEW_PLAN_NAME_INVALID_TEXT)

    def test_invalid_character_name_shows_fixed_reason_and_creates_nothing(self):
        window = self.make_window()
        window.new_plan_name_var.set("計画/名前")
        window._on_create_plan()
        self.assertIsNone(window.plan)
        self.assertEqual(window.create_plan_notice_var.get(), view.NEW_PLAN_NAME_INVALID_TEXT)

    def test_fixing_the_name_after_a_rejected_attempt_clears_the_notice_and_creates_it(self):
        window = self.make_window()
        window.new_plan_name_var.set("")
        window._on_create_plan()
        self.assertEqual(window.create_plan_notice_var.get(), view.NEW_PLAN_NAME_EMPTY_TEXT)
        window.new_plan_name_var.set("新しい計画")
        window._on_create_plan()
        self.assertEqual(window.create_plan_notice_var.get(), "")
        self.assertIsNotNone(window.plan)


# --------------------------------------------------------------------------- DCC Task WF-4a: C2/C5
# 次のタスクが始まらない理由 -- always via the injected plan_start_block_reason_fn, never the real
# workflow_runner defaults (which would resolve a real repo via the real Orchestrator registry):
# this window's own test boundary stays Tk-free/Orchestrator-free (C8), while workflow_runner's own
# plan_start_block_reason is exercised directly (with its own fakes) in
# test_dev_control_center_workflow_runner.py.

class StartReasonNoticeTests(WorkflowPlanWindowCase):
    def test_no_plan_selected_shows_nothing(self):
        window = self.make_window()
        self.assertEqual(window.start_reason_var.get(), "")

    def test_reason_shown_after_selecting_a_plan_using_the_stored_paths(self):
        p = plan(task("T1", status="approved"))
        self.save(p)
        calls = []

        def fake_reason(plan_arg, **kwargs):
            calls.append((plan_arg["plan_id"], kwargs))
            return wr.PlanStartBlockReason(wr.START_BLOCK_GLOBAL_OFF)

        window = self.make_window(plan_start_block_reason_fn=fake_reason)
        window.select_plan(p["plan_id"])
        self.assertEqual(window.start_reason_var.get(), view.START_BLOCK_LABELS[wr.START_BLOCK_GLOBAL_OFF])
        self.assertEqual(calls[-1][0], p["plan_id"])
        self.assertEqual(calls[-1][1]["runner_config_path"], self.runner_config_path)
        self.assertEqual(calls[-1][1]["daily_count_path"], self.daily_count_path)

    def test_reason_with_task_id_is_shown_verbatim(self):
        p = plan(task("T1", status="failed"))
        self.save(p)
        window = self.make_window(
            plan_start_block_reason_fn=lambda *_a, **_k: wr.PlanStartBlockReason(
                wr.START_BLOCK_PAUSED, "T1"))
        window.select_plan(p["plan_id"])
        self.assertEqual(window.start_reason_var.get(),
                         view.start_block_reason_text(wr.PlanStartBlockReason(wr.START_BLOCK_PAUSED, "T1")))

    def test_reason_rereads_on_tick(self):
        p = plan(task("T1", status="approved"))
        self.save(p)
        codes = [wr.START_BLOCK_GLOBAL_OFF, wr.START_BLOCK_CAN_START]
        window = self.make_window(
            plan_start_block_reason_fn=lambda *_a, **_k: wr.PlanStartBlockReason(codes.pop(0)))
        window.select_plan(p["plan_id"])
        self.assertEqual(window.start_reason_var.get(), view.START_BLOCK_LABELS[wr.START_BLOCK_GLOBAL_OFF])
        window._tick()
        self.assertEqual(window.start_reason_var.get(), view.START_BLOCK_LABELS[wr.START_BLOCK_CAN_START])

    def test_reason_rereads_on_auto_run_toggle(self):
        p = plan(task("T1", status="approved"))
        self.save(p)
        codes = [wr.START_BLOCK_PLAN_AUTO_RUN_OFF, wr.START_BLOCK_CAN_START]
        window = self.make_window(
            plan_start_block_reason_fn=lambda *_a, **_k: wr.PlanStartBlockReason(codes.pop(0)),
            set_plan_auto_run_fn=lambda *_a, **_k: None)
        window.select_plan(p["plan_id"])
        self.assertEqual(window.start_reason_var.get(), view.START_BLOCK_LABELS[wr.START_BLOCK_PLAN_AUTO_RUN_OFF])
        window.auto_run_var.set(True)
        with mock.patch.object(view.messagebox, "askyesno", return_value=True):
            window._on_auto_run_toggle()
        self.assertEqual(window.start_reason_var.get(), view.START_BLOCK_LABELS[wr.START_BLOCK_CAN_START])

    def test_a_bad_read_clears_the_notice_instead_of_raising(self):
        p = plan(task("T1", status="approved"))
        self.save(p)

        def raiser(*_a, **_k):
            raise RuntimeError("boom")

        window = self.make_window(plan_start_block_reason_fn=raiser)
        window.select_plan(p["plan_id"])
        self.assertEqual(window.start_reason_var.get(), "")


# --------------------------------------------------------------------------- DCC Task WF-4a:
# reviewer finding -- every window test (not just this class) must stay isolated from the real
# global-mode config file and the real Orchestrator repo registry, never only the tests that
# explicitly exercise the notice.

class StartReasonNoticeIsolationTests(WorkflowPlanWindowCase):
    def test_default_fixture_never_touches_real_global_config_or_repo_registry(self):
        p = plan(task("T1", status="approved"))
        self.save(p)
        with mock.patch.object(wr.auto, "load_auto_mode_config") as loader, \
             mock.patch("tools.ai_orchestrator.orchestrator.resolve_repo_dir_for_app") as resolver:
            window = self.make_window()  # default plan_start_block_reason_fn -- no override
            window.select_plan(p["plan_id"])
            window._tick()
        loader.assert_not_called()
        resolver.assert_not_called()

    def test_real_plan_start_block_reason_wired_through_the_window_stays_isolated(self):
        """A caller that *does* want the real judgment (as app.py's own open_workflow_plan does)
        must still only ever touch the temp paths/fakes this test wires -- global_config_path,
        runner_config_path, state and resolve_repo_dir are all explicit, so this can never fall
        through to the real %LOCALAPPDATA% config or the real Orchestrator registry either."""
        p = plan(task("T1", status="approved"))
        self.save(p)
        # Never created: the real auto.load_auto_mode_config degrades a missing file to its own
        # all-OFF default (enabled=False) -- never the real %LOCALAPPDATA% auto-mode config, since
        # this explicit path (not None) is what the window below actually passes.
        global_config_path = self.plans_root.parent / "global.json"
        state = wr.WorkflowRunnerState(daily_count_path=self.daily_count_path)

        def real_reason_fn(plan_arg, **kwargs):
            return wr.plan_start_block_reason(
                plan_arg, global_config_path=global_config_path, runner_config_path=kwargs["runner_config_path"],
                state=kwargs["state"], resolve_repo_dir=lambda _k: self.plans_root.parent / "repos",
                busy_fn=lambda _n: False, repo_run_blocked_fn=lambda _r: False)

        with mock.patch("tools.ai_orchestrator.orchestrator.resolve_repo_dir_for_app") as resolver:
            window = self.make_window(plan_start_block_reason_fn=real_reason_fn, runner_state=state)
            window.select_plan(p["plan_id"])
        resolver.assert_not_called()  # resolve_repo_dir is this test's own fake, never the real registry
        self.assertEqual(window.start_reason_var.get(), view.START_BLOCK_LABELS[wr.START_BLOCK_GLOBAL_OFF])


# --------------------------------------------------------------------------- app.py wiring

class _FakeWorkflowPlanWindow:
    instances: list["_FakeWorkflowPlanWindow"] = []

    def __init__(self, master, **kwargs):
        self.master = master
        self.kwargs = kwargs
        self._exists = True
        self.focus_calls = 0
        _FakeWorkflowPlanWindow.instances.append(self)

    def exists(self) -> bool:
        return self._exists

    def focus(self) -> None:
        self.focus_calls += 1

    def close(self) -> None:
        self._exists = False


class AppWorkflowPlanButtonTests(unittest.TestCase):
    def setUp(self):
        _FakeWorkflowPlanWindow.instances.clear()
        patcher = mock.patch(
            "scripts.dev_control_center.workflow_plan_view.WorkflowPlanWindow", _FakeWorkflowPlanWindow)
        patcher.start()
        self.addCleanup(patcher.stop)
        dcc.ACTIVE_OPERATIONS.clear()
        self.addCleanup(dcc.ACTIVE_OPERATIONS.clear)
        timing_patch = mock.patch.object(dcc.TIMING, "enabled", False)
        timing_patch.start()
        self.addCleanup(timing_patch.stop)
        self.destroyed = False
        self.app = dcc.App.__new__(dcc.App)
        self.app.master = SimpleNamespace(destroy=self._note_destroyed)
        self.app.workflow_plan_window = None
        # DCC Task WF-4a: open_workflow_plan hands this one process-lifetime WorkflowRunnerState
        # to the window (see test_open_workflow_plan_passes_the_shared_runner_state below) so the
        # window's own "次のタスクが始まらない理由" notice shares the real background loop's
        # in-memory daily count instead of a second, independently-drifting one.
        self.app._workflow_runner_state = wr.WorkflowRunnerState()

    def _note_destroyed(self):
        self.destroyed = True

    def test_main_screen_wires_a_button_to_open_workflow_plan(self):
        """DCC Task UI-C: 開発計画 moved into the Orchestrator window's own header. The main
        screen no longer builds its own 開発計画 button at all -- it only ever forwards
        open_workflow_plan to OrchestratorWindow, whose header button calls it back through
        self._on_workflow_plan."""
        from scripts.dev_control_center import orchestrator_view as orch_view

        self.assertNotIn("self.workflow_plan_button", inspect.getsource(dcc.App))
        self.assertIn("on_workflow_plan=self.open_workflow_plan", inspect.getsource(dcc.App.open_orchestrator))
        header_source = inspect.getsource(orch_view.OrchestratorWindow.__init__)
        self.assertIn("command=self._open_workflow_plan", header_source)
        self.assertIn(
            "self._on_workflow_plan()", inspect.getsource(orch_view.OrchestratorWindow._open_workflow_plan))

    def test_open_workflow_plan_passes_the_shared_runner_state(self):
        self.app.open_workflow_plan()
        window = self.app.workflow_plan_window
        self.assertIs(window.kwargs.get("runner_state"), self.app._workflow_runner_state)

    def test_opening_twice_focuses_the_existing_window_instead_of_duplicating(self):
        self.app.open_workflow_plan()
        window = self.app.workflow_plan_window
        self.assertIsInstance(window, _FakeWorkflowPlanWindow)
        self.assertEqual(len(_FakeWorkflowPlanWindow.instances), 1)

        self.app.open_workflow_plan()
        self.assertIs(self.app.workflow_plan_window, window)
        self.assertEqual(len(_FakeWorkflowPlanWindow.instances), 1)
        self.assertEqual(window.focus_calls, 1)

    def test_closing_dcc_with_the_window_open_does_not_raise(self):
        self.app.open_workflow_plan()
        window = self.app.workflow_plan_window
        self.app._closed = False
        self.app._badge_stop = threading.Event()
        self.app._auto_triage_stop = threading.Event()
        self.app._auto_start_stop = threading.Event()
        self.app._requeue_stop = threading.Event()
        self.app._auto_progress_stop = threading.Event()
        self.app._workflow_runner_stop = threading.Event()
        self.app.orchestrator_window = None
        self.app.reports_window = None
        self.app.selection = SimpleNamespace(close=lambda: None)
        self.app._on_close()
        self.assertTrue(self.app._closed)
        self.assertFalse(window.exists())
        self.assertTrue(self.destroyed)


# --------------------------------------------------------------------------- WF-3b: import dialog
# validate_proposal_text / import_summary_text are pure (Tk-free) and exercised directly against
# the real WF-1 (workflow_plan.preview_proposal) below -- no fakes needed for these, same as
# test_dev_control_center_workflow_plan.py's own style, since WF-1 itself does no I/O.

class ValidateProposalTextTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan(task("T1", status="proposed"),
                          task("T2", status="proposed", depends_on=["T1"]))

    def _proposal_text(self, *ops, base_revision=None):
        return json.dumps({
            "plan_id": self.plan["plan_id"],
            "base_revision": self.plan["revision"] if base_revision is None else base_revision,
            "ops": list(ops),
        })

    def _validate(self, text, p=None):
        return view.validate_proposal_text(
            text, p or self.plan, preview_fn=wf.preview_proposal, registered_keys=KEYS)

    def test_valid_proposal_returns_summary_and_next_revision(self):
        text = self._proposal_text({"op": "hold", "task_id": "T1"})
        _proposal, summary, new_revision, reason = self._validate(text)
        self.assertIsNone(reason)
        self.assertEqual(new_revision, self.plan["revision"] + 1)
        self.assertEqual(summary["changed"]["count"], 1)
        self.assertIn("T1", summary["changed"]["task_ids"])

    def test_too_long_paste_is_rejected_without_calling_preview(self):
        calls = []
        text = "x" * (view.PROPOSAL_PASTE_MAX_CHARS + 1)
        _proposal, _summary, _rev, reason = view.validate_proposal_text(
            text, self.plan, preview_fn=lambda *a, **k: calls.append(1), registered_keys=KEYS)
        self.assertEqual(reason, view.IMPORT_REASON_TOO_LONG)
        self.assertEqual(calls, [])

    def test_deeply_nested_json_is_rejected_without_calling_preview(self):
        # Within the PROPOSAL_PASTE_MAX_CHARS cap but deep enough to overflow the json module's
        # own C-level recursion limit (RecursionError, not a plain json.JSONDecodeError).
        calls = []
        text = "[" * 2000 + "0" + "]" * 2000
        self.assertLessEqual(len(text), view.PROPOSAL_PASTE_MAX_CHARS)
        _proposal, _summary, _rev, reason = view.validate_proposal_text(
            text, self.plan, preview_fn=lambda *a, **k: calls.append(1), registered_keys=KEYS)
        self.assertEqual(reason, view.IMPORT_REASON_INVALID_FORMAT)
        self.assertEqual(calls, [])

    def test_malformed_or_non_json_text_is_rejected(self):
        cases = {
            "broken_syntax": "{not valid json",
            "wrong_shape": json.dumps({"foo": 1}),
            "not_an_object": json.dumps([1, 2, 3]),
            "control_char_in_string": ('{"plan_id": "' + self.plan["plan_id"] +
                                        '", "base_revision": 0, "ops": '
                                        '[{"op": "hold", "task_id": "T1\x07"}]}'),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                _p, _s, _r, reason = self._validate(text)
                self.assertEqual(reason, view.IMPORT_REASON_INVALID_FORMAT)

    def test_plan_id_mismatch_is_rejected(self):
        text = json.dumps({"plan_id": "some-other-plan", "base_revision": 0,
                            "ops": [{"op": "hold", "task_id": "T1"}]})
        _p, _s, _r, reason = self._validate(text)
        self.assertEqual(reason, view.IMPORT_REASON_PLAN_ID_MISMATCH)

    def test_stale_base_revision_shows_the_exact_fixed_text(self):
        text = self._proposal_text({"op": "hold", "task_id": "T1"}, base_revision=99)
        _p, _s, _r, reason = self._validate(text)
        self.assertEqual(reason, view.IMPORT_REASON_STALE)
        self.assertIn("マネージャーに案を作り直してもらってください", reason)

    def test_circular_dependency_is_rejected(self):
        text = self._proposal_text({"op": "set_depends_on", "task_id": "T1", "depends_on": ["T2"]})
        _p, _s, _r, reason = self._validate(text)
        self.assertEqual(reason, view.IMPORT_REASON_GENERIC_INVALID)

    def test_running_task_change_is_rejected(self):
        p = plan(task("T1", status="running"))
        text = json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                            "ops": [{"op": "hold", "task_id": "T1"}]})
        _p, _s, _r, reason = self._validate(text, p)
        self.assertEqual(reason, view.IMPORT_REASON_LOCKED)

    def test_approve_op_is_always_rejected(self):
        text = self._proposal_text({"op": "approve", "task_id": "T1"})
        _p, _s, _r, reason = self._validate(text)
        self.assertEqual(reason, view.IMPORT_REASON_APPROVE_NOT_ALLOWED)

    def test_approve_mixed_with_other_ops_still_rejects_the_whole_proposal(self):
        text = self._proposal_text({"op": "hold", "task_id": "T2"}, {"op": "approve", "task_id": "T1"})
        _p, _s, _r, reason = self._validate(text)
        self.assertEqual(reason, view.IMPORT_REASON_APPROVE_NOT_ALLOWED)

    def test_path_and_command_like_strings_never_reach_the_fixed_reason_text(self):
        dangerous = ("../../etc/passwd", "rm -rf /", "git push origin main; curl evil.example")
        for value in dangerous:
            with self.subTest(value=value):
                text = self._proposal_text({"op": "add_task", "task": {
                    "task_id": "newtask", "title": value, "repo_key": "sample-repo",
                    "body": BODY, "depends_on": [], "status": "proposed"}})
                _p, _s, _r, reason = self._validate(text)
                self.assertIsNotNone(reason)
                self.assertNotIn(value, reason)


class ImportSummaryTextTests(unittest.TestCase):
    def test_includes_counts_ids_and_next_revision(self):
        summary = {
            "added": {"count": 1, "task_ids": ["T2"]},
            "changed": {"count": 0, "task_ids": []},
            "deleted": {"count": 0, "task_ids": []},
            "reordered": {"count": 0, "task_ids": []},
        }
        text = view.import_summary_text(summary, 5)
        self.assertIn("追加", text)
        self.assertIn("T2", text)
        self.assertIn("5", text)


# --------------------------------------------------------------------------- WorkflowImportDialog

class WorkflowImportDialogCase(WorkflowPlanWindowCase):
    def make_dialog(self, p, **overrides):
        kwargs = dict(plan=p, plans_root=self.plans_root, registered_keys=KEYS)
        kwargs.update(overrides)
        dialog = view.WorkflowImportDialog(self.master, **kwargs)
        self.addCleanup(lambda: dialog._close() if dialog.exists() else None)
        return dialog

    def set_paste(self, dialog, text):
        dialog.paste_text.delete("1.0", "end")
        dialog.paste_text.insert("1.0", text)


# --------------------------------------------------------------------------- C1: valid proposal

class ImportDialogValidateSuccessTests(WorkflowImportDialogCase):
    def test_valid_proposal_shows_diff_summary_and_enables_apply(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        dialog = self.make_dialog(p)
        self.set_paste(dialog, json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                            "ops": [{"op": "hold", "task_id": "T1"}]}))
        dialog._on_validate()
        self.assertTrue(dialog.apply_button.instate(["!disabled"]))
        self.assertEqual(dialog.notice_var.get(), "")
        summary = dialog.summary_text.get("1.0", "end")
        self.assertIn("変更", summary)
        self.assertIn("T1", summary)
        self.assertIn("revision", summary)


# --------------------------------------------------------------------------- C2: fixed failure reasons

class ImportDialogFixedReasonTests(WorkflowImportDialogCase):
    def test_each_failure_case_shows_a_fixed_reason_and_keeps_apply_disabled(self):
        p = plan(task("T1", status="proposed"), task("T2", status="proposed", depends_on=["T1"]))
        self.save(p)
        cases = (
            ("invalid_format", "{not valid json", view.IMPORT_REASON_INVALID_FORMAT),
            ("plan_id_mismatch",
             json.dumps({"plan_id": "other-plan", "base_revision": 0,
                         "ops": [{"op": "hold", "task_id": "T1"}]}),
             view.IMPORT_REASON_PLAN_ID_MISMATCH),
            ("stale_base_revision",
             json.dumps({"plan_id": p["plan_id"], "base_revision": 9,
                         "ops": [{"op": "hold", "task_id": "T1"}]}),
             view.IMPORT_REASON_STALE),
            ("circular_dependency",
             json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                         "ops": [{"op": "set_depends_on", "task_id": "T1", "depends_on": ["T2"]}]}),
             view.IMPORT_REASON_GENERIC_INVALID),
        )
        for label, text, expected_reason in cases:
            with self.subTest(label=label):
                dialog = self.make_dialog(p)
                self.set_paste(dialog, text)
                dialog._on_validate()
                self.assertEqual(dialog.notice_var.get(), expected_reason)
                self.assertFalse(dialog.apply_button.instate(["!disabled"]))
                self.assertEqual(dialog.summary_text.get("1.0", "end"), "")

    def test_running_task_change_shows_the_locked_reason(self):
        p = plan(task("T1", status="running"))
        self.save(p)
        dialog = self.make_dialog(p)
        self.set_paste(dialog, json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                            "ops": [{"op": "hold", "task_id": "T1"}]}))
        dialog._on_validate()
        self.assertEqual(dialog.notice_var.get(), view.IMPORT_REASON_LOCKED)
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))

    def test_deeply_nested_json_shows_the_invalid_format_reason_without_crashing(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        dialog = self.make_dialog(p)
        self.set_paste(dialog, "[" * 2000 + "0" + "]" * 2000)
        dialog._on_validate()  # must not raise RecursionError
        self.assertEqual(dialog.notice_var.get(), view.IMPORT_REASON_INVALID_FORMAT)
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))
        self.assertEqual(dialog.summary_text.get("1.0", "end"), "")


# --------------------------------------------------------------------------- C3: approve always rejected

class ImportDialogApproveRejectedTests(WorkflowImportDialogCase):
    def test_approve_op_is_rejected_and_cannot_be_applied(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        apply_calls = []
        dialog = self.make_dialog(p, apply_proposal_fn=lambda *a, **k: apply_calls.append((a, k)))
        self.set_paste(dialog, json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                            "ops": [{"op": "approve", "task_id": "T1"}]}))
        dialog._on_validate()
        self.assertEqual(dialog.notice_var.get(), view.IMPORT_REASON_APPROVE_NOT_ALLOWED)
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))
        dialog._on_apply()  # a no-op: _validated_proposal is None after a failed 検証
        self.assertEqual(apply_calls, [])
        on_disk = wf.load_plan(p["plan_id"], root=self.plans_root, registered_keys=KEYS)
        self.assertEqual(on_disk["revision"], 0)


# --------------------------------------------------------------------------- C4: paste change invalidates apply

class ImportDialogPasteChangeTests(WorkflowImportDialogCase):
    def test_editing_paste_after_validate_disables_apply_until_revalidated(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        dialog = self.make_dialog(p)
        valid_text = json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                  "ops": [{"op": "hold", "task_id": "T1"}]})
        self.set_paste(dialog, valid_text)
        dialog._on_validate()
        self.assertTrue(dialog.apply_button.instate(["!disabled"]))

        # No key event is fired here at all: a programmatic insert (standing in for a
        # middle-click/Ctrl+V paste, which never produces a KeyRelease either) must disable
        # 反映 purely through the Text widget's own modified-flag/<<Modified>> event.
        dialog.paste_text.insert("end", " ")  # content changed since the last 検証
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))

        # Re-validating re-enables 反映: the gate is "this exact text was just validated", not
        # whether the edit happened to still be syntactically valid JSON.
        dialog._on_validate()
        self.assertTrue(dialog.apply_button.instate(["!disabled"]))

    def test_deleting_paste_without_any_insert_also_disables_apply(self):
        # A delete-only edit (e.g. selecting all and pressing Delete) must disable 反映 too --
        # not just an insert -- since it is still a real content change away from what 検証 saw.
        p = plan(task("T1", status="proposed"))
        self.save(p)
        dialog = self.make_dialog(p)
        valid_text = json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                  "ops": [{"op": "hold", "task_id": "T1"}]})
        self.set_paste(dialog, valid_text)
        dialog._on_validate()
        self.assertTrue(dialog.apply_button.instate(["!disabled"]))

        dialog.paste_text.delete("1.0", "end")
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))


# --------------------------------------------------------------------------- C5: apply confirmation

class ImportDialogApplyConfirmationTests(WorkflowImportDialogCase):
    def _validated_dialog(self, p):
        dialog = self.make_dialog(p)
        text = json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                            "ops": [{"op": "hold", "task_id": "T1"}]})
        self.set_paste(dialog, text)
        dialog._on_validate()
        self.assertTrue(dialog.apply_button.instate(["!disabled"]))
        return dialog

    def test_cancelling_the_confirmation_applies_nothing(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        calls = []
        dialog = self._validated_dialog(p)
        dialog._apply_proposal_fn = lambda *a, **k: calls.append((a, k))
        with mock.patch.object(view.messagebox, "askyesno", return_value=False):
            dialog._on_apply()
        self.assertEqual(calls, [])
        on_disk = wf.load_plan(p["plan_id"], root=self.plans_root, registered_keys=KEYS)
        self.assertEqual(on_disk["revision"], 0)

    def test_confirming_calls_wf1_once_with_manager_actor_and_increments_revision(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        applied = []
        calls = []
        real_apply = wf.apply_and_save_proposal

        def counting_apply(*args, **kwargs):
            calls.append(kwargs)
            return real_apply(*args, **kwargs)

        dialog = self._validated_dialog(p)
        dialog._apply_proposal_fn = counting_apply
        dialog._on_applied = applied.append
        with mock.patch.object(view.messagebox, "askyesno", return_value=True):
            dialog._on_apply()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["actor"], "manager")
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["revision"], 1)
        on_disk = wf.load_plan(p["plan_id"], root=self.plans_root, registered_keys=KEYS)
        self.assertEqual(on_disk["revision"], 1)
        self.assertEqual(on_disk["tasks"][0]["status"], "held")
        self.assertIn(view.IMPORT_APPLY_SUCCESS_TEXT, dialog.notice_var.get())
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))


# --------------------------------------------------------------------------- stale-plan reload
# (Review 1 finding #2): this dialog's own self._plan is only a snapshot taken when it was
# opened. A plan that changes on disk afterwards -- either before 検証 or between a successful
# 検証 and 反映 -- must be caught both times, each with the TaskSpec's own fixed stale-plan text,
# never silently validated/applied against data that is no longer current.

class ImportDialogStalePlanTests(WorkflowImportDialogCase):
    def test_validate_reloads_the_plan_and_rejects_a_proposal_stale_since_dialog_open(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        dialog = self.make_dialog(p)  # snapshot taken at revision 0

        # The plan changes on disk (e.g. a human operation on WF-3a's own window) after this
        # dialog opened but before 検証 is pressed.
        wf.apply_and_save_proposal(
            p["plan_id"],
            {"plan_id": p["plan_id"], "base_revision": 0,
             "ops": [{"op": "hold", "task_id": "T1"}]},
            actor="human", root=self.plans_root, registered_keys=KEYS)

        # A manager proposal built against the dialog's own (now stale) base_revision=0.
        self.set_paste(dialog, json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                            "ops": [{"op": "cancel", "task_id": "T1"}]}))
        dialog._on_validate()
        self.assertEqual(dialog.notice_var.get(), view.IMPORT_REASON_STALE)
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))
        self.assertEqual(dialog.summary_text.get("1.0", "end"), "")

        on_disk = wf.load_plan(p["plan_id"], root=self.plans_root, registered_keys=KEYS)
        self.assertEqual(on_disk["revision"], 1)
        self.assertEqual(on_disk["tasks"][0]["status"], "held")

    def test_plan_updated_between_validate_and_apply_shows_stale_reason_and_applies_nothing(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        dialog = self.make_dialog(p)
        self.set_paste(dialog, json.dumps({"plan_id": p["plan_id"], "base_revision": 0,
                                            "ops": [{"op": "hold", "task_id": "T1"}]}))
        dialog._on_validate()
        self.assertTrue(dialog.apply_button.instate(["!disabled"]))

        # The plan changes on disk after 検証 succeeded but before the human presses 反映.
        wf.apply_and_save_proposal(
            p["plan_id"],
            {"plan_id": p["plan_id"], "base_revision": 0,
             "ops": [{"op": "cancel", "task_id": "T1"}]},
            actor="human", root=self.plans_root, registered_keys=KEYS)

        with mock.patch.object(view.messagebox, "askyesno", return_value=True):
            dialog._on_apply()
        self.assertEqual(dialog.notice_var.get(), view.IMPORT_REASON_STALE)
        self.assertFalse(dialog.apply_button.instate(["!disabled"]))

        # Only the human's own cancel landed; the dialog's stale hold proposal never applied.
        on_disk = wf.load_plan(p["plan_id"], root=self.plans_root, registered_keys=KEYS)
        self.assertEqual(on_disk["revision"], 1)
        self.assertEqual(on_disk["tasks"][0]["status"], "cancelled")


# --------------------------------------------------------------------------- C6: dangerous paste safety

class ImportDialogDangerousInputTests(WorkflowImportDialogCase):
    def test_oversized_control_path_and_command_pastes_never_echo_raw_text(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        cases = (
            ("too_long", "x" * (view.PROPOSAL_PASTE_MAX_CHARS + 1), view.IMPORT_REASON_TOO_LONG),
            ("control_chars",
             '{"plan_id": "' + p["plan_id"] + '", "base_revision": 0, '
             '"ops": [{"op": "hold", "task_id": "T1\x07\x1b"}]}',
             view.IMPORT_REASON_INVALID_FORMAT),
            ("path_like",
             json.dumps({"plan_id": p["plan_id"], "base_revision": 0, "ops": [
                 {"op": "add_task", "task": {"task_id": "../../etc/passwd", "title": "x",
                                              "repo_key": "sample-repo", "body": BODY,
                                              "depends_on": [], "status": "proposed"}}]}),
             view.IMPORT_REASON_GENERIC_INVALID),
            ("command_like",
             json.dumps({"plan_id": p["plan_id"], "base_revision": 0, "ops": [
                 {"op": "add_task", "task": {"task_id": "newtask",
                                              "title": "rm -rf / ; echo pwned",
                                              "repo_key": "sample-repo", "body": BODY,
                                              "depends_on": [], "status": "proposed"}}]}),
             view.IMPORT_REASON_GENERIC_INVALID),
        )
        for label, text, expected_reason in cases:
            with self.subTest(label=label):
                dialog = self.make_dialog(p)
                self.set_paste(dialog, text)
                dialog._on_validate()
                self.assertFalse(dialog.apply_button.instate(["!disabled"]))
                reason = dialog.notice_var.get()
                self.assertEqual(reason, expected_reason)
                self.assertNotIn("\x07", reason)
                self.assertNotIn("\x1b", reason)
                self.assertNotIn("/etc/passwd", reason)
                self.assertNotIn("rm -rf", reason)
                self.assertEqual(dialog.summary_text.get("1.0", "end"), "")


# --------------------------------------------------------------------------- C7: button wiring on the plan window

class ImportButtonWiringTests(WorkflowPlanWindowCase):
    def test_import_button_disabled_without_a_loaded_plan(self):
        window = self.make_window()
        self.assertFalse(window.import_button.instate(["!disabled"]))

    def test_import_button_enabled_once_a_plan_is_loaded(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        self.assertTrue(window.import_button.instate(["!disabled"]))

    def test_import_does_nothing_without_a_loaded_plan(self):
        window = self.make_window()
        with mock.patch.object(view, "WorkflowImportDialog") as ctor:
            window._on_import_proposal()
            ctor.assert_not_called()

    def test_opening_import_dialog_passes_the_current_plan_snapshot(self):
        p = plan(task("T1"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        captured = {}

        class _FakeImportDialog:
            def __init__(self, master, **kwargs):
                captured.update(kwargs)

        with mock.patch.object(view, "WorkflowImportDialog", _FakeImportDialog):
            window._on_import_proposal()
        self.assertEqual(captured["plan"]["plan_id"], p["plan_id"])
        self.assertEqual(captured["plans_root"], self.plans_root)

    def test_applied_proposal_refreshes_the_visible_task_list(self):
        p = plan(task("T1", status="proposed"))
        self.save(p)
        window = self.make_window()
        window.select_plan(p["plan_id"])
        new_plan = dict(plan_id=p["plan_id"], name=p["name"], revision=1,
                         tasks=[task("T1", status="held")])
        window._on_import_applied(new_plan)
        self.assertEqual(window.plan["revision"], 1)
        lines = window.task_list.get(0, "end")
        self.assertIn("保留", lines[0])


if __name__ == "__main__":
    unittest.main()
