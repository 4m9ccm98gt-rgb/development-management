"""DCC Task WF-6c: read-only snapshot for the "自動処理の状況" screen (automation_status_view.py).

Reads activity_log.py (DCC Task WF-6a/WF-6b's shared record) and each automatic-processing
module's own already-existing, read-only settings/eligibility functions (reports_auto.py,
reports_auto_start.py, reports_auto_approve.py, reports_auto_progress.py, orchestrator_requeue.py,
workflow_runner.py/workflow_plan.py), and projects them onto a small closed vocabulary
(STATE_*/REASON_*) for display. Never starts, approves, pushes, builds, updates or releases
anything, and never writes to the activity record or any other file -- this module only reads.

Security posture (same family as activity_log.py):
 - Every field this module returns is one of its own fixed words, a role's own already-hashed
   next-report id (reports_auto.peek_next_report_id -- never the raw report_id), a timestamp
   copied verbatim from an already-validated activity_log.ActivityEntry, or a number -- never a
   report body, Task/plan body, AI free-text output, a path, or an exception's own text.
 - A read/parse/config failure anywhere below is caught and degraded to a fixed placeholder (an
   unreadable activity log sets log_unreadable=True with an empty entry list; every config loader
   this module calls already degrades to safe, all-OFF defaults on its own -- see each module's
   own load_*/daily_limit_reached docstring); nothing here ever lets an underlying exception's
   own message reach the screen.

Reviewer finding 1 (this revision): 計画の自動実行 (ROLE_AUTO_PLAN) no longer classifies itself
with a hand-rolled "permission on and not globally stopped -> running" rule. It instead reuses
workflow_runner.plan_start_block_reason -- the exact same read-only judgment
_start_eligible_task/run_workflow_runner_once themselves call before ever starting a task -- for
every one of this DCC process's own enabled plans, so this screen's own "running/waiting/stopped"
call can never silently disagree with what the real cycle does next. Busy is checked only against
the specific repository the eligible task of each plan would use (busy_fn/repo_run_blocked_fn are
threaded straight through to plan_start_block_reason, never a blanket "something, somewhere is
busy" flag) -- an unrelated repository's own manual Run/PUSH/BUILD no longer makes this role (or
自動承認, which the real reports_auto_approve.refresh never busy-gates at all -- see its own
docstring) show 待機中 for no reason.

Reviewer finding 1 (repair): permission being ON and the daily limit not being reached are no
longer, by themselves, read as "動いている" for any role. classify() now only returns
STATE_RUNNING when a caller passes `running=True`, backed by that role's own already-existing,
read-only state -- never eligibility/permission alone. For 自動調査 that comes from the shared
activity record itself (_triage_is_processing: its last logged action is still ACTION_START, with
no ACTION_COMPLETE/ACTION_FAIL yet); for 計画の自動実行 it is already workflow_runner's own
START_BLOCK_RUNNING (a task whose status is literally "running"), now kept strictly apart from
START_BLOCK_CAN_START (eligible but not yet started -> STATE_WAITING/REASON_NOT_STARTED, never
STATE_RUNNING). 自動開始/自動承認/自動再実行 have no equivalent existing "still in progress"
record to read (each logs a momentary action, not a bracketed start/finish pair), so they are
never shown as 動いている here -- showing 待機中 while eligible/permitted is the honest reading of
what is actually, verifiably known from their own existing state.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import activity_log
from . import orchestrator_requeue as requeue
from . import reports_auto as auto
from . import reports_auto_approve as approve
from . import reports_auto_progress as progress
from . import reports_auto_start as start
from . import workflow_plan as wf
from . import workflow_runner as runner

STATE_RUNNING = "動いている"
STATE_WAITING = "待機中"
STATE_STOPPED = "止まっている"

REASON_GLOBAL_OFF = "全体の停止スイッチがOFF"
REASON_PERMISSION_OFF = "許可がOFF"
REASON_DAILY_LIMIT = "1日の上限"
REASON_BUSY = "他の処理が動いている"
REASON_PLAN_PAUSED = "計画が一時停止中"
REASON_NO_APPROVED = "承認済みのタスクがない"
REASON_DEPENDS_INCOMPLETE = "依存するタスクが未完了"
REASON_RECORD_UNAVAILABLE = "記録を確認できない"
REASON_NOT_STARTED = "未開始"
REASON_NONE = ""

LOG_UNREADABLE_TEXT = "活動の記録を読めません"
LOGIN_EXPIRED_HINT = "claude.cmd を起動して /login でログインし直してください"
QUOTA_LIMIT_HINT = "使用枠の上限に達しました。時間をおいて再開されます"
NO_NEXT_REPORT_TEXT = "なし"

MAX_RECENT = 100


def hint_for_reason(reason: str) -> str:
    """仕様2: the fixed extra sentence for the two AI-failure reasons a human must act on, keyed
    only off activity_log's own closed REASON_* vocabulary -- never off any free text."""
    if reason == activity_log.REASON_LOGIN_EXPIRED:
        return LOGIN_EXPIRED_HINT
    if reason == activity_log.REASON_QUOTA_LIMIT:
        return QUOTA_LIMIT_HINT
    return ""


