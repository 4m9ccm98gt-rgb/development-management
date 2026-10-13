"""DCC Task 19b: automatic re-run of an Orchestrator run that stopped only because an AI
provider's usage quota/credit ran out (needs_human code PROVIDER_QUOTA) -- waits for the quota
to likely have recovered, then starts the *same* request again as a brand-new run through the
existing Orchestrator start entry point (tools.ai_orchestrator.orchestrator.start_run). A run
can never be resumed mid-way, so every re-run starts over from the base commit; nothing here
ever approves, pushes, builds or deploys anything.

Security posture (same family as reports_auto.py / reports_auto_start.py):
 - Only a run whose final_result.code is exactly PROVIDER_QUOTA is ever a candidate. Every other
   needs_human reason, and every failed/stopped run, is left alone (is_quota_stop).
 - The re-run's task text, target repository, Main/Reviewer pairing, Tests and acceptance
   criteria all come unchanged from the stopped run's own run.json record
   (_default_start_requeue) -- never rewritten, never taken from report text or AI output. No
   new start entry point is introduced: _default_start_requeue builds the same
   tools.ai_orchestrator.orchestrator.StartRequest a human's own start button builds, then calls
   the same orchestrator.start_run.
 - The only untrusted text this module ever reads is the stopped run's own final_result.message
   (whatever the AI/provider happened to say). requeue_delay_minutes reads it only to look for one
   strict, fixed shape ("resets 5pm (Asia/Tokyo)"-like: hour, am/pm, IANA-style region/city, from a
   small hand-verified allowlist of DST-free zones) via _parse_quota_reset; anything that does not
   match that exact shape (a path, a command-like prefix, an unknown region, text with a newline,
   anything trailing after the match) is never parsed and falls back to a fixed 60-minute wait.
   The computed result is always an integer number of minutes, clamped to [MIN_DELAY_MINUTES,
   MAX_DELAY_MINUTES] -- never a string, path or command built from the text.
 - Both the shared global switch (reports_auto.AutoModeConfig.enabled, reused unchanged -- the
   same switch Task 17/18 already gate on) and this module's own RequeueConfig.enabled must be ON,
   re-read fresh right before every actual start attempt (run_requeue_once's own guard), so a
   human flipping either mid-wait stops the one attempt a cycle may make.
 - Scheduling state (which run is waiting, for how long, how many requeues a lineage has already
   used) lives only in the in-memory RequeueState the caller keeps for the life of the DCC process
   (仕様3): a plan is never written to disk, so a DCC restart never resumes a stopped run on its
   own by itself scheduling it again. To make that true even though list_runs() still returns
   runs that were already sitting in PROVIDER_QUOTA before this process started, the caller must
   call seed_startup_exclusions() once, synchronously, right after creating the RequeueState and
   before the first run_requeue_once -- every run_id it sees is permanently excluded from
   discovery for the rest of this process's life, regardless of whether either switch is on yet.
   If that one call's own list_runs_fn fails, discovery/starting stays disabled
   (RequeueState.startup_seeded) until a later attempt (retried automatically, once per
   run_requeue_once cycle, using that cycle's own list_runs_fn) actually succeeds -- a transient
   failure at startup must never let an already-stopped run slip through unexcluded once the list
   call starts working again.
   The fixed-word run log (write_run_log_entry, 仕様5), the daily/overall config, and (when the
   caller supplies a daily_count_path) the day's requeue count persist to %LOCALAPPDATA%.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Callable

from . import reports_auto as auto

DEFAULT_DAILY_LIMIT = 2
MAX_LINEAGE_ATTEMPTS = 2
REQUEUE_INTERVAL_SECONDS = 2 * 60

MIN_DELAY_MINUTES = 5
MAX_DELAY_MINUTES = 6 * 60
FALLBACK_DELAY_MINUTES = 60
_RESET_BUFFER_MINUTES = 5  # 仕様2: "その時刻の数分後" -- a few minutes after the reported reset time

LIMIT_REACHED_TEXT = "本日の再実行の上限に達しました"
NEEDS_HUMAN_TEXT = "人の確認が必要"

STATUS_DISABLED = "disabled"
STATUS_NOTHING_TO_DO = "nothing_to_do"
STATUS_STARTED = "started"
STATUS_STOPPED = "stopped"

LOG_RESULT_STARTED = "再実行開始"
LOG_RESULT_START_FAILED = "再実行失敗"

RUN_LOG_MAX_FILES = 50


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "requeue"


def requeue_config_path() -> Path:
    return _root() / "config.json"


def run_log_root() -> Path:
    return _root() / "run_log"


def daily_count_path() -> Path:
    return _root() / "daily_count.json"


# --------------------------------------------------------------------------- small JSON helpers

def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ----------------------------------------------------- 仕様1/3: 1日の上限の永続化（再起動をまたぐ）

def _read_daily_count(today: str, path: Path) -> int:
    """Mirrors reports_auto_start._read_daily_count exactly (same on-disk shape: {"date",
    "count"}) -- a count from any date other than `today` (or an unreadable/missing file) reads
    as 0, so the day rolling over always resets it without any extra bookkeeping."""
    data = _read_json(path)
    if data is None or data.get("date") != today:
        return 0
    try:
        return int(data.get("count", 0))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- 仕様1: 設定

@dataclass(frozen=True)
class RequeueConfig:
    """enabled: 「枠不足のとき自動で再実行する」の全体設定（初期値OFF）。daily_limit: 1日あたりの
    自動再実行の回数の上限（初期値2; Task18の自動開始の上限とは別勘定）。"""

    enabled: bool = False
    daily_limit: int = DEFAULT_DAILY_LIMIT


def load_requeue_config(path: Path | None = None) -> RequeueConfig:
    """Never raises: a missing or unreadable/corrupt file degrades to the all-OFF defaults."""
    data = _read_json(path if path is not None else requeue_config_path())
    if data is None:
        return RequeueConfig()
    try:
        daily_limit = int(data.get("daily_limit", DEFAULT_DAILY_LIMIT))
    except (TypeError, ValueError):
        daily_limit = DEFAULT_DAILY_LIMIT
    return RequeueConfig(enabled=bool(data.get("enabled", False)), daily_limit=daily_limit)


def save_requeue_config(config: RequeueConfig, path: Path | None = None) -> None:
    target = path if path is not None else requeue_config_path()
    _write_json_atomic(target, {"enabled": config.enabled, "daily_limit": config.daily_limit})


def set_enabled(enabled: bool, *, path: Path | None = None) -> RequeueConfig:
    """Read-modify-write the feature's own switch (DCC画面のチェックボックス用)."""
    config = load_requeue_config(path)
    updated = RequeueConfig(enabled=bool(enabled), daily_limit=config.daily_limit)
    save_requeue_config(updated, path)
    return updated


