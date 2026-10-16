"""DCC Task WF-2: workflow execution -- send an already-approved task from a workflow_plan.py
(WF-1) plan to the Orchestrator, one task at a time, respecting depends_on and plan order. This
module only decides *whether* and *how* to call the existing Orchestrator entry point (Task 18's
own reports_create_and_start.create_and_start / tools.ai_orchestrator.orchestrator.start_run) and
records the fixed-word outcome; it never approves, pushes, builds, updates or releases anything,
and it stops exactly where Task 14.5/18 already stop: a candidate branch exists.

Security posture (same family as workflow_plan.py / reports_auto_start.py / reports_auto_progress.py):
 - A task's title/body and any AI output are untrusted text: they are never used to decide which
   command, path or repository to touch. The target repository is decided only from the task's own
   `repo_key` plus DCC's own registry (tools.ai_orchestrator.orchestrator.resolve_repo_dir_for_app),
   exactly like every other DCC Task 14+ module -- the task body is only ever handed to the Main/
   Reviewer AI as free text and to the existing spec-file machinery (reports_inbox.create_spec_file,
   via reports_create_and_start.create_and_start) to extract already-approved acceptance criteria.
 - Automatic execution requires the shared global stop switch (reports_auto.AutoModeConfig.enabled,
   reused unchanged) and a *separate* per-plan permission (WorkflowRunnerConfig.plans, initial OFF
   for every plan) to both be ON, re-read at the top of a cycle, again right after a task is picked,
   and a third time inside a guard wired into the real Orchestrator start itself (same three-layer
   pattern reports_auto_start.run_auto_start_once introduced).
 - approve / push / BUILD / UPDATE / RELEASE are never called anywhere in this module. A
   `candidate_ready` task only ever becomes `landed` after confirming, from DCC's own existing
   candidate records (candidate.py: RUN_DEV result, human approval, push), that a human already
   approved and pushed exactly that candidate -- never decided by this module itself.
 - Every persisted record (daily count, per-task run association, run log) holds only fixed
   words/numbers (plan_id/task_id -- already-validated identifiers, never free text -- run
   identifiers DCC itself generated, and an outcome code checked by _safe_reason against the
   closed _ALLOWED_REASONS vocabulary, not merely shape, before being stored) -- never a task
   body, an AI's own output, a path or exception text. There is no separate "already started"
   index either: the plan file's own task status (approved -> running, a compare-and-set) is the
   one durable "started" marker -- see WorkflowRunnerState's own docstring for why a second one
   would be actively wrong.
"""
from __future__ import annotations

import copy
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import reports_auto as auto
from . import reports_auto_progress as progress
from . import reports_auto_start as start
from . import reports_create_and_start as cas
from . import workflow_plan as wf

DEFAULT_DAILY_LIMIT = 5
WORKFLOW_RUNNER_INTERVAL_SECONDS = 5 * 60

LIMIT_REACHED_TEXT = "本日の計画の自動実行の上限に達しました"

STATUS_STARTUP_BLOCKED = "startup_blocked"
STATUS_DISABLED = "disabled"
STATUS_LIMIT_REACHED = "limit_reached"
STATUS_DONE = "done"

RUN_LOG_MAX_FILES = 100

# A task's own run never starting (spec file / repo resolution / Tests / Orchestrator start all
# failed before any run.json existed) is recorded with this one fixed internal code -- never
# reports_create_and_start.StartResult.reason's own Japanese sentence.
REASON_START_FAILED = "START_FAILED"
REASON_UNKNOWN = "UNKNOWN"

# The closed vocabulary _safe_reason accepts -- every `code` tools.ai_orchestrator.engine.py /
# common.py / runstate.py itself can put in a finished run's final_result (NeedsHuman/
# OrchestratorError subclasses' own fixed `code` attribute, reached via orchestrator.py's
# worker_main finishing the run with exc.code), plus this module's own two synthetic codes above.
# A shape-valid but undefined code (whether forged by untrusted AI output or simply a future code
# this set has not been updated for yet) is deliberately rejected to REASON_UNKNOWN rather than
# accepted on shape alone (C: 理由は固定語の集合に限定) -- a regex can never give that guarantee.
_ALLOWED_REASONS = frozenset((
    REASON_START_FAILED, REASON_UNKNOWN,
    # engine.py: NeedsHuman/SafetyViolation codes raised while a run is actually executing.
    "MAX_RUNTIME", "PROVIDER_QUOTA", "PROVIDER_AUTH", "PROVIDER_ERROR", "REVIEW_BUDGET",
    "MAIN_BUDGET", "MAIN_TURN_LIMIT", "MAIN_NO_PROGRESS", "TASK_BLOCKED", "NO_CHANGES",
    "TEST_RUNNER_PROBLEM", "SAME_FAILURE_REPEATED", "MAX_REPAIR_ITERATIONS", "REVIEWER_NEEDS_HUMAN",
    "NO_PROGRESS", "MAX_REVIEW_ROUNDS", "REVIEW_UNPARSABLE", "REVIEW_LOOP", "SAFETY_VIOLATION",
    "NEEDS_HUMAN",
    # common.py/runstate.py: OrchestratorError codes a command/git/worker failure during the run
    # can surface as (orchestrator.py's generic except falls back to exc.code, or "ORCHESTRATOR_
    # ERROR" for anything without one), plus the stop/user-safety and reconciliation codes.
    "COMMAND_NOT_FOUND", "COMMAND_TIMEOUT", "PROCESS_START_FAILED", "GIT_FAILED",
    "ILLEGAL_TRANSITION", "LOCK_UNAVAILABLE", "WORKER_LOST", "USER_SAFETY_STOP",
    "ORCHESTRATOR_ERROR",
))

