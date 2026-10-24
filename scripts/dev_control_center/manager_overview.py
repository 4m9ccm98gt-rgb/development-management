"""Read-only Manager projection; workflow_plan remains the sole TASK authority.

No loaders, clocks, callbacks, writes or execution entry points are used here.
Callers supply loaded plans, registered repository keys, runner associations keyed
by (plan_id, task_id), and inspect_run-shaped observations keyed by run_id.
None represents missing/unreadable data. Observations must come from trusted
collectors, never task text. This is recorded state, not start eligibility.
"""
from __future__ import annotations

import re

from . import workflow_plan as wf

ACTIVE_STAGES = frozenset(('created', 'preflight', 'implementing', 'testing',
                           'repairing', 'reviewing', 'finalizing', 'stopping'))
TERMINAL_STAGES = frozenset(('completed', 'needs_human', 'failed', 'stopped'))
LIVENESS = frozenset(('finished', 'running', 'starting', 'unresponsive', 'lost', 'unknown'))
CATEGORY = {'proposed': 'not_started', 'approved': 'waiting', 'held': 'waiting',
            'running': 'running', 'candidate_ready': 'needs_human',
            'landed': 'completed', 'failed': 'failed', 'needs_human': 'needs_human',
            'cancelled': 'cancelled'}

# DCC Task UI-D1: 動いているタスク＝準備中・実装中・テスト中・修理中・レビュー中・最終処理中のみ
# （作成済み／停止処理中／完了・失敗・停止・needs_humanはここに含めない）。
RUNNING_STAGES = frozenset(('preflight', 'implementing', 'testing', 'repairing', 'reviewing', 'finalizing'))
# A stage still looking active on disk is not actually 動いている unless its worker is
# provably alive: lost/unresponsive/unknown (or finished, which a stage in RUNNING_STAGES
# should never carry) must not render as a normal running row.
ALIVE_LIVENESS = frozenset(('running', 'starting'))

ORIGIN_PLAN = '計画'
ORIGIN_REPORT = '報告'
ORIGIN_REQUEST = '依頼'
ORIGINS = frozenset((ORIGIN_PLAN, ORIGIN_REPORT, ORIGIN_REQUEST))

# DCC Task UI-D2: closed vocabulary for a needs_human run's own PROVIDER_QUOTA 振り分け (computed
# upstream by orchestrator_requeue.quota_bucket/quota_display, never derived here) -- see _run
# and running_tasks below.
QUOTA_WAITING = 'quota_waiting'
QUOTA_MANUAL_TEMPORARY = 'manual_temporary'
QUOTA_MANUAL_PERMANENT = 'manual_permanent'
QUOTA_BUCKETS = frozenset((QUOTA_WAITING, QUOTA_MANUAL_TEMPORARY, QUOTA_MANUAL_PERMANENT))

_RUN_ID = re.compile(r'[0-9]{8}-[0-9]{6}-[0-9]{6}')
_REPO_NAME = re.compile(r'[A-Za-z0-9_.-]{1,80}')


def task_origin(run_id, *, plan_run_ids, report_run_ids):
    """Fixed-word 出どころ for one run_id (DCC Task UI-D1, C1): 計画 when the run is linked to a
    workflow-plan task (plan_run_ids), else 報告 when it is linked to a report-inbox automatic
    start (report_run_ids), else 依頼 -- the fallback for anything else, including an unrecognized
    or unidentifiable run_id. Never guesses; membership only."""
    if isinstance(run_id, str) and run_id in (plan_run_ids or ()):
        return ORIGIN_PLAN
    if isinstance(run_id, str) and run_id in (report_run_ids or ()):
        return ORIGIN_REPORT
    return ORIGIN_REQUEST


def _repo_name(value):
    if not isinstance(value, str):
        return None
    name = value.replace('\\', '/').rsplit('/', 1)[-1]
    return name if _REPO_NAME.fullmatch(name) else None


def running_tasks(all_runs, *, plan_run_ids, report_run_ids):
    """Pure projection: one row per currently 動いている run (stage in RUNNING_STAGES AND
    liveness in ALIVE_LIVENESS), each tagged with task_origin. A row whose worker is
    lost/unresponsive/unknown (or whose liveness is otherwise missing/invalid) is dropped even
    if its saved stage still looks active -- a stage alone never proves the worker is alive.
    `all_runs` entries missing/invalid required fields are dropped, never guessed; a duplicate
    run_id keeps only its first entry. Only run_id/stage/repo/main_agent/review_agent/origin are
    exposed -- no other field of an `all_runs` entry passes through.

    DCC Task UI-D2 (C1): a run whose own entry already carries quota_bucket == QUOTA_WAITING
    (computed upstream by orchestrator_requeue.quota_display, never derived here) is also
    included even though its own stage (needs_human) is never in RUNNING_STAGES and its own
    liveness (finished) is never in ALIVE_LIVENESS -- it reached that terminal state only because
    an automatic requeue is actually scheduled, so the Manager's own 動いているタスク view keeps
    showing it (as 使用枠待ち, with the manager_label's own ETA) instead of letting it vanish."""
    rows = []
    seen = set()
    plan_run_ids = plan_run_ids or ()
    report_run_ids = report_run_ids or ()
    for item in all_runs if isinstance(all_runs, list) else ():
        if not isinstance(item, dict):
            continue
        rid = item.get('run_id')
        stage = item.get('stage')
        liveness = item.get('liveness')
        if not (isinstance(rid, str) and _RUN_ID.fullmatch(rid)) or rid in seen:
            continue
        quota_label = item.get('quota_label')
        is_quota_waiting = (stage == 'needs_human' and item.get('quota_bucket') == QUOTA_WAITING
                            and liveness == 'finished' and isinstance(quota_label, str) and quota_label)
        if not is_quota_waiting and (stage not in RUNNING_STAGES or liveness not in ALIVE_LIVENESS):
            continue
        seen.add(rid)
        main_agent = item.get('main_agent')
        review_agent = item.get('review_agent')
        rows.append(dict(
            run_id=rid, stage=stage, repo=_repo_name(item.get('repo')),
            main_agent=main_agent if main_agent in ('claude', 'codex') else None,
            review_agent=review_agent if review_agent in ('claude', 'codex') else None,
            quota_bucket=QUOTA_WAITING if is_quota_waiting else None,
            quota_label=quota_label if is_quota_waiting else '',
            origin=task_origin(rid, plan_run_ids=plan_run_ids, report_run_ids=report_run_ids)))
    return rows