def classify(*, global_enabled: bool, permission_on: bool, limit_reached: bool,
             running: bool = False, busy: bool = False) -> tuple[str, str]:
    """The priority order 自動調査/自動開始/自動承認/自動再実行 each use (計画の自動実行 has its
    own richer判定 -- see _runner_role_state below): global switch off -> this role's own
    permission off -> this role's own daily limit reached -> otherwise 動いている only when the
    caller has separately confirmed, read-only, from that role's own already-existing state, that
    it is actually processing something right now (`running`) -- permission/eligibility alone
    (Reviewer finding 1: 許可ON・上限未到達だけ) is never enough. `busy` is kept for callers/tests
    that still want the generic waiting-on-busy shape; checked only once `running` is False.
    Returns (state, reason); reason is REASON_NONE exactly when state is STATE_RUNNING."""
    if not global_enabled:
        return STATE_STOPPED, REASON_GLOBAL_OFF
    if not permission_on:
        return STATE_STOPPED, REASON_PERMISSION_OFF
    if limit_reached:
        return STATE_STOPPED, REASON_DAILY_LIMIT
    if running:
        return STATE_RUNNING, REASON_NONE
    if busy:
        return STATE_WAITING, REASON_BUSY
    return STATE_WAITING, REASON_NOT_STARTED


# Reviewer finding 1: 計画の自動実行 only -- the one role whose real cycle (workflow_runner.py)
# already exposes a read-only "why would the next task not start" judgment
# (plan_start_block_reason) that itself re-checks eligibility/pause/dependency/repo-busy per plan.
# Every code plan_start_block_reason can return is mapped here exactly once, so a future new
# START_BLOCK_* code (that nobody maps) still shows a safe default (STATE_WAITING/REASON_BUSY)
# rather than silently and wrongly claiming the role is running.
#
# Reviewer finding 1 (repair): START_BLOCK_CAN_START ("an eligible task exists but has not
# actually been started yet") is its own case, mapped to STATE_WAITING/REASON_NOT_STARTED below --
# only START_BLOCK_RUNNING (a task whose own status is already "running") is STATE_RUNNING. The
# two must never share one bucket: CAN_START is eligibility/startability, not actual processing.
_RUNNER_STOPPED_REASON = {
    runner.START_BLOCK_GLOBAL_OFF: REASON_GLOBAL_OFF,
    runner.START_BLOCK_LIMIT_REACHED: REASON_DAILY_LIMIT,
    runner.START_BLOCK_RECORD_UNAVAILABLE: REASON_RECORD_UNAVAILABLE,
    runner.START_BLOCK_PLAN_AUTO_RUN_OFF: REASON_PERMISSION_OFF,
}
_RUNNER_WAITING_REASON = {
    runner.START_BLOCK_PAUSED: REASON_PLAN_PAUSED,
    runner.START_BLOCK_NO_APPROVED: REASON_NO_APPROVED,
    runner.START_BLOCK_DEPENDS_INCOMPLETE: REASON_DEPENDS_INCOMPLETE,
    runner.START_BLOCK_REPO_BUSY: REASON_BUSY,
}


