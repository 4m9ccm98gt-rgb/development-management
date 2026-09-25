"""AI Orchestrator window: a client of the run directory, never the owner of a run.

Closing this window (or DCC) does not touch any run. Runs are started through
`orchestrator.start_run` (a detached worker), watched through `RunMonitor` (a background
poller of the run files) and stopped only by the explicit "AI安全停止" action.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from tools.ai_orchestrator import orchestrator as orch
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator import usage as usage_mod
from tools.ai_orchestrator.common import OrchestratorError
from tools.ai_orchestrator.providers import DEFAULT_MAIN_AGENT, DEFAULT_REVIEW_AGENT, PROVIDER_CLASSES

POLL_SECONDS = 2.0
UI_TICK_MS = 400
MAX_LOG_CHARS = 400_000

LIVENESS_TEXT = {
    rs.LIVE_RUNNING: "実行中",
    rs.LIVE_STARTING: "起動中",
    rs.LIVE_UNRESPONSIVE: "接続不能・状態確認が必要（実行中と断定できません）",
    rs.LIVE_LOST: "workerが消失（staleと判定）",
    rs.LIVE_FINISHED: "終了",
    rs.LIVE_UNKNOWN: "状態不明",
}
STAGE_TEXT = {
    rs.CREATED: "作成済み", rs.PREFLIGHT: "事前確認", rs.IMPLEMENTING: "Main実装中", rs.TESTING: "Tests実行中",
    rs.REPAIRING: "Main修正中", rs.REVIEWING: "Reviewer確認中", rs.FINALIZING: "完了前の安全チェック",
    rs.COMPLETED: "完成", rs.NEEDS_HUMAN: "人間の確認が必要", rs.STOPPING: "停止処理中",
    rs.STOPPED: "AI安全停止", rs.FAILED: "失敗",
}
LIVE_MARK = {rs.LIVE_RUNNING: "●", rs.LIVE_STARTING: "◐", rs.LIVE_UNRESPONSIVE: "?", rs.LIVE_LOST: "✕",
             rs.LIVE_FINISHED: "○", rs.LIVE_UNKNOWN: "-"}
ROLE_LABEL = {"claude": "Claude", "codex": "Codex"}


def role_label(name: str) -> str:
    return ROLE_LABEL.get(name, name)


class RunMonitor:
    """Polls run files, usage caches and the selected run's log off the UI thread."""

    def __init__(self, *, interval: float = POLL_SECONDS, list_runs=rs.list_runs, usage_names=("claude", "codex")):
        self.interval = interval
        self._list_runs = list_runs
        self._usage_names = usage_names
        self._selected: str | None = None
        self._offset = 0
        self._reset = True
        self._reconciled: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.queue: queue.Queue = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None

    def select(self, run_id: str | None) -> None:
        with self._lock:
            if run_id != self._selected:
                self._selected, self._offset, self._reset = run_id, 0, True
        self._wake.set()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="orchestrator-monitor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh_now(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self.poll_once()
            except Exception as exc:  # noqa: BLE001 - the monitor must outlive any single bad poll
                snapshot = {"error": f"{type(exc).__name__}: {exc}"}
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(snapshot)
            except queue.Full:
                pass
            self._wake.wait(self.interval)
            self._wake.clear()

    def poll_once(self) -> dict:
        runs = self._list_runs(limit=40)
        for item in runs:
            record = item["record"]
            if item["liveness"] == rs.LIVE_LOST and record["run_id"] not in self._reconciled:
                # Provably dead worker: end the run record, release the repo lock and stop any
                # provider children it still owned (verified by PID + creation time).
                self._reconciled.add(record["run_id"])
                try:
                    rs.reconcile_lost(item["run_dir"])
                except Exception:  # noqa: BLE001
                    pass
                fresh = rs.inspect_run(item["run_dir"])
                item.update(liveness=fresh["liveness"], record=fresh["record"] or record, reason=fresh["reason"])
        with self._lock:
            selected = self._selected
            offset, reset = self._offset, self._reset
            self._reset = False
        log_text = ""
        if selected:
            match = next((i for i in runs if i["record"]["run_id"] == selected), None)
            if match is not None:
                log_text, new_offset = rs.tail_log(match["run_dir"], offset)
                with self._lock:
                    if self._selected == selected:
                        self._offset = new_offset
        usage = {}
        for name in self._usage_names:
            try:
                usage[name] = usage_mod.make_usage_provider(name).load()
            except Exception:  # noqa: BLE001
                usage[name] = {"account": None, "context": None, "errors": {"account": "cache unreadable"}}
        return {"runs": runs, "usage": usage, "selected": selected, "log": log_text, "log_reset": reset,
                "at": time.time()}


