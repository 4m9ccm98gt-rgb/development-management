"""Tkinter UI for the Development Control Center."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from .core import (
    ControlCenterConfigError,
    RepoDefinition,
    active_repo_definitions,
    candidate_sha_is_valid,
    choice_text,
    discover_entrypoints,
    inspect_repo,
    short_sha,
)

DM_ROOT = Path(__file__).resolve().parents[2]
REPOS_ROOT = DM_ROOT.parent
TYPES_PATH = DM_ROOT / "scripts" / "repo_types.toml"
BRANCHES_PATH = DM_ROOT / "scripts" / "dev_control_center_repos.toml"


class App(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=14)
        self.master = master
        self.definitions = active_repo_definitions(TYPES_PATH, BRANCHES_PATH)
        self.current: RepoDefinition | None = None
        self.repo_state = None
        self.entrypoints = None
        self.active_process = None
        self.candidate_by_repo = {d.name: "" for d in self.definitions}

        self.title_var = tk.StringVar()
        self.meta_var = tk.StringVar()
        self.branch_var = tk.StringVar()
        self.head_var = tk.StringVar()
        self.origin_var = tk.StringVar()
        self.clean_var = tk.StringVar()
        self.candidate_var = tk.StringVar()
        self.sync_var = tk.StringVar()
        self.run_var = tk.StringVar()
        self.build_var = tk.StringVar()
        self.release_var = tk.StringVar()
        self.release_button_var = tk.StringVar(value="⑤ UPDATE")
        self.banner_var = tk.StringVar(value="repoを選択してください")

        self._build()
        self.candidate_var.trace_add("write", lambda *_: self._set_button_states())
        if self.definitions:
            self.repo_list.selection_set(0)
            self._select_repo()

    def _build(self) -> None:
        self.master.title("Development Control Center")
        self.master.geometry("1160x740")
        self.master.minsize(960, 620)
        self.pack(fill="both", expand=True)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        ttk.Label(left, text="Apps", font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 8))
        self.repo_list = tk.Listbox(left, width=34, height=28, exportselection=False)
        self.repo_list.pack(fill="y", expand=True)
        self.repo_list.bind("<<ListboxSelect>>", lambda _e: self._select_repo())
        for item in self.definitions:
            self.repo_list.insert("end", f"{item.name}   [{item.repo_type}]")
        ttk.Button(left, text="状態更新", command=self.refresh).pack(fill="x", pady=(10, 0))
        ttk.Button(left, text="GitHubを開く", command=self.open_github).pack(fill="x", pady=(6, 0))

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(5, weight=1)

        ttk.Label(right, textvariable=self.title_var, font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.meta_var).grid(row=1, column=0, sticky="w", pady=(2, 10))

        status = ttk.LabelFrame(right, text="現在状態", padding=10)
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

        flow = ttk.LabelFrame(right, text="ChatGPT開発 → SYNC → RUN → BUILD → UPDATE", padding=10)
        flow.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        for col in range(5):
            flow.columnconfigure(col, weight=1)
        self.chat_button = ttk.Button(flow, text="①② ChatGPT開発", command=self.open_chatgpt)
        self.chat_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.sync_button = ttk.Button(flow, text="③ SYNC", command=lambda: self.launch("sync"))
        self.sync_button.grid(row=0, column=1, sticky="ew", padx=5)
        self.run_button = ttk.Button(flow, text="④ RUN_DEV", command=lambda: self.launch("run"))
        self.run_button.grid(row=0, column=2, sticky="ew", padx=5)
        self.build_button = ttk.Button(flow, text="⑤ BUILD", command=lambda: self.launch("build"))
        self.build_button.grid(row=0, column=3, sticky="ew", padx=5)
        self.release_button = ttk.Button(flow, textvariable=self.release_button_var, command=lambda: self.launch("release"))
        self.release_button.grid(row=0, column=4, sticky="ew", padx=(5, 0))

        ttk.Label(flow, text="candidate SHA").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(flow, textvariable=self.candidate_var).grid(row=1, column=1, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Label(flow, text="各工程は自動連続しません。③はSHA一致で停止、④確認後に⑤へ進みます。").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(8, 0)
        )

        entries = ttk.LabelFrame(right, text="検出した正式入口", padding=10)
        entries.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        entries.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate([
            ("SYNC", self.sync_var),
            ("RUN", self.run_var),
            ("BUILD", self.build_var),
            ("UPDATE/DEPLOY", self.release_var),
        ]):
            ttk.Label(entries, text=label, width=16).grid(row=row, column=0, sticky="nw")
            ttk.Label(entries, textvariable=var, wraplength=760).grid(row=row, column=1, sticky="w")

        log_box = ttk.LabelFrame(right, text="操作ログ", padding=8)
        log_box.grid(row=5, column=0, sticky="nsew")
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=9, state="disabled", wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        ttk.Label(right, textvariable=self.banner_var).grid(row=6, column=0, sticky="w", pady=(8, 0))

    def _select_repo(self) -> None:
        selection = self.repo_list.curselection()
        if not selection:
            return
        if self.current:
            self.candidate_by_repo[self.current.name] = self.candidate_var.get().strip()
        self.current = self.definitions[selection[0]]
        self.candidate_var.set(self.candidate_by_repo[self.current.name])
        self.refresh()

    def refresh(self) -> None:
        if not self.current:
            return
        repo_root = REPOS_ROOT / self.current.name
        self.repo_state = inspect_repo(repo_root, self.current)
        self.entrypoints = discover_entrypoints(repo_root, self.current.repo_type)
        state = self.repo_state
        entries = self.entrypoints

        self.title_var.set(self.current.name)
        self.meta_var.set(f"{repo_root}   |   type={self.current.repo_type}   |   expected branch={self.current.branch}")
        self.branch_var.set(state.branch or "-")
        self.head_var.set(short_sha(state.head))
        self.origin_var.set(f"{short_sha(state.origin_head)}   ({state.origin_repo or 'origin不明'})")
        if state.error:
            self.clean_var.set(f"STOP: {state.error}")
        else:
            self.clean_var.set(f"{'DIRTY' if state.tracked_dirty else 'CLEAN'}   untracked={state.untracked_count}")
        self.sync_var.set(choice_text(entries.sync, repo_root))
        self.run_var.set(choice_text(entries.run, repo_root))
        self.build_var.set(choice_text(entries.build, repo_root))
        self.release_var.set(choice_text(entries.release, repo_root))
        self.release_button_var.set(f"⑤ {entries.release_label}")
        if state.safe_for_lifecycle(self.current):
            self.banner_var.set("正式repo / branch / origin / tracked clean を確認済み。")
        else:
            self.banner_var.set("安全条件を満たしていないためライフサイクル操作を停止中。")
        self._set_button_states()

    def _set_button_states(self) -> None:
        busy = self.active_process is not None
        safe = bool(self.current and self.repo_state and self.repo_state.safe_for_lifecycle(self.current))
        self.chat_button.configure(state="normal" if self.current and not busy else "disabled")
        if not safe or not self.entrypoints or busy:
            for button in (self.sync_button, self.run_button, self.build_button, self.release_button):
                button.configure(state="disabled")
            return
        self.sync_button.configure(
            state="normal"
            if self.entrypoints.sync.ready and candidate_sha_is_valid(self.candidate_var.get())
            else "disabled"
        )
        self.run_button.configure(state="normal" if self.entrypoints.run.ready else "disabled")
        self.build_button.configure(state="normal" if self.entrypoints.build.ready else "disabled")
        self.release_button.configure(state="normal" if self.entrypoints.release.ready else "disabled")

    def open_chatgpt(self) -> None:
        if not self.current:
            return
        prompt = (
            f"{self.current.name} の開発をお願いします。正式ソースは {self.current.github_url} です。\n"
            "development-management/OPERATING_CONTRACT.md と STARTUP_HANDOFF_POLICY.md を正本として、"
            "①設計→②GitHub開発・PR・candidate SHAのCI greenまで進めてください。\n"
            f"candidate branch は {self.current.branch}。③〜⑤へは進まず、最後に candidate branch / candidate SHA を明示してください。"
        )
        self.master.clipboard_clear()
        self.master.clipboard_append(prompt)
        self.master.update_idletasks()
        webbrowser.open_new_tab("https://chatgpt.com/")
        self._log(f"{self.current.name}: 開発依頼文をコピーしてChatGPTを開きました。")

    def open_github(self) -> None:
        if self.current:
            webbrowser.open_new_tab(self.current.github_url)

    def launch(self, action: str) -> None:
        if not self.current or not self.entrypoints or not self.repo_state:
            return
        if self.active_process is not None:
            return
        if not self.repo_state.safe_for_lifecycle(self.current):
            messagebox.showerror("STOP", "正式repo / branch / origin / tracked clean の安全条件を満たしていません。")
            return
        choice = getattr(self.entrypoints, action)
        if not choice.ready or not choice.path:
            messagebox.showerror("STOP", f"{action.upper()} の正式入口を一意に特定できません。")
            return
        args: list[str] = []
        if action == "sync":
            candidate = self.candidate_var.get().strip()
            if not candidate_sha_is_valid(candidate):
                return
            args = [candidate]
        if action == "release":
            if not messagebox.askyesno(
                f"⑤ {self.entrypoints.release_label}",
                "④の実機確認と必要なBUILDが完了していることを確認しましたか？\n\n対象repoの正式な配布/更新入口を起動します。",
            ):
                return
        self._launch_cmd(choice.path, args, action)

    def _launch_cmd(self, path: Path, args: list[str], action: str) -> None:
        if path.suffix.lower() not in {".cmd", ".bat"}:
            messagebox.showerror("STOP", f"初版はCMD/BATの正式入口だけ実行します: {path.name}")
            return
        repo_root = REPOS_ROOT / self.current.name
        command = ["cmd.exe", "/c", "call", str(path), *args]
        try:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            process = subprocess.Popen(command, cwd=repo_root, creationflags=flags)
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
        rc = process.poll()
        if rc is None:
            self.master.after(750, self._poll)
            return
        self.active_process = None
        self._log(f"{repo_name}: {action.upper()} 終了 rc={rc}")
        if self.current and self.current.name == repo_name:
            self.refresh()
        else:
            self._set_button_states()

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