def _runner_role_state(
    *,
    global_enabled: bool,
    runner_config: "runner.WorkflowRunnerConfig",
    global_config: "auto.AutoModeConfig",
    today: str,
    daily_count_path: Path | None,
    plans_root: Path | None,
    registered_keys,
    busy_fn: Callable[[str], bool] | None,
    repo_run_blocked_fn: Callable[[str], bool] | None,
    resolve_repo_dir: Callable[[str], Path | None] | None,
) -> tuple[str, str]:
    """計画の自動実行の現在の状態。全体の停止スイッチ/共有の1日の上限は、どの計画も読めない場合
    にも必ず効く独立した判定として先に見る（run_workflow_runner_once 自身の
    サイクルレベルの早期終了と同じ2段構成 -- Reviewer finding 1）。それを過ぎたら、許可がONの
    計画ごとに plan_start_block_reason（実際の開始判定そのもの）へ委ね、どれか1つでも
    CAN_START/RUNNING なら全体を「動いている」とする。残りはすべて「待機中」（一時停止・
    承認待ち・依存待ち・対象リポジトリの競合・未開始はいずれも一時的な事情で、許可もスイッチも
    ONのままなので「止まっている」ではない）。どの計画か1つでも実際に実行中（タスク自身の
    status が running）なら、それを最優先でSTATE_RUNNINGとする（Reviewer finding 1 repair:
    他の計画が単にCAN_STARTであっても、実際に動いている計画があればそちらを必ず優先するため、
    CAN_STARTで即returnせず走査を続ける）。"""
    if not global_enabled:
        return STATE_STOPPED, REASON_GLOBAL_OFF
    if runner.daily_limit_reached(today, runner_config.daily_limit, path=daily_count_path):
        return STATE_STOPPED, REASON_DAILY_LIMIT

    enabled_plan_ids = [plan_id for plan_id, on in runner_config.plans.items() if on]
    if not enabled_plan_ids:
        return STATE_STOPPED, REASON_PERMISSION_OFF

    any_loaded = False
    waiting: tuple[str, str] | None = None
    for plan_id in enabled_plan_ids:
        try:
            loaded_plan = wf.load_plan(plan_id, root=plans_root, registered_keys=registered_keys)
        except Exception:  # noqa: BLE001 - unreadable/corrupt plan: try the next, never crash
            continue
        any_loaded = True
        reason = runner.plan_start_block_reason(
            loaded_plan, global_config=global_config, runner_config=runner_config, today=today,
            daily_count_path=daily_count_path, resolve_repo_dir=resolve_repo_dir,
            busy_fn=busy_fn, repo_run_blocked_fn=repo_run_blocked_fn)
        if reason.code == runner.START_BLOCK_RUNNING:
            return STATE_RUNNING, REASON_NONE
        if reason.code in _RUNNER_STOPPED_REASON:
            return STATE_STOPPED, _RUNNER_STOPPED_REASON[reason.code]
        if reason.code == runner.START_BLOCK_CAN_START:
            if waiting is None:
                waiting = (STATE_WAITING, REASON_NOT_STARTED)
            continue
        if waiting is None:
            waiting = (STATE_WAITING, _RUNNER_WAITING_REASON.get(reason.code, REASON_BUSY))
    if not any_loaded:
        return STATE_STOPPED, REASON_PERMISSION_OFF
    return waiting if waiting is not None else (STATE_STOPPED, REASON_PERMISSION_OFF)


@dataclass(frozen=True)
class RoleStatus:
    role: str
    state: str
    reason: str
    last_activity_at: str = ""
    last_result: str = ""
    last_reason: str = ""
    hint: str = ""


@dataclass(frozen=True)
class StatusSnapshot:
    roles: tuple[RoleStatus, ...]
    recent: tuple["activity_log.ActivityEntry", ...]
    next_report_id: str
    not_running_reason: str
    log_unreadable: bool = False


def format_timestamp(ts: str) -> str:
    """"YYYY-MM-DDTHH:MM:SSZ" -> "YYYY-MM-DD HH:MM:SS", for both a role's own last-activity time
    and the recent-activity table's own 時刻 column (automation_status_view.py reuses this
    directly rather than reformatting the same ActivityEntry.timestamp a second way)."""
    return ts.replace("T", " ").rstrip("Z") if ts else ""