@dataclass
class Draft:
    task: str = ""
    tests: str = ""


def _style_dark_comboboxes(master: tk.Misc) -> None:
    """The shared DCC theme does not cover ttk.Combobox; give it the same dark palette."""
    from . import app as theme

    style = ttk.Style(master)
    style.configure("TCombobox", fieldbackground=theme.DARK_FIELD, background=theme.DARK_FIELD,
                    foreground=theme.DARK_FG, arrowcolor=theme.DARK_FG, bordercolor=theme.DARK_BORDER,
                    lightcolor=theme.DARK_BORDER, darkcolor=theme.DARK_BORDER, insertcolor=theme.DARK_FG,
                    selectbackground=theme.DARK_FIELD, selectforeground=theme.DARK_FG, padding=(6, 4))
    style.map("TCombobox",
              fieldbackground=[("readonly", theme.DARK_FIELD), ("disabled", theme.DARK_DISABLED_BG)],
              foreground=[("readonly", theme.DARK_FG), ("disabled", theme.DARK_DISABLED_FG)],
              selectbackground=[("readonly", theme.DARK_FIELD)], selectforeground=[("readonly", theme.DARK_FG)],
              background=[("active", theme.DARK_SELECTION)], bordercolor=[("focus", theme.DARK_ACCENT)])
    master.option_add("*TCombobox*Listbox.background", theme.DARK_SURFACE)
    master.option_add("*TCombobox*Listbox.foreground", theme.DARK_FG)
    master.option_add("*TCombobox*Listbox.selectBackground", theme.DARK_SELECTION)
    master.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")


def _set_enabled(button: ttk.Button, enabled: bool) -> None:
    """Change ttk's disabled bit only when it really changes, so hover / pressed states survive."""
    if bool(button.instate(["disabled"])) == (not enabled):
        return
    button.state(["!disabled" if enabled else "disabled"])


