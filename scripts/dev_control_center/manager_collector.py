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
conditions itself. Revalidation consumes the latest issued observation once,
checks its age and full-state fingerprint against a fresh collection, then uses
the ORIGINAL generation for JSON validation. IDs are never silently rebound.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
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


# DCC Task UI-D2 (C1-C3): closed vocabulary for the optional, injected quota classifier's return
# value -- never trust its shape beyond this allowlist.
_QUOTA_BUCKETS = frozenset(('quota_waiting', 'manual_temporary', 'manual_permanent'))


def _quota_fields(raw, quota_display_fn):
    """Project an injected quota classifier's output into exactly two closed-vocabulary fields
    (quota_bucket, quota_label) -- never forwards the classifier's own record, message or
    exception text. `raw` is the collector's own self._inspect(rid) result; only its 'record'
    sub-dict (when present) is ever handed to quota_display_fn, and only a well-shaped
    {bucket, manager_label} return value is ever trusted."""
    if quota_display_fn is None or not isinstance(raw, dict):
        return None, ''
    record = raw.get('record')
    if not isinstance(record, dict):
        return None, ''
    try:
        quota = quota_display_fn(record)
    except Exception:  # noqa: BLE001 - a broken classifier must not break collection
        return None, ''
    if not (isinstance(quota, dict) and quota.get('bucket') in _QUOTA_BUCKETS
            and isinstance(quota.get('manager_label'), str)):
        return None, ''
    return quota['bucket'], quota['manager_label']