# --------------------------------------------------------------------------- 仕様3: 対象の判定

def is_quota_stop(record: dict) -> bool:
    """C2: only a run whose stop reason is exactly PROVIDER_QUOTA is ever a requeue candidate --
    every other needs_human code, and every failed/stopped run, is left alone."""
    if record.get("stage") != "needs_human":
        return False
    final = record.get("final_result") or {}
    return final.get("code") == "PROVIDER_QUOTA"


_REQUIRED_SCALAR_FIELDS = ("task", "repo", "main_agent", "review_agent")


def required_fields_present(record: dict) -> bool:
    """C13: everything a requeue needs (task text, repo, Main/Reviewer pairing, at least one Tests
    command, at least one acceptance criterion) must already be in the stopped run's own record."""
    for key in _REQUIRED_SCALAR_FIELDS:
        if not record.get(key):
            return False
    tests = record.get("tests")
    if not isinstance(tests, list) or not tests:
        return False
    criteria = record.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return False
    return True


# --------------------------------------------------------------------------- 仕様2: 待ち時間の計算

# Strict shape only: "resets <h>[:<mm>] <am|pm> (<Region>/<City>)" -- hour/minute/am-pm/region are
# the only things ever read out of an AI/provider message. No path, command or multi-line text can
# match (see _parse_quota_reset's own boundary checks below).
_QUOTA_RESET_RE = re.compile(
    r"resets?\s+(1[0-2]|[1-9])(?::([0-5][0-9]))?\s*([ap]m)\s*\(([A-Za-z]+/[A-Za-z_]+)\)\.?",
    re.IGNORECASE,
)
# A match is only accepted when whatever precedes it is either nothing (message starts with the
# phrase) or ends in one of these sentence-boundary punctuation marks. A bare run of letters right
# before "resets" (an "echo resets ..." command-like prefix, a word like "presets") is never a
# boundary and is therefore rejected -- plain whitespace alone is *not* enough, since a shell
# command's own arguments are whitespace-separated too.
_ALLOWED_LEAD_PUNCTUATION = ":：。、(（"
_LEAD_STRIP_WHITESPACE = " \t　"
_ALLOWED_TRAILING = " 。.\t"

