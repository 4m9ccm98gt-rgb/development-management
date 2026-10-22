"""DCC Task WF-6c: the "自動処理の状況" window -- a Tk client of automation_status.py's own
read-only snapshot. This window never starts, changes, or approves anything: it only reads the
shared activity record and each automatic-processing module's own settings (via
automation_status.build_snapshot) and displays the result. Every value shown is one of
automation_status.py's own fixed words/ids/numbers/timestamps -- never a report body, Task/plan
body, AI free-text output, a path, or an exception's own text.

Reviewer finding 3 (this revision): automation_status.build_snapshot can block for several
seconds (reports_inbox.scan_all's own SCAN_TIMEOUT_SECONDS wait on an unresponsive shared folder,
reached via auto.peek_next_report_id). Calling it straight from the Tk tick would freeze this
window's own event loop -- and, since Tk's mainloop is shared with the rest of DCC, the whole
main screen too. Every tick now starts the fetch on a background thread (never touching a Tk
widget there -- same "plain queue.Queue, drained only from an .after() tick on the Tk thread"
convention app.py's own _start_orchestrator_badge already uses for exactly this reason) and only
applies whatever the most recent completed fetch produced; a slow/hanging fetch delays what is
shown, never this window's own responsiveness or close()."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from . import activity_log
from . import automation_status as status

TICK_MS = 10_000

ROLE_COLUMNS = (
    ("role", "役割", 110),
    ("state", "状態", 90),
    ("reason", "現在の理由", 150),
    ("last_at", "最後の活動", 150),
    ("last_result", "最後の結果", 140),
    ("last_reason", "最後の理由", 170),
    ("hint", "対応", 320),
)
RECENT_COLUMNS = (
    ("time", "時刻", 150),
    ("role", "役割", 110),
    ("action", "動作", 70),
    ("target", "対象", 220),
    ("result", "結果", 140),
    ("reason", "理由", 170),
)


def target_text(entry: "activity_log.ActivityEntry") -> str:
    """The 対象 column: both fields are already this module's own closed vocabulary / an
    already-hashed or already-validated identifier (activity_log._validate enforces the exact
    shape per target_type) -- never report/Task/AI free text or a path."""
    if entry.target_type == activity_log.TARGET_NONE:
        return entry.target_type
    return f"{entry.target_type} {entry.target_id}"


class _Table:
    """A small, reusable Treeview + scrollbars, dark-themed the same way
    reports_inbox_view._ReportTable already is -- used for both tables this window shows (役割
    ごとの状態 / 最近の活動), so they share exactly one dark-mode implementation."""

    def __init__(self, master, columns: tuple[tuple[str, str, int], ...], *, style_prefix: str) -> None:
        self._style_prefix = style_prefix
        self.frame = ttk.Frame(master)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            self.frame, columns=[c[0] for c in columns], show="headings",
            selectmode="none", style=f"{style_prefix}.Treeview")
        for key, heading, width in columns:
            self.tree.heading(key, text=heading, anchor="w")
            self.tree.column(key, width=width, minwidth=width, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        horizontal = self.horizontal = ttk.Scrollbar(self.frame, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        vertical = self.vertical = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        self.tree.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self._theme_key = None
        self.frame.bind("<<ThemeChanged>>", self._apply_theme, add="+")
        self._apply_theme()

    def _apply_theme(self, _event=None) -> None:
        from .app import (DARK_ACCENT, DARK_BG, DARK_BORDER, DARK_DISABLED_BG, DARK_FG, DARK_FIELD,
                          DARK_MUTED, DARK_SELECTION, DARK_SURFACE)

        style = ttk.Style(self.frame)
        key = (style.theme_use(), style.lookup("TFrame", "background"))
        if key == self._theme_key:
            return
        self._theme_key = key
        dark = key[1] == DARK_BG
        prefix = self._style_prefix
        if dark:
            style.configure(f"{prefix}.TFrame", background=DARK_BG)
            style.configure(f"{prefix}.Treeview", background=DARK_SURFACE, fieldbackground=DARK_SURFACE,
                            foreground=DARK_FG, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER,
                            darkcolor=DARK_BORDER)
            style.map(f"{prefix}.Treeview", background=[("selected", DARK_SELECTION)],
                      foreground=[("selected", DARK_FG)])
            style.configure(f"{prefix}.Treeview.Heading", background=DARK_FIELD, foreground=DARK_FG,
                            bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
            style.map(f"{prefix}.Treeview.Heading",
                      background=[("pressed", DARK_SELECTION), ("active", DARK_FIELD)],
                      foreground=[("disabled", DARK_MUTED), ("active", DARK_FG)])
            for orientation in ("Horizontal", "Vertical"):
                name = f"{prefix}.{orientation}.TScrollbar"
                style.configure(name, background=DARK_FIELD, troughcolor=DARK_BG, arrowcolor=DARK_FG,
                                bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
                style.map(name, background=[("disabled", DARK_DISABLED_BG), ("pressed", DARK_SELECTION),
                                           ("active", DARK_ACCENT)],
                          arrowcolor=[("disabled", DARK_MUTED), ("active", DARK_FG)])
        # Native light styles are left untouched; ttk styles are local to each theme.
        self.frame.configure(style=f"{prefix}.TFrame" if dark else "TFrame")
        self.tree.configure(style=f"{prefix}.Treeview" if dark else "Treeview")
        self.horizontal.configure(style=f"{prefix}.Horizontal.TScrollbar" if dark else "Horizontal.TScrollbar")
        self.vertical.configure(style=f"{prefix}.Vertical.TScrollbar" if dark else "Vertical.TScrollbar")

    def grid(self, **kwargs) -> None:
        self.frame.grid(**kwargs)

    def set_rows(self, rows: list[tuple]) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in rows:
            self.tree.insert("", "end", values=row)


class AutomationStatusWindow:
    """DCC Task WF-6c: opened (or focused) from the DCC main screen's own「自動処理の状況」button.
    Fetches a fresh automation_status.StatusSnapshot on a background thread every tick (default
    10 seconds, see the module docstring's own Reviewer finding 3) and displays whatever the most
    recently completed fetch produced; never starts, changes, or approves anything -- see this
    module's own docstring."""

    def __init__(self, master: tk.Misc, *, snapshot_fn: Callable[[], "status.StatusSnapshot"] | None = None,
                 tick_ms: int = TICK_MS) -> None:
        from .app import DARK_BG

        self._snapshot_fn = snapshot_fn or status.build_snapshot
        self._tick_ms = tick_ms
        self._closed = False
        self._fetch_in_flight = False
        self._result_queue: "queue.Queue" = queue.Queue(maxsize=1)

        self.window = tk.Toplevel(master)
        self.window.title("自動処理の状況")
        self.window.geometry("1040x760")
        self.window.minsize(900, 600)
        self.window.configure(background=DARK_BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.log_notice_var = tk.StringVar(value="")
        self.next_report_var = tk.StringVar(value=status.NO_NEXT_REPORT_TEXT)
        self.not_running_reason_var = tk.StringVar(value="")

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, textvariable=self.log_notice_var, foreground="#e3b341").grid(
            row=0, column=0, sticky="w", pady=(0, 6))

        role_box = ttk.LabelFrame(outer, text="役割ごとの状態", padding=8)
        role_box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        role_box.columnconfigure(0, weight=1)
        self.role_table = _Table(role_box, ROLE_COLUMNS, style_prefix="RoleStatus")
        self.role_table.grid(row=0, column=0, sticky="nsew")

        recent_box = ttk.LabelFrame(outer, text="最近の活動（新しい順・最大100件）", padding=8)
        recent_box.grid(row=2, column=0, sticky="nsew")
        recent_box.columnconfigure(0, weight=1)
        recent_box.rowconfigure(0, weight=1)
        self.recent_table = _Table(recent_box, RECENT_COLUMNS, style_prefix="RecentActivity")
        self.recent_table.grid(row=0, column=0, sticky="nsew")

        bottom_box = ttk.LabelFrame(outer, text="自動調査の次と、動いていない理由", padding=8)
        bottom_box.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(bottom_box, text="次に調査される報告:").grid(row=0, column=0, sticky="w")
        ttk.Label(bottom_box, textvariable=self.next_report_var).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(bottom_box, text="動いていない理由:").grid(row=1, column=0, sticky="w")
        ttk.Label(bottom_box, textvariable=self.not_running_reason_var).grid(row=1, column=1, sticky="w", padx=(6, 0))

        self._tick_id = self.window.after(0, self._tick)

    # ---------------------------------------------------------------- lifecycle
    def exists(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()

    def close(self) -> None:
        """Never waits on a background fetch: a fetch already running keeps running to
        completion on its own daemon thread (it only ever touches a plain queue.Queue, never a Tk
        widget -- see _start_fetch below), harmlessly dropped once this window is gone."""
        if self._closed:
            return
        self._closed = True
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        self.window.destroy()

    # ---------------------------------------------------------------- refresh
    def _tick(self) -> None:
        if self._closed:
            return
        self._start_fetch()
        self._drain_fetch_result()
        self._tick_id = self.window.after(self._tick_ms, self._tick)

    def _start_fetch(self) -> None:
        """Runs automation_status.build_snapshot on a background thread -- it may block for
        several seconds (Reviewer finding 3) -- and never starts a second one while the first is
        still in flight. The worker thread touches nothing but the plain result queue; every Tk
        widget update happens later, back on the Tk thread, inside _drain_fetch_result/_apply."""
        if self._fetch_in_flight:
            return
        self._fetch_in_flight = True
        snapshot_fn, result_queue = self._snapshot_fn, self._result_queue

        def work() -> None:
            try:
                snapshot = snapshot_fn()
            except Exception:  # noqa: BLE001 - a broken snapshot must never crash this screen
                snapshot = None
            try:
                result_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                result_queue.put_nowait(snapshot)
            except queue.Full:
                pass

        threading.Thread(target=work, name="dcc-automation-status-fetch", daemon=True).start()

    def _drain_fetch_result(self) -> None:
        try:
            snapshot = self._result_queue.get_nowait()
        except queue.Empty:
            return
        self._fetch_in_flight = False
        self._apply(snapshot)

    def _refresh(self) -> None:
        """Synchronous fetch-and-apply, kept only for tests that supply an instantly-returning
        snapshot_fn (see automation_status_view tests) -- _tick itself never calls this; it always
        goes through the non-blocking _start_fetch/_drain_fetch_result pair above."""
        try:
            snapshot = self._snapshot_fn()
        except Exception:  # noqa: BLE001 - a broken snapshot must never crash this screen
            snapshot = None
        self._apply(snapshot)

    def _apply(self, snapshot: "status.StatusSnapshot | None") -> None:
        if snapshot is None:
            self.log_notice_var.set(status.LOG_UNREADABLE_TEXT)
            self.role_table.set_rows([])
            self.recent_table.set_rows([])
            self.next_report_var.set(status.NO_NEXT_REPORT_TEXT)
            self.not_running_reason_var.set("")
            return

        self.log_notice_var.set(status.LOG_UNREADABLE_TEXT if snapshot.log_unreadable else "")
        self.role_table.set_rows([
            (role.role, role.state, role.reason, role.last_activity_at, role.last_result,
             role.last_reason, role.hint)
            for role in snapshot.roles
        ])
        self.recent_table.set_rows([
            (status.format_timestamp(entry.timestamp), entry.role, entry.action, target_text(entry),
             entry.result, entry.reason)
            for entry in snapshot.recent
        ])
        self.next_report_var.set(snapshot.next_report_id or status.NO_NEXT_REPORT_TEXT)
        self.not_running_reason_var.set(snapshot.not_running_reason or "")
