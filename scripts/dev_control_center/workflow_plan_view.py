"""DCC Task WF-3a: a human-facing window over Task WF-1's plan data (workflow_plan.py) and
Task WF-2's executor (workflow_runner.py) -- plan selection/creation, the task list and its
read-only body, human-only task operations, the per-plan automatic-run permission, and a
manager-facing "state copy" to the clipboard. Importing a plan's proposed changes (WF-3b) is a
separate, later window; this one never applies anything but a human-actor WF-1 proposal.

Security posture (same family as reports_inbox_view.py):
 - A plan's title/name is untrusted display text (the TaskSpec's own words: "計画のタイトルなどの
   文字列は、信頼できないデータ"), sanitized and length-capped for display the same way
   reports_inbox_view.py treats report titles -- independent of whatever workflow_plan.py's own
   _label() already enforces on a file that loaded successfully, so a corrupt/forged plan file
   can never put a control character or an unbounded string on screen.
 - Every human-operation button (承認/保留/取消/再試行) calls workflow_plan.apply_and_save_proposal
   with actor="human" -- never "manager" -- and only ever with one of the WF-1 ops
   hold/release/cancel/approve on a single existing task_id. None of them, and nothing else in
   this module, ever calls a candidate-approval, push, BUILD, UPDATE or RELEASE entry point: this
   window stops exactly where WF-1/WF-2 already stop (an approved task queued for the
   Orchestrator). The automatic-run checkbox only ever calls
   workflow_runner.set_plan_auto_run_allowed -- never anything that starts a run itself (that is
   workflow_runner's own background loop, wired up in app.py, not this window).
 - Every destructive-looking human action (承認/保留/取消/再試行, turning automatic-run ON) asks
   for confirmation first (messagebox.askyesno) and performs the call only when the human
   confirms; a cancelled confirmation never calls into workflow_plan.py/workflow_runner.py at all.
 - The clipboard "state copy" never includes a task's body (only task_id/title/repo_key/status/
   depends_on/last-result, all either fixed vocabulary or already-sanitized display text), plus a
   fixed-text explanation of WF-1's own proposal JSON shape -- so a manager AI reading the copy
   can draft a next proposal without ever seeing (or needing) a task's full acceptance-criteria
   text.
"""
from __future__ import annotations

import json
import secrets
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from .orchestrator_view import resolve_click_index
from . import workflow_plan as wf
from . import workflow_runner as wr

TICK_MS = 150
TITLE_DISPLAY_MAX = 80
BODY_MAX_LINE_CHARS = 2_000
BODY_MAX_CHARS = 20_000
TRUNCATION_MARK = "…(切り詰め)"

PAUSED_TEXT = "この計画は一時停止中です"
LOAD_FAILED_TEXT = "計画を読み込めません"
CREATE_FAILED_TEXT = "計画を作成できませんでした。名前を確認してください。"
OP_FAILED_TEXT = "操作に失敗しました。計画を再読み込みしてください。"
AUTO_RUN_CONFIRM_TEXT = "承認、PUSH、BUILD は人が行います。この計画を自動で実行しますか？"
NO_RESULT_WORD = "(なし)"
NO_VALUE_WORD = "(既定)"
NO_DEPENDS_WORD = "(なし)"

STATUS_LABELS = {
    "proposed": "提案", "approved": "承認済み", "held": "保留", "running": "実行中",
    "candidate_ready": "候補あり", "landed": "取り込み済み", "failed": "失敗",
    "needs_human": "人の確認が必要", "cancelled": "取消",
}

PROPOSAL_FORMAT_TEXT = """変更案の書式:
変更案は JSON で、{"plan_id": ..., "base_revision": ..., "ops": [...]} の形です。
ops の各要素は次のいずれかです（approve はここでは使えません）:
  {"op": "add_task", "task": {"task_id": "t2", "title": "...", "repo_key": "...", "body": "...", "depends_on": [], "status": "proposed"}}
  {"op": "insert_after", "after": "t1", "task": {"task_id": "t2", "title": "...", "repo_key": "...", "body": "...", "depends_on": [], "status": "proposed"}}
  {"op": "move", "task_id": "t2", "after": "t1"}
  {"op": "hold", "task_id": "t2"}
  {"op": "release", "task_id": "t2"}
  {"op": "cancel", "task_id": "t2"}
  {"op": "update_body", "task_id": "t2", "body": "..."}
  {"op": "set_depends_on", "task_id": "t2", "depends_on": ["t1"]}"""


