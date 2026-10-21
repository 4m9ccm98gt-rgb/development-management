"""Explicit, one-shot Manager inference; no automatic actions or provider fallback.

infer(allow_ai=True) is the only call site. Inject a fake collector/provider for
unit tests. Provider factories are trusted Python configuration, never AI data.
The default provider inherits CodexProvider.run_review and parse, with a private
empty temporary cwd, ignored user configuration and tools disabled. This is not
an OS container: CLI authentication is still handled by Codex. Unsupported CLI
flags fail closed; no permission relaxation or alternate provider is attempted.

Transport output is limited during line delivery and checked again after return;
the existing line-oriented transport may buffer a large single line before its
callback. No raw response/log is returned or persisted by this adapter.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time

from . import manager_decision as decision
from .manager_collector import ManagerCollector
from tools.ai_orchestrator.common import ProcessHooks, StopRequested, OrchestratorError, run_streaming
from tools.ai_orchestrator.providers import CodexProvider, AgentResult

MAX_RESPONSE_CHARS = 16_000
MAX_STREAM_CHARS = 256_000
MAX_INPUT_CHARS = 200_000
_INFERENCE_LOCK = threading.Lock()
ERRORS = {'quota': 'PROVIDER_QUOTA', 'auth': 'PROVIDER_AUTH', 'timeout': 'PROVIDER_TIMEOUT',
          'process': 'PROVIDER_PROCESS', 'transient': 'PROVIDER_TRANSIENT',
          'protocol': 'PROVIDER_PROTOCOL', 'empty_response': 'PROVIDER_PROTOCOL',
          'token_limit': 'OUTPUT_LIMIT', 'max_turns': 'PROVIDER_LIMIT'}


class _Stop:
    def __init__(self, external, budget):
        self.external, self.budget = external, budget
    def is_set(self):
        return self.budget.is_set() or (self.external is not None and self.external.is_set())


class ManagerCodexProvider(CodexProvider):
    """Reuse review role/JSON parser; restrict this invocation only, never global config."""
    def _command(self, worktree, sandbox, ephemeral=True):
        if sandbox != 'read-only':
            raise ValueError('REVIEW_ONLY')
        command = super()._command(worktree, sandbox, ephemeral=True)
        options = ['--ignore-user-config', '--ignore-rules', '--skip-git-repo-check', '--strict-config']
        for key, value in (
            ('approval_policy', '"never"'), ('web_search', '"disabled"'),
            ('features.shell_tool', 'false'), ('features.unified_exec', 'false'),
            ('features.apply_patch_freeform', 'false'), ('features.js_repl', 'false'),
            ('features.code_mode', 'false'), ('features.multi_agent', 'false'),
            ('features.multi_agent_v2', 'false'), ('agents.enabled', 'false'),
            ('features.apps', 'false'), ('features.plugins', 'false'),
            ('features.memories', 'false'),
            ('features.skill_mcp_dependency_install', 'false'), ('tools.view_image', 'false'),
            ('project_doc_max_bytes', '0'), ('mcp_servers', '{}')):
            options.extend(('-c', key + '=' + value))
        return command[:-1] + options + command[-1:]

    def _call(self, role, command, worktree, prompt, timeout, hooks):
        if role != 'review':
            raise ValueError('REVIEW_ONLY')
        budget = threading.Event()
        count = 0
        lock = threading.Lock()
        def on_line(_stream, line):
            nonlocal count
            with lock:
                count += len(line) + 1
                if count > MAX_STREAM_CHARS:
                    budget.set()
        try:
            output = run_streaming(command, cwd=worktree, input_text=prompt,
                timeout=timeout, env=self.child_env('review'),
                hooks=ProcessHooks(on_line=on_line, stop=_Stop(hooks.stop, budget)))
        except StopRequested:
            if budget.is_set():
                return AgentResult('codex', 'review', False, error_kind='token_limit')
            raise
        except OrchestratorError as exc:
            return AgentResult('codex', 'review', False,
                error_kind='timeout' if exc.code == 'COMMAND_TIMEOUT' else 'process')
        if budget.is_set() or len(output.stdout) + len(output.stderr) > MAX_STREAM_CHARS:
            return AgentResult('codex', 'review', False, error_kind='token_limit')
        return self.parse('review', output)


def build_prompt(manager_input):
    """Revalidate the typed projection; reject extra fields before sending any data."""
    if not isinstance(manager_input, dict):
        raise ValueError('INVALID_INPUT')
    clean = decision.build_manager_input(dict(schema_version=manager_input.get('schema_version'),
        availability=manager_input.get('availability'), plans=manager_input.get('plans')),
        observation_id=manager_input.get('observation_id'))
    if clean != manager_input:
        raise ValueError('INVALID_INPUT')
    text = json.dumps(clean, ensure_ascii=True, sort_keys=True)
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError('INPUT_LIMIT')
    return (
        'You are a proposal-only Manager. Use ONLY the JSON observation below. No tools, files, '
        'commands, edits, execution, approvals or external information. Return exactly ONE JSON object, '
        'without markdown. Keys: kind, reason_code, plan_id, task_id, snapshot_id, change. '
        'Copy existing IDs and the original snapshot_id. Allowed kinds: ' + ', '.join(sorted(decision.KINDS)) + '. '
        'Rules: landed/cancelled -> NO_ACTION TERMINAL; unavailable -> REQUEST_HUMAN STATE_UNAVAILABLE; '
        'failed -> REQUEST_HUMAN TASK_FAILED; needs_human/candidate_ready -> REQUEST_HUMAN HUMAN_REQUIRED; '
        'proposed -> REQUEST_HUMAN APPROVAL_REQUIRED; held -> WAIT HELD; running -> WAIT TASK_ACTIVE. '
        'Approved with unmet dependencies -> WAIT DEPENDENCIES_PENDING. Otherwise only the first '
        'approved task in plan order whose dependencies are landed may be PROPOSE_START APPROVED_READY, '
        'and only when the plan has no running/candidate_ready/failed/needs_human task; others WAIT QUEUED. '
        'PROPOSE_START is a candidate, never permission. Normally change=null. PROPOSE_TASK_CHANGE '
        'requires reason WORKFLOW_CHANGE and a Workflow proposal {plan_id,base_revision,ops}, one op '
        '{op,task_id} where op is hold/release/cancel. Never guess missing revision or business context; '
        'prefer an ordinary state-based decision when change context is absent. No other keys or free text.\n'
        + text)


class ManagerAgent:
    def __init__(self, *, collector=None, provider_name='codex', provider_factory=None,
                 timeout_seconds=120, now=None):
        self.collector = collector if collector is not None else ManagerCollector()
        self.provider_name = provider_name
        self._factory = provider_factory or ManagerCodexProvider
        self.timeout = timeout_seconds
        self._now = now or time.monotonic

    def infer(self, *, allow_ai=False, stop_event=None):
        """Explicit trusted authorization only. Returns fixed display data, never a change payload."""
        name = 'codex' if self.provider_name == 'codex' else 'unknown'
        def result(code, *, value=None, validation='NOT_RUN', tokens=None):
            return dict(ok=code == 'ACCEPTED', code=code, provider=name,
                decision_kind=value['kind'] if value else None,
                plan_id=value['plan_id'] if value else None, task_id=value['task_id'] if value else None,
                reason_code=value['reason_code'] if value else None,
                validation_code=validation, tokens=tokens)
        if allow_ai is not True:
            return result('AI_NOT_AUTHORIZED')
        if name != 'codex':
            return result('UNSUPPORTED_PROVIDER')
        if type(self.timeout) is not int or not 1 <= self.timeout <= 240:
            return result('INVALID_TIMEOUT')
        if not _INFERENCE_LOCK.acquire(blocking=False):
            return result('BUSY')
        try:
            if stop_event is not None and stop_event.is_set():
                return result('STOPPED')
            collected = self.collector.collect()
            if collected.get('status') != 'available' or collected.get('manager_input') is None:
                return result('COLLECTION_UNAVAILABLE')
            try:
                prompt = build_prompt(collected['manager_input'])
            except (ValueError, TypeError, KeyError, RecursionError):
                return result('INVALID_INPUT')
            if not any(p['tasks'] for p in collected['manager_input']['plans']):
                return result('NO_TASKS')
            if stop_event is not None and stop_event.is_set():
                return result('STOPPED')
            started = self._now()
            with tempfile.TemporaryDirectory(prefix='dcc-manager-') as directory:
                reply = self._factory().run_review(Path(directory), prompt, timeout=self.timeout,
                                                   hooks=ProcessHooks(stop=stop_event))
            if stop_event is not None and stop_event.is_set():
                return result('STOPPED')
            if self._now() - started >= self.timeout:
                return result('PROVIDER_TIMEOUT')
            if not isinstance(reply, AgentResult) or reply.provider != 'codex' or reply.role != 'review' or type(reply.ok) is not bool:
                return result('PROVIDER_PROTOCOL')
            tokens = reply.tokens if type(reply.tokens) is int and reply.tokens > 0 else None
            if not reply.ok:
                code = ERRORS.get(reply.error_kind, 'PROVIDER_ERROR') if isinstance(reply.error_kind, str) else 'PROVIDER_ERROR'
                return result(code, tokens=tokens)
            if not isinstance(reply.text, str) or not isinstance(reply.raw, str):
                return result('PROVIDER_PROTOCOL', tokens=tokens)
            if len(reply.text) > MAX_RESPONSE_CHARS or len(reply.raw) > MAX_STREAM_CHARS:
                return result('OUTPUT_LIMIT', tokens=tokens)
            context = collected['manager_input']
            # Change proposals are structurally checked here; only Collector has
            # the full current plans for the final manager-actor Workflow preview.
            initial = decision.validate_ai_response(reply.text,
                dict(schema_version=1, availability=context['availability'], plans=context['plans']),
                observation_id=context['observation_id'])
            if not initial['accepted'] and initial['code'] != 'WORKFLOW_CONTEXT_REQUIRED':
                return result('INVALID_DECISION', validation=initial['code'], tokens=tokens)
            if stop_event is not None and stop_event.is_set():
                return result('STOPPED', tokens=tokens)
            checked = self.collector.revalidate(reply.text)['validation']
            if stop_event is not None and stop_event.is_set():
                return result('STOPPED', tokens=tokens)
            if not checked['accepted']:
                return result('REVALIDATION_FAILED', validation=checked['code'], tokens=tokens)
            return result('ACCEPTED', value=checked['decision'], validation='ACCEPTED', tokens=tokens)
        except StopRequested:
            return result('STOPPED')
        except TimeoutError:
            return result('PROVIDER_TIMEOUT')
        except Exception:
            return result('PROVIDER_ERROR')
        finally:
            _INFERENCE_LOCK.release()
