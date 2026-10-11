"""DCC Task 18: automatic second-stage start -- only a report Task 17's automatic triage
(reports_auto.py) already bucketed as 自動で進めてよい (OUTCOME_PROCEED) may be started
automatically, through the same entry point Task 14.5's human-pressed 作成して開始 button uses
(reports_create_and_start.create_and_start). This module only decides *whether* to call that
entry point and records the fixed-word outcome; it never approves, pushes, builds or deploys
anything, and it stops at "a candidate branch exists" -- exactly where Task 14.5 already stops.

Security posture (same family as reports_auto.py / reports_create_and_start.py):
 - Every acceptance criterion written into the spec file this module creates is one of the fixed
   Japanese sentences in FIXED_CRITERIA below -- never report text, never the AI's own free-text
   investigation output (Task 17's own AutoTriageRecord never even stores that output; see its
   module docstring), so there is nothing untrusted left to smuggle into a path, a command, or a
   criterion.
 - The repository is decided only by resolve_repo_dir (defaulting to DCC's own registry lookup,
   orchestrator.resolve_repo_dir_for_app, keyed by the report's own app_key -- itself assigned by
   DCC's own config scan, never read from report content) -- the same rule every DCC Task
   14/14.5/17 module already follows.
 - Automatic start additionally requires a *separate* per-app permission (AutoStartConfig.apps,
   initial OFF for every app) on top of Task 17's own global switch (reused unchanged here, never
   duplicated) and that app's Task 17 "自動調査を許可" permission (implied by there being an
   OUTCOME_PROCEED record at all). The global switch, this module's own per-app permission, and
   the daily limit are re-read twice more after the top-of-cycle check: once right after the
   eligible report is chosen (the same re-check pattern Task 17's Reviewer finding introduced for
   run_auto_triage_once), and again inside a guard wired into the real Orchestrator start itself
   (see run_auto_start_once's own docstring) -- so a human (or DCC shutting down) flipping any of
   the three mid-cycle, even during create_and_start_fn's own spec-file creation, still stops the
   one start attempt a cycle may make, before it reaches the Orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Callable, Iterable

from . import reports_auto as auto
from . import reports_create_and_start as cas
from . import reports_inbox as inbox

DEFAULT_DAILY_LIMIT = 3
AUTO_START_INTERVAL_SECONDS = 5 * 60

LIMIT_REACHED_TEXT = "本日の自動開始の上限に達しました"

STATUS_DISABLED = "disabled"
STATUS_LIMIT_REACHED = "limit_reached"
STATUS_NOTHING_TO_DO = "nothing_to_do"
STATUS_WAITING = "waiting"
STATUS_STARTED = "started"
STATUS_START_FAILED = "start_failed"
STATUS_STOPPED = "stopped"

# 仕様4: the two fixed result words the inbox's existing「自動調査の結果」column shows once a
# Run this module started has reached a terminal stage -- never the Run's own final message.
RESULT_PENDING = ""
RESULT_CANDIDATE = "候補あり"
RESULT_NEEDS_HUMAN = "人の確認が必要"

# 仕様2: shown for a report that is eligible but currently held back -- its target repository
# already has an active run, or this cycle's final pre-start guard aborted the one attempt this
# cycle was allowed to make. Display-only: unlike AutoStartRecord, a waiting mark never gates
# already_started -- the report is picked up again next cycle (see mark_waiting/clear_waiting).
RESULT_WAITING = "待機中"

# tools.ai_orchestrator.runstate's own fixed stage vocabulary (COMPLETED / NEEDS_HUMAN / FAILED /
# STOPPED) -- duplicated here as plain strings rather than importing runstate at module load time,
# the same lazy-import convention every other DCC Task 14+ module already follows for the
# Orchestrator package.
_RESULT_FOR_STAGE = {
    "completed": RESULT_CANDIDATE,
    "needs_human": RESULT_NEEDS_HUMAN,
    "failed": RESULT_NEEDS_HUMAN,
    "stopped": RESULT_NEEDS_HUMAN,
}

LOG_RESULT_STARTED = "開始"
LOG_RESULT_START_FAILED = "開始失敗"

RUN_LOG_MAX_FILES = 50

# 仕様3: the fixed acceptance-criteria template, used for every automatic start -- never report
# text, never Task 17's own (never-persisted) AI investigation output. The "AIの推測（未確認）"
# line is itself a fixed sentence: this module has no AI-suggested location to show in the first
# place (Task 17's AutoTriageRecord stores only fixed words/numbers), so the honest, always-true
# statement is written instead of ever inventing or guessing one.
FIXED_CRITERIA = (
    "先に、報告の症状を再現する自動テストを追加し、修正前のコードでそのテストが失敗することを確認すること。",
    "再現するテストが書けない、または修正前に失敗しない場合は、修正をせず、その理由を最終報告に書いて、"
    "人の判断に回すこと（変更を残さない）。",
    "修正後は、追加した再現テストが成功し、既存のテストが変わらず通ること。",
    "変更は、再現と修正に必要な最小限のファイルにとどめること（目安: 5 ファイルまで。それを超える必要が"
    "あるときは、止めて人の判断に回す）。",
    "AIの推測（未確認）: 自動開始の仕組みは調査結果の詳細（修正箇所の候補など）を保存しないため、"
    "修正箇所は未確認。",
    "最終報告に、確認できたことと、実機で確認が必要なことを分けて書くこと。",
)

_SCOPE_NOTE = "承認・PUSH・ビルド・配布・報告への返信"


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "auto_start"


def auto_start_config_path() -> Path:
    return _root() / "config.json"


def _daily_count_path() -> Path:
    return _root() / "daily_count.json"


def records_root() -> Path:
    return _root() / "records"


def run_log_root() -> Path:
    return _root() / "run_log"


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


# --------------------------------------------------------------------------- 仕様1: 設定（自動開始）

@dataclass(frozen=True)
class AutoStartConfig:
    """apps: app_key -> 自動開始の許可（初期値、未記載は全アプリOFF）。daily_limit: 1日あたりの
    自動開始の回数（初期値3）。The global stop switch is deliberately *not* duplicated here -- it
    is reports_auto.AutoModeConfig.enabled, read fresh wherever this module needs it."""

    apps: dict = field(default_factory=dict)
    daily_limit: int = DEFAULT_DAILY_LIMIT


def app_start_allowed(global_config: "auto.AutoModeConfig", start_config: AutoStartConfig, app_key: str) -> bool:
    """C1: the shared global switch (reports_auto.AutoModeConfig.enabled) and this module's own
    per-app permission must both be ON. Task 17's own per-app「自動調査を許可」is not re-checked
    here: a report cannot have an OUTCOME_PROCEED record at all unless that permission was ON when
    it was investigated (see _eligible_report)."""
    return bool(global_config.enabled) and bool(start_config.apps.get(app_key, False))


def load_auto_start_config(path: Path | None = None) -> AutoStartConfig:
    """Never raises: a missing or unreadable/corrupt file degrades to all-OFF defaults."""
    data = _read_json(path if path is not None else auto_start_config_path())
    if data is None:
        return AutoStartConfig()
    apps_raw = data.get("apps")
    apps = {str(k): bool(v) for k, v in apps_raw.items()} if isinstance(apps_raw, dict) else {}
    try:
        daily_limit = int(data.get("daily_limit", DEFAULT_DAILY_LIMIT))
    except (TypeError, ValueError):
        daily_limit = DEFAULT_DAILY_LIMIT
    return AutoStartConfig(apps=apps, daily_limit=daily_limit)


def save_auto_start_config(config: AutoStartConfig, path: Path | None = None) -> None:
    target = path if path is not None else auto_start_config_path()
    _write_json_atomic(target, {"apps": dict(config.apps), "daily_limit": config.daily_limit})


def set_app_start_allowed(app_key: str, allowed: bool, *, path: Path | None = None) -> AutoStartConfig:
    """Read-modify-write one app's permission (DCC画面のチェックボックス用)."""
    config = load_auto_start_config(path)
    apps = dict(config.apps)
    apps[app_key] = bool(allowed)
    updated = AutoStartConfig(apps=apps, daily_limit=config.daily_limit)
    save_auto_start_config(updated, path)
    return updated