# 仕様2: "検証済みの地域の時刻として" -- only a small, hand-verified allowlist of IANA region/city
# names that never observe DST (so a fixed UTC-offset lookup is always correct, with no tzdata
# package available under "標準ライブラリのみ"). Any other region/city, however well-formed,
# resolves to None and the whole message is treated as not matching the strict shape (fallback
# 60 minutes) -- exactly 仕様2's "未知の地域は60分にフォールバック".
_KNOWN_FIXED_OFFSET_MINUTES = {
    "Asia/Tokyo": 9 * 60,
    "Asia/Seoul": 9 * 60,
    "Asia/Shanghai": 8 * 60,
    "Asia/Singapore": 8 * 60,
    "Asia/Hong_Kong": 8 * 60,
    "Asia/Taipei": 8 * 60,
    "Asia/Kolkata": 5 * 60 + 30,
}


def _has_allowed_lead(message: str, start: int) -> bool:
    prefix = message[:start].rstrip(_LEAD_STRIP_WHITESPACE)
    return not prefix or prefix[-1] in _ALLOWED_LEAD_PUNCTUATION


def _resolve_offset_minutes(region: str) -> int | None:
    return _KNOWN_FIXED_OFFSET_MINUTES.get(region)


def _parse_quota_reset(message: str) -> tuple[int, int, int] | None:
    """(hour24, minute, utc_offset_minutes) parsed out of `message`'s one strict "resets H(:MM)
    am/pm (Region/City)" phrase, or None when the message does not contain exactly that shape --
    including when the region/city does not resolve to one of the known, DST-free zones above.
    Rejects: any message with a newline, a match whose immediate lead-in is not a sentence
    boundary (a command-like "echo resets ..." prefix, a path, a word like "presets"), and a
    match followed by anything other than trailing punctuation/whitespace."""
    if not message or "\n" in message or "\r" in message:
        return None
    match = _QUOTA_RESET_RE.search(message)
    if not match:
        return None
    start, end = match.span()
    if not _has_allowed_lead(message, start):
        return None
    if message[end:].strip(_ALLOWED_TRAILING):
        return None
    offset_minutes = _resolve_offset_minutes(match.group(4))
    if offset_minutes is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = match.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return hour, minute, offset_minutes


