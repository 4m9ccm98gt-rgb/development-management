"""Fakes and temp cwd only. Actual providers/processes/network are forbidden."""
import copy
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from scripts.dev_control_center import manager_agent as agent
from scripts.dev_control_center.manager_collector import ManagerCollector
from scripts.dev_control_center import manager_decision as md
from tools.ai_orchestrator.providers import AgentResult
from tools.ai_orchestrator.common import CommandResult, ProcessHooks, StopRequested, OrchestratorError
from tests.test_dev_control_center_manager_overview import plan, task, KEYS

SECRET = 'SECRET C:/private AI output'


def reply_for(prompt):
    context = json.loads(prompt.split('\n', 1)[1])
    snapshot = dict(schema_version=1, availability=context['availability'], plans=context['plans'])
    value = md.suggest_decisions(snapshot, observation_id=context['observation_id'])[0]
    return AgentResult('codex', 'review', True, text=json.dumps(value), tokens=23, raw=SECRET)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('subprocess.Popen', 'socket.socket', 'tkinter.Tk',
            'scripts.dev_control_center.workflow_plan.plans_root',
            'scripts.dev_control_center.workflow_plan.save_plan',
            'scripts.dev_control_center.workflow_plan.update_plan',
            'scripts.dev_control_center.candidate.approve',
            'scripts.dev_control_center.candidate.push',
            'scripts.dev_control_center.provenance.build',
            'scripts.dev_control_center.release_update.plan',
            'tools.ai_orchestrator.orchestrator.start_run'):
            forbidden = self.stack.enter_context(patch(target, side_effect=AssertionError('FORBIDDEN')))
            self.addCleanup(forbidden.assert_not_called)
        self.source = plan(task('T1'))
        self.clock = [0.0]
        self.collector = ManagerCollector(registered_keys=KEYS,
            list_plans=lambda: ['Plan-1'], load_plan=lambda pid: copy.deepcopy(self.source),
            read_association=lambda *args: None, inspect_run=Mock(side_effect=AssertionError),
            next_observation=itertools.count(1).__next__, now=lambda: self.clock[0])
        self.provider = Mock()
        self.provider.run_review.side_effect = lambda cwd, prompt, **kwargs: reply_for(prompt)
        self.factory = Mock(return_value=self.provider)
        self.adapter = agent.ManagerAgent(collector=self.collector, provider_factory=self.factory)

    def test_explicit_authorization_only_and_provider_choice_trusted(self):
        for allowed in (False, None, 1, 'yes'):
            self.assertEqual(self.adapter.infer(allow_ai=allowed)['code'], 'AI_NOT_AUTHORIZED')
        self.factory.assert_not_called()
        self.adapter.provider_name = 'SECRET'
        self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'UNSUPPORTED_PROVIDER')
        self.factory.assert_not_called()

    def test_success_safe_prompt_empty_isolated_cwd_and_result(self):
        self.source['tasks'][0]['body'] += '\n## 範囲外\n' + SECRET
        before = copy.deepcopy(self.source)
        captured = []
        def call(cwd, prompt, **kwargs):
            self.assertTrue(cwd.is_dir())
            self.assertEqual(list(cwd.iterdir()), [])
            self.assertNotIn('SECRET', prompt)
            self.assertNotIn(str(cwd), prompt)
            self.assertIn('PROPOSE_TASK_CHANGE', prompt)
            captured.append(cwd)
            return reply_for(prompt)
        self.provider.run_review.side_effect = call
        result = self.adapter.infer(allow_ai=True)
        self.assertEqual(result, dict(ok=True, code='ACCEPTED', provider='codex',
            decision_kind='PROPOSE_START', plan_id='Plan-1', task_id='T1',
            reason_code='APPROVED_READY', validation_code='ACCEPTED', tokens=23))
        self.assertFalse(captured[0].exists())
        self.assertNotIn('SECRET', str(result))
        self.assertEqual(self.source, before)

    def test_invalid_json_unknown_command_and_stale_response(self):
        def bad_json(cwd, prompt, **kwargs):
            return AgentResult('codex', 'review', True, text='{SECRET')
        self.provider.run_review.side_effect = bad_json
        self.assertEqual(self.adapter.infer(allow_ai=True)['validation_code'], 'INVALID_JSON')
        def wrong(cwd, prompt, **kwargs):
            response = reply_for(prompt)
            value = json.loads(response.text)
            value['command'] = SECRET
            response.text = json.dumps(value)
            return response
        self.provider.run_review.side_effect = wrong
        self.assertEqual(self.adapter.infer(allow_ai=True)['validation_code'], 'INVALID_SCHEMA')
        prior = []
        def stale(cwd, prompt, **kwargs):
            current = reply_for(prompt)
            prior.append(current)
            return prior[0]
        self.provider.run_review.side_effect = stale
        self.assertTrue(self.adapter.infer(allow_ai=True)['ok'])
        self.assertEqual(self.adapter.infer(allow_ai=True)['validation_code'], 'STALE_SNAPSHOT')

    def test_changed_expired_consumed_and_superseded_observations(self):
        for mode, expected in [('changed', 'STATE_CHANGED'), ('expired', 'OBSERVATION_EXPIRED'),
                               ('consumed', 'OBSERVATION_UNKNOWN'), ('superseded', 'STALE_SNAPSHOT')]:
            with self.subTest(mode=mode):
                self.clock[0] = 0
                self.source['tasks'][0]['status'] = 'approved'
                def call(cwd, prompt, **kwargs):
                    response = reply_for(prompt)
                    if mode == 'changed':
                        self.source['revision'] += 1
                    elif mode == 'expired':
                        self.clock[0] = 301
                    elif mode == 'consumed':
                        self.collector.revalidate(response.text)
                    else:
                        self.collector.collect()
                    return response
                self.provider.run_review.side_effect = call
                result = self.adapter.infer(allow_ai=True)
                self.assertEqual(result['code'], 'REVALIDATION_FAILED')
                self.assertEqual(result['validation_code'], expected)

    def test_provider_errors_fixed_without_raw_detail_or_retry(self):
        for kind, code in agent.ERRORS.items():
            self.provider.run_review.return_value = AgentResult('codex', 'review', False,
                error_kind=kind, error_detail=SECRET, raw=SECRET)
            self.provider.run_review.side_effect = None
            result = self.adapter.infer(allow_ai=True)
            self.assertEqual(result['code'], code)
            self.assertNotIn('SECRET', str(result))
        for error, code in ((RuntimeError(SECRET), 'PROVIDER_ERROR'),
                             (TimeoutError(SECRET), 'PROVIDER_TIMEOUT'),
                             (StopRequested(SECRET), 'STOPPED')):
            self.provider.run_review.side_effect = error
            self.assertEqual(self.adapter.infer(allow_ai=True)['code'], code)

    def test_stop_before_and_during_provider(self):
        stop = threading.Event()
        stop.set()
        self.assertEqual(self.adapter.infer(allow_ai=True, stop_event=stop)['code'], 'STOPPED')
        self.factory.assert_not_called()
        stop.clear()
        def call(cwd, prompt, **kwargs):
            self.assertIs(kwargs['hooks'].stop, stop)
            stop.set()
            return reply_for(prompt)
        self.provider.run_review.side_effect = call
        self.assertEqual(self.adapter.infer(allow_ai=True, stop_event=stop)['code'], 'STOPPED')

    def test_duplicate_execution_prevented_across_instances(self):
        other = agent.ManagerAgent(collector=Mock(), provider_factory=Mock())
        def call(cwd, prompt, **kwargs):
            self.assertEqual(other.infer(allow_ai=True)['code'], 'BUSY')
            other.collector.collect.assert_not_called()
            return reply_for(prompt)
        self.provider.run_review.side_effect = call
        self.assertTrue(self.adapter.infer(allow_ai=True)['ok'])

    def test_output_limits_timeout_and_malformed_agent_result(self):
        for response in (AgentResult('codex', 'review', True, text='x' * 16001),
                         AgentResult('codex', 'review', True, raw='x' * 256001)):
            self.provider.run_review.side_effect = None
            self.provider.run_review.return_value = response
            self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'OUTPUT_LIMIT')
        self.adapter._now = Mock(side_effect=[0, 121])
        self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'PROVIDER_TIMEOUT')
        self.adapter._now = lambda: 0
        self.provider.run_review.return_value = object()
        self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'PROVIDER_PROTOCOL')
        self.adapter.timeout = 0
        self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'INVALID_TIMEOUT')

    def test_unavailable_input_and_extra_context_never_calls_ai(self):
        self.adapter.collector = Mock()
        self.adapter.collector.collect.return_value = {'status': 'unavailable'}
        self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'COLLECTION_UNAVAILABLE')
        collected = self.collector.collect()
        collected['manager_input']['body'] = SECRET
        self.adapter.collector.collect.return_value = collected
        self.assertEqual(self.adapter.infer(allow_ai=True)['code'], 'INVALID_INPUT')
        self.factory.assert_not_called()

    def test_change_proposal_requires_final_workflow_validation(self):
        def propose(cwd, prompt, **kwargs):
            response = reply_for(prompt)
            value = json.loads(response.text)
            value.update(kind='PROPOSE_TASK_CHANGE', reason_code='WORKFLOW_CHANGE',
                change=dict(plan_id='Plan-1', base_revision=0, ops=[dict(op='hold', task_id='T1')]))
            response.text = json.dumps(value)
            return response
        self.provider.run_review.side_effect = propose
        before = copy.deepcopy(self.source)
        self.assertEqual(self.adapter.infer(allow_ai=True)['decision_kind'], 'PROPOSE_TASK_CHANGE')
        self.assertEqual(self.source, before)
        self.source['revision'] = 1
        result = self.adapter.infer(allow_ai=True)
        self.assertEqual(result['validation_code'], 'INVALID_WORKFLOW')
        self.assertFalse(result['ok'])

    def test_stop_during_final_collection_is_not_accepted(self):
        stop = threading.Event()
        revalidate = self.collector.revalidate
        def finish(text):
            result = revalidate(text)
            stop.set()
            return result
        with patch.object(self.collector, 'revalidate', side_effect=finish):
            result = self.adapter.infer(allow_ai=True, stop_event=stop)
        self.assertEqual(result['code'], 'STOPPED')
        self.assertIsNone(result['decision_kind'])

    def test_codex_review_command_and_parser_reused_without_process(self):
        provider = agent.ManagerCodexProvider()
        with patch('tools.ai_orchestrator.providers.resolved_command', return_value=['codex']):
            command = provider._command(Path('isolated'), 'read-only')
        self.assertIn('read-only', command)
        self.assertIn('--ignore-user-config', command)
        self.assertIn('--ephemeral', command)
        self.assertIn('--skip-git-repo-check', command)
        for override in ('features.shell_tool=false', 'features.apps=false',
                         'web_search="disabled"', 'mcp_servers={}', 'agents.enabled=false'):
            self.assertIn(override, command)
        stdout = json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}}) + '\n' + json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 2, 'output_tokens': 3}})
        output = CommandResult(('codex',), 0, stdout, '')
        with patch.object(provider, '_command', return_value=['codex']), \
             patch.object(agent, 'run_streaming', return_value=output) as streaming:
            result = provider.run_review(Path('isolated'), 'safe', timeout=10, hooks=ProcessHooks())
        self.assertTrue(result.ok)
        self.assertEqual(result.tokens, 5)
        self.assertEqual(result.role, 'review')
        self.assertEqual(streaming.call_args.kwargs['timeout'], 10)

    def test_stream_budget_requests_stop_and_provider_timeout_classification(self):
        provider = agent.ManagerCodexProvider()
        def overrun(*args, **kwargs):
            kwargs['hooks'].on_line('stdout', 'x' * (agent.MAX_STREAM_CHARS + 1))
            self.assertTrue(kwargs['hooks'].stop.is_set())
            raise StopRequested(SECRET)
        with patch.object(agent, 'run_streaming', side_effect=overrun):
            result = provider._call('review', ['codex'], Path('isolated'), 'safe', 10, ProcessHooks())
        self.assertEqual(result.error_kind, 'token_limit')
        with patch.object(agent, 'run_streaming', side_effect=OrchestratorError(SECRET, 'COMMAND_TIMEOUT')):
            result = provider._call('review', ['codex'], Path('isolated'), 'safe', 10, ProcessHooks())
        self.assertEqual(result.error_kind, 'timeout')


if __name__ == '__main__':
    unittest.main()
