"""Acceptance-criteria edit dialog (DCC Task 11): turns one selected inbox report into a
fixed-format spec file (tools/ai_orchestrator/taskspec.py) for the Orchestrator start form
(orchestrator_view.py, Task 10).

The report's title/body are untrusted external text (see reports_inbox.py's own module docstring):
this dialog only quotes them read-only, for a human to read while writing the criteria. The spec
file's criteria are built exclusively from what the human types into the editable box and confirms
here; report content is never copied into it (see reports_inbox.create_spec_file).

DCC Task 14 adds a read-only AI investigation that starts the moment the dialog opens, on a
background thread so the criteria box and "仕様ファイルを作る" stay usable while it runs (see
reports_triage.py for the AI call, prompt and strict output validation). The AI's draft is shown
read-only; only "受入条件の下書きを反映" copies its criteria_draft into the editable box, and only
after confirming when the human has already edited that box away from the template.
"""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from . import reports_inbox as inbox
from . import reports_triage as triage

TICK_MS = 150


class ReportSpecDialog:
    def __init__(self, master: tk.Misc, report: inbox.Report, *, target_repo: str,
                 on_created: Callable[[Path], None] | None = None,
                 investigate_fn: Callable[..., "triage.TriageOutcome"] | None = None) -> None:
        from .app import DARK_BG, DARK_MUTED, configure_dark_text

        self._report = report
        self._target_repo = target_repo
        self._on_created = on_created
        self._investigate_fn = investigate_fn or triage.investigate
        self._stop_event = threading.Event()
        self._triage_queue: queue.Queue = queue.Queue()
        self._triage_outcome: triage.TriageOutcome | None = None
        self._closed = False
        self._tick_id = None

        self.window = tk.Toplevel(master)
        self.window.title("受入条件の確認・編集")
        self.window.geometry("640x760")
        self.window.minsize(560, 620)
        self.window.configure(background=DARK_BG)

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="報告の要約（読み取り専用）").pack(anchor="w")
        self.summary_text = tk.Text(outer, height=8, wrap="word", state="disabled")
        configure_dark_text(self.summary_text)
        self.summary_text.pack(fill="both", pady=(4, 10))
        self._set_readonly(self.summary_text, inbox.spec_summary_quote(report))

        ttk.Label(outer, text="受入条件（1行1件。1〜20件。人が確認・編集してください）").pack(anchor="w")
        self.criteria_text = tk.Text(outer, height=10, wrap="word")
        configure_dark_text(self.criteria_text)
        self.criteria_text.pack(fill="both", pady=(4, 8))
        self.criteria_text.insert("1.0", "\n".join(inbox.SPEC_CRITERIA_TEMPLATE))
        self.criteria_text.bind("<KeyRelease>", lambda _e: self._update_validation())

        self.notice_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.notice_var, foreground="#e3b341", wraplength=600,
                  justify="left").pack(anchor="w", pady=(0, 4))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(4, 0))
        self.create_button = ttk.Button(buttons, text="仕様ファイルを作る", command=self._on_create)
        self.create_button.pack(side="left")
        ttk.Button(buttons, text="キャンセル", command=self._close).pack(side="left", padx=(8, 0))

        ttk.Label(outer, text="AIによる調査結果（読み取り専用）").pack(anchor="w", pady=(10, 0))
        self.triage_status_var = tk.StringVar(value="調査中…")
        ttk.Label(outer, textvariable=self.triage_status_var, foreground=DARK_MUTED, wraplength=600,
                  justify="left").pack(anchor="w")
        self.triage_result_text = tk.Text(outer, height=10, wrap="word", state="disabled")
        configure_dark_text(self.triage_result_text)
        self.triage_result_text.pack(fill="both", expand=True, pady=(4, 4))
        self.apply_criteria_button = ttk.Button(
            outer, text="受入条件の下書きを反映", command=self._apply_criteria_draft)
        self.apply_criteria_button.pack(anchor="w")
        self.apply_criteria_button.state(["disabled"])

        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.bind("<Destroy>", self._on_window_destroyed)

        self._update_validation()
        self._start_investigation()

    def exists(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def _set_readonly(self, widget, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _update_validation(self) -> None:
        """Live re-check as the human edits the criteria box: keeps the Japanese reason and the
        create button's enabled state in sync with the current text (DCC Task 11 review fix —
        previously only _on_create validated, so an invalid draft still showed an enabled
        button)."""
        lines = inbox.parse_criteria_lines(self.criteria_text.get("1.0", "end"))
        reason = inbox.validate_criteria_lines(lines)
        self.notice_var.set(reason or "")
        self.create_button.state(["disabled"] if reason else ["!disabled"])

    def _on_create(self) -> None:
        lines = inbox.parse_criteria_lines(self.criteria_text.get("1.0", "end"))
        reason = inbox.validate_criteria_lines(lines)
        if reason:
            self.notice_var.set(reason)
            self.create_button.state(["disabled"])
            return
        try:
            path = inbox.create_spec_file(lines, self._target_repo, self._report.identity)
        except inbox.SpecCreateError as exc:
            self.notice_var.set(str(exc))
            return
        if self._on_created is not None:
            self._on_created(path)
        self._close()

    # ---------------------------------------------------------------- AI investigation (DCC Task 14)
    def _start_investigation(self) -> None:
        report = self._report
        q = self._triage_queue
        stop_event = self._stop_event
        investigate_fn = self._investigate_fn

        def work() -> None:
            try:
                outcome = investigate_fn(report, stop_event=stop_event)
            except Exception:  # noqa: BLE001 - a bug here must degrade, never crash the background thread
                outcome = triage.TriageOutcome(None, "調査中に問題が発生しました。", False)
            if not stop_event.is_set():
                q.put(outcome)

        self._investigation_thread = threading.Thread(target=work, daemon=True, name="dcc-report-triage")
        self._investigation_thread.start()
        self._tick_id = self.window.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        try:
            outcome = self._triage_queue.get_nowait()
        except queue.Empty:
            self._tick_id = self.window.after(TICK_MS, self._tick)
            return
        self._apply_triage_outcome(outcome)

    def _apply_triage_outcome(self, outcome: "triage.TriageOutcome") -> None:
        self._triage_outcome = outcome
        if outcome.result is None:
            self.triage_status_var.set(outcome.reason or "調査できませんでした。")
            self._set_readonly(self.triage_result_text, "")
            self.apply_criteria_button.state(["disabled"])
            return
        result = outcome.result
        lines = [f"仕分け: {result.classification_label}（確信度: {result.confidence_label}）"]
        if result.low_confidence_bug:
            lines.append("※ バグと判定されましたが、確信度は低めです。内容を確認してください。")
        if not outcome.code_available:
            lines.append("※ 対象アプリのコードを読めなかったため、報告の文面だけから判断しています。")
        lines += ["", "根拠:", result.evidence or "(なし)", "", "修正箇所の候補:"]
        lines += [f"- {loc}" for loc in result.suspected_locations] if result.suspected_locations else ["(なし)"]
        lines += ["", "返信の下書き:", result.reply_draft or "(なし)"]
        self._set_readonly(self.triage_result_text, "\n".join(lines))
        self.triage_status_var.set("調査が完了しました。")
        self.apply_criteria_button.state(["!disabled"] if result.criteria_draft else ["disabled"])

    def _apply_criteria_draft(self) -> None:
        outcome = self._triage_outcome
        if outcome is None or outcome.result is None or not outcome.result.criteria_draft:
            return
        current = inbox.parse_criteria_lines(self.criteria_text.get("1.0", "end"))
        if current != list(inbox.SPEC_CRITERIA_TEMPLATE):
            if not messagebox.askyesno(
                "確認", "受入条件の編集内容を、AIの下書きで置き換えます。よろしいですか？", parent=self.window,
            ):
                return
        self.criteria_text.delete("1.0", "end")
        self.criteria_text.insert("1.0", "\n".join(outcome.result.criteria_draft))
        self._update_validation()

    def _on_window_destroyed(self, _event=None) -> None:
        """Fires on this Toplevel's own <Destroy> -- including when a *parent* window (e.g. the
        inbox view's ReportsInboxView.close()) destroys it as part of tearing down its own
        widget tree, not only when _close() destroys it directly. Without this, closing the
        inbox while this dialog's investigation is still running would leave the background
        thread unstopped (DCC Task 14仕様1 review fix)."""
        self._stop_background()

    def _stop_background(self) -> None:
        """Idempotent: shared by _close() and _on_window_destroyed() so stopping the
        investigation and cancelling the tick never runs twice and never depends on which path
        tore the window down."""
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass

    def _close(self) -> None:
        """Used by キャンセル, successful 仕様ファイルを作る, and the window's own close
        button. Stops the background investigation (DCC Task 14仕様1: closing the dialog
        mid-investigation must abort it and never touch a widget afterwards) before destroying
        the window."""
        self._stop_background()
        self.window.destroy()
