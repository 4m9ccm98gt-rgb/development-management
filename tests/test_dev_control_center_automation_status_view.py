"""DCC Task WF-6c: the "自動処理の状況" window (scripts/dev_control_center/automation_status_view.py).

Pure helpers (target_text) are tested Tk-free. AutomationStatusWindow itself never constructs a
real Tk widget: the module's own `tk`/`ttk` references are swapped for a small fake widget set
(below) for the duration of each test, and `_Table` is swapped for a fake that just records the
rows it was given -- so the window's real __init__/_tick/_refresh code runs unmodified against
fakes instead of a real display, AI, Orchestrator, or network of any kind. Every path this test
file touches (via automation_status.build_snapshot in the one integration test) is a
tempfile.TemporaryDirectory() path.
"""
from __future__ import annotations

import inspect
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import activity_log
from scripts.dev_control_center import automation_status as status
from scripts.dev_control_center import automation_status_view as view
from scripts.dev_control_center import app as dcc


def entry(**overrides) -> activity_log.ActivityEntry:
    fields = dict(
        timestamp="2026-01-01T09:30:00Z", role=activity_log.ROLE_AUTO_TRIAGE,
        action=activity_log.ACTION_COMPLETE, target_type=activity_log.TARGET_REPORT,
        target_id="0" * 64, result=activity_log.RESULT_PROCEED, reason="",
    )
    fields.update(overrides)
    return activity_log.ActivityEntry(**fields)


def role_status(**overrides) -> status.RoleStatus:
    fields = dict(role=activity_log.ROLE_AUTO_TRIAGE, state=status.STATE_RUNNING, reason=status.REASON_NONE)
    fields.update(overrides)
    return status.RoleStatus(**fields)


# --------------------------------------------------------------------------- pure helpers

class TargetTextTests(unittest.TestCase):
    def test_target_none_shows_only_the_fixed_word(self):
        e = entry(target_type=activity_log.TARGET_NONE, target_id="")
        self.assertEqual(view.target_text(e), activity_log.TARGET_NONE)

    def test_report_target_shows_type_and_hashed_id(self):
        e = entry(target_type=activity_log.TARGET_REPORT, target_id="a" * 64)
        self.assertEqual(view.target_text(e), f"{activity_log.TARGET_REPORT} {'a' * 64}")

    def test_run_target_shows_type_and_run_id(self):
        e = entry(target_type=activity_log.TARGET_RUN, target_id="20260101-000000-000001")
        self.assertEqual(view.target_text(e), f"{activity_log.TARGET_RUN} 20260101-000000-000001")


