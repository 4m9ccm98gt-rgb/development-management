"""Reports inbox window (DCC Task 8b): a Tk client of reports_inbox.py's pure functions.

Report content (title, body, every other field) is untrusted free text written by a field
user through the reporting tool. This window only displays it (truncated for *display
only*; see truncate_for_display) and saves a local decision; it never writes into the
shared folder, never executes or interprets report content, and never feeds a draft to an
AI automatically — the draft text is for the developer to copy and edit elsewhere.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from . import reports_inbox as inbox
from .orchestrator_view import resolve_click_index

TICK_MS = 150
MAX_DISPLAY_CHARS = 20_000
MAX_LINE_CHARS = 2_000
ROW_TITLE_MAX = 60
TRUNCATION_MARK = "…(切り詰め)"

DECISIONS = (("handle", "対応する"), ("investigate", "実機で調べる"), ("skip", "見送る"))


def truncate_for_display(text: str, *, max_line_chars: int = MAX_LINE_CHARS, max_chars: int = MAX_DISPLAY_CHARS) -> str:
    """Display-only truncation of untrusted report text: sanitize control chars, cap each
    line, then cap the total. Never used for the saved decision or the Orchestrator draft —
    those always go through reports_inbox.py's own functions on the untruncated report."""
    sanitized = inbox.sanitize_text(text)
    lines = []
    for line in sanitized.split("\n"):
        if len(line) > max_line_chars:
            lines.append(line[:max_line_chars] + TRUNCATION_MARK)
        else:
            lines.append(line)
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        joined = joined[:max_chars] + TRUNCATION_MARK
    return joined


def row_title(text: str, *, limit: int = ROW_TITLE_MAX) -> str:
    """A list row is one line: newlines/tabs collapse to spaces before the length cap."""
    sanitized = inbox.sanitize_text(text).replace("\n", " ").replace("\t", " ")
    if len(sanitized) > limit:
        return sanitized[:limit] + TRUNCATION_MARK
    return sanitized


def row_line(row: inbox.ReportRow) -> str:
    report = row.report
    stamp = report.created_at[:16].replace("T", " ")
    return (f"[{report.kind_label}/{report.severity_label}] {report.app_display_name} "
            f"{row_title(report.title)}  {stamp}  ({row.status_label})")


def _set_enabled(widget, enabled: bool) -> None:
    if bool(widget.instate(["disabled"])) == (not enabled):
        return
    widget.state(["!disabled" if enabled else "disabled"])