# tools.ai_orchestrator.runstate's own fixed stage vocabulary -> the task status this module sets.
_TERMINAL_STAGE_TO_STATUS = {
    "completed": "candidate_ready",
    "needs_human": "needs_human",
    "failed": "failed",
    "stopped": "failed",
}

_BLOCKING_STATUSES = frozenset(("running", "candidate_ready", "failed", "needs_human"))


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "workflow_runner"


def workflow_runner_config_path() -> Path:
    return _root() / "config.json"


def _daily_count_path() -> Path:
    return _root() / "daily_count.json"


def records_root() -> Path:
    return _root() / "records"


def run_log_root() -> Path:
    return _root() / "run_log"


# --------------------------------------------------------------------------- 仕様1: 計画ごとの許可

@dataclass(frozen=True)
class WorkflowRunnerConfig:
    """plans: plan_id -> 計画の自動実行の許可（初期値、未記載は全計画OFF）。daily_limit: 1日あたりの
    自動実行の開始回数（初期値5）。The global stop switch is deliberately *not* duplicated here -- it
    is reports_auto.AutoModeConfig.enabled, read fresh wherever this module needs it."""

    plans: dict = field(default_factory=dict)
    daily_limit: int = DEFAULT_DAILY_LIMIT


def plan_auto_run_allowed(global_config: "auto.AutoModeConfig", runner_config: WorkflowRunnerConfig,
                           plan_id: str) -> bool:
    """C1: the shared global switch and this plan's own permission must both be ON."""
    return bool(global_config.enabled) and bool(runner_config.plans.get(plan_id, False))


def load_workflow_runner_config(path: Path | None = None) -> WorkflowRunnerConfig:
    """Never raises: a missing or unreadable/corrupt file degrades to all-OFF defaults."""
    data = start._read_json(path if path is not None else workflow_runner_config_path())
    if data is None:
        return WorkflowRunnerConfig()
    plans_raw = data.get("plans")
    plans = {str(k): bool(v) for k, v in plans_raw.items()} if isinstance(plans_raw, dict) else {}
    try:
        daily_limit = int(data.get("daily_limit", DEFAULT_DAILY_LIMIT))
    except (TypeError, ValueError):
        daily_limit = DEFAULT_DAILY_LIMIT
    return WorkflowRunnerConfig(plans=plans, daily_limit=daily_limit)


def save_workflow_runner_config(config: WorkflowRunnerConfig, path: Path | None = None) -> None:
    target = path if path is not None else workflow_runner_config_path()
    start._write_json_atomic(target, {"plans": dict(config.plans), "daily_limit": config.daily_limit})


def set_plan_auto_run_allowed(plan_id: str, allowed: bool, *, path: Path | None = None) -> WorkflowRunnerConfig:
    """Read-modify-write one plan's permission (人がONにする操作。画面は次のTask)."""
    config = load_workflow_runner_config(path)
    plans = dict(config.plans)
    plans[plan_id] = bool(allowed)
    updated = WorkflowRunnerConfig(plans=plans, daily_limit=config.daily_limit)
    save_workflow_runner_config(updated, path)
    return updated


# --------------------------------------------------------------------------- 仕様2: 1日の上限・開始済み

