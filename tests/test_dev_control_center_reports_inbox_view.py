"""Reports inbox window (DCC Task 8b): Tk client of reports_inbox.py.

Pure helpers (truncate_for_display, row_title, row_line) and the click-wiring are tested
Tk-free. The window itself (ReportsInboxWindowCase and its subclasses) never constructs a
real Tk widget either: reports_inbox_view's `tk`/`ttk` module references are swapped for a
small fake widget set (below) for the duration of each test, so ReportsInboxWindow's own
construction and event-tick logic run unmodified against fakes instead of a real display.
The DCC-entrance tests (AppReportsButtonTests) likewise never build a real App: App.__init__
(which would build the real main screen) is bypassed via __new__, and only the two methods
Task 8b touches (open_reports_inbox, _on_close) are exercised against a minimal double.
"""
from __future__ import annotations

import inspect
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.dev_control_center import app as dcc
from scripts.dev_control_center import reports_inbox as inbox
from scripts.dev_control_center import reports_inbox_view as view


def make_report(**overrides) -> inbox.Report:
    fields = dict(
        app_key="app", app_display_name="お品書き", file_name="r.json", schema_version=1,
        report_id="r1", created_at="2026-01-01T00:00:00Z", kind="bug", severity="stopped",
        title="タイトル", body="本文", reporter="yamada", app_id="menu-sheet-generator",
        display_name="お品書き", release_id="rel-1", git_commit="a" * 40, version_source="BUILD_INFO.txt",
        pc_name="FRONT-PC1",
    )
    fields.update(overrides)
    return inbox.Report(**fields)


class TruncateAndRowHelpersTests(unittest.TestCase):
    """Pure, Tk-free: display truncation must never touch saved/draft content."""

    def test_short_text_is_unchanged(self):
        self.assertEqual(view.truncate_for_display("hello\nworld"), "hello\nworld")

    def test_an_extremely_long_line_is_truncated_with_a_visible_mark(self):
        huge = "A" * 10_000
        out = view.truncate_for_display(huge, max_line_chars=100, max_chars=1_000_000)
        self.assertLess(len(out), len(huge))
        self.assertIn(view.TRUNCATION_MARK, out)
        self.assertTrue(out.startswith("A" * 100))

    def test_total_length_is_capped_even_with_many_short_lines(self):
        text = "\n".join(["line"] * 10_000)
        out = view.truncate_for_display(text, max_chars=500)
        self.assertLessEqual(len(out), 500 + len(view.TRUNCATION_MARK))
        self.assertIn(view.TRUNCATION_MARK, out)

    def test_control_characters_are_sanitized(self):
        out = view.truncate_for_display("a\x00\x07b\tc\nd")
        self.assertNotIn("\x00", out)
        self.assertNotIn("\x07", out)
        self.assertIn("\t", out)
        self.assertIn("\n", out)

    def test_row_title_collapses_newlines_and_caps_length(self):
        out = view.row_title("line1\nline2\tline3" + "x" * 200)
        self.assertNotIn("\n", out)
        self.assertNotIn("\t", out)
        self.assertLessEqual(len(out), view.ROW_TITLE_MAX + len(view.TRUNCATION_MARK))

    def test_row_title_tolerates_tk_format_like_strings(self):
        # A title crafted to look like a Tk/format directive must come through as plain text.
        nasty = "%s{bg=red} ${HOME} }{" + "\x1b[31m"
        out = view.row_title(nasty)
        self.assertNotIn("\x1b", out)

    def test_row_line_includes_kind_app_title_and_status(self):
        report = make_report(kind="request", severity="note", title="画面が遅い")
        row = inbox.ReportRow(report, None)
        line = view.row_line(row)
        self.assertIn("仕様変更の希望", line)
        self.assertIn("お品書き", line)
        self.assertIn("画面が遅い", line)
        self.assertIn("未対応", line)


class _FakeReportListbox:
    def __init__(self, rows):
        self.rows = rows
        self.selection = None
        self.focused = False

    def size(self):
        return len(self.rows)

    def nearest(self, y):
        if not self.rows:
            return 0
        best = 0
        for i, (top, _height) in enumerate(self.rows):
            if y < top:
                break
            best = i
        return best

    def bbox(self, index):
        if index is None or not (0 <= index < len(self.rows)):
            return None
        top, height = self.rows[index]
        return (0, top, 200, height)

    def selection_clear(self, _start, _end):
        self.selection = None

    def selection_set(self, index):
        self.selection = index

    def focus_set(self):
        self.focused = True


