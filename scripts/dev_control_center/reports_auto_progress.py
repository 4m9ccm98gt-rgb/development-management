"""DCC Task 19c-2a: automatic RUN_DEV -> 自動承認 -> Task 19a's combined execution
(PUSH -> BUILD -> UPDATE-DRY-RUN), for a candidate Task 19c-1 (reports_auto_approve.py)
has already labelled 自動承認の対象 (ELIGIBLE), on an app whose Task 19c-1 per-app
permission is ON. RELEASE is never called from anywhere in this module -- the chain stops
after UPDATE-DRY-RUN's read-only plan, exactly where Task 19a's own combined button stops.

Screen display is Task 19c-2b's job; this module only keeps the fixed-word/number record a
later screen can read (write_run_log_entry / run_log_root), and the in-memory + best-effort
persisted counters/markers that make a cycle idempotent and bounded.

Security posture (same family as reports_auto.py / reports_auto_start.py / reports_auto_approve.py):
 - The five real actions (RUN_DEV, 自動承認, PUSH, BUILD, UPDATE-DRY-RUN's plan) are never a new
   execution method: the default stage runners call exactly the same plain functions the manual
   DCC buttons already invoke underneath their own subprocess wrapper (candidate.run_dev /
   candidate.approve / candidate.push, provenance.build, release_update.plan) -- the shared
   "処理本体" Task 19c-2a's spec asks for. No command list is ever assembled twice.
 - The candidate's full SHA and Orchestrator run_id are re-derived from candidate.latest_candidate
   (the same trusted source every DCC candidate screen uses), never from a report's own text, an
   AI's output, or a decision record's own display-only truncated SHA. A stored decision whose
   truncated `candidate` field does not prefix-match the live full SHA, or that has no run_id
   association at all, is never treated as a normal "not eligible" skip -- it is flagged
   人の確認が必要 and left alone (see _select_candidate).
 - 回数 (daily count) and 実行済み (attempted) markers are kept authoritative in *this process's*
   memory (ProgressState) for the whole DCC run, mirroring orchestrator_requeue.RequeueState's
   `daily_count`/`record_daily_attempt`: a save failure only ever risks the persisted mirror
   lagging behind, never the in-memory decision already made, so a candidate already attempted or
   a limit already reached this process can never be re-attempted / exceeded merely because a
   write failed. Unlike RequeueState, this module's persisted mirrors must be read *successfully*
   once before anything is allowed to run at all (ProgressState.seed_startup) -- a corrupt or
   unreadable prior file blocks every cycle (not just a decision) until a later read succeeds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

from . import activity_log
from . import reports_auto as auto
from . import reports_auto_approve as approve
from . import reports_auto_start as start
from . import reports_inbox as inbox

AUTO_PROGRESS_INTERVAL_SECONDS = 5 * 60

STATE_IN_PROGRESS = "自動で進行中"
STATE_RELEASE_READY = "RELEASE待ち"
STATE_NEEDS_HUMAN = "人の確認が必要"

LIMIT_REACHED_TEXT = "本日の自動承認の上限に達しました"
RECORD_KIND = "自動承認"

# DCC Task 19c-2b, 仕様1: fixed sentence shown once any report's own progress label (below) is
# currently STATE_RELEASE_READY -- never built from report or AI content.
RELEASE_READY_NOTICE_TEXT = "RELEASE の準備ができました"

STAGE_RUN_DEV = "RUN_DEV"
STAGE_APPROVE = "自動承認"
STAGE_PUSH = "PUSH"
STAGE_BUILD = "BUILD"
STAGE_DRY_RUN = "UPDATE-DRY-RUN"
STAGES = (STAGE_RUN_DEV, STAGE_APPROVE, STAGE_PUSH, STAGE_BUILD, STAGE_DRY_RUN)

RESULT_OK = "成功"
RESULT_FAIL = "失敗"

STATUS_DISABLED = "disabled"
STATUS_STARTUP_BLOCKED = "startup_blocked"
STATUS_LIMIT_REACHED = "limit_reached"
STATUS_DONE = "done"

RUN_LOG_MAX_FILES = 50


def _log_activity(*, action: str, target_type: str = activity_log.TARGET_NONE, target_id: str = "",
                   result: str = activity_log.RESULT_NONE, reason: str = activity_log.REASON_NONE,
                   path: Path | None = None) -> None:
    """Best-effort (DCC Task WF-6b): a logging failure must never affect the chain this module's
    own cycle has already decided (same contract as reports_auto_start._log_activity). `reason`,
    when given, is one of this module's own STAGE_* words (== activity_log.STAGE_* literally --
    same fixed vocabulary, never free text) so a 開始/完了/失敗 entry says which stage it is about."""
    try:
        activity_log.append(role=activity_log.ROLE_AUTO_APPROVE, action=action, target_type=target_type,
                             target_id=target_id, result=result, reason=reason, path=path)
    except activity_log.ActivityLogError:
        pass


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "auto_progress"


def daily_count_path() -> Path:
    return _root() / "daily_count.json"


def attempted_index_path() -> Path:
    return _root() / "attempted_index.json"


def run_log_root() -> Path:
    return _root() / "run_log"


def progress_labels_root() -> Path:
    return _root() / "labels"


# --------------------------------------------------------------------------- 実行済みキー

def _attempt_key(app_key: str, sha: str) -> str:
    """One-way: never reversible back to (app_key, sha) -- only ever used for membership tests
    against a key this same function computed from a value already in hand."""
    return hashlib.sha256(f"{app_key}\x00{sha.lower()}".encode("utf-8")).hexdigest()


def _read_daily_count_strict(today: str, path: Path | None) -> int:
    """Unlike reports_auto_start._read_daily_count, a file that exists but cannot be parsed into
    a valid {date, count} shape raises instead of degrading to 0 -- ProgressState.seed_startup
    treats that as a startup-block (C10), never as "nothing counted yet"."""
    if path is None or not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("daily_count.json: invalid shape")
    if data.get("date") != today:
        return 0
    count = data.get("count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("daily_count.json: invalid count")
    return count


def _read_attempted_index_strict(path: Path | None) -> set:
    if path is None or not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("attempted_index.json: invalid shape")
    entries = data.get("entries")
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ValueError("attempted_index.json: invalid entries")
    return set(entries)


class ProgressState:
    """Held by the caller for one DCC process's lifetime (same convention as
    orchestrator_requeue.RequeueState). `daily_count`/`attempted` are authoritative in memory once
    `seed_startup` has succeeded at least once; persistence to `daily_count_path`/
    `attempted_index_path` is best-effort and only ever a mirror -- a write failure never changes
    what this process itself already decided (C9)."""

    def __init__(self, *, daily_count_path: Path | None = None, attempted_index_path: Path | None = None) -> None:
        self._daily_count_path = daily_count_path
        self._attempted_index_path = attempted_index_path
        self._daily_date: str | None = None
        self._daily_count = 0
        self._attempted: set = set()
        self.startup_seeded = False
        self._lock = threading.Lock()

    def seed_startup(self, today: str) -> bool:
        """C10: must succeed (an existing file parses, or is simply absent) before anything may
        run. Idempotent and safe to call every cycle: once True, never re-reads disk again."""
        with self._lock:
            if self.startup_seeded:
                return True
            try:
                count = _read_daily_count_strict(today, self._daily_count_path)
                attempted = _read_attempted_index_strict(self._attempted_index_path)
            except Exception:  # noqa: BLE001 - any parse/OS trouble blocks until a later success
                return False
            self._daily_date, self._daily_count = today, count
            self._attempted = attempted
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
            except OSError:  # noqa: BLE001 - C9: a save failure must never undo the count above
                pass
        return total

    def has_attempted(self, app_key: str, sha: str) -> bool:
        with self._lock:
            return _attempt_key(app_key, sha) in self._attempted

    def mark_attempted(self, app_key: str, sha: str) -> None:
        key = _attempt_key(app_key, sha)
        with self._lock:
            self._attempted.add(key)  # memory first -- authoritative even if the write below fails
            snapshot = sorted(self._attempted)
        if self._attempted_index_path is not None:
            try:
                start._write_json_atomic(self._attempted_index_path, {"entries": snapshot})
            except OSError:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- 排他（デフォルト実装）

_DEFAULT_RESERVATIONS: dict = {}
_DEFAULT_RESERVATIONS_LOCK = threading.Lock()


def _default_reserve(repo_name: str) -> object | None:
    with _DEFAULT_RESERVATIONS_LOCK:
        if repo_name in _DEFAULT_RESERVATIONS:
            return None
        token = object()
        _DEFAULT_RESERVATIONS[repo_name] = token
        return token


def _default_release(repo_name: str, token: object | None) -> None:
    if token is None:
        return
    with _DEFAULT_RESERVATIONS_LOCK:
        if _DEFAULT_RESERVATIONS.get(repo_name) is token:
            del _DEFAULT_RESERVATIONS[repo_name]


def _default_busy(repo_name: str) -> bool:
    return False


# --------------------------------------------------------------------------- 既定のstage実装
# Every default below calls exactly the plain function the manual DCC buttons' own subprocess
# ultimately runs (candidate.run_dev/approve/push, provenance.build, release_update.plan) --
# never a re-assembled command line, never a new execution path.

def _default_run_dev(repo_dir: Path, branch: str, sha: str) -> bool:
    from . import candidate

    try:
        return candidate.run_dev(repo_dir, branch, sha) == 0
    except Exception:  # noqa: BLE001 - any stop here is simply a failed stage
        return False


def _default_approve(candidate_obj, sha: str) -> bool:
    from . import candidate

    try:
        candidate.approve(candidate_obj, sha)
        return True
    except Exception:  # noqa: BLE001
        return False


def _default_push(repo_dir: Path, branch: str, sha: str) -> bool:
    from . import candidate

    try:
        candidate.push(repo_dir, branch, sha)
        return True
    except Exception:  # noqa: BLE001
        return False


def _default_build(repo_dir: Path, definition, candidate_obj) -> bool:
    from . import provenance, entrypoints as machine_entries
    from .core import discover_entrypoints

    try:
        profile = provenance.PROFILES.get(definition.name)
        if not profile:
            return False  # no folder dialog is possible automatically (仕様1: 新しい実行方法は作らない)
        artifact = (repo_dir / profile[0]).resolve()
        if not machine_entries.supported(repo_dir, "build"):
            return False
        entries = discover_entrypoints(repo_dir, definition.repo_type,
                                       application_implemented=definition.application_implemented)
        choice = entries.build
        if not choice.ready or not choice.path:
            return False
        result = provenance.build(repo_dir, choice.path, artifact, expected_sha=candidate_obj.sha,
                                   candidate_run_id=candidate_obj.run_id, expected_branch=definition.branch)
        return result.get("status") == "ready"
    except Exception:  # noqa: BLE001
        return False


def _default_dry_run(repo_dir: Path, definition, candidate_obj) -> bool:
    from . import release_update, provenance
    from . import candidate as candidate_flow

    try:
        production = candidate_flow._read_json(provenance.production_record_path(repo_dir.resolve())) or {}
        target = production.get("target")
        if not isinstance(target, str) or not target:
            return False  # no folder dialog automatically -- only a known production target counts
        plan_path = release_update.plans_dir(repo_dir.resolve()) / f"auto-plan-{time.strftime('%Y%m%d_%H%M%S')}.json"
        body = release_update.plan(repo_dir, Path(target), branch=definition.branch, out=plan_path, emit=lambda *_a: None)
        return not body.get("stop_reasons")
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- 仕様3: 実行ごとの記録

def _display_safe_app(app_key: str) -> str:
    return app_key if isinstance(app_key, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", app_key) else "不明"


def _display_safe_sha(sha: str | None) -> str:
    return sha[:12].lower() if isinstance(sha, str) and approve._sha(sha) else "不明"


def _write_log_entry(*, log_dir: Path | None, app_key: str, sha: str | None, state_word: str,
                      stages: dict, failed_stage: str, files, lines) -> None:
    try:
        directory = log_dir if log_dir is not None else run_log_root()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kind": RECORD_KIND,
            "app": _display_safe_app(app_key),
            "candidate": _display_safe_sha(sha),
            "state": state_word,
            "stages": dict(stages),
            "failed_stage": failed_stage,
            "files": files if type(files) is int and files >= 0 else "不明",
            "lines": lines if type(lines) is int and lines >= 0 else "不明",
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        seq = start._next_log_sequence()
        start._write_json_atomic(directory / f"{stamp}-{seq:010d}.json", payload)
        start._prune_old_logs(directory, RUN_LOG_MAX_FILES)
    except OSError:  # noqa: BLE001 - logging must never affect the outcome already computed
        pass


# --------------------------------------------------------------------------- DCC Task 19c-2b: 画面表示用ラベル
# A best-effort, per-report mirror of this cycle's own state_word/failed_stage -- written purely
# for reports_inbox_view.py's own「自動調査の結果」column. Never read back by this module itself
# (the chain's own candidate/skip/retry decisions stay keyed by (app_key, sha) via ProgressState,
# exactly as before); a write failure here can never affect the chain already decided, and the
# run log's own payload shape (tested by test_record_is_fixed_words_and_numbers_only_and_marked_
# auto_approval) is untouched -- this is a separate file, not a new key on that payload.

def _label_path(app_key: str, report_id: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else progress_labels_root()
    return base / start._hash(app_key) / f"{start._hash(report_id)}.json"


def _write_progress_label(*, root: Path | None, app_key: str, report_id: str,
                          state_word: str, failed_stage: str) -> None:
    try:
        start._write_json_atomic(_label_path(app_key, report_id, root=root), {
            "state": state_word, "failed_stage": failed_stage,
        })
    except OSError:  # noqa: BLE001 - display-only write; never affects the chain already decided
        pass


def format_progress_label(state_word: str, failed_stage: str) -> str:
    return f"{state_word}（{failed_stage}）" if failed_stage else state_word


def load_progress_label(app_key: str, report_id: str, *, root: Path | None = None) -> str:
    """表示用の読み込み（仕様2）: state/failed_stage は固定の語に限定し、知らない値は
    STATE_NEEDS_HUMAN にする。記録が無い、または壊れていて読めないときは "" (空) -- 次の更新で
    記録が直れば自然に回復する。例外は投げない -- start._read_json 自身が捕まえない例外（深く
    ネストした JSON による RecursionError など）も、ここで安全な表示に変換する。呼び出し側
    (reports_inbox_view._tick) は、この関数が例外を外に出さないことに頼って次の定期更新を
    必ず予約できる。"""
    try:
        data = start._read_json(_label_path(app_key, report_id, root=root))
    except Exception:  # noqa: BLE001 - 表示専用の読み込み。失敗は空 (記録が直れば次回回復)
        return ""
    if data is None:
        return ""
    if not isinstance(data, dict):
        return STATE_NEEDS_HUMAN
    state_word = data.get("state")
    if state_word not in (STATE_IN_PROGRESS, STATE_RELEASE_READY, STATE_NEEDS_HUMAN):
        return STATE_NEEDS_HUMAN
    failed_stage = data.get("failed_stage", "")
    if failed_stage and failed_stage not in STAGES:
        return STATE_NEEDS_HUMAN
    return format_progress_label(state_word, failed_stage)


def load_progress_labels(identities, *, root: Path | None = None) -> dict:
    """Mirrors reports_auto_start.load_auto_start_records: {identity: label} for every report
    that already has one -- used by the inbox list's own column (DCC Task 19c-2b)."""
    out: dict = {}
    for app_key, report_id in identities:
        label = load_progress_label(app_key, report_id, root=root)
        if label:
            out[(app_key, report_id)] = label
    return out