class WorkflowRunnerState:
    """Held by the caller for one DCC process's lifetime (same convention as
    reports_auto_progress.ProgressState). `daily_count` is authoritative in memory once
    `seed_startup` has succeeded at least once; persistence is best-effort and only ever a mirror --
    a write failure never changes what this process itself already decided (C10). There is no
    separate "already started" index: the plan file's own task status is that durable marker --
    starting flips `approved` to `running` (an atomic compare-and-set, see _set_task_status), which
    `_eligible_task` never selects again, and only a human's own re-approval (workflow_plan.py's
    existing failed/needs_human -> approved transition) ever makes the task selectable a second
    time (仕様4: 再試行は人がapprovedに戻したときだけ) -- a plain in-memory/persisted "started" set
    keyed by task id would either duplicate that guarantee or (if it survived a human's own
    re-approval) silently block a retry the spec requires to work."""

    def __init__(self, *, daily_count_path: Path | None = None) -> None:
        self._daily_count_path = daily_count_path
        self._daily_date: str | None = None
        self._daily_count = 0
        self.startup_seeded = False
        self._lock = threading.Lock()
        # (plan_id, task_id) -> {"run_id", "reason", "candidate_sha"}: this process's own in-memory
        # mirror of _record_path's persisted file, so a *temporary* save failure for that one
        # on-disk record (C: 保存失敗からの結果回収) never loses the task<->run association --
        # _refresh_hot_task falls back to this, and retries the persisted save, until it succeeds.
        self._hot_runs: dict[tuple[str, str], dict] = {}

    def remember_run(self, plan_id: str, task_id: str, *, run_id: str, reason: str = "",
                     candidate_sha: str = "") -> None:
        with self._lock:
            self._hot_runs[(plan_id, task_id)] = {
                "run_id": run_id, "reason": reason, "candidate_sha": candidate_sha}

    def hot_run(self, plan_id: str, task_id: str) -> dict | None:
        with self._lock:
            record = self._hot_runs.get((plan_id, task_id))
            return dict(record) if record is not None else None

    def forget_run(self, plan_id: str, task_id: str) -> None:
        with self._lock:
            self._hot_runs.pop((plan_id, task_id), None)

    def seed_startup(self, today: str) -> bool:
        """C11: must succeed (an existing file parses, or is simply absent) before anything may
        start. Idempotent and safe to call every cycle: once True, never re-reads disk again."""
        with self._lock:
            if self.startup_seeded:
                return True
            try:
                count = progress._read_daily_count_strict(today, self._daily_count_path)
            except Exception:  # noqa: BLE001 - any parse/OS trouble blocks until a later success
                return False
            self._daily_date, self._daily_count = today, count
            self.startup_seeded = True
            return True

    def daily_count(self, today: str) -> int:
        with self._lock:
            return self._daily_count if self._daily_date == today else 0

    def limit_reached(self, today: str, limit: int) -> bool:
        return self.daily_count(today) >= limit

    def record_daily_attempt(self, today: str) -> int:
        with self._lock:
            total = (self._daily_count if self._daily_date == today else 0) + 1
            self._daily_date, self._daily_count = today, total
        if self._daily_count_path is not None:
            try:
                start._write_json_atomic(self._daily_count_path, {"date": today, "count": total})
            except OSError:  # noqa: BLE001 - C10: a save failure must never undo the count above
                pass
        return total


# --------------------------------------------------------------------------- 仕様2/3: タスクのRun対応付け記録

