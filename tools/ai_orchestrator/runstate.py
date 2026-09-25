"""Run state machine, durable run record, liveness inspection, repo lock and stop control.

A run is a directory under ``<state_root>/runs/<run_id>`` written only by that run's
own worker process (plus the explicit stop / reconcile paths in this module):

    run.json         authoritative record (stage, counters, history, result ...)
    heartbeat.json   {"ts", "pid", "token", "stage"} refreshed every few seconds
    control.json     client requests (currently: stop)
    events.log       human readable progress log
    task.md          the TaskSpec

DCC (and anything else) is only a client of these files: it never owns the run's
lifetime. A PID alone is never treated as proof that a run is alive.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .common import (
    OrchestratorError, now_iso, pid_matches, process_start_token, read_json, slugify,
    state_root, terminate_pid_tree, write_json_atomic,
)

SCHEMA_VERSION = 2

# --- stages ------------------------------------------------------------------------
CREATED = "created"
PREFLIGHT = "preflight"
IMPLEMENTING = "implementing"
TESTING = "testing"
REPAIRING = "repairing"
REVIEWING = "reviewing"
FINALIZING = "finalizing"
COMPLETED = "completed"
NEEDS_HUMAN = "needs_human"
STOPPING = "stopping"
STOPPED = "stopped"
FAILED = "failed"

TERMINAL_STAGES = frozenset({COMPLETED, NEEDS_HUMAN, STOPPED, FAILED})
ACTIVE_STAGES = frozenset({CREATED, PREFLIGHT, IMPLEMENTING, TESTING, REPAIRING, REVIEWING, FINALIZING, STOPPING})
_ANY_EXIT = {NEEDS_HUMAN, FAILED, STOPPING}
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({PREFLIGHT, STOPPED} | _ANY_EXIT),
    PREFLIGHT: frozenset({IMPLEMENTING} | _ANY_EXIT),
    IMPLEMENTING: frozenset({TESTING} | _ANY_EXIT),
    TESTING: frozenset({REPAIRING, REVIEWING} | _ANY_EXIT),
    REPAIRING: frozenset({TESTING} | _ANY_EXIT),
    REVIEWING: frozenset({REPAIRING, FINALIZING} | _ANY_EXIT),
    FINALIZING: frozenset({COMPLETED} | _ANY_EXIT),
    STOPPING: frozenset({STOPPED, FAILED}),
    COMPLETED: frozenset(), NEEDS_HUMAN: frozenset(), STOPPED: frozenset(), FAILED: frozenset(),
}

# liveness of a run as seen by a client
LIVE_FINISHED = "finished"
LIVE_RUNNING = "running"
LIVE_STARTING = "starting"
LIVE_UNRESPONSIVE = "unresponsive"   # process exists but heartbeat is stale: state must be checked
LIVE_LOST = "lost"                   # worker is definitely gone but the run never finished
LIVE_UNKNOWN = "unknown"

HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_STALE_SECONDS = 30.0
STARTING_GRACE_SECONDS = 45.0
STOP_GRACE_SECONDS = 25.0


@dataclass
class Limits:
    """Every loop bound is a named, configurable constant; nothing loops unbounded."""

    reviewer_trigger_fails: int = 2       # Tests FAIL #N brings the Reviewer in
    max_repair_iterations: int = 12
    max_same_failure: int = 3             # same failure fingerprint this many times => human
    max_same_review: int = 3              # same reviewer finding set this many times => human
    max_no_change_repairs: int = 2        # consecutive repairs that changed nothing
    max_review_rounds: int = 12
    max_provider_retries: int = 2         # transient provider errors only
    max_main_resumes: int = 2             # empty-diff max-turns resume (Claude)
    max_runtime_minutes: int = 360
    agent_timeout: int = 1800
    review_timeout: int = 1200
    test_timeout: int = 600


DEFAULT_LIMITS = Limits()


def runs_root() -> Path:
    return state_root() / "runs"


def locks_root() -> Path:
    return state_root() / "locks"


def new_record(*, run_id: str, repo: str, task: str, main_agent: str, review_agent: str,
               tests: list[str], limits: Limits, branch: str = "", base_sha: str = "") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id, "repo": repo, "source_branch": branch, "base_sha": base_sha,
        "task": task, "tests": list(tests),
        "main_agent": main_agent, "review_agent": review_agent,
        "limits": asdict(limits),
        "stage": CREATED, "stage_detail": "", "stage_history": [],
        "tests_run_count": 0, "tests_fail_count": 0, "tests_consecutive_fail_count": 0,
        "repair_iteration": 0, "main_calls": 0, "review_calls": 0, "review_rounds": 0,
        "reviewer_engaged": False,
        "current_failure_fingerprint": None, "failure_fingerprint_counts": {},
        "review_fingerprint_counts": {}, "no_change_repairs": 0,
        "failure_history": [], "repair_history": [], "review_history": [],
        "provider_errors": [], "quota_errors": [],
        "worktree": "", "candidate_branch": "", "candidate_sha": "",
        "apply_status": "", "apply_detail": "",
        "worker": None, "children": [],
        "created_at": now_iso(), "started_at": None, "heartbeat_at": None, "finished_at": None,
        "final_result": None, "stopped_by_user": False,
    }


# --- writer side: used by the run's own worker --------------------------------------

class RunRecorder:
    """The single writer of run.json for a live run (thread-safe)."""

    def __init__(self, run_dir: Path, record: dict):
        self.run_dir = run_dir
        self.record = record
        self._lock = threading.RLock()
        self.stop_event = threading.Event()
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None
        self.seq = 0

    # persistence
    def save(self) -> None:
        with self._lock:
            self.record["heartbeat_at"] = now_iso()
            write_json_atomic(self.run_dir / "run.json", self.record)

    def update(self, **fields) -> None:
        with self._lock:
            self.record.update(fields)
            self.save()

    def incr(self, field_name: str, by: int = 1) -> int:
        with self._lock:
            self.record[field_name] = int(self.record.get(field_name, 0)) + by
            self.save()
            return self.record[field_name]

    def append(self, field_name: str, entry) -> None:
        with self._lock:
            self.record.setdefault(field_name, []).append(entry)
            self.save()

    # stages
    @property
    def stage(self) -> str:
        return self.record["stage"]

    def transition(self, new_stage: str, detail: str = "") -> None:
        with self._lock:
            current = self.record["stage"]
            if new_stage != current:
                if new_stage not in ALLOWED_TRANSITIONS.get(current, frozenset()):
                    raise OrchestratorError(f"illegal stage transition {current} -> {new_stage}", "ILLEGAL_TRANSITION")
                self.record["stage_history"].append({"stage": new_stage, "at": now_iso()})
                self.record["stage"] = new_stage
            self.record["stage_detail"] = detail
            self.save()
        self.log(f"[{new_stage}] {detail}" if detail else f"[{new_stage}]")

    def finish(self, stage: str, code: str, message: str, **extra) -> None:
        with self._lock:
            if self.record["stage"] not in TERMINAL_STAGES:
                if stage not in ALLOWED_TRANSITIONS.get(self.record["stage"], frozenset()):
                    # e.g. failed while already `stopping`: always allow reaching a terminal state
                    if stage not in TERMINAL_STAGES:
                        raise OrchestratorError(f"illegal finish stage {stage}", "ILLEGAL_TRANSITION")
                self.record["stage_history"].append({"stage": stage, "at": now_iso()})
                self.record["stage"] = stage
            self.record["stage_detail"] = message
            self.record["finished_at"] = now_iso()
            self.record["final_result"] = {"stage": stage, "code": code, "message": message, **extra}
            self.record["children"] = []
            self.save()
        self.log(f"[{stage}] {code}: {message}")

    # log
    def log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        try:
            with open(self.run_dir / "events.log", "a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {line}\n")
        except OSError:
            pass

    def write_text(self, relative: str, text: str) -> None:
        path = self.run_dir / relative
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass

    # child process registry (ChildRegistry protocol)
    def add(self, pid: int, label: str) -> None:
        with self._lock:
            self.record["children"] = [c for c in self.record["children"] if c["pid"] != pid]
            self.record["children"].append({"pid": pid, "token": process_start_token(pid), "label": label})
            self.save()

    def remove(self, pid: int) -> None:
        with self._lock:
            self.record["children"] = [c for c in self.record["children"] if c["pid"] != pid]
            self.save()

    # heartbeat + control watcher
    def start_heartbeat(self) -> None:
        pid = os.getpid()
        token = process_start_token(pid)

        def loop() -> None:
            last_beat = 0.0
            while not self._hb_stop.is_set():
                now = time.monotonic()
                if now - last_beat >= HEARTBEAT_INTERVAL:
                    self.seq += 1
                    try:
                        write_json_atomic(self.run_dir / "heartbeat.json", {
                            "ts": time.time(), "pid": pid, "token": token,
                            "stage": self.record.get("stage"), "seq": self.seq})
                    except OSError:
                        pass
                    last_beat = now
                control = read_json(self.run_dir / "control.json")
                if control and control.get("stop_requested") and not self.stop_event.is_set():
                    self.log("safe stop requested by user")
                    self.stop_event.set()
                self._hb_stop.wait(1.0)

        self._hb_thread = threading.Thread(target=loop, name="run-heartbeat", daemon=True)
        self._hb_thread.start()

    def stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=3)


# --- reader side: DCC and CLI ---------------------------------------------------------

def read_record(run_dir: Path) -> dict | None:
    return read_json(run_dir / "run.json")


def inspect_run(run_dir: Path, now: float | None = None) -> dict:
    """Combine run id, process identity (pid + creation time), and heartbeat.

    Returns {"liveness", "record", "heartbeat_age", "reason"}. `running` is asserted
    only when the worker process is provably the same one that was started AND its
    heartbeat is fresh.
    """
    now = time.time() if now is None else now
    record = read_record(run_dir)
    if record is None:
        return {"liveness": LIVE_UNKNOWN, "record": None, "heartbeat_age": None, "reason": "run.jsonを読めません"}
    if record.get("stage") in TERMINAL_STAGES:
        return {"liveness": LIVE_FINISHED, "record": record, "heartbeat_age": None, "reason": ""}
    worker = record.get("worker") or {}
    if not worker.get("pid"):
        age = _age_since_iso(record.get("created_at"), now)
        if age is not None and age <= STARTING_GRACE_SECONDS:
            return {"liveness": LIVE_STARTING, "record": record, "heartbeat_age": None, "reason": "起動中"}
        return {"liveness": LIVE_LOST, "record": record, "heartbeat_age": None, "reason": "workerが起動していません"}
    if not pid_matches(int(worker["pid"]), worker.get("token")):
        return {"liveness": LIVE_LOST, "record": record, "heartbeat_age": None,
                "reason": "workerプロセスが存在しません（終了、またはPID再利用）"}
    heartbeat = read_json(run_dir / "heartbeat.json") or {}
    age = None
    if heartbeat.get("pid") == worker["pid"] and heartbeat.get("token") == worker.get("token") and heartbeat.get("ts"):
        age = max(0.0, now - float(heartbeat["ts"]))
    if age is not None and age <= HEARTBEAT_STALE_SECONDS:
        return {"liveness": LIVE_RUNNING, "record": record, "heartbeat_age": age, "reason": ""}
    started = _age_since_iso(record.get("started_at") or record.get("created_at"), now)
    if age is None and started is not None and started <= STARTING_GRACE_SECONDS:
        return {"liveness": LIVE_STARTING, "record": record, "heartbeat_age": None, "reason": "起動中"}
    return {"liveness": LIVE_UNRESPONSIVE, "record": record, "heartbeat_age": age,
            "reason": "接続不能: heartbeatが途絶えています。状態確認が必要です"}


def _age_since_iso(text, now: float) -> float | None:
    try:
        return now - time.mktime(time.strptime(str(text), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def list_runs(*, repo: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first. Each item is inspect_run() output plus run_dir."""
    root = runs_root()
    try:
        dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)[:limit]
    except OSError:
        return []
    items = []
    wanted = _norm(repo) if repo is not None else None
    for directory in dirs:
        info = inspect_run(directory)
        record = info["record"]
        if record is None:
            continue
        if wanted is not None and _norm(record.get("repo")) != wanted:
            continue
        info["run_dir"] = directory
        items.append(info)
    return items