def limit_notice(global_config: "auto.AutoModeConfig", approve_config: "approve.ApprovalConfig",
                  state: "ProgressState", today: str) -> str:
    """DCC Task 19c-2b, 仕様1: the fixed LIMIT_REACHED_TEXT sentence for the reports inbox
    window's own notice label, mirroring orchestrator_requeue.limit_notice -- reads only this
    process's own in-memory ProgressState (the one app.py keeps for its whole life), never the
    persisted mirror file directly."""
    if global_config.enabled and state.limit_reached(today, approve_config.daily_limit):
        return LIMIT_REACHED_TEXT
    return ""


# --------------------------------------------------------------------------- 候補の選択（C11）

def _current(config, path, loader):
    return config if path is None else loader(path)


def _select_candidate(app_key: str, reports: list, state: ProgressState, *, records_dir, results_dir,
                      resolve_repo_dir, resolve_repo_definition, latest_candidate_fn, log_dir, labels_dir=None):
    """Returns (repo_dir, definition, candidate_obj, sha, decision, report_id) for the first
    report of this app that is 自動承認の対象 (ELIGIBLE), has a sound Task 18 association, and
    whose full SHA the live Orchestrator candidate itself (not the decision's own display-only
    truncated field) confirms -- or None when this app has nothing new to do this cycle. A broken
    association / missing run_id / stale decision is never silently skipped like an ordinary
    non-candidate: it is recorded 人の確認が必要 (C11) and left for a human, without consuming a
    実行済み marker (there is no SHA trustworthy enough yet to key one). report_id is also used
    to mirror the fixed state word onto DCC Task 19c-2b's own per-report display label."""
    def flag_needs_human(report_id: str) -> None:
        _write_log_entry(log_dir=log_dir, app_key=app_key, sha=None, state_word=STATE_NEEDS_HUMAN,
                         stages={}, failed_stage="", files=None, lines=None)
        _write_progress_label(root=labels_dir, app_key=app_key, report_id=report_id,
                              state_word=STATE_NEEDS_HUMAN, failed_stage="")

    for report in reports:
        directory = results_dir if results_dir is not None else approve.root() / "results"
        payload = start._read_json(approve._result_path(app_key, report.report_id, directory))
        if payload is None:
            flag_needs_human(report.report_id)  # 判定の欠落 (C11): never a silent "not a candidate" skip
            continue
        decision = approve._payload_decision(payload)
        if decision is None:
            flag_needs_human(report.report_id)  # 不正な payload (C11)
            continue
        if decision.reasons:
            continue  # 人の確認が必要 by Task 19c-1's own evaluation -- normal, not eligible

        association = start.load_auto_start_record(app_key, report.report_id, root=records_dir)
        if association is None or not association.run_id:
            flag_needs_human(report.report_id)
            continue

        try:
            repo_dir = resolve_repo_dir(app_key)
        except Exception:  # noqa: BLE001 - registry trouble: wait, do not flag as broken
            repo_dir = None
        if repo_dir is None:
            continue
        try:
            definition = resolve_repo_definition(repo_dir.name)
        except Exception:  # noqa: BLE001
            definition = None
        if definition is None:
            continue

        try:
            current = latest_candidate_fn(repo_dir)
        except Exception:  # noqa: BLE001 - transient git trouble: wait, do not flag as broken
            current = None
        if current is None or current.run_id != association.run_id:
            flag_needs_human(report.report_id)
            continue

        sha = current.sha
        # Strict match (C11): the decision's own full SHA and run_id -- never the display-only
        # truncated `candidate` field and never a prefix test -- must equal the live candidate's.
        # A decision recorded before these fields existed, or carrying only the short field, is
        # never treated as still applicable; it is flagged exactly like a broken association.
        raw_candidate_full = payload.get("candidate_full")
        raw_run_id = payload.get("run_id")
        if (not isinstance(raw_candidate_full, str) or not approve._sha(raw_candidate_full)
                or not isinstance(raw_run_id, str) or not raw_run_id or raw_run_id == "不明"
                or raw_candidate_full.lower() != sha.lower() or raw_run_id != current.run_id
                or raw_run_id != association.run_id):
            flag_needs_human(report.report_id)
            continue

        if state.has_attempted(app_key, sha):
            continue

        return repo_dir, definition, current, sha, decision, report.report_id
    return None