class ManagerCollector:
    def __init__(self, *, registered_keys=None, plans_root=None, records_root=None,
                 runs_root=None, runner_state=None, list_plans=None, load_plan=None,
                 read_association=None, inspect_run=None, next_observation=None,
                 list_active_runs=None, report_run_ids=None, quota_display_fn=None,
                 now=None, max_age_seconds=300):
        if (type(max_age_seconds) not in (int, float) or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0):
            raise ValueError("INVALID_MAX_AGE")
        self._now = now or time.monotonic
        self._max_age = max_age_seconds
        self._pending = None
        self._keys = registered_keys
        self._runner_state = runner_state
        # Defaults are lazy: injected tests never resolve or read production roots.
        self._list = list_plans or (lambda: list_saved_plans(
            wf.plans_root() if plans_root is None else plans_root))
        self._load = load_plan or (lambda pid: wf.load_plan(pid, root=plans_root, registered_keys=self._keys))
        self._read_association = read_association or self._disk_reader(records_root)
        self._inspect = inspect_run or self._run_reader(runs_root)
        self._next = next_observation or _CLOCK
        # DCC Task UI-D1: independent of collect()'s generation/fingerprint/revalidate machinery
        # -- display data only, never execution permission (see collect_running_tasks).
        self._list_active_runs = list_active_runs or self._active_runs_reader(runs_root)
        self._report_run_ids = report_run_ids or self._default_report_run_ids
        # DCC Task UI-D2: optional closed-vocabulary quota classifier (orchestrator_requeue.
        # quota_display bound to the caller's own RequeueState). None (every pre-existing
        # caller/test) leaves every observation's quota_bucket/quota_label at their inert
        # defaults (None/''), unchanged from before this task.
        self._quota_display_fn = quota_display_fn
        self._last_generation = -1
        self._previous = None  # safe comparison metadata only, never fallback data
        self._lock = threading.Lock()

    def _observe_raw(self, rid):
        """DCC Task UI-D2: one self._inspect(rid) call, projected into the existing safe
        observation shape (_safe_observation) plus the two closed-vocabulary quota fields
        (_quota_fields) -- both derived from the exact same raw read, so every caller comparing
        two observations for change-detection (_collect's own bounded double-read) sees a
        consistent shape on both sides. Returns (safe, raw); raw is never exposed beyond this
        method's own quota projection."""
        raw = self._inspect(rid)
        safe = _safe_observation(rid, raw)
        bucket, label = (None, '')
        if safe['record'] is not None:
            bucket, label = _quota_fields(raw, self._quota_display_fn)
        return dict(safe, quota_bucket=bucket, quota_label=label), raw

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

    def _active_runs_reader(self, root):
        """DCC Task UI-D1: every run DCC currently knows about, regardless of plan association --
        the only way a direct-request or report-started run (never in a workflow plan) is visible
        at all. Walks every directory under root (an injected test can point this at a temp
        directory); unlike tools.ai_orchestrator.runstate.list_runs's own bounded listing, this
        must not stop early -- a long-running task that is still active must not disappear just
        because enough newer runs have since finished. Liveness comes from self._inspect (shared
        with _collect's own observations, and injectable in tests) via the same _safe_observation
        projection, so a stage that still looks active but whose worker is lost/unresponsive/
        unknown is marked accordingly rather than passed through as a bare stage string.
        Read-only: inspect_run never writes; a listing failure yields an empty list."""
        def list_active():
            from tools.ai_orchestrator import runstate
            base = runstate.runs_root() if root is None else Path(root)
            try:
                directories = sorted((d for d in base.iterdir() if d.is_dir()),
                                     key=lambda d: d.name, reverse=True)
            except OSError:
                return []
            items = []
            for directory in directories:
                rid = directory.name
                try:
                    safe, raw = self._observe_raw(rid)
                except Exception:
                    continue
                if safe['record'] is None:
                    continue
                record = raw['record']
                items.append(dict(run_id=rid, stage=safe['record']['stage'], liveness=safe['liveness'],
                                  repo=record.get('repo'), main_agent=record.get('main_agent'),
                                  review_agent=record.get('review_agent'),
                                  quota_bucket=safe.get('quota_bucket'), quota_label=safe.get('quota_label')))
            return items
        return list_active

    @staticmethod
    def _default_report_run_ids():
        from . import reports_auto_start
        try:
            return reports_auto_start.started_run_ids()
        except Exception:
            return set()

    def _association(self, pid, tid):
        if self._runner_state is not None:
            hot = self._runner_state.hot_run(pid, tid)
            if hot is not None:
                return hot  # never fall back to an older disk association, even if corrupt
        return self._read_association(pid, tid)

    def _plan_linked_run_ids(self) -> set:
        """DCC Task UI-D1 (C1): every run_id linked to ANY task of ANY saved plan, regardless of
        that task's current status -- a run the workflow runner once started from a plan task is
        計画-sourced for display purposes even if the task's status later changed. Independent of
        collect(): no generation, no issue tracking, no revalidate interaction. A malformed plan,
        task or association is simply skipped (fails closed to 依頼 at the classifier), never
        raised."""
        run_ids: set = set()
        try:
            entries = self._list()
        except Exception:
            return run_ids
        if not isinstance(entries, list):
            return run_ids
        for pid in entries:
            if not _identifier(pid, 32):
                continue
            try:
                loaded = self._load(pid)
            except Exception:
                continue
            if not isinstance(loaded, dict) or not isinstance(loaded.get('tasks'), list):
                continue
            for task in loaded['tasks']:
                if not isinstance(task, dict):
                    continue
                tid = task.get('task_id')
                if not _identifier(tid, 16):
                    continue
                try:
                    raw = self._association(pid, tid)
                except Exception:
                    continue
                if isinstance(raw, dict) and _run_id(raw.get('run_id')):
                    run_ids.add(raw['run_id'])
        return run_ids

    def collect_running_tasks(self) -> list:
        """DCC Task UI-D1 (C2/C3/C4): best-effort, read-only list of every currently 動いている
        task (any origin), each tagged with its fixed-word 出どころ (overview.task_origin).
        Independent of collect()/revalidate() -- display data only, never execution permission or
        AI-decision validation; never raises, never mutates any state."""
        try:
            plan_run_ids = self._plan_linked_run_ids()
        except Exception:
            plan_run_ids = set()
        try:
            report_run_ids = self._report_run_ids()
            if not isinstance(report_run_ids, (set, frozenset, list, tuple)):
                report_run_ids = set()
        except Exception:
            report_run_ids = set()
        try:
            all_runs = self._list_active_runs()
            if not isinstance(all_runs, list):
                all_runs = []
        except Exception:
            all_runs = []
        return overview.running_tasks(all_runs, plan_run_ids=plan_run_ids, report_run_ids=report_run_ids)

    def collect(self):
        """New generation + fresh safe payload; no cached-success fallback."""
        with self._lock:
            self._pending = None  # every ordinary collection revokes the prior issue
            try:
                issued_at = self._read_time()
            except Exception:
                issued_at = None
            payload, _, _, fingerprint = self._collect()
            if issued_at is None:
                payload['status'] = 'unavailable'
                payload['manager_input'] = None
                payload['issues'].append(dict(code='CLOCK_UNAVAILABLE', plan_id=None, task_id=None))
            elif payload['status'] == 'available':
                self._pending = dict(snapshot=copy.deepcopy(payload['snapshot']),
                    observation_id=payload['observation_id'], fingerprint=fingerprint,
                    issued_at=issued_at)
            return payload

    def _read_time(self):
        value = self._now()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('CLOCK_UNAVAILABLE')
        return value

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
        association_digests = {}
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
                        association_digests[(pid, tid)] = _digest(raw)
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
                            observations[rid], _ = self._observe_raw(rid)
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
                        if (now != associations.get((pid, tid)) or
                            _digest(raw) != association_digests.get((pid, tid))):
                            associations[(pid, tid)] = None
                            issue('ASSOCIATION_CHANGED', pid, tid)
                    except Exception:
                        associations[(pid, tid)] = None
                        issue('ASSOCIATION_UNAVAILABLE', pid, tid)
            for rid, before in list(observations.items()):
                try:
                    after, _ = self._observe_raw(rid)
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
        # Private only: full Workflow content (including body/history), membership,
        # registry, association metadata and fixed Run observations. Never log/export.
        fingerprint = _digest(dict(plans=full, keys=sorted(keys), snapshot=snapshot,
            associations=[(pid, tid, digest) for (pid, tid), digest in sorted(association_digests.items())],
            runs=run_states))
        return payload, full, keys, fingerprint

    def revalidate(self, response_json):
        """Consume one issued observation and recollect, even for an invalid attempt.

        A successful comparison authorizes validation against the original ID only;
        it grants no execution permission. Any attempt consumes the issue, including
        rejected/malformed responses. New collect(), restart or expiry revokes it.
        """
        with self._lock:
            issued, self._pending = self._pending, None
            payload, plans, keys, fingerprint = self._collect()
            code = None
            if payload['status'] != 'available':
                code = 'COLLECTION_UNAVAILABLE'
            elif issued is None:
                code = 'OBSERVATION_UNKNOWN'
            else:
                try:
                    age = self._read_time() - issued['issued_at']
                    if age < 0 or age >= self._max_age:
                        code = 'OBSERVATION_EXPIRED'
                except Exception:
                    code = 'CLOCK_UNAVAILABLE'
                if code is None and fingerprint != issued['fingerprint']:
                    code = 'STATE_CHANGED'
            if code is not None:
                result = dict(accepted=False, code=code, decision=None)
            else:
                result = decision.validate_ai_response(response_json, issued['snapshot'],
                    observation_id=issued['observation_id'], workflow_plans=plans,
                    registered_keys=keys)
            return dict(collection=payload, validation=result)