def _norm(path) -> str:
    """Canonical spelling: an 8.3 short path and its long form name the same repo."""
    text = str(path or "")
    return os.path.normcase(os.path.realpath(text)) if text else ""


def active_runs(repo: str | None = None) -> list[dict]:
    """Runs that are (or may be) alive: running / starting / unresponsive. Lost runs are not."""
    return [i for i in list_runs(repo=repo)
            if i["liveness"] in (LIVE_RUNNING, LIVE_STARTING, LIVE_UNRESPONSIVE)]


def tail_log(run_dir: Path, offset: int = 0, initial_limit: int = 60_000) -> tuple[str, int]:
    """New log text since `offset`; the first read of a long log starts near its end."""
    path = run_dir / "events.log"
    try:
        size = path.stat().st_size
        if size < offset:
            offset = 0
        if offset == 0 and size > initial_limit:
            offset = size - initial_limit
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read(200_000)
        return data.decode("utf-8", errors="replace"), offset + len(data)
    except OSError:
        return "", offset


# --- repo lock (duplicate start prevention) ------------------------------------------

class ActiveRunExists(OrchestratorError):
    code = "RUN_ALREADY_ACTIVE"

    def __init__(self, run_id: str, liveness: str):
        super().__init__(f"このrepoには実行中または状態確認が必要なrunがあります: {run_id} ({liveness})")
        self.run_id = run_id
        self.liveness = liveness