def requeue_delay_minutes(message: str, *, now: datetime) -> int:
    """C3: minutes to wait before requeueing, clamped to [MIN_DELAY_MINUTES, MAX_DELAY_MINUTES].
    When `message` matches the one strict shape *and* names one of the known, DST-free regions
    above, the wait is computed on that region's own wall clock (never `now`'s own timezone) --
    converted back to the same UTC instant as `now` to get the actual number of minutes; otherwise
    (no match, or an unresolvable/unknown region) the fixed FALLBACK_DELAY_MINUTES is used."""
    parsed = _parse_quota_reset(message)
    if parsed is None:
        minutes = FALLBACK_DELAY_MINUTES
    else:
        hour, minute, offset_minutes = parsed
        now_utc = now.astimezone(timezone.utc) if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        offset = timedelta(minutes=offset_minutes)
        local_now = now_utc + offset
        target_local = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_local <= local_now:
            target_local += timedelta(days=1)
        target_utc = target_local - offset
        minutes = math.ceil((target_utc - now_utc).total_seconds() / 60) + _RESET_BUFFER_MINUTES
    return max(MIN_DELAY_MINUTES, min(MAX_DELAY_MINUTES, minutes))


# --------------------------------------------------------------------------- 仕様3: in-memory state

@dataclass
class _Pending:
    scheduled_at: datetime
    lineage_root: str
    attempt: int


class RequeueState:
    """Held by the caller for one DCC process's lifetime. Scheduling itself (pending/needs_human/
    lineage_attempts/excluded_at_startup) is in-memory only (仕様3: a DCC restart never resumes a
    stopped run on its own). The day's requeue *count* is the one exception: when the caller
    supplies `daily_count_path` it is mirrored to disk (same convention as
    reports_auto_start._read_daily_count) so a same-day restart still inherits how many requeues
    already happened. Reviewer finding 1: record_daily_attempt must base the new in-memory total
    on daily_count(today) itself (memory vs. disk, whichever is already higher) and *then* add
    one -- never on a from-this-process-only running total -- otherwise a fresh RequeueState
    created after a same-day restart would start counting from 0 and a save failure right after
    that restart could let the day's real total slip past daily_limit. A save failure never blocks
    counting -- the in-memory total is always bumped first, so a restart can only ever see *at
    least* as many requeues as actually happened, never fewer. Omitting daily_count_path (every
    existing caller/test before this feature) keeps counting purely in-memory, with no disk access
    at all."""

    def __init__(self, *, daily_count_path: Path | None = None) -> None:
        self.pending: dict[str, _Pending] = {}
        self.needs_human: set[str] = set()
        self.started: set[str] = set()  # original run_ids that already triggered one requeue
        self.lineage_of: dict[str, str] = {}  # successor run_id -> its lineage's root run_id
        self.lineage_attempts: dict[str, int] = {}
        # 仕様3/再起動: run_ids that were already sitting in PROVIDER_QUOTA the moment this DCC
        # process started (seed_startup_exclusions) -- permanently excluded from discovery, even
        # once the config/global switch is later turned on.
        self.excluded_at_startup: set[str] = set()
        # Reviewer finding 2: True once seed_startup_exclusions has *successfully* read the run
        # list at least once. A caller that never seeds at all (every pre-existing test of this
        # module's own cycle behaviour) is left at this default of True, unaffected -- this only
        # ever turns False when a real seeding attempt's own list_runs_fn raised, in which case
        # run_requeue_once refuses discovery/starting until a later attempt actually succeeds.
        self.startup_seeded = True
        self._daily_count_path = daily_count_path
        self._daily_date: str | None = None
        self._daily_count = 0

    def lineage_root_for(self, run_id: str) -> str:
        return self.lineage_of.get(run_id, run_id)

    def known_run_ids(self) -> set[str]:
        """Stopped runs discovery must never look at again: either already scheduled/terminal, a
        run that already triggered its own requeue, or one excluded at this process's own startup
        (`lineage_of` on its own is only a counting lookup -- a freshly-started successor run_id
        must stay *undiscovered* here until it is itself seen stopped, or it would never get its
        own turn to be scheduled)."""
        return set(self.pending) | self.needs_human | self.started | self.excluded_at_startup

    def daily_count(self, today: str) -> int:
        memory = self._daily_count if self._daily_date == today else 0
        if self._daily_count_path is None:
            return memory
        try:
            persisted = _read_daily_count(today, self._daily_count_path)
        except Exception:  # noqa: BLE001 - an unreadable count file must not block a decision
            persisted = 0
        return max(memory, persisted)

    def record_daily_attempt(self, today: str) -> int:
        total = self.daily_count(today) + 1  # based on memory-vs-disk max, not a from-0 running total
        self._daily_date, self._daily_count = today, total
        if self._daily_count_path is not None:
            try:
                _write_json_atomic(self._daily_count_path, {"date": today, "count": total})
            except Exception:  # noqa: BLE001 - C12: a save failure must never undo the count above
                pass
        return total


