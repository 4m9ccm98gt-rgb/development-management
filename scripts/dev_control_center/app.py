"""Tkinter UI for the Development Control Center."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from .core import (
    ControlCenterConfigError,
    GitHubState,
    RemoteRepo,
    RepoDefinition,
    active_repo_definitions,
    apply_local_candidate,
    build_new_repo_registration_task,
    candidate_sha_is_valid,
    choice_text,
    clone_new_repository,
    discover_entrypoints,
    decide_lifecycle,
    fetch_github_state,
    inspect_repo,
    list_github_repositories,
    load_repo_definitions,
    short_sha,
    suggest_test_command,
    unmanaged_github_repositories,
)

DM_ROOT = Path(__file__).resolve().parents[2]
REPOS_ROOT = DM_ROOT.parent
TYPES_PATH = DM_ROOT / "scripts" / "repo_types.toml"
BRANCHES_PATH = DM_ROOT / "scripts" / "dev_control_center_repos.toml"
LAUNCHER_PATH = DM_ROOT / "DEV_CONTROL_CENTER.pyw"

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


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        configure_dark_theme(master)
        super().__init__(master, padding=14)
        self.master = master
        self.all_definitions = load_repo_definitions(TYPES_PATH, BRANCHES_PATH)
        self.definitions = active_repo_definitions(TYPES_PATH, BRANCHES_PATH)
        self.current: RepoDefinition | None = None
        self.repo_state = None
        self.entrypoints = None
        self.active_process = None
        self.ai_output_queue: queue.Queue[str] = queue.Queue()
        self.ai_context: dict[str, object] | None = None
        self.ai_task_by_repo: dict[str, str] = {}
        self.ai_test_by_repo: dict[str, str] = {}
        self.unmanaged_repos: list[RemoteRepo] = []
        self.github_states: dict[str, GitHubState] = {}
        self.candidate_by_repo = {item.name: "" for item in self.definitions}
        self.auto_candidate_by_repo = {item.name: "" for item in self.definitions}
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

        self._build()
        self.candidate_var.trace_add("write", lambda *_: self._candidate_changed())
        if self.definitions:
            self.repo_list.selection_set(0)
            self._select_repo()
        self.master.after(150, self.scan_remote_repos)
        self.master.after(300, self.check_self_update)

    def _build(self) -> None:
        self.master.title("Development Control Center")
        self.master.geometry("1320x860")
        self.master.minsize(1080, 720)
        self.pack(fill="both", expand=True)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Managed Repositories", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.repo_list = tk.Listbox(left, width=36, height=17, exportselection=False)
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
        self.new_repo_list = tk.Listbox(new_box, width=34, height=6, exportselection=False)
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
        ttk.Label(right, textvariable=self.title_var, font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.meta_var).grid(row=1, column=0, sticky="w", pady=(2, 10))

        status = ttk.LabelFrame(right, text="ローカル現在状態", padding=10)
        status.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        status.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("branch", self.branch_var),
            ("HEAD", self.head_var),
            ("origin", self.origin_var),
            ("working tree", self.clean_var),
        ]):
            ttk.Label(status, text=label, width=14).grid(row=row, column=0, sticky="w")
            ttk.Label(status, textvariable=var).grid(row=row, column=1, sticky="w")

        github_box = ttk.LabelFrame(right, text="GitHub / PR / CI", padding=10)
        github_box.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        github_box.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("branch HEAD", self.github_head_var),
            ("CI", self.ci_var),
            ("open PR", self.pr_var),
        ]):
            ttk.Label(github_box, text=label, width=14).grid(row=row, column=0, sticky="w")
            ttk.Label(github_box, textvariable=var, wraplength=780).grid(row=row, column=1, sticky="w")
        ttk.Button(github_box, text="PR / CIを開く", command=self.open_pr_or_ci).grid(row=0, column=2, rowspan=3, sticky="ns", padx=(12, 0))

        ai_box = ttk.LabelFrame(
            right,
            text="AI開発 — Claude実装 → Tests → Astraレビュー → local candidate",
            padding=12,
        )
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
        ttk.Label(
            ai_box,
            textvariable=self.ai_status_var,
            wraplength=820,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(
            ai_box,
            text="成功時もpush / BUILD / UPDATEは行いません。candidateをローカル適用する前に確認します。",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        lifecycle = ttk.LabelFrame(right, text="実機確認・配布", padding=10)
        lifecycle.grid(row=5, column=0, sticky="ew", pady=(0, 10))
        for col in range(4):
            lifecycle.columnconfigure(col, weight=1)

        ttk.Label(lifecycle, text="candidate SHA").grid(row=0, column=0, sticky="w")
        ttk.Entry(lifecycle, textvariable=self.candidate_var).grid(
            row=0, column=1, columnspan=2, sticky="ew"
        )
        ttk.Label(
            lifecycle,
            textvariable=self.candidate_source_var,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))

        self.run_button = ttk.Button(
            lifecycle,
            text="RUN_DEV",
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
            text="通常ルートはAI開発 → local candidate → RUN_DEV。GitHub単独開発の入口は表示しません。",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        entries = ttk.LabelFrame(right, text="検出した正式入口", padding=10)
        entries.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        entries.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("SYNC", self.sync_var),
            ("RUN", self.run_var),
            ("BUILD", self.build_var),
            ("UPDATE/DEPLOY", self.release_var),
        ]):
            ttk.Label(entries, text=label, width=16).grid(row=row, column=0, sticky="nw")
            ttk.Label(entries, textvariable=var, wraplength=820).grid(row=row, column=1, sticky="w")

        log_box = ttk.LabelFrame(right, text="操作ログ", padding=8)
        log_box.grid(row=7, column=0, sticky="nsew")
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=8, state="disabled", wrap="word")
        configure_dark_text(self.log)
        self.log.grid(row=0, column=0, sticky="nsew")
        ttk.Label(right, textvariable=self.banner_var).grid(row=8, column=0, sticky="w", pady=(8, 0))

    def _select_repo(self) -> None:
        selection = self.repo_list.curselection()
        if not selection:
            return
        if self.current:
            self.candidate_by_repo[self.current.name] = self.candidate_var.get().strip()
            self.ai_task_by_repo[self.current.name] = self.ai_task.get("1.0", "end").strip()
            self.ai_test_by_repo[self.current.name] = self.ai_test_var.get().strip()
        self.current = self.definitions[selection[0]]
        self.candidate_var.set(self.candidate_by_repo[self.current.name])
        self.ai_task.delete("1.0", "end")
        saved_task = self.ai_task_by_repo.get(self.current.name, "")
        initial_task = saved_task or self.current.initial_ai_task
        if initial_task:
            self.ai_task.insert("1.0", initial_task)
        repo_root = REPOS_ROOT / self.current.name
        self.ai_test_var.set(
            self.ai_test_by_repo.get(self.current.name)
            or self.current.initial_test_command
            or suggest_test_command(repo_root)
        )
        self.ai_status_var.set("待機")
        self.refresh()
        self.master.after(50, self.refresh_github)

    def refresh_all(self) -> None:
        self.refresh()
        self.refresh_github()

    def refresh(self) -> None:
        if not self.current:
            return
        repo_root = REPOS_ROOT / self.current.name
        self.repo_state = inspect_repo(repo_root, self.current)
        self.entrypoints = discover_entrypoints(
            repo_root, self.current.repo_type,
            application_implemented=self.current.application_implemented,
        )
        state = self.repo_state
        entries = self.entrypoints
        self.title_var.set(self.current.name)
        self.meta_var.set(f"{repo_root}   |   type={self.current.repo_type}   |   expected branch={self.current.branch}")
        self.branch_var.set(state.branch or "-")
        self.head_var.set(short_sha(state.head))
        self.origin_var.set(f"{short_sha(state.origin_head)}   ({state.origin_repo or 'origin不明'})")
        self.clean_var.set(f"STOP: {state.error}" if state.error else f"{'DIRTY' if state.tracked_dirty else 'CLEAN'}   untracked={state.untracked_count}")
        self.sync_var.set(choice_text(entries.sync, repo_root))
        self.run_var.set(choice_text(entries.run, repo_root))
        self.build_var.set(choice_text(entries.build, repo_root))
        self.release_var.set(choice_text(entries.release, repo_root))
        self.release_button_var.set(entries.release_label)
        self._apply_lifecycle_state()

    def refresh_github(self) -> None:
        if not self.current:
            return
        self.github_head_var.set("取得中...")
        self.ci_var.set("取得中...")
        self.pr_var.set("取得中...")
        self.master.update_idletasks()
        state = fetch_github_state(self.current)
        self.github_states[self.current.name] = state
        if state.error:
            self.github_head_var.set("-")
            self.ci_var.set(f"ERROR: {state.error}")
            self.pr_var.set("-")
            self._set_button_states()
            return

        self.github_head_var.set(short_sha(state.branch_sha))
        self.ci_var.set(f"{state.ci_target or '-'}: {state.ci_state}   checks={state.check_count}")
        if state.latest_pr:
            prefix = "DRAFT" if state.latest_pr.is_draft else "OPEN"
            self.pr_var.set(f"#{state.latest_pr.number} {prefix} [{state.latest_pr.head_branch}] {state.latest_pr.title}")
        else:
            self.pr_var.set("なし")

        old_auto = self.auto_candidate_by_repo.get(self.current.name, "")
        current_value = self.candidate_var.get().strip()
        if state.candidate_ready and (not current_value or current_value == old_auto):
            self._applying_lifecycle = True
            try:
                self.candidate_var.set(state.branch_sha)
                self.candidate_by_repo[self.current.name] = state.branch_sha
                self.auto_candidate_by_repo[self.current.name] = state.branch_sha
            finally:
                self._applying_lifecycle = False
            self._log(
                f"{self.current.name}: expected branch HEADをcandidateへ自動反映 "
                f"{short_sha(state.branch_sha)} / CI={state.ci_state}"
            )
        if state.candidate_blocked_by_pr and state.latest_pr:
            self._log(
                f"{self.current.name}: open PR #{state.latest_pr.number} は表示のみ。"
                f"candidateはexpected branch HEAD {short_sha(state.branch_sha)} を使用します。"
            )
        self._apply_lifecycle_state()

    def _candidate_changed(self) -> None:
        if self._applying_lifecycle or not self.current:
            return
        self.candidate_by_repo[self.current.name] = self.candidate_var.get().strip()
        self._apply_lifecycle_state()

    def _apply_lifecycle_state(self) -> None:
        busy = self.active_process is not None
        has_current = self.current is not None
        ai_ready = bool(
            has_current
            and not busy
            and self.repo_state
            and self.current
            and self.repo_state.safe_for_lifecycle(self.current)
            and self.repo_state.head
            and self.repo_state.head.lower() == self.repo_state.origin_head.lower()
        )
        self.ai_start_button.configure(state="normal" if ai_ready else "disabled")

        if not self.current or not self.repo_state or not self.entrypoints:
            for button in (self.sync_button, self.run_button, self.build_button, self.release_button):
                button.configure(state="disabled")
            self.candidate_source_var.set("-")
            self.self_update_button.configure(state="normal" if self.self_update_sha and not busy else "disabled")
            return

        decision = decide_lifecycle(
            self.current,
            self.repo_state,
            self.entrypoints,
            self.github_states.get(self.current.name),
            self.candidate_var.get(),
            busy=busy,
        )

        current_value = self.candidate_var.get().strip()
        if decision.candidate_sha and decision.candidate_sha != current_value:
            self._applying_lifecycle = True
            try:
                self.candidate_var.set(decision.candidate_sha)
                self.candidate_by_repo[self.current.name] = decision.candidate_sha
            finally:
                self._applying_lifecycle = False

        if decision.candidate_source == "AUTO / branch HEAD":
            self.auto_candidate_by_repo[self.current.name] = decision.candidate_sha
        self.candidate_source_var.set(decision.candidate_source)
        self.banner_var.set(decision.banner)

        self.sync_button.configure(state="normal" if decision.sync_enabled else "disabled")
        self.run_button.configure(state="normal" if decision.run_enabled else "disabled")
        self.build_button.configure(state="normal" if decision.build_enabled else "disabled")
        self.release_button.configure(state="normal" if decision.release_enabled else "disabled")
        self.self_update_button.configure(state="normal" if self.self_update_sha and not busy else "disabled")

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
        state = self.github_states.get(self.current.name)
        if state and state.latest_pr and state.latest_pr.url:
            webbrowser.open_new_tab(state.latest_pr.url)
            return
        if state and candidate_sha_is_valid(state.ci_sha):
            webbrowser.open_new_tab(f"{self.current.github_url}/commit/{state.ci_sha}/checks")
            return
        webbrowser.open_new_tab(self.current.github_url)

    def scan_remote_repos(self) -> None:
        self.remote_status_var.set("GitHub確認中...")
        self.master.update_idletasks()
        try:
            remote = list_github_repositories()
        except RuntimeError as exc:
            self.remote_status_var.set(f"取得失敗: {exc}")
            return
        managed = {item.name for item in self.all_definitions} | {"development-management"}
        self.unmanaged_repos = unmanaged_github_repositories(managed, remote)
        self.new_repo_list.delete(0, "end")
        for repo in self.unmanaged_repos:
            branch = repo.default_branch or "no branch"
            self.new_repo_list.insert("end", f"NEW  {repo.name}   [{branch}]")
        self.remote_status_var.set("未登録repoなし" if not self.unmanaged_repos else f"未登録 {len(self.unmanaged_repos)} repo")

    def setup_new_repo(self) -> None:
        selection = self.new_repo_list.curselection()
        if not selection:
            messagebox.showinfo("新規repo", "セットアップするrepoを選択してください。")
            return
        remote = self.unmanaged_repos[selection[0]]
        dest = REPOS_ROOT / remote.name
        if not (dest / ".git").exists():
            if dest.exists():
                messagebox.showerror("セットアップ停止", f"{dest} が存在しますがGit repoではありません。自動変更しません。")
                return
            if not messagebox.askyesno(
                "新規repoセットアップ",
                f"{remote.full_name} を正式パスへcloneします。\n\n{dest}\n\n既存ファイルの上書き・branch変更・buildは行いません。",
            ):
                return
            try:
                clone_new_repository(remote, REPOS_ROOT)
            except RuntimeError as exc:
                messagebox.showerror("セットアップ停止", str(exc))
                return

        try:
            dev_index = next(
                index
                for index, definition in enumerate(self.definitions)
                if definition.name == "development-management"
            )
        except StopIteration:
            messagebox.showerror(
                "セットアップ停止",
                "development-management がManaged Repositoriesにありません。Control Centerを更新してください。",
            )
            return

        task = build_new_repo_registration_task(remote, dest)
        self.repo_list.selection_clear(0, "end")
        self.repo_list.selection_set(dev_index)
        self.repo_list.activate(dev_index)
        self.repo_list.see(dev_index)
        self._select_repo()
        self.ai_task.delete("1.0", "end")
        self.ai_task.insert("1.0", task)
        self.ai_task_by_repo["development-management"] = task
        self.ai_status_var.set("新規repo登録タスクを準備済み")

        self._log(
            f"{remote.name}: clone確認 → development-management のAI依頼欄へ登録タスクをセットしました。"
        )
        messagebox.showinfo(
            "新規repo",
            "正式ローカルrepoを確認しました。\n"
            "development-management を選択し、AI依頼欄へ登録タスクをセットしました。\n\n"
            "必要ならGPTでrepo種別や最初のデモ要件をAI依頼へ追記し、"
            "そのまま「AI開発開始」を押してください。\n"
            "以後は Claude実装 → Tests → Astraレビュー → local candidate の通常ルートです。",
        )

    def check_self_update(self) -> None:
        definition = RepoDefinition("development-management", "management", "main")
        local_state = inspect_repo(DM_ROOT, definition)
        if not local_state.safe_for_lifecycle(definition):
            detail = local_state.error or "main / 正式origin / tracked cleanを確認してください"
            self.self_update_var.set(f"更新停止: {detail}")
            self.self_update_sha = ""
            self._set_button_states()
            return

        self.self_update_var.set("GitHub確認中...")
        self.master.update_idletasks()
        github_state = fetch_github_state(definition)
        self.self_update_sha = ""
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

    def apply_self_update(self) -> None:
        if not self.self_update_sha:
            return
        if not messagebox.askyesno(
            "Control Center更新",
            f"development-managementを {self.self_update_sha} へSYNCします。\nCI: {self.self_update_ci_state}\n\n成功後はControl Centerを自動再起動します。",
        ):
            return
        sync_path = DM_ROOT / "SYNC_CLICK_ME.cmd"
        command = ["cmd.exe", "/c", "call", str(sync_path), self.self_update_sha, "--no-pause"]
        try:
            completed = subprocess.run(command, cwd=DM_ROOT, check=False)
        except OSError as exc:
            messagebox.showerror("更新起動失敗", str(exc))
            return
        if completed.returncode != 0:
            messagebox.showerror("更新停止", f"SYNCが rc={completed.returncode} で停止しました。SYNC_RESULT.txtを確認してください。")
            return
        self._log(f"Control Center: self update完了 → {short_sha(self.self_update_sha)}")
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.executable.lower().endswith("python.exe") else 0
            subprocess.Popen([sys.executable, str(LAUNCHER_PATH)], cwd=DM_ROOT, creationflags=flags)
        except OSError as exc:
            messagebox.showwarning("更新完了", f"更新は完了しましたが自動再起動に失敗しました。\n{exc}\n\nDEV_CONTROL_CENTER.pyw を開き直してください。")
            return
        self.master.destroy()

    def launch_ai_orchestrator(self) -> None:
        if not self.current or not self.repo_state or self.active_process is not None:
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
        ]
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=DM_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
            )
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
        self.active_process = (process, self.current.name, "ai_orchestrator")
        self.ai_status_var.set("実行中 — Claude実装 → Tests → Astraレビュー")
        self._log(f"{self.current.name}: AI Orchestrator開始")
        self.banner_var.set("AI開発実行中。完了まで別工程はロックします。")
        self._set_button_states()

        reader = threading.Thread(
            target=self._read_ai_output,
            args=(process,),
            daemon=True,
        )
        reader.start()
        self.master.after(250, self._poll)

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
            self._log(f"AI: {line}")
            self.ai_status_var.set(line)

    def _finish_ai_orchestrator(self, repo_name: str, rc: int) -> None:
        context = self.ai_context or {}
        self.ai_context = None
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
        candidate = str(payload.get("candidate_sha", "")).strip().lower()
        if rc != 0 or status != "candidate_ready" or not candidate_sha_is_valid(candidate):
            error = str(payload.get("error", "")).strip() or f"rc={rc}"
            self.ai_status_var.set(f"STOP: {error}")
            self._log(f"{repo_name}: AI Orchestrator停止 — {error}")
            messagebox.showerror(
                "AI開発停止",
                f"candidateは作成されませんでした。\n\n{error}",
            )
            return

        self.candidate_by_repo[repo_name] = candidate
        claude_calls = payload.get("claude_calls", "?")
        codex_calls = payload.get("codex_calls", "?")
        rounds = payload.get("rounds_used", "?")
        self.ai_status_var.set(
            f"CANDIDATE READY {short_sha(candidate)} / "
            f"rounds={rounds} Claude={claude_calls} Astra={codex_calls}"
        )
        self._log(
            f"{repo_name}: AI candidate {candidate} "
            f"(rounds={rounds}, Claude={claude_calls}, Astra={codex_calls})"
        )

        if not self.current or self.current.name != repo_name:
            return

        self._applying_lifecycle = True
        try:
            self.candidate_var.set(candidate)
            self.candidate_by_repo[repo_name] = candidate
        finally:
            self._applying_lifecycle = False

        base_sha = str(payload.get("base_sha", "") or context.get("base_sha", "")).lower()
        if not messagebox.askyesno(
            "AI candidate ready",
            f"candidate {candidate}\n\n"
            "このcandidateをローカルexpected branchへfast-forwardして、"
            "RUN_DEVで実機確認できる状態にしますか？\n\n"
            "push / BUILD / UPDATEは行いません。",
        ):
            self.banner_var.set(
                f"AI candidate {short_sha(candidate)} は作成済み。ローカル適用は未実施です。"
            )
            self._set_button_states()
            return

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
            self.refresh()
            return

        self._log(f"{repo_name}: local expected branchをAI candidateへfast-forward {short_sha(candidate)}")
        self.refresh()
        self.banner_var.set(
            f"AI candidate {short_sha(candidate)} をローカル適用済み。RUN_DEVで実機確認してください。"
        )
        messagebox.showinfo(
            "AI candidate ready",
            f"ローカルcandidateを適用しました。\n\n{candidate}\n\n"
            "次はRUN_DEVで実機確認してください。push / BUILD / UPDATEは未実施です。",
        )

    def launch(self, action: str) -> None:
        if not self.current or not self.entrypoints or not self.repo_state or self.active_process is not None:
            return
        if not self.repo_state.safe_for_lifecycle(self.current):
            messagebox.showerror("STOP", "正式repo / branch / origin / tracked clean の安全条件を満たしていません。")
            return
        choice = getattr(self.entrypoints, action)
        if not choice.ready or not choice.path:
            messagebox.showerror("STOP", f"{action.upper()} の正式入口を一意に特定できません。")
            return

        args: list[str] = []
        candidate = self.candidate_var.get().strip()
        if action == "sync":
            if not candidate_sha_is_valid(candidate):
                messagebox.showerror("STOP", "candidateは完全40桁SHAで指定してください。")
                return
            args = [candidate]
        elif not self._candidate_matches_local():
            messagebox.showerror("STOP", "ローカルHEADがcandidate SHAと一致していません。先にSYNCしてください。")
            return

        if action == "release" and not messagebox.askyesno(
            self.entrypoints.release_label,
            f"candidate {candidate}\n\nこのSHAをユーザー実機確認済みで、必要なBUILDも完了していますか？\n正式な配布/更新入口を起動します。",
        ):
            return
        self._launch_cmd(choice.path, args, action)

    def _launch_cmd(self, path: Path, args: list[str], action: str) -> None:
        if path.suffix.lower() not in {".cmd", ".bat"}:
            messagebox.showerror("STOP", f"CMD/BATの正式入口だけ実行します: {path.name}")
            return
        repo_root = REPOS_ROOT / self.current.name
        command = ["cmd.exe", "/c", "call", str(path), *args]
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            process = subprocess.Popen(command, cwd=path.parent, creationflags=flags)
        except OSError as exc:
            messagebox.showerror("起動失敗", str(exc))
            return
        self.active_process = (process, self.current.name, action)
        self._log(f"{self.current.name}: {action.upper()} → {path.relative_to(repo_root)}")
        self.banner_var.set(f"{action.upper()} 実行中。完了まで別工程はロックします。")
        self._set_button_states()
        self.master.after(750, self._poll)

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
        self.active_process = None
        self._log(f"{repo_name}: {action.upper()} 終了 rc={rc}")

        if action == "ai_orchestrator":
            self._finish_ai_orchestrator(repo_name, rc)
            if self.current and self.current.name == repo_name:
                self._set_button_states()
            return

        if self.current and self.current.name == repo_name:
            self.refresh()
            self.refresh_github()
        else:
            self._set_button_states()

    def _set_button_states(self) -> None:
        self._apply_lifecycle_state()

    def _copy_to_clipboard(self, text: str) -> None:
        self.master.clipboard_clear()
        self.master.clipboard_append(text)
        self.master.update_idletasks()

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
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