# --------------------------------------------------------------------------- pure display helpers

def _is_control(ch: str) -> bool:
    if ch in ("\n", "\t"):
        return False
    code = ord(ch)
    return code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F


def sanitize_text(value) -> str:
    """Neutralize control characters for display; newline/tab pass through unchanged."""
    return "".join("�" if _is_control(ch) else ch for ch in str(value))


def display_title(value, *, limit: int = TITLE_DISPLAY_MAX) -> str:
    """A list row / combobox entry is one line: newlines/tabs collapse to spaces first."""
    text = sanitize_text(value).replace("\n", " ").replace("\t", " ")
    if len(text) > limit:
        return text[:limit] + TRUNCATION_MARK
    return text


def truncate_for_display(value, *, max_line_chars: int = BODY_MAX_LINE_CHARS,
                          max_chars: int = BODY_MAX_CHARS) -> str:
    """Display-only truncation for a task body: sanitize, cap each line, then cap the total."""
    sanitized = sanitize_text(value)
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


def status_label(status) -> str:
    return STATUS_LABELS.get(status, "")


def task_row_line(order: int, task: dict) -> str:
    """One list row per task: task_id/repo_key/depends_on are already-validated identifiers
    (workflow_plan._identifier's own alphabet), safe to show as-is; only the title is free text
    and goes through display_title."""
    deps = ",".join(task.get("depends_on") or []) or NO_DEPENDS_WORD
    main_ai = task.get("main_ai") or NO_VALUE_WORD
    reviewer_ai = task.get("reviewer_ai") or NO_VALUE_WORD
    return (f"{order}. [{status_label(task.get('status'))}] {task.get('repo_key', '')} / "
            f"{display_title(task.get('title', ''))}  依存:{deps}  "
            f"Main:{main_ai} Reviewer:{reviewer_ai}  task_id:{task.get('task_id', '')}")


def plan_is_paused(plan: dict) -> bool:
    return any(t["status"] in ("failed", "needs_human") for t in plan["tasks"])


def build_status_copy_text(plan: dict, *, last_result_fn: Callable[[str, str], str]) -> str:
    """Manager-facing state copy: plan identity + task list (never a task body) + a fixed
    explanation of WF-1's own proposal JSON shape."""
    lines = [
        f"plan_id: {plan['plan_id']}",
        f"name: {display_title(plan['name'])}",
        f"revision: {plan['revision']}",
        "",
        "タスク一覧 (順番. task_id / タイトル / アプリ名 / 状態 / 依存 / 最後の結果):",
    ]
    for index, task in enumerate(plan["tasks"], start=1):
        deps = ",".join(task["depends_on"]) or NO_DEPENDS_WORD
        result = last_result_fn(plan["plan_id"], task["task_id"])
        lines.append(f"{index}. {task['task_id']} / {display_title(task['title'])} / "
                     f"{task['repo_key']} / {status_label(task['status'])} / {deps} / {result}")
    lines.append("")
    lines.append(PROPOSAL_FORMAT_TEXT)
    return "\n".join(lines)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _generate_plan_id() -> str:
    return "plan-" + secrets.token_hex(8)


def _is_valid_plan_id(value) -> bool:
    """WF-1's own identifier contract (workflow_plan._identifier: `[A-Za-z0-9-]{1,32}`), reused
    directly rather than re-expressed here, so an enumerated plan_id can never disagree with what
    load_plan/save_plan themselves accept -- a corrupt/forged plan file's identifier field is
    exactly the one piece of this listing that is not already shaped by workflow_plan.py (unlike
    `name`, which still goes through display_title below)."""
    try:
        wf._identifier(value, 32)
    except wf.WorkflowError:
        return False
    return True


