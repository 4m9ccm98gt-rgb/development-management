"""Pure Manager decision boundary. No AI, storage, execution or mutation APIs.

The caller supplies the latest MGR-1 snapshot and a monotonically increasing
observation_id on EVERY collection (including unchanged state). It must revalidate
against the latest observation before presenting/connecting a decision. A digest
cannot detect elapsed time or a revision/body change absent from MGR-1: collection
freshness and observation generations belong to the future trusted collector.

Business context extension: add a separately reviewed typed/allowlisted field to
build_manager_input and bump schema_version; never append raw TASK/report text.
Workflow extension: only hold/release/cancel are supported now. Other WF operations
are UNSUPPORTED_CHANGE, not a new permission/API. Even supported proposals require
current full plan context and WF's manager-actor preview; nothing is applied.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import manager_overview as overview
from . import workflow_plan as wf

KINDS = frozenset(('NO_ACTION', 'PROPOSE_TASK_CHANGE', 'PROPOSE_START', 'REQUEST_HUMAN', 'WAIT'))
REASONS = frozenset(('TERMINAL', 'APPROVED_READY', 'STATE_UNAVAILABLE', 'TASK_FAILED',
                     'HUMAN_REQUIRED', 'APPROVAL_REQUIRED', 'DEPENDENCIES_PENDING',
                     'TASK_ACTIVE', 'HELD', 'QUEUED', 'WORKFLOW_CHANGE'))
SUPPORTED_CHANGES = frozenset(('hold', 'release', 'cancel'))


class DecisionError(ValueError):
    """Only fixed codes cross the boundary."""


def _require(ok, code='INVALID_SNAPSHOT'):
    if not ok:
        raise DecisionError(code)


def _id(value, limit):
    _require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) is not None)
    return value


def _word(value, allowed):
    _require(isinstance(value, str) and value in allowed)
    return value


def build_manager_input(snapshot, *, observation_id):
    """Strict safe projection + content fingerprint. Unknown fields are never copied.

    Unavailable plans are represented without inventing TASKs. Invalid structures
    raise a content-free DecisionError. Unknown TASK state is represented only by
    MGR-1's check_required/unavailable combination, never inferred as success.
    """
    _require(type(observation_id) is int and observation_id >= 0)
    _require(isinstance(snapshot, dict) and type(snapshot.get('schema_version')) is int and snapshot['schema_version'] == 1)
    availability = _word(snapshot.get('availability'), ('available', 'partial', 'unavailable'))
    _require(isinstance(snapshot.get('plans'), list))
    result = dict(schema_version=1, observation_id=observation_id, availability=availability, plans=[])
    seen = set()
    for plan in snapshot['plans']:
        _require(isinstance(plan, dict))
        available = _word(plan.get('availability'), ('available', 'unavailable'))
        pid = plan.get('plan_id')
        if pid is not None:
            _id(pid, 32)
        _require(isinstance(plan.get('tasks'), list))
        if available == 'unavailable':
            _require(not plan['tasks'])
            result['plans'].append(dict(plan_id=pid, availability=available, tasks=[]))
            continue
        _id(pid, 32)
        _require(pid not in seen)
        seen.add(pid)
        tasks = []
        by_id = {}
        for task in plan['tasks']:
            _require(isinstance(task, dict) and task.get('plan_id') == pid)
            tid = _id(task.get('task_id'), 16)
            _require(tid not in by_id)
            status = _word(task.get('status'), wf.STATUSES)
            category = _word(task.get('category'), set(overview.CATEGORY.values()) | {'check_required'})
            task_availability = _word(task.get('availability'), ('available', 'unavailable'))
            _require((category == overview.CATEGORY[status] and task_availability == 'available') or
                     (status == 'running' and category == 'check_required' and task_availability == 'unavailable'))
            clean = dict(plan_id=pid, task_id=tid, repo_key=_id(task.get('repo_key'), 80),
                         status=status, category=category, availability=task_availability)
            for role in ('main_ai', 'reviewer_ai'):
                value = task.get(role)
                _require(value is None or isinstance(value, str) and value in ('claude', 'codex'))
                clean[role] = value
            deps = task.get('dependencies')
            _require(isinstance(deps, list) and len(deps) <= 50)
            clean['dependencies'] = []
            dep_ids = set()
            for dep in deps:
                _require(isinstance(dep, dict))
                did = _id(dep.get('task_id'), 16)
                _require(did not in dep_ids and did != tid)
                dep_ids.add(did)
                clean['dependencies'].append(dict(task_id=did, status=_word(dep.get('status'), wf.STATUSES)))
            expected = 'satisfied' if all(d['status'] == 'landed' for d in clean['dependencies']) else 'waiting'
            _require(task.get('dependency_state') == expected)
            clean['dependency_state'] = expected
            run = task.get('run')
            _require(isinstance(run, dict))
            rid = run.get('run_id')
            _require(rid is None or isinstance(rid, str) and re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', rid) is not None)
            clean['run'] = dict(run_id=rid,
                stage=_word(run.get('stage'), overview.ACTIVE_STAGES | overview.TERMINAL_STAGES | {'unknown'}),
                liveness=_word(run.get('liveness'), overview.LIVENESS),
                availability=_word(run.get('availability'), ('available', 'unavailable')))
            if clean['run']['availability'] == 'available':
                _require(rid is not None and clean['run']['stage'] != 'unknown' and clean['run']['liveness'] != 'unknown')
            if category == 'running':
                _require(clean['run']['availability'] == 'available' and clean['run']['stage'] in overview.ACTIVE_STAGES
                         and clean['run']['liveness'] in ('running', 'starting'))
            tasks.append(clean)
            by_id[tid] = clean
        for task in tasks:
            for dep in task['dependencies']:
                _require(dep['task_id'] in by_id and by_id[dep['task_id']]['status'] == dep['status'])
        # Reject cycles without relying on recursion or accepting ambiguous dependencies.
        pending = {t['task_id']: {d['task_id'] for d in t['dependencies']} for t in tasks}
        done = set()
        while pending:
            ready = {tid for tid, deps in pending.items() if deps <= done}
            _require(bool(ready))
            done.update(ready)
            pending = {tid: deps for tid, deps in pending.items() if tid not in ready}
        result['plans'].append(dict(plan_id=pid, availability=available, tasks=tasks))
    unavailable = any(p['availability'] == 'unavailable' for p in result['plans'])
    _require((availability == 'available' and not unavailable) or
             (availability == 'partial' and unavailable) or
             (availability == 'unavailable' and not result['plans']))
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    result['snapshot_id'] = hashlib.sha256(encoded).hexdigest()
    return result


def _suggest(task, tasks):
    status = task['status']
    if task['availability'] != 'available':
        return 'REQUEST_HUMAN', 'STATE_UNAVAILABLE'
    if status in ('landed', 'cancelled'):
        return 'NO_ACTION', 'TERMINAL'
    if status == 'failed':
        return 'REQUEST_HUMAN', 'TASK_FAILED'
    if status in ('needs_human', 'candidate_ready'):
        return 'REQUEST_HUMAN', 'HUMAN_REQUIRED'
    if status == 'proposed':
        return 'REQUEST_HUMAN', 'APPROVAL_REQUIRED'
    if status == 'held':
        return 'WAIT', 'HELD'
    if status == 'running':
        return 'WAIT', 'TASK_ACTIVE'
    if task['dependency_state'] != 'satisfied':
        return 'WAIT', 'DEPENDENCIES_PENDING'
    # Delegate plan order, dependency completion and plan-level blocking to the
    # Runner's pure selector. Do not call its permission/config/repo/start APIs.
    from . import workflow_runner
    candidate = workflow_runner._eligible_task({'tasks': [
        dict(task_id=t['task_id'], status=t['status'],
             depends_on=[d['task_id'] for d in t['dependencies']]) for t in tasks]})
    if candidate is None or candidate['task_id'] != task['task_id']:
        return 'WAIT', 'QUEUED'
    return 'PROPOSE_START', 'APPROVED_READY'


def suggest_decisions(snapshot, *, observation_id):
    """Conservative deterministic baseline; start means candidate, never permission."""
    context = build_manager_input(snapshot, observation_id=observation_id)
    decisions = []
    for plan in context['plans']:
        for task in plan['tasks']:
            kind, reason = _suggest(task, plan['tasks'])
            decisions.append(dict(kind=kind, reason_code=reason, plan_id=task['plan_id'],
                task_id=task['task_id'], snapshot_id=context['snapshot_id'], change=None))
    return decisions


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'INVALID_JSON')
        result[key] = value
    return result


def validate_ai_response(response_json, snapshot, *, observation_id, workflow_plans=None, registered_keys=()):
    """Validate one fake/provider JSON response against the CURRENT observation.

    JSON has exactly kind, reason_code, plan_id, task_id, snapshot_id, change.
    change is null except for a one-operation WF proposal. No free-text reason.
    Returns {accepted, code, decision}; rejection never echoes supplied data.
    workflow_plans is required only for changes. preview_proposal validates the
    original proposal with actor=manager against an explicitly supplied registry.
    All mutable returned values are newly allocated by JSON parsing/projection.
    """
    try:
        context = build_manager_input(snapshot, observation_id=observation_id)
        _require(isinstance(response_json, str) and len(response_json) <= 16000, 'INVALID_JSON')
        try:
            value = json.loads(response_json, object_pairs_hook=_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(DecisionError('INVALID_JSON')))
        except (ValueError, RecursionError):
            raise DecisionError('INVALID_JSON') from None
        _require(isinstance(value, dict) and set(value) == {
            'kind', 'reason_code', 'plan_id', 'task_id', 'snapshot_id', 'change'}, 'INVALID_SCHEMA')
        _require(isinstance(value['kind'], str) and value['kind'] in KINDS, 'INVALID_KIND')
        _require(isinstance(value['reason_code'], str) and value['reason_code'] in REASONS, 'INVALID_REASON')
        _require(value['snapshot_id'] == context['snapshot_id'], 'STALE_SNAPSHOT')
        matches = [(p, t) for p in context['plans'] for t in p['tasks']
                   if t['plan_id'] == value['plan_id'] and t['task_id'] == value['task_id']]
        _require(len(matches) == 1, 'UNKNOWN_TARGET')
        plan, task = matches[0]
        if value['kind'] != 'PROPOSE_TASK_CHANGE':
            _require(value['change'] is None, 'INVALID_SCHEMA')
            _require((value['kind'], value['reason_code']) == _suggest(task, plan['tasks']), 'STATE_CONFLICT')
        else:
            _require(value['reason_code'] == 'WORKFLOW_CHANGE' and task['availability'] == 'available', 'STATE_CONFLICT')
            proposal = value['change']
            _require(isinstance(proposal, dict) and set(proposal) == {'plan_id', 'base_revision', 'ops'}, 'INVALID_SCHEMA')
            _require(proposal['plan_id'] == value['plan_id'] and isinstance(proposal['ops'], list) and len(proposal['ops']) == 1, 'INVALID_SCHEMA')
            op = proposal['ops'][0]
            _require(isinstance(op, dict) and set(op) == {'op', 'task_id'} and op['task_id'] == value['task_id'], 'INVALID_SCHEMA')
            _require(isinstance(op['op'], str) and op['op'] in SUPPORTED_CHANGES, 'UNSUPPORTED_CHANGE')
            _require(isinstance(workflow_plans, list), 'WORKFLOW_CONTEXT_REQUIRED')
            sources = [p for p in workflow_plans if isinstance(p, dict) and p.get('plan_id') == value['plan_id']]
            _require(len(sources) == 1, 'WORKFLOW_CONTEXT_REQUIRED')
            source = sources[0]
            # Reuse WF validation, then ensure the full plan agrees with observed TASK metadata.
            wf.validate_plan(source, registered_keys=registered_keys)
            source_tasks = source['tasks']
            _require(len(source_tasks) == len(plan['tasks']), 'STATE_CONFLICT')
            for original, observed in zip(source_tasks, plan['tasks']):
                _require(all(original.get(k) == observed[k] for k in
                             ('task_id', 'repo_key', 'status', 'main_ai', 'reviewer_ai')) and
                         original['depends_on'] == [d['task_id'] for d in observed['dependencies']], 'STATE_CONFLICT')
            wf.preview_proposal(source, proposal, actor='manager', registered_keys=registered_keys)
        return dict(accepted=True, code='ACCEPTED', decision=value)
    except DecisionError as exc:
        return dict(accepted=False, code=str(exc), decision=None)
    except (wf.WorkflowError, TypeError, KeyError, RecursionError):
        return dict(accepted=False, code='INVALID_WORKFLOW', decision=None)