class _FakeReportsWindow:
    """Stands in for the parts of ReportsInboxWindow that the click handlers touch."""

    def __init__(self, rows, identities):
        self.report_list = _FakeReportListbox(rows)
        self.visible_rows = [SimpleNamespace(report=SimpleNamespace(identity=i)) for i in identities]
        self.selected_identity = None
        self.shown = []

    def _show_detail(self, row):
        self.shown.append(row)

    _on_report_click = view.ReportsInboxWindow._on_report_click
    _on_report_drag = view.ReportsInboxWindow._on_report_drag
    _on_report_selected = view.ReportsInboxWindow._on_report_selected


class ReportListClickWiringTests(unittest.TestCase):
    """Selection changes only on a real in-row click; margin clicks, scroll and drag must not
    change it (same contract as orchestrator_view's run list)."""

    def test_clicking_a_row_selects_it(self):
        win = _FakeReportsWindow([(0, 20), (20, 20), (40, 20)], ["id0", "id1", "id2"])
        result = view.ReportsInboxWindow._on_report_click(win, SimpleNamespace(y=25))
        self.assertEqual(result, "break")
        self.assertEqual(win.selected_identity, "id1")
        self.assertEqual(len(win.shown), 1)
        self.assertTrue(win.report_list.focused)

    def test_margin_click_leaves_selection_untouched(self):
        win = _FakeReportsWindow([(0, 20), (20, 20), (40, 20)], ["id0", "id1", "id2"])
        win.selected_identity = "id0"
        result = view.ReportsInboxWindow._on_report_click(win, SimpleNamespace(y=9000))
        self.assertEqual(result, "break")
        self.assertEqual(win.selected_identity, "id0")
        self.assertEqual(win.shown, [])

    def test_drag_motion_never_changes_selection(self):
        win = _FakeReportsWindow([(0, 20), (20, 20)], ["id0", "id1"])
        win.selected_identity = "id0"
        result = view.ReportsInboxWindow._on_report_drag(win, SimpleNamespace(y=25))
        self.assertEqual(result, "break")
        self.assertEqual(win.selected_identity, "id0")
        self.assertEqual(win.shown, [])


def make_shared_folder(root: Path) -> Path:
    (root / "reports" / "pending").mkdir(parents=True)
    return root


def write_report(directory: Path, name: str, **overrides) -> Path:
    import json
    fields = dict(
        schema_version=1, report_id=name, created_at="2026-01-01T00:00:00Z", kind="bug",
        severity="stopped", title="t-" + name, body="body-" + name, reporter="u",
        app_id="app", display_name="App", release_id="rel", git_commit="a" * 40,
        version_source="src", pc_name="pc",
    )
    fields.update(overrides)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# Fake tk / ttk widget set used only to build a *full* ReportsInboxWindow Tk-free: these
# replace reports_inbox_view's own `tk` / `ttk` module references (see ReportsInboxWindowCase
# below), so ReportsInboxWindow's real __init__ / _tick / _decide / ... code runs against
# these stand-ins instead of ever calling tk.Tk()/tk.Toplevel() for real. Geometry-based
# click resolution is already covered Tk-free above by ReportListClickWiringTests, so the
# listbox fake here only needs to track inserted content and the handful of selection calls
# the window itself issues.
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


class _FakeButton(_FakeTkWidget):
    def __init__(self, master=None, *, command=None, **kwargs):
        super().__init__(master, **kwargs)
        self.command = command
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


class _FakeContentListbox:
    def __init__(self, master=None, **_kwargs):
        self.items: list = []
        self.selection = None
        self.focused = False

    def configure(self, **_kwargs):
        pass

    def pack(self, **_kwargs):
        pass

    def grid(self, **_kwargs):
        pass

    def bind(self, _sequence, _func):
        pass

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


class _FakeText:
    def __init__(self, master=None, **_kwargs):
        self.content = ""

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

    def clipboard_clear(self):
        pass

    def clipboard_append(self, _text):
        pass


_FAKE_TK_MODULE = SimpleNamespace(
    Toplevel=_FakeToplevel, BooleanVar=_FakeVar, StringVar=_FakeVar,
    Listbox=_FakeContentListbox, Text=_FakeText, TclError=tk.TclError,
)
_FAKE_TTK_MODULE = SimpleNamespace(
    Frame=_FakeTkWidget, LabelFrame=_FakeTkWidget, Label=_FakeTkWidget,
    Button=_FakeButton, Checkbutton=_FakeTkWidget,
)