def _list_plans(root) -> list[tuple[str, str]]:
    """[(plan_id, name), ...] read directly off disk: a plan file's name is a content-free hash
    of plan_id (workflow_plan._plan_path), so there is no other way to enumerate existing plans.
    A corrupt/unreadable file, or one whose plan_id does not match WF-1's own identifier contract,
    is skipped, never raised -- listing must stay available even when one plan file is damaged,
    and an invalid identifier must never reach the combobox at all."""
    result = []
    try:
        entries = list(Path(root).iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_file() or entry.suffix != ".json":
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        plan_id, name = data.get("plan_id"), data.get("name")
        if _is_valid_plan_id(plan_id) and isinstance(name, str):
            result.append((plan_id, name))
    result.sort(key=lambda pair: pair[1])
    return result


def _set_enabled(widget, enabled: bool) -> None:
    if bool(widget.instate(["disabled"])) == (not enabled):
        return
    widget.state(["!disabled" if enabled else "disabled"])


class WorkflowPlanWindow:
    def __init__(self, master: tk.Misc, *, plans_root=None, registered_keys=None,
                 runner_config_path=None, daily_count_path=None, records_dir=None,
                 list_plans_fn: Callable[[object], list] | None = None,
                 load_plan_fn=None, save_plan_fn=None, apply_proposal_fn=None,
                 set_plan_auto_run_fn=None, load_runner_config_fn=None,
                 daily_limit_reached_fn=None, copy_to_clipboard: Callable[[str], None] | None = None,
                 ) -> None:
        from .app import DARK_BG, DARK_MUTED, configure_dark_listbox, configure_dark_text

        # _list_plans (unlike every workflow_plan.py/workflow_runner.py function below) is this
        # module's own helper and never defaults a None root itself, so plans_root/daily_count_path
        # -- the two paths only this module ever passes to a function that does not already
        # default them -- are resolved to the real on-disk locations here when the caller (the
        # real app.py, never a test) omits them.
        self._plans_root = plans_root if plans_root is not None else wf.plans_root()
        self._registered_keys = registered_keys
        self._runner_config_path = runner_config_path
        self._daily_count_path = daily_count_path if daily_count_path is not None else wr._daily_count_path()
        self._records_dir = records_dir
        self._list_plans_fn = list_plans_fn or _list_plans
        self._load_plan_fn = load_plan_fn or wf.load_plan
        self._save_plan_fn = save_plan_fn or wf.save_plan
        self._apply_proposal_fn = apply_proposal_fn or wf.apply_and_save_proposal
        self._set_plan_auto_run_fn = set_plan_auto_run_fn or wr.set_plan_auto_run_allowed
        self._load_runner_config_fn = load_runner_config_fn or wr.load_workflow_runner_config
        self._daily_limit_reached_fn = daily_limit_reached_fn or wr.daily_limit_reached
        self._copy_to_clipboard = copy_to_clipboard

        self._closed = False
        self._plan_choices: list[tuple[str, str]] = []
        self.plan_id: str | None = None
        self.plan: dict | None = None
        self.visible_tasks: list[dict] = []
        self.selected_task_id: str | None = None

        self.window = tk.Toplevel(master)
        self.window.title("開発計画")
        self.window.geometry("1180x760")
        self.window.minsize(980, 640)
        self.window.configure(background=DARK_BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.plan_select_var = tk.StringVar(value="")
        self.new_plan_name_var = tk.StringVar(value="")
        self.load_notice_var = tk.StringVar(value="")
        self.pause_notice_var = tk.StringVar(value="")
        self.limit_notice_var = tk.StringVar(value="")
        self.auto_run_var = tk.BooleanVar(value=False)

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(2, weight=1)

        select_row = ttk.Frame(outer)
        select_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(select_row, text="計画:").pack(side="left")
        self.plan_combo = ttk.Combobox(select_row, textvariable=self.plan_select_var,
                                        state="readonly", width=40)
        self.plan_combo.pack(side="left", padx=(4, 12))
        self.plan_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_plan_combo_selected())
        ttk.Entry(select_row, textvariable=self.new_plan_name_var, width=24).pack(side="left")
        ttk.Button(select_row, text="新規計画の作成", command=self._on_create_plan).pack(
            side="left", padx=(4, 0))

        notice_row = ttk.Frame(outer)
        notice_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(notice_row, textvariable=self.load_notice_var, foreground=DARK_MUTED).pack(
            side="left")
        ttk.Label(notice_row, textvariable=self.pause_notice_var, foreground="#e3b341").pack(
            side="left", padx=(12, 0))
        ttk.Label(notice_row, textvariable=self.limit_notice_var, foreground="#e3b341").pack(
            side="left", padx=(12, 0))

        left = ttk.Frame(outer)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="タスク一覧（順番）").grid(row=0, column=0, sticky="w")
        self.task_list = tk.Listbox(left, width=70, exportselection=False)
        configure_dark_listbox(self.task_list)
        self.task_list.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.task_list.bind("<Button-1>", self._on_task_click)

        right = ttk.Frame(outer)
        right.grid(row=2, column=1, sticky="nsew", pady=(8, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="本文（読み取り専用）").grid(row=0, column=0, sticky="w")
        self.detail_text = tk.Text(right, height=14, state="disabled", wrap="word")
        configure_dark_text(self.detail_text)
        self.detail_text.grid(row=1, column=0, sticky="nsew")

        actions = ttk.Frame(right)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.approve_button = ttk.Button(actions, text="承認", command=self._on_approve)
        self.approve_button.pack(side="left", padx=(0, 6))
        self.hold_button = ttk.Button(actions, text="保留", command=self._on_hold)
        self.hold_button.pack(side="left", padx=(0, 6))
        self.cancel_button = ttk.Button(actions, text="取消", command=self._on_cancel)
        self.cancel_button.pack(side="left", padx=(0, 6))
        self.retry_button = ttk.Button(actions, text="再試行", command=self._on_retry)
        self.retry_button.pack(side="left", padx=(0, 6))
        for button in (self.approve_button, self.hold_button, self.cancel_button, self.retry_button):
            _set_enabled(button, False)

        auto_row = ttk.Frame(right)
        auto_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(auto_row, text="この計画を自動で実行する（候補の作成まで）",
                        variable=self.auto_run_var, command=self._on_auto_run_toggle).pack(
            side="left")

        copy_row = ttk.Frame(right)
        copy_row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(copy_row, text="状態をコピー", command=self._on_copy_status).pack(side="left")

        self._reload_plan_list()
        self._tick_id = self.window.after(TICK_MS, self._tick)

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
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        self.window.destroy()

    # ---------------------------------------------------------------- plan list / selection
    def _plan_display(self, plan_id: str, name: str) -> str:
        return f"{display_title(name)} ({plan_id})"

    def _reload_plan_list(self) -> None:
        self._plan_choices = self._list_plans_fn(self._plans_root)
        self.plan_combo["values"] = [self._plan_display(pid, name) for pid, name in self._plan_choices]

    def _on_plan_combo_selected(self) -> None:
        current = self.plan_select_var.get()
        for plan_id, name in self._plan_choices:
            if self._plan_display(plan_id, name) == current:
                self.select_plan(plan_id)
                return

    def select_plan(self, plan_id: str) -> None:
        """Switch the window to a different plan (also used directly by tests)."""
        self.plan_id = plan_id
        self._clear_plan_state()
        self._reload_current_plan()

    def _clear_plan_state(self) -> None:
        """Drop whatever plan/task data is currently rendered and disable every operation that
        reads it. Called both before switching to a (possibly different) plan_id and whenever a
        (re)load fails, so a failed load can never leave a previous plan's tasks, read/write
        operation buttons or auto-run checkbox state live underneath the plan_id the window now
        points at -- the plan actually on screen and the plan an operation would act on must never
        disagree."""
        self.plan = None
        self.selected_task_id = None
        self._render_plan()

    def _reload_current_plan(self) -> None:
        if self.plan_id is None:
            return
        try:
            plan = self._load_plan_fn(self.plan_id, root=self._plans_root,
                                      registered_keys=self._registered_keys)
        except wf.WorkflowError:
            # Catches both WorkflowStorageError (unreadable/corrupt file) and a plain
            # WorkflowError (e.g. load_plan's own _plan_path rejecting a malformed plan_id before
            # its try/except even starts) -- both are the same fixed-text "読み込めません" case to
            # this window, and both must blank the stale previous plan the same way.
            self.load_notice_var.set(LOAD_FAILED_TEXT)
            self._clear_plan_state()
            return
        self.load_notice_var.set("")
        self.plan = plan
        self._render_plan()

    def _on_create_plan(self) -> None:
        name = self.new_plan_name_var.get().strip()
        if not name:
            return
        plan_id = _generate_plan_id()
        new_plan = {"plan_id": plan_id, "name": name, "revision": 0, "tasks": []}
        try:
            self._save_plan_fn(new_plan, root=self._plans_root, registered_keys=self._registered_keys)
        except (wf.WorkflowError, wf.WorkflowStorageError):
            messagebox.showerror("開発計画", CREATE_FAILED_TEXT, parent=self.window)
            return
        self.new_plan_name_var.set("")
        self._reload_plan_list()
        self.plan_select_var.set(self._plan_display(plan_id, name))
        self.select_plan(plan_id)

    # ---------------------------------------------------------------- rendering
    def _render_plan(self) -> None:
        self._render_tasks()
        self._refresh_pause_and_limit_notice()
        self._refresh_auto_run_checkbox()

    def _render_tasks(self) -> None:
        tasks = self.plan["tasks"] if self.plan else []
        self.visible_tasks = tasks
        self.task_list.delete(0, "end")
        for index, task in enumerate(tasks, start=1):
            self.task_list.insert("end", task_row_line(index, task))
        self._sync_task_selection()

    def _sync_task_selection(self) -> None:
        self.task_list.selection_clear(0, "end")
        task = None
        if self.selected_task_id is not None:
            for index, candidate in enumerate(self.visible_tasks):
                if candidate["task_id"] == self.selected_task_id:
                    self.task_list.selection_set(index)
                    task = candidate
                    break
            else:
                self.selected_task_id = None
        self._show_task_body(task)
        self._update_task_buttons(task)

    def select_task(self, task_id: str) -> None:
        """Select a task by id (also used directly by tests)."""
        self.selected_task_id = task_id
        self._sync_task_selection()

    def _show_task_body(self, task: dict | None) -> None:
        text = truncate_for_display(task["body"]) if task else ""
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if text:
            self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def _update_task_buttons(self, task: dict | None) -> None:
        status = task["status"] if task else None
        _set_enabled(self.approve_button, status in ("proposed", "held"))
        _set_enabled(self.hold_button, status in ("proposed", "approved"))
        _set_enabled(self.cancel_button,
                     status in ("proposed", "approved", "held", "failed", "needs_human"))
        _set_enabled(self.retry_button, status in ("failed", "needs_human"))

    def _on_task_click(self, event: tk.Event) -> str:
        index = resolve_click_index(event.y, self.task_list.size(), self.task_list.nearest,
                                     self.task_list.bbox)
        if index is not None and index < len(self.visible_tasks):
            self.task_list.selection_clear(0, "end")
            self.task_list.selection_set(index)
            self.task_list.focus_set()
            self.selected_task_id = self.visible_tasks[index]["task_id"]
            self._show_task_body(self.visible_tasks[index])
            self._update_task_buttons(self.visible_tasks[index])
        return "break"

    # ---------------------------------------------------------------- human operations
    def _selected_task(self) -> dict | None:
        if self.selected_task_id is None:
            return None
        return next((t for t in self.visible_tasks if t["task_id"] == self.selected_task_id), None)

    def _do_task_op(self, op: str, confirm_text: str) -> None:
        task = self._selected_task()
        if task is None or self.plan is None:
            return
        if not messagebox.askyesno("開発計画", confirm_text, parent=self.window):
            return
        proposal = {"plan_id": self.plan["plan_id"], "base_revision": self.plan["revision"],
                    "ops": [{"op": op, "task_id": task["task_id"]}]}
        try:
            new_plan, _summary = self._apply_proposal_fn(
                self.plan["plan_id"], proposal, actor="human",
                root=self._plans_root, registered_keys=self._registered_keys)
        except (wf.WorkflowError, wf.WorkflowStorageError):
            messagebox.showerror("開発計画", OP_FAILED_TEXT, parent=self.window)
            return
        self.plan = new_plan
        self._render_plan()

    def _on_approve(self) -> None:
        self._do_task_op("approve", "このタスクを承認しますか？")

    def _on_hold(self) -> None:
        self._do_task_op("hold", "このタスクを保留しますか？")

    def _on_cancel(self) -> None:
        self._do_task_op("cancel", "このタスクを取消しますか？")

    def _on_retry(self) -> None:
        self._do_task_op("approve", "このタスクを再試行しますか？（承認済みに戻します）")

    # ---------------------------------------------------------------- automatic-run permission
    def _refresh_auto_run_checkbox(self) -> None:
        if self.plan is None:
            self.auto_run_var.set(False)
            return
        try:
            config = self._load_runner_config_fn(self._runner_config_path)
        except Exception:  # noqa: BLE001 - never block rendering on a bad runner config read
            return
        self.auto_run_var.set(bool(config.plans.get(self.plan["plan_id"], False)))

    def _on_auto_run_toggle(self) -> None:
        if self.plan is None:
            return
        desired = self.auto_run_var.get()
        if desired and not messagebox.askyesno("開発計画", AUTO_RUN_CONFIRM_TEXT, parent=self.window):
            self.auto_run_var.set(False)
            return
        try:
            self._set_plan_auto_run_fn(self.plan["plan_id"], desired, path=self._runner_config_path)
        except OSError:
            self.auto_run_var.set(not desired)

    # ---------------------------------------------------------------- pause / daily-limit notices
    def _refresh_pause_and_limit_notice(self) -> None:
        if self.plan is None:
            self.pause_notice_var.set("")
            self.limit_notice_var.set("")
            return
        self.pause_notice_var.set(PAUSED_TEXT if plan_is_paused(self.plan) else "")
        try:
            config = self._load_runner_config_fn(self._runner_config_path)
            reached = self._daily_limit_reached_fn(_today_str(), config.daily_limit,
                                                    path=self._daily_count_path)
        except Exception:  # noqa: BLE001 - never block rendering on a bad config/count read
            reached = False
        self.limit_notice_var.set(wr.LIMIT_REACHED_TEXT if reached else "")

    # ---------------------------------------------------------------- state copy
    def _last_result_word(self, plan_id: str, task_id: str) -> str:
        """The copy's "最後の結果" column must itself be drawn from WF-2's own closed reason
        vocabulary (_ALLOWED_REASONS), never the raw record field: the record file is a trusted
        write path for workflow_runner.py's own fixed codes, but reading it back here must not
        assume that -- a forged/corrupted record (a path, control characters, an arbitrary long
        string, or a non-string value) must never reach the manager-facing text verbatim."""
        try:
            from . import reports_auto_start as start

            record = start._read_json(wr._record_path(plan_id, task_id, root=self._records_dir))
        except Exception:  # noqa: BLE001 - display-only: never fails the copy
            return NO_RESULT_WORD
        if not isinstance(record, dict):
            return NO_RESULT_WORD
        reason = record.get("reason")
        if not reason:
            return NO_RESULT_WORD
        return wr._safe_reason(reason)

    def _on_copy_status(self) -> None:
        if self.plan is None:
            return
        text = build_status_copy_text(self.plan, last_result_fn=self._last_result_word)
        if self._copy_to_clipboard is not None:
            self._copy_to_clipboard(text)
        else:
            self.window.clipboard_clear()
            self.window.clipboard_append(text)

    # ---------------------------------------------------------------- periodic update
    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        try:
            if self.plan_id is not None:
                self._reload_current_plan()
        finally:
            # The next tick must always be scheduled, even if _reload_current_plan somehow raised
            # something other than the WorkflowError it already converts to a fixed notice above --
            # a periodic update must never silently stop firing.
            self._tick_id = self.window.after(TICK_MS, self._tick)