# --------------------------------------------------------------------------- 仕様4: 表示（純関数）

def run_status_label(run_id: str, state: RequeueState, *, now: datetime | None = None) -> str:
    """C14: the fixed-word status for one run, recomputed fresh on every call (periodic UI tick) --
    never the stopped run's own final_result.message."""
    if run_id in state.needs_human:
        return NEEDS_HUMAN_TEXT
    pending = state.pending.get(run_id)
    if pending is None:
        return ""
    now = now or datetime.now(timezone.utc)
    minutes = max(0, math.ceil((pending.scheduled_at - now).total_seconds() / 60))
    return f"枠の回復待ち（再実行まで約{minutes}分）"


def limit_notice(global_config: "auto.AutoModeConfig", requeue_config: RequeueConfig,
                  state: RequeueState, today: str) -> str:
    """C6/仕様4: the fixed "本日の再実行の上限に達しました" sentence once today's own (separate)
    daily count has reached requeue_config.daily_limit -- gated on the same shared global switch,
    mirroring reports_auto_start._refresh_auto_start_notice."""
    if global_config.enabled and requeue_config.enabled and state.daily_count(today) >= requeue_config.daily_limit:
        return LIMIT_REACHED_TEXT
    return ""


# --------------------------------------------------------------------------- 仕様5: 実行ごとの記録

_LOG_SEQUENCE_LOCK = threading.Lock()
_LOG_SEQUENCE_COUNTER = 0


def _next_log_sequence() -> int:
    global _LOG_SEQUENCE_COUNTER
    with _LOG_SEQUENCE_LOCK:
        _LOG_SEQUENCE_COUNTER += 1
        return _LOG_SEQUENCE_COUNTER


def _prune_old_logs(directory: Path, keep: int) -> None:
    try:
        files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name)
    except OSError:
        return
    for stale in files[:-keep] if len(files) > keep else []:
        try:
            stale.unlink()
        except OSError:
            pass


def write_run_log_entry(*, repo: str, original_run_id: str, new_run_id: str, attempt: int, outcome: str,
                         log_dir: Path | None = None) -> None:
    """仕様5: one fixed-word/number record per automatic-requeue attempt (date/time, repo name,
    original run id, new run id, which attempt number, the fixed outcome word) -- never a message,
    path or exception text. Best-effort (C12): a logging failure must never affect the already-
    computed outcome, and in particular must never undo the in-memory counting that already
    happened before this is called. Kept to ~RUN_LOG_MAX_FILES recent entries."""
    try:
        from . import reports_inbox as inbox  # reuse the same display-safe sanitizer

        directory = log_dir if log_dir is not None else run_log_root()
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        lines = [
            f"日時: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"リポジトリ: {inbox.sanitize_path_for_display(Path(str(repo)).name)}",
            f"元のRun: {inbox.sanitize_path_for_display(original_run_id)}",
            f"新しいRun: {inbox.sanitize_path_for_display(new_run_id) if new_run_id else '(なし)'}",
            f"何回目の再実行か: {attempt}",
            f"結果: {outcome}",
        ]
        content = "\n".join(lines)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        seq = _next_log_sequence()
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
        _prune_old_logs(directory, RUN_LOG_MAX_FILES)
    except Exception:  # noqa: BLE001 - logging must never affect the outcome already computed
        pass