class NeverStartsOrApprovesAnythingTests(unittest.TestCase):
    """C5: static source inspection, the same convention
    test_dev_control_center_workflow_plan_view.py's NeverCallsDeploymentOrApprovalOpsTests uses --
    this window must never reference any approval/push/BUILD/UPDATE/RELEASE entry point."""

    def test_view_source_never_references_deployment_or_approval_ops(self):
        source = Path(view.__file__).read_text(encoding="utf-8")
        forbidden = (
            "import candidate", "release_update", "processes.", "machine_entries",
            "approve_candidate", "push_candidate", "discard_candidate", "push_build_dry_run",
            ".build(", ".push(", ".approve(", "candidate_flow", "entrypoints",
            "subprocess", "create_and_start", "start_run", "investigate_fn", "investigate(",
        )
        for token in forbidden:
            self.assertNotIn(token, source, token)

    def test_logic_source_never_references_deployment_or_approval_ops(self):
        source = Path(status.__file__).read_text(encoding="utf-8")
        forbidden = (
            "import candidate", "release_update", "processes.", "machine_entries",
            "approve_candidate", "push_candidate", "discard_candidate", "push_build_dry_run",
            ".build(", ".push(", ".approve(", "candidate_flow", "subprocess",
            "create_and_start", "start_run", "triage.investigate", "investigate(",
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


class _FakeToplevel:
    def __init__(self, master=None):
        self.master = master
        self._destroyed = False
        self._after_calls: dict[int, object] = {}
        self._after_seq = 0

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


class _FakeTable:
    """Records exactly what AutomationStatusWindow handed it -- never renders anything real."""

    def __init__(self, master, columns, *, style_prefix):
        self.master = master
        self.columns = columns
        self.style_prefix = style_prefix
        self.rows: list[tuple] | None = None
        self.grid_calls: list[dict] = []

    def grid(self, **kwargs):
        self.grid_calls.append(kwargs)

    def set_rows(self, rows):
        self.rows = list(rows)


_FAKE_TK_MODULE = SimpleNamespace(Toplevel=_FakeToplevel, StringVar=_FakeVar, TclError=tk.TclError)
_FAKE_TTK_MODULE = SimpleNamespace(Frame=_FakeTkWidget, LabelFrame=_FakeTkWidget, Label=_FakeTkWidget)


class AutomationStatusWindowCase(unittest.TestCase):
    def setUp(self):
        tk_patch = mock.patch.object(view, "tk", _FAKE_TK_MODULE)
        tk_patch.start()
        self.addCleanup(tk_patch.stop)
        ttk_patch = mock.patch.object(view, "ttk", _FAKE_TTK_MODULE)
        ttk_patch.start()
        self.addCleanup(ttk_patch.stop)
        table_patch = mock.patch.object(view, "_Table", _FakeTable)
        table_patch.start()
        self.addCleanup(table_patch.stop)
        self.master = object()

    def make_window(self, snapshot_fn=None):
        return view.AutomationStatusWindow(self.master, snapshot_fn=snapshot_fn)


class LifecycleTests(AutomationStatusWindowCase):
    def test_window_opens_without_touching_a_real_display(self):
        window = self.make_window(snapshot_fn=lambda: status.StatusSnapshot(
            roles=(), recent=(), next_report_id="", not_running_reason=""))
        self.assertTrue(window.exists())

    def test_close_cancels_the_tick_and_destroys_the_window(self):
        window = self.make_window(snapshot_fn=lambda: status.StatusSnapshot(
            roles=(), recent=(), next_report_id="", not_running_reason=""))
        window.close()
        self.assertFalse(window.exists())
        # Calling close twice must not raise (same convention as every other DCC window).
        window.close()

    def test_focus_does_not_raise_when_window_is_already_open(self):
        window = self.make_window(snapshot_fn=lambda: status.StatusSnapshot(
            roles=(), recent=(), next_report_id="", not_running_reason=""))
        window.focus()  # must not raise


# --------------------------------------------------------------------------- C1: fixed-word display

class RoleAndRecentDisplayTests(AutomationStatusWindowCase):
    def test_role_rows_show_fixed_state_last_activity_result_and_reason(self):
        roles = (
            role_status(role=activity_log.ROLE_AUTO_TRIAGE, state=status.STATE_RUNNING,
                        reason=status.REASON_NONE, last_activity_at="2026-01-01 09:30:00",
                        last_result=activity_log.RESULT_PROCEED, last_reason="", hint=""),
            role_status(role=activity_log.ROLE_AUTO_START, state=status.STATE_STOPPED,
                        reason=status.REASON_DAILY_LIMIT, last_activity_at="", last_result="",
                        last_reason="", hint=""),
        )
        snapshot = status.StatusSnapshot(roles=roles, recent=(), next_report_id="", not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.role_table.rows, [
            (activity_log.ROLE_AUTO_TRIAGE, status.STATE_RUNNING, status.REASON_NONE,
             "2026-01-01 09:30:00", activity_log.RESULT_PROCEED, "", ""),
            (activity_log.ROLE_AUTO_START, status.STATE_STOPPED, status.REASON_DAILY_LIMIT, "", "", "", ""),
        ])

    def test_recent_activity_rows_are_rendered_in_the_order_given(self):
        entries = (
            entry(timestamp="2026-01-02T00:00:00Z", role=activity_log.ROLE_AUTO_PLAN,
                  action=activity_log.ACTION_START, target_type=activity_log.TARGET_PLAN_TASK,
                  target_id="plan1:task1", result="", reason=""),
            entry(timestamp="2026-01-01T00:00:00Z", role=activity_log.ROLE_AUTO_TRIAGE,
                  action=activity_log.ACTION_EXCLUDED, target_type=activity_log.TARGET_NONE,
                  target_id="", result="", reason=""),
        )
        snapshot = status.StatusSnapshot(roles=(), recent=entries, next_report_id="", not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.recent_table.rows, [
            ("2026-01-02 00:00:00", activity_log.ROLE_AUTO_PLAN, activity_log.ACTION_START,
             f"{activity_log.TARGET_PLAN_TASK} plan1:task1", "", ""),
            ("2026-01-01 00:00:00", activity_log.ROLE_AUTO_TRIAGE, activity_log.ACTION_EXCLUDED,
             activity_log.TARGET_NONE, "", ""),
        ])

    def test_next_report_id_is_shown_verbatim_when_present(self):
        snapshot = status.StatusSnapshot(roles=(), recent=(), next_report_id="f" * 64, not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.next_report_var.get(), "f" * 64)

    def test_next_report_shows_fixed_nashi_when_absent(self):
        snapshot = status.StatusSnapshot(roles=(), recent=(), next_report_id="", not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.next_report_var.get(), status.NO_NEXT_REPORT_TEXT)

    def test_not_running_reason_is_shown_as_the_fixed_word(self):
        snapshot = status.StatusSnapshot(
            roles=(), recent=(), next_report_id="", not_running_reason=status.REASON_PERMISSION_OFF)
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.not_running_reason_var.get(), status.REASON_PERMISSION_OFF)


