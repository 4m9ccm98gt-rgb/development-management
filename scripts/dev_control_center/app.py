"""Tkinter UI for the Development Control Center."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import (
    ControlCenterConfigError,
    GitHubState,
    RemoteRepo,
    RepoDefinition,
    active_repo_definitions,
    apply_local_candidate,
    build_new_repo_setup_prompt,
    candidate_sha_is_valid,
    choice_text,
    clone_new_repository,
    decide_lifecycle,
    fetch_github_state,
    inspect_repo,
    list_github_repositories,
    load_repo_definitions,
    short_sha,
    unmanaged_github_repositories,
)
from . import provenance, processes, entrypoints as machine_entries
from .loader import Coordinator, NoticeKind
from .selection import (
    DEV_MANAGEMENT,
    GLOBAL_REMOTE_REPOS,
    GLOBAL_SELF_UPDATE,
    IntentSnapshot,
    Loaders,
    SelectionState,
)
from .timing import TIMING, HeartbeatMonitor

DM_ROOT = Path(__file__).resolve().parents[2]
REPOS_ROOT = DM_ROOT.parent
TYPES_PATH = DM_ROOT / "scripts" / "repo_types.toml"
BRANCHES_PATH = DM_ROOT / "scripts" / "dev_control_center_repos.toml"
LAUNCHER_PATH = DM_ROOT / "DEV_CONTROL_CENTER.pyw"
HEARTBEAT_MS = 50
ACTIVE_OPERATIONS: dict[int, tuple[str, str]] = {}
LOADING_TEXT = "読込中..."
STATE_CHANGED_TEXT = "CONFIRMEDの後に状態が変わったため中止しました。再確認してください"

DARK_BG = "#0f1419"
DARK_SURFACE = "#171c22"
DARK_FIELD = "#20262d"
DARK_BORDER = "#30363d"
DARK_FG = "#e6edf3"
DARK_MUTED = "#9ba7b4"
DARK_DISABLED_BG = "#1a2026"
DARK_DISABLED_FG = "#6e7681"
DARK_ACCENT = "#2f81f7"
DARK_SELECTION = "#1f6feb"


def configure_dark_theme(master: tk.Tk) -> None:
    """Apply the DCC dark palette to ttk and the root window."""
    master.configure(background=DARK_BG)
    style = ttk.Style(master)
    style.theme_use("clam")

    style.configure(".", background=DARK_BG, foreground=DARK_FG)
    style.configure("TFrame", background=DARK_BG)
    style.configure("TLabel", background=DARK_BG, foreground=DARK_FG)
    style.configure(
        "TLabelframe",
        background=DARK_BG,
        foreground=DARK_FG,
        bordercolor=DARK_BORDER,
        lightcolor=DARK_BORDER,
        darkcolor=DARK_BORDER,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=DARK_BG,
        foreground=DARK_FG,
    )
    style.configure(
        "TButton",
        background=DARK_FIELD,
        foreground=DARK_FG,
        bordercolor=DARK_BORDER,
        lightcolor=DARK_BORDER,
        darkcolor=DARK_BORDER,
        focuscolor=DARK_FIELD,
        padding=(8, 5),
    )
    style.map(
        "TButton",
        background=[
            ("disabled", DARK_DISABLED_BG),
            ("pressed", DARK_SELECTION),
            ("active", DARK_ACCENT),
        ],
        foreground=[
            ("disabled", DARK_DISABLED_FG),
            ("pressed", "#ffffff"),
            ("active", "#ffffff"),
        ],
        bordercolor=[
            ("disabled", DARK_BORDER),
            ("active", DARK_ACCENT),
        ],
    )
    style.configure(
        "TEntry",
        fieldbackground=DARK_FIELD,
        foreground=DARK_FG,
        insertcolor=DARK_FG,
        bordercolor=DARK_BORDER,
        lightcolor=DARK_BORDER,
        darkcolor=DARK_BORDER,
        padding=(6, 4),
    )
    style.map(
        "TEntry",
        fieldbackground=[
            ("disabled", DARK_DISABLED_BG),
            ("readonly", DARK_FIELD),
        ],
        foreground=[("disabled", DARK_DISABLED_FG)],
        bordercolor=[("focus", DARK_ACCENT)],
    )


def configure_dark_listbox(widget: tk.Listbox) -> None:
    widget.configure(
        background=DARK_SURFACE,
        foreground=DARK_FG,
        selectbackground=DARK_SELECTION,
        selectforeground="#ffffff",
        highlightbackground=DARK_BORDER,
        highlightcolor=DARK_ACCENT,
        highlightthickness=1,
        relief="flat",
        borderwidth=0,
        activestyle="none",
    )


def configure_dark_text(widget: tk.Text) -> None:
    widget.configure(
        background=DARK_SURFACE,
        foreground=DARK_FG,
        insertbackground=DARK_FG,
        selectbackground=DARK_SELECTION,
        selectforeground="#ffffff",
        highlightbackground=DARK_BORDER,
        highlightcolor=DARK_ACCENT,
        highlightthickness=1,
        relief="flat",
        borderwidth=0,
    )


class _TkScheduler:
    """Adapter so SelectionState can debounce through Tk's after()."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master

    def after(self, ms: int, fn):
        return self.master.after(ms, fn)

    def cancel(self, handle) -> None:
        self.master.after_cancel(handle)