def _record_path(plan_id: str, task_id: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else records_root()
    return base / start._hash(plan_id) / f"{start._hash(task_id)}.json"


def _load_record(plan_id: str, task_id: str, *, root: Path | None = None) -> dict | None:
    return start._read_json(_record_path(plan_id, task_id, root=root))


def _save_record(plan_id: str, task_id: str, *, run_id: str, reason: str, candidate_sha: str,
                  root: Path | None = None) -> None:
    try:
        start._write_json_atomic(_record_path(plan_id, task_id, root=root),
                                  {"run_id": run_id, "reason": reason, "candidate_sha": candidate_sha})
    except OSError:  # noqa: BLE001 - best-effort: never affects the outcome already decided (C10)
        pass


# --------------------------------------------------------------------------- 仕様5: 実行ごとの記録

def _write_run_log_entry(*, plan_id: str, task_id: str, result: str, reason: str = "", run_id: str = "",
                          log_dir: Path | None = None) -> None:
    """One fixed-word/number record per cycle event -- never a task body, an AI's own output, a
    path, or exception text. Kept to ~RUN_LOG_MAX_FILES recent entries."""
    try:
        directory = log_dir if log_dir is not None else run_log_root()
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        lines = [
            f"日時: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"計画の識別子: {plan_id or '(なし)'}",
            f"タスクの識別子: {task_id or '(なし)'}",
            f"結果: {result}",
            f"理由: {reason or '(なし)'}",
            f"Runの識別子: {run_id or '(なし)'}",
        ]
        content = "\n".join(lines)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        seq = start._next_log_sequence()
        base_name = f"{stamp}-{seq:010d}.log"
        name = base_name
        counter = 2
        while True:
            path = directory / name
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                name = f"{stamp}-{seq:010d}-{counter}.log"
                counter += 1
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            break
        start._prune_old_logs(directory, RUN_LOG_MAX_FILES)
    except Exception:  # noqa: BLE001 - logging must never affect the outcome already computed
        pass


def _safe_reason(code) -> str:
    return code if isinstance(code, str) and code in _ALLOWED_REASONS else REASON_UNKNOWN


# --------------------------------------------------------------------------- 仕様1: 実行してよいタスク

def _eligible_task(plan: dict) -> dict | None:
    """First (plan-order) `approved` task whose depends_on are all `landed`, or None when the plan
    is paused (a running/candidate_ready/failed/needs_human task already exists, C3/C12) or no
    task qualifies yet (C2)."""
    if any(t["status"] in _BLOCKING_STATUSES for t in plan["tasks"]):
        return None
    landed = {t["task_id"] for t in plan["tasks"] if t["status"] == "landed"}
    for task in plan["tasks"]:
        if task["status"] == "approved" and all(dep in landed for dep in task["depends_on"]):
            return task
    return None


def _set_task_status(plan_id: str, task_id: str, *, expected: str, new: str, root: Path | None,
                      registered_keys) -> bool:
    """Compare-and-set against the plan file's own task status, bypassing workflow_plan's
    human-actor proposal pipeline (running/candidate_ready/landed/failed/needs_human are executor-
    owned targets with no TRANSITIONS entry). Goes through workflow_plan.update_plan -- the one
    shared load/mutate/save serialization point (see its own docstring) -- so a concurrent human
    change (e.g. cancel) is never silently overwritten by a lost update, and advances the plan's
    own revision on every executor-owned change too, so a human's own stale-base_revision proposal
    is still rejected by apply_proposal's WORKFLOW_STALE check even when only this module changed
    the plan since the human last loaded it. Returns False without writing when the task is no
    longer in `expected` or the plan cannot be read/written."""
    changed = False

    def mutate(plan):
        nonlocal changed
        task = next((t for t in plan["tasks"] if t["task_id"] == task_id), None)
        if task is None or task["status"] != expected:
            return None
        updated = copy.deepcopy(plan)
        for t in updated["tasks"]:
            if t["task_id"] == task_id:
                t["status"] = new
        updated["revision"] += 1
        changed = True
        return updated

    try:
        wf.update_plan(plan_id, mutate, root=root, registered_keys=registered_keys)
    except wf.WorkflowStorageError:
        return False
    return changed


# --------------------------------------------------------------------------- default collaborators

@dataclass(frozen=True)
class _TaskShim:
    """Duck-typed stand-in for reports_inbox.Report: reports_create_and_start.create_and_start
    only ever reads .app_key (repo resolution/spec target_repo) and .identity (spec file naming)
    off its `report` argument, and hands the same object, unread, to task_text_fn -- so this is
    enough to reuse Task 18's own entry point unchanged for a workflow_plan task."""

    app_key: str
    identity: tuple


def _default_resolve_repo_dir(repo_key: str) -> Path | None:
    from tools.ai_orchestrator.orchestrator import resolve_repo_dir_for_app

    return resolve_repo_dir_for_app(repo_key)


def _default_busy(repo_name: str) -> bool:
    return False


# Standalone (non-App) fallback reservation, mirroring reports_auto_progress._default_reserve/
# _default_release exactly: App.* _start_workflow_runner_loop always wires its own
# ACTIVE_OPERATIONS-backed reserve_fn/release_fn instead (see app.py), so this pair only matters
# when run_workflow_runner_once is used standalone (tests, a future non-GUI caller).
_DEFAULT_RESERVATIONS: set[str] = set()
_DEFAULT_RESERVATIONS_LOCK = threading.Lock()


def _default_reserve(repo_name: str) -> object | None:
    with _DEFAULT_RESERVATIONS_LOCK:
        if repo_name in _DEFAULT_RESERVATIONS:
            return None
        _DEFAULT_RESERVATIONS.add(repo_name)
        return repo_name


def _default_release(repo_name: str, token: object | None) -> None:
    if token is None:
        return
    with _DEFAULT_RESERVATIONS_LOCK:
        _DEFAULT_RESERVATIONS.discard(repo_name)


def _default_repo_run_blocked(repo: str) -> bool:
    """Orchestrator run check (1 repo / 1 run), mirroring reports_auto_start's own active_runs_fn
    but stricter (C4: 確認できないときも進まない). runstate.list_runs() cannot be reused here: it
    swallows a genuine enumeration failure (OSError iterating the runs root) into an empty list,
    and silently drops any run whose run.json is unreadable (record is None) -- both look exactly
    like "confirmed no runs" to a caller, which is the one thing C4 forbids. This enumerates the
    runs root itself so either case blocks instead."""
    from tools.ai_orchestrator import runstate

    root = runstate.runs_root()
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()]
    except FileNotFoundError:
        return False  # the runs root itself has never been created -- genuinely nothing has run
    except OSError:  # noqa: BLE001 - C4: enumeration failed, cannot confirm empty
        return True

    wanted = runstate._norm(repo)
    blocking = (runstate.LIVE_RUNNING, runstate.LIVE_STARTING, runstate.LIVE_UNRESPONSIVE, runstate.LIVE_UNKNOWN)
    for directory in dirs:
        try:
            info = runstate.inspect_run(directory)
        except Exception:  # noqa: BLE001 - C4: cannot confirm this run is unrelated/safe
            return True
        record = info["record"]
        if record is None:
            return True  # C4: unreadable run.json -- cannot rule out this repo
        if runstate._norm(record.get("repo")) != wanted:
            continue
        if info["liveness"] in blocking:
            return True
    return False


