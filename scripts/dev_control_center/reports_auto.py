"""DCC Task 17: automatic first-stage triage -- "自動調査と振り分け" only (no automatic start).

When the global switch and an app's own permission are both ON, a periodic caller (app.py) may
run this module's run_auto_triage_once() at most once per interval. It looks at the reports
inbox (reports_inbox.py, read-only) for an app whose permission is ON and that has not yet been
auto-investigated, runs exactly one existing, read-only Task 14 investigation
(reports_triage.investigate -- unchanged, no new capability), and buckets the fixed-field result
into one of four fixed Japanese labels (OUTCOME_*). It never starts the Orchestrator, never
creates a spec file, and never writes to the shared report folder -- only to this module's own
local records under %LOCALAPPDATA%\\ShizenDev\\DCC\\auto_triage\\.

Security posture (same as reports_triage.py / reports_inbox.py):
 - The report body and the AI's own free-text fields (evidence, reply_draft, criteria_draft) are
   untrusted; classify_outcome reads only the fixed fields (classification, confidence,
   suspected_locations) and never pattern-matches their content.
 - Every local record (AutoTriageRecord, the run log) holds only fixed words and numbers --
   app_key/report_id are carried as DCC already carries them elsewhere (reports_inbox.Decision
   stores the same two fields unsanitized), but the run log's free-text *line* embedding sanitizes
   them first (see _display_safe) so a newline-laced report_id cannot forge extra log lines.
 - Which report gets investigated and which repo it may read code from are still decided only by
   reports_inbox's own config/scan and reports_triage/orchestrator's own registry lookup -- this
   module adds no new repo-resolution or command-execution path.
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
import time
from typing import Callable, Iterable

from . import reports_inbox as inbox
from . import reports_triage as triage

DEFAULT_DAILY_LIMIT = 10
AUTO_TRIAGE_INTERVAL_SECONDS = 10 * 60

# 仕様3: the four fixed outcome labels -- never built from AI free text.
OUTCOME_PROCEED = "自動で進めてよい"
OUTCOME_NEEDS_HUMAN = "人の確認が必要"
OUTCOME_NOT_APPLICABLE = "対象外"
OUTCOME_FAILED = "調査失敗"

# 仕様2: the fixed sentence shown once the day's investigation count hits the limit.
LIMIT_REACHED_TEXT = "本日の上限に達しました"

# The literal fallback text build_triage_prompt's own _INVESTIGATION_BUDGET_NOTE tells the AI to
# write for a location it could not confirm (see reports_triage.py) -- compared by equality only.
_UNCONFIRMED_LOCATION = "未確認"

STATUS_DISABLED = "disabled"
STATUS_LIMIT_REACHED = "limit_reached"
STATUS_NOTHING_TO_DO = "nothing_to_do"
STATUS_RAN = "ran"
STATUS_STOPPED = "stopped"

RUN_LOG_MAX_FILES = 50


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "auto_triage"


def auto_mode_config_path() -> Path:
    return _root() / "config.json"


def _daily_count_path() -> Path:
    return _root() / "daily_count.json"


def results_root() -> Path:
    return _root() / "results"


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


# --------------------------------------------------------------------------- 仕様1: 設定（自動モード）

@dataclass(frozen=True)
class AutoModeConfig:
    """enabled: 全体の停止スイッチ（初期値OFF）。apps: app_key -> 許可（初期値、未記載はOFF）。
    daily_limit: 1日あたりの自動調査の回数（初期値10）。"""

    enabled: bool = False
    apps: dict = field(default_factory=dict)
    daily_limit: int = DEFAULT_DAILY_LIMIT


def app_allowed(config: AutoModeConfig, app_key: str) -> bool:
    """C1: both the global switch and this app's own permission must be ON."""
    return bool(config.enabled) and bool(config.apps.get(app_key, False))


def load_auto_mode_config(path: Path | None = None) -> AutoModeConfig:
    """Never raises: a missing or unreadable/corrupt file degrades to the all-OFF defaults."""
    data = _read_json(path if path is not None else auto_mode_config_path())
    if data is None:
        return AutoModeConfig()
    apps_raw = data.get("apps")
    apps = {str(k): bool(v) for k, v in apps_raw.items()} if isinstance(apps_raw, dict) else {}
    try:
        daily_limit = int(data.get("daily_limit", DEFAULT_DAILY_LIMIT))
    except (TypeError, ValueError):
        daily_limit = DEFAULT_DAILY_LIMIT
    return AutoModeConfig(enabled=bool(data.get("enabled", False)), apps=apps, daily_limit=daily_limit)