class ReportsInboxWindowCase(unittest.TestCase):
    def setUp(self):
        self.decisions_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.decisions_tmp.cleanup)
        self.decisions_scope = mock.patch.object(inbox, "decisions_root", return_value=Path(self.decisions_tmp.name))
        self.decisions_scope.start()
        self.addCleanup(self.decisions_scope.stop)
        tk_patch = mock.patch.object(view, "tk", _FAKE_TK_MODULE)
        tk_patch.start()
        self.addCleanup(tk_patch.stop)
        ttk_patch = mock.patch.object(view, "ttk", _FAKE_TTK_MODULE)
        ttk_patch.start()
        self.addCleanup(ttk_patch.stop)
        self.master = object()
        self.window = None
        self.addCleanup(self._destroy)

    def _destroy(self):
        if self.window is not None and self.window.exists():
            self.window.close()

    def make_window(self, *, apps=None, scan_fn=None, clipboard=None, reports_config_fn=None):
        scan_fn = scan_fn or inbox.scan_all
        if reports_config_fn is not None:
            self.window = view.ReportsInboxWindow(self.master, scan_fn=scan_fn, copy_to_clipboard=clipboard,
                                                  reports_config_fn=reports_config_fn)
            return self.window
        apps = apps if apps is not None else [("app-a", "アプリA", "configured")]
        self.window = view.ReportsInboxWindow(self.master, configured_apps=lambda: apps, scan_fn=scan_fn,
                                              copy_to_clipboard=clipboard)
        return self.window

    def pump(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.window._tick()
            time.sleep(0.01)
        self.assertTrue(condition())


class LoadAndDisplayTests(ReportsInboxWindowCase):
    def test_connection_status_newest_first_unresolved_filter_and_broken_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            pending = share / "reports" / "pending"
            write_report(pending, "old", created_at="2026-01-01T00:00:00Z")
            write_report(pending, "new", created_at="2026-06-01T00:00:00Z")
            (pending / "broken.json").write_text("{not json", encoding="utf-8")
            apps = [("app-a", "アプリA", str(share)), ("app-b", "アプリB", "")]
            window = self.make_window(apps=apps)
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))

            self.assertEqual(window.app_status_vars["app-a"].get(),
                              f"接続できました（{inbox.truncate_path_for_display(str(share))}）")
            self.assertIn("未設定", window.app_status_vars["app-b"].get())
            self.assertEqual([r.report.report_id for r in window.visible_rows], ["new", "old"])
            self.assertEqual(window.report_list.get(0, "end").__len__(), 2)
            self.assertEqual(window.broken_list.get(0, "end").__len__(), 1)
            self.assertIn("broken.json", window.broken_list.get(0, "end")[0])

            inbox.save_decision("app-a", "old", "skip")
            window.reload()
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            window.unresolved_only_var.set(True)
            window._render_rows()
            self.assertEqual([r.report.report_id for r in window.visible_rows], ["new"])

    def test_unreachable_but_configured_app_still_shows_the_path_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            config = inbox.ReportsConfig(
                apps=[inbox.ConfiguredApp("app-a", "アプリA", str(missing), "repo")], notices=[])
            window = self.make_window(reports_config_fn=lambda: config)
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            status = window.app_status_vars["app-a"].get()
            self.assertIn("接続できません", status)
            self.assertIn(inbox.truncate_path_for_display(str(missing)), status)
            self.assertIn("リポジトリ設定", status)

    def test_unconfigured_app_shows_未設定_without_affecting_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            write_report(share / "reports" / "pending", "r1")
            apps = [("ok", "OKアプリ", str(share)), ("missing", "未設定アプリ", "")]
            window = self.make_window(apps=apps)
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            self.assertEqual(window.app_status_vars["ok"].get(),
                              f"接続できました（{inbox.truncate_path_for_display(str(share))}）")
            self.assertIn("未設定", window.app_status_vars["missing"].get())


