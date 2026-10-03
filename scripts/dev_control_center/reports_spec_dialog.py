"""Acceptance-criteria edit dialog (DCC Task 11): turns one selected inbox report into a
fixed-format spec file (tools/ai_orchestrator/taskspec.py) for the Orchestrator start form
(orchestrator_view.py, Task 10).

The report's title/body are untrusted external text (see reports_inbox.py's own module docstring):
this dialog only quotes them read-only, for a human to read while writing the criteria. The spec
file's criteria are built exclusively from what the human types into the editable box and confirms
here; report content is never copied into it (see reports_inbox.create_spec_file).
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Callable

from . import reports_inbox as inbox


class ReportSpecDialog:
    def __init__(self, master: tk.Misc, report: inbox.Report, *, target_repo: str,
                 on_created: Callable[[Path], None] | None = None) -> None:
        from .app import DARK_BG, configure_dark_text

        self._report = report
        self._target_repo = target_repo
        self._on_created = on_created

        self.window = tk.Toplevel(master)
        self.window.title("受入条件の確認・編集")
        self.window.geometry("640x560")
        self.window.minsize(560, 480)
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
        self.criteria_text.pack(fill="both", expand=True, pady=(4, 8))
        self.criteria_text.insert("1.0", "\n".join(inbox.SPEC_CRITERIA_TEMPLATE))
        self.criteria_text.bind("<KeyRelease>", lambda _e: self._update_validation())

        self.notice_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.notice_var, foreground="#e3b341", wraplength=600,
                  justify="left").pack(anchor="w", pady=(0, 4))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(4, 0))
        self.create_button = ttk.Button(buttons, text="仕様ファイルを作る", command=self._on_create)
        self.create_button.pack(side="left")
        ttk.Button(buttons, text="キャンセル", command=self.window.destroy).pack(side="left", padx=(8, 0))

        self._update_validation()

    def exists(self) -> bool:
        return bool(self.window.winfo_exists())

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
        self.window.destroy()