def _last_for_role(role: str, entries: tuple) -> "activity_log.ActivityEntry | None":
    for entry in entries:  # entries is already newest-first (activity_log.read_recent's contract)
        if entry.role == role:
            return entry
    return None


def _triage_is_processing(entries: tuple) -> bool:
    """Reviewer finding 1 (repair): 自動調査 is the one of the four simple roles whose own cycle
    (reports_auto.run_auto_triage_once) already logs an ACTION_START immediately before its one
    (possibly slow) AI call and always follows it with ACTION_COMPLETE/ACTION_FAIL under the same
    role once that call returns -- so "the most recently logged entry for 自動調査 is still
    ACTION_START" is read-only, already-existing evidence that it is actually investigating a
    report right now, never a guess from permission/eligibility alone. 自動開始/自動承認/
    自動再実行 do not log a matching completion under their own role for every start (each is a
    momentary action, not a long call this activity log brackets) -- applying this same check to
    them would make a role look permanently "動いている" after its very first-ever action, which
    is exactly the wrong kind of always-on reading the reviewer flagged, so it is intentionally
    used for 自動調査 only."""
    last = _last_for_role(activity_log.ROLE_AUTO_TRIAGE, entries)
    return last is not None and last.action == activity_log.ACTION_START


def _role_status(role: str, *, state: str, reason: str, entries: tuple) -> RoleStatus:
    last = _last_for_role(role, entries)
    if last is None:
        return RoleStatus(role=role, state=state, reason=reason)
    return RoleStatus(
        role=role, state=state, reason=reason,
        last_activity_at=format_timestamp(last.timestamp),
        last_result=last.result, last_reason=last.reason,
        hint=hint_for_reason(last.reason),
    )


def _disk_count_reached(reader: Callable[[], int], limit: int) -> bool:
    """Display-only daily-limit check, shared shape for the two roles (自動承認/自動再実行) whose
    own module has no public path-only daily_limit_reached (reports_auto.py/reports_auto_start.py/
    workflow_runner.py each already expose one; see their own calls below). Never raises: an
    unreadable/corrupt count file reads as "not reached" here, same as workflow_runner's own
    display-only daily_limit_reached degrades on a read failure -- this is a status screen, never
    the real gate (ProgressState.seed_startup / RequeueState.daily_count stay the real gates)."""
    try:
        return reader() >= limit
    except Exception:  # noqa: BLE001 - display-only
        return False