def _default_create_and_start(shim, criteria_lines, *, main_agent, review_agent, resolve_repo_dir, task_text_fn,
                               start_run=None):
    return cas.create_and_start(
        shim, criteria_lines, main_agent=main_agent, review_agent=review_agent,
        resolve_repo_dir=resolve_repo_dir, task_text_fn=task_text_fn, start_run=start_run)


def _default_run_lookup(run_id: str) -> dict | None:
    from tools.ai_orchestrator import runstate

    return runstate.read_record(runstate.runs_root() / run_id)


def _default_is_landed(repo_dir: Path, run_id: str, candidate_sha: str) -> bool:
    """DCC's own existing candidate record (candidate.py): landed only when the live Orchestrator
    candidate is still this exact run/sha, it passed RUN_DEV + human approval, and it was pushed --
    never decided by this module itself. Any uncertainty (unreadable state, a superseding run)
    degrades to "not landed" (candidate_ready stays, retried next cycle)."""
    from . import candidate as candidate_mod

    try:
        current = candidate_mod.latest_candidate(repo_dir)
    except Exception:  # noqa: BLE001
        return False
    if current is None or current.run_id != run_id:
        return False
    if candidate_sha and not current.sha.lower().startswith(candidate_sha.lower()):
        return False
    try:
        state = candidate_mod.load_state(current)
    except Exception:  # noqa: BLE001
        return False
    if not candidate_mod.approval_valid(current, state):
        return False
    push = state.get("push")
    return isinstance(push, dict) and str(push.get("sha", "")).lower() == current.sha.lower()


# --------------------------------------------------------------------------- 仕様3: 結果の取り込み

def _hot_record(plan_id: str, task_id: str, *, state: "WorkflowRunnerState", records_dir) -> dict | None:
    """This process's own in-memory association, when present, always wins over the persisted
    file: remember_run is only ever called for the *current* attempt (a human re-approval starts a
    new run with its own fresh remember_run call; the previous attempt's association was already
    forgotten before that, or is about to be overwritten in memory right now), so it can never be
    older than whatever is on disk -- but a disk record can absolutely be older, when this exact
    attempt's own _save_record call failed right after starting (C: 保存失敗からの結果回収) and the
    disk still holds a *previous* attempt's stale record (e.g. an earlier failed run, before a
    human re-approved and this attempt began). Falling back to disk-first would then resolve the
    wrong run. Only when this process has no memory of the task at all (e.g. just restarted) does
    the persisted file apply. Retries the save on every call so storage coming back finishes the
    recovery without this module ever starting the task a second time (the plan's own status, not
    this record, is what _eligible_task checks)."""
    remembered = state.hot_run(plan_id, task_id)
    if remembered is not None:
        _save_record(plan_id, task_id, run_id=remembered["run_id"], reason=remembered.get("reason", ""),
                     candidate_sha=remembered.get("candidate_sha", ""), root=records_dir)
        return remembered
    return _load_record(plan_id, task_id, root=records_dir)