# --------------------------------------------------------------------------- default collaborators

def _default_list_runs() -> list:
    from tools.ai_orchestrator import runstate as rs

    return rs.list_runs(limit=200)


# --------------------------------------------------------------------------- 仕様3: 再起動時の除外

def seed_startup_exclusions(state: RequeueState, list_runs_fn: Callable[[], list] | None = None) -> bool:
    """Call exactly once, synchronously, right after creating `state` -- before the first
    run_requeue_once of this DCC process, and *unconditionally* (independent of either the global
    or this feature's own switch, so a DCC started with the switch OFF and later turned ON still
    keeps the exclusion, 仕様6). Every run_id already sitting in PROVIDER_QUOTA at this moment is
    permanently excluded from this process's own discovery: a DCC restart must never resume a
    stopped run on its own. A run that only becomes PROVIDER_QUOTA-stopped *after* this snapshot
    (even one with an older run_id that existed but was not yet stopped), and any successor run a
    requeue itself later starts, are unaffected -- only run_ids visible to this exact call are
    ever added here.

    Reviewer finding 2: returns whether the list itself was actually readable this call, and sets
    `state.startup_seeded` the same way -- an unreadable run list at startup must not silently act
    as "nothing was stopped" (which would let an already-stopped run slip through unexcluded once
    the list call starts working again). On failure, state.startup_seeded is left/set False so
    run_requeue_once refuses discovery/starting until a later call here actually succeeds."""
    list_runs_fn = list_runs_fn or _default_list_runs
    try:
        runs = list(list_runs_fn())
    except Exception:  # noqa: BLE001 - an unreadable run list at startup must not block DCC
        state.startup_seeded = False
        return False
    for item in runs:
        if not isinstance(item, dict):
            continue
        record = item.get("record")
        if not isinstance(record, dict):
            continue
        run_id = record.get("run_id")
        if run_id and is_quota_stop(record):
            state.excluded_at_startup.add(run_id)
    state.startup_seeded = True
    return True


def _default_active_runs(repo: str) -> list:
    from tools.ai_orchestrator import runstate as rs

    return rs.active_runs(repo=repo)


def _default_start_requeue(*, record: dict) -> Path:
    """The real "既存のOrchestratorの開始の入口" (no new start path): the same
    tools.ai_orchestrator.orchestrator.StartRequest / start_run a human's own 開始 button and
    reports_create_and_start._default_start_run already use, built only from the stopped run's own
    record -- task, tests, repo, Main/Reviewer and acceptance criteria are reused unchanged, never
    rewritten (C4)."""
    from tools.ai_orchestrator import taskspec
    from tools.ai_orchestrator.orchestrator import StartRequest, start_run as orch_start_run

    spec = taskspec.Spec(criteria=tuple(dict(c) for c in record["criteria"]), target_repo=None)
    request = StartRequest(
        repo=record["repo"], task=record["task"], tests=list(record["tests"]),
        main_agent=record["main_agent"], review_agent=record["review_agent"],
        expected_branch=record.get("source_branch") or None, prepare_source=True, fetch=True, spec=spec,
    )
    return orch_start_run(request)


# --------------------------------------------------------------------------- 仕様3: 実行本体

@dataclass(frozen=True)
class RequeueCycleOutcome:
    status: str
    started: tuple = ()  # tuple[tuple[str, str], ...]: (original_run_id, new_run_id) actually started