def build_snapshot(
    *,
    activity_log_path: Path | None = None,
    triage_config_path: Path | None = None,
    triage_daily_count_path: Path | None = None,
    triage_results_dir: Path | None = None,
    start_config_path: Path | None = None,
    start_daily_count_path: Path | None = None,
    approve_config_path: Path | None = None,
    approve_daily_count_path: Path | None = None,
    requeue_config_path: Path | None = None,
    requeue_daily_count_path: Path | None = None,
    workflow_runner_config_path: Path | None = None,
    workflow_runner_daily_count_path: Path | None = None,
    workflow_runner_plans_root: Path | None = None,
    workflow_runner_registered_keys=None,
    workflow_runner_busy_fn: Callable[[str], bool] | None = None,
    workflow_runner_repo_run_blocked_fn: Callable[[str], bool] | None = None,
    workflow_runner_resolve_repo_dir: Callable[[str], Path | None] | None = None,
    today: str | None = None,
    reports_config_fn: Callable[[], object] | None = None,
    scan_fn: Callable[[list], list] | None = None,
    load_decision_fn: Callable[[str, str], object] | None = None,
) -> StatusSnapshot:
    """One read-only pass over the shared activity record and every automatic-processing module's
    own already-existing settings files -- never a write, never an AI call, never approve/push/
    BUILD/UPDATE/RELEASE. Every path argument defaults to that module's own real on-disk
    location; a caller (tests, or a future caller with no special path) gets a safe, fully
    degraded snapshot without needing to own or thread through any live in-memory state --
    display-only daily-limit reads are used throughout (see _disk_count_reached), the same
    convention workflow_runner.daily_limit_reached/workflow_plan_view.py already use for the
    identical "show the limit, never gate on it here" purpose.

    workflow_runner_busy_fn/workflow_runner_repo_run_blocked_fn/workflow_runner_resolve_repo_dir
    (Reviewer finding 1) are threaded straight through to workflow_runner.plan_start_block_reason
    for 計画の自動実行 -- never resolved to a blanket "something is busy" flag here. Left at their
    default (None), plan_start_block_reason falls back to its own real-repo defaults, same as a
    standalone (non-App) caller of that function gets; app.py's own caller passes its real
    App._repo_name_busy instead, scoped to one repository at a time exactly as the real workflow
    runner loop already does."""
    today = today if today is not None else auto.today_str()

    log_unreadable = False
    try:
        entries: tuple = tuple(activity_log.read_recent(path=activity_log_path))
    except activity_log.ActivityLogError:
        entries = ()
        log_unreadable = True

    triage_config = auto.load_auto_mode_config(triage_config_path)
    start_config = start.load_auto_start_config(start_config_path)
    approve_config = approve.load_config(approve_config_path, start_config=start_config)
    requeue_config = requeue.load_requeue_config(requeue_config_path)
    runner_config = runner.load_workflow_runner_config(workflow_runner_config_path)

    global_enabled = triage_config.enabled

    triage_state, triage_reason = classify(
        global_enabled=global_enabled, permission_on=any(triage_config.apps.values()),
        limit_reached=auto.daily_limit_reached(triage_config, today, path=triage_daily_count_path),
        running=_triage_is_processing(entries))
    start_state, start_reason = classify(
        global_enabled=global_enabled, permission_on=any(start_config.apps.values()),
        limit_reached=start.daily_limit_reached(start_config, today, path=start_daily_count_path))
    approve_path = approve_daily_count_path if approve_daily_count_path is not None else progress.daily_count_path()
    # Reviewer finding 1: reports_auto_approve.refresh (its real cycle) never busy-gates at all --
    # it only ever observes an already-finished Run's own result -- so this role is never made to
    # wait on any repo's busy state; permission/limit are its only two blocking conditions.
    approve_state, approve_reason = classify(
        global_enabled=global_enabled, permission_on=any(approve_config.apps.values()),
        limit_reached=_disk_count_reached(
            lambda: progress._read_daily_count_strict(today, approve_path), approve_config.daily_limit))
    requeue_path = requeue_daily_count_path if requeue_daily_count_path is not None else requeue.daily_count_path()
    requeue_role_state, requeue_reason = classify(
        global_enabled=global_enabled, permission_on=requeue_config.enabled,
        limit_reached=_disk_count_reached(
            lambda: requeue._read_daily_count(today, requeue_path), requeue_config.daily_limit))
    runner_role_state, runner_reason = _runner_role_state(
        global_enabled=global_enabled, runner_config=runner_config, global_config=triage_config,
        today=today, daily_count_path=workflow_runner_daily_count_path,
        plans_root=workflow_runner_plans_root, registered_keys=workflow_runner_registered_keys,
        busy_fn=workflow_runner_busy_fn, repo_run_blocked_fn=workflow_runner_repo_run_blocked_fn,
        resolve_repo_dir=workflow_runner_resolve_repo_dir)

    roles = (
        _role_status(activity_log.ROLE_AUTO_TRIAGE, state=triage_state, reason=triage_reason, entries=entries),
        _role_status(activity_log.ROLE_AUTO_START, state=start_state, reason=start_reason, entries=entries),
        _role_status(activity_log.ROLE_AUTO_APPROVE, state=approve_state, reason=approve_reason, entries=entries),
        _role_status(activity_log.ROLE_AUTO_RETRY, state=requeue_role_state, reason=requeue_reason, entries=entries),
        _role_status(activity_log.ROLE_AUTO_PLAN, state=runner_role_state, reason=runner_reason, entries=entries),
    )

    try:
        next_report_id = auto.peek_next_report_id(
            config=triage_config, today=today, reports_config_fn=reports_config_fn, scan_fn=scan_fn,
            load_decision_fn=load_decision_fn, daily_count_path=triage_daily_count_path,
            results_dir=triage_results_dir)
    except Exception:  # noqa: BLE001 - a broken preview must never crash the status screen
        next_report_id = ""

    return StatusSnapshot(
        roles=roles, recent=entries[:MAX_RECENT], next_report_id=next_report_id,
        not_running_reason=triage_reason, log_unreadable=log_unreadable,
    )
