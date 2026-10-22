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


def _word(value, allowed, default='unknown'):
    return value if isinstance(value, str) and value in allowed else default


def _id(value, limit):
    return value if isinstance(value, str) and re.fullmatch(
        r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) else None


def _run(association, observations):
    result = dict(run_id=None, stage='unknown', liveness='unknown', availability='unavailable')
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
