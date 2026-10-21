"""Read-only MGR collection and fresh decision validation. No UI/AI/execution.

collect() returns ONLY safe data. Its status covers ALL collection sources;
snapshot.availability covers plan projection only. manager_input is withheld on
any partial/unavailable collection. Full validated Workflow documents remain local
inside _collect for the duration of revalidate(), never in display/Manager input.
Injected readers have signatures list_plans() -> [plan_id | None], load_plan(id),
read_association(plan_id, task_id), inspect_run(run_id), next_observation() -> int.
None in a listing means a damaged/unreadable entry, not a successful empty scan.

One bounded double-read detects changes; it is not an atomic cross-file database
transaction. A subsequent execution connection must recheck authoritative Runner
conditions itself. Revalidation always issues a new generation: even unchanged
old responses are stale and must be regenerated; IDs are never silently rebound.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import uuid

from . import manager_decision as decision
from . import manager_overview as overview
from . import workflow_plan as wf


class ObservationClock:
    """Process-session random 128-bit namespace + monotonic counter; no disk writes.

    Namespace collision across restarts is probabilistically negligible (UUID4).
    A global instance also prevents reuse across collectors in this process.
    """
    def __init__(self):
        self._namespace = uuid.uuid4().int
        self._counter = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self._counter += 1
            if self._counter >= 2 ** 64:
                raise ValueError('GENERATION_EXHAUSTED')
            return (self._namespace << 64) | self._counter


_CLOCK = ObservationClock()


def _identifier(value, limit):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) is not None


def _run_id(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', value) is not None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def list_saved_plans(root):
    """Discovery only, modeled on WF view listing, retaining failed entries.

    Hashed filenames are verified against WF's existing path contract. No raw
    filename, label, JSON content or exception is returned. Missing root is a
    collection failure, never silently interpreted as an empty plan collection.
    """
    root = Path(root)
    result = []
    for entry in sorted(root.iterdir()):
        if entry.suffix != '.json':
            continue
        try:
            if not entry.is_file() or entry.is_symlink():
                raise ValueError('INVALID_ENTRY')
            value = json.loads(entry.read_text(encoding='utf-8'))
            pid = value.get('plan_id') if isinstance(value, dict) else None
            if not _identifier(pid, 32) or entry.name != wf._plan_path(pid, root).name:
                raise ValueError('INVALID_ENTRY')
            result.append(pid)
        except (OSError, UnicodeError, ValueError, RecursionError):
            result.append(None)
    # Sort IDs, not potentially free-text filenames. None entries preserve failures.
    return sorted(result, key=lambda value: (value is None, value or ''))


def _safe_observation(rid, raw):
    """Project inspect_run output without reason, worker, path or free text."""
    unknown = dict(record=None, liveness='unknown')
    if not isinstance(raw, dict) or not isinstance(raw.get('record'), dict):
        return unknown
    record = raw['record']
    stage, live = record.get('stage'), raw.get('liveness')
    if (record.get('run_id') != rid or not isinstance(stage, str)
        or stage not in overview.ACTIVE_STAGES | overview.TERMINAL_STAGES
        or not isinstance(live, str) or live not in overview.LIVENESS):
        return unknown
    if ((stage in overview.TERMINAL_STAGES and live != 'finished') or
        (stage in overview.ACTIVE_STAGES and live == 'finished')):
        return unknown
    return dict(record=dict(run_id=rid, stage=stage), liveness=live)


class ManagerCollector:
    def __init__(self, *, registered_keys=None, plans_root=None, records_root=None,
                 runs_root=None, runner_state=None, list_plans=None, load_plan=None,
                 read_association=None, inspect_run=None, next_observation=None):
        self._keys = registered_keys
        self._runner_state = runner_state
        # Defaults are lazy: injected tests never resolve or read production roots.
        self._list = list_plans or (lambda: list_saved_plans(
            wf.plans_root() if plans_root is None else plans_root))
        self._load = load_plan or (lambda pid: wf.load_plan(pid, root=plans_root, registered_keys=self._keys))
        self._read_association = read_association or self._disk_reader(records_root)
        self._inspect = inspect_run or self._run_reader(runs_root)
        self._next = next_observation or _CLOCK
        self._last_generation = -1
        self._previous = None  # safe comparison metadata only, never fallback data
        self._lock = threading.Lock()

    @staticmethod
    def _disk_reader(root):
        def read(pid, tid):
            from . import workflow_runner as runner
            value = runner._load_record(pid, tid, root=root)
            if value is None and runner._record_path(pid, tid, root=root).exists():
                raise ValueError('ASSOCIATION_UNREADABLE')
            return value
        return read

    @staticmethod
    def _run_reader(root):
        def inspect(rid):
            from tools.ai_orchestrator import runstate
            base = runstate.runs_root() if root is None else Path(root)
            return runstate.inspect_run(base / rid)
        return inspect

    def _association(self, pid, tid):
        if self._runner_state is not None:
            hot = self._runner_state.hot_run(pid, tid)
            if hot is not None:
                return hot  # never fall back to an older disk association, even if corrupt
        return self._read_association(pid, tid)

    def collect(self):
        """New generation + fresh safe payload; no cached-success fallback."""
        with self._lock:
            return self._collect()[0]

    def _collect(self):
        issues = []
        def issue(code, pid=None, tid=None):
            item = dict(code=code, plan_id=pid, task_id=tid)
            if item not in issues:
                issues.append(item)
        generation = None
        try:
            generation = self._next()
            if type(generation) is not int or generation <= self._last_generation:
                raise ValueError('INVALID_GENERATION')
            self._last_generation = generation
        except Exception:
            generation = None
            issue('GENERATION_UNAVAILABLE')
        keys = self._keys
        try:
            keys = frozenset(wf.registered_repo_keys() if keys is None else keys)
            if not all(_identifier(k, 80) for k in keys):
                raise ValueError('INVALID_REGISTRY')
        except Exception:
            keys = frozenset()
            issue('REGISTRY_UNAVAILABLE')

        def listing():
            values = self._list()
            if not isinstance(values, list) or any(v is not None and not _identifier(v, 32) for v in values):
                raise ValueError('INVALID_LIST')
            return sorted(values, key=lambda value: (value is None, value or ''))

        plans, full, associations, observations = [], [], {}, {}
        revisions = []
        run_owners = {}
        entries = None
        try:
            entries = listing()
        except Exception:
            issue('LIST_UNAVAILABLE')
        if entries is not None:
            for pid in entries:
                if pid is None or entries.count(pid) != 1:
                    plans.append(None if pid is None else dict(plan_id=pid))
                    issue('PLAN_UNAVAILABLE', pid)
                    continue
                try:
                    original = copy.deepcopy(self._load(pid))
                    wf.validate_plan(original, registered_keys=keys)
                    if original['plan_id'] != pid:
                        raise ValueError('PLAN_MISMATCH')
                except Exception:
                    plans.append(dict(plan_id=pid))
                    issue('PLAN_UNAVAILABLE', pid)
                    continue
                plans.append(original)
                full.append(original)
                revisions.append(dict(plan_id=pid, revision=original['revision']))
                for task in original['tasks']:
                    tid = task['task_id']
                    try:
                        raw = self._association(pid, tid)
                        # Empty run_id is Runner's legitimate pre-start failure record.
                        if raw is None or isinstance(raw, dict) and raw.get('run_id') == '':
                            if task['status'] in ('running', 'candidate_ready'):
                                issue('ASSOCIATION_UNAVAILABLE', pid, tid)
                            associations[(pid, tid)] = None
                            continue
                        if not isinstance(raw, dict) or not _run_id(raw.get('run_id')):
                            raise ValueError('INVALID_ASSOCIATION')
                        rid = raw['run_id']
                        if rid in run_owners and run_owners[rid] != (pid, tid):
                            issue('ASSOCIATION_CONFLICT', pid, tid)
                        run_owners[rid] = (pid, tid)
                        associations[(pid, tid)] = dict(run_id=rid)
                        if rid not in observations:
                            observations[rid] = _safe_observation(rid, self._inspect(rid))
                        safe = observations[rid]
                        if safe['record'] is None or safe['liveness'] in ('unknown', 'lost', 'unresponsive'):
                            issue('RUN_UNAVAILABLE', pid, tid)
                        elif (task['status'] == 'running' and safe['record']['stage'] not in overview.ACTIVE_STAGES or
                              task['status'] in ('candidate_ready', 'landed') and safe['record']['stage'] != 'completed' or
                              task['status'] == 'failed' and safe['record']['stage'] not in ('failed', 'stopped') or
                              task['status'] == 'needs_human' and safe['record']['stage'] != 'needs_human' or
                              task['status'] not in ('running',) and safe['record']['stage'] in overview.ACTIVE_STAGES):
                            issue('RUN_TASK_CONFLICT', pid, tid)
                    except Exception:
                        associations[(pid, tid)] = None
                        issue('ASSOCIATION_OR_RUN_UNAVAILABLE', pid, tid)
            # Bounded verification: changed plans are discarded, never published as stable.
            for index, original in enumerate(plans):
                if not isinstance(original, dict) or 'tasks' not in original:
                    continue
                pid = original['plan_id']
                try:
                    after = copy.deepcopy(self._load(pid))
                    wf.validate_plan(after, registered_keys=keys)
                    if after != original:
                        raise ValueError('CHANGED')
                except Exception:
                    plans[index] = dict(plan_id=pid)
                    full = [p for p in full if p['plan_id'] != pid]
                    revisions = [r for r in revisions if r['plan_id'] != pid]
                    issue('PLAN_CHANGED', pid)
                for task in original['tasks']:
                    tid = task['task_id']
                    try:
                        raw = self._association(pid, tid)
                        if raw is not None and not (isinstance(raw, dict) and (raw.get('run_id') == '' or _run_id(raw.get('run_id')))):
                            raise ValueError('INVALID_ASSOCIATION')
                        now = dict(run_id=raw['run_id']) if isinstance(raw, dict) and _run_id(raw.get('run_id')) else None
                        if now != associations.get((pid, tid)):
                            associations[(pid, tid)] = None
                            issue('ASSOCIATION_CHANGED', pid, tid)
                    except Exception:
                        associations[(pid, tid)] = None
                        issue('ASSOCIATION_UNAVAILABLE', pid, tid)
            for rid, before in list(observations.items()):
                try:
                    after = _safe_observation(rid, self._inspect(rid))
                    if after != before:
                        observations[rid] = dict(record=None, liveness='unknown')
                        issue('RUN_CHANGED')
                except Exception:
                    observations[rid] = dict(record=None, liveness='unknown')
                    issue('RUN_UNAVAILABLE')
            try:
                if listing() != entries:
                    raise ValueError('LIST_CHANGED')
            except Exception:
                # Entire membership may be stale; no old plans survive a list race.
                plans, full, revisions = [None], [], []
                issue('LIST_CHANGED')

        snapshot = overview.build_snapshot(plans if entries is not None else None,
            registered_keys=keys, associations=associations, observations=observations)
        context = None
        if generation is not None:
            try:
                context = decision.build_manager_input(snapshot, observation_id=generation)
            except decision.DecisionError:
                issue('SNAPSHOT_UNAVAILABLE')
        run_states = [dict(run_id=rid, stage=value['record']['stage'] if value['record'] else 'unknown',
                           liveness=value['liveness']) for rid, value in sorted(observations.items())]
        task_states = [dict(plan_id=p['plan_id'], tasks=[dict(task_id=t['task_id'], status=t['status'],
                       dependencies=t['dependencies']) for t in p['tasks']]) for p in snapshot['plans']]
        metadata = dict(revision_id=_digest(revisions), task_state_id=_digest(task_states), run_state_id=_digest(run_states))
        status = 'available' if not issues else ('partial' if full else 'unavailable')
        changes = []
        if self._previous is None:
            changes.append('INITIAL')
        else:
            for field, code in (('revision_id', 'REVISION_CHANGED'), ('task_state_id', 'TASK_STATE_CHANGED'), ('run_state_id', 'RUN_STATE_CHANGED')):
                if self._previous[field] != metadata[field]:
                    changes.append(code)
        if issues:
            changes.append('COLLECTION_FAILED')
        self._previous = metadata
        payload = dict(status=status, observation_id=generation,
                       snapshot_id=context['snapshot_id'] if context else None,
                       snapshot=snapshot, manager_input=context if status == 'available' else None,
                       revisions=revisions, runs=run_states,
                       issues=issues, changes=changes, **metadata)
        return payload, full, keys

    def revalidate(self, response_json):
        """Recollect immediately, fail closed, never rebase a saved decision's ID.

        Consequently an earlier collected decision is STALE_SNAPSHOT even when
        unchanged. This gate only reports acceptance; no workflow writes/execution.
        """
        with self._lock:
            payload, plans, keys = self._collect()
            if payload['status'] != 'available':
                result = dict(accepted=False, code='COLLECTION_UNAVAILABLE', decision=None)
            else:
                result = decision.validate_ai_response(response_json, payload['snapshot'],
                    observation_id=payload['observation_id'], workflow_plans=plans,
                    registered_keys=keys)
            return dict(collection=payload, validation=result)
