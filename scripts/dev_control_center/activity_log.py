"""DCC Task WF-6a: a single, shared activity record for every automatic process (自動調査,
自動開始, and -- added later, by Task WF-6b -- 自動承認/自動再実行/計画の自動実行), so what just
happened and why something stopped can be read from one place instead of several separate,
differently-shaped records.

Security posture:
 - Every field accepted by append() other than target_id and the timestamp must be one of this
   module's own fixed-word tuples (ROLES / ACTIONS / TARGET_TYPES / RESULTS / REASONS) --
   anything else raises ActivityLogError. The report body, a Task/plan body, any AI free-text
   output, a filesystem path, or an exception's own message is therefore never representable in
   an entry at all; only fixed words, an identifier, and numbers/timestamps ever reach disk.
 - A read of a missing file returns an empty list (nothing has ever been logged yet), but a file
   that exists and cannot be read, or whose content is not valid JSON Lines in this module's own
   shape, raises ActivityLogError rather than degrading to an empty list -- a caller must not
   mistake "the record is broken" for "there is nothing to show" (see read_recent). append() has
   the same contract on the existing file it rewrites: a corrupt existing file fails loudly too,
   rather than being silently replaced with just the one new entry.
 - append() never raises for the *caller's own decision*: every DCC automatic-process module that
   calls it wraps the call so a logging failure (disk full, a corrupt file, anything else) can
   never change the outcome the caller already computed -- see each module's own `_log_activity`
   helper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading

MAX_ENTRIES = 500

# 役割 (role): the fixed actors this record distinguishes. Only the first two are wired by this
# Task (自動調査 / 自動開始); the rest are reserved for Task WF-6b (範囲外 for this Task).
ROLE_AUTO_TRIAGE = "自動調査"
ROLE_AUTO_START = "自動開始"
ROLE_AUTO_APPROVE = "自動承認"
ROLE_AUTO_RETRY = "自動再実行"
ROLE_AUTO_PLAN = "計画の自動実行"
ROLE_HUMAN = "人"
ROLES = (ROLE_AUTO_TRIAGE, ROLE_AUTO_START, ROLE_AUTO_APPROVE, ROLE_AUTO_RETRY, ROLE_AUTO_PLAN, ROLE_HUMAN)

# 動作 (action): what happened to the target, independent of which role it was.
ACTION_START = "開始"
ACTION_COMPLETE = "完了"
ACTION_FAIL = "失敗"
ACTION_EXCLUDED = "対象外"
ACTION_WAITING = "待機"
ACTION_LIMIT = "上限"
ACTIONS = (ACTION_START, ACTION_COMPLETE, ACTION_FAIL, ACTION_EXCLUDED, ACTION_WAITING, ACTION_LIMIT)

# 対象の種類 (target kind). TARGET_NONE is for an entry about a whole cycle (e.g. "automatic mode
# is OFF"), not any one report/run/task.
TARGET_REPORT = "報告"
TARGET_RUN = "Run"
TARGET_PLAN_TASK = "計画タスク"
TARGET_NONE = "(なし)"
TARGET_TYPES = (TARGET_REPORT, TARGET_RUN, TARGET_PLAN_TASK, TARGET_NONE)

# 結果の固定語 (result): the role-specific outcome word, shared across roles where the words
# happen to coincide (reports_auto.OUTCOME_* / reports_auto_start.RESULT_* use this same text).
RESULT_PROCEED = "自動で進めてよい"
RESULT_NEEDS_HUMAN = "人の確認が必要"
RESULT_NOT_APPLICABLE = "対象外"
RESULT_FAILED = "調査失敗"
RESULT_CANDIDATE = "候補あり"
RESULT_NONE = ""
RESULTS = (RESULT_PROCEED, RESULT_NEEDS_HUMAN, RESULT_NOT_APPLICABLE, RESULT_FAILED, RESULT_CANDIDATE, RESULT_NONE)

# 理由の固定語 (reason, optional): DCC Task WF-6a 仕様3 -- five AI-failure kinds, classified only
# from the provider's own already-classified error_kind (tools.ai_orchestrator.providers.ERR_* --
# itself the result of known-phrase matching against the AI's output; see classify_ai_failure),
# plus the four fixed「人の確認が必要」reasons, plus "" (no reason recorded).
REASON_LOGIN_EXPIRED = "ログインの期限切れ"
REASON_QUOTA_LIMIT = "使用枠の上限"
REASON_CANNOT_LAUNCH = "起動できない"
REASON_CRASHED = "異常終了"
REASON_TIMEOUT = "時間切れ"
REASON_SPEC_CHANGE_REQUEST = "仕様変更の希望"
REASON_AUTO_CONDITION_NOT_MET = "自動進行の条件を満たさない"
REASON_PROTECTED_TARGET = "保護された対象"
REASON_CANNOT_DECIDE = "判断できない"
REASON_NONE = ""
REASONS = (
    REASON_LOGIN_EXPIRED, REASON_QUOTA_LIMIT, REASON_CANNOT_LAUNCH, REASON_CRASHED, REASON_TIMEOUT,
    REASON_SPEC_CHANGE_REQUEST, REASON_AUTO_CONDITION_NOT_MET, REASON_PROTECTED_TARGET, REASON_CANNOT_DECIDE,
    REASON_NONE,
)

# 対象 ID の形式 (target_id format), one fixed pattern per TARGET_TYPES member -- never a bare
# length cap. Every current caller hands in exactly one of these shapes already (see each
# module's own _hash()/now_id()-based identifiers), so a path, the report body, or any other
# free text can never pass validation even if a caller tried to hand one in.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REPORT_ID_RE = re.compile(r"^[0-9a-f]{64}$")  # sha256 hex digest (reports_auto._hash et al.)
_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-\d{6}$")  # tools.ai_orchestrator.common.now_id()
_PLAN_TASK_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,32}:[A-Za-z0-9-]{1,16}$")  # plan_id ':' task_id
_TARGET_ID_PATTERNS = {
    TARGET_REPORT: _REPORT_ID_RE,
    TARGET_RUN: _RUN_ID_RE,
    TARGET_PLAN_TASK: _PLAN_TASK_ID_RE,
    TARGET_NONE: None,  # TARGET_NONE: target_id must be exactly ""
}

_FIELDS = frozenset({"timestamp", "role", "action", "target_type", "target_id", "result", "reason"})


class ActivityLogError(Exception):
    """Raised by append()/read_recent() for any failure to write, read, or parse the activity
    log, and for any field value outside this module's own fixed vocabulary. Never carries a
    path or the underlying OS/JSON exception's own text -- callers only need to know that the
    record could not be written or read, never why in free text (that stays in-process and is
    never persisted or displayed)."""


@dataclass(frozen=True)
class ActivityEntry:
    timestamp: str
    role: str
    action: str
    target_type: str
    target_id: str
    result: str = RESULT_NONE
    reason: str = REASON_NONE


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "activity_log"


def log_path(root: Path | None = None) -> Path:
    return (root if root is not None else _root()) / "activity.jsonl"


def _validate(entry: ActivityEntry) -> None:
    if not isinstance(entry.timestamp, str) or not _TIMESTAMP_RE.fullmatch(entry.timestamp):
        raise ActivityLogError("invalid timestamp")
    if entry.role not in ROLES:
        raise ActivityLogError("invalid role")
    if entry.action not in ACTIONS:
        raise ActivityLogError("invalid action")
    if entry.target_type not in TARGET_TYPES:
        raise ActivityLogError("invalid target_type")
    if entry.result not in RESULTS:
        raise ActivityLogError("invalid result")
    if entry.reason not in REASONS:
        raise ActivityLogError("invalid reason")
    if not isinstance(entry.target_id, str):
        raise ActivityLogError("invalid target_id")
    pattern = _TARGET_ID_PATTERNS[entry.target_type]
    if pattern is None:
        if entry.target_id != "":
            raise ActivityLogError("invalid target_id")
    elif not pattern.fullmatch(entry.target_id):
        raise ActivityLogError("invalid target_id")


def _entry_to_line(entry: ActivityEntry) -> str:
    return json.dumps({
        "timestamp": entry.timestamp, "role": entry.role, "action": entry.action,
        "target_type": entry.target_type, "target_id": entry.target_id,
        "result": entry.result, "reason": entry.reason,
    }, ensure_ascii=False, sort_keys=True)


def _line_to_entry(line: str) -> ActivityEntry:
    try:
        data = json.loads(line)
    except (ValueError, RecursionError) as exc:
        # RecursionError: a deeply nested (and therefore already-corrupt, since every entry this
        # module writes is a flat object) line must fail the same fixed way as any other
        # unparsable JSON, not escape as a raw RecursionError past this module's own contract.
        raise ActivityLogError("activity log line is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ActivityLogError("activity log line is not a JSON object")
    if set(data) != _FIELDS:
        raise ActivityLogError("activity log line has an unexpected field set")
    for key in _FIELDS:
        if not isinstance(data[key], str):
            raise ActivityLogError("activity log line has a non-string field")
    entry = ActivityEntry(
        timestamp=data["timestamp"], role=data["role"], action=data["action"],
        target_type=data["target_type"], target_id=data["target_id"],
        result=data["result"], reason=data["reason"],
    )
    _validate(entry)
    return entry


def _read_lines(path: Path) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ActivityLogError("activity log could not be read") from exc
    return [line for line in raw.splitlines() if line.strip()]


_LOCK = threading.Lock()


def append(*, role: str, action: str, target_type: str, target_id: str, result: str = RESULT_NONE,
           reason: str = REASON_NONE, now: datetime | None = None, path: Path | None = None) -> None:
    """Append one activity entry, atomically, keeping only the most recent MAX_ENTRIES lines.

    Raises ActivityLogError for any field outside this module's own fixed vocabulary, or for any
    failure to read the existing file (including one that already exists but is corrupt -- it is
    never silently replaced with just the one new entry), write the temp file, or replace the
    target. Callers that must never let a logging failure change an already-computed outcome are
    expected to catch ActivityLogError themselves (see each caller's own `_log_activity` helper)."""
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = ActivityEntry(timestamp=timestamp, role=role, action=action, target_type=target_type,
                           target_id=str(target_id), result=result, reason=reason)
    _validate(entry)

    target = path if path is not None else log_path()
    with _LOCK:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            exists = target.exists()
        except OSError as exc:
            raise ActivityLogError("activity log directory could not be created") from exc
        lines = _read_lines(target) if exists else []
        for line in lines:
            _line_to_entry(line)  # an existing corrupt line must fail loudly, not be dropped silently
        lines.append(_entry_to_line(entry))
        trimmed = lines[-MAX_ENTRIES:]
        content = "\n".join(trimmed) + "\n" if trimmed else ""
        try:
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".jsonl")
        except OSError as exc:
            raise ActivityLogError("activity log temp file could not be created") from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except OSError as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise ActivityLogError("activity log could not be written") from exc


def read_recent(limit: int = MAX_ENTRIES, *, path: Path | None = None) -> list[ActivityEntry]:
    """Most-recent-first. A missing file is "nothing logged yet" (returns []); a file that exists
    but cannot be read, or whose content is not this module's own valid JSON Lines shape, raises
    ActivityLogError instead -- a broken record must never look identical to an empty one."""
    target = path if path is not None else log_path()
    try:
        missing = not target.exists()
    except OSError as exc:
        raise ActivityLogError("activity log could not be read") from exc
    if missing:
        return []
    lines = _read_lines(target)
    entries = [_line_to_entry(line) for line in lines]
    entries.reverse()
    return entries[:limit]