# --------------------------------------------------------------------------- 1候補分の実行（仕様1/2）

def _process_candidate(app_key: str, repo_dir: Path, definition, candidate_obj, sha: str, decision,
                       state: ProgressState, today: str, *, report_id: str, active_runs_fn, busy_fn, reserve_fn,
                       release_fn, run_dev_fn, approve_fn, push_fn, build_fn, dry_run_fn, latest_candidate_fn,
                       log_dir, labels_dir, global_config, start_config, approve_config,
                       global_config_path, start_config_path, approve_config_path,
                       activity_log_path: Path | None = None) -> None:
    repo_name = repo_dir.name
    report_target_id = start._hash(report_id)

    try:
        busy_run = bool(active_runs_fn(str(repo_dir)))
    except Exception:  # noqa: BLE001 - C12: 確認できないときも進まない
        busy_run = True
    if busy_run or busy_fn(repo_name):
        return  # wait: never a real attempt, no 実行済み marker, nothing to release

    token = reserve_fn(repo_name)
    if token is None:
        return  # 予約が競合: wait for the next cycle

    stages: dict = {}
    current_stage = ""  # set right before each gate+stage pair; read back if an exception escapes
    try:
        # Past this point a real attempt begins: C3/C4/C8's 実行済み marker is written *before*
        # any stage runs, so a crash mid-chain can never lead to a second attempt at this SHA.
        state.mark_attempted(app_key, sha)
        state.record_daily_attempt(today)
        # 仕様3: the chain's own in-progress record, so a reader of the log sees 自動で進行中
        # while the stages below are still running -- always followed by exactly one terminal
        # record (RELEASE待ち or 人の確認が必要) below, never left as the last word on this SHA.
        _write_log_entry(log_dir=log_dir, app_key=app_key, sha=sha, state_word=STATE_IN_PROGRESS,
                         stages={}, failed_stage="", files=decision.files, lines=decision.lines)
        _write_progress_label(root=labels_dir, app_key=app_key, report_id=report_id,
                              state_word=STATE_IN_PROGRESS, failed_stage="")

        def boundary_ok() -> bool:
            g = _current(global_config, global_config_path, auto.load_auto_mode_config)
            s = _current(start_config, start_config_path, start.load_auto_start_config)
            a = _current(approve_config, approve_config_path, lambda p: approve.load_config(p, start_config=s))
            return approve.allowed(app_key, g, s, a)

        def sha_unchanged() -> bool:
            try:
                latest = latest_candidate_fn(repo_dir)
            except Exception:  # noqa: BLE001
                return False
            return latest is not None and latest.sha == sha and latest.run_id == candidate_obj.run_id

        def finalize(state_word: str, failed_stage: str) -> None:
            _write_log_entry(log_dir=log_dir, app_key=app_key, sha=sha, state_word=state_word, stages=stages,
                             failed_stage=failed_stage, files=decision.files, lines=decision.lines)
            _write_progress_label(root=labels_dir, app_key=app_key, report_id=report_id,
                                  state_word=state_word, failed_stage=failed_stage)

        # Every stage, including RUN_DEV, is gated by a fresh re-read of the app's permission,
        # the global stop switch and the full SHA/run_id -- never just the state this candidate
        # was picked with at the top of the cycle (C5/C6).
        stage_calls = (
            (STAGE_RUN_DEV, lambda: run_dev_fn(repo_dir, definition.branch, sha)),
            (STAGE_APPROVE, lambda: approve_fn(candidate_obj, sha)),
            (STAGE_PUSH, lambda: push_fn(repo_dir, definition.branch, sha)),
            (STAGE_BUILD, lambda: build_fn(repo_dir, definition, candidate_obj)),
            (STAGE_DRY_RUN, lambda: dry_run_fn(repo_dir, definition, candidate_obj)),
        )
        for stage_name, call_stage in stage_calls:
            current_stage = stage_name
            # DCC Task WF-6b 仕様1: 各段階の開始・完了・失敗の記録点 -- 段階そのものの判断/結果は
            # 変えない。段階名は activity_log.STAGE_* と同じ固定語として reason に乗る（自由文では
            # なく、既存の STAGE_RUN_DEV/STAGE_APPROVE/STAGE_PUSH/STAGE_BUILD/STAGE_DRY_RUN と同じ
            # 文字列そのもの）。
            _log_activity(action=activity_log.ACTION_START, target_type=activity_log.TARGET_REPORT,
                          target_id=report_target_id, reason=current_stage, path=activity_log_path)
            if not boundary_ok() or not sha_unchanged():
                _log_activity(action=activity_log.ACTION_FAIL, target_type=activity_log.TARGET_REPORT,
                              target_id=report_target_id, result=activity_log.RESULT_NEEDS_HUMAN,
                              reason=current_stage, path=activity_log_path)
                finalize(STATE_NEEDS_HUMAN, current_stage)
                return
            ok = call_stage()
            stages[current_stage] = RESULT_OK if ok else RESULT_FAIL
            _log_activity(action=activity_log.ACTION_COMPLETE if ok else activity_log.ACTION_FAIL,
                          target_type=activity_log.TARGET_REPORT, target_id=report_target_id,
                          result=activity_log.RESULT_NONE if ok else activity_log.RESULT_NEEDS_HUMAN,
                          reason=current_stage, path=activity_log_path)
            if not ok:
                finalize(STATE_NEEDS_HUMAN, current_stage)
                return

        # DCC Task WF-6b 仕様1: RELEASE待ちの記録点。
        _log_activity(action=activity_log.ACTION_COMPLETE, target_type=activity_log.TARGET_REPORT,
                      target_id=report_target_id, result=activity_log.RESULT_CANDIDATE, path=activity_log_path)
        finalize(STATE_RELEASE_READY, "")
    except Exception:  # noqa: BLE001 - 仕様1: 例外も「失敗」。自動で進行中のまま残さない
        if current_stage and current_stage not in stages:
            stages[current_stage] = RESULT_FAIL
        _log_activity(action=activity_log.ACTION_FAIL, target_type=activity_log.TARGET_REPORT,
                      target_id=report_target_id, result=activity_log.RESULT_NEEDS_HUMAN,
                      reason=current_stage, path=activity_log_path)
        _write_log_entry(log_dir=log_dir, app_key=app_key, sha=sha, state_word=STATE_NEEDS_HUMAN,
                         stages=stages, failed_stage=current_stage, files=decision.files, lines=decision.lines)
        _write_progress_label(root=labels_dir, app_key=app_key, report_id=report_id,
                              state_word=STATE_NEEDS_HUMAN, failed_stage=current_stage)
    finally:
        release_fn(repo_name, token)