class ConfigNoticeAndSourceDisplayTests(ReportsInboxWindowCase):
    """DCC Task 8c: the window must open and show config-mistake notices even when the local or
    repo toml is broken (4c), must warn about an unknown [reports.<name>] without adding it to
    the app list (4b), and must show which source (local/repo) supplied a reachable app's path
    (5), all with fake widgets and no real Tk, shared folder, or LOCALAPPDATA."""

    def test_window_opens_and_shows_notices_when_config_is_broken(self):
        config = inbox.ReportsConfig(apps=[], notices=["ローカル設定を読めません: bad toml",
                                                         "リポジトリ設定を読めません: bad toml"])
        window = self.make_window(reports_config_fn=lambda: config)
        self.assertTrue(window.exists())
        self.assertIn("ローカル設定を読めません: bad toml", window.config_notice_var.get())
        self.assertIn("リポジトリ設定を読めません: bad toml", window.config_notice_var.get())

    def test_unknown_config_name_warns_and_is_not_in_the_app_list(self):
        config = inbox.ReportsConfig(
            apps=[inbox.ConfiguredApp("app-a", "アプリA", "", "")],
            notices=["未知の設定名: totally-unknown-app（綴りを確認してください）"],
        )
        window = self.make_window(reports_config_fn=lambda: config)
        self.assertIn("未知の設定名: totally-unknown-app（綴りを確認してください）", window.config_notice_var.get())
        self.assertEqual(set(window.app_status_vars), {"app-a"})

    def test_window_opens_and_shows_a_notice_when_the_local_toml_is_not_valid_utf8(self):
        # Exercises the real loader (inbox.load_reports_config), not an injected ReportsConfig:
        # tomllib.load() decodes as UTF-8 internally, and a malformed-encoding local file must
        # become a notice, not an uncaught UnicodeDecodeError that aborts window construction.
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.toml"
            registry.write_text('[branches]\napp-a = "main"\n\n[reports.app-a]\nshared_root = ""\n',
                                 encoding="utf-8")
            local = Path(tmp) / "local.toml"
            local.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
            window = self.make_window(
                reports_config_fn=lambda: inbox.load_reports_config(registry, local))
        self.assertTrue(window.exists())
        self.assertIn("ローカル設定を読めません", window.config_notice_var.get())

    def test_window_opens_and_shows_a_notice_when_the_repo_toml_is_not_valid_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.toml"
            registry.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
            local = Path(tmp) / "local.toml"
            window = self.make_window(
                reports_config_fn=lambda: inbox.load_reports_config(registry, local))
        self.assertTrue(window.exists())
        self.assertIn("リポジトリ設定を読めません", window.config_notice_var.get())

    def test_reachable_app_status_shows_the_used_path_and_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            write_report(share / "reports" / "pending", "r1")
            config = inbox.ReportsConfig(
                apps=[inbox.ConfiguredApp("app-a", "アプリA", str(share), "local")], notices=[])
            window = self.make_window(reports_config_fn=lambda: config)
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            self.assertEqual(window.app_status_vars["app-a"].get(),
                              f"接続できました（{inbox.truncate_path_for_display(str(share))}）（ローカル設定）")

    def test_a_very_long_path_and_control_characters_do_not_break_the_status_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            write_report(share / "reports" / "pending", "r1")
            nasty_root = str(share) + "\x00\x1b" + "x" * 500
            config = inbox.ReportsConfig(
                apps=[inbox.ConfiguredApp("app-a", "アプリA", nasty_root, "repo")], notices=[])
            # scan_app itself only ever reads the real (clean) `share` path; what's under test
            # here is that the *displayed* status text for the (fake, nasty) configured value
            # never breaks, independent of whether that value happens to be reachable.
            window = self.make_window(reports_config_fn=lambda: config,
                                       scan_fn=lambda apps: [inbox.AppInbox("app-a", "アプリA", True, "")])
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            status = window.app_status_vars["app-a"].get()
            self.assertNotIn("\x00", status)
            self.assertNotIn("\x1b", status)
            self.assertIn("リポジトリ設定", status)
            self.assertLess(len(status), 200)


