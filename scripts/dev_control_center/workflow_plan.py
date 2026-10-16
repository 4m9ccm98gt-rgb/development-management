"""Workflow planning only: no UI, commands, repository resolution or execution.

JSON objects are copied at the API boundary. apply_proposal returns (new_plan,
summary), never mutates its inputs. actor and registered_keys are trusted caller
context, never fields taken from a proposal. Omitted AI choices remain omitted
so the future execution caller can use its current DCC settings.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class WorkflowError(ValueError):
    """Fixed, content-free validation failure."""


class WorkflowStorageError(WorkflowError):
    """Missing, unreadable, invalid or unwritable plan file."""


STATUSES = frozenset(('proposed', 'approved', 'held', 'running', 'candidate_ready',
                      'landed', 'failed', 'needs_human', 'cancelled'))
LOCKED = frozenset(('running', 'candidate_ready', 'landed', 'cancelled'))
OPS = {
    'add_task': {'task'}, 'insert_after': {'task', 'after'},
    'move': {'task_id', 'after'}, 'hold': {'task_id'},
    'release': {'task_id'}, 'approve': {'task_id'}, 'cancel': {'task_id'},
    'update_body': {'task_id', 'body'}, 'set_depends_on': {'task_id', 'depends_on'},
}
TRANSITIONS = {
    'hold': ({'proposed', 'approved'}, 'held'),
    'release': ({'held'}, 'proposed'),
    'approve': ({'proposed', 'held', 'failed', 'needs_human'}, 'approved'),
    'cancel': ({'proposed', 'approved', 'held', 'failed', 'needs_human'}, 'cancelled'),
}


def _require(condition, code='WORKFLOW_INVALID'):
    if not condition:
        raise WorkflowError(code)


def _identifier(value, limit):
    _require(isinstance(value, str) and
             re.fullmatch(r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) is not None)


def _label(value):
    # Explicit display-label alphabet: Unicode letters/numbers, spaces and these
    # punctuation marks. Paths, shell syntax and all control characters fail.
    _require(isinstance(value, str) and 0 < len(value) <= 80 and bool(value.strip()))
    _require(all(c.isalnum() or c in ' -_()（）「」、。・' for c in value))


def registered_repo_keys():
    from .core import active_repo_definitions
    scripts = Path(__file__).resolve().parents[1]
    return frozenset(d.name for d in active_repo_definitions(
        scripts / 'repo_types.toml', scripts / 'dev_control_center_repos.toml'))


def _body(value, repo_key):
    from tools.ai_orchestrator import review, taskspec
    _require(isinstance(value, str) and 0 < len(value) <= 20000)
    _require(taskspec.extract_target_repo_name(value) == repo_key)
    lines = value.splitlines()
    markers = [i for i, line in enumerate(lines)
               if re.search(r'受入条件|受け入れ条件|acceptance', line, re.I)]
    _require(len(markers) == 1)
    start = markers[0]
    _require(lines[start].startswith('## '))
    criteria = []
    for line in lines[start + 1:]:
        if line.startswith('## '):
            break
        if not line.strip():
            continue
        _require(line.startswith('- ') and bool(line[2:].strip()))
        criteria.append({'text': line[2:]})
    try:
        spec = taskspec.parse_spec_text(json.dumps({'criteria': criteria, 'target_repo': repo_key}))
    except taskspec.SpecError:
        raise WorkflowError('WORKFLOW_INVALID_BODY') from None
    # The existing extractor has a 40-line window. Never accept a document
    # whose visible criteria would silently disappear or change at execution.
    _require(list(spec.criteria) == review.criteria_from_acceptance(review.extract_acceptance(value)),
             'WORKFLOW_INVALID_BODY')


def _task(task, keys):
    required = {'task_id', 'title', 'repo_key', 'body', 'depends_on', 'status'}
    _require(isinstance(task, dict) and required <= task.keys() and
             task.keys() <= required | {'tests', 'main_ai', 'reviewer_ai'})
    _identifier(task['task_id'], 16)
    _label(task['title'])
    _identifier(task['repo_key'], 80)
    _require(task['repo_key'] in keys)
    _require(isinstance(task['status'], str) and task['status'] in STATUSES)
    for field in ('main_ai', 'reviewer_ai'):
        if field in task:
            _require(isinstance(task[field], str) and task[field] in ('claude', 'codex'))
    if 'tests' in task:
        # Inert single-line metadata only; never a command passed to a runner.
        value = task['tests']
        _require(isinstance(value, str) and len(value) <= 1000 and
                 all(c.isalnum() or c in ' -_./' for c in value))
    deps = task['depends_on']
    _require(isinstance(deps, list) and len(deps) <= 50)
    for dep in deps:
        _identifier(dep, 16)
    _require(len(set(deps)) == len(deps))
    _body(task['body'], task['repo_key'])


def validate_plan(plan, *, registered_keys=None):
    """Validate persisted state (including future executor-owned statuses)."""
    keys = registered_repo_keys() if registered_keys is None else frozenset(registered_keys)
    required = {'plan_id', 'name', 'revision', 'tasks'}
    _require(isinstance(plan, dict) and required <= plan.keys() and
             plan.keys() <= required | {'history'})
    _identifier(plan['plan_id'], 32)
    _label(plan['name'])
    _require(type(plan['revision']) is int and plan['revision'] >= 0)
    _require(isinstance(plan['tasks'], list) and len(plan['tasks']) <= 50)
    for task in plan['tasks']:
        _task(task, keys)
    by_id = {t['task_id']: t for t in plan['tasks']}
    _require(len(by_id) == len(plan['tasks']))
    visiting, visited = set(), set()

    def visit(tid):
        _require(tid in by_id and tid not in visiting)
        if tid in visited:
            return
        visiting.add(tid)
        for dep in by_id[tid]['depends_on']:
            visit(dep)
        visiting.remove(tid)
        visited.add(tid)

    for tid in by_id:
        visit(tid)
    history = plan.get('history', [])
    _require(isinstance(history, list) and len(history) <= 200)
    previous = 0
    for entry in history:
        _require(isinstance(entry, dict) and set(entry) == {'revision', 'ops'})
        rev = entry['revision']
        _require(type(rev) is int and previous < rev <= plan['revision'])
        previous = rev
        _require(isinstance(entry['ops'], list) and len(entry['ops']) <= 200)
        for op in entry['ops']:
            _require(isinstance(op, dict) and set(op) == {'op', 'task_id'})
            _require(isinstance(op['op'], str) and op['op'] in OPS)
            _identifier(op['task_id'], 16)


def diff_summary(before, after):
    """Net changes; reordered counts existing IDs whose relative order changed.

    Cancellation is a status change, not deletion. Physical deletion has no op,
    but this comparison can describe removed IDs for a future caller.
    """
    old = {t['task_id']: t for t in before['tasks']}
    new = {t['task_id']: t for t in after['tasks']}
    common_old = [tid for tid in old if tid in new]
    common_new = [tid for tid in new if tid in old]
    groups = {
        'added': [tid for tid in new if tid not in old],
        'changed': [tid for tid in new if tid in old and new[tid] != old[tid]],
        'deleted': [tid for tid in old if tid not in new],
        'reordered': [tid for i, tid in enumerate(common_new) if common_old[i] != tid],
    }
    return {word: {'count': len(ids), 'task_ids': ids} for word, ids in groups.items()}


def apply_proposal(plan, proposal, *, actor, registered_keys=None):
    """All-or-nothing pure operation. No proposal metadata grants authority."""
    _require(isinstance(actor, str) and actor in ('human', 'manager'))
    keys = registered_repo_keys() if registered_keys is None else frozenset(registered_keys)
    validate_plan(plan, registered_keys=keys)
    _require(isinstance(proposal, dict) and
             set(proposal) == {'plan_id', 'base_revision', 'ops'})
    _require(proposal['plan_id'] == plan['plan_id'])
    _require(type(proposal['base_revision']) is int and
             proposal['base_revision'] == plan['revision'], 'WORKFLOW_STALE')
    _require(isinstance(proposal['ops'], list) and 1 <= len(proposal['ops']) <= 200)
    result = copy.deepcopy(plan)
    tasks = result['tasks']
    records = []

    def find(tid):
        _identifier(tid, 16)
        found = next((t for t in tasks if t['task_id'] == tid), None)
        _require(found is not None)
        return found

    for raw in proposal['ops']:
        _require(isinstance(raw, dict))
        op = raw.get('op')
        _require(isinstance(op, str) and op in OPS)
        _require(set(raw) == OPS[op] | {'op'})
        if op in ('add_task', 'insert_after'):
            task = copy.deepcopy(raw['task'])
            _require(isinstance(task, dict))
            task.setdefault('status', 'proposed')
            task.setdefault('depends_on', [])
            _task(task, keys)
            _require(task['status'] == 'proposed')
            _require(not any(t['task_id'] == task['task_id'] for t in tasks))
            index = len(tasks) if op == 'add_task' else tasks.index(find(raw['after'])) + 1
            tasks.insert(index, task)
        else:
            task = find(raw['task_id'])
            _require(task['status'] not in LOCKED, 'WORKFLOW_LOCKED')
            if op == 'move':
                anchor = find(raw['after'])
                _require(anchor is not task)
                tasks.remove(task)
                tasks.insert(tasks.index(anchor) + 1, task)
            elif op in TRANSITIONS:
                sources, target = TRANSITIONS[op]
                _require(task['status'] in sources)
                _require(op != 'approve' or actor == 'human', 'WORKFLOW_HUMAN_REQUIRED')
                task['status'] = target
            elif op == 'update_body':
                task['body'] = raw['body']
                # An edited approval must be reviewed again by a human.
                if task['status'] == 'approved':
                    task['status'] = 'proposed'
            else:
                task['depends_on'] = copy.deepcopy(raw['depends_on'])
                if task['status'] == 'approved':
                    task['status'] = 'proposed'
        records.append({'op': op, 'task_id': task['task_id']})
    # No operation may indirectly reorder a protected task across another
    # existing task, even when the moved task itself is editable.
    old_ids = [t['task_id'] for t in plan['tasks']]
    new_ids = [t['task_id'] for t in tasks if t['task_id'] in old_ids]
    for task in plan['tasks']:
        if task['status'] in LOCKED:
            tid = task['task_id']
            _require(set(old_ids[:old_ids.index(tid)]) == set(new_ids[:new_ids.index(tid)]),
                     'WORKFLOW_LOCKED')
    result['revision'] += 1
    result['history'] = (result.get('history', []) + [
        {'revision': result['revision'], 'ops': records}])[-200:]
    validate_plan(result, registered_keys=keys)
    return result, diff_summary(plan, result)


def preview_proposal(plan, proposal, *, actor, registered_keys=None):
    """Same validation as apply, without saving or changing the source plan."""
    return apply_proposal(plan, proposal, actor=actor, registered_keys=registered_keys)[1]


def plans_root():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ShizenDev' / 'DCC' / 'workflow_plans'


def _plan_path(plan_id, root):
    _identifier(plan_id, 32)
    # A fixed hash filename also avoids Windows device names and case aliases.
    return Path(root) / (hashlib.sha256(plan_id.encode('ascii')).hexdigest() + '.json')


def save_plan(plan, *, root=None, registered_keys=None):
    """Trusted persistence API; callers serialize access to each plan.

    Plan and history share one atomic replacement. This API is not an approval
    endpoint: untrusted changes must first pass apply_proposal.
    """
    snapshot = copy.deepcopy(plan)
    validate_plan(snapshot, registered_keys=registered_keys)
    path = _plan_path(snapshot['plan_id'], plans_root() if root is None else root)
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-', suffix='.json')
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except (OSError, UnicodeError):
        raise WorkflowStorageError('WORKFLOW_STORAGE_ERROR') from None
    finally:
        if temp is not None and os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                raise WorkflowStorageError('WORKFLOW_STORAGE_ERROR') from None


def load_plan(plan_id, *, root=None, registered_keys=None):
    path = _plan_path(plan_id, plans_root() if root is None else root)
    try:
        plan = json.loads(path.read_text(encoding='utf-8'))
        validate_plan(plan, registered_keys=registered_keys)
        _require(plan['plan_id'] == plan_id)
        return plan
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise WorkflowStorageError('WORKFLOW_STORAGE_ERROR') from None