def _lock_path(repo: str) -> Path:
    digest = hashlib.sha1(_norm(repo).encode("utf-8")).hexdigest()[:10]
    return locks_root() / f"{slugify(Path(repo).name, 24)}-{digest}.json"


def acquire_repo_lock(repo: str, run_id: str) -> Path:
    """One orchestrator run per repo. Other repos are unaffected. A lock whose holder
    is definitely gone is reclaimed; one whose holder is merely unresponsive is not."""
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = read_json(path) or {}
            holder_id = str(holder.get("run_id", ""))
            info = inspect_run(runs_root() / holder_id) if holder_id else {"liveness": LIVE_UNKNOWN}
            if info["liveness"] in (LIVE_RUNNING, LIVE_STARTING, LIVE_UNRESPONSIVE):
                raise ActiveRunExists(holder_id, info["liveness"])
            if info["liveness"] == LIVE_LOST:
                reconcile_lost(runs_root() / holder_id)
            try:
                path.unlink()
            except OSError:
                time.sleep(0.05)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('{"run_id": "%s", "repo": %s, "created_at": "%s"}' % (
                run_id, json.dumps(str(repo)), now_iso()))
        return path
    raise OrchestratorError("could not acquire the repo run lock", "LOCK_UNAVAILABLE")


def release_repo_lock(repo: str, run_id: str) -> None:
    path = _lock_path(repo)
    holder = read_json(path) or {}
    if holder.get("run_id") == run_id:
        try:
            path.unlink()
        except OSError:
            pass


