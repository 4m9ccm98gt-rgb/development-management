"""DCC Task WF-3a: a human-facing window over Task WF-1's plan data (workflow_plan.py) and
Task WF-2's executor (workflow_runner.py) -- plan selection/creation, the task list and its
read-only body, human-only task operations, the per-plan automatic-run permission, and a
manager-facing "state copy" to the clipboard. Importing a plan's proposed changes (WF-3b,
WorkflowImportDialog below) is a separate dialog opened from this window's own "変更案を取り込む"
button; this window itself never applies anything but a human-actor WF-1 proposal.

DCC Task WF-3b (WorkflowImportDialog): a human pastes an external manager AI's proposal JSON,
clicks 検証 to preview it through WF-1 (workflow_plan.preview_proposal, actor="manager" --
never "human", so a pasted "approve" op is always rejected by WF-1's own
WORKFLOW_HUMAN_REQUIRED check, exactly like the TaskSpec's security section requires), reviews
the diff summary, and only reaches 反映 (apply_and_save_proposal, one call, behind its own
messagebox confirmation) once validation against the *current* pasted text succeeded. Editing
the paste box after a successful 検証 disables 反映 again until the human re-validates. The
pasted text is untrusted data start to finish: it is never used to choose a command, a path or
a repository, and every failure the human sees is one of this module's own fixed Japanese
reason strings (never raw exception text, never a copy of the pasted JSON) -- see
validate_proposal_text and the IMPORT_REASON_* constants below.

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
 - WorkflowImportDialog always calls workflow_plan.preview_proposal/apply_and_save_proposal with
   actor="manager", never "human" -- a pasted "approve" op is rejected by WF-1's own
   WORKFLOW_HUMAN_REQUIRED check every time, and a human's own approval still only ever happens
   through this window's own 承認 button above. Like every other button in this module, it never
   calls a candidate-approval, push, BUILD, UPDATE or RELEASE entry point, and the pasted JSON is
   never used to choose a command, a path or a repository -- only task_id values and numbers
   (already validated by WF-1's own _identifier()) and this module's own fixed Japanese reason
   strings ever reach the screen; an exception's own message text is never shown.
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
NEW_PLAN_NAME_EMPTY_TEXT = "計画の名前を入力してください"
NEW_PLAN_NAME_INVALID_TEXT = "計画の名前を確認してください（長さや使える文字）。"
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

# --------------------------------------------------------------------------- WF-3b: import dialog
#
# Fixed, content-free vocabulary only: every one of these strings is shown as-is, never built
# from the pasted text, a JSON value inside it, or an exception's own message.

PROPOSAL_PASTE_MAX_CHARS = 100_000
IMPORT_REASON_TOO_LONG = f"貼り付けが長すぎます（上限 {PROPOSAL_PASTE_MAX_CHARS} 文字）。検証していません。"
IMPORT_REASON_INVALID_FORMAT = "変更案の書式が正しくありません。JSON の形式と plan_id / base_revision / ops を確認してください。"
IMPORT_REASON_PLAN_ID_MISMATCH = "変更案の plan_id が、この計画と一致しません。"
IMPORT_REASON_STALE = "計画が更新されています。最新の状態をコピーして、マネージャーに案を作り直してもらってください。"
IMPORT_REASON_APPROVE_NOT_ALLOWED = "承認の操作はここでは使えません。承認は人が計画の画面の「承認」ボタンで行ってください。"
IMPORT_REASON_LOCKED = "実行中のタスクは変更できません。"
IMPORT_REASON_GENERIC_INVALID = "変更案の検証に失敗しました（依存関係の循環などタスクの内容を確認してください）。"
IMPORT_APPLY_FAILED_TEXT = "反映に失敗しました。計画を再読み込みしてください。"
IMPORT_APPLY_SUCCESS_TEXT = "反映しました。"
IMPORT_APPLY_CONFIRM_TEXT = "この変更案を計画に反映しますか？"
IMPORT_STALE_SINCE_VALIDATION_TEXT = "貼り付けの内容が変わりました。もう一度検証してください。"

# WF-1's own default WorkflowError code ('WORKFLOW_INVALID', workflow_plan._require's own
# default) covers many different shapes of "invalid" (malformed ops, bad task fields, a
# circular dependency, ...) under one string -- this window cannot and does not try to tell
# those apart beyond what the three pre-checks in validate_proposal_text already do locally
# (paste length, JSON shape, plan_id, base_revision); anything else WF-1 rejects lands on
# IMPORT_REASON_GENERIC_INVALID, which names the circular-dependency case explicitly since that
# is the one the TaskSpec calls out by name.
_IMPORT_ERROR_REASONS = {
    "WORKFLOW_STALE": IMPORT_REASON_STALE,
    "WORKFLOW_HUMAN_REQUIRED": IMPORT_REASON_APPROVE_NOT_ALLOWED,
    "WORKFLOW_LOCKED": IMPORT_REASON_LOCKED,
}


def validate_proposal_text(text: str, plan: dict, *, preview_fn, registered_keys):
    """Pure classification of one pasted proposal (Tk-free, easy to unit test) against the
    currently loaded plan. Returns (proposal, summary, new_revision, None) on success, or
    (None, None, None, reason) on failure where reason is always one of this module's own
    fixed Japanese strings above -- never exception text, never a fragment of the pasted JSON.
    preview_fn is always called with actor="manager" (never "human"): a pasted "approve" op is
    therefore always rejected by WF-1's own WORKFLOW_HUMAN_REQUIRED check, never silently
    accepted here."""
    if len(text) > PROPOSAL_PASTE_MAX_CHARS:
        return None, None, None, IMPORT_REASON_TOO_LONG
    try:
        proposal = json.loads(text)
    except (ValueError, RecursionError):
        # A deeply nested array/object (e.g. 2000 levels of "[") is within the length cap but
        # still overflows the C json decoder's own recursion limit -- that is a malformed-input
        # case to this dialog, not a crash, so it gets the same fixed reason as any other
        # unparsable paste.
        return None, None, None, IMPORT_REASON_INVALID_FORMAT
    if not (isinstance(proposal, dict) and set(proposal) == {"plan_id", "base_revision", "ops"}):
        return None, None, None, IMPORT_REASON_INVALID_FORMAT
    if not isinstance(proposal.get("plan_id"), str) or proposal["plan_id"] != plan["plan_id"]:
        return None, None, None, IMPORT_REASON_PLAN_ID_MISMATCH
    if type(proposal.get("base_revision")) is not int or proposal["base_revision"] != plan["revision"]:
        return None, None, None, IMPORT_REASON_STALE
    try:
        summary = preview_fn(plan, proposal, actor="manager", registered_keys=registered_keys)
    except wf.WorkflowError as exc:
        return None, None, None, _IMPORT_ERROR_REASONS.get(str(exc), IMPORT_REASON_GENERIC_INVALID)
    return proposal, summary, plan["revision"] + 1, None


def import_summary_text(summary: dict, new_revision: int) -> str:
    """Pure formatting of WF-1's own diff_summary() plus the next revision number. Every value
    shown here is either a fixed Japanese word, an already-validated task_id
    (workflow_plan._identifier's own alphabet -- safe to display as-is, same reasoning as
    task_row_line above) or a plain int; never proposal free text."""
    lines = []
    for key, label in (("added", "追加"), ("changed", "変更"), ("deleted", "削除"),
                        ("reordered", "並べ替え")):
        entry = summary[key]
        ids = ",".join(entry["task_ids"]) if entry["task_ids"] else NO_DEPENDS_WORD
        lines.append(f"{label}: {entry['count']}件  {ids}")
    lines.append(f"反映後の revision: {new_revision}")
    return "\n".join(lines)


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


# DCC Task WF-4a: workflow_runner.plan_start_block_reason's own fixed codes -> this module's own
# fixed Japanese label, same convention as STATUS_LABELS above for a task's own status.
START_BLOCK_LABELS = {
    wr.START_BLOCK_PLAN_AUTO_RUN_OFF: "計画の自動実行が OFF",
    wr.START_BLOCK_GLOBAL_OFF: "全体の停止スイッチが OFF",
    wr.START_BLOCK_NO_APPROVED: "承認済みのタスクがない",
    wr.START_BLOCK_DEPENDS_INCOMPLETE: "依存するタスクが完了していない",
    wr.START_BLOCK_PAUSED: "計画が一時停止中",
    wr.START_BLOCK_RUNNING: "実行中のタスクがある",
    wr.START_BLOCK_REPO_BUSY: "対象のリポジトリで他の処理が動いている、または確認できない",
    wr.START_BLOCK_LIMIT_REACHED: "本日の上限に達した",
    wr.START_BLOCK_RECORD_UNAVAILABLE: "記録を取得できていない",
    wr.START_BLOCK_CAN_START: "開始できる（次の周期で始まる）",
}
START_BLOCK_REPO_BUSY_HINT_TEXT = "Orchestrator の画面で、動いている Run や古い記録を確認してください"


def start_block_reason_text(reason: "wr.PlanStartBlockReason") -> str:
    """Pure formatting of one PlanStartBlockReason into the single line the plan window shows:
    a fixed label, plus task_id (already-validated, workflow_plan._identifier's own alphabet --
    safe to display as-is) when the reason has one, plus the fixed repo-busy hint when that is
    the reason -- never an AI's output, a Task's own body, a path or exception text."""
    label = START_BLOCK_LABELS.get(reason.code, "")
    if reason.task_id:
        label = f"{label}（{reason.task_id}）"
    if reason.code == wr.START_BLOCK_REPO_BUSY:
        label = f"{label}。{START_BLOCK_REPO_BUSY_HINT_TEXT}"
    return label


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


def validate_new_plan_name(raw_name: str) -> str | None:
    """Pure precheck for the new-plan name field: empty/whitespace-only gets the TaskSpec's own
    exact fixed text; anything else workflow_plan._label would also reject on save (too long,
    a character outside its own display-label alphabet) shares one fixed reason -- the
    authoritative rule stays wf._label's own (reused, never re-expressed here), so this can never
    accept a name save_plan would then reject. Returns None when the name is fine to save."""
    name = raw_name.strip()
    if not name:
        return NEW_PLAN_NAME_EMPTY_TEXT
    try:
        wf._label(name)
    except wf.WorkflowError:
        return NEW_PLAN_NAME_INVALID_TEXT
    return None


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
                 runner_state: "wr.WorkflowRunnerState | None" = None,
                 list_plans_fn: Callable[[object], list] | None = None,
                 load_plan_fn=None, save_plan_fn=None, apply_proposal_fn=None,
                 set_plan_auto_run_fn=None, load_runner_config_fn=None,
                 daily_limit_reached_fn=None, plan_start_block_reason_fn=None,
                 copy_to_clipboard: Callable[[str], None] | None = None,
                 ) -> None:
        from .app import (DARK_BG, DARK_MUTED, configure_combobox_popup,
                          configure_dark_listbox, configure_dark_text)

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
        # DCC Task WF-4a: the same WorkflowRunnerState instance app.py's own background loop holds
        # for this DCC process's lifetime (never a second one this window would own) -- so
        # _refresh_start_reason_notice's call into plan_start_block_reason shares the real cycle's
        # own in-memory daily count (see plan_start_block_reason's own docstring for why a second,
        # independent disk read cannot be trusted to agree with it after a save failure). None here
        # (every test, and any standalone caller) falls back to plan_start_block_reason's own
        # disk-only path -- correct in isolation, just not tied to a live cycle's own state.
        self._runner_state = runner_state
        self._list_plans_fn = list_plans_fn or _list_plans
        self._load_plan_fn = load_plan_fn or wf.load_plan
        self._save_plan_fn = save_plan_fn or wf.save_plan
        self._apply_proposal_fn = apply_proposal_fn or wf.apply_and_save_proposal
        self._set_plan_auto_run_fn = set_plan_auto_run_fn or wr.set_plan_auto_run_allowed
        self._load_runner_config_fn = load_runner_config_fn or wr.load_workflow_runner_config
        self._daily_limit_reached_fn = daily_limit_reached_fn or wr.daily_limit_reached
        self._plan_start_block_reason_fn = plan_start_block_reason_fn or wr.plan_start_block_reason
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
        self.create_plan_notice_var = tk.StringVar(value="")
        self.load_notice_var = tk.StringVar(value="")
        self.pause_notice_var = tk.StringVar(value="")
        self.limit_notice_var = tk.StringVar(value="")
        self.start_reason_var = tk.StringVar(value="")
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
        configure_combobox_popup(self.plan_combo)
        self.plan_combo.bind("<<ThemeChanged>>",
                             lambda _e: configure_combobox_popup(self.plan_combo), add="+")
        self.plan_combo.pack(side="left", padx=(4, 12))
        self.plan_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_plan_combo_selected())
        ttk.Entry(select_row, textvariable=self.new_plan_name_var, width=24).pack(side="left")
        ttk.Button(select_row, text="新規計画の作成", command=self._on_create_plan).pack(
            side="left", padx=(4, 0))
        ttk.Label(select_row, textvariable=self.create_plan_notice_var, foreground="#e3b341").pack(
            side="left", padx=(8, 0))

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
        ttk.Label(auto_row, text="次のタスク:").pack(side="left", padx=(12, 0))
        ttk.Label(auto_row, textvariable=self.start_reason_var, foreground=DARK_MUTED).pack(
            side="left", padx=(4, 0))

        copy_row = ttk.Frame(right)
        copy_row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(copy_row, text="状態をコピー", command=self._on_copy_status).pack(side="left")
        self.import_button = ttk.Button(copy_row, text="変更案を取り込む",
                                         command=self._on_import_proposal)
        self.import_button.pack(side="left", padx=(8, 0))
        _set_enabled(self.import_button, False)

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
        raw_name = self.new_plan_name_var.get()
        reason = validate_new_plan_name(raw_name)
        if reason is not None:
            self.create_plan_notice_var.set(reason)
            return
        name = raw_name.strip()
        plan_id = _generate_plan_id()
        new_plan = {"plan_id": plan_id, "name": name, "revision": 0, "tasks": []}
        try:
            self._save_plan_fn(new_plan, root=self._plans_root, registered_keys=self._registered_keys)
        except (wf.WorkflowError, wf.WorkflowStorageError):
            self.create_plan_notice_var.set("")
            messagebox.showerror("開発計画", CREATE_FAILED_TEXT, parent=self.window)
            return
        self.create_plan_notice_var.set("")
        self.new_plan_name_var.set("")
        self._reload_plan_list()
        self.plan_select_var.set(self._plan_display(plan_id, name))
        self.select_plan(plan_id)

    # ---------------------------------------------------------------- rendering
    def _render_plan(self) -> None:
        self._render_tasks()
        self._refresh_pause_and_limit_notice()
        self._refresh_auto_run_checkbox()
        self._refresh_start_reason_notice()
        _set_enabled(self.import_button, self.plan is not None)

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

    # ---------------------------------------------------------------- WF-3b: import a proposal
    def _on_import_proposal(self) -> None:
        if self.plan is None:
            return
        WorkflowImportDialog(
            self.window, plan=self.plan, plans_root=self._plans_root,
            registered_keys=self._registered_keys, apply_proposal_fn=self._apply_proposal_fn,
            on_applied=self._on_import_applied)

    def _on_import_applied(self, new_plan: dict) -> None:
        if self.plan is not None and new_plan["plan_id"] == self.plan["plan_id"]:
            self.plan = new_plan
            self._render_plan()

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
        self._refresh_start_reason_notice()

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

    def _refresh_start_reason_notice(self) -> None:
        """DCC Task WF-4a: one fixed-vocabulary line for the selected plan's own next task,
        re-read on every reload/tick (_render_plan) and on every auto-run toggle. Delegates the
        actual judgment to workflow_runner.plan_start_block_reason -- never re-decided here --
        and only ever displays that function's own fixed code/task_id (see start_block_reason_text
        above): never an AI's output, a Task's own body, a path or exception text."""
        if self.plan is None:
            self.start_reason_var.set("")
            return
        try:
            reason = self._plan_start_block_reason_fn(
                self.plan, runner_config_path=self._runner_config_path,
                state=self._runner_state, daily_count_path=self._daily_count_path)
        except Exception:  # noqa: BLE001 - never block rendering on a bad config/count/repo read
            self.start_reason_var.set("")
            return
        self.start_reason_var.set(start_block_reason_text(reason))

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


class WorkflowImportDialog:
    """DCC Task WF-3b: paste one external manager AI's proposal JSON, validate+preview it
    against the plan snapshot the parent window already had loaded, and only reflect it into
    the plan once a human has seen the diff summary and pressed 反映 followed by its own
    confirmation dialog. See the module docstring and validate_proposal_text above for the
    security posture; this class only wires that pure logic to widgets.

    plan is only the parent WorkflowPlanWindow's own self.plan snapshot at the moment this dialog
    was opened, used to know which plan_id to reload. Every 検証 reloads that plan_id fresh via
    load_plan_fn (trusted plan_id + plans_root, never anything from the pasted text) before
    validating, so a plan that was changed on disk after this dialog opened is validated against
    its *current* revision, not a stale one. apply_proposal_fn then re-checks base_revision again
    against whatever is actually on disk at save time (workflow_plan.update_plan's own per-plan
    lock), so a plan that moved on between a successful 検証 and 反映 still fails safely
    (WORKFLOW_STALE -> IMPORT_REASON_STALE) rather than silently applying on stale data."""

    def __init__(self, master: tk.Misc, *, plan: dict, plans_root, registered_keys,
                 load_plan_fn=None, preview_proposal_fn=None, apply_proposal_fn=None,
                 on_applied: Callable[[dict], None] | None = None) -> None:
        from .app import DARK_BG, configure_dark_text

        self._plan = plan
        self._plans_root = plans_root
        self._registered_keys = registered_keys
        self._load_plan_fn = load_plan_fn or wf.load_plan
        self._preview_proposal_fn = preview_proposal_fn or wf.preview_proposal
        self._apply_proposal_fn = apply_proposal_fn or wf.apply_and_save_proposal
        self._on_applied = on_applied
        self._closed = False
        self._validated_text: str | None = None
        self._validated_proposal: dict | None = None

        self.window = tk.Toplevel(master)
        self.window.title("変更案を取り込む")
        self.window.geometry("640x700")
        self.window.minsize(560, 600)
        self.window.configure(background=DARK_BG)
        self.window.protocol("WM_DELETE_WINDOW", self._close)

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=f"変更案（JSON、上限 {PROPOSAL_PASTE_MAX_CHARS} 文字）を貼り付けてください").pack(
            anchor="w")
        self.paste_text = tk.Text(outer, height=12, wrap="word")
        configure_dark_text(self.paste_text)
        self.paste_text.pack(fill="both", expand=True, pady=(4, 8))
        # <<Modified>> (not <KeyRelease>) so a middle-click/Ctrl+V paste or any other edit that
        # never fires a key-release still disables 反映 until the human re-validates.
        self.paste_text.bind("<<Modified>>", self._on_text_modified)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        self.validate_button = ttk.Button(buttons, text="検証", command=self._on_validate)
        self.validate_button.pack(side="left")
        self.apply_button = ttk.Button(buttons, text="反映", command=self._on_apply)
        self.apply_button.pack(side="left", padx=(8, 0))
        self.apply_button.state(["disabled"])
        ttk.Button(buttons, text="閉じる", command=self._close).pack(side="left", padx=(8, 0))

        ttk.Label(outer, text="差分の要約（読み取り専用）").pack(anchor="w", pady=(10, 0))
        self.summary_text = tk.Text(outer, height=10, wrap="word", state="disabled")
        configure_dark_text(self.summary_text)
        self.summary_text.pack(fill="both", expand=True, pady=(4, 4))

        self.notice_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.notice_var, foreground="#e3b341", wraplength=600,
                  justify="left").pack(anchor="w", pady=(4, 0))

    def exists(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    # ---------------------------------------------------------------- paste box
    def _current_paste_text(self) -> str:
        # A real tk.Text always reports a trailing newline from its own final character; this
        # strips exactly that one artifact so length-checking and change-detection act on what
        # the human actually pasted/typed, not on a widget implementation detail.
        text = self.paste_text.get("1.0", "end")
        if text.endswith("\n"):
            text = text[:-1]
        return text

    def _on_text_modified(self, _event=None) -> None:
        # Tk only fires <<Modified>> when the flag actually changes, so resetting it to False
        # below fires this handler once more with edit_modified() already False -- a harmless
        # second call that does nothing, never an infinite loop.
        if self.paste_text.edit_modified():
            self._on_paste_changed()
            self.paste_text.edit_modified(False)

    def _on_paste_changed(self) -> None:
        if self._current_paste_text() != self._validated_text:
            self._validated_proposal = None
            self.apply_button.state(["disabled"])

    # ---------------------------------------------------------------- 検証
    def _set_summary_text(self, text: str) -> None:
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        if text:
            self.summary_text.insert("1.0", text)
        self.summary_text.configure(state="disabled")

    def _on_validate(self) -> None:
        text = self._current_paste_text()
        self._validated_text = text
        self._validated_proposal = None
        self.apply_button.state(["disabled"])
        try:
            # Reload the plan_id this dialog was opened for -- never anything from the pasted
            # text -- so validation always runs against the plan's *current* on-disk revision,
            # not a stale snapshot taken when this dialog was opened.
            current_plan = self._load_plan_fn(self._plan["plan_id"], root=self._plans_root,
                                               registered_keys=self._registered_keys)
        except wf.WorkflowError:
            self.notice_var.set(LOAD_FAILED_TEXT)
            self._set_summary_text("")
            return
        self._plan = current_plan
        proposal, summary, new_revision, reason = validate_proposal_text(
            text, self._plan, preview_fn=self._preview_proposal_fn,
            registered_keys=self._registered_keys)
        if reason is not None:
            self.notice_var.set(reason)
            self._set_summary_text("")
            return
        self._validated_proposal = proposal
        self.notice_var.set("")
        self._set_summary_text(import_summary_text(summary, new_revision))
        self.apply_button.state(["!disabled"])

    # ---------------------------------------------------------------- 反映
    def _on_apply(self) -> None:
        if self._validated_proposal is None:
            return
        if self._current_paste_text() != self._validated_text:
            # Defense in depth: the paste box changed without this button's state catching up
            # (should already be disabled by _on_paste_changed) -- never reflect text that was
            # not the text 検証 actually previewed.
            self.notice_var.set(IMPORT_STALE_SINCE_VALIDATION_TEXT)
            self.apply_button.state(["disabled"])
            return
        if not messagebox.askyesno("変更案を取り込む", IMPORT_APPLY_CONFIRM_TEXT, parent=self.window):
            return
        proposal = self._validated_proposal
        try:
            new_plan, _summary = self._apply_proposal_fn(
                self._plan["plan_id"], proposal, actor="manager",
                root=self._plans_root, registered_keys=self._registered_keys)
        except wf.WorkflowError as exc:
            # apply_and_save_proposal re-checks base_revision against the plan actually on disk
            # at save time: if it moved on since 検証 succeeded (e.g. a human operation landed in
            # between), this is WORKFLOW_STALE, same fixed reason as a stale paste would get at
            # 検証 time -- never the generic failure text for that one well-known case.
            self.notice_var.set(_IMPORT_ERROR_REASONS.get(str(exc), IMPORT_APPLY_FAILED_TEXT))
            self._validated_proposal = None
            self.apply_button.state(["disabled"])
            return
        self._plan = new_plan
        self._validated_proposal = None
        self.apply_button.state(["disabled"])
        self.notice_var.set(f"{IMPORT_APPLY_SUCCESS_TEXT}（revision: {new_plan['revision']}）")
        if self._on_applied is not None:
            self._on_applied(new_plan)

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.window.destroy()
