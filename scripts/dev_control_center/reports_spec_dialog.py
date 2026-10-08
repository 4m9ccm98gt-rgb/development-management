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

DCC Task 14.5 adds "作成して開始": enabled only once the investigation concluded バグ or 変更要望
(reports_create_and_start.button_enabled), it opens CreateAndStartDialog -- a second, human-only
confirmation step (target app/repo, current Main/Reviewer, title, two editable criteria boxes,
one of them headed "AIの推測（未確認）") -- before reports_create_and_start.create_and_start
writes the spec file and starts the Orchestrator through its existing entry point. Nothing starts
without that second dialog's own "作成して開始" button being pressed by a human.

create_and_start_fn's own call (ending in orch.start_run, which blocks for Git/provider work and
worker registration) runs on a background thread exactly like orchestrator_view's own
_confirm_start, not on the Tk thread (review fix, iteration 2) -- the 作成して開始 button disables
itself immediately to guard against a second press starting a second run, and a result that
arrives after this second dialog was already closed is dropped instead of touching a widget.
"""
from __future__ import annotations

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from . import reports_create_and_start as cas
from . import reports_inbox as inbox
from . import reports_triage as triage

TICK_MS = 150


def _default_current_roles() -> tuple[str, str]:
    from tools.ai_orchestrator.providers import DEFAULT_MAIN_AGENT, DEFAULT_REVIEW_AGENT

    return DEFAULT_MAIN_AGENT, DEFAULT_REVIEW_AGENT


class ReportSpecDialog:
    def __init__(self, master: tk.Misc, report: inbox.Report, *, target_repo: str,
                 on_created: Callable[[Path], None] | None = None,
                 investigate_fn: Callable[..., "triage.TriageOutcome"] | None = None,
                 current_roles: Callable[[], tuple[str, str]] | None = None,
                 create_and_start_fn: Callable[..., "cas.StartResult"] | None = None,
                 resolve_repo_dir_for_confirm: Callable[[str], Path | None] | None = None) -> None:
        from .app import DARK_BG, DARK_MUTED, configure_dark_text

        self._report = report
        self._target_repo = target_repo
        self._on_created = on_created
        self._investigate_fn = investigate_fn or triage.investigate
        self._current_roles = current_roles or _default_current_roles
        self._create_and_start_fn = create_and_start_fn or cas.create_and_start
        self._resolve_repo_dir_for_confirm = resolve_repo_dir_for_confirm
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
        self.create_and_start_button = ttk.Button(
            outer, text="作成して開始", command=self._on_create_and_start)
        self.create_and_start_button.pack(anchor="w", pady=(4, 0))
        self.create_and_start_button.state(["disabled"])

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
        self.create_and_start_button.state(["!disabled" if cas.button_enabled(outcome) else "disabled"])
        if outcome.result is None:
            self.triage_status_var.set(outcome.reason or "調査できませんでした。")
            note = "" if outcome.code_available else triage.code_unavailable_note(outcome.code_unavailable_reason)
            self._set_readonly(self.triage_result_text, note)
            self.apply_criteria_button.state(["disabled"])
            return
        result = outcome.result
        lines = [f"仕分け: {result.classification_label}（確信度: {result.confidence_label}）"]
        if result.low_confidence_bug:
            lines.append("※ バグと判定されましたが、確信度は低めです。内容を確認してください。")
        if not outcome.code_available:
            lines.append(triage.code_unavailable_note(outcome.code_unavailable_reason))
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

    # ---------------------------------------------------------------- 作成して開始 (DCC Task 14.5)
    def _on_create_and_start(self) -> None:
        outcome = self._triage_outcome
        if outcome is None or not cas.button_enabled(outcome):
            return
        main_agent, review_agent = self._current_roles()
        confirm_info = cas.build_confirm_info(
            self._report, main_agent=main_agent, review_agent=review_agent,
            resolve_repo_dir=self._resolve_repo_dir_for_confirm)
        base_criteria = inbox.parse_criteria_lines(self.criteria_text.get("1.0", "end"))
        ai_criteria = cas.ai_suggested_criteria(outcome.result)
        self._confirm_dialog = CreateAndStartDialog(
            self.window, report=self._report, confirm_info=confirm_info,
            base_criteria_lines=base_criteria, ai_criteria_lines=ai_criteria,
            main_agent=main_agent, review_agent=review_agent,
            create_and_start_fn=self._create_and_start_fn,
            on_result=self._on_create_and_start_result,
        )

    def _on_create_and_start_result(self, result: "cas.StartResult") -> None:
        """Whether the Orchestrator actually started or not, a spec file that *was* written
        reaches the same on_created hand-off "仕様ファイルを作る" already uses (DCC Task 11) --
        so a human who sees 既に実行中 or リポジトリ不明 in the confirmation dialog still lands on
        the Orchestrator start form with the just-written spec loaded, ready for a manual 開始
        (C12's "仕様ファイルだけ作った場合は、そのことも伝える"). This dialog only closes itself
        when the run actually started."""
        if result.spec_path is not None and self._on_created is not None:
            self._on_created(result.spec_path)
        if result.ok:
            self._close()

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


class CreateAndStartDialog:
    """DCC Task 14.5仕様2: the human-only confirmation step between 作成して開始 and actually
    creating a spec file / starting the Orchestrator. Shows only what C6 asks for -- app, repo
    *name* (never a path), current Main/Reviewer, task title, and two editable criteria boxes
    (the ordinary one, prefilled from the parent dialog's own box, and a second one headed
    "AIの推測（未確認）", prefilled from reports_create_and_start.ai_suggested_criteria). Nothing
    is written or started until this dialog's own 作成して開始 button is pressed; キャンセル (or
    the window's own close button) closes it without calling create_and_start at all."""

    def __init__(self, master: tk.Misc, *, report: inbox.Report, confirm_info: "cas.ConfirmInfo",
                 base_criteria_lines: list[str], ai_criteria_lines: list[str], main_agent: str,
                 review_agent: str, create_and_start_fn: Callable[..., "cas.StartResult"],
                 on_result: Callable[["cas.StartResult"], None] | None = None) -> None:
        from .app import DARK_BG, configure_dark_text

        self._report = report
        self._confirm_info = confirm_info
        self._main_agent = main_agent
        self._review_agent = review_agent
        self._create_and_start_fn = create_and_start_fn
        self._on_result = on_result
        self._closed = False
        self._starting = False
        self._result_queue: queue.Queue = queue.Queue()
        self._start_thread: threading.Thread | None = None
        self._tick_id = None

        self.window = tk.Toplevel(master)
        self.window.title("作成して開始の確認")
        self.window.geometry("640x680")
        self.window.minsize(560, 560)
        self.window.configure(background=DARK_BG)
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.bind("<Destroy>", self._on_window_destroyed)

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)

        self._labels: list = []  # test-introspection only: every ttk.Label this dialog created
        for label, value in (
            ("対象アプリ", confirm_info.app_display_name),
            ("対象リポジトリ", confirm_info.repo_display_name),
            ("Main / Reviewer", confirm_info.roles_text),
            ("タスクの題名", confirm_info.task_title),
        ):
            row = ttk.Frame(outer)
            row.pack(fill="x", anchor="w")
            ttk.Label(row, text=f"{label}: ").pack(side="left")
            self._labels.append(ttk.Label(row, text=value))
            self._labels[-1].pack(side="left")

        self._labels.append(ttk.Label(outer, text="受入条件（編集可能）"))
        self._labels[-1].pack(anchor="w", pady=(8, 0))
        self.base_text = tk.Text(outer, height=6, wrap="word")
        configure_dark_text(self.base_text)
        self.base_text.pack(fill="both", pady=(4, 8))
        self.base_text.insert("1.0", "\n".join(base_criteria_lines))

        self._labels.append(ttk.Label(outer, text=f"{cas.AI_GUESS_HEADING}（編集可能）"))
        self._labels[-1].pack(anchor="w")
        self.ai_text = tk.Text(outer, height=6, wrap="word")
        configure_dark_text(self.ai_text)
        self.ai_text.pack(fill="both", pady=(4, 8))
        self.ai_text.insert("1.0", "\n".join(ai_criteria_lines))

        self.base_text.bind("<KeyRelease>", lambda _e: self._update_criteria_count())
        self.ai_text.bind("<KeyRelease>", lambda _e: self._update_criteria_count())

        self.criteria_count_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.criteria_count_var).pack(anchor="w", pady=(2, 0))
        self._update_criteria_count()

        self.notice_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.notice_var, foreground="#e3b341", wraplength=600,
                  justify="left").pack(anchor="w")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="キャンセル", command=self._cancel).pack(side="left")
        self.start_button = ttk.Button(buttons, text="作成して開始", command=self._on_start)
        self.start_button.pack(side="left", padx=(8, 0))

    def exists(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def _update_criteria_count(self) -> None:
        """C3: the confirmation dialog shows the acceptance-criteria *count* (not just the
        editable text) -- kept live as the human edits either box, since that count is exactly
        what create_and_start will validate/write."""
        self.criteria_count_var.set(f"受入条件: {len(self._combined_criteria())}件")

    def _combined_criteria(self) -> list[str]:
        base = inbox.parse_criteria_lines(self.base_text.get("1.0", "end"))
        ai = inbox.parse_criteria_lines(self.ai_text.get("1.0", "end"))
        return base + ai

    def _on_start(self) -> None:
        """Review fix (iteration 2): create_and_start_fn ends in orch.start_run, which blocks for
        up to ~30s (worker registration) after doing Git/provider work -- calling it directly on
        the Tk thread froze the whole DCC window. This now mirrors
        orchestrator_view.OrchestratorWindow._confirm_start: the call runs on a background
        thread, the button is disabled immediately (both to signal "running" and to guard against
        a second press starting a second run -- C11 "一度の操作"/"1回だけ"), and the result is
        only applied through _tick's closed-guard, so a result that arrives after this dialog was
        already destroyed never touches a widget."""
        if self._starting or self._closed:
            return
        criteria = self._combined_criteria()
        self._starting = True
        self.start_button.state(["disabled"])
        self.notice_var.set("作成して開始しています…")
        report, main_agent, review_agent = self._report, self._main_agent, self._review_agent
        create_and_start_fn, q = self._create_and_start_fn, self._result_queue

        def work() -> None:
            try:
                result = create_and_start_fn(
                    report, criteria, main_agent=main_agent, review_agent=review_agent)
            except Exception:  # noqa: BLE001 - a bug here must degrade, never crash the background thread
                result = cas.StartResult(False, cas.REASON_START_FAILED)
            q.put(result)

        self._start_thread = threading.Thread(target=work, daemon=True, name="dcc-create-and-start")
        self._start_thread.start()
        self._tick_id = self.window.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        try:
            result = self._result_queue.get_nowait()
        except queue.Empty:
            self._tick_id = self.window.after(TICK_MS, self._tick)
            return
        self._apply_result(result)

    def _apply_result(self, result: "cas.StartResult") -> None:
        self._starting = False
        if result.ok:
            self._close()
        else:
            note = result.reason
            if result.spec_created_note:
                note = f"{note} {result.spec_created_note}"
            self.notice_var.set(note)
            self.start_button.state(["!disabled"])
        if self._on_result is not None:
            self._on_result(result)

    def _cancel(self) -> None:
        self._close()

    def _on_window_destroyed(self, _event=None) -> None:
        """Fires on this Toplevel's own <Destroy> -- including a parent window's destroy()
        cascading down to this one (same reasoning as ReportSpecDialog._on_window_destroyed).
        Marks this dialog closed so a start result that arrives afterwards is dropped by
        _tick's/_apply_result's guard instead of touching a destroyed widget."""
        self._mark_closed()

    def _mark_closed(self) -> None:
        """Idempotent: shared by _close() and _on_window_destroyed() so the closed flag and the
        tick cancellation never depend on which path tore the window down."""
        if self._closed:
            return
        self._closed = True
        if self._tick_id is not None:
            try:
                self.window.after_cancel(self._tick_id)
            except (tk.TclError, AttributeError):
                pass

    def _close(self) -> None:
        self._mark_closed()
        self.window.destroy()