# --- stop / reconcile ---------------------------------------------------------------

def request_stop(run_dir: Path, reason: str = "user") -> None:
    write_json_atomic(run_dir / "control.json", {"stop_requested": True, "reason": reason, "requested_at": now_iso()})


def kill_owned_children(record: dict) -> list[dict]:
    """Terminate only the children this run registered, each verified by PID + creation time."""
    results = []
    for child in record.get("children") or []:
        pid, token = int(child["pid"]), child.get("token")
        alive = pid_matches(pid, token)
        killed = terminate_pid_tree(pid, token) if alive else False
        results.append({"pid": pid, "label": child.get("label"), "was_alive": alive, "terminated": killed})
    return results


def _mark_terminal(run_dir: Path, record: dict, stage: str, code: str, message: str, **extra) -> dict:
    record["stage_history"].append({"stage": stage, "at": now_iso()})
    record["stage"] = stage
    record["stage_detail"] = message
    record["finished_at"] = now_iso()
    record["children"] = []
    record["final_result"] = {"stage": stage, "code": code, "message": message, **extra}
    write_json_atomic(run_dir / "run.json", record)
    try:
        with open(run_dir / "events.log", "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} [{stage}] {code}: {message}\n")
    except OSError:
        pass
    release_repo_lock(str(record.get("repo", "")), str(record.get("run_id", "")))
    return record


