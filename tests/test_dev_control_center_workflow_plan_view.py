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

    def bind(self, _sequence, _func):
        pass


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
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.content = ""

    def delete(self, _start, _end):
        self.content = ""

    def insert(self, _index, text):
        self.content += text

    def get(self, _start, _end):
        return self.content


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
        kwargs = dict(
            plans_root=self.plans_root, registered_keys=KEYS,
            runner_config_path=self.runner_config_path, daily_count_path=self.daily_count_path,
            records_dir=self.records_dir,
        )
        kwargs.update(overrides)
        self.window = view.WorkflowPlanWindow(self.master, **kwargs)
        return self.window

    def save(self, p):
        wf.save_plan(p, root=self.plans_root, registered_keys=KEYS)


# --------------------------------------------------------------------------- C1/C2: list & detail

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


# --------------------------------------------------------------------------- app.py wiring

class _FakeWorkflowPlanWindow:
    instances: list["_FakeWorkflowPlanWindow"] = []

    def __init__(self, master, **_kwargs):
        self.master = master
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

    def _note_destroyed(self):
        self.destroyed = True

    def test_main_screen_wires_a_button_to_open_workflow_plan(self):
        source = inspect.getsource(dcc.App.__init__) + inspect.getsource(dcc.App._build)
        self.assertIn("self.workflow_plan_button", source)
        self.assertIn("command=self.open_workflow_plan", source)

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


if __name__ == "__main__":
    unittest.main()