# --------------------------------------------------------------------------- C2/C3: degraded states

class DegradedStateTests(AutomationStatusWindowCase):
    def test_unreadable_log_shows_the_fixed_sentence_and_does_not_crash(self):
        snapshot = status.StatusSnapshot(
            roles=(), recent=(), next_report_id="", not_running_reason="", log_unreadable=True)
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.log_notice_var.get(), status.LOG_UNREADABLE_TEXT)
        self.assertTrue(window.exists())

    def test_empty_snapshot_shows_no_unreadable_notice_and_does_not_crash(self):
        snapshot = status.StatusSnapshot(roles=(), recent=(), next_report_id="", not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertEqual(window.log_notice_var.get(), "")
        self.assertEqual(window.recent_table.rows, [])
        self.assertTrue(window.exists())

    def test_a_snapshot_fn_that_raises_degrades_to_the_fixed_sentence_without_crashing(self):
        """A snapshot builder that somehow raises (the broken/corrupt case at its worst) must
        never crash this screen -- it degrades to the same fixed 読めません sentence."""
        window = self.make_window(snapshot_fn=mock.Mock(side_effect=RuntimeError("disk exploded")))
        window._refresh()  # must not raise
        self.assertEqual(window.log_notice_var.get(), status.LOG_UNREADABLE_TEXT)
        self.assertEqual(window.role_table.rows, [])
        self.assertEqual(window.recent_table.rows, [])
        self.assertEqual(window.next_report_var.get(), status.NO_NEXT_REPORT_TEXT)
        self.assertTrue(window.exists())

    def test_login_expired_hint_reaches_the_role_row(self):
        roles = (role_status(hint=status.LOGIN_EXPIRED_HINT, last_reason=activity_log.REASON_LOGIN_EXPIRED),)
        snapshot = status.StatusSnapshot(roles=roles, recent=(), next_report_id="", not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertIn(status.LOGIN_EXPIRED_HINT, window.role_table.rows[0])

    def test_quota_limit_hint_reaches_the_role_row(self):
        roles = (role_status(hint=status.QUOTA_LIMIT_HINT, last_reason=activity_log.REASON_QUOTA_LIMIT),)
        snapshot = status.StatusSnapshot(roles=roles, recent=(), next_report_id="", not_running_reason="")
        window = self.make_window(snapshot_fn=lambda: snapshot)
        window._refresh()
        self.assertIn(status.QUOTA_LIMIT_HINT, window.role_table.rows[0])


# --------------------------------------------------------------------------- C4: no free text ever

class NoFreeTextLeaksTests(AutomationStatusWindowCase):
    def test_refresh_never_surfaces_a_path_or_exception_text(self):
        banned = ("C:\\", "/home/", "Traceback", "本文", "ShizenDev")

        def _raise():
            raise RuntimeError(f"C:\\Users\\someone\\secret path failed: Traceback (most recent call last)")

        window = self.make_window(snapshot_fn=_raise)
        window._refresh()
        rendered = "".join([
            window.log_notice_var.get() or "", window.next_report_var.get() or "",
            window.not_running_reason_var.get() or "", repr(window.role_table.rows),
            repr(window.recent_table.rows),
        ])
        for token in banned:
            self.assertNotIn(token, rendered, token)


# --------------------------------------------------------------------------- Reviewer finding 3:
# the background fetch must never block the Tk thread (this window's own event loop, and -- since
# Tk's mainloop is shared with the rest of DCC -- the whole main screen too), and close() must
# never wait for a fetch that is still in flight.

class BackgroundFetchTests(AutomationStatusWindowCase):
    def test_tick_returns_immediately_even_when_the_snapshot_fn_is_slow(self):
        started = threading.Event()
        release = threading.Event()

        def slow_snapshot():
            started.set()
            release.wait(5)
            return status.StatusSnapshot(roles=(), recent=(), next_report_id="", not_running_reason="")

        window = self.make_window(snapshot_fn=slow_snapshot)
        try:
            before = time.monotonic()
            window._tick()
            self.assertLess(time.monotonic() - before, 1.0)
            self.assertTrue(started.wait(1), "background fetch never started")
        finally:
            release.set()

    def test_close_does_not_wait_for_a_fetch_still_in_flight(self):
        release = threading.Event()

        def slow_snapshot():
            release.wait(5)
            return status.StatusSnapshot(roles=(), recent=(), next_report_id="", not_running_reason="")

        window = self.make_window(snapshot_fn=slow_snapshot)
        window._tick()
        before = time.monotonic()
        window.close()  # must return immediately, never joining the background thread
        self.assertLess(time.monotonic() - before, 1.0)
        self.assertFalse(window.exists())
        release.set()

    def test_a_second_tick_does_not_start_another_fetch_while_one_is_in_flight(self):
        calls = []
        release = threading.Event()

        def slow_snapshot():
            calls.append(1)
            release.wait(5)
            return status.StatusSnapshot(roles=(), recent=(), next_report_id="", not_running_reason="")

        window = self.make_window(snapshot_fn=slow_snapshot)
        window._tick()
        window._tick()
        window._tick()
        release.set()
        deadline = time.monotonic() + 2
        while window._fetch_in_flight and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(calls), 1)
        window.close()

    def test_tick_applies_the_snapshot_once_the_background_fetch_completes(self):
        release = threading.Event()

        def delayed_snapshot():
            release.wait(5)
            return status.StatusSnapshot(roles=(), recent=(), next_report_id="z" * 64, not_running_reason="")

        window = self.make_window(snapshot_fn=delayed_snapshot)
        window._tick()
        self.assertEqual(window.next_report_var.get(), status.NO_NEXT_REPORT_TEXT)  # not applied yet
        release.set()
        deadline = time.monotonic() + 2
        while window._fetch_in_flight and time.monotonic() < deadline:
            time.sleep(0.01)
        window._tick()  # drains the now-ready queue and applies it
        self.assertEqual(window.next_report_var.get(), "z" * 64)
        window.close()

    def test_a_fetch_that_finishes_after_close_touches_no_widget(self):
        release = threading.Event()

        def slow_snapshot():
            release.wait(5)
            return status.StatusSnapshot(roles=(), recent=(), next_report_id="z" * 64, not_running_reason="")

        window = self.make_window(snapshot_fn=slow_snapshot)
        window._tick()
        window.close()
        release.set()
        time.sleep(0.2)  # let the background thread finish; it must not raise or touch Tk
        self.assertEqual(window.next_report_var.get(), status.NO_NEXT_REPORT_TEXT)


# --------------------------------------------------------------------------- C6: dark mode

class TableThemeTests(unittest.TestCase):
    def test_dark_palette_is_applied_and_scrollbars_are_wired(self):
        tree = mock.Mock()
        scrollbars = [mock.Mock(), mock.Mock()]
        with mock.patch.object(view.ttk, "Frame"), mock.patch.object(view.ttk, "Style") as style_cls, \
                mock.patch.object(view.ttk, "Treeview", return_value=tree), \
                mock.patch.object(view.ttk, "Scrollbar", side_effect=scrollbars) as scrollbar:
            style = style_cls.return_value
            style.theme_use.return_value = "clam"
            style.lookup.return_value = dcc.DARK_BG
            table = view._Table(object(), view.ROLE_COLUMNS, style_prefix="RoleStatus")
        tree.heading.assert_any_call("role", text="役割", anchor="w")
        self.assertEqual(scrollbar.call_args_list[0].kwargs["command"], tree.xview)
        self.assertEqual(scrollbar.call_args_list[1].kwargs["command"], tree.yview)
        tree.configure.assert_any_call(xscrollcommand=scrollbars[0].set, yscrollcommand=scrollbars[1].set)
        heading_call = next(c for c in style.configure.call_args_list if c.args == ("RoleStatus.Treeview.Heading",))
        self.assertEqual(heading_call.kwargs["background"], dcc.DARK_FIELD)
        self.assertEqual(heading_call.kwargs["foreground"], dcc.DARK_FG)
        tree_call = next(c for c in style.configure.call_args_list if c.args == ("RoleStatus.Treeview",))
        self.assertEqual(tree_call.kwargs["background"], dcc.DARK_SURFACE)
        scrollbar_call = next(
            c for c in style.configure.call_args_list if c.args == ("RoleStatus.Horizontal.TScrollbar",))
        self.assertEqual(scrollbar_call.kwargs["troughcolor"], dcc.DARK_BG)
        self.assertEqual(scrollbar_call.kwargs["background"], dcc.DARK_FIELD)
        self.assertEqual(scrollbar_call.kwargs["arrowcolor"], dcc.DARK_FG)
        table.horizontal.configure.assert_called_with(style="RoleStatus.Horizontal.TScrollbar")
        table.vertical.configure.assert_called_with(style="RoleStatus.Vertical.TScrollbar")
        table.tree.configure.assert_called_with(style="RoleStatus.Treeview")
        table.frame.configure.assert_called_with(style="RoleStatus.TFrame")

    def test_light_theme_leaves_native_styles_untouched(self):
        tree = mock.Mock()
        scrollbars = [mock.Mock(), mock.Mock()]
        with mock.patch.object(view.ttk, "Frame"), mock.patch.object(view.ttk, "Style") as style_cls, \
                mock.patch.object(view.ttk, "Treeview", return_value=tree), \
                mock.patch.object(view.ttk, "Scrollbar", side_effect=scrollbars):
            style = style_cls.return_value
            style.theme_use.return_value = "default"
            style.lookup.return_value = "#ffffff"
            table = view._Table(object(), view.RECENT_COLUMNS, style_prefix="RecentActivity")
        table.tree.configure.assert_called_with(style="Treeview")
        table.frame.configure.assert_called_with(style="TFrame")
        table.horizontal.configure.assert_called_with(style="Horizontal.TScrollbar")
        table.vertical.configure.assert_called_with(style="Vertical.TScrollbar")

    def test_theme_is_not_reapplied_when_unchanged(self):
        tree = mock.Mock()
        scrollbars = [mock.Mock(), mock.Mock()]
        with mock.patch.object(view.ttk, "Frame"), mock.patch.object(view.ttk, "Style") as style_cls, \
                mock.patch.object(view.ttk, "Treeview", return_value=tree), \
                mock.patch.object(view.ttk, "Scrollbar", side_effect=scrollbars):
            style = style_cls.return_value
            style.theme_use.return_value = "clam"
            style.lookup.return_value = dcc.DARK_BG
            table = view._Table(object(), view.ROLE_COLUMNS, style_prefix="RoleStatus")
            style.configure.reset_mock()
            table._apply_theme()
            style.configure.assert_not_called()  # no feedback loop on an unchanged theme


# --------------------------------------------------------------------------- app.py wiring (C5)

class _FakeAutomationStatusWindow:
    instances: list = []

    def __init__(self, master, **kwargs):
        self.master = master
        self.kwargs = kwargs
        self._exists = True
        self.focus_calls = 0
        _FakeAutomationStatusWindow.instances.append(self)

    def exists(self):
        return self._exists

    def focus(self):
        self.focus_calls += 1

    def close(self):
        self._exists = False


class AppAutomationStatusButtonTests(unittest.TestCase):
    def setUp(self):
        _FakeAutomationStatusWindow.instances.clear()
        patcher = mock.patch(
            "scripts.dev_control_center.automation_status_view.AutomationStatusWindow",
            _FakeAutomationStatusWindow)
        patcher.start()
        self.addCleanup(patcher.stop)
        dcc.ACTIVE_OPERATIONS.clear()
        self.addCleanup(dcc.ACTIVE_OPERATIONS.clear)
        self.destroyed = False
        self.app = dcc.App.__new__(dcc.App)
        self.app.master = SimpleNamespace(destroy=self._note_destroyed)
        self.app.automation_status_window = None
        self.app.active_process = None  # _repo_name_busy's own "a manual run is active" check
        self.app.selection = SimpleNamespace(current=None)  # App.current reads selection.current

    def _note_destroyed(self):
        self.destroyed = True

    def test_main_screen_wires_a_button_to_open_automation_status(self):
        """DCC Task UI-C: 自動処理の状況 moved into the Orchestrator window's own header. The
        main screen no longer builds its own 自動処理の状況 button at all -- it only ever
        forwards open_automation_status to OrchestratorWindow, whose header button calls it back
        through self._on_automation_status."""
        from scripts.dev_control_center import orchestrator_view as orch_view

        self.assertNotIn("self.automation_status_button", inspect.getsource(dcc.App))
        self.assertIn(
            "on_automation_status=self.open_automation_status", inspect.getsource(dcc.App.open_orchestrator))
        header_source = inspect.getsource(orch_view.OrchestratorWindow.__init__)
        self.assertIn("command=self._open_automation_status", header_source)
        self.assertIn(
            "self._on_automation_status()",
            inspect.getsource(orch_view.OrchestratorWindow._open_automation_status))

    def test_opening_twice_focuses_the_existing_window_instead_of_duplicating(self):
        self.app.open_automation_status()
        window = self.app.automation_status_window
        self.assertIsInstance(window, _FakeAutomationStatusWindow)
        self.assertEqual(len(_FakeAutomationStatusWindow.instances), 1)

        self.app.open_automation_status()
        self.assertIs(self.app.automation_status_window, window)
        self.assertEqual(len(_FakeAutomationStatusWindow.instances), 1)
        self.assertEqual(window.focus_calls, 1)

    def test_snapshot_closure_passes_a_busy_fn_scoped_to_one_repository_at_a_time(self):
        """Reviewer finding 1: 計画の自動実行 must only ever see its own eligible task's own
        repository as busy -- never a blanket "something, somewhere is busy" flag -- so this
        checks the closure app.py hands to automation_status.build_snapshot is a per-repo-name
        callable backed by ACTIVE_OPERATIONS (App._repo_name_busy), not a precomputed bool."""
        self.app.open_automation_status()
        window = self.app.automation_status_window
        snapshot_fn = window.kwargs.get("snapshot_fn")
        self.assertIsNotNone(snapshot_fn)
        with mock.patch(
                "scripts.dev_control_center.automation_status.build_snapshot") as build_snapshot:
            build_snapshot.return_value = "irrelevant"
            dcc.ACTIVE_OPERATIONS[1] = ("some-repo", "manual-run")
            snapshot_fn()
            busy_fn = build_snapshot.call_args.kwargs["workflow_runner_busy_fn"]
            self.assertTrue(busy_fn("some-repo"))
            self.assertFalse(busy_fn("some-other-repo"))
            dcc.ACTIVE_OPERATIONS.clear()
            snapshot_fn()
            busy_fn = build_snapshot.call_args.kwargs["workflow_runner_busy_fn"]
            self.assertFalse(busy_fn("some-repo"))

    def test_closing_dcc_with_the_window_open_does_not_raise(self):
        import threading

        self.app.open_automation_status()
        window = self.app.automation_status_window
        self.app._closed = False
        self.app._badge_stop = threading.Event()
        self.app._auto_triage_stop = threading.Event()
        self.app._auto_start_stop = threading.Event()
        self.app._requeue_stop = threading.Event()
        self.app._auto_progress_stop = threading.Event()
        self.app._workflow_runner_stop = threading.Event()
        self.app.orchestrator_window = None
        self.app.reports_window = None
        self.app.workflow_plan_window = None
        self.app.selection = SimpleNamespace(close=lambda: None)
        timing_patch = mock.patch.object(dcc.TIMING, "enabled", False)
        timing_patch.start()
        self.addCleanup(timing_patch.stop)
        self.app._on_close()
        self.assertTrue(self.app._closed)
        self.assertFalse(window.exists())
        self.assertTrue(self.destroyed)


if __name__ == "__main__":
    unittest.main()