class ReportsInboxWindow:
    def __init__(self, master: tk.Misc, *, configured_apps: Callable[[], list] | None = None,
                 scan_fn: Callable[[list], list] | None = None,
                 copy_to_clipboard: Callable[[str], None] | None = None,
                 reports_config_fn: Callable[[], "inbox.ReportsConfig"] | None = None,
                 on_spec_ready: Callable[[object], None] | None = None) -> None:
        from .app import DARK_BG, DARK_MUTED, configure_dark_listbox, configure_dark_text

        if reports_config_fn is not None:
            self._reports_config_fn = reports_config_fn
        elif configured_apps is not None:
            # A caller (mostly tests) supplied a fixed (app_key, display_name, shared_root) list
            # with no notice/source metadata: wrap it as a ReportsConfig with no notices and no
            # known source, so the rest of the window can treat it the same as the real thing.
            def _reports_config_fn(_apps=configured_apps):
                apps = [inbox.ConfiguredApp(key, name, root, "") for key, name, root in _apps()]
                return inbox.ReportsConfig(apps, [])
            self._reports_config_fn = _reports_config_fn
        else:
            self._reports_config_fn = inbox.load_reports_config
        self._scan_fn = scan_fn or inbox.scan_all
        self._copy_to_clipboard = copy_to_clipboard
        self._on_spec_ready = on_spec_ready
        self._source_by_key: dict[str, str] = {}
        self._shared_root_by_key: dict[str, str] = {}
        self._events: queue.Queue = queue.Queue()
        self._closed = False
        self._closed_event = threading.Event()
        self._loading = False
        self.inboxes: list = []
        self.rows: list[inbox.ReportRow] = []
        self.broken: list[inbox.BrokenReport] = []
        self.visible_rows: list[inbox.ReportRow] = []
        self.selected_identity: tuple[str, str] | None = None
        self._draft_full: str = ""

        self.window = tk.Toplevel(master)
        self.window.title("報告の受信箱")
        self.window.geometry("1180x760")
        self.window.minsize(980, 640)
        self.window.configure(background=DARK_BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.unresolved_only_var = tk.BooleanVar(value=False)
        self.notice_var = tk.StringVar(value="")
        self.config_notice_var = tk.StringVar(value="")

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(3, weight=1)

        ttk.Label(outer, textvariable=self.config_notice_var, foreground=DARK_MUTED,
                  wraplength=1100, justify="left").grid(row=0, column=0, columnspan=2, sticky="ew")

        # Config notices (unknown [reports.*] name, unreadable local/repo toml) must be visible
        # even if the background scan below never completes, so the window is never silently
        # mute about a config mistake (DCC Task 8c).
        initial_config = self._reports_config_fn()
        self._apply_config_metadata(initial_config)

        status_frame = ttk.LabelFrame(outer, text="アプリの接続状態", padding=8)
        status_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.app_status_vars: dict[str, tk.StringVar] = {}
        for col, app in enumerate(initial_config.apps):
            var = tk.StringVar(value="読み込み中…")
            self.app_status_vars[app.app_key] = var
            box = ttk.Frame(status_frame)
            box.grid(row=0, column=col, sticky="nw", padx=(0 if col == 0 else 16, 0))
            ttk.Label(box, text=app.display_name, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Label(box, textvariable=var, wraplength=220).pack(anchor="w")

        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.reload_button = ttk.Button(controls, text="再読み込み", command=self.reload)
        self.reload_button.pack(side="left")
        ttk.Checkbutton(controls, text="未対応だけ", variable=self.unresolved_only_var,
                        command=self._render_rows).pack(side="left", padx=(12, 0))
        ttk.Label(controls, textvariable=self.notice_var, foreground=DARK_MUTED).pack(side="left", padx=(12, 0))

        left = ttk.Frame(outer)
        left.grid(row=3, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        left.rowconfigure(1, weight=3)
        left.rowconfigure(4, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="報告一覧（新しい順）").grid(row=0, column=0, sticky="w")
        self.report_list = tk.Listbox(left, width=70, exportselection=False)
        configure_dark_listbox(self.report_list)
        self.report_list.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
        self.report_list.bind("<Button-1>", self._on_report_click)
        self.report_list.bind("<B1-Motion>", self._on_report_drag)
        ttk.Label(left, text="読めない報告").grid(row=3, column=0, sticky="w")
        self.broken_list = tk.Listbox(left, width=70, height=6, exportselection=False)
        configure_dark_listbox(self.broken_list)
        self.broken_list.grid(row=4, column=0, sticky="nsew", pady=(4, 0))

        right = ttk.Frame(outer)
        right.grid(row=3, column=1, sticky="nsew", pady=(8, 0))
        right.rowconfigure(1, weight=1)
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="詳細").grid(row=0, column=0, sticky="w")
        self.detail_text = tk.Text(right, height=14, state="disabled", wrap="word")
        configure_dark_text(self.detail_text)
        self.detail_text.grid(row=1, column=0, sticky="nsew")

        decision_frame = ttk.Frame(right)
        decision_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.decision_buttons: dict[str, ttk.Button] = {}
        for key, label in DECISIONS:
            button = ttk.Button(decision_frame, text=label, command=lambda k=key: self._decide(k))
            button.pack(side="left", padx=(0, 6))
            _set_enabled(button, False)
            self.decision_buttons[key] = button
        # DCC Task 11: opens an acceptance-criteria edit dialog that, on confirm, builds a spec
        # file and hands it to the Orchestrator start form. Separate widget/command from
        # decision_buttons["handle"] above (which only records a local decision + copyable draft,
        # Task 8a) — neither changes the other's behaviour.
        self.handle_spec_button = ttk.Button(decision_frame, text="対応する", command=self._open_handle_spec_dialog)
        self.handle_spec_button.pack(side="left", padx=(12, 0))
        _set_enabled(self.handle_spec_button, False)

        ttk.Label(right, text="依頼文の下書き（コピーして編集してください）").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.draft_text = tk.Text(right, height=10, wrap="word")
        configure_dark_text(self.draft_text)
        self.draft_text.grid(row=4, column=0, sticky="nsew")
        self.copy_button = ttk.Button(right, text="下書きをコピー", command=self.copy_draft)
        self.copy_button.grid(row=5, column=0, sticky="e", pady=(4, 0))
        _set_enabled(self.copy_button, False)

        self._tick_id = self.window.after(TICK_MS, self._tick)
        self._start_load()

    # ---------------------------------------------------------------- lifecycle
    def exists(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._closed_event.set()
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        self.window.destroy()

    # ---------------------------------------------------------------- loading
    def _apply_config_metadata(self, config) -> None:
        self.config_notice_var.set("\n".join(config.notices))
        self._source_by_key = {app.app_key: app.source for app in config.apps}
        self._shared_root_by_key = {app.app_key: app.shared_root for app in config.apps}

    def reload(self) -> None:
        self._start_load()

    def _start_load(self) -> None:
        if self._loading:
            return
        self._loading = True
        _set_enabled(self.reload_button, False)
        self.notice_var.set("読み込み中…")
        config = self._reports_config_fn()
        self._apply_config_metadata(config)
        events, closed = self._events, self._closed_event
        scan_fn = self._scan_fn
        apps = [(app.app_key, app.display_name, app.shared_root) for app in config.apps]

        def work() -> None:
            try:
                outcome = ("ok", scan_fn(apps))
            except Exception as exc:  # noqa: BLE001 - one bad scan must not break the window
                outcome = ("error", f"{type(exc).__name__}: {exc}")
            if not closed.is_set():
                events.put(outcome)

        threading.Thread(target=work, name="reports-inbox-load", daemon=True).start()

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        try:
            while True:
                kind, value = self._events.get_nowait()
                if kind == "ok":
                    self._apply_inboxes(value)
                else:
                    self.notice_var.set(f"読み込みに失敗しました: {value}")
                self._loading = False
                _set_enabled(self.reload_button, True)
        except queue.Empty:
            pass
        self._tick_id = self.window.after(TICK_MS, self._tick)

    def _apply_inboxes(self, inboxes: list) -> None:
        self.inboxes = inboxes
        by_key = {inb.app_key: inb for inb in inboxes}
        for app_key, var in self.app_status_vars.items():
            inb = by_key.get(app_key)
            if inb is None:
                var.set("未確認")
            else:
                var.set(inbox.connection_status_text(
                    inb, self._shared_root_by_key.get(app_key, ""), self._source_by_key.get(app_key, "")))
        self.rows = inbox.build_rows(inboxes)
        self.broken = inbox.all_broken(inboxes)
        self.notice_var.set(f"読み込み完了（{len(self.rows)}件 / 読めない報告 {len(self.broken)}件）")
        self._render_rows()
        self._render_broken()
        self._restore_selection()

    # ---------------------------------------------------------------- list / selection
    def _render_rows(self) -> None:
        rows = self.rows
        if self.unresolved_only_var.get():
            rows = inbox.unresolved_only(rows)
        self.visible_rows = rows
        lines = [row_line(r) for r in rows]
        self.report_list.delete(0, "end")
        for line in lines:
            self.report_list.insert("end", line)
        self._sync_listbox_selection()

    def _render_broken(self) -> None:
        self.broken_list.delete(0, "end")
        for b in self.broken:
            self.broken_list.insert("end", f"{b.app_display_name} / {b.file_name}: {b.reason}")

    def _sync_listbox_selection(self) -> None:
        self.report_list.selection_clear(0, "end")
        if self.selected_identity is None:
            return
        for index, row in enumerate(self.visible_rows):
            if row.report.identity == self.selected_identity:
                self.report_list.selection_set(index)
                break

    def _restore_selection(self) -> None:
        if self.selected_identity is None:
            return
        row = next((r for r in self.rows if r.report.identity == self.selected_identity), None)
        if row is None:
            self.selected_identity = None
            self._clear_detail()
        else:
            self._show_detail(row)
        self._sync_listbox_selection()

    def _on_report_click(self, event: tk.Event) -> str:
        index = resolve_click_index(event.y, self.report_list.size(), self.report_list.nearest, self.report_list.bbox)
        if index is not None and index < len(self.visible_rows):
            self.report_list.selection_clear(0, "end")
            self.report_list.selection_set(index)
            self.report_list.focus_set()
            self._on_report_selected(index)
        return "break"

    def _on_report_drag(self, _event: tk.Event) -> str:
        return "break"

    def _on_report_selected(self, index: int) -> None:
        row = self.visible_rows[index]
        self.selected_identity = row.report.identity
        self._show_detail(row)

    # ---------------------------------------------------------------- detail / decision
    def _show_detail(self, row: inbox.ReportRow) -> None:
        report = row.report
        fields = [
            ("種類", report.kind_label), ("度合い", report.severity_label),
            ("アプリ（設定上の名称）", report.app_display_name), ("タイトル", report.title),
            ("日時", report.created_at), ("状態", row.status_label),
            ("報告者", report.reporter), ("app_id", report.app_id),
            ("display_name（報告内）", report.display_name),
            ("release_id", report.release_id), ("git_commit", report.git_commit),
            ("version_source", report.version_source), ("PC名", report.pc_name),
            ("report_id", report.report_id), ("ファイル名", report.file_name),
            ("schema_version", str(report.schema_version)),
        ]
        lines = [f"{label}: {truncate_for_display(str(value))}" for label, value in fields]
        lines.append("")
        lines.append("本文:")
        lines.append(truncate_for_display(report.body))
        self._set_readonly_text(self.detail_text, "\n".join(lines))
        self._set_draft("")
        for button in self.decision_buttons.values():
            _set_enabled(button, True)
        _set_enabled(self.handle_spec_button, True)

    def _clear_detail(self) -> None:
        self._set_readonly_text(self.detail_text, "")
        self._set_draft("")
        for button in self.decision_buttons.values():
            _set_enabled(button, False)
        _set_enabled(self.handle_spec_button, False)

    def _selected_row(self) -> inbox.ReportRow | None:
        if self.selected_identity is None:
            return None
        return next((r for r in self.rows if r.report.identity == self.selected_identity), None)

    def _decide(self, decision_kind: str) -> None:
        row = self._selected_row()
        if row is None:
            return
        report = row.report
        decision = inbox.save_decision(report.app_key, report.report_id, decision_kind)
        self.rows = [inbox.ReportRow(r.report, decision) if r.report.identity == report.identity else r
                     for r in self.rows]
        self._render_rows()
        if decision_kind == "handle":
            draft = inbox.build_handle_draft(report)
        elif decision_kind == "investigate":
            draft = inbox.build_investigate_draft(report)
        else:
            draft = ""
        self._set_draft(draft)

    def _open_handle_spec_dialog(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        from .reports_spec_dialog import ReportSpecDialog

        ReportSpecDialog(self.window, row.report, target_repo=row.report.app_key, on_created=self._on_spec_created)

    def _on_spec_created(self, path) -> None:
        if self._on_spec_ready is not None:
            self._on_spec_ready(path)

    def _set_draft(self, text: str) -> None:
        """text is Task 8a's full, untruncated draft. It is kept in self._draft_full for
        copy_draft and tests; the Text widget only ever shows truncate_for_display(text), so a
        single very long report line in the draft cannot grow the window unboundedly."""
        self._draft_full = text
        self.draft_text.delete("1.0", "end")
        if text:
            self.draft_text.insert("1.0", truncate_for_display(text))
        _set_enabled(self.copy_button, bool(text))

    def copy_draft(self) -> None:
        text = self._draft_full
        if not text:
            return
        if self._copy_to_clipboard is not None:
            self._copy_to_clipboard(text)
        else:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
        self.notice_var.set(f"下書きをClipboardへコピーしました（{len(text):,} 文字）。")

    def _set_readonly_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if text:
            widget.insert("1.0", text)
        widget.configure(state="disabled")