class BackgroundLoadSafetyTests(ReportsInboxWindowCase):
    def test_hanging_scan_disables_reload_but_never_blocks_the_ui(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def hanging_scan(apps):
            release.wait(10)
            return []

        window = self.make_window(scan_fn=hanging_scan)
        self.pump(lambda: window.reload_button.instate(["disabled"]))
        # the UI thread stays responsive: toggling the checkbox does not raise or hang
        window.unresolved_only_var.set(True)
        window._render_rows()
        self.assertEqual(window.notice_var.get(), "読み込み中…")
        release.set()
        self.pump(lambda: window.reload_button.instate(["!disabled"]))

    def test_closing_before_a_hanging_scan_returns_touches_no_widget_and_raises_nothing(self):
        release = threading.Event()
        worker_done = threading.Event()
        self.addCleanup(release.set)

        def hanging_scan(apps):
            release.wait(10)
            worker_done.set()
            return []

        class _ExplodingWidget:
            """Stands in for every widget the post-close event path could touch; any attribute
            access (set/get/insert/...) is itself the failure, so no assertion can be skipped."""

            def __getattr__(self, name):
                raise AssertionError(f"widget touched after window.close(): .{name}")

        window = self.make_window(scan_fn=hanging_scan)
        self.pump(lambda: window.reload_button.instate(["disabled"]))
        window.close()
        self.assertFalse(window.exists())
        # Swap in exploding stand-ins for everything _tick / _apply_inboxes would touch: if the
        # cancelled _tick ever fired again, or the worker's late result reached _apply_inboxes,
        # the very first attribute access below would raise instead of silently succeeding.
        window.notice_var = _ExplodingWidget()
        window.reload_button = _ExplodingWidget()
        window.report_list = _ExplodingWidget()
        window.broken_list = _ExplodingWidget()
        window.app_status_vars = _ExplodingWidget()
        release.set()
        self.assertTrue(worker_done.wait(5))  # the worker actually ran past the release point
        # even a direct call to the (closed) tick must stop at its own `if self._closed: return`
        # guard before touching any of the exploding stand-ins above.
        window._tick()


class DecisionAndDraftTests(ReportsInboxWindowCase):
    def test_decision_is_saved_locally_reflected_in_the_row_and_shared_folder_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            write_report(share / "reports" / "pending", "r1")
            apps = [("app-a", "アプリA", str(share))]
            window = self.make_window(apps=apps)
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))

            def snapshot_bytes():
                return {str(p.relative_to(share)): p.read_bytes() for p in share.rglob("*") if p.is_file()}

            before = snapshot_bytes()
            window.selected_identity = window.visible_rows[0].report.identity
            window._decide("handle")
            self.assertEqual(before, snapshot_bytes())
            self.assertEqual(inbox.load_decision("app-a", "r1").decision, "handle")
            self.assertIn("対応する", window.report_list.get(0, "end")[0])

            window._decide("skip")
            self.assertEqual(inbox.load_decision("app-a", "r1").decision, "skip")
            self.assertIn("見送る", window.report_list.get(0, "end")[0])
            self.assertEqual(before, snapshot_bytes())

    def test_handle_and_investigate_build_a_draft_copyable_to_clipboard_skip_clears_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            write_report(share / "reports" / "pending", "r1")
            apps = [("app-a", "アプリA", str(share))]
            copied = []
            window = self.make_window(apps=apps, clipboard=lambda text: copied.append(text))
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            window.selected_identity = window.visible_rows[0].report.identity

            window._decide("handle")
            draft = window.draft_text.get("1.0", "end-1c")
            self.assertIn("Orchestratorへの依頼文", draft)
            self.assertTrue(window.copy_button.instate(["!disabled"]))
            window.copy_draft()
            self.assertEqual(copied, [draft])

            window._decide("investigate")
            draft2 = window.draft_text.get("1.0", "end-1c")
            self.assertIn("実機調査の依頼文", draft2)

            window._decide("skip")
            self.assertEqual(window.draft_text.get("1.0", "end-1c"), "")
            self.assertTrue(window.copy_button.instate(["disabled"]))

    def test_very_long_and_control_character_report_does_not_break_the_detail_pane(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = make_shared_folder(Path(tmp) / "share")
            nasty_title = "x" * 5000 + "\n\x00\x1b[31m" + "y" * 5000
            nasty_body = ("line" + "z" * 3000 + "\n") * 5 + "\x07control\x00chars"  # stays under MAX_REPORT_BYTES
            write_report(share / "reports" / "pending", "r1", title=nasty_title, body=nasty_body)
            apps = [("app-a", "アプリA", str(share))]
            window = self.make_window(apps=apps)
            self.pump(lambda: window.notice_var.get().startswith("読み込み完了"))
            report = window.visible_rows[0].report
            window.selected_identity = report.identity
            window._show_detail(window.visible_rows[0])
            detail = window.detail_text.get("1.0", "end-1c")
            self.assertIn(view.TRUNCATION_MARK, detail)
            self.assertNotIn("\x00", detail)
            self.assertNotIn("\x1b", detail)

            # Truncation is display-only. The draft text widget must never grow to the full
            # report's size (it is truncated like the detail pane), but the content actually
            # saved / copied is Task 8a's own, untruncated draft. build_handle_draft mixes in a
            # fresh random boundary token each call, so pin it to compare two independent calls.
            with mock.patch("scripts.dev_control_center.reports_inbox.secrets.token_hex", return_value="f" * 32):
                window._decide("handle")
                full_draft = inbox.build_handle_draft(report)
            self.assertEqual(window._draft_full, full_draft)
            self.assertIn("z" * 3000, window._draft_full)
            shown_draft = window.draft_text.get("1.0", "end-1c")
            self.assertIn(view.TRUNCATION_MARK, shown_draft)
            self.assertNotIn("z" * 3000, shown_draft)
            copied = []
            window._copy_to_clipboard = copied.append
            window.copy_draft()
            self.assertEqual(copied, [full_draft])


class _FakeInboxWindow:
    """Stands in for reports_inbox_view.ReportsInboxWindow in the entrance test: it must never
    construct a real ReportsInboxWindow, since that would read the *real*
    dev_control_center_repos.toml and scan whatever shared folder is configured on this machine.
    Records how many times it was constructed so "never duplicated" is an actual assertion."""

    instances: list["_FakeInboxWindow"] = []

    def __init__(self, master, **_kwargs):
        self.master = master
        self._exists = True
        self.focus_calls = 0
        _FakeInboxWindow.instances.append(self)

    def exists(self) -> bool:
        return self._exists

    def focus(self) -> None:
        self.focus_calls += 1

    def close(self) -> None:
        self._exists = False


class AppReportsButtonTests(unittest.TestCase):
    """DCC main screen entrance: the 報告 button opens (or focuses, never duplicates) the
    inbox, and closing DCC with it open never raises. No real (or fake) Tk widget is built
    anywhere here: App.__init__ -- which is what would build the real main screen, with its
    own treeview/combobox/etc. widgets -- is bypassed entirely via __new__, and only the two
    methods Task 8b touches (open_reports_inbox, _on_close) run, against a bare instance with
    just the handful of attributes those two methods read or write."""

    def setUp(self):
        _FakeInboxWindow.instances.clear()
        fake_window_patch = mock.patch("scripts.dev_control_center.reports_inbox_view.ReportsInboxWindow", _FakeInboxWindow)
        fake_window_patch.start()
        self.addCleanup(fake_window_patch.stop)
        dcc.ACTIVE_OPERATIONS.clear()
        self.addCleanup(dcc.ACTIVE_OPERATIONS.clear)
        timing_patch = mock.patch.object(dcc.TIMING, "enabled", False)
        timing_patch.start()
        self.addCleanup(timing_patch.stop)
        self.destroyed = False
        self.app = dcc.App.__new__(dcc.App)
        self.app.master = SimpleNamespace(destroy=self._note_destroyed)
        self.app.reports_window = None

    def _note_destroyed(self):
        self.destroyed = True

    def test_main_screen_wires_a_reports_button_to_open_reports_inbox(self):
        source = inspect.getsource(dcc.App.__init__) + inspect.getsource(dcc.App._build)
        self.assertIn("self.reports_button", source)
        self.assertIn("command=self.open_reports_inbox", source)

    def test_opening_twice_focuses_the_existing_window_instead_of_duplicating(self):
        self.app.open_reports_inbox()
        window = self.app.reports_window
        self.assertIsInstance(window, _FakeInboxWindow)
        self.assertIs(window, _FakeInboxWindow.instances[0])
        self.assertEqual(len(_FakeInboxWindow.instances), 1)
        self.assertTrue(window.exists())

        self.app.open_reports_inbox()
        self.assertIs(self.app.reports_window, window)  # focused, not duplicated
        self.assertEqual(len(_FakeInboxWindow.instances), 1)
        self.assertEqual(window.focus_calls, 1)

        window.close()
        self.assertFalse(window.exists())

    def test_closing_dcc_with_the_inbox_open_does_not_raise(self):
        self.app.open_reports_inbox()
        window = self.app.reports_window
        self.assertTrue(window.exists())
        self.app._closed = False
        self.app._badge_stop = threading.Event()
        self.app.orchestrator_window = None
        self.app.selection = SimpleNamespace(close=lambda: None)
        self.app._on_close()  # must not raise even though the inbox window is still open
        self.assertTrue(self.app._closed)
        self.assertFalse(window.exists())  # the inbox is closed along with DCC
        self.assertTrue(self.destroyed)


if __name__ == "__main__":
    unittest.main()