def _terminate_ai_process_tree(process: subprocess.Popen) -> None:
    """Kill the AI Orchestrator process and its full child tree (Claude/Codex
    CLI subprocesses included), mirroring orchestrator.py's own
    _terminate_process_tree used for its internal test-timeout handling."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            process.terminate()
    except OSError:
        pass


AI_SAFETY_STOP_REASON = "ユーザーによる安全停止"
_AI_RUN_DIR_MARKER = "[Preflight] run_dir="


def _merge_json_file(path: Path, updates: dict[str, object]) -> None:
    """Merge `updates` into the JSON object at `path`, creating it if missing.

    Only the given keys are added/overwritten; every other existing key
    (run_id, worktree, stage, round, provider/session fields, ...) is kept
    exactly as the Orchestrator run left it.
    """
    payload: dict[str, object] = {}
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload = raw
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload.update(updates)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _mark_ai_run_stopped(run_dir: Path) -> None:
    """Record the AI safety stop onto the run's durable status.json/result.json.

    Additive merge only (see _merge_json_file): existing run_id / worktree /
    stage / round / provider-session fields are preserved. The isolated
    worktree itself is never touched here, and no Git/GitHub command runs.
    """
    now = datetime.now().isoformat(timespec="seconds")
    _merge_json_file(
        run_dir / "status.json",
        {"status": "stopped", "reason": AI_SAFETY_STOP_REASON, "updated_at": now},
    )
    _merge_json_file(
        run_dir / "result.json",
        {
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "status": "stopped",
            "error": AI_SAFETY_STOP_REASON,
            "error_code": "USER_SAFETY_STOP",
        },
    )


_REVIEW_VERDICTS = ("PASS", "FAIL", "PENDING")
_REVIEW_NO_RUN_TEXT = "FINAL REVIEW待ちのrun_dirを指定してください"
_REVIEW_DECISION_TEMPLATE = (
    '{"request_id": "<final-review-request.jsonのrequest_id>", '
    '"verdict": "PASS | FAIL | PENDING", "summary": "<レビュー要約>"}'
)


@dataclass(frozen=True)
class ReviewResumePlan:
    """Read-only inspection of a review_pending run; `message` explains a refusal."""

    ok: bool
    message: str
    run_dir: Path | None = None
    task: str = ""
    tests: tuple[str, ...] = ()
    max_rounds: int = 0
    request_id: str = ""


def _read_json_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return raw


def _same_path(left: object, right: Path) -> bool:
    try:
        return os.path.normcase(str(Path(str(left)).resolve())) == os.path.normcase(str(right.resolve()))
    except (OSError, ValueError):
        return False


def inspect_review_pending_run(
    run_dir_text: str,
    repo_root: Path,
    expected_branch: str,
    head_sha: str,
) -> ReviewResumePlan:
    """Decide whether `run_dir` is a review_pending run of this repo that DCC may resume.

    Only reads result.json / task.md / final-review-request.json. The values the
    Orchestrator requires to be unchanged (TaskSpec, tests, max-rounds) come from
    the run itself, never from the current UI fields.
    """
    text = run_dir_text.strip()
    if not text:
        return ReviewResumePlan(False, "run_dirが未指定です（FINAL REVIEW待ちのrunだけ再開できます）")
    run_dir = Path(text)
    try:
        result = _read_json_object(run_dir / "result.json")
    except (OSError, ValueError) as exc:
        return ReviewResumePlan(False, f"result.jsonを読めません: {exc}")
    status = str(result.get("status", ""))
    if status != "review_pending":
        return ReviewResumePlan(False, f"status={status or '不明'} — review_pending以外は再開できません")
    if not _same_path(result.get("repo", ""), repo_root) or result.get("source_branch") != expected_branch:
        return ReviewResumePlan(False, "選択中のrepo / branchのrunではありません")
    if str(result.get("base_sha", "")).lower() != head_sha.lower():
        return ReviewResumePlan(False, "runのbase SHAが現在のlocal HEADと一致しません")
    tests = result.get("tests")
    max_rounds = result.get("max_rounds")
    if (not isinstance(tests, list) or not tests
            or not all(isinstance(item, str) and item for item in tests)
            or not isinstance(max_rounds, int) or isinstance(max_rounds, bool)):
        return ReviewResumePlan(False, "runのtests / max_roundsが不正です")
    try:
        task = (run_dir / "task.md").read_text(encoding="utf-8").strip()
        request = _read_json_object(run_dir / "final-review-request.json")
    except (OSError, ValueError) as exc:
        return ReviewResumePlan(False, f"run記録を読めません: {exc}")
    request_id = request.get("request_id")
    if not task or not isinstance(request_id, str) or not request_id:
        return ReviewResumePlan(False, "task.md / final-review-request.jsonが不正です")
    return ReviewResumePlan(
        True,
        f"FINAL REVIEW待ち — request_id={request_id}",
        run_dir=run_dir,
        task=task,
        tests=tuple(tests),
        max_rounds=max_rounds,
        request_id=request_id,
    )


def parse_review_decision(text: str, request_id: str) -> tuple[dict[str, object] | None, str]:
    """Validate a final-review-decision.json body; returns (decision, error)."""
    if not text.strip():
        return None, "レビュー結果（JSON）が空です"
    try:
        decision = json.loads(text)
    except ValueError as exc:
        return None, f"レビュー結果がJSONではありません: {exc}"
    if not isinstance(decision, dict):
        return None, "レビュー結果はJSONオブジェクトである必要があります"
    if decision.get("request_id") != request_id:
        return None, f"request_idが一致しません（期待: {request_id}）"
    summary = decision.get("summary")
    if decision.get("verdict") not in _REVIEW_VERDICTS or not isinstance(summary, str) or not summary.strip():
        return None, "verdictはPASS / FAIL / PENDING、summaryは空でない文字列が必要です"
    return decision, ""


def build_review_resume_command(
    plan: ReviewResumePlan,
    repo_root: Path,
    expected_branch: str,
    result_path: Path,
    decision_path: Path,
) -> list[str]:
    """Orchestrator `run --resume-review`: same TaskSpec / tests / budget as the saved run."""
    command = [
        sys.executable,
        str(DM_ROOT / "tools" / "ai_orchestrator" / "orchestrator.py"),
        "run",
        "--repo",
        str(repo_root),
        "--expected-branch",
        expected_branch,
        "--task",
        plan.task,
    ]
    for test in plan.tests:
        command += ["--test", test]
    command += [
        "--result-file",
        str(result_path),
        "--max-rounds",
        str(plan.max_rounds),
        "--test-timeout",
        "600",
        "--resume-review",
        str(plan.run_dir),
        "--final-review-decision",
        str(decision_path),
    ]
    return command


def _unlink_quietly(path: object) -> None:
    if isinstance(path, Path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _spawn_ai_process(command: list[str]) -> subprocess.Popen[str]:
    """Start an Orchestrator child with the UTF-8 pipe contract (shared by run / resume)."""
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.Popen(
        command,
        cwd=DM_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=child_env,
    )


class App(ttk.Frame):
    def __init__(self, master: tk.Tk, *, orchestrator_mode: bool = False) -> None:
        self.orchestrator_mode = orchestrator_mode
        self.orchestrator_window = None
        self.orchestrator_app = None
        self._closed = False
        configure_dark_theme(master)
        super().__init__(master, padding=14)
        self.master = master
        self.all_definitions = load_repo_definitions(TYPES_PATH, BRANCHES_PATH)
        self.definitions = active_repo_definitions(TYPES_PATH, BRANCHES_PATH)
        self.coordinator = Coordinator(timing=TIMING)
        self.selection = SelectionState(
            self.coordinator,
            self.definitions,
            self,
            Loaders(REPOS_ROOT),
            scheduler=_TkScheduler(master),
        )
        self._heartbeat = HeartbeatMonitor(HEARTBEAT_MS / 1000)
        self._suggest_seed = ""
        self.active_process = None
        self.pending_preflight = False
        self._stream_key = None
        self._stream_open = False
        self.lifecycle_events: queue.Queue = queue.Queue(maxsize=2048)
        self.lifecycle_jobs: dict[str, object] = {}
        self.lifecycle_cancellations: dict[str, threading.Event] = {}
        self.ai_output_queue: queue.Queue[str] = queue.Queue()
        self.ai_context: dict[str, object] | None = None
        self.ai_stop_requested = False
        self.ai_task_by_repo: dict[str, str] = {}
        self.ai_test_by_repo: dict[str, str] = {}
        self.unmanaged_repos: list[RemoteRepo] = []
        self._applying_lifecycle = False
        self.self_update_sha = ""
        self.self_update_ci_state = "UNKNOWN"

        self.title_var = tk.StringVar()
        self.meta_var = tk.StringVar()
        self.branch_var = tk.StringVar()
        self.head_var = tk.StringVar()
        self.origin_var = tk.StringVar()
        self.clean_var = tk.StringVar()
        self.github_head_var = tk.StringVar(value="-")
        self.ci_var = tk.StringVar(value="-")
        self.pr_var = tk.StringVar(value="-")
        self.candidate_var = tk.StringVar()
        self.candidate_source_var = tk.StringVar(value="-")
        self.sync_var = tk.StringVar()
        self.run_var = tk.StringVar()
        self.build_var = tk.StringVar()
        self.release_var = tk.StringVar()
        self.release_button_var = tk.StringVar(value="UPDATE")
        self.banner_var = tk.StringVar(value="repoを選択してください")
        self.remote_status_var = tk.StringVar(value="未確認")
        self.self_update_var = tk.StringVar(value="未確認")
        self.ai_test_var = tk.StringVar()
        self.ai_status_var = tk.StringVar(value="待機")
        self.review_run_dir_var = tk.StringVar()
        self.review_status_var = tk.StringVar(value=_REVIEW_NO_RUN_TEXT)
        self.review_plan: ReviewResumePlan | None = None

        self._build()
        self.candidate_var.trace_add("write", lambda *_: self._candidate_changed())
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)
        self.master.after(HEARTBEAT_MS, self._heartbeat_tick)
        if self.definitions:
            self.repo_list.selection_set(0)
            self._select_repo()
        # No subprocess or scan runs on the UI thread: these only submit background requests.
        self.master.after(150, self.scan_remote_repos)
        self.master.after(300, self.check_self_update)

    # --- state read only through the epoch-stamped accessors -----------------
    @property
    def current(self) -> RepoDefinition | None:
        return self.selection.current

    @property
    def repo_state(self):
        snapshot = self.selection.authoritative_local(self.current.name) if self.current else None
        return snapshot.repo_state if snapshot else None

    @property
    def entrypoints(self):
        snapshot = self.selection.authoritative_local(self.current.name) if self.current else None
        return snapshot.entrypoints if snapshot else None

    def _github_state(self) -> GitHubState | None:
        return self.selection.authoritative_github(self.current.name) if self.current else None

    def _on_close(self) -> None:
        if getattr(self, "orchestrator_mode", False) is True:
            self.master.withdraw()
            return
        if any(action == "ai_orchestrator" for _, action in ACTIVE_OPERATIONS.values()):
            messagebox.showinfo("AI Orchestrator実行中", "Phase 1ではDCC終了後の継続・再接続は未対応です。\n画面は閉じず、必要ならOrchestrator画面のAI安全停止を操作してください。")
            return
        if ACTIVE_OPERATIONS:
            messagebox.showinfo("工程実行中", "工程完了後にDCCを閉じてください。")
            return
        child = getattr(self, "orchestrator_app", None)
        if isinstance(child, App):
            child._closed = True
            child.selection.close()
        self._closed = True
        if TIMING.enabled:
            TIMING.event("ui-lag-summary", **self._heartbeat.stats())
        self.selection.close()
        # Destroying Tk does not cancel pending Tcl after callbacks. Cancel them
        # before destroying the root, including the hidden Orchestrator view.
        if isinstance(self.master, tk.Tk):
            for token in self.master.tk.call("after", "info"):
                self.master.tk.call("after", "cancel", token)
        self.master.destroy()

    def _heartbeat_tick(self) -> None:
        if self._closed:
            return
        lag = self._heartbeat.beat(time.perf_counter())
        if TIMING.enabled and lag > 0.1:
            TIMING.event("ui-lag", ms=round(lag * 1000))
        TIMING.since_mark("startup", record_as="startup-to-operable")
        try:
            self.selection.pump()
        except Exception:  # noqa: BLE001 - keep the heartbeat alive
            import logging

            logging.getLogger(__name__).exception("selection pump failed")
        self._drain_lifecycle_events()
        self._set_button_states()
        self.master.after(HEARTBEAT_MS, self._heartbeat_tick)

    def _build(self) -> None:
        self.master.title("AI Orchestrator" if self.orchestrator_mode else "Development Control Center")
        self.master.geometry("1200x800" if self.orchestrator_mode else "1080x720")
        self.master.minsize(1080, 720)
        self.pack(fill="both", expand=True)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Managed Repositories", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.repo_list = tk.Listbox(left, width=29, height=12, exportselection=False)
        configure_dark_listbox(self.repo_list)
        self.repo_list.grid(row=1, column=0, sticky="nsew")
        self.repo_list.bind("<<ListboxSelect>>", lambda _e: self._select_repo())
        for item in self.definitions:
            self.repo_list.insert("end", f"{item.name}   [{item.repo_type}]")

        repo_buttons = ttk.Frame(left)
        repo_buttons.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for col in (0, 1):
            repo_buttons.columnconfigure(col, weight=1)
        ttk.Button(repo_buttons, text="全状態更新", command=self.refresh_all).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(repo_buttons, text="GitHubを開く", command=self.open_github).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        new_box = ttk.LabelFrame(left, text="GitHub未登録repo", padding=8)
        new_box.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(new_box, textvariable=self.remote_status_var, wraplength=300).pack(anchor="w")
        self.new_repo_list = tk.Listbox(new_box, width=29, height=3, exportselection=False)
        configure_dark_listbox(self.new_repo_list)
        self.new_repo_list.pack(fill="x", pady=(6, 6))
        new_buttons = ttk.Frame(new_box)
        new_buttons.pack(fill="x")
        for col in (0, 1):
            new_buttons.columnconfigure(col, weight=1)
        ttk.Button(new_buttons, text="再読込", command=self.scan_remote_repos).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(new_buttons, text="セットアップ開始", command=self.setup_new_repo).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        update_box = ttk.LabelFrame(left, text="Control Center更新", padding=8)
        update_box.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(update_box, textvariable=self.self_update_var, wraplength=300).pack(anchor="w")
        update_buttons = ttk.Frame(update_box)
        update_buttons.pack(fill="x", pady=(6, 0))
        for col in (0, 1):
            update_buttons.columnconfigure(col, weight=1)
        ttk.Button(update_buttons, text="更新確認", command=self.check_self_update).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.self_update_button = ttk.Button(update_buttons, text="更新する", command=self.apply_self_update)
        self.self_update_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(7, weight=1)
        self.main_panel = right
        ttk.Label(right, textvariable=self.title_var, font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.meta_var, wraplength=580).grid(row=1, column=0, sticky="w", pady=(2, 10))

        status = ttk.LabelFrame(right, text="ローカル現在状態", padding=10)
        status.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        status.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("branch", self.branch_var),
            ("HEAD", self.head_var),
            ("origin", self.origin_var),
            ("working tree", self.clean_var),
        ]):
            ttk.Label(status, text=label, width=14).grid(row=row, column=0, sticky="w")
            ttk.Label(status, textvariable=var, wraplength=440).grid(row=row, column=1, sticky="w")

        github_box = ttk.LabelFrame(right, text="GitHub / PR / CI", padding=10)
        github_box.grid(row=5, column=0, sticky="ew", pady=(0, 10))
        github_box.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("branch HEAD", self.github_head_var),
            ("CI", self.ci_var),
            ("open PR", self.pr_var),
        ]):
            ttk.Label(github_box, text=label, width=14).grid(row=row, column=0, sticky="w")
            ttk.Label(github_box, textvariable=var, wraplength=540).grid(row=row, column=1, sticky="w")
        ttk.Button(github_box, text="PR / CIを開く", command=self.open_pr_or_ci).grid(row=0, column=2, rowspan=3, sticky="ns", padx=(12, 0))

        ai_box = ttk.LabelFrame(
            right,
            text="AI開発 — Claude実装 → Verification → Final Review → local candidate",
            padding=12,
        )
        self.ai_panel = ai_box
        if self.orchestrator_mode:
            ai_box.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ai_box.columnconfigure(1, weight=1)
        ttk.Label(ai_box, text="AI依頼", width=14).grid(row=0, column=0, sticky="nw")
        self.ai_task = tk.Text(ai_box, height=8, wrap="word")
        configure_dark_text(self.ai_task)
        self.ai_task.grid(row=0, column=1, columnspan=2, sticky="ew")
        ttk.Label(ai_box, text="テスト", width=14).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(ai_box, textvariable=self.ai_test_var).grid(
            row=1, column=1, sticky="ew", pady=(8, 0)
        )
        self.ai_start_button = ttk.Button(
            ai_box,
            text="AI開発開始",
            command=self.launch_ai_orchestrator,
        )
        self.ai_start_button.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.ai_stop_button = ttk.Button(
            ai_box,
            text="AI安全停止",
            command=self.stop_ai_orchestrator,
        )
        self.ai_stop_button.configure(state="disabled")
        self.ai_stop_button.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(
            ai_box,
            textvariable=self.ai_status_var,
            wraplength=560,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(
            ai_box,
            text="成功時もpush / BUILD / UPDATEは行いません。candidateをローカル適用する前に確認します。",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        review_box = ttk.LabelFrame(ai_box, text="Final Reviewを返して再開（review_pendingのrunのみ）", padding=8)
        review_box.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        review_box.columnconfigure(1, weight=1)
        ttk.Label(review_box, text="run_dir", width=14).grid(row=0, column=0, sticky="w")
        review_run_entry = ttk.Entry(review_box, textvariable=self.review_run_dir_var)
        review_run_entry.grid(row=0, column=1, sticky="ew")
        review_run_entry.bind("<FocusOut>", lambda _event: self._refresh_review_plan())
        review_run_entry.bind("<Return>", lambda _event: self._refresh_review_plan())
        ttk.Button(review_box, text="参照", command=self.browse_review_run_dir).grid(
            row=0, column=2, sticky="ew", padx=(8, 0)
        )
        ttk.Label(review_box, text="レビュー結果", width=14).grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.review_decision = tk.Text(review_box, height=5, wrap="word")
        configure_dark_text(self.review_decision)
        self.review_decision.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(review_box, text="JSONを読み込む", command=self.load_review_decision_file).grid(
            row=1, column=2, sticky="new", padx=(8, 0), pady=(8, 0)
        )
        ttk.Label(review_box, textvariable=self.review_status_var, wraplength=540).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        self.review_resume_button = ttk.Button(
            review_box,
            text="レビュー結果を返して再開",
            command=self.resume_ai_review,
        )
        self.review_resume_button.configure(state="disabled")
        self.review_resume_button.grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(review_box, text=f"形式: {_REVIEW_DECISION_TEMPLATE}", wraplength=540).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

        lifecycle = ttk.LabelFrame(right, text="実機確認・配布", padding=10)
        lifecycle.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for col in range(4):
            lifecycle.columnconfigure(col, weight=1)

        candidate_panel = ttk.Frame(ai_box)
        candidate_panel.grid(row=5, column=0, columnspan=4, sticky="ew")
        ttk.Label(candidate_panel, text="candidate SHA").pack(side="left")
        ttk.Entry(candidate_panel, textvariable=self.candidate_var).pack(side="left", fill="x", expand=True)
        ttk.Label(
            candidate_panel,
            textvariable=self.candidate_source_var,
        ).pack(side="left")

        self.run_button = ttk.Button(
            lifecycle,
            text="RUN",
            command=lambda: self.launch("run"),
        )
        self.run_button.grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(8, 0))
        self.build_button = ttk.Button(
            lifecycle,
            text="BUILD",
            command=lambda: self.launch("build"),
        )
        self.build_button.grid(row=1, column=1, sticky="ew", padx=3, pady=(8, 0))
        self.release_button = ttk.Button(
            lifecycle,
            textvariable=self.release_button_var,
            command=lambda: self.launch("release"),
        )
        self.release_button.grid(row=1, column=2, sticky="ew", padx=3, pady=(8, 0))

        # Kept as a non-visual compatibility hook for legacy/bootstrap lifecycle code.
        self.sync_button = ttk.Button(
            lifecycle,
            text="SYNC",
            command=lambda: self.launch("sync"),
        )

        ttk.Label(
            lifecycle,
            text="RUN / BUILDは現在の作業内容を使用。UPDATEは成果物・配布先の確認が必要です。", wraplength=570,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.orchestrator_button = ttk.Button(lifecycle, text="AI Orchestrator", command=self.open_orchestrator)
        self.orchestrator_button.grid(row=1, column=3, sticky="ew", padx=(3, 0), pady=(8, 0))
        self.operation_stop_button = ttk.Button(lifecycle, text="このrepoの実行を停止", command=self.stop_lifecycle)
        self.operation_stop_button.grid(row=0, column=0, columnspan=2, sticky="w")
        if self.orchestrator_mode:
            lifecycle.grid_remove()
            status.grid_remove()
            github_box.grid_remove()
            new_box.grid_remove()
            update_box.grid_remove()

        entries = ttk.LabelFrame(right, text="検出した正式入口", padding=10)
        # Entry paths are available in tool logs; keep the main screen compact.
        if self.orchestrator_mode:
            entries.grid_remove()
        entries.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("SYNC", self.sync_var),
            ("RUN", self.run_var),
            ("BUILD", self.build_var),
            ("UPDATE/DEPLOY", self.release_var),
        ]):
            ttk.Label(entries, text=label, width=16).grid(row=row, column=0, sticky="nw")
            ttk.Label(entries, textvariable=var, wraplength=560).grid(row=row, column=1, sticky="w")

        log_box = ttk.LabelFrame(right, text="操作ログ", padding=8)
        log_box.grid(row=7, column=0, sticky="nsew")
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=8, state="disabled", wrap="word")
        configure_dark_text(self.log)
        self.log.grid(row=0, column=0, sticky="nsew")
        ttk.Label(right, textvariable=self.banner_var).grid(row=8, column=0, sticky="w", pady=(8, 0))

    def open_orchestrator(self) -> None:
        if self.orchestrator_window is None or not self.orchestrator_window.winfo_exists():
            window = tk.Toplevel(self.master)
            self.orchestrator_window = window
            self.orchestrator_app = App(window, orchestrator_mode=True)
            if self.current:
                child = self.orchestrator_app
                index = next(i for i, d in enumerate(child.definitions) if d.name == self.current.name)
                child.repo_list.selection_clear(0, "end")
                child.repo_list.selection_set(index)
                child._select_repo()
        self.orchestrator_window.deiconify()
        self.orchestrator_window.lift()

    def _repo_busy(self) -> bool:
        if self.active_process is not None:
            return True
        return bool(self.current and any(name == self.current.name for name, _ in ACTIVE_OPERATIONS.values()))

    def _select_repo(self) -> None:
        selection = self.repo_list.curselection()
        if not selection:
            return
        if self.current:
            self.ai_task_by_repo[self.current.name] = self.ai_task.get("1.0", "end").strip()
            self.ai_test_by_repo[self.current.name] = self.ai_test_var.get().strip()
        # leave(outgoing) + enter(new): no subprocess or file scan on the UI thread.
        self.selection.select(self.definitions[selection[0]].name)

    # --- view interface used by SelectionState (all run on the UI thread) ----
    def on_loading(self, name: str) -> None:
        definition = self.current
        repo_root = REPOS_ROOT / name
        self.title_var.set(name)
        self.meta_var.set(f"{repo_root}   |   type={definition.repo_type}   |   expected branch={definition.branch}")
        self._set_candidate_text(self.selection.provenance.text(name))
        self.ai_task.delete("1.0", "end")
        saved_task = self.ai_task_by_repo.get(name) or definition.initial_ai_task
        if saved_task:
            self.ai_task.insert("1.0", saved_task)
        self.ai_test_var.set(self.ai_test_by_repo.get(name) or definition.initial_test or "")
        self._suggest_seed = self.ai_test_var.get()
        self.ai_status_var.set("待機")
        self.review_run_dir_var.set("")
        self.review_decision.delete("1.0", "end")
        self.review_plan = None
        self.review_status_var.set(_REVIEW_NO_RUN_TEXT)
        self._show_local_loading()
        self._show_github_loading()
        self.banner_var.set(LOADING_TEXT)
        self._apply_lifecycle_state()

    def _show_local_loading(self) -> None:
        for var in (self.branch_var, self.head_var, self.origin_var, self.clean_var,
                    self.sync_var, self.run_var, self.build_var, self.release_var):
            var.set(LOADING_TEXT)

    def _show_github_loading(self) -> None:
        self.github_head_var.set("取得中...")
        self.ci_var.set("取得中...")
        self.pr_var.set("取得中...")
        self.candidate_source_var.set("-")

    def on_request_suggestion(self, name: str) -> None:
        if not self.ai_test_var.get().strip():
            self.selection.submit_suggest(name)

    def on_suggestion(self, name: str, value: str) -> None:
        if value and self.ai_test_var.get() == self._suggest_seed:
            self.ai_test_var.set(value)

    def on_local(self, name: str, snapshot) -> None:
        state, entries = snapshot.repo_state, snapshot.entrypoints
        repo_root = REPOS_ROOT / name
        self.branch_var.set(state.branch or "-")
        self.head_var.set(short_sha(state.head))
        self.origin_var.set(f"{short_sha(state.origin_head)}   ({state.origin_repo or 'origin不明'})")
        self.clean_var.set(f"STOP: {state.error}" if state.error else f"{'DIRTY' if state.tracked_dirty else 'CLEAN'}   untracked={state.untracked_count}")
        self.sync_var.set(choice_text(entries.sync, repo_root))
        self.run_var.set(choice_text(entries.run, repo_root))
        self.build_var.set(choice_text(entries.build, repo_root))
        self.release_var.set(choice_text(entries.release, repo_root))
        self.release_button_var.set(entries.release_label)
        self._refresh_review_plan(state)

    def on_local_unavailable(self, name: str, text: str) -> None:
        for var in (self.branch_var, self.head_var, self.origin_var,
                    self.sync_var, self.run_var, self.build_var, self.release_var):
            var.set("-")
        self.clean_var.set(f"STOP: {text}")
        self.banner_var.set(text)

    def on_github(self, name: str, state: GitHubState) -> None:
        if state.error:
            self.github_head_var.set("-")
            self.ci_var.set(f"ERROR: {state.error}")
            self.pr_var.set("-")
            return
        self.github_head_var.set(short_sha(state.branch_sha))
        self.ci_var.set(f"{state.ci_target or '-'}: {state.ci_state}   checks={state.check_count}")
        if state.latest_pr:
            prefix = "DRAFT" if state.latest_pr.is_draft else "OPEN"
            self.pr_var.set(f"#{state.latest_pr.number} {prefix} [{state.latest_pr.head_branch}] {state.latest_pr.title}")
        else:
            self.pr_var.set("なし")

    def on_candidate_text(self, text: str) -> None:
        self._set_candidate_text(text)

    def on_lifecycle(self) -> None:
        self._apply_lifecycle_state()

    def on_log(self, text: str) -> None:
        self._log(text)

    def on_post_notice(self, text: str) -> None:
        self.banner_var.set(text)

    def _set_candidate_text(self, text: str) -> None:
        self._applying_lifecycle = True
        try:
            self.candidate_var.set(text)
        finally:
            self._applying_lifecycle = False

    def refresh_all(self) -> None:
        """Manual reload: one new epoch for the whole local+GitHub batch."""
        if not self.current:
            return
        self._reload_batch("manual")

    def _reload_batch(self, reason: str) -> None:
        name = self.current.name
        self.selection.new_epoch(name, reason)
        self._set_candidate_text(self.selection.provenance.text(name))
        self.refresh()
        self.refresh_github()

    def refresh(self) -> None:
        """Submit a LOCAL load under the current epoch (never runs git on the UI thread)."""
        if not self.current:
            return
        self.selection.reload_local(self.current.name)
        self._show_local_loading()
        self._apply_lifecycle_state()

    def refresh_github(self) -> None:
        if not self.current:
            return
        self._show_github_loading()
        self.selection.submit_github(self.current.name)
        self._apply_lifecycle_state()

    def _candidate_changed(self) -> None:
        if self._applying_lifecycle or not self.current:
            return
        self.selection.provenance.user_edit(self.current.name, self.candidate_var.get())
        self._apply_lifecycle_state()

    def _self_update_enabled(self) -> bool:
        return bool(
            self.self_update_sha
            and self.active_process is None
            and not ACTIVE_OPERATIONS
            and self.self_update_var.get() != "確認中"
        )

    def _apply_lifecycle_state(self) -> None:
        busy = App._repo_busy(self)
        has_current = self.current is not None
        repo_state = self.repo_state
        entrypoints = self.entrypoints
        ai_ready = bool(
            has_current
            and not busy
            and repo_state
            and self.current
            and repo_state.safe_for_lifecycle(self.current)
            and repo_state.head
            and repo_state.head.lower() == repo_state.origin_head.lower()
        )
        self.ai_start_button.configure(state="normal" if ai_ready else "disabled")
        ai_running = bool(self.active_process is not None and self.active_process[2] == "ai_orchestrator")
        ai_run_dir_captured = bool(ai_running and self.ai_context and self.ai_context.get("run_dir"))
        self.ai_stop_button.configure(
            state="normal" if (ai_run_dir_captured and not self.ai_stop_requested) else "disabled"
        )
        review_plan = self.review_plan
        self.review_resume_button.configure(
            state="normal" if (ai_ready and review_plan is not None and review_plan.ok) else "disabled"
        )
        update_state = "normal" if self._self_update_enabled() else "disabled"

        if not self.current or not repo_state or not entrypoints:
            for button in (self.sync_button, self.run_button, self.build_button, self.release_button):
                button.configure(state="disabled")
            self.candidate_source_var.set("-")
            self.self_update_button.configure(state=update_state)
            return

        name = self.current.name
        github_state = self._github_state()
        decision = decide_lifecycle(
            self.current,
            repo_state,
            entrypoints,
            github_state,
            self.candidate_var.get(),
            busy=busy,
        )

        # Write-back is split: case normalisation vs. auto reflection (single writer).
        current_value = self.candidate_var.get().strip()
        if decision.candidate_sha:
            if current_value and decision.candidate_sha != current_value:
                if self.selection.provenance.normalize(name, decision.candidate_sha):
                    self._set_candidate_text(self.selection.provenance.text(name))
            elif not current_value:
                if self.selection.provenance.auto_reflect(name, decision.candidate_sha, github_state):
                    self._set_candidate_text(self.selection.provenance.text(name))

        self.candidate_source_var.set(decision.candidate_source)
        if not decision.candidate_sha and github_state is None and self.selection.github_loading and not busy:
            self.banner_var.set("GitHub状態取得中")
        else:
            self.banner_var.set(decision.banner)

        self.sync_button.configure(state="normal" if decision.sync_enabled else "disabled")
        self.run_button.configure(state="normal" if decision.run_enabled else "disabled")
        self.build_button.configure(state="normal" if decision.build_enabled else "disabled")
        self.release_button.configure(state="normal" if decision.release_enabled else "disabled")
        self.self_update_button.configure(state=update_state)

    def _candidate_matches_local(self) -> bool:
        if not self.repo_state:
            return False
        candidate = self.candidate_var.get().strip().lower()
        return candidate_sha_is_valid(candidate) and self.repo_state.head.lower() == candidate

    def open_github(self) -> None:
        if self.current:
            webbrowser.open_new_tab(self.current.github_url)

    def open_pr_or_ci(self) -> None:
        if not self.current:
            return
        state = self._github_state()
        if state and state.latest_pr and state.latest_pr.url:
            webbrowser.open_new_tab(state.latest_pr.url)
            return
        if state and candidate_sha_is_valid(state.ci_sha):
            webbrowser.open_new_tab(f"{self.current.github_url}/commit/{state.ci_sha}/checks")
            return
        webbrowser.open_new_tab(self.current.github_url)

    def scan_remote_repos(self) -> None:
        self.remote_status_var.set("GitHub確認中...")
        self.selection.submit_global(
            GLOBAL_REMOTE_REPOS, lambda cancel: list_github_repositories(cancel=cancel)
        )

    def _apply_remote_repos(self, remote) -> None:
        selected = self._selected_unmanaged()
        managed = {item.name for item in self.all_definitions}
        self.unmanaged_repos = unmanaged_github_repositories(managed, remote)
        self.new_repo_list.delete(0, "end")
        for repo in self.unmanaged_repos:
            branch = repo.default_branch or "no branch"
            self.new_repo_list.insert("end", f"NEW  {repo.name}   [{branch}]")
        if selected is not None:
            for index, repo in enumerate(self.unmanaged_repos):
                if repo.full_name == selected.full_name:
                    self.new_repo_list.selection_set(index)
                    break
        self.remote_status_var.set("未登録repoなし" if not self.unmanaged_repos else f"未登録 {len(self.unmanaged_repos)} repo")

    def _selected_unmanaged(self) -> RemoteRepo | None:
        selection = self.new_repo_list.curselection()
        if selection and selection[0] < len(self.unmanaged_repos):
            return self.unmanaged_repos[selection[0]]
        return None

    def _confirm_with_guard(self, kind: str, capture, ask) -> tuple[bool, bool]:
        """Run a confirmation dialog with result application held. (approved, unchanged)"""
        guard = self.selection.guard
        guard.begin(IntentSnapshot(kind, capture()))
        approved = False
        try:
            approved = bool(ask())
        finally:
            unchanged = guard.finish(capture)
        return approved, unchanged

    def setup_new_repo(self) -> None:
        remote = self._selected_unmanaged()
        if remote is None:
            messagebox.showinfo("新規repo", "セットアップするrepoを選択してください。")
            return
        dest = REPOS_ROOT / remote.name
        if not (dest / ".git").exists():
            if dest.exists():
                messagebox.showerror("セットアップ停止", f"{dest} が存在しますがGit repoではありません。自動変更しません。")
                return
            approved, unchanged = self._confirm_with_guard(
                "setup_new_repo",
                lambda: {"remote": remote, "dest_exists": dest.exists()},
                lambda: messagebox.askyesno(
                    "新規repoセットアップ",
                    f"{remote.full_name} を正式パスへcloneします。\n\n{dest}\n\n既存ファイルの上書き・branch変更・buildは行いません。",
                ),
            )
            if not approved:
                return
            if not unchanged:
                messagebox.showinfo("新規repo", STATE_CHANGED_TEXT)
                return
            try:
                clone_new_repository(remote, REPOS_ROOT)
            except RuntimeError as exc:
                messagebox.showerror("セットアップ停止", str(exc))
                return
        self._start_new_repo_registration(remote, dest)

    def _start_new_repo_registration(self, remote: RemoteRepo, local_path: Path) -> None:
        """Select development-management and put the registration task in its AI request field."""
        prompt = build_new_repo_setup_prompt(remote, local_path)
        window = tk.Toplevel(self.master)
        window.title("新規repo登録 — Claude / Codexへの指示")
        window.geometry("760x480")
        text = tk.Text(window, wrap="word")
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.insert("1.0", prompt)
        text.configure(state="disabled")
        ttk.Button(window, text="指示をコピー", command=lambda: self._copy_to_clipboard(prompt)).pack(pady=8)
        self._log(f"{remote.name}: 登録指示を生成しました。Claude / Codexで直接実装できます。")

    def check_self_update(self) -> None:
        self.self_update_sha = ""
        self.self_update_var.set("確認中")
        self._set_button_states()

        def work(cancel):
            definition = RepoDefinition(DEV_MANAGEMENT, "management", "main")
            local_state = inspect_repo(DM_ROOT, definition, cancel=cancel)
            if not local_state.safe_for_lifecycle(definition):
                return local_state, None
            return local_state, fetch_github_state(definition, cancel=cancel)

        self.selection.submit_global(GLOBAL_SELF_UPDATE, work)

    def _apply_self_update_result(self, local_state, github_state) -> None:
        definition = RepoDefinition(DEV_MANAGEMENT, "management", "main")
        self.self_update_sha = ""
        if github_state is None:
            detail = local_state.error or "main / 正式origin / tracked cleanを確認してください"
            self.self_update_var.set(f"更新停止: {detail}")
            self._set_button_states()
            return
        self.self_update_ci_state = github_state.ci_state
        if github_state.error:
            self.self_update_var.set(f"確認失敗: {github_state.error}")
        elif github_state.branch_sha == local_state.head:
            self.self_update_var.set(f"最新版 {short_sha(local_state.head)} / CI {github_state.ci_state}")
        elif github_state.ci_state == "FAILED":
            self.self_update_var.set(f"候補 {short_sha(github_state.branch_sha)} / CI FAILED（自動更新停止）")
        else:
            self.self_update_sha = github_state.branch_sha
            self.self_update_var.set(f"更新あり → {short_sha(self.self_update_sha)} / CI {github_state.ci_state}")
        self._set_button_states()

    def on_global_result(self, kind: str, message) -> None:
        if kind == GLOBAL_REMOTE_REPOS:
            if message.error is not None:
                self.remote_status_var.set(f"取得失敗: {message.error}")
            else:
                self._apply_remote_repos(message.payload)
        elif kind == GLOBAL_SELF_UPDATE:
            if message.error is not None:
                self.self_update_sha = ""
                self.self_update_var.set(f"確認失敗: {message.error}")
                self._set_button_states()
            else:
                self._apply_self_update_result(*message.payload)

    def on_global_notice(self, kind: str, notice) -> None:
        if kind == GLOBAL_REMOTE_REPOS:
            self.remote_status_var.set("GitHub確認: タイムアウト")
        elif kind == GLOBAL_SELF_UPDATE:
            self.self_update_sha = ""
            self.self_update_var.set("確認失敗: タイムアウト")
            self._set_button_states()

    def apply_self_update(self) -> None:
        if not self.self_update_sha or not self._self_update_enabled():
            return
        sha = self.self_update_sha
        ci_state = self.self_update_ci_state
        approved, unchanged = self._confirm_with_guard(
            "self_update",
            lambda: {"sha": self.self_update_sha, "epoch": self.selection.self_update_epoch},
            lambda: messagebox.askyesno(
                "Control Center更新",
                f"development-managementを {sha} へSYNCします。\nCI: {ci_state}\n\n成功後はControl Centerを自動再起動します。",
            ),
        )
        if not approved:
            return
        if not unchanged:
            messagebox.showinfo("Control Center更新", STATE_CHANGED_TEXT)
            return
        sync_path = DM_ROOT / "SYNC_CLICK_ME.cmd"
        command = ["cmd.exe", "/c", "call", str(sync_path), sha, "--no-pause"]
        try:
            completed = subprocess.run(command, cwd=DM_ROOT, check=False, **processes.hidden_options())
        except OSError as exc:
            messagebox.showerror("更新起動失敗", str(exc))
            return
        if completed.returncode != 0:
            messagebox.showerror("更新停止", f"SYNCが rc={completed.returncode} で停止しました。SYNC_RESULT.txtを確認してください。")
            return
        self.selection.self_update_epoch += 1
        self._log(f"Control Center: self update完了 → {short_sha(sha)}")
        try:
            subprocess.Popen([sys.executable, str(LAUNCHER_PATH)], cwd=DM_ROOT, **processes.hidden_options())
        except OSError as exc:
            messagebox.showwarning("更新完了", f"更新は完了しましたが自動再起動に失敗しました。\n{exc}\n\nDEV_CONTROL_CENTER.pyw を開き直してください。")
            return
        self._on_close()

    def launch_ai_orchestrator(self) -> None:
        if not self.current or not self.repo_state or App._repo_busy(self):
            return
        if not self.repo_state.safe_for_lifecycle(self.current):
            messagebox.showerror(
                "AI開発停止",
                "正式repo / branch / origin / tracked clean の安全条件を満たしていません。",
            )
            return
        if self.repo_state.head.lower() != self.repo_state.origin_head.lower():
            messagebox.showerror(
                "AI開発停止",
                "AI開発開始前は local HEAD == origin HEAD が必要です。"
                "未pushのlocal candidateがある場合は先に実機確認を完了してください。",
            )
            return

        task = self.ai_task.get("1.0", "end").strip()
        test_command = self.ai_test_var.get().strip()
        if not task:
            messagebox.showinfo("AI開発", "AI依頼を入力してください。")
            return
        if not test_command:
            messagebox.showerror(
                "AI開発停止",
                "独立テストコマンドが未設定です。テスト欄へコマンドを入力してください。",
            )
            return

        repo_root = REPOS_ROOT / self.current.name
        result_path = (
            Path(tempfile.gettempdir())
            / f"dcc-ai-result-{self.current.name}-{id(self)}.json"
        )
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass

        command = [
            sys.executable,
            str(DM_ROOT / "tools" / "ai_orchestrator" / "orchestrator.py"),
            "run",
            "--repo",
            str(repo_root),
            "--expected-branch",
            self.current.branch,
            "--task",
            task,
            "--test",
            test_command,
            "--result-file",
            str(result_path),
            "--max-rounds",
            "30",
            "--test-timeout",
            "600",
        ]
        try:
            process = _spawn_ai_process(command)
        except OSError as exc:
            messagebox.showerror("AI開発起動失敗", str(exc))
            return

        while True:
            try:
                self.ai_output_queue.get_nowait()
            except queue.Empty:
                break

        self.ai_context = {
            "repo_name": self.current.name,
            "result_path": result_path,
            "base_sha": self.repo_state.head.lower(),
        }
        self.ai_stop_requested = False
        self._begin_process(process, self.current.name, "ai_orchestrator")
        self.ai_status_var.set("実行中 — 失敗時のみRecovery（最大30回）")
        self._log(f"{self.current.name}: AI Orchestrator開始（Recovery上限30回）")
        self.banner_var.set("AI開発実行中。このrepoの競合操作を制限しています。")
        self._set_button_states()

        reader = threading.Thread(
            target=self._read_ai_output,
            args=(process,),
            daemon=True,
        )
        reader.start()
        self.master.after(250, self._poll)

    def _refresh_review_plan(self, state=None) -> None:
        """Re-inspect the entered run_dir (file reads; never called from _apply_lifecycle_state)."""
        state = state or self.repo_state
        if not self.current or state is None:
            plan = ReviewResumePlan(False, _REVIEW_NO_RUN_TEXT)
        else:
            plan = inspect_review_pending_run(
                self.review_run_dir_var.get(),
                REPOS_ROOT / self.current.name,
                self.current.branch,
                state.head,
            )
        self.review_plan = plan
        self.review_status_var.set(plan.message)
        self._apply_lifecycle_state()

    def browse_review_run_dir(self) -> None:
        chosen = filedialog.askdirectory(title="FINAL REVIEW待ちのrun_dirを選択")
        if chosen:
            self.review_run_dir_var.set(chosen)
            self._refresh_review_plan()

    def load_review_decision_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="final-review-decision.jsonを選択",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not chosen:
            return
        try:
            text = Path(chosen).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            messagebox.showerror("レビュー結果の読込失敗", str(exc))
            return
        self.review_decision.delete("1.0", "end")
        self.review_decision.insert("1.0", text)

    def resume_ai_review(self) -> None:
        """Hand a Final Review decision to `orchestrator.py run --resume-review`.

        Reuses the normal AI run path (`ai_orchestrator` action, result file,
        progress drain, candidate confirmation); it only builds a different command.
        """
        if not self.current or not self.repo_state or App._repo_busy(self):
            return
        if not self.repo_state.safe_for_lifecycle(self.current):
            messagebox.showerror(
                "レビュー再開停止",
                "正式repo / branch / origin / tracked clean の安全条件を満たしていません。",
            )
            return
        if self.repo_state.head.lower() != self.repo_state.origin_head.lower():
            messagebox.showerror(
                "レビュー再開停止",
                "再開前は local HEAD == origin HEAD が必要です。",
            )
            return
        self._refresh_review_plan()
        plan = self.review_plan
        if plan is None or not plan.ok:
            messagebox.showerror(
                "レビュー再開停止",
                plan.message if plan else _REVIEW_NO_RUN_TEXT,
            )
            return
        decision, error = parse_review_decision(
            self.review_decision.get("1.0", "end"), plan.request_id
        )
        if decision is None:
            messagebox.showerror("レビュー結果が不正です", error)
            return

        repo_name = self.current.name
        result_path = Path(tempfile.gettempdir()) / f"dcc-ai-result-{repo_name}-{id(self)}.json"
        decision_path = Path(tempfile.gettempdir()) / f"dcc-ai-review-decision-{repo_name}-{id(self)}.json"
        try:
            result_path.unlink(missing_ok=True)
            decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("レビュー再開失敗", str(exc))
            return

        command = build_review_resume_command(
            plan,
            REPOS_ROOT / repo_name,
            self.current.branch,
            result_path,
            decision_path,
        )
        try:
            process = _spawn_ai_process(command)
        except OSError as exc:
            _unlink_quietly(decision_path)
            messagebox.showerror("レビュー再開起動失敗", str(exc))
            return

        while True:
            try:
                self.ai_output_queue.get_nowait()
            except queue.Empty:
                break

        self.ai_context = {
            "repo_name": repo_name,
            "result_path": result_path,
            "base_sha": self.repo_state.head.lower(),
            "decision_path": decision_path,
        }
        self.ai_stop_requested = False
        self._begin_process(process, repo_name, "ai_orchestrator")
        self.ai_status_var.set(f"レビュー結果（{decision['verdict']}）を返して再開中")
        self._log(f"{repo_name}: Final Review {decision['verdict']} を返してOrchestratorを再開 ({plan.run_dir})")
        self.banner_var.set("AI開発実行中。このrepoの競合操作を制限しています。")
        self._set_button_states()

        reader = threading.Thread(
            target=self._read_ai_output,
            args=(process,),
            daemon=True,
        )
        reader.start()
        self.master.after(250, self._poll)

    def stop_ai_orchestrator(self) -> None:
        """User-initiated AI safety stop.

        Enabled only while an AI Orchestrator process is active. This is a
        distinct action from closing the window: it never destroys the
        window and window close never calls this. It only tears down the
        Orchestrator process and its Claude/Codex child processes; it does
        not touch source main, does not apply a candidate, and does not
        push / BUILD / UPDATE / DEPLOY. The isolated worktree and run
        logs are left on disk for a possible future resume.
        """
        if self.active_process is None or self.active_process[2] != "ai_orchestrator":
            return
        process, repo_name, _action = self.active_process
        if not messagebox.askyesno(
            "AI安全停止",
            "実行中のAI Orchestrator（Claude / Codex等の子プロセスを含む）を安全停止しますか？\n\n"
            "source mainは変更されず、candidateの自動適用・PUSH・BUILD・UPDATE・DEPLOYは行いません。\n"
            "isolated worktreeとrun logは保持されます。",
        ):
            return
        self.ai_stop_requested = True
        self.ai_stop_button.configure(state="disabled")
        _terminate_ai_process_tree(process)
        self.ai_status_var.set("安全停止を要求しました...")
        self._log(f"{repo_name}: AI安全停止を要求（ユーザーによる安全停止）。worktree / run logは保持します。")
        self.banner_var.set("AI安全停止を実行中。完了までお待ちください。")

    def _read_ai_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            text = line.rstrip()
            if text:
                self.ai_output_queue.put(text)

    def _drain_ai_output(self) -> None:
        while True:
            try:
                line = self.ai_output_queue.get_nowait()
            except queue.Empty:
                return
            if self.ai_context is not None and line.startswith(_AI_RUN_DIR_MARKER):
                self.ai_context["run_dir"] = Path(line[len(_AI_RUN_DIR_MARKER):].strip())
                self._apply_lifecycle_state()
            self._log(f"AI: {line}")
            self.ai_status_var.set(line)

    def _reload_after(self, repo_name: str) -> None:
        """Forced LOCAL+GITHUB reload for the repo, or defer it until it is selected."""
        if self.current and self.current.name == repo_name:
            self._reload_batch("post-action")
        else:
            self.selection.needs_reload.add(repo_name)

    def _ai_apply_fields(self, repo_name: str) -> dict[str, object]:
        return {
            "repo": self.current.name if self.current else None,
            "epoch": self.selection.lifecycle_epoch.get(repo_name),
            "idle": not App._repo_busy(self),
            "candidate": self.selection.provenance.text(repo_name),
            "closed": self.selection.closed,
        }

    def _finish_ai_orchestrator(self, repo_name: str, rc: int) -> None:
        context = self.ai_context or {}
        self.ai_context = None
        _unlink_quietly(context.get("decision_path"))
        if self.ai_stop_requested:
            self.ai_stop_requested = False
            reason = AI_SAFETY_STOP_REASON
            run_dir = context.get("run_dir")
            if isinstance(run_dir, Path):
                _mark_ai_run_stopped(run_dir)
                self._log(f"{repo_name}: run状態を保持したままstatus.json / result.jsonへ{reason}を記録しました。")
            else:
                self._log(f"{repo_name}: run_dirが未取得のためstatus.json / result.jsonへの記録は行いません。")
            self.ai_status_var.set(f"STOPPED: {reason}")
            self._log(f"{repo_name}: AI Orchestrator STOPPED — {reason}。isolated worktree / run logは保持します。")
            self.banner_var.set(f"AI Orchestratorは{reason}で停止しました。isolated worktree / run logは保持されています。")
            self._reload_after(repo_name)
            return

        result_path = context.get("result_path")
        payload: dict[str, object] = {}
        if isinstance(result_path, Path) and result_path.is_file():
            try:
                raw = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    payload = raw
            except (OSError, json.JSONDecodeError) as exc:
                self._log(f"{repo_name}: AI result JSON読込失敗: {exc}")
            finally:
                try:
                    result_path.unlink(missing_ok=True)
                except OSError:
                    pass

        status = str(payload.get("status", ""))
        if rc == 0 and status == "review_pending":
            self.ai_status_var.set("FINAL REVIEW待ち — candidate未作成")
            self._log(f"{repo_name}: Final Review request: {payload.get('run_dir', '')}")
            if self.current and self.current.name == repo_name and payload.get("run_dir"):
                self.review_run_dir_var.set(str(payload["run_dir"]))
                self.review_decision.delete("1.0", "end")
            self._reload_after(repo_name)
            return
        candidate = str(payload.get("candidate_sha", "")).strip().lower()
        if rc != 0 or status != "candidate_ready" or not candidate_sha_is_valid(candidate):
            error = str(payload.get("error", "")).strip() or f"rc={rc}"
            self.ai_status_var.set(f"STOP: {error}")
            self._log(f"{repo_name}: AI Orchestrator停止 — {error}")
            # Provider failures remain in the Orchestrator status/log. A modal
            # error from a hidden child must not block ordinary development.
            self._reload_after(repo_name)
            return

        self.selection.provenance.ai_result(repo_name, candidate)
        claude_calls = payload.get("claude_calls", "?")
        codex_calls = payload.get("codex_calls", "?")
        rounds = payload.get("rounds_used", "?")
        self.ai_status_var.set(
            f"CANDIDATE READY {short_sha(candidate)} / "
            f"Recovery={rounds} Claude={claude_calls} Codex={codex_calls}"
        )
        self._log(
            f"{repo_name}: AI candidate {candidate} "
            f"(Recovery={rounds}, Claude={claude_calls}, Codex={codex_calls})"
        )

        if not self.current or self.current.name != repo_name:
            self.selection.needs_reload.add(repo_name)
            return

        self._set_candidate_text(self.selection.provenance.text(repo_name))
        base_sha = str(payload.get("base_sha", "") or context.get("base_sha", "")).lower()
        approved, unchanged = self._confirm_with_guard(
            "ai_apply",
            lambda: self._ai_apply_fields(repo_name),
            lambda: messagebox.askyesno(
                "AI candidate ready",
                f"candidate {candidate}\n\n"
                "このcandidateをローカルexpected branchへfast-forwardして、"
                "RUN_DEVで実機確認できる状態にしますか？\n\n"
                "push / BUILD / UPDATEは行いません。",
            ),
        )
        if not unchanged:
            text = "AI candidate適用は中止されました（状態が変わりました）"
            self.selection.post_action_notice[repo_name] = text
            self.banner_var.set(text)
            self._reload_after(repo_name)
            return
        if not approved:
            text = f"AI candidate {short_sha(candidate)} は作成済み。ローカル適用は未実施です。"
            self.selection.post_action_notice[repo_name] = text
            self.banner_var.set(text)
            self._reload_after(repo_name)
            return

        # Bump the epoch and invalidate BEFORE the apply; the AI-origin candidate is kept.
        self.selection.new_epoch(repo_name, "ai-apply")
        try:
            apply_local_candidate(
                REPOS_ROOT / repo_name,
                self.current,
                base_sha=base_sha,
                candidate_sha=candidate,
            )
        except RuntimeError as exc:
            self.banner_var.set(f"AI candidate適用停止: {exc}")
            self._log(f"{repo_name}: local candidate適用停止 — {exc}")
            messagebox.showerror("candidate適用停止", str(exc))
            self._reload_after(repo_name)
            return

        self._log(f"{repo_name}: local expected branchをAI candidateへfast-forward {short_sha(candidate)}")
        done = f"AI candidate {short_sha(candidate)} をローカル適用済み。RUN_DEVで実機確認してください。"
        self.selection.post_action_notice[repo_name] = done
        self._reload_after(repo_name)
        self.banner_var.set(done)
        messagebox.showinfo(
            "AI candidate ready",
            f"ローカルcandidateを適用しました。\n\n{candidate}\n\n"
            "次はRUN_DEVで実機確認してください。push / BUILD / UPDATEは未実施です。",
        )

    def _launch_fields(self, action: str) -> dict[str, object]:
        choice = getattr(self.entrypoints, action, None) if self.entrypoints else None
        return {
            "repo": self.current.name if self.current else None,
            "candidate": self.candidate_var.get().strip(),
            "entrypoint": str(choice.path) if choice and choice.path else None,
            "head": self.repo_state.head if self.repo_state else None,
            "state_generation": self.selection.state_generation,
            "epoch": self.selection.lifecycle_epoch.get(self.current.name) if self.current else None,
            "idle": not App._repo_busy(self),
        }

    def launch(self, action: str) -> None:
        if not self.current or App._repo_busy(self):
            return
        definition = self.current
        repo_root = REPOS_ROOT / definition.name

        def inspect():
            from .core import discover_entrypoints
            state = inspect_repo(repo_root, definition)
            entries = discover_entrypoints(repo_root, definition.repo_type, application_implemented=definition.application_implemented)
            if not state.safe_for_development(definition):
                raise ValueError("正式repo / originを確認できません")
            choice = getattr(entries, action)
            if not choice.ready or not choice.path:
                raise ValueError(f"{action.upper()}の正式入口を一意に特定できません")
            if action in {"run", "build"} and not machine_entries.supported(repo_root, action):
                raise ValueError("非対話entrypoint未登録です。dcc_entrypoints.jsonで本体を指定してください")
            return state, choice

        def ready(result):
            state, choice = result
            if self.current != definition or App._repo_busy(self):
                self._log(f"{definition.name}: 開始中止（選択または実行状態が変化）")
                return
            if action == "sync":
                self._log("SYNCは手動の正式入口を使用してください。DCC通常操作はRUN / BUILD / UPDATEです。")
                return
            if action == "run":
                command = [processes.console_python(), "-u", "-B", "-m", "scripts.dev_control_center.entrypoints", "run", "--repo", str(repo_root)]
                self._start_lifecycle(command, definition.name, action)
                return
            if action == "build":
                profile = provenance.PROFILES.get(definition.name)
                if profile:
                    artifact = (repo_root / profile[0]).resolve()
                else:
                    folder = filedialog.askdirectory(title="BUILD成果物の出力フォルダを指定", parent=self.master)
                    if not folder:
                        return
                    artifact = Path(folder).resolve()
                if artifact == repo_root.resolve() or repo_root.resolve().is_relative_to(artifact):
                    raise ValueError("repo全体やその親を成果物には指定できません")
                if self.current != definition or App._repo_busy(self):
                    return
                command = [processes.console_python(), "-u", "-B", "-m", "scripts.dev_control_center.provenance", "build",
                           "--repo", str(repo_root), "--entry", str(choice.path), "--artifact", str(artifact)]
                self._start_lifecycle(command, definition.name, action)
                return
            folder = filedialog.askdirectory(title="配布先フォルダを選択（HDD更新はドライブ直下）", parent=self.master)
            if folder:
                self._prepare_release(repo_root, definition, Path(folder))

        self._prepare_operation(definition.name, action, inspect, ready)

    def _prepare_operation(self, repo_name: str, action: str, work, ready) -> None:
        token = object()
        ACTIVE_OPERATIONS[id(token)] = (repo_name, action + "-check")
        self.banner_var.set(f"{repo_name}: {action.upper()}開始条件を確認中...")

        def inspect():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, str(exc)
            self.lifecycle_events.put(("prepared", token, repo_name, action, result, error, ready))

        threading.Thread(target=inspect, daemon=True).start()
        self._set_button_states()

    def _start_lifecycle(self, command: list[str], repo_name: str, action: str) -> None:
        if any(name == repo_name for name, _ in ACTIVE_OPERATIONS.values()):
            self._log(f"{repo_name}: 競合する操作があるため開始しません")
            return
        token = object()
        self.lifecycle_jobs[repo_name] = token
        cancel = threading.Event()
        self.lifecycle_cancellations[repo_name] = cancel
        ACTIVE_OPERATIONS[id(token)] = (repo_name, action)
        self.selection.process_boundary(repo_name, f"process-start:{action}")
        self._log(f"{repo_name}: {action.upper()}開始（非対話・バックグラウンド）")

        def execute():
            try:
                rc = processes.stream(command, cwd=DM_ROOT,
                    emit=lambda text: self.lifecycle_events.put(("output", repo_name, action, text)), cancel=cancel)
            except Exception as exc:
                self.lifecycle_events.put(("output", repo_name, action, f"起動失敗: {exc}\n"))
                rc = 1
            self.lifecycle_events.put(("finished", token, repo_name, action, rc))

        threading.Thread(target=execute, daemon=True).start()
        self._set_button_states()

    def stop_lifecycle(self) -> None:
        if not self.current:
            return
        name = self.current.name
        cancel = self.lifecycle_cancellations.get(name)
        if cancel is not None and messagebox.askyesno("実行停止", f"{name}の実行と子processを停止しますか？\nBUILD中の成果物はUPDATE可能と扱いません。", parent=self.master):
            cancel.set()
            self._log(f"{name}: 明示的な停止を要求しました")

    def _drain_lifecycle_events(self) -> None:
        # Bounded work per tick keeps movement/selection responsive under log floods.
        deadline = time.monotonic() + 0.008
        for _ in range(100):
            if time.monotonic() >= deadline:
                break
            try:
                event = self.lifecycle_events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "output":
                _, repo, action, text = event
                self._log_process(repo, action, text)
            elif event[0] == "prepared":
                _, token, repo, action, result, error, ready = event
                ACTIVE_OPERATIONS.pop(id(token), None)
                if error:
                    self.banner_var.set(f"{repo}: {action.upper()}停止 — {error}")
                    self._log(self.banner_var.get())
                else:
                    try:
                        ready(result)
                    except Exception as exc:
                        self.banner_var.set(f"{repo}: {action.upper()}停止 — {exc}")
                        self._log(self.banner_var.get())
            else:
                _, token, repo, action, rc = event
                ACTIVE_OPERATIONS.pop(id(token), None)
                self.lifecycle_jobs.pop(repo, None)
                cancellation = self.lifecycle_cancellations.pop(repo, None)
                self.selection.process_boundary(repo, f"process-end:{action}")
                outcome = "停止" if cancellation and cancellation.is_set() else ("成功" if rc == 0 else "失敗")
                text = f"{repo}: {action.upper()} {outcome} rc={rc}"
                self._log(text)
                self.selection.post_action_notice[repo] = text
                self.banner_var.set(text)
                self._reload_after(repo)
        self._set_button_states()

    def _prepare_release(self, repo_root: Path, definition: RepoDefinition, target: Path) -> None:
        if self.current != definition or App._repo_busy(self):
            return

        def ready(snapshot):
            if self.current != definition or App._repo_busy(self):
                return
            record = snapshot["receipt"]
            details = (f"repo: {repo_root}\nBUILD: {record['build_id']}\nbase HEAD: {record['base_head']}\n"
                       f"dirty: {record['dirty']}\n成果物: {record['artifact']}\nSHA256: {record['artifact_hash']}\n"
                       f"配布先: {snapshot.get('destination_detail', snapshot['target'])}\n\nこの成果物を実機確認済みで、UPDATEを実行しますか？")
            if not messagebox.askyesno("UPDATE確認", details, parent=self.master):
                self.banner_var.set("UPDATEをキャンセルしました")
                return
            if self.current != definition or App._repo_busy(self):
                return
            request_path = provenance.receipt_path(repo_root).with_name("update-" + record["build_id"] + ".json")
            provenance.write_json(request_path, snapshot)
            command = [processes.console_python(), "-u", "-B", "-m", "scripts.dev_control_center.provenance", "release",
                       "--repo", str(repo_root), "--request", str(request_path)]
            self._start_lifecycle(command, definition.name, "release")

        self._prepare_operation(definition.name, "release", lambda: provenance.release_snapshot(repo_root, target), ready)

    def _begin_process(self, process, repo_name: str, action: str) -> None:
        """The ONLY place that sets active_process: new epoch, invalidate, cancel old loads."""
        self.active_process = (process, repo_name, action)
        ACTIVE_OPERATIONS[id(self)] = (repo_name, action)
        if self.selection.process_boundary(repo_name, f"process-start:{action}"):
            self.self_update_sha = ""
        if self.current and self.current.name == repo_name:
            self._set_candidate_text(self.selection.provenance.text(repo_name))

    def _end_process(self, repo_name: str) -> None:
        ACTIVE_OPERATIONS.pop(id(self), None)
        self.active_process = None
        if self.selection.process_boundary(repo_name, "process-end"):
            self.self_update_sha = ""
            self.self_update_var.set("未確認（更新確認を押してください）")
        if self.current and self.current.name == repo_name:
            self._set_candidate_text(self.selection.provenance.text(repo_name))
        else:
            self.selection.needs_reload.add(repo_name)

    def _launch_cmd(self, path: Path, args: list[str], action: str) -> None:
        # Do not fall back to a manual CMD with pause/input/start behavior.
        if action != "run" or not self.current:
            raise ValueError("手動CMDの直接実行は非対応です")
        command = [processes.console_python(), "-u", "-B", "-m", "scripts.dev_control_center.entrypoints", "run",
                   "--repo", str(REPOS_ROOT / self.current.name)]
        self._start_lifecycle(command, self.current.name, action)

    def _poll(self) -> None:
        if self.active_process is None:
            return
        process, repo_name, action = self.active_process
        if action == "ai_orchestrator":
            self._drain_ai_output()
        rc = process.poll()
        if rc is None:
            self.master.after(250 if action == "ai_orchestrator" else 750, self._poll)
            return

        if action == "ai_orchestrator":
            self._drain_ai_output()
        self._end_process(repo_name)
        self._log(f"{repo_name}: {action.upper()} 終了 rc={rc}")

        if action == "ai_orchestrator":
            self.banner_var.set("AI完了処理中")
            self._finish_ai_orchestrator(repo_name, rc)
            if self.current and self.current.name == repo_name:
                self._refresh_review_plan()
            return

        if self.current and self.current.name == repo_name:
            self.refresh()
            self.refresh_github()
        else:
            self._set_button_states()

    def _set_button_states(self) -> None:
        self._apply_lifecycle_state()
        if hasattr(self, "operation_stop_button"):
            running = self.current and self.current.name in self.lifecycle_cancellations
            self.operation_stop_button.configure(state="normal" if running else "disabled")

    def _copy_to_clipboard(self, text: str) -> None:
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        self.master.update_idletasks()

    def _log_process(self, repo: str, action: str, text: str) -> None:
        key = (repo, action)
        self.log.configure(state="normal")
        if self._stream_key != key and self._stream_open:
            self.log.insert("end", "\n")
            self._stream_open = False
        self._stream_key = key
        for piece in text.splitlines(keepends=True):
            if not self._stream_open:
                self.log.insert("end", f"[{repo} {action.upper()}] ")
            self.log.insert("end", piece)
            self._stream_open = not piece.endswith("\n")
        if int(self.log.index("end-1c").split(".")[0]) > 12000:
            self.log.delete("1.0", "2000.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        if self._stream_open:
            self.log.insert("end", "\n")
        self._stream_open = False
        self._stream_key = None
        self.log.insert("end", text + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 12000:
            self.log.delete("1.0", "2000.0")
        self.log.see("end")
        self.log.configure(state="disabled")


def self_check() -> int:
    try:
        items = active_repo_definitions(TYPES_PATH, BRANCHES_PATH)
    except (OSError, ControlCenterConfigError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Development Control Center config OK: {len(items)} active repositories")
    for item in items:
        print(f"- {item.name}: {item.repo_type}, branch={item.branch}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except (OSError, ControlCenterConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