def run_requeue_once(
    *,
    state: RequeueState,
    global_config: "auto.AutoModeConfig | None" = None,
    global_config_path: Path | None = None,
    requeue_config: RequeueConfig | None = None,
    requeue_config_path: Path | None = None,
    now: datetime | None = None,
    today: str | None = None,
    list_runs_fn: Callable[[], list] | None = None,
    active_runs_fn: Callable[[str], list] | None = None,
    start_requeue_fn: Callable[..., Path] | None = None,
    log_dir: Path | None = None,
    stop_event: threading.Event | None = None,
) -> RequeueCycleOutcome:
    """Run at most one automatic requeue per target repository this cycle (C1-C13). Nothing here
    ever approves, pushes, builds or deploys; this only ever calls start_requeue_fn (default:
    _default_start_requeue -> the existing Orchestrator start entry point).

    Discovery (a stopped run seen for the first time) decides once, immediately, whether the run
    becomes a scheduled candidate (state.pending) or goes straight to `人の確認が必要`
    (state.needs_human) -- missing required fields or an already-exhausted lineage (C13/C5) never
    get a schedule at all. A scheduled candidate is only ever acted on once its own scheduled_at
    has passed; repositories are processed independently so one repo waiting on a busy target
    never blocks another repo's due candidate in the same cycle (C8/C11). The global switch and
    this module's own switch are re-read fresh immediately before the one real start attempt a
    repo may make this cycle (C7); any guard abort (switch off, or a genuine Orchestrator race)
    simply leaves the candidate pending for the next cycle without consuming the daily count or a
    lineage attempt. A genuine start rejection (C9: e.g. uncommitted changes in the source repo)
    is different -- it is terminal, so it does consume one attempt and goes straight to
    `人の確認が必要`, the same as a lineage that has already used its 2 allowed requeues (C5)."""
    global_config = global_config if global_config is not None else auto.load_auto_mode_config(global_config_path)
    requeue_config = requeue_config if requeue_config is not None else load_requeue_config(requeue_config_path)
    now = now or datetime.now(timezone.utc)
    today = today if today is not None else now.strftime("%Y-%m-%d")

    if not global_config.enabled or not requeue_config.enabled:
        return RequeueCycleOutcome(STATUS_DISABLED)

    list_runs_fn = list_runs_fn or _default_list_runs
    active_runs_fn = active_runs_fn or _default_active_runs
    start_requeue_fn = start_requeue_fn or _default_start_requeue

    # Reviewer finding 2: if the one startup seeding call ever failed, every cycle retries it
    # (using this cycle's own list_runs_fn) before doing anything else; until it actually
    # succeeds, discovery/starting stay fully disabled so an already-stopped run can never slip
    # through unexcluded. A caller that never seeds at all (state.startup_seeded's default True)
    # is completely unaffected.
    if not state.startup_seeded:
        seed_startup_exclusions(state, list_runs_fn)
    if not state.startup_seeded:
        return RequeueCycleOutcome(STATUS_NOTHING_TO_DO)

    try:
        runs = list(list_runs_fn())
    except Exception:  # noqa: BLE001 - an unreadable run list must not crash the cycle
        runs = []
    run_by_id = {r["record"]["run_id"]: r for r in runs
                 if isinstance(r, dict) and isinstance(r.get("record"), dict) and r["record"].get("run_id")}

    # 1) discovery: a stopped PROVIDER_QUOTA run is scheduled or sent to 人の確認が必要 exactly once.
    known = state.known_run_ids()
    for run_id, item in run_by_id.items():
        if run_id in known:
            continue
        record = item["record"]
        if not is_quota_stop(record):
            continue
        lineage_root = state.lineage_root_for(run_id)
        if not required_fields_present(record):
            state.needs_human.add(run_id)
            continue
        if state.lineage_attempts.get(lineage_root, 0) >= MAX_LINEAGE_ATTEMPTS:
            state.needs_human.add(run_id)
            continue
        message = (record.get("final_result") or {}).get("message", "")
        delay = requeue_delay_minutes(message, now=now)
        state.pending[run_id] = _Pending(scheduled_at=now + timedelta(minutes=delay), lineage_root=lineage_root,
                                          attempt=state.lineage_attempts.get(lineage_root, 0) + 1)

    if stop_event is not None and stop_event.is_set():
        return RequeueCycleOutcome(STATUS_STOPPED)

    # 2) due candidates, grouped by target repository: at most one start attempt per repo, repos
    #    are fully independent of each other (C11).
    by_repo: dict[str, str] = {}
    for run_id, pending in state.pending.items():
        if pending.scheduled_at > now:
            continue
        item = run_by_id.get(run_id)
        if item is None:
            continue
        repo = str(item["record"].get("repo", ""))
        by_repo.setdefault(repo, run_id)

    started: list[tuple[str, str]] = []
    for repo, run_id in by_repo.items():
        pending = state.pending[run_id]
        record = run_by_id[run_id]["record"]
        try:
            busy = bool(active_runs_fn(repo))
        except Exception:  # noqa: BLE001 - an unreadable lock must not block forever
            busy = False
        if busy:
            continue  # C8: stays pending, retried next cycle

        current_global = auto.load_auto_mode_config(global_config_path) if global_config_path else global_config
        current_requeue = load_requeue_config(requeue_config_path) if requeue_config_path else requeue_config
        if not current_global.enabled or not current_requeue.enabled:
            continue  # C7: stays pending, retried next cycle
        if state.daily_count(today) >= current_requeue.daily_limit:
            continue  # C6: stays pending (shown via limit_notice), retried once the day rolls over

        def _guarded_start(_record=record, _global_path=global_config_path, _requeue_path=requeue_config_path,
                            _fallback_global=current_global, _fallback_requeue=current_requeue):
            from tools.ai_orchestrator.runstate import ActiveRunExists

            if stop_event is not None and stop_event.is_set():
                raise ActiveRunExists("", "guard")
            latest_global = auto.load_auto_mode_config(_global_path) if _global_path else _fallback_global
            latest_requeue = load_requeue_config(_requeue_path) if _requeue_path else _fallback_requeue
            if not latest_global.enabled or not latest_requeue.enabled:
                raise ActiveRunExists("", "guard")
            if state.daily_count(today) >= latest_requeue.daily_limit:
                raise ActiveRunExists("", "guard")
            return start_requeue_fn(record=_record)

        from tools.ai_orchestrator.runstate import ActiveRunExists

        try:
            new_run_dir = _guarded_start()
        except ActiveRunExists:
            continue  # guard aborted (switch off / limit) or a genuine race: retried next cycle
        except Exception:  # noqa: BLE001 - a genuine rejection (C9): terminal, never shown raw text
            state.lineage_attempts[pending.lineage_root] = state.lineage_attempts.get(pending.lineage_root, 0) + 1
            state.record_daily_attempt(today)
            state.pending.pop(run_id, None)
            state.needs_human.add(run_id)
            write_run_log_entry(repo=repo, original_run_id=run_id, new_run_id="", attempt=pending.attempt,
                                outcome=LOG_RESULT_START_FAILED, log_dir=log_dir)
            continue

        new_run_id = Path(new_run_dir).name
        state.lineage_attempts[pending.lineage_root] = state.lineage_attempts.get(pending.lineage_root, 0) + 1
        state.record_daily_attempt(today)
        state.pending.pop(run_id, None)
        state.started.add(run_id)
        state.lineage_of[new_run_id] = pending.lineage_root
        write_run_log_entry(repo=repo, original_run_id=run_id, new_run_id=new_run_id, attempt=pending.attempt,
                            outcome=LOG_RESULT_STARTED, log_dir=log_dir)
        started.append((run_id, new_run_id))

    if started:
        return RequeueCycleOutcome(STATUS_STARTED, tuple(started))
    if stop_event is not None and stop_event.is_set():
        return RequeueCycleOutcome(STATUS_STOPPED)
    return RequeueCycleOutcome(STATUS_NOTHING_TO_DO)