def _refresh_hot_task(plan_id: str, plan: dict, *, state: "WorkflowRunnerState", records_dir, plans_root,
                       registered_keys, resolve_repo_dir, run_lookup_fn, is_landed_fn, log_dir) -> None:
    """The plan's single running/candidate_ready task (by construction there is never more than
    one -- see _eligible_task), reflected into a fixed-word status, or left untouched when the Run
    record / candidate record cannot be read (C7/C8: 次の周期でもう一度見る)."""
    hot = next((t for t in plan["tasks"] if t["status"] in ("running", "candidate_ready")), None)
    if hot is None:
        return
    record = _hot_record(plan_id, hot["task_id"], state=state, records_dir=records_dir)
    if record is None or not record.get("run_id"):
        return
    try:
        repo_dir = resolve_repo_dir(hot["repo_key"])
    except Exception:  # noqa: BLE001 - registry trouble: wait, do not guess
        repo_dir = None

    if hot["status"] == "candidate_ready":
        if repo_dir is None:
            return
        try:
            landed = bool(is_landed_fn(repo_dir, record["run_id"], record.get("candidate_sha", "")))
        except Exception:  # noqa: BLE001
            landed = False
        if landed and _set_task_status(plan_id, hot["task_id"], expected="candidate_ready", new="landed",
                                        root=plans_root, registered_keys=registered_keys):
            state.forget_run(plan_id, hot["task_id"])
            _write_run_log_entry(plan_id=plan_id, task_id=hot["task_id"], result="landed",
                                  run_id=record["run_id"], log_dir=log_dir)
        return

    try:
        run_record = run_lookup_fn(record["run_id"])
    except Exception:  # noqa: BLE001 - C7: 読めないときは次の周期でもう一度見る
        run_record = None
    if not isinstance(run_record, dict):
        return
    new_status = _TERMINAL_STAGE_TO_STATUS.get(run_record.get("stage"))
    if new_status is None:
        return  # still active, or an unrecognized stage -- never guess
    final = run_record.get("final_result") or {}
    if new_status == "candidate_ready":
        candidate_sha = str(run_record.get("candidate_sha") or "")[:12]
        reason = ""
    else:
        candidate_sha = ""
        reason = _safe_reason(final.get("code"))
    if _set_task_status(plan_id, hot["task_id"], expected="running", new=new_status,
                        root=plans_root, registered_keys=registered_keys):
        state.remember_run(plan_id, hot["task_id"], run_id=record["run_id"], reason=reason,
                           candidate_sha=candidate_sha)
        _save_record(plan_id, hot["task_id"], run_id=record["run_id"], reason=reason,
                     candidate_sha=candidate_sha, root=records_dir)
        if new_status != "candidate_ready":
            state.forget_run(plan_id, hot["task_id"])  # terminal and non-candidate: never revisited
        _write_run_log_entry(plan_id=plan_id, task_id=hot["task_id"], result=new_status, reason=reason,
                             run_id=record["run_id"], log_dir=log_dir)


# --------------------------------------------------------------------------- 仕様1/2: 1タスク分の開始

def _current_global(path, fallback):
    return fallback if path is None else auto.load_auto_mode_config(path)


def _current_runner(path, fallback):
    return fallback if path is None else load_workflow_runner_config(path)


