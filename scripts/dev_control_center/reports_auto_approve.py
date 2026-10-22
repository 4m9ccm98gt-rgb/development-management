"""Task 19c-1: read-only eligibility, never an approval or delivery executor.

Run fields are evidence only. Repository lookup uses the local registry; all
display/log output is projected onto a closed vocabulary and validated numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import re
import subprocess

from . import activity_log
from . import reports_auto as auto
from . import reports_auto_start as start

ELIGIBLE = "自動承認の対象"
HUMAN = "人の確認が必要"
UNAVAILABLE = "値を取得できません"
REASONS = (UNAVAILABLE, "Runが完了していません", "TestsがPASSではありません",
           "ReviewerがPASSではありません", "安全チェックがPASSではありません",
           "fast-forwardできません", "変更ファイルが5件を超えています",
           "変更行数が300行を超えています", "テストの追加・変更がありません",
           "保護パスを含みます", "CIがGREENではありません")
DEFAULT_PROTECTED_PATHS = (".github/", "BUILD*.cmd", "*.spec", "requirements*.txt",
                           "pyproject.toml", "setup.py", "data/", "保存データ/",
                           "saved_data/", "app_data/", "config/", "outputs/", "print_work/",
                           "logs/", "log/", "backup/", "master_settings.json", "ui_prefs.json",
                           "closing_tasks.json", "monthly_tasks.json")


def _log_activity(*, action: str, target_type: str = activity_log.TARGET_NONE, target_id: str = "",
                   result: str = activity_log.RESULT_NONE, path: Path | None = None) -> None:
    """Best-effort (DCC Task WF-6b): a logging failure must never affect the eligibility decision
    refresh() has already computed and recorded via record_decision."""
    try:
        activity_log.append(role=activity_log.ROLE_AUTO_APPROVE, action=action, target_type=target_type,
                             target_id=target_id, result=result, path=path)
    except activity_log.ActivityLogError:
        pass


def root() -> Path:
    return start._root().parent / "auto_approve"


def config_path() -> Path:
    return root() / "config.json"


@dataclass(frozen=True)
class ApprovalConfig:
    apps: dict = field(default_factory=dict)
    daily_limit: int = 2  # persisted only; counting belongs to Task 19c-2
    protected_paths: tuple = DEFAULT_PROTECTED_PATHS


def permission_possible(app_key, start_config):
    return app_key != "development-management" and start_config.apps.get(app_key) is True


def allowed(app_key, global_config, start_config, config):
    return (global_config.enabled is True and permission_possible(app_key, start_config)
            and config.apps.get(app_key) is True)


def load_config(path=None, *, start_config=None):
    data = start._read_json(path if path is not None else config_path()) or {}
    sc = start_config if start_config is not None else start.load_auto_start_config()
    raw = data.get("apps", {})
    apps = {k: v is True and permission_possible(k, sc) for k, v in raw.items()} if isinstance(raw, dict) else {}
    limit = data.get("daily_limit", 2)
    if type(limit) is not int or limit < 0:
        limit = 2
    paths = data.get("protected_paths", list(DEFAULT_PROTECTED_PATHS))
    if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
        paths = list(DEFAULT_PROTECTED_PATHS)
    return ApprovalConfig(apps, limit, tuple(dict.fromkeys((*DEFAULT_PROTECTED_PATHS, *paths))))


def save_config(config, path=None, *, start_config=None):
    sc = start_config if start_config is not None else start.load_auto_start_config()
    start._write_json_atomic(path if path is not None else config_path(), {
        "apps": {k: v is True and permission_possible(k, sc) for k, v in config.apps.items()},
        "daily_limit": config.daily_limit, "protected_paths": list(config.protected_paths)})


def set_app_allowed(app_key, value, *, path=None, start_config=None):
    sc = start_config if start_config is not None else start.load_auto_start_config()
    config = load_config(path, start_config=sc)
    apps = dict(config.apps)
    apps[app_key] = value is True and permission_possible(app_key, sc)
    updated = ApprovalConfig(apps, config.daily_limit, config.protected_paths)
    save_config(updated, path, start_config=sc)
    return updated


@dataclass(frozen=True)
class Decision:
    reasons: tuple = ()
    files: int | None = None
    lines: int | None = None

    @property
    def label(self):
        return HUMAN + "（" + "、".join(self.reasons) + "）" if self.reasons else ELIGIBLE


def _number(value):
    return type(value) is int and value >= 0


def _protected(path, patterns):
    parts = path.lower().split("/")
    return any(any(fnmatchcase("/".join(parts[i:]), p.lower().rstrip("/")) or
                   (p.endswith("/") and "/".join(parts[i:]).startswith(p.lower()))
                   for i in range(len(parts))) for p in patterns)


def evaluate(run, changes, ci, config, *, automatic):
    """Pure predicate. Provenance comes from Task 18's local association, not Run text.
    changes is a list of {path, status, added, deleted}; missing/binary data fails closed.
    """
    if automatic is not True:
        return None
    reasons = []
    def check(value, expected, reason):
        if value is None or value == "":
            reasons.append(UNAVAILABLE)
        elif value != expected:
            reasons.append(reason)
    run = run if isinstance(run, dict) else {}
    for key, expected, reason in zip(
            ("stage", "tests", "reviewer", "safety", "apply_status"),
            ("completed", "PASS", "PASS", "PASS", "ready"), REASONS[1:6]):
        check(run.get(key), expected, reason)
    files = lines = None
    valid = isinstance(changes, list)
    if valid:
        for c in changes:
            if not isinstance(c, dict):
                valid = False
                break
            p = c.get("path")
            if (not isinstance(p, str) or not p or "\\" in p or ":" in p
                    or p.startswith("/") or ".." in p.split("/")
                    or any(ord(ch) < 32 for ch in p) or c.get("status") not in ("A", "M", "D")
                    or not _number(c.get("added")) or not _number(c.get("deleted"))):
                valid = False
                break
    if not valid:
        reasons.append(UNAVAILABLE)
    else:
        files = len(changes)
        lines = sum(c["added"] + c["deleted"] for c in changes)
        if files > 5:
            reasons.append(REASONS[6])
        if lines > 300:
            reasons.append(REASONS[7])
        if not any(c["status"] in ("A", "M") and (
                "tests" in PurePosixPath(c["path"]).parts[:-1]
                or PurePosixPath(c["path"]).name.startswith("test_")
                or PurePosixPath(c["path"]).name.endswith("_test.py")) for c in changes):
            reasons.append(REASONS[8])
        if any(_protected(c["path"], config.protected_paths) for c in changes):
            reasons.append(REASONS[9])
    check(ci if ci not in ("UNKNOWN", "UNAVAILABLE") else None, "GREEN", REASONS[10])
    return Decision(tuple(dict.fromkeys(reasons)), files, lines)


def run_values(record):
    """Engine._finalize writes completed/OK only after the final safety gate.
    Tests counters and the final review must independently corroborate that marker.
    Free-text final_result.message is deliberately never interpreted.
    """
    if not isinstance(record, dict):
        return {}
    final = record.get("final_result")
    final = final if isinstance(final, dict) else {}
    reviews = record.get("review_history")
    review = reviews[-1] if isinstance(reviews, list) and reviews else {}
    review = review if isinstance(review, dict) else {}
    count, failures = record.get("tests_run_count"), record.get("tests_consecutive_fail_count")
    tests = None
    if _number(count) and _number(failures) and type(review.get("tests_ok")) is bool:
        tests = "PASS" if count > 0 and failures == 0 and review.get("tests_ok") is True else "FAIL"
    safety = None
    if final.get("code") is not None and final.get("stage") is not None:
        safety = "PASS" if final.get("code") == "OK" and final.get("stage") == "completed" else "FAIL"
    return dict(stage=record.get("stage"), tests=tests, reviewer=review.get("verdict"),
                safety=safety, apply_status=record.get("apply_status"))


def read_run(run_id):
    from tools.ai_orchestrator import runstate
    # Enumerate trusted root, never join an untrusted Run identifier as a path.
    for directory in runstate.runs_root().iterdir():
        if directory.name == run_id and directory.is_dir() and not directory.is_symlink():
            return runstate.read_record(directory)
    return None


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None


def read_changes(app_key, record):
    from tools.ai_orchestrator.orchestrator import resolve_repo_dir_for_app
    repo = resolve_repo_dir_for_app(app_key)
    base, candidate = record.get("base_sha"), record.get("candidate_sha")
    if repo is None or not _sha(base) or not _sha(candidate):
        return None
    def git(*args):
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError("unavailable")
        return result.stdout.decode("utf-8", errors="strict")
    # Disable rename folding: both the deleted and added paths must be checked.
    args = ("--no-ext-diff", "--no-textconv", "--no-renames", base, candidate, "--")
    stats = git("diff", "--numstat", "-z", *args).split("\0")
    names = git("diff", "--name-status", "-z", *args).split("\0")
    statuses = dict(zip(names[1::2], names[0::2]))
    changes = []
    for item in filter(None, stats):
        added, deleted, path = item.split("\t", 2)
        changes.append(dict(path=path, status=statuses.get(path), added=int(added), deleted=int(deleted)))
    return changes


def read_ci(app_key):
    from tools.ai_orchestrator.orchestrator import resolve_repo_definition
    from .core import fetch_github_state
    definition = resolve_repo_definition(app_key)
    if definition is None:
        return None
    state = fetch_github_state(definition)
    return None if state.error else state.ci_state


def _result_path(app_key, report_id, directory):
    return directory / start._hash(app_key) / (start._hash(report_id) + ".json")


def _payload_decision(data):
    if not isinstance(data, dict):
        return None
    reasons = data.get("reasons")
    if (not isinstance(reasons, list) or not all(isinstance(r, str) and r in REASONS for r in reasons)
            or data.get("result") != (HUMAN if reasons else ELIGIBLE)
            or any(data.get(k) != "不明" and not _number(data.get(k)) for k in ("files", "lines"))):
        return None
    return Decision(tuple(reasons), *(data[k] if _number(data[k]) else None for k in ("files", "lines")))


def load_labels(identities, global_config, start_config, config, *, results_dir=None, records_dir=None):
    directory = results_dir if results_dir is not None else root() / "results"
    labels = {}
    for app_key, report_id in identities:
        if allowed(app_key, global_config, start_config, config):
            association = start.load_auto_start_record(app_key, report_id, root=records_dir)
            if association is None or not association.run_id:
                continue
            decision = _payload_decision(start._read_json(_result_path(app_key, report_id, directory)))
            if decision is not None:
                labels[(app_key, report_id)] = decision.label
    return labels


def record_decision(app_key, report_id, candidate, decision, *, run_id=None, results_dir=None, log_dir=None):
    directory = results_dir if results_dir is not None else root() / "results"
    logs = log_dir if log_dir is not None else root() / "run_log"
    # app_key originates in local config, but even a corrupted config must not leak paths.
    safe_app = app_key if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", app_key) else "不明"
    # candidate_full/run_id are DCC Task 19c-2a's own strict-match keys (never report- or
    # AI-derived -- candidate comes from the same trusted Run record as `candidate`, run_id from
    # Task 18's own association); `candidate` above stays the display-only truncated field so
    # Task 19c-1's own screen/log shape is unchanged.
    safe_run_id = run_id if isinstance(run_id, str) and run_id else "不明"
    payload = dict(app=safe_app, candidate=candidate[:12].lower() if _sha(candidate) else "不明",
                   candidate_full=candidate.lower() if _sha(candidate) else "不明", run_id=safe_run_id,
                   result=HUMAN if decision.reasons else ELIGIBLE, reasons=list(decision.reasons),
                   files=decision.files if _number(decision.files) else "不明",
                   lines=decision.lines if _number(decision.lines) else "不明")
    path = _result_path(app_key, report_id, directory)
    payload["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start._write_json_atomic(path, payload)
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    start._write_json_atomic(logs / f"{stamp}-{start._next_log_sequence():010d}.json", payload)
    start._prune_old_logs(logs, 50)


def refresh(reports, global_config, start_config, config, *, records_dir=None,
            results_dir=None, log_dir=None, run_fn=read_run, changes_fn=read_changes, ci_fn=read_ci,
            current_settings_fn=None, activity_log_path=None):
    """Observation only. Manual Runs cannot enter: require Task 18's association first."""
    if global_config.enabled is not True:
        return
    for report in reports:
        if not allowed(report.app_key, global_config, start_config, config):
            continue
        association = start.load_auto_start_record(report.app_key, report.report_id, root=records_dir)
        if association is None or not association.run_id:
            continue
        record = None
        try:
            record = run_fn(association.run_id)
        except Exception:
            pass
        if isinstance(record, dict) and record.get("stage") in (
                "created", "preflight", "implementing", "testing", "repairing", "reviewing", "finalizing", "stopping"):
            continue  # active Run: wait for its terminal observation
        changes = ci = None
        if isinstance(record, dict):
            try:
                changes = changes_fn(report.app_key, record)
            except Exception:
                pass
            try:
                ci = ci_fn(report.app_key)
            except Exception:
                pass
        if current_settings_fn is not None:
            global_config, start_config, config = current_settings_fn()
            if not allowed(report.app_key, global_config, start_config, config):
                continue
        decision = evaluate(run_values(record), changes, ci, config, automatic=True)
        candidate = record.get("candidate_sha") if isinstance(record, dict) else None
        if not _sha(candidate):
            decision = Decision(tuple(dict.fromkeys((*decision.reasons, UNAVAILABLE))), decision.files, decision.lines)
        try:
            record_decision(report.app_key, report.report_id, candidate, decision, run_id=association.run_id,
                            results_dir=results_dir, log_dir=log_dir)
        except OSError:
            pass
        # DCC Task WF-6b 仕様1: 判定（対象／人の確認が必要）の記録点 -- 自動承認そのものの動作は変えない。
        _log_activity(action=activity_log.ACTION_COMPLETE, target_type=activity_log.TARGET_REPORT,
                      target_id=start._hash(report.report_id),
                      result=activity_log.RESULT_NEEDS_HUMAN if decision.reasons else activity_log.RESULT_PROCEED,
                      path=activity_log_path)


def refresh_once():
    """Called by DCC's existing background observation cycle, never on Tk's thread."""
    def current_settings():
        gc = auto.load_auto_mode_config()
        sc = start.load_auto_start_config()
        return gc, sc, load_config(start_config=sc)
    gc, sc, config = current_settings()
    if not gc.enabled or not any(allowed(k, gc, sc, config) for k in config.apps):
        return
    cfg = start.inbox.load_reports_config()
    inboxes = start.inbox.scan_all([(a.app_key, a.display_name, a.shared_root) for a in cfg.apps])
    refresh(start.inbox.all_reports(inboxes), gc, sc, config, current_settings_fn=current_settings)