# --------------------------------------------------------------------------- 仕様1: 1日の上限

def _read_daily_count(today: str, path: Path | None = None) -> int:
    data = _read_json(path if path is not None else _daily_count_path())
    if data is None or data.get("date") != today:
        return 0
    try:
        return int(data.get("count", 0))
    except (TypeError, ValueError):
        return 0


def _increment_daily_count(today: str, path: Path | None = None) -> int:
    target = path if path is not None else _daily_count_path()
    count = _read_daily_count(today, target) + 1
    _write_json_atomic(target, {"date": today, "count": count})
    return count


def daily_limit_reached(config: AutoStartConfig, today: str, *, path: Path | None = None) -> bool:
    return _read_daily_count(today, path) >= config.daily_limit


# --------------------------------------------------------------------------- 仕様2: 開始済みの記録

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_path(app_key: str, report_id: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else records_root()
    return base / _hash(app_key) / f"{_hash(report_id)}.json"


@dataclass(frozen=True)
class AutoStartRecord:
    """app_key/report_id are the caller's own already-known identity (never read back from the
    stored file, same convention as reports_auto.AutoTriageRecord): report_id is report-derived,
    untrusted free-form text, so the file on disk never holds it in the clear, only its sha256
    digest. run_id is DCC's own Orchestrator-generated identifier (never report- or AI-derived) --
    "" when the start attempt itself failed before a run existed. result is one of RESULT_* above,
    RESULT_PENDING until a later cycle sees the run reach a terminal stage."""

    app_key: str
    report_id: str
    started_at: str
    run_id: str = ""
    result: str = RESULT_PENDING


def _save_record(record: AutoStartRecord, *, root: Path | None = None) -> None:
    _write_json_atomic(_record_path(record.app_key, record.report_id, root=root), {
        "report_id_hash": _hash(record.report_id), "started_at": record.started_at,
        "run_id": record.run_id, "result": record.result,
    })


def load_auto_start_record(app_key: str, report_id: str, *, root: Path | None = None) -> AutoStartRecord | None:
    data = _read_json(_record_path(app_key, report_id, root=root))
    if data is None:
        return None
    try:
        return AutoStartRecord(
            app_key=app_key, report_id=report_id, started_at=str(data["started_at"]),
            run_id=str(data.get("run_id", "")), result=str(data.get("result", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_auto_start_records(identities: Iterable[tuple[str, str]], *,
                             root: Path | None = None) -> dict[tuple[str, str], AutoStartRecord]:
    """Mirrors reports_auto.load_auto_results: {identity: record} for every report that already
    has one -- used both to skip an already-started report and for the inbox list's own column."""
    out: dict[tuple[str, str], AutoStartRecord] = {}
    for app_key, report_id in identities:
        record = load_auto_start_record(app_key, report_id, root=root)
        if record is not None:
            out[(app_key, report_id)] = record
    return out


def already_started(app_key: str, report_id: str, *, root: Path | None = None) -> bool:
    """C3/C4: a record exists -- the report is never auto-started a second time, which is also how
    a failed start is never retried (仕様2). The record is written as a reservation *before*
    create_and_start_fn is ever called (see run_auto_start_once), so a crash mid-start can never
    lead to the same report being started twice; it is only deleted again (via _delete_record) when
    the attempt turns out not to have happened at all (target repo busy, or this cycle's final
    pre-start guard aborted) -- never after a genuine success or a genuine Orchestrator failure. A
    report that only hit STATUS_WAITING never reaches this point with a record, by design -- it is
    picked again next cycle instead."""
    return load_auto_start_record(app_key, report_id, root=root) is not None


def _delete_record(app_key: str, report_id: str, *, root: Path | None = None) -> None:
    """Undo an in-flight reservation (仕様2/C3/C6): called only when create_and_start_fn reports
    the target was never actually started (a genuine Orchestrator race, or this module's own
    pre-start guard aborting) -- never after a real attempt (success or genuine failure) was
    already recorded."""
    try:
        _record_path(app_key, report_id, root=root).unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- 仕様2/4: 待機中の表示

def waiting_root() -> Path:
    return _root() / "waiting"


def _waiting_path(app_key: str, report_id: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else waiting_root()
    return base / _hash(app_key) / f"{_hash(report_id)}.json"


def mark_waiting(app_key: str, report_id: str, *, root: Path | None = None) -> None:
    """Display-only (RESULT_WAITING, 仕様2/C6): a report currently held back by a busy target
    repository or a last-moment guard abort -- unlike AutoStartRecord, this mark never gates
    already_started, so the report is still picked up again next cycle. Best-effort: a write
    failure must never affect the outcome already computed."""
    try:
        _write_json_atomic(_waiting_path(app_key, report_id, root=root), {"waiting": True})
    except OSError:
        pass


def clear_waiting(app_key: str, report_id: str, *, root: Path | None = None) -> None:
    try:
        _waiting_path(app_key, report_id, root=root).unlink()
    except OSError:
        pass


def is_waiting(app_key: str, report_id: str, *, root: Path | None = None) -> bool:
    return _read_json(_waiting_path(app_key, report_id, root=root)) is not None


def load_waiting_marks(identities: Iterable[tuple[str, str]], *,
                        root: Path | None = None) -> dict[tuple[str, str], bool]:
    """Mirrors load_auto_start_records -- for the inbox list's own「待機中」display only."""
    out: dict[tuple[str, str], bool] = {}
    for app_key, report_id in identities:
        if is_waiting(app_key, report_id, root=root):
            out[(app_key, report_id)] = True
    return out


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


def _display_safe(value: str) -> str:
    return inbox.sanitize_path_for_display(value)


def write_run_log_entry(*, app_key: str, report_id: str, outcome: str, run_id: str = "",
                         log_dir: Path | None = None) -> None:
    """仕様5: one record per automatic-start attempt -- fixed words and numbers only (date/time,
    app name, report identifier's hash, the fixed outcome word, and DCC's own run identifier).
    Never the report body, the AI's own output, a path, or exception text. Best-effort: a logging
    failure must never affect the outcome already computed. Kept to ~RUN_LOG_MAX_FILES recent
    entries, the same convention as reports_auto.write_run_log_entry."""
    try:
        directory = log_dir if log_dir is not None else run_log_root()
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        lines = [
            f"日時: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"アプリ: {_display_safe(app_key)}",
            f"報告の識別子: {_hash(report_id)}",
            f"結果: {outcome}",
            f"Runの識別子: {_display_safe(run_id) if run_id else '(なし)'}",
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


# --------------------------------------------------------------------------- 仕様3: Task本文

def _build_task_text(report: "inbox.Report", repo_name: str) -> str:
    """docs/orchestrator_input_contract.md R1-R4, fixed template only (DCC Task 18仕様3): a
    "対象リポジトリ:" line within the first 10 lines (R1), the "受入条件" heading word used only
    here (R2) with "- " bullets right after it (R3), then a "## " section break (R4). The spec
    file this run also carries (create_spec_file) is what actually fixes the criteria
    (taskspec.parse_spec_text numbers them C1, C2, ... regardless of this text) -- this body is
    for the Main/Reviewer AI to read, never for a human to approve first. repo_name always comes
    from resolve_repo_dir's own resolved directory name (DCC's registry), never from report
    content; report.kind_label is one of reports_inbox.KIND_LABELS' two fixed strings."""
    lines = [
        cas.build_task_title(report), "",
        f"対象リポジトリ: {repo_name}", "",
        "## 受入条件",
    ]
    lines += [f"- {criterion}" for criterion in FIXED_CRITERIA]
    lines += ["", "## 範囲外", f"- {_SCOPE_NOTE}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- default collaborators

def _default_resolve_repo_dir(app_key: str) -> Path | None:
    from tools.ai_orchestrator.orchestrator import resolve_repo_dir_for_app

    return resolve_repo_dir_for_app(app_key)


def _default_active_runs(repo: str) -> list:
    from tools.ai_orchestrator import runstate

    return runstate.active_runs(repo=repo)


def _default_create_and_start(report, criteria_lines, *, main_agent, review_agent, resolve_repo_dir,
                               task_text_fn, start_run=None):
    return cas.create_and_start(
        report, criteria_lines, main_agent=main_agent, review_agent=review_agent,
        resolve_repo_dir=resolve_repo_dir, task_text_fn=task_text_fn, start_run=start_run)


def _default_run_stage(run_id: str) -> str | None:
    from tools.ai_orchestrator import runstate

    record = runstate.read_record(runstate.runs_root() / run_id)
    return record.get("stage") if record else None


def _default_load_decision(app_key: str, report_id: str):
    return inbox.load_decision(app_key, report_id)


# --------------------------------------------------------------------------- 仕様2/4: 実行本体

@dataclass(frozen=True)
class AutoStartRunOutcome:
    status: str  # STATUS_* above
    message: str = ""
    record: AutoStartRecord | None = None


def _eligible_report(global_config: "auto.AutoModeConfig", start_config: AutoStartConfig, reports: list, *,
                      records_dir: Path | None, auto_results_root: Path | None,
                      load_decision_fn: Callable[[str, str], object]) -> "inbox.Report | None":
    for report in reports:
        if not app_start_allowed(global_config, start_config, report.app_key):
            continue
        triage_record = auto.load_auto_result(report.app_key, report.report_id, root=auto_results_root)
        if triage_record is None or triage_record.outcome != auto.OUTCOME_PROCEED:
            continue
        if already_started(report.app_key, report.report_id, root=records_dir):
            continue
        try:
            decided = load_decision_fn(report.app_key, report.report_id) is not None
        except Exception:  # noqa: BLE001 - a broken decision lookup must not block eligibility forever
            decided = False
        if decided:
            continue
        return report
    return None


def _current_global_config(config: "auto.AutoModeConfig", path: Path | None) -> "auto.AutoModeConfig":
    if path is None:
        return config
    return auto.load_auto_mode_config(path)


def _current_start_config(config: AutoStartConfig, path: Path | None) -> AutoStartConfig:
    if path is None:
        return config
    return load_auto_start_config(path)


def refresh_pending_results(reports: list, *, records_dir: Path | None = None,
                             run_lookup_fn: Callable[[str], str | None] | None = None) -> None:
    """仕様4: for every report currently visible in the inbox, resolve any PENDING AutoStartRecord
    whose run has since reached a terminal stage (completed/needs_human/failed/stopped) into the
    fixed RESULT_* word the inbox list shows -- never the run's own final message. A run that is
    still active, or whose stage cannot be determined, is left PENDING for a later cycle."""
    run_lookup_fn = run_lookup_fn or _default_run_stage
    for report in reports:
        record = load_auto_start_record(report.app_key, report.report_id, root=records_dir)
        if record is None or record.result != RESULT_PENDING or not record.run_id:
            continue
        try:
            stage = run_lookup_fn(record.run_id)
        except Exception:  # noqa: BLE001 - an unreadable run must not crash the refresh cycle
            stage = None
        result = _RESULT_FOR_STAGE.get(stage or "")
        if result is None:
            continue
        updated = AutoStartRecord(record.app_key, record.report_id, record.started_at, record.run_id, result)
        _save_record(updated, root=records_dir)


def run_auto_start_once(
    *,
    global_config: "auto.AutoModeConfig | None" = None,
    global_config_path: Path | None = None,
    start_config: AutoStartConfig | None = None,
    start_config_path: Path | None = None,
    today: str | None = None,
    reports_config_fn: Callable[[], "inbox.ReportsConfig"] | None = None,
    scan_fn: Callable[[list], list] | None = None,
    auto_results_root: Path | None = None,
    resolve_repo_dir: Callable[[str], Path | None] | None = None,
    active_runs_fn: Callable[[str], list] | None = None,
    create_and_start_fn: Callable[..., object] | None = None,
    start_run_fn: Callable[..., Path] | None = None,
    run_lookup_fn: Callable[[str], str | None] | None = None,
    load_decision_fn: Callable[[str, str], object] | None = None,
    main_agent: str = "claude",
    review_agent: str = "codex",
    daily_count_path: Path | None = None,
    records_dir: Path | None = None,
    waiting_dir: Path | None = None,
    log_dir: Path | None = None,
    stop_event: threading.Event | None = None,
) -> AutoStartRunOutcome:
    """Run at most one automatic start (C1-C6). Never starts the Orchestrator for a report whose
    Task 17 triage is not exactly OUTCOME_PROCEED, whose app is not both globally and individually
    permitted, that was already attempted before, or whose target repository already has an
    active run (that report is simply left for the next cycle -- STATUS_WAITING, shown in the
    inbox as RESULT_WAITING via mark_waiting -- see reports_inbox_view.py). The global switch,
    this module's own per-app permission, and the daily limit are all re-read (via
    `_current_*_config`/`daily_limit_reached`) twice more after the top-of-cycle check: once right
    after the eligible report is chosen (mirroring reports_auto.run_auto_triage_once's own
    Reviewer-fixed re-check), and again inside a guard this function wires into
    create_and_start_fn's own `start_run` parameter -- called immediately before the real
    Orchestrator start (which the guard only then delegates to via `start_run_fn`, defaulting to
    reports_create_and_start._default_start_run, the same entry point a human's own 開始 button
    uses), i.e. *after* whatever time create_and_start_fn's own spec-file creation and parsing
    takes (C5). A reservation record is written *before* create_and_start_fn is ever
    called (so a crash mid-start can never lead to a duplicate start, C3/C4); it is only deleted
    again if the guard aborts or create_and_start_fn itself hits a genuine Orchestrator race
    (REASON_ALREADY_RUNNING either way) -- never after a real success or a real failure, and the
    daily count is only consumed once one of those two real outcomes is known (never for a race or
    a guard abort, so contention never silently eats the day's quota)."""
    global_config = global_config if global_config is not None else auto.load_auto_mode_config(global_config_path)
    start_config = start_config if start_config is not None else load_auto_start_config(start_config_path)
    today = today if today is not None else auto.today_str()

    reports_config_fn = reports_config_fn or inbox.load_reports_config
    scan_fn = scan_fn or inbox.scan_all
    resolve_repo_dir = resolve_repo_dir or _default_resolve_repo_dir
    active_runs_fn = active_runs_fn or _default_active_runs
    create_and_start_fn = create_and_start_fn or _default_create_and_start
    start_run_fn = start_run_fn or cas._default_start_run
    run_lookup_fn = run_lookup_fn or _default_run_stage
    load_decision_fn = load_decision_fn or _default_load_decision

    reports_cfg = reports_config_fn()
    apps = [(a.app_key, a.display_name, a.shared_root) for a in reports_cfg.apps]
    inboxes = scan_fn(apps)
    reports = inbox.all_reports(inboxes)

    # 仕様4: independent of whether anything is started below -- resolving an already-started
    # run's result is never gated by the switch, the permission, or the daily limit.
    refresh_pending_results(reports, records_dir=records_dir, run_lookup_fn=run_lookup_fn)

    if not global_config.enabled:
        return AutoStartRunOutcome(STATUS_DISABLED)
    if daily_limit_reached(start_config, today, path=daily_count_path):
        return AutoStartRunOutcome(STATUS_LIMIT_REACHED, LIMIT_REACHED_TEXT)

    report = _eligible_report(global_config, start_config, reports, records_dir=records_dir,
                               auto_results_root=auto_results_root, load_decision_fn=load_decision_fn)
    if report is None:
        return AutoStartRunOutcome(STATUS_NOTHING_TO_DO)

    if stop_event is not None and stop_event.is_set():
        return AutoStartRunOutcome(STATUS_STOPPED)
    current_global = _current_global_config(global_config, global_config_path)
    current_start = _current_start_config(start_config, start_config_path)
    if not app_start_allowed(current_global, current_start, report.app_key):
        return AutoStartRunOutcome(STATUS_DISABLED)
    if daily_limit_reached(current_start, today, path=daily_count_path):
        return AutoStartRunOutcome(STATUS_LIMIT_REACHED, LIMIT_REACHED_TEXT)

    try:
        repo_dir = resolve_repo_dir(report.app_key)
    except Exception:  # noqa: BLE001 - registry trouble must degrade, not crash the cycle
        repo_dir = None
    if repo_dir is not None:
        try:
            busy = bool(active_runs_fn(str(repo_dir)))
        except Exception:  # noqa: BLE001 - an unreadable lock must not block forever either way
            busy = False
        if busy:
            mark_waiting(report.app_key, report.report_id, root=waiting_dir)
            return AutoStartRunOutcome(STATUS_WAITING)

    # Past this point a real attempt is about to be made: reserve it *before* create_and_start_fn
    # runs (C3/C4) and clear any stale「待機中」mark left from an earlier cycle.
    clear_waiting(report.app_key, report.report_id, root=waiting_dir)
    reserved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save_record(AutoStartRecord(report.app_key, report.report_id, reserved_at), root=records_dir)

    def _guarded_start_run(**start_run_kwargs):
        """C5: the actual last check before the Orchestrator starts -- re-reads the stop event,
        both permissions, and the daily limit one more time, since create_and_start_fn's own spec
        creation/parsing (called just before this) can take an unpredictable amount of time. An
        abort here raises the same ActiveRunExists the real Orchestrator itself would raise on a
        genuine 1-repo-1-run race, so create_and_start_fn's existing REASON_ALREADY_RUNNING branch
        handles both cases identically -- no new path, no new exception type."""
        from tools.ai_orchestrator.runstate import ActiveRunExists

        # ActiveRunExists's own two fields (run_id/liveness) only ever feed its human-facing
        # message text, never read back by create_and_start's except-clause (it matches on
        # exception type only) -- "" / "guard" are fixed literals, not report- or AI-derived.
        if stop_event is not None and stop_event.is_set():
            raise ActiveRunExists("", "guard")
        latest_global = _current_global_config(current_global, global_config_path)
        latest_start = _current_start_config(current_start, start_config_path)
        if not app_start_allowed(latest_global, latest_start, report.app_key):
            raise ActiveRunExists("", "guard")
        if daily_limit_reached(latest_start, today, path=daily_count_path):
            raise ActiveRunExists("", "guard")
        return start_run_fn(**start_run_kwargs)

    repo_name = repo_dir.name if repo_dir is not None else report.app_key
    task_text_fn = lambda rep, _name=repo_name: _build_task_text(rep, _name)  # noqa: E731

    result = create_and_start_fn(
        report, list(FIXED_CRITERIA), main_agent=main_agent, review_agent=review_agent,
        resolve_repo_dir=resolve_repo_dir, task_text_fn=task_text_fn, start_run=_guarded_start_run,
    )

    if not result.ok and result.reason == cas.REASON_ALREADY_RUNNING:
        # Either a genuine race against our own pre-check above, or this cycle's own guard
        # aborting: nothing was actually started, so the reservation is undone -- the report is
        # picked up again next cycle (same STATUS_WAITING contract), and the daily count is never
        # consumed for an attempt that never happened.
        _delete_record(report.app_key, report.report_id, root=records_dir)
        mark_waiting(report.app_key, report.report_id, root=waiting_dir)
        return AutoStartRunOutcome(STATUS_WAITING)

    # A real outcome (success or genuine failure) is now known: this is the one daily-limit slot
    # this cycle is allowed to consume.
    _increment_daily_count(today, daily_count_path)

    if result.ok:
        run_id = result.run_dir.name if result.run_dir is not None else ""
        record = AutoStartRecord(report.app_key, report.report_id, reserved_at, run_id, RESULT_PENDING)
        _save_record(record, root=records_dir)
        write_run_log_entry(app_key=report.app_key, report_id=report.report_id, outcome=LOG_RESULT_STARTED,
                             run_id=run_id, log_dir=log_dir)
        clear_waiting(report.app_key, report.report_id, root=waiting_dir)
        return AutoStartRunOutcome(STATUS_STARTED, "", record)

    record = AutoStartRecord(report.app_key, report.report_id, reserved_at, "", RESULT_NEEDS_HUMAN)
    _save_record(record, root=records_dir)
    write_run_log_entry(app_key=report.app_key, report_id=report.report_id, outcome=LOG_RESULT_START_FAILED,
                         log_dir=log_dir)
    clear_waiting(report.app_key, report.report_id, root=waiting_dir)
    return AutoStartRunOutcome(STATUS_START_FAILED, "", record)