def _start_eligible_task(plan_id: str, *, global_config, global_config_path, runner_config,
                          runner_config_path, state: WorkflowRunnerState, today: str, plans_root,
                          registered_keys, records_dir, resolve_repo_dir, busy_fn, repo_run_blocked_fn,
                          reserve_fn, release_fn, create_and_start_fn, start_run_fn, default_main_agent,
                          default_review_agent, log_dir, stop_event) -> None:
    try:
        plan = wf.load_plan(plan_id, root=plans_root, registered_keys=registered_keys)
    except wf.WorkflowStorageError:
        return

    task = _eligible_task(plan)
    if task is None:
        return

    # C5: re-confirm right before starting -- a human (or DCC shutting down) may have flipped
    # either switch, or the daily limit may have just been reached, since the top-of-cycle check.
    if stop_event is not None and stop_event.is_set():
        return
    latest_global = _current_global(global_config_path, global_config)
    latest_runner = _current_runner(runner_config_path, runner_config)
    if not plan_auto_run_allowed(latest_global, latest_runner, plan_id):
        return
    if state.limit_reached(today, latest_runner.daily_limit):
        return

    try:
        repo_dir = resolve_repo_dir(task["repo_key"])
    except Exception:  # noqa: BLE001 - registry trouble: wait, do not guess
        repo_dir = None
    if repo_dir is None:
        return  # cannot resolve this cycle -- try again later, never guess a path

    try:
        blocked = bool(repo_run_blocked_fn(str(repo_dir))) or bool(busy_fn(repo_dir.name))
    except Exception:  # noqa: BLE001 - C4: 確認できないときも進まない
        blocked = True
    if blocked:
        return

    # Close the TOCTOU gap between the busy check above and the real start below: hold this
    # repo's own exclusive-operation reservation for that whole window, exactly like
    # reports_auto_progress._process_candidate holds one around its own RUN_DEV/push/build
    # sequence -- so a manual RUN_DEV/PUSH/BUILD cannot slip in between the two.
    token = reserve_fn(repo_dir.name)
    if token is None:
        return  # reservation contended -- try again next cycle, never guess
    try:
        # C10: 同じタスクは自動で開始するのは1回だけ -- this compare-and-set is the one
        # authoritative "started" marker (see WorkflowRunnerState's own docstring): it never
        # re-fires for this task until a human flips it back to approved.
        if not _set_task_status(plan_id, task["task_id"], expected="approved", new="running",
                                root=plans_root, registered_keys=registered_keys):
            return  # plan changed under us (e.g. a human cancelled it) -- try again next cycle

        # 回数と開始済みの印は、記録の保存の成否にかかわらず、開始の前に必ず数える: reserved here,
        # before the real entry point is ever called, so an abnormal exit out of
        # create_and_start_fn/start_run_fn below (not just an ordinary StartResult(False, ...))
        # can never lose this attempt's place in the day's quota, and a fake entry point can
        # observe the count already reflecting this attempt before it returns. `reserved_total` is
        # this attempt's own 1-based position in today's count (the value *after* reserving it) --
        # guarded_start_run below must compare against this, not against a fresh daily_count() read
        # (which would always include this same reservation and reject every attempt, even the
        # first one under daily_limit=1: daily_count() >= limit is already true the instant this
        # attempt's own reservation lands on the limit).
        reserved_total = state.record_daily_attempt(today)

        from tools.ai_orchestrator import review as review_mod

        criteria_lines = [c["text"] for c in
                          review_mod.criteria_from_acceptance(review_mod.extract_acceptance(task["body"]))]
        main_agent = task.get("main_ai") or default_main_agent
        review_agent = task.get("reviewer_ai") or default_review_agent

        def guarded_start_run(**start_run_kwargs):
            """C5: the actual last check before the Orchestrator starts, mirroring
            reports_auto_start._guarded_start_run -- raises the same ActiveRunExists the real
            Orchestrator itself raises on a genuine 1-repo-1-run race, so create_and_start_fn's
            existing REASON_ALREADY_RUNNING branch handles both cases identically."""
            from tools.ai_orchestrator.runstate import ActiveRunExists

            if stop_event is not None and stop_event.is_set():
                raise ActiveRunExists("", "guard")
            g = _current_global(global_config_path, latest_global)
            r = _current_runner(runner_config_path, latest_runner)
            if not plan_auto_run_allowed(g, r, plan_id):
                raise ActiveRunExists("", "guard")
            # This attempt's own slot (reserved_total) is already counted -- only reject when that
            # reserved position itself exceeds the (possibly just-lowered) limit, never merely
            # because the reservation brought the count up to the limit.
            if reserved_total > r.daily_limit:
                raise ActiveRunExists("", "guard")
            return start_run_fn(**start_run_kwargs)

        shim = _TaskShim(app_key=task["repo_key"], identity=(plan_id, task["task_id"]))
        task_body = task["body"]
        try:
            result = create_and_start_fn(
                shim, criteria_lines, main_agent=main_agent, review_agent=review_agent,
                resolve_repo_dir=resolve_repo_dir, task_text_fn=lambda _s, _b=task_body: _b,
                start_run=guarded_start_run,
            )
        except Exception:  # noqa: BLE001 - the real entry point must never leave the task stuck
            # "running" with nothing recorded: an exception here is exactly as final as an
            # ordinary StartResult(False, ...) failure, handled identically below.
            result = cas.StartResult(False, REASON_START_FAILED)

        if not result.ok and result.reason == cas.REASON_ALREADY_RUNNING:
            # Either a genuine race against our own pre-check above, or this cycle's own guard
            # aborting: nothing was actually started -- undo the status flip so the task is picked
            # up again next cycle. The daily slot reserved above is still spent either way (the
            # count happens unconditionally before the attempt, never only on a clean outcome).
            _set_task_status(plan_id, task["task_id"], expected="running", new="approved",
                             root=plans_root, registered_keys=registered_keys)
            return

        if result.ok:
            run_id = result.run_dir.name if result.run_dir is not None else ""
            state.remember_run(plan_id, task["task_id"], run_id=run_id, reason="", candidate_sha="")
            _save_record(plan_id, task["task_id"], run_id=run_id, reason="", candidate_sha="",
                         root=records_dir)
            _write_run_log_entry(plan_id=plan_id, task_id=task["task_id"], result="running", run_id=run_id,
                                 log_dir=log_dir)
            return

        _set_task_status(plan_id, task["task_id"], expected="running", new="failed",
                         root=plans_root, registered_keys=registered_keys)
        _save_record(plan_id, task["task_id"], run_id="", reason=REASON_START_FAILED, candidate_sha="",
                    root=records_dir)
        _write_run_log_entry(plan_id=plan_id, task_id=task["task_id"], result="failed",
                             reason=REASON_START_FAILED, log_dir=log_dir)
    finally:
        release_fn(repo_dir.name, token)


# --------------------------------------------------------------------------- 実行本体

@dataclass(frozen=True)
class WorkflowRunnerCycleOutcome:
    status: str  # STATUS_* above
    message: str = ""


