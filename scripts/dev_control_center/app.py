"""Tkinter UI for the Development Control Center."""

from __future__ import annotations

import argparse
from pathlib import Path
import queue
import subprocess
import sys
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


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        self.orchestrator_window = None
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
        self.active_process = None
        self.pending_preflight = False
        self._stream_key = None
        self._stream_open = False
        self.lifecycle_events: queue.Queue = queue.Queue(maxsize=2048)
        self.lifecycle_jobs: dict[str, object] = {}
        self.lifecycle_cancellations: dict[str, threading.Event] = {}
        # Orchestrator drafts (Task / Tests per repo) and the running-run badge. The Orchestrator itself
        # is not an operation of this window: its runs live in their own worker processes.
        self.ai_drafts: dict[str, object] = {}
        self._badge_queue: queue.Queue = queue.Queue(maxsize=1)
        self._badge_stop = threading.Event()
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
        self.orchestrator_button_var = tk.StringVar(value="AI Orchestrator")

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
        self.master.after(500, self._start_orchestrator_badge)

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
        # Orchestrator runs are independent worker processes: closing DCC never stops or blocks on them.
        if ACTIVE_OPERATIONS:
            messagebox.showinfo("工程実行中", "工程完了後にDCCを閉じてください。")
            return
        self._closed = True
        self._badge_stop.set()
        window = self.orchestrator_window
        if window is not None and window.exists():
            window.close()
        if TIMING.enabled:
            TIMING.event("ui-lag-summary", **self._heartbeat.stats())
        self.selection.close()
        # Destroying Tk does not cancel pending Tcl after callbacks. Cancel them
        # before destroying the root.
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
        self._drain_orchestrator_badge()
        self._set_button_states()
        self.master.after(HEARTBEAT_MS, self._heartbeat_tick)

    def _build(self) -> None:
        self.master.title("Development Control Center")
        self.master.geometry("1080x720")
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

        lifecycle = ttk.LabelFrame(right, text="実機確認・配布", padding=10)
        lifecycle.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for col in range(4):
            lifecycle.columnconfigure(col, weight=1)

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

        self.orchestrator_button = ttk.Button(lifecycle, textvariable=self.orchestrator_button_var, command=self.open_orchestrator)
        self.orchestrator_button.grid(row=1, column=3, sticky="ew", padx=(3, 0), pady=(8, 0))
        self.operation_stop_button = ttk.Button(lifecycle, text="このrepoの実行を停止", command=self.stop_lifecycle)
        self.operation_stop_button.grid(row=0, column=0, columnspan=2, sticky="w")
        entries = ttk.LabelFrame(right, text="検出した正式入口", padding=10)
        # Entry paths are available in tool logs; keep the main screen compact.
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
        """Open (or focus) the Orchestrator window. It is only a client of the run files."""
        from .orchestrator_view import OrchestratorWindow

        window = self.orchestrator_window
        if window is not None and window.exists():
            if self.current:
                window.select_repo(self.current.name)
            window.focus()
            return
        self.orchestrator_window = OrchestratorWindow(
            self.master, self.definitions, initial_repo=self.current.name if self.current else None,
            drafts=self.ai_drafts, on_apply=self.apply_ai_candidate, repos_root=REPOS_ROOT)

    def _repo_busy(self) -> bool:
        if self.active_process is not None:
            return True
        return bool(self.current and any(name == self.current.name for name, _ in ACTIVE_OPERATIONS.values()))

    def _select_repo(self) -> None:
        selection = self.repo_list.curselection()
        if not selection:
            return
        # leave(outgoing) + enter(new): no subprocess or file scan on the UI thread.
        self.selection.select(self.definitions[selection[0]].name)

    # --- view interface used by SelectionState (all run on the UI thread) ----
    def on_loading(self, name: str) -> None:
        definition = self.current
        repo_root = REPOS_ROOT / name
        self.title_var.set(name)
        self.meta_var.set(f"{repo_root}   |   type={definition.repo_type}   |   expected branch={definition.branch}")
        self._set_candidate_text(self.selection.provenance.text(name))
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
        # A suggested Tests command only fills an empty Orchestrator draft; it never overrides input.
        draft = self.ai_drafts.get(name)
        if not (draft and draft.tests):
            self.selection.submit_suggest(name)

    def on_suggestion(self, name: str, value: str) -> None:
        from .orchestrator_view import Draft

        draft = self.ai_drafts.get(name)
        if value and not (draft and draft.tests):
            self.ai_drafts[name] = Draft(draft.task if draft else "", value)
            window = self.orchestrator_window
            if window is not None and window.exists():
                window.suggest_tests(name, value)

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
        update_state = "normal" if self._self_update_enabled() else "disabled"

        if not self.current or not repo_state or not entrypoints:
            for button in (self.sync_button, self.run_button, self.build_button, self.release_button):
                button.state(["disabled"])
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
        # configure(state="normal") clears ttk's active bit on every heartbeat.
        # Change only disabled, preserving pointer/pressed state managed by Tk.
        for button, enabled in (
            (self.run_button, decision.run_enabled),
            (self.build_button, decision.build_enabled),
            (self.release_button, decision.release_enabled),
        ):
            button.state(["!disabled" if enabled else "disabled"])
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

    def _repo_name_busy(self, repo_name: str) -> bool:
        if self.active_process is not None and self.current and self.current.name == repo_name:
            return True
        return any(name == repo_name for name, _ in ACTIVE_OPERATIONS.values())

    def apply_ai_candidate(self, record: dict, run_dir: Path) -> None:
        """Apply a completed Orchestrator run to the local expected branch (never push / BUILD / UPDATE).

        Normal Development may have moved the repo while the run worked: then applying is *held*
        (nothing is forced and the run stays completed), and the reason is shown."""
        from tools.ai_orchestrator import runstate as run_state

        repo_name = Path(str(record.get("repo", ""))).name
        definition = next((d for d in self.definitions if d.name == repo_name), None)
        candidate = str(record.get("candidate_sha", "")).strip().lower()
        base_sha = str(record.get("base_sha", "")).strip().lower()
        parent = getattr(self.orchestrator_window, "window", self.master)
        if definition is None or not candidate_sha_is_valid(candidate):
            messagebox.showerror("candidate適用停止", "対象repoまたはcandidate SHAを確認できません。", parent=parent)
            return
        if self._repo_name_busy(repo_name):
            messagebox.showinfo("candidate適用を保留", f"{repo_name}でRUN / BUILD / UPDATE等を実行中です。完了後に再度適用してください。", parent=parent)
            return
        approved, unchanged = self._confirm_with_guard(
            "ai_apply",
            lambda: self._ai_apply_fields(repo_name),
            lambda: messagebox.askyesno(
                "AI candidate",
                f"candidate {candidate}\n\nこのcandidateをローカルexpected branchへfast-forwardし、"
                "RUN / BUILDで実機確認できる状態にしますか？\n\npush / BUILD / UPDATEは行いません。",
                parent=parent,
            ),
        )
        if not unchanged:
            self._log(f"{repo_name}: AI candidate適用は中止されました（状態が変わりました）")
            return
        if not approved:
            return
        self.selection.new_epoch(repo_name, "ai-apply")
        try:
            apply_local_candidate(REPOS_ROOT / repo_name, definition, base_sha=base_sha, candidate_sha=candidate)
        except RuntimeError as exc:
            text = f"Orchestrator成果物の適用を保留しました: {exc}"
            self._log(f"{repo_name}: {text}")
            self.banner_var.set(text)
            messagebox.showwarning("candidate適用を保留", f"{exc}\n\nOrchestratorのrunと成果物(candidate {short_sha(candidate)})は保持されています。"
                                   "base状態を確認してから再度適用してください。", parent=parent)
            self._reload_after(repo_name)
            return
        self.selection.provenance.ai_result(repo_name, candidate)
        try:
            run_state.mark_applied(run_dir, f"local branchへfast-forward済み {short_sha(candidate)}")
        except Exception as exc:  # noqa: BLE001 - the note is informational
            self._log(f"{repo_name}: run記録の更新に失敗: {exc}")
        done = f"AI candidate {short_sha(candidate)} をローカル適用済み。RUN / BUILDで実機確認してください。"
        self._log(f"{repo_name}: {done}")
        self.selection.post_action_notice[repo_name] = done
        self._reload_after(repo_name)
        self.banner_var.set(done)

    # --- Orchestrator badge: reconnect visibility for runs that outlive DCC -------------
    def _start_orchestrator_badge(self) -> None:
        if self._closed:
            return
        # The thread gets only plain objects (never `self`): releasing a Tk object off the main thread aborts Tcl.
        stop, results = self._badge_stop, self._badge_queue

        def work() -> None:
            from tools.ai_orchestrator import runstate as run_state

            while not stop.is_set():
                try:
                    items = run_state.active_runs()
                    payload = [(i["record"]["run_id"], Path(str(i["record"]["repo"])).name, i["record"]["stage"],
                                i["liveness"]) for i in items]
                except Exception:  # noqa: BLE001 - auxiliary
                    payload = None
                try:
                    results.get_nowait()
                except queue.Empty:
                    pass
                try:
                    results.put_nowait(payload)
                except queue.Full:
                    pass
                stop.wait(10.0)

        threading.Thread(target=work, name="orchestrator-badge", daemon=True).start()

    def _drain_orchestrator_badge(self) -> None:
        try:
            payload = self._badge_queue.get_nowait()
        except queue.Empty:
            return
        if payload is None:
            return
        previous = getattr(self, "_badge_runs", None)
        self._badge_runs = payload
        text = "AI Orchestrator" if not payload else f"AI Orchestrator ● 実行中 {len(payload)}"
        if self.orchestrator_button_var.get() != text:
            self.orchestrator_button_var.set(text)
        if previous is None and payload:
            for run_id, repo, stage, liveness in payload:
                self._log(f"AI Orchestrator: 実行中のrunを検出 {repo} / {stage} / {liveness}（{run_id}）。Orchestrator画面で進捗・ログ・残量を確認できます。")

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
        rc = process.poll()
        if rc is None:
            self.master.after(750, self._poll)
            return

        self._end_process(repo_name)
        self._log(f"{repo_name}: {action.upper()} 終了 rc={rc}")

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