# --------------------------------------------------------------------------- 既定の協力者

def _default_resolve_repo_dir(app_key: str):
    from tools.ai_orchestrator.orchestrator import resolve_repo_dir_for_app

    return resolve_repo_dir_for_app(app_key)


def _default_resolve_repo_definition(repo_name: str):
    from tools.ai_orchestrator.orchestrator import resolve_repo_definition

    return resolve_repo_definition(repo_name)


def _default_active_runs(repo: str) -> list:
    from tools.ai_orchestrator import runstate

    return runstate.active_runs(repo=repo)


def _default_latest_candidate(repo_dir: Path):
    from . import candidate

    return candidate.latest_candidate(repo_dir)


@dataclass(frozen=True)
class ProgressCycleOutcome:
    status: str
    message: str = ""


def run_auto_progress_once(
    *,
    state: ProgressState,
    global_config: "auto.AutoModeConfig | None" = None,
    global_config_path: Path | None = None,
    start_config: "start.AutoStartConfig | None" = None,
    start_config_path: Path | None = None,
    approve_config: "approve.ApprovalConfig | None" = None,
    approve_config_path: Path | None = None,
    today: str | None = None,
    reports_config_fn: Callable[[], "inbox.ReportsConfig"] | None = None,
    scan_fn: Callable[[list], list] | None = None,
    records_dir: Path | None = None,
    results_dir: Path | None = None,
    resolve_repo_dir: Callable[[str], Path | None] | None = None,
    resolve_repo_definition: Callable[[str], object] | None = None,
    active_runs_fn: Callable[[str], list] | None = None,
    latest_candidate_fn: Callable[[Path], object | None] | None = None,
    busy_fn: Callable[[str], bool] | None = None,
    reserve_fn: Callable[[str], object | None] | None = None,
    release_fn: Callable[[str, object | None], None] | None = None,
    run_dev_fn: Callable[[Path, str, str], bool] | None = None,
    approve_fn: Callable[[object, str], bool] | None = None,
    push_fn: Callable[[Path, str, str], bool] | None = None,
    build_fn: Callable[[Path, object, object], bool] | None = None,
    dry_run_fn: Callable[[Path, object, object], bool] | None = None,
    log_dir: Path | None = None,
    labels_dir: Path | None = None,
    activity_log_path: Path | None = None,
    stop_event: threading.Event | None = None,
) -> ProgressCycleOutcome:
    """Run one cycle (C1-C14). Each app is considered independently (仕様1: 他アプリを妨げない):
    one app waiting on a busy repository, a reservation conflict, or an unconfirmable Orchestrator
    Run never stops another app's own eligible candidate from proceeding the same cycle. The
    global stop switch and the daily limit (shared across every app, Task 19c-1's own
    daily_limit) are the two exceptions that stop the whole cycle outright."""
    global_config = global_config if global_config is not None else auto.load_auto_mode_config(global_config_path)
    if not global_config.enabled:
        return ProgressCycleOutcome(STATUS_DISABLED)

    today = today if today is not None else auto.today_str()
    if not state.seed_startup(today):
        return ProgressCycleOutcome(STATUS_STARTUP_BLOCKED)

    start_config = start_config if start_config is not None else start.load_auto_start_config(start_config_path)
    approve_config = (approve_config if approve_config is not None
                      else approve.load_config(approve_config_path, start_config=start_config))

    if state.limit_reached(today, approve_config.daily_limit):
        _write_log_entry(log_dir=log_dir, app_key="不明", sha=None, state_word=LIMIT_REACHED_TEXT,
                         stages={}, failed_stage="", files=None, lines=None)
        _log_activity(action=activity_log.ACTION_LIMIT, path=activity_log_path)
        return ProgressCycleOutcome(STATUS_LIMIT_REACHED, LIMIT_REACHED_TEXT)

    reports_config_fn = reports_config_fn or inbox.load_reports_config
    scan_fn = scan_fn or inbox.scan_all
    resolve_repo_dir = resolve_repo_dir or _default_resolve_repo_dir
    resolve_repo_definition = resolve_repo_definition or _default_resolve_repo_definition
    active_runs_fn = active_runs_fn or _default_active_runs
    latest_candidate_fn = latest_candidate_fn or _default_latest_candidate
    busy_fn = busy_fn or _default_busy
    reserve_fn = reserve_fn or _default_reserve
    release_fn = release_fn or _default_release
    run_dev_fn = run_dev_fn or _default_run_dev
    approve_fn = approve_fn or _default_approve
    push_fn = push_fn or _default_push
    build_fn = build_fn or _default_build
    dry_run_fn = dry_run_fn or _default_dry_run

    reports_cfg = reports_config_fn()
    apps_meta = [(a.app_key, a.display_name, a.shared_root) for a in reports_cfg.apps]
    inboxes = scan_fn(apps_meta)
    reports = inbox.all_reports(inboxes)

    by_app: dict = {}
    for report in reports:
        by_app.setdefault(report.app_key, []).append(report)

    for app_key, app_reports in by_app.items():
        if stop_event is not None and stop_event.is_set():
            break
        cur_global = _current(global_config, global_config_path, auto.load_auto_mode_config)
        if not cur_global.enabled:
            break  # 仕様1: 全体の停止スイッチOFFは即座に全体を止める
        cur_start = _current(start_config, start_config_path, start.load_auto_start_config)
        cur_approve = _current(approve_config, approve_config_path,
                               lambda p, _s=cur_start: approve.load_config(p, start_config=_s))
        if state.limit_reached(today, cur_approve.daily_limit):
            _log_activity(action=activity_log.ACTION_LIMIT, path=activity_log_path)
            break  # 共有の1日の上限
        if not approve.allowed(app_key, cur_global, cur_start, cur_approve):
            continue  # このアプリは対象外。他アプリは妨げない

        picked = _select_candidate(app_key, app_reports, state, records_dir=records_dir, results_dir=results_dir,
                                   resolve_repo_dir=resolve_repo_dir, resolve_repo_definition=resolve_repo_definition,
                                   latest_candidate_fn=latest_candidate_fn, log_dir=log_dir, labels_dir=labels_dir)
        if picked is None:
            continue
        repo_dir, definition, candidate_obj, sha, decision, report_id = picked

        _process_candidate(
            app_key, repo_dir, definition, candidate_obj, sha, decision, state, today,
            report_id=report_id, active_runs_fn=active_runs_fn, busy_fn=busy_fn, reserve_fn=reserve_fn,
            release_fn=release_fn, run_dev_fn=run_dev_fn, approve_fn=approve_fn, push_fn=push_fn,
            build_fn=build_fn, dry_run_fn=dry_run_fn, latest_candidate_fn=latest_candidate_fn,
            log_dir=log_dir, labels_dir=labels_dir, global_config=cur_global,
            start_config=cur_start, approve_config=cur_approve,
            global_config_path=global_config_path, start_config_path=start_config_path,
            approve_config_path=approve_config_path, activity_log_path=activity_log_path,
        )

    return ProgressCycleOutcome(STATUS_DONE)