def reconcile_lost(run_dir: Path) -> dict | None:
    """The worker is provably gone but never wrote a final state: clean up what it owned
    and record the outcome. Never guesses about a worker that might still be alive."""
    info = inspect_run(run_dir)
    if info["liveness"] != LIVE_LOST:
        return info["record"]
    record = info["record"]
    outcomes = kill_owned_children(record)
    stopping = record.get("stage") == STOPPING or record.get("stopped_by_user")
    if stopping:
        return _mark_terminal(run_dir, record, STOPPED, "USER_SAFETY_STOP", "safe stop completed (worker had exited)",
                              process_results=outcomes)
    return _mark_terminal(
        run_dir, record, FAILED, "WORKER_LOST",
        "run worker process disappeared without a final result; isolated worktree preserved for inspection",
        process_results=outcomes)


def force_stop(run_dir: Path, *, wait: float = STOP_GRACE_SECONDS, poll: float = 0.5) -> dict:
    """AI safe stop: ask the worker to stop; if it does not finish within `wait`, terminate the
    worker tree by verified identity plus the children it registered. Nothing else is touched."""
    info = inspect_run(run_dir)
    record = info["record"]
    if record is None:
        raise OrchestratorError("run not found", "RUN_NOT_FOUND")
    if info["liveness"] == LIVE_FINISHED:
        return record
    request_stop(run_dir)
    if info["liveness"] == LIVE_LOST:
        record["stopped_by_user"] = True
        return reconcile_lost(run_dir) or record
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        current = inspect_run(run_dir)
        if current["liveness"] == LIVE_FINISHED:
            return current["record"]
        if current["liveness"] == LIVE_LOST:
            break
        time.sleep(poll)
    current = inspect_run(run_dir)
    if current["liveness"] == LIVE_FINISHED:
        return current["record"]
    record = current["record"] or record
    worker = record.get("worker") or {}
    results = kill_owned_children(record)
    if worker.get("pid") and worker.get("token") and pid_matches(int(worker["pid"]), worker["token"]):
        terminate_pid_tree(int(worker["pid"]), worker["token"])
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and pid_matches(int(worker["pid"]), worker["token"]):
            time.sleep(0.2)
        if pid_matches(int(worker["pid"]), worker["token"]):
            raise OrchestratorError("worker process did not terminate; run state cannot be confirmed", "STOP_UNCONFIRMED")
    latest = read_record(run_dir) or record
    if latest.get("stage") in TERMINAL_STAGES:
        return latest
    latest["stopped_by_user"] = True
    return _mark_terminal(run_dir, latest, STOPPED, "USER_SAFETY_STOP", "safe stop (worker terminated by identity-verified process tree)",
                          process_results=results, forced=True)


def mark_applied(run_dir: Path, detail: str) -> None:
    """Record that a completed run's candidate was applied to the local branch (client-side note
    on an already finished run; the run itself is never re-opened)."""
    record = read_record(run_dir)
    if record is None or record.get("stage") != COMPLETED:
        raise OrchestratorError("only a completed run can be marked applied", "RUN_NOT_COMPLETED")
    record["apply_status"] = "applied"
    record["apply_detail"] = detail
    write_json_atomic(run_dir / "run.json", record)
