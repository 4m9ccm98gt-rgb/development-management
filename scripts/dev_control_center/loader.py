"""Tk-free async load coordinator for the Development Control Center.

Workers never touch Tk. All token-state transitions, slots, queues and worker
bookkeeping are guarded by ONE coordinator lock, so result-vs-timeout
arbitration and worker accounting are atomic. Workers are our own daemon
threads (not ThreadPoolExecutor) so a wedged worker can never block exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import itertools
import threading
import time
from typing import Any, Callable

from . import core
from .timing import Timing

GLOBAL = "__global__"
ABANDON_ROOM = 4          # T_max = pool size + ABANDON_ROOM live threads
SUPERSEDE_GRACE = 10.0    # provisional; counted from cancelled_at

LOCAL_POOL = "LOCAL"
GITHUB_POOL = "GITHUB"
BACKGROUND_POOL = "BACKGROUND"

TIMEOUT_MESSAGE = "読込タイムアウト"
ABANDON_CAP_MESSAGE = "読込リソース枯渇（応答しない処理が残っています）— しばらくして「再読込」"


class RequestState(enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    TIMED_OUT = "TIMED_OUT"


class WorkerState(enum.Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    ABANDONED = "ABANDONED"
    RETIRED = "RETIRED"


class NoticeKind(enum.Enum):
    TIMEOUT = "TIMEOUT"
    ABANDON_CAP = "ABANDON_CAP"


@dataclass(frozen=True)
class PoolConfig:
    name: str
    size: int
    deadline: float


DEFAULT_POOLS = (
    PoolConfig(LOCAL_POOL, 2, 30.0),
    PoolConfig(GITHUB_POOL, 3, 60.0),
    PoolConfig(BACKGROUND_POOL, 2, 90.0),
)


@dataclass(frozen=True)
class WorkerResult:
    token: int
    key: tuple[str, str]
    repo: str | None
    epoch: int | None
    extra: dict[str, Any]
    payload: Any = None
    error: BaseException | None = None

    @property
    def scope(self) -> str:
        return GLOBAL if self.repo is None else "REPO"


@dataclass(frozen=True)
class TerminalNotice:
    token: int
    key: tuple[str, str]
    repo: str | None
    epoch: int | None
    extra: dict[str, Any]
    kind: NoticeKind
    message: str

    @property
    def scope(self) -> str:
        return GLOBAL if self.repo is None else "REPO"


@dataclass
class Request:
    token: int
    key: tuple[str, str]
    pool: str
    fn: Callable[[threading.Event], Any]
    repo: str | None
    epoch: int | None
    extra: dict[str, Any]
    deadline: float
    queued_at: float
    cancel: threading.Event = field(default_factory=threading.Event)
    state: RequestState = RequestState.PENDING
    started_at: float | None = None
    cancelled_at: float | None = None
    worker_id: int | None = None


@dataclass
class WorkerRecord:
    worker_id: int
    pool: str
    state: WorkerState = WorkerState.IDLE
    current_request: Request | None = None
    reclaimed: bool = False

    @property
    def current_token(self) -> int | None:
        return self.current_request.token if self.current_request else None


class Coordinator:
    def __init__(
        self,
        pools: tuple[PoolConfig, ...] = DEFAULT_POOLS,
        *,
        clock: Callable[[], float] = time.monotonic,
        timing: Timing | None = None,
        abandon_room: int = ABANDON_ROOM,
        grace: float = SUPERSEDE_GRACE,
    ) -> None:
        self._pools = {p.name: p for p in pools}
        self._clock = clock
        self._timing = timing
        self._room = abandon_room
        self.grace = grace
        self._cv = threading.Condition(threading.Lock())
        self._tokens = itertools.count(1)
        self._ids = itertools.count(1)
        self._workers: dict[int, WorkerRecord] = {}
        self._pending: dict[tuple[str, str], Request] = {}
        self._latest: dict[tuple[str, str], Request] = {}
        self._result_slot: dict[tuple[str, str], WorkerResult] = {}
        self._notice_slot: dict[tuple[str, str], TerminalNotice] = {}
        self._started_pools: set[str] = set()
        self._closed = False

    # ------------------------------------------------------------------ util
    def _event(self, name: str, **fields: object) -> None:
        if self._timing is not None:
            self._timing.event(name, **fields)

    @property
    def closed(self) -> bool:
        return self._closed

    def _active(self, pool: str) -> int:
        return sum(
            1 for w in self._workers.values()
            if w.pool == pool and w.state in (WorkerState.IDLE, WorkerState.RUNNING)
        )

    def _abandoned(self, pool: str) -> int:
        return sum(
            1 for w in self._workers.values()
            if w.pool == pool and w.state is WorkerState.ABANDONED
        )

    def stats(self, pool: str) -> dict[str, int]:
        with self._cv:
            cfg = self._pools[pool]
            active = self._active(pool)
            abandoned = self._abandoned(pool)
            return {
                "size": cfg.size,
                "active_count": active,
                "abandoned_live": abandoned,
                "total_live": active + abandoned,
                "t_max": cfg.size + self._room,
                "deficit": cfg.size - active,
                "pending": sum(1 for r in self._pending.values() if r.pool == pool),
                "running": sum(
                    1 for w in self._workers.values()
                    if w.pool == pool and w.state is WorkerState.RUNNING
                ),
            }

    def slot_counts(self) -> tuple[int, int, int]:
        with self._cv:
            return len(self._pending), len(self._result_slot), len(self._notice_slot)

    def request_state(self, token: int) -> RequestState | None:
        with self._cv:
            for req in self._all_requests_locked():
                if req.token == token:
                    return req.state
            return None

    def latest_token(self, key: tuple[str, str]) -> int | None:
        with self._cv:
            req = self._latest.get(key)
            return req.token if req else None

    def is_latest(self, token: int, key: tuple[str, str]) -> bool:
        return self.latest_token(key) == token

    def _all_requests_locked(self) -> list[Request]:
        seen = list(self._pending.values())
        seen.extend(self._latest.values())
        seen.extend(w.current_request for w in self._workers.values() if w.current_request)
        return seen

    # --------------------------------------------------------------- workers
    def _spawn_locked(self, pool: str) -> None:
        rec = WorkerRecord(next(self._ids), pool)
        self._workers[rec.worker_id] = rec
        threading.Thread(
            target=self._worker_main, args=(rec,), daemon=True,
            name=f"dcc-{pool.lower()}-{rec.worker_id}",
        ).start()

    def _ensure_workers_locked(self, pool: str) -> None:
        cfg = self._pools[pool]
        limit = cfg.size + self._room
        while (
            not self._closed
            and self._active(pool) < cfg.size
            and self._active(pool) + self._abandoned(pool) < limit
        ):
            self._spawn_locked(pool)

    def _take_pending_locked(self, rec: WorkerRecord) -> Request | None:
        for key, req in self._pending.items():
            if req.pool == rec.pool:
                del self._pending[key]
                req.state = RequestState.RUNNING
                req.started_at = self._clock()
                req.worker_id = rec.worker_id
                rec.state = WorkerState.RUNNING
                rec.current_request = req
                return req
        return None

    def _worker_main(self, rec: WorkerRecord) -> None:
        while True:
            with self._cv:
                while True:
                    if self._closed or rec.state is WorkerState.RETIRED:
                        rec.state = WorkerState.RETIRED
                        return
                    req = self._take_pending_locked(rec)
                    if req is not None:
                        break
                    self._cv.wait()
            outcome: tuple[str, Any]
            try:
                outcome = ("ok", req.fn(req.cancel))
            except core.Cancelled:
                outcome = ("cancelled", None)
            except Exception as exc:  # noqa: BLE001 - reported as WorkerResult.error
                outcome = ("error", exc)
            with self._cv:
                self._finish_locked(rec, req, outcome)
                if rec.state is WorkerState.RETIRED:
                    return

    def _finish_locked(self, rec: WorkerRecord, req: Request, outcome: tuple[str, Any]) -> None:
        self._complete_locked(req, outcome)
        rec.current_request = None
        if rec.state is WorkerState.RUNNING:
            rec.state = WorkerState.IDLE
        elif rec.state is WorkerState.ABANDONED:
            # A wedged worker came back: rehabilitate it if the pool has room.
            if self._active(rec.pool) < self._pools[rec.pool].size:
                rec.state = WorkerState.IDLE
                rec.reclaimed = False  # a later wedge must be reclaimable again
                self._event("rehabilitate", pool=rec.pool, worker=rec.worker_id)
            else:
                rec.state = WorkerState.RETIRED
                self._event("retire", pool=rec.pool, worker=rec.worker_id)
        self._ensure_workers_locked(rec.pool)
        self._cv.notify_all()

    def _complete_locked(self, req: Request, outcome: tuple[str, Any]) -> None:
        """Atomic arbitration: exactly one outcome (result XOR notice) per token."""
        if req.state is RequestState.RUNNING:
            kind, value = outcome
            if kind == "cancelled":
                req.state = RequestState.SUPERSEDED
                return
            req.state = RequestState.COMPLETED
            msg = WorkerResult(
                req.token, req.key, req.repo, req.epoch, req.extra,
                payload=value if kind == "ok" else None,
                error=value if kind == "error" else None,
            )
            held = self._result_slot.get(req.key)
            if held is None or held.token < msg.token:
                self._result_slot[req.key] = msg
            return
        # SUPERSEDED / TIMED_OUT: the late result is dropped at the source.
        if req.state is RequestState.SUPERSEDED and req.cancelled_at is not None:
            self._event(
                "superseded-worker-returned", key=req.key,
                ms=round((self._clock() - req.cancelled_at) * 1000),
            )
        else:
            self._event("result-dropped-at-source", key=req.key, state=req.state.value)

    # ------------------------------------------------------------ submission
    def submit(
        self,
        key: tuple[str, str],
        fn: Callable[[threading.Event], Any],
        *,
        pool: str,
        epoch: int | None = None,
        extra: dict[str, Any] | None = None,
        deadline: float | None = None,
    ) -> Request:
        repo = None if key[0] == GLOBAL else key[0]
        with self._cv:
            cfg = self._pools[pool]
            now = self._clock()
            req = Request(
                token=next(self._tokens), key=key, pool=pool, fn=fn, repo=repo,
                epoch=epoch, extra=dict(extra or {}),
                deadline=cfg.deadline if deadline is None else deadline, queued_at=now,
            )
            if self._closed:
                req.state = RequestState.SUPERSEDED
                req.cancel.set()
                return req
            prior = self._latest.get(key)
            if prior is not None and prior.state in (RequestState.PENDING, RequestState.RUNNING):
                self._supersede_locked(prior, now)
            self._notice_slot.pop(key, None)
            self._result_slot.pop(key, None)
            self._latest[key] = req
            self._pending[key] = req
            self._started_pools.add(pool)
            self._ensure_workers_locked(pool)
            if self._active(pool) == 0:
                del self._pending[key]
                req.state = RequestState.TIMED_OUT
                req.cancel.set()
                self._put_notice_locked(req, NoticeKind.ABANDON_CAP, ABANDON_CAP_MESSAGE)
            self._cv.notify_all()
            return req

    def _put_notice_locked(self, req: Request, kind: NoticeKind, message: str) -> None:
        notice = TerminalNotice(req.token, req.key, req.repo, req.epoch, req.extra, kind, message)
        held = self._notice_slot.get(req.key)
        if held is None or held.token < notice.token:
            self._notice_slot[req.key] = notice
        self._event("notice", key=req.key, kind=kind.value)

    def _supersede_locked(self, req: Request, now: float) -> None:
        """The single per-request supersede routine (no notice, ever)."""
        if req.state is RequestState.PENDING:
            if self._pending.get(req.key) is req:
                del self._pending[req.key]
            req.cancel.set()
            req.state = RequestState.SUPERSEDED
        elif req.state is RequestState.RUNNING:
            req.cancel.set()
            req.state = RequestState.SUPERSEDED
            req.cancelled_at = now
        else:
            return
        held = self._result_slot.get(req.key)
        if held is not None and held.token == req.token:
            del self._result_slot[req.key]
        held_notice = self._notice_slot.get(req.key)
        if held_notice is not None and held_notice.token == req.token:
            del self._notice_slot[req.key]

    def cancel_repo_scope(self, repo: str, reason: str) -> tuple[int, int]:
        """THE cancellation primitive for a repo's REPO-scope requests.

        Supersedes PENDING (removed) and RUNNING (cancel Event set, grace clock
        started) requests. Produces no notice and never touches GLOBAL requests.
        """
        with self._cv:
            now = self._clock()
            pending = [r for r in self._pending.values() if r.repo == repo]
            running = [
                w.current_request for w in self._workers.values()
                if w.state is WorkerState.RUNNING and w.current_request is not None
                and w.current_request.repo == repo
                and w.current_request.state is RequestState.RUNNING
            ]
            for req in pending + running:
                self._supersede_locked(req, now)
            self._event(
                "repo-scope-cancel", repo=repo, reason=reason,
                pending=len(pending), running=len(running),
            )
            self._cv.notify_all()
            return len(pending), len(running)

    # -------------------------------------------------------------- watchdog
    def tick(self, now: float | None = None) -> None:
        with self._cv:
            now = self._clock() if now is None else now
            for req in list(self._pending.values()):
                if now - req.queued_at >= req.deadline:                      # 5a
                    del self._pending[req.key]
                    req.cancel.set()
                    req.state = RequestState.TIMED_OUT
                    self._put_notice_locked(req, NoticeKind.TIMEOUT, TIMEOUT_MESSAGE)
                    self._event("timeout-pending", key=req.key)
            for rec in list(self._workers.values()):
                req = rec.current_request
                if rec.state is not WorkerState.RUNNING or req is None:
                    continue
                if req.state is RequestState.RUNNING:
                    if req.started_at is not None and now - req.started_at >= req.deadline:  # 5b
                        req.cancel.set()
                        req.state = RequestState.TIMED_OUT
                        self._abandon_locked(rec)
                        self._put_notice_locked(req, NoticeKind.TIMEOUT, TIMEOUT_MESSAGE)
                        self._event("timeout-running", key=req.key)
                elif (
                    req.state is RequestState.SUPERSEDED
                    and req.cancelled_at is not None
                    and not rec.reclaimed
                    and now - req.cancelled_at >= self.grace                  # 5g
                ):
                    self._abandon_locked(rec)
                    self._event("superseded-worker-abandoned", key=req.key)
            for pool in self._started_pools:
                self._ensure_workers_locked(pool)
            self._cv.notify_all()

    def _abandon_locked(self, rec: WorkerRecord) -> None:
        rec.state = WorkerState.ABANDONED
        rec.reclaimed = True
        self._event("abandon", pool=rec.pool, worker=rec.worker_id)
        self._ensure_workers_locked(rec.pool)

    # ----------------------------------------------------------------- drain
    def drain(self) -> list[WorkerResult | TerminalNotice]:
        """Take at most one message per key (highest token), ordered by token."""
        with self._cv:
            if self._closed:
                self._result_slot.clear()
                self._notice_slot.clear()
                return []
            out: list[WorkerResult | TerminalNotice] = []
            for key in set(self._result_slot) | set(self._notice_slot):
                result = self._result_slot.pop(key, None)
                notice = self._notice_slot.pop(key, None)
                pick = max(
                    (m for m in (result, notice) if m is not None), key=lambda m: m.token
                )
                out.append(pick)
            out.sort(key=lambda m: m.token)
            return out

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        """Stop applying results and cancel everything; never joins workers."""
        with self._cv:
            self._closed = True
            for req in self._all_requests_locked():
                req.cancel.set()
            self._pending.clear()
            self._result_slot.clear()
            self._notice_slot.clear()
            self._cv.notify_all()
        core.kill_registered_children()