def run_workflow_runner_once(
    *,
    state: WorkflowRunnerState,
    global_config: "auto.AutoModeConfig | None" = None,
    global_config_path: Path | None = None,
    runner_config: WorkflowRunnerConfig | None = None,
    runner_config_path: Path | None = None,
    today: str | None = None,
    plans_root: Path | None = None,
    registered_keys=None,
    records_dir: Path | None = None,
    resolve_repo_dir: Callable[[str], Path | None] | None = None,
    busy_fn: Callable[[str], bool] | None = None,
    repo_run_blocked_fn: Callable[[str], bool] | None = None,
    reserve_fn: Callable[[str], object | None] | None = None,
    release_fn: Callable[[str, object | None], None] | None = None,
    create_and_start_fn: Callable[..., object] | None = None,
    start_run_fn: Callable[..., Path] | None = None,
    run_lookup_fn: Callable[[str], dict | None] | None = None,
    is_landed_fn: Callable[[Path, str, str], bool] | None = None,
    default_main_agent: str | None = None,
    default_review_agent: str | None = None,
    log_dir: Path | None = None,
    stop_event: threading.Event | None = None,
) -> WorkflowRunnerCycleOutcome:
    """Run one cycle over every plan this DCC process knows the permission for (runner_config.plans'
    own keys -- there is no other registry of plan ids). Each plan is considered independently
    (仕様1: 他の計画を妨げない): one plan paused by a failed/needs_human task, or waiting on a busy
    repository, never stops another plan's own eligible task the same cycle. The global stop switch
    and the shared daily limit are the two exceptions that stop further *starts* outright (reflecting
    already-started results, below, is never gated by either -- 仕様3)."""
    from tools.ai_orchestrator.providers import DEFAULT_MAIN_AGENT, DEFAULT_REVIEW_AGENT

    today = today if today is not None else auto.today_str()
    if not state.seed_startup(today):
        return WorkflowRunnerCycleOutcome(STATUS_STARTUP_BLOCKED)

    global_config = global_config if global_config is not None else auto.load_auto_mode_config(global_config_path)
    runner_config = runner_config if runner_config is not None else load_workflow_runner_config(runner_config_path)
    registered_keys = registered_keys if registered_keys is not None else wf.registered_repo_keys()

    resolve_repo_dir = resolve_repo_dir or _default_resolve_repo_dir
    busy_fn = busy_fn or _default_busy
    repo_run_blocked_fn = repo_run_blocked_fn or _default_repo_run_blocked
    reserve_fn = reserve_fn or _default_reserve
    release_fn = release_fn or _default_release
    create_and_start_fn = create_and_start_fn or _default_create_and_start
    start_run_fn = start_run_fn or cas._default_start_run
    run_lookup_fn = run_lookup_fn or _default_run_lookup
    is_landed_fn = is_landed_fn or _default_is_landed
    default_main_agent = default_main_agent or DEFAULT_MAIN_AGENT
    default_review_agent = default_review_agent or DEFAULT_REVIEW_AGENT

    # 仕様3: independent of whether anything is started below -- resolving an already-started
    # task's result is never gated by either switch or the daily limit.
    for plan_id in list(runner_config.plans):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            plan = wf.load_plan(plan_id, root=plans_root, registered_keys=registered_keys)
        except wf.WorkflowStorageError:
            continue  # unreadable/corrupt -- try again next cycle, never guess
        _refresh_hot_task(plan_id, plan, state=state, records_dir=records_dir, plans_root=plans_root,
                          registered_keys=registered_keys, resolve_repo_dir=resolve_repo_dir,
                          run_lookup_fn=run_lookup_fn, is_landed_fn=is_landed_fn, log_dir=log_dir)

    if not global_config.enabled:
        return WorkflowRunnerCycleOutcome(STATUS_DISABLED)
    if state.limit_reached(today, runner_config.daily_limit):
        _write_run_log_entry(plan_id="", task_id="", result=LIMIT_REACHED_TEXT, log_dir=log_dir)
        return WorkflowRunnerCycleOutcome(STATUS_LIMIT_REACHED, LIMIT_REACHED_TEXT)

    for plan_id, allowed in runner_config.plans.items():
        if stop_event is not None and stop_event.is_set():
            break
        cur_global = _current_global(global_config_path, global_config)
        if not cur_global.enabled:
            break  # 仕様1: 全体の停止スイッチOFFは即座に全体を止める
        if state.limit_reached(today, runner_config.daily_limit):
            break  # 共有の1日の上限
        if not allowed:
            continue  # この計画は対象外。他の計画は妨げない
        _start_eligible_task(
            plan_id, global_config=cur_global, global_config_path=global_config_path,
            runner_config=runner_config, runner_config_path=runner_config_path, state=state, today=today,
            plans_root=plans_root, registered_keys=registered_keys, records_dir=records_dir,
            resolve_repo_dir=resolve_repo_dir, busy_fn=busy_fn, repo_run_blocked_fn=repo_run_blocked_fn,
            reserve_fn=reserve_fn, release_fn=release_fn,
            create_and_start_fn=create_and_start_fn, start_run_fn=start_run_fn,
            default_main_agent=default_main_agent, default_review_agent=default_review_agent,
            log_dir=log_dir, stop_event=stop_event,
        )

    return WorkflowRunnerCycleOutcome(STATUS_DONE)