class OrchestratorWindow:
    def __init__(self, master: tk.Misc, definitions, *, initial_repo: str | None, drafts: dict,
                 on_apply: Callable[[dict, Path], None] | None = None, monitor: RunMonitor | None = None,
                 repos_root: Path | None = None, auto_usage: bool = True) -> None:
        from .app import DARK_BG, DARK_MUTED, configure_dark_listbox, configure_dark_text

        self._events: queue.Queue = queue.Queue()
        self._shown_repo = ""
        self.definitions = list(definitions)
        self.drafts = drafts
        self.on_apply = on_apply
        self.repos_root = repos_root
        self._closed = False
        # Worker threads must never hold `self`: a Tk object released on a non-main thread aborts Tcl.
        self._closed_event = threading.Event()
        self.snapshot: dict = {}
        self.selected_run: str | None = None
        self.run_items: list[dict] = []
        self.window = tk.Toplevel(master)
        self.window.title("AI Orchestrator")
        self.window.geometry("1180x840")
        self.window.minsize(1000, 740)
        self.window.configure(background=DARK_BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._muted = DARK_MUTED
        _style_dark_comboboxes(self.window)

        self.repo_var = tk.StringVar()
        self.tests_var = tk.StringVar()
        self.main_var = tk.StringVar(value=role_label(DEFAULT_MAIN_AGENT))
        self.review_var = tk.StringVar(value=role_label(DEFAULT_REVIEW_AGENT))
        self.notice_var = tk.StringVar(value="")
        self.warn_var = tk.StringVar(value="")
        self.stage_var = tk.StringVar(value="-")
        self.counts_var = tk.StringVar(value="-")
        self.calls_var = tk.StringVar(value="-")
        self.fp_var = tk.StringVar(value="-")
        self.time_var = tk.StringVar(value="-")
        self.result_var = tk.StringVar(value="-")
        self.roles_var = tk.StringVar(value="-")
        self.usage_vars = {name: tk.StringVar(value="取得不能（未取得）") for name in ("claude", "codex")}
        self.usage_role_vars = {name: tk.StringVar(value="") for name in ("claude", "codex")}

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ttk.Label(left, text="実行中 / 過去のrun", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.run_list = tk.Listbox(left, width=58, exportselection=False)
        configure_dark_listbox(self.run_list)
        self.run_list.pack(fill="both", expand=True, pady=(6, 0))
        self.run_list.bind("<<ListboxSelect>>", lambda _e: self._on_run_selected())

        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(9, weight=1)

        row = 0
        ttk.Label(right, text="対象repo", width=12).grid(row=row, column=0, sticky="w")
        self.repo_box = ttk.Combobox(right, textvariable=self.repo_var, state="readonly",
                                     values=[d.name for d in self.definitions])
        self.repo_box.grid(row=row, column=1, sticky="ew", columnspan=3)
        self.repo_box.bind("<<ComboboxSelected>>", lambda _e: self._on_repo_changed())

        row += 1
        ttk.Label(right, text="Task", width=12).grid(row=row, column=0, sticky="nw", pady=(6, 0))
        self.task_text = tk.Text(right, height=6, wrap="word")
        configure_dark_text(self.task_text)
        self.task_text.grid(row=row, column=1, columnspan=3, sticky="ew", pady=(6, 0))

        row += 1
        ttk.Label(right, text="Tests", width=12).grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(right, textvariable=self.tests_var).grid(row=row, column=1, columnspan=3, sticky="ew", pady=(6, 0))

        row += 1
        roles = ttk.Frame(right)
        roles.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(roles, text="Main AI").pack(side="left")
        self.main_box = ttk.Combobox(roles, textvariable=self.main_var, state="readonly", width=10,
                                     values=[role_label(n) for n in PROVIDER_CLASSES if n in ROLE_LABEL])
        self.main_box.pack(side="left", padx=(6, 18))
        ttk.Label(roles, text="Reviewer AI").pack(side="left")
        self.review_box = ttk.Combobox(roles, textvariable=self.review_var, state="readonly", width=10,
                                       values=[role_label(n) for n in PROVIDER_CLASSES if n in ROLE_LABEL])
        self.review_box.pack(side="left", padx=(6, 18))
        self.main_box.bind("<<ComboboxSelected>>", lambda _e: self._on_role_changed("main"))
        self.review_box.bind("<<ComboboxSelected>>", lambda _e: self._on_role_changed("review"))
        self.start_button = ttk.Button(roles, text="開始", command=self.start_run)
        self.start_button.pack(side="left", padx=(6, 6))
        self.stop_button = ttk.Button(roles, text="AI安全停止", command=self.stop_run)
        self.stop_button.pack(side="left", padx=6)
        self.usage_button = ttk.Button(roles, text="残量更新", command=self.refresh_usage)
        self.usage_button.pack(side="left", padx=6)
        ttk.Label(right, textvariable=self.notice_var, wraplength=800, foreground=DARK_MUTED).grid(
            row=row + 1, column=0, columnspan=4, sticky="w")
        ttk.Label(right, textvariable=self.warn_var, wraplength=800, foreground="#e3b341").grid(
            row=row + 2, column=0, columnspan=4, sticky="w")
        row += 3

        usage_frame = ttk.Frame(right)
        usage_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        usage_frame.columnconfigure(0, weight=1)
        usage_frame.columnconfigure(1, weight=1)
        self.usage_labels = {}
        for col, name in enumerate(("claude", "codex")):
            box = ttk.LabelFrame(usage_frame, text=role_label(name), padding=8)
            box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0))
            ttk.Label(box, textvariable=self.usage_role_vars[name], foreground="#58a6ff").pack(anchor="w")
            label = ttk.Label(box, textvariable=self.usage_vars[name], font=("Consolas", 9), justify="left")
            label.pack(anchor="w")
            self.usage_labels[name] = label

        row += 1
        status = ttk.LabelFrame(right, text="選択中のrun", padding=8)
        status.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        status.columnconfigure(1, weight=1)
        for r, (label, var) in enumerate([
            ("Main / Reviewer", self.roles_var), ("Current stage", self.stage_var), ("Tests", self.counts_var),
            ("AI呼出し", self.calls_var), ("failure fingerprint", self.fp_var), ("時刻", self.time_var),
            ("最終結果", self.result_var),
        ]):
            ttk.Label(status, text=label, width=20).grid(row=r, column=0, sticky="nw")
            ttk.Label(status, textvariable=var, wraplength=720, justify="left").grid(row=r, column=1, sticky="w")
        self.apply_button = ttk.Button(status, text="candidateをlocalへ適用", command=self.apply_candidate)
        self.apply_button.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(12, 0))

        row += 1
        ttk.Label(right, text="ログ（画面を閉じてもrunは継続します）", foreground=DARK_MUTED).grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.log = tk.Text(right, height=10, state="disabled", wrap="word")
        configure_dark_text(self.log)
        # `right.rowconfigure(9, weight=1)` targets this row
        self.log.grid(row=9, column=0, columnspan=4, sticky="nsew")

        self.monitor = monitor or RunMonitor()
        self._own_monitor = monitor is None
        self.monitor.start()
        self._select_repo(initial_repo or (self.definitions[0].name if self.definitions else ""))
        self._on_role_changed("main")
        self._tick_id = self.window.after(UI_TICK_MS, self._tick)
        if auto_usage:
            self._refresh_free_usage()

    def _refresh_free_usage(self) -> None:
        """On open, refresh only what costs nothing: the Codex account query spends no tokens.
        Claude reports its limits only inside a real call, so it stays on last known values until the
        user presses 残量更新 or a run makes a call. Never raises; throttled by the adapter."""
        monitor, closed = self.monitor, self._closed_event

        def work() -> None:
            try:
                usage_mod.make_usage_provider("codex").refresh()
            except Exception:  # noqa: BLE001 - auxiliary
                pass
            if not closed.is_set():
                monitor.refresh_now()

        threading.Thread(target=work, name="orchestrator-usage-open", daemon=True).start()

    # ---------------------------------------------------------------- lifecycle
    def exists(self) -> bool:
        return not self._closed and bool(self.window.winfo_exists())

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()

    def close(self) -> None:
        """Close the window only. Runs, workers and provider processes are untouched."""
        if self._closed:
            return
        self._save_draft()
        self._closed = True
        self._closed_event.set()
        try:
            self.window.after_cancel(self._tick_id)
        except (tk.TclError, AttributeError):
            pass
        if self._own_monitor:
            self.monitor.stop()
        self.window.destroy()

    # ---------------------------------------------------------------- repo / drafts
    def _save_draft(self) -> None:
        if self._shown_repo:
            self.drafts[self._shown_repo] = Draft(self.task_text.get("1.0", "end").strip(), self.tests_var.get().strip())

    def _select_repo(self, name: str) -> None:
        self.repo_var.set(name)
        draft = self.drafts.get(name)
        definition = next((d for d in self.definitions if d.name == name), None)
        task = draft.task if draft else (getattr(definition, "initial_ai_task", "") if definition else "")
        tests = draft.tests if draft else (getattr(definition, "initial_test", "") if definition else "")
        self.task_text.delete("1.0", "end")
        if task:
            self.task_text.insert("1.0", task)
        self.tests_var.set(tests or "")
        self._shown_repo = name

    def select_repo(self, name: str) -> None:
        if name != self._shown_repo:
            self._save_draft()
            self._select_repo(name)

    def suggest_tests(self, name: str, value: str) -> None:
        """A suggested Tests command only fills an empty field of the repo being shown."""
        if name == self._shown_repo and not self.tests_var.get().strip():
            self.tests_var.set(value)

    def _on_repo_changed(self) -> None:
        name = self.repo_var.get()
        self._save_draft()
        self._select_repo(name)

    # ---------------------------------------------------------------- roles
    def _names(self) -> tuple[str, str]:
        inverse = {v: k for k, v in ROLE_LABEL.items()}
        return inverse.get(self.main_var.get(), DEFAULT_MAIN_AGENT), inverse.get(self.review_var.get(), DEFAULT_REVIEW_AGENT)

    def _on_role_changed(self, changed: str) -> None:
        main, reviewer = self._names()
        if main == reviewer:
            # A Reviewer from the same provider is not an independent review: never selectable.
            other = next((n for n in ROLE_LABEL if n != main), main)
            if changed == "main":
                self.review_var.set(role_label(other))
            else:
                self.main_var.set(role_label(other))
            self.notice_var.set("Main AIとReviewer AIは異なるproviderにします（同一providerでは独立レビューにならないため自動で入れ替えました）")
        else:
            self.notice_var.set("Main AIが実装・修正し、Reviewer AIは読み取り専用でレビューします。")
        self._update_usage_roles()
        self._update_warnings()

    def _update_usage_roles(self) -> None:
        main, reviewer = self._names()
        for name, var in self.usage_role_vars.items():
            var.set("Main" if name == main else "Reviewer" if name == reviewer else "")

    def _update_warnings(self) -> None:
        main, reviewer = self._names()
        lines = []
        for role, name in (("Main AI", main), ("Reviewer AI", reviewer)):
            data = (self.snapshot.get("usage") or {}).get(name)
            if data:
                lines += usage_mod.warnings(data, f"{role}（{role_label(name)}）")
        self.warn_var.set("\n".join(lines))

    # ---------------------------------------------------------------- actions
    def start_run(self) -> None:
        self._save_draft()
        name = self.repo_var.get()
        definition = next((d for d in self.definitions if d.name == name), None)
        task = self.task_text.get("1.0", "end").strip()
        tests = self.tests_var.get().strip()
        if definition is None:
            return
        if not task:
            messagebox.showinfo("AI Orchestrator", "Taskを入力してください。", parent=self.window)
            return
        if not tests:
            messagebox.showerror("AI Orchestrator", "独立Testsコマンドが未設定です。Tests欄へ入力してください。", parent=self.window)
            return
        main, reviewer = self._names()
        repo_root = (self.repos_root or Path(__file__).resolve().parents[3]) / name
        request = orch.StartRequest(repo=str(repo_root), task=task, tests=[tests], main_agent=main,
                                    review_agent=reviewer, expected_branch=definition.branch)
        self.start_button.state(["disabled"])
        self.notice_var.set("開始条件を確認し、独立したrun workerを起動しています...")

        events, closed = self._events, self._closed_event

        def work() -> None:
            try:
                run_dir = orch.start_run(request)
                outcome: tuple = ("ok", run_dir)
            except (OrchestratorError, OSError) as exc:
                outcome = ("error", str(exc))
            except Exception as exc:  # noqa: BLE001
                outcome = ("error", f"{type(exc).__name__}: {exc}")
            if not closed.is_set():
                events.put(outcome)

        threading.Thread(target=work, name="orchestrator-start", daemon=True).start()

    def stop_run(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        record, liveness = item["record"], item["liveness"]
        if liveness == rs.LIVE_LOST:
            action = lambda: rs.reconcile_lost(item["run_dir"])  # noqa: E731
            text = "workerが消失したrunを整理します（そのrunが所有していた子processのみ終了）。"
        else:
            action = lambda: rs.force_stop(item["run_dir"])  # noqa: E731
            text = ("このrunのAI（Claude / Codex）、Tests、補助processだけを安全停止しますか？\n\n"
                    "無関係なClaude / Codex / Pythonなどは停止しません。source repoは変更されません。"
                    "isolated worktreeとrun logは保持されます。")
        if not messagebox.askyesno("AI安全停止", text, parent=self.window):
            return
        _set_enabled(self.stop_button, False)
        self.notice_var.set("安全停止を実行中...")
        events = self._events

        def work() -> None:
            try:
                final = action()
                stage = (final or {}).get("stage", "?")
                events.put(("stopped", f"停止処理が完了しました（{STAGE_TEXT.get(stage, stage)}）"))
            except Exception as exc:  # noqa: BLE001
                events.put(("error", f"AI安全停止に失敗: {exc}。状態を確認してください"))

        threading.Thread(target=work, name="orchestrator-stop", daemon=True).start()

    def refresh_usage(self) -> None:
        main, reviewer = self._names()
        self.notice_var.set("残量を確認しています（Claudeは最小の1回呼出しで取得します）...")
        events = self._events

        def work() -> None:
            for name in {main, reviewer}:
                try:
                    usage_mod.make_usage_provider(name).refresh(force=True)
                except Exception:  # noqa: BLE001 - never fatal; the card shows the failure
                    pass
            events.put(("usage", ""))

        threading.Thread(target=work, name="orchestrator-usage", daemon=True).start()

    def apply_candidate(self) -> None:
        item = self._selected_item()
        if item is None or self.on_apply is None:
            return
        self.on_apply(item["record"], item["run_dir"])

    # ---------------------------------------------------------------- polling / rendering
    def _selected_item(self) -> dict | None:
        return next((i for i in self.run_items if i["record"]["run_id"] == self.selected_run), None)

    def _on_run_selected(self) -> None:
        index = self.run_list.curselection()
        if not index or index[0] >= len(self.run_items):
            return
        self.selected_run = self.run_items[index[0]]["record"]["run_id"]
        self.monitor.select(self.selected_run)
        self._render_selected()

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self.window.after_cancel(self._tick_id)  # never keep two tick chains alive
        except (tk.TclError, AttributeError):
            pass
        try:
            while True:
                kind, value = self._events.get_nowait()
                if kind == "ok":
                    self.selected_run = value.name
                    self.monitor.select(value.name)
                    self.notice_var.set(f"run {value.name} を独立workerで開始しました。この画面やDCCを閉じても継続します。")
                elif kind == "error":
                    self.notice_var.set(value)
                    messagebox.showerror("AI Orchestrator", value, parent=self.window)
                else:
                    self.notice_var.set(value or self.notice_var.get())
                self.monitor.refresh_now()
        except queue.Empty:
            pass
        try:
            snapshot = self.monitor.queue.get_nowait()
        except queue.Empty:
            snapshot = None
        if snapshot is not None:
            self.apply_snapshot(snapshot)
        self._tick_id = self.window.after(UI_TICK_MS, self._tick)

    def apply_snapshot(self, snapshot: dict) -> None:
        if "error" in snapshot:
            self.notice_var.set("run状態を読み込めません: " + snapshot["error"])
            return
        self.snapshot = snapshot
        self.run_items = list(snapshot.get("runs", []))
        self._render_runs()
        for name, data in (snapshot.get("usage") or {}).items():
            if name in self.usage_vars:
                rows = usage_mod.describe(data)
                width = max(len(label) for label, _ in rows)
                self.usage_vars[name].set("\n".join(f"{label:<{width}}  {text}" for label, text in rows))
        self._update_warnings()
        self._render_selected()
        if snapshot.get("log_reset"):
            self._set_log("")
        if snapshot.get("log"):
            self._append_log(snapshot["log"])

    def _run_line(self, item: dict) -> str:
        record = item["record"]
        stamp = str(record.get("created_at", ""))[5:16].replace("T", " ")
        repo = Path(str(record["repo"])).name
        repo = repo if len(repo) <= 20 else repo[:19] + "…"
        return (f"{LIVE_MARK.get(item['liveness'], '-')} {stamp} {repo} {record['stage']} "
                f"[{record['main_agent'][:1].upper()}→{record['review_agent'][:1].upper()}]")

    def _render_runs(self) -> None:
        lines = [self._run_line(i) for i in self.run_items]
        current = list(self.run_list.get(0, "end"))
        if lines != current:
            self.run_list.delete(0, "end")
            for line in lines:
                self.run_list.insert("end", line)
        if self.selected_run is None and self.run_items:
            repo = self.repo_var.get()
            active = [i for i in self.run_items if i["liveness"] in (rs.LIVE_RUNNING, rs.LIVE_STARTING, rs.LIVE_UNRESPONSIVE)]
            pick = next((i for i in active if Path(str(i["record"]["repo"])).name == repo), None) or (active[0] if active else None)
            if pick is not None:
                self.selected_run = pick["record"]["run_id"]
                self.monitor.select(self.selected_run)
        for index, item in enumerate(self.run_items):
            if item["record"]["run_id"] == self.selected_run:
                self.run_list.selection_clear(0, "end")
                self.run_list.selection_set(index)
                break

    def _render_selected(self) -> None:
        item = self._selected_item()
        # busy start button while a start is in flight is handled by the notice; recompute here
        if item is None:
            for var in (self.stage_var, self.counts_var, self.calls_var, self.fp_var, self.time_var,
                        self.result_var, self.roles_var):
                var.set("-")
            _set_enabled(self.stop_button, False)
            _set_enabled(self.apply_button, False)
            _set_enabled(self.start_button, True)
            return
        record, liveness = item["record"], item["liveness"]
        limits = record.get("limits", {})
        self.roles_var.set(f"Main = {role_label(record['main_agent'])} / Reviewer = {role_label(record['review_agent'])}"
                           + ("" if record.get("reviewer_engaged") else "（Reviewer未投入）"))
        stage = record["stage"]
        detail = f" — {record.get('stage_detail')}" if record.get("stage_detail") else ""
        self.stage_var.set(f"{STAGE_TEXT.get(stage, stage)} ({stage}) / {LIVENESS_TEXT.get(liveness, liveness)}{detail}"
                           + (f"\n{item['reason']}" if item.get("reason") and liveness != rs.LIVE_FINISHED else ""))
        self.counts_var.set(f"実行 {record['tests_run_count']} 回 / FAIL {record['tests_fail_count']} 回"
                            f"（Reviewer投入は{limits.get('reviewer_trigger_fails', 2)}回目のFAIL） / "
                            f"repair iteration {record['repair_iteration']}/{limits.get('max_repair_iterations', '?')}")
        self.calls_var.set(f"Main {record['main_calls']} 回 / Reviewer {record['review_calls']} 回"
                           f" / レビュー履歴 {len(record.get('review_history', []))} 件"
                           + (f" / provider error {len(record.get('provider_errors', []))} 件"
                              if record.get("provider_errors") else "")
                           + (f" / quota error {len(record.get('quota_errors', []))} 件" if record.get("quota_errors") else ""))
        fingerprint = record.get("current_failure_fingerprint")
        counts = record.get("failure_fingerprint_counts", {})
        self.fp_var.set(f"{fingerprint}（同一{counts.get(fingerprint, 0)}回目）" if fingerprint else "なし（直近のTestsはPASS、または未実行）")
        self.time_var.set(f"開始 {record.get('started_at') or record.get('created_at')} / heartbeat {record.get('heartbeat_at') or '-'}"
                          + (f" / 終了 {record['finished_at']}" if record.get("finished_at") else ""))
        final = record.get("final_result")
        if final:
            text = f"{final.get('stage')}: {final.get('code')} — {final.get('message')}"
            if record.get("candidate_sha"):
                text += f"\ncandidate {record['candidate_sha'][:12]} ({record.get('candidate_branch')}) / 適用: {record.get('apply_status') or '-'}"
                if record.get("apply_detail"):
                    text += f" — {record['apply_detail']}"
            self.result_var.set(text)
        else:
            self.result_var.set("実行中")
        active = liveness in (rs.LIVE_RUNNING, rs.LIVE_STARTING, rs.LIVE_UNRESPONSIVE, rs.LIVE_LOST)
        self.stop_button.configure(text="stale runを整理" if liveness == rs.LIVE_LOST else "AI安全停止")
        _set_enabled(self.stop_button, active)
        applicable = (stage == rs.COMPLETED and bool(record.get("candidate_sha"))
                      and record.get("apply_status") != "applied" and self.on_apply is not None)
        _set_enabled(self.apply_button, applicable)

    def _set_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        if text:
            self.log.insert("end", text)
        self.log.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        excess = len(self.log.get("1.0", "end")) - MAX_LOG_CHARS
        if excess > 0:
            self.log.delete("1.0", f"1.0+{excess}c")
        self.log.see("end")
        self.log.configure(state="disabled")