def save_auto_mode_config(config: AutoModeConfig, path: Path | None = None) -> None:
    target = path if path is not None else auto_mode_config_path()
    _write_json_atomic(target, {
        "enabled": config.enabled, "apps": dict(config.apps), "daily_limit": config.daily_limit,
    })


def set_enabled(enabled: bool, *, path: Path | None = None) -> AutoModeConfig:
    """Read-modify-write the global switch (DCC画面のチェックボックス用)."""
    config = load_auto_mode_config(path)
    updated = AutoModeConfig(enabled=bool(enabled), apps=dict(config.apps), daily_limit=config.daily_limit)
    save_auto_mode_config(updated, path)
    return updated


def set_app_allowed(app_key: str, allowed: bool, *, path: Path | None = None) -> AutoModeConfig:
    """Read-modify-write one app's permission (DCC画面のチェックボックス用)."""
    config = load_auto_mode_config(path)
    apps = dict(config.apps)
    apps[app_key] = bool(allowed)
    updated = AutoModeConfig(enabled=config.enabled, apps=apps, daily_limit=config.daily_limit)
    save_auto_mode_config(updated, path)
    return updated


# --------------------------------------------------------------------------- 仕様1: 1日の上限

def today_str(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


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


def daily_limit_reached(config: AutoModeConfig, today: str, *, path: Path | None = None) -> bool:
    return _read_daily_count(today, path) >= config.daily_limit


# --------------------------------------------------------------------------- 仕様2: 調査済みの印・結果

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _result_path(app_key: str, report_id: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else results_root()
    return base / _hash(app_key) / f"{_hash(report_id)}.json"


@dataclass(frozen=True)
class AutoTriageRecord:
    """app_key/report_id here are the caller's own already-known identity (never read back from
    the stored file -- see _save_result/load_auto_result): report_id in particular is report-
    derived, untrusted free-form text (same posture as reports_inbox.decision_path), so the file
    on disk never holds it in the clear, only its sha256 digest (report_id_hash). failure_reason
    is "" on success, else one of reports_triage's own fixed FAILURE_KIND_* codes (never the raw
    exception text -- see run_auto_triage_once)."""

    app_key: str
    report_id: str
    outcome: str
    investigated_at: str
    elapsed_seconds: float
    failure_reason: str = ""


def _save_result(record: AutoTriageRecord, *, root: Path | None = None) -> None:
    _write_json_atomic(_result_path(record.app_key, record.report_id, root=root), {
        "report_id_hash": _hash(record.report_id), "outcome": record.outcome,
        "investigated_at": record.investigated_at, "elapsed_seconds": record.elapsed_seconds,
        "failure_reason": record.failure_reason,
    })


def load_auto_result(app_key: str, report_id: str, *, root: Path | None = None) -> AutoTriageRecord | None:
    """app_key/report_id are the caller's own identity (the arguments), not read from the file --
    the file never stores them in the clear (see AutoTriageRecord's own docstring)."""
    data = _read_json(_result_path(app_key, report_id, root=root))
    if data is None:
        return None
    try:
        return AutoTriageRecord(
            app_key=app_key, report_id=report_id, outcome=str(data["outcome"]),
            investigated_at=str(data["investigated_at"]), elapsed_seconds=float(data["elapsed_seconds"]),
            failure_reason=str(data.get("failure_reason", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_auto_results(identities: Iterable[tuple[str, str]], *,
                       root: Path | None = None) -> dict[tuple[str, str], AutoTriageRecord]:
    """Mirrors reports_inbox.load_decisions: {identity: record} for every report that already has
    one (used both to skip already-investigated reports and for the inbox list's own column)."""
    out: dict[tuple[str, str], AutoTriageRecord] = {}
    for app_key, report_id in identities:
        record = load_auto_result(app_key, report_id, root=root)
        if record is not None:
            out[(app_key, report_id)] = record
    return out


def already_investigated(app_key: str, report_id: str, *, root: Path | None = None) -> bool:
    """C2/C5: a record exists (success, 対象外, or 調査失敗 alike) -- the report is never picked
    again, which is also how a failed investigation is never retried (仕様2)."""
    return load_auto_result(app_key, report_id, root=root) is not None


# --------------------------------------------------------------------------- 仕様3: 振り分け

def classify_outcome(outcome: "triage.TriageOutcome") -> str:
    """C3: decides using only outcome.result's fixed fields (classification, confidence,
    suspected_locations) -- never evidence/criteria_draft/reply_draft, and never any substring or
    pattern match against them. A failed investigation (outcome.result is None) is always
    調査失敗, regardless of outcome.reason's wording."""
    result = outcome.result
    if result is None:
        return OUTCOME_FAILED
    if result.classification == "bug":
        has_real_candidate = any(loc != _UNCONFIRMED_LOCATION for loc in result.suspected_locations)
        if result.confidence == "high" and result.suspected_locations and has_real_candidate:
            return OUTCOME_PROCEED
        return OUTCOME_NEEDS_HUMAN
    if result.classification == "feature_request":
        return OUTCOME_NEEDS_HUMAN
    return OUTCOME_NOT_APPLICABLE  # spec_misunderstanding (質問) / insufficient_info (その他)


# --------------------------------------------------------------------------- 仕様5: 実行ごとの記録

_LOG_SEQUENCE_LOCK = threading.Lock()
_LOG_SEQUENCE_COUNTER = 0


def _next_log_sequence() -> int:
    """Same reasoning as reports_triage._next_log_sequence: keeps file name order equal to
    creation order even for several entries written within the same wall-clock second."""
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
    """C3: app_key is a trusted, DCC-registered identifier (one of reports_cfg.apps' own
    app_key values -- never report content), but is still run through the same control-
    character/newline/tab neutralization as every other value embedded in the run log's
    fixed-field text lines, as defense in depth."""
    return inbox.sanitize_path_for_display(value)


def write_run_log_entry(*, app_key: str, report_id: str, outcome: str, elapsed_seconds: float,
                         failure_reason: str = "", log_dir: Path | None = None) -> None:
    """仕様5: one record per automatic investigation attempt -- fixed words and numbers only
    (date/time, app name, report identifier, outcome bucket, elapsed seconds, and -- only on
    失敗 -- one of reports_triage's own fixed FAILURE_KIND_* codes). Never the report body, the
    AI's own output, a path, or exception text. report_id is report-derived, untrusted free-form
    text (same posture as reports_inbox.decision_path), so only its sha256 digest is ever written
    here, never the raw value -- a path-like, command-like, or newline-laced report_id therefore
    can never reach this file at all, let alone forge an extra line. Best-effort: a logging
    failure must never affect the outcome already computed. Kept to ~RUN_LOG_MAX_FILES recent
    entries, the same convention as reports_triage.triage_logs."""
    try:
        directory = log_dir if log_dir is not None else run_log_root()
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        lines = [
            f"日時: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"アプリ: {_display_safe(app_key)}",
            f"報告の識別子: {_hash(report_id)}",
            f"振り分け: {outcome}",
            f"所要秒数: {elapsed_seconds:.1f}",
        ]
        if failure_reason:
            lines.append(f"失敗理由: {failure_reason}")
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


# --------------------------------------------------------------------------- 仕様2/4: 実行本体

@dataclass(frozen=True)
class AutoTriageRunOutcome:
    status: str  # STATUS_* above
    message: str = ""
    record: AutoTriageRecord | None = None


def _eligible_report(config: AutoModeConfig, reports: list, *, results_dir: Path | None) -> "inbox.Report | None":
    for report in reports:
        if not app_allowed(config, report.app_key):
            continue
        if already_investigated(report.app_key, report.report_id, root=results_dir):
            continue
        return report
    return None


def _current_config(config: AutoModeConfig, config_path: Path | None) -> AutoModeConfig:
    """Re-reads the on-disk settings right before the one AI call this cycle may make (Reviewer
    finding: a human toggling the master switch or an app's permission off while the inbox scan
    above was running must still be honored). When no config_path was given there is no on-disk
    source to refresh from -- the config already read for this cycle is used unchanged, which is
    also what keeps every caller that only ever hands in an in-memory `config=` (no file at all)
    working exactly as before."""
    if config_path is None:
        return config
    return load_auto_mode_config(config_path)


def run_auto_triage_once(
    *,
    config: AutoModeConfig | None = None,
    config_path: Path | None = None,
    today: str | None = None,
    reports_config_fn: Callable[[], "inbox.ReportsConfig"] | None = None,
    scan_fn: Callable[[list], list] | None = None,
    investigate_fn: Callable[["inbox.Report"], "triage.TriageOutcome"] | None = None,
    daily_count_path: Path | None = None,
    results_dir: Path | None = None,
    log_dir: Path | None = None,
    stop_event: threading.Event | None = None,
) -> AutoTriageRunOutcome:
    """Run at most one automatic investigation (C1/C2/C4). Never raises for an ordinary failure
    of the investigation itself (reports_triage.investigate already degrades that to
    outcome.result is None); an unexpected exception from investigate_fn itself (e.g. its own
    setup code failing before any TriageOutcome exists) is caught here too and recorded the same
    way, as reports_triage.FAILURE_KIND_OTHER -- never left unrecorded, which is what would let
    the same report be retried next cycle. Never starts the Orchestrator, never writes a spec
    file, never touches the shared report folder (C6) -- it only calls reports_inbox's own
    read-only config/scan and reports_triage.investigate, then writes to this module's own local
    records.

    `stop_event` (set by app.py when DCC is closing) and the settings themselves are both
    re-checked (via `_current_config`) immediately before investigate_fn is actually called --
    not just once at the top -- so a human switching automatic mode off (or DCC shutting down)
    while the inbox scan above was in flight still stops the one AI call this cycle would
    otherwise have made."""
    config = config if config is not None else load_auto_mode_config(config_path)
    today = today if today is not None else today_str()

    if not config.enabled:
        return AutoTriageRunOutcome(STATUS_DISABLED, "自動モードはOFFです。")
    if daily_limit_reached(config, today, path=daily_count_path):
        return AutoTriageRunOutcome(STATUS_LIMIT_REACHED, LIMIT_REACHED_TEXT)

    reports_config_fn = reports_config_fn or inbox.load_reports_config
    scan_fn = scan_fn or inbox.scan_all
    investigate_fn = investigate_fn or triage.investigate

    reports_cfg = reports_config_fn()
    apps = [(a.app_key, a.display_name, a.shared_root) for a in reports_cfg.apps]
    inboxes = scan_fn(apps)
    reports = inbox.all_reports(inboxes)

    report = _eligible_report(config, reports, results_dir=results_dir)
    if report is None:
        return AutoTriageRunOutcome(STATUS_NOTHING_TO_DO, "対象の報告がありません。")

    if stop_event is not None and stop_event.is_set():
        return AutoTriageRunOutcome(STATUS_STOPPED, "DCCが終了します。")
    current_config = _current_config(config, config_path)
    if not app_allowed(current_config, report.app_key):
        return AutoTriageRunOutcome(STATUS_DISABLED, "自動モードはOFFです。")

    _increment_daily_count(today, daily_count_path)
    started = time.monotonic()
    try:
        triage_outcome = investigate_fn(report)
    except Exception:  # noqa: BLE001 - investigate_fn's own contract is "never raises for an
        # ordinary failure", so reaching here is already unexpected; it must still end in a
        # fixed, recorded failure (never the exception text) so the report is never retried.
        triage_outcome = None
        failure_reason = triage.FAILURE_KIND_OTHER
    else:
        failure_reason = ""
    elapsed = time.monotonic() - started

    if triage_outcome is None:
        outcome_label = OUTCOME_FAILED
    else:
        outcome_label = classify_outcome(triage_outcome)
        if outcome_label == OUTCOME_FAILED:
            failure_reason = triage.failure_kind_for_reason(triage_outcome.reason)

    investigated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = AutoTriageRecord(report.app_key, report.report_id, outcome_label, investigated_at, elapsed,
                               failure_reason)
    _save_result(record, root=results_dir)
    write_run_log_entry(app_key=report.app_key, report_id=report.report_id, outcome=outcome_label,
                         elapsed_seconds=elapsed, failure_reason=failure_reason, log_dir=log_dir)
    return AutoTriageRunOutcome(STATUS_RAN, "", record)