def _word(value, allowed, default='unknown'):
    return value if isinstance(value, str) and value in allowed else default


def _id(value, limit):
    return value if isinstance(value, str) and re.fullmatch(
        r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) else None


def _run(association, observations):
    result = dict(run_id=None, stage='unknown', liveness='unknown', availability='unavailable',
                   quota_bucket=None, quota_label='')
    if not isinstance(association, dict):
        return result
    rid = association.get('run_id')
    if not isinstance(rid, str) or not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', rid):
        return result
    result['run_id'] = rid
    observation = observations.get(rid)
    if not isinstance(observation, dict):
        return result
    record = observation.get('record')
    if not isinstance(record, dict) or record.get('run_id') != rid:
        return result
    result['stage'] = _word(record.get('stage'), ACTIVE_STAGES | TERMINAL_STAGES)
    result['liveness'] = _word(observation.get('liveness'), LIVENESS)
    if result['stage'] != 'unknown' and result['liveness'] != 'unknown':
        result['availability'] = 'available'
    # DCC Task UI-D2 (C3): only ever trusted for a needs_human run -- quota_bucket/quota_label
    # are the collector's own closed-vocabulary projection (manager_collector._quota_fields),
    # never derived here and never present for any other stage.
    if result['stage'] == 'needs_human':
        qb = observation.get('quota_bucket')
        if qb in QUOTA_BUCKETS:
            result['quota_bucket'] = qb
            ql = observation.get('quota_label')
            result['quota_label'] = ql if isinstance(ql, str) else ''
    return result


def build_snapshot(plans, *, registered_keys, associations=None, observations=None):
    """Return a fresh JSON-compatible snapshot from a list of workflow plans.

    Full WF validation is reused with explicit registry keys (no registry I/O).
    Invalid plans fail closed as a unit, including cycles/duplicate identities;
    no valid-looking completed tasks from corrupt plans are exposed. Duplicate
    plan IDs likewise fail closed. Empty list is an available empty collection;
    None/non-list is unavailable. Only landed dependencies count as satisfied,
    matching the runner; this projection does not grant execution permission.
    """
    output = dict(schema_version=1, availability='available', plans=[])
    if not isinstance(plans, list):
        output['availability'] = 'unavailable'
        return output
    associations = associations if isinstance(associations, dict) else {}
    observations = observations if isinstance(observations, dict) else {}
    keys = frozenset(k for k in registered_keys if _id(k, 80))
    ids = [p.get('plan_id') for p in plans if isinstance(p, dict)]
    for plan in plans:
        pid = _id(plan.get('plan_id'), 32) if isinstance(plan, dict) else None
        projected = dict(plan_id=pid, availability='unavailable', category='check_required', tasks=[])
        output['plans'].append(projected)
        try:
            wf.validate_plan(plan, registered_keys=keys)
            if ids.count(pid) != 1:
                continue
        except (wf.WorkflowError, TypeError, KeyError, RecursionError):
            continue
        projected['availability'] = 'available'
        projected['category'] = 'recorded'
        by_id = {t['task_id']: t for t in plan['tasks']}
        for task in plan['tasks']:
            deps = [dict(task_id=dep, status=by_id[dep]['status']) for dep in task['depends_on']]
            dep_state = ('satisfied' if all(d['status'] == 'landed' for d in deps) else 'waiting')
            run = _run(associations.get((pid, task['task_id'])), observations)
            category = CATEGORY[task['status']]
            availability = 'available'
            if task['status'] == 'running' and (
                run['availability'] != 'available' or run['stage'] not in ACTIVE_STAGES
                or run['liveness'] not in ('running', 'starting')
            ):
                category, availability = 'check_required', 'unavailable'
            projected['tasks'].append(dict(
                plan_id=pid, task_id=task['task_id'], repo_key=task['repo_key'],
                status=task['status'], category=category, availability=availability,
                dependencies=deps, dependency_state=dep_state, run=run,
                main_ai=task.get('main_ai'), reviewer_ai=task.get('reviewer_ai')))
    if any(p['availability'] != 'available' for p in output['plans']):
        output['availability'] = 'partial'
    return output
