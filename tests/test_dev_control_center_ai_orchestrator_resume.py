"""Focused HOL regressions; all provider execution is mocked (no credits used)."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.ai_orchestrator import orchestrator as o

SESSION = '12345678-1234-1234-1234-123456789abc'


def response(kind='max', session=SESSION, returncode=None, message=''):
    payload = {'type': 'result', 'session_id': session}
    if kind == 'max':
        payload.update(is_error=True, subtype='error_max_turns', errors=['Reached maximum number of turns (12)'])
    elif kind == 'ok':
        payload.update(is_error=False, subtype='success', result=message or 'Implemented')
    else:
        payload.update(is_error=True, subtype='error_during_execution', errors=[message])
    return o.CommandResult(('claude',), (0 if kind == 'ok' else 1) if returncode is None else returncode,
                           json.dumps(payload), '')


class ClaudeResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []
        self.diff = ''
        self.commands = []
        self.agent_inputs = []

    def pipeline(self, outputs):
        worktree = self.root / 'isolated'
        worktree.mkdir()
        baseline = o.RepoBaseline(self.root / 'source', 'main', 'a'*40, 'a'*40)
        args = o.build_parser().parse_args([
            'run', '--repo', str(baseline.root), '--task', 'implement confirmed fix',
            '--test', 'mock test', '--no-fetch', '--max-rounds', '0', '--result-file', str(self.root/'external.json'),
        ])
        sequence = iter(outputs)

        def provider(command, **kwargs):
            self.events.append('claude')
            self.commands.append(command)
            self.agent_inputs.append(kwargs)
            result, self.diff = next(sequence)
            if isinstance(result, Exception):
                raise result
            return result

        def gate(*args):
            self.events.append('review')
            return {'verdict': 'PASS', 'summary': 'independent approval'}

        def tests(*args):
            self.events.append('tests')
            return True, 'PASS'

        with ExitStack() as stack:
            patches = {
                '_resolved_command': mock.Mock(side_effect=lambda name: [name]),
                '_enforce_billing_guard': mock.Mock(return_value=()),
                '_repo_baseline': mock.Mock(return_value=baseline),
                '_create_worktree': mock.Mock(return_value=(self.root/'parent', worktree)),
                '_state_root': mock.Mock(return_value=self.root/'state'),
                '_now_id': mock.Mock(return_value='test-run'),
                '_diff_for_review': mock.Mock(side_effect=lambda _: ('stat', self.diff)),
                '_run': mock.Mock(side_effect=provider),
                '_run_codex_review': mock.Mock(side_effect=AssertionError('unexpected Astra call')),
                '_final_review_gate': mock.Mock(side_effect=gate),
                '_assert_agent_did_not_commit': mock.Mock(),
                '_assert_source_unchanged': mock.Mock(),
                '_run_tests': mock.Mock(side_effect=tests),
                '_create_candidate': mock.Mock(return_value=('ai-candidate/test', 'b'*40)),
                '_git': mock.Mock(),
            }
            for name, replacement in patches.items():
                stack.enter_context(mock.patch.object(o, name, replacement))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            code = o.run(args)
            self.safety_checks = patches['_assert_source_unchanged'].call_count
        self.result = json.loads((self.root/'external.json').read_text(encoding='utf-8'))
        self.saved = json.loads((self.root/'state/runs/test-run/claude-session.json').read_text(encoding='utf-8'))
        self.assertEqual(self.result['run_id'], 'test-run')
        self.assertEqual(self.saved['worktree'], str(worktree))
        for command in self.commands:
            self.assertEqual(command[command.index('--max-turns')+1], '12')
            self.assertEqual(command[command.index('--permission-mode')+1], 'acceptEdits')
            self.assertNotIn('--fork-session', command)
            self.assertNotIn('--continue', command)
        for kwargs in self.agent_inputs:
            self.assertEqual(kwargs['cwd'], worktree)
            self.assertEqual(kwargs['env']['GIT_CONFIG_VALUE_0'], 'disabled://ai-orchestrator')
        return code

    def assert_stopped(self, code):
        self.assertEqual(self.result['status'], 'stopped')
        self.assertEqual(self.result['error_code'], code)
        self.assertEqual(self.saved['outcome'], code)
        self.assertNotIn('tests', self.events)
        self.assertNotIn('review', self.events)
        self.assertTrue(Path(self.saved['worktree']).is_dir())

    def test_max_turns_with_diff_runs_tests_without_resume(self):
        self.assertEqual(self.pipeline([(response(session=None), 'diff')]), 0)
        self.assertEqual(self.events, ['claude', 'tests', 'review'])
        self.assertEqual(self.saved['outcome'], 'IMPLEMENTATION_DIFF')
        self.assertNotIn('--resume', self.commands[0])

    def test_empty_max_turns_resumes_same_session_then_tests(self):
        self.assertEqual(self.pipeline([(response(), ''), (response(), 'new diff')]), 0)
        self.assertEqual(self.events, ['claude', 'claude', 'tests', 'review'])
        self.assertEqual(self.commands[1][-2:], ['--resume', SESSION])
        self.assertEqual(self.saved['session_id'], SESSION)
        self.assertEqual(self.saved['resume_count'], 1)
        self.assertEqual(self.result['claude_calls'], 2)
        self.assertGreaterEqual(self.safety_checks, 2)
        self.assertIn('do not restart investigation', self.agent_inputs[1]['input_text'])

    def test_successful_resume_with_diff_runs_tests(self):
        self.assertEqual(self.pipeline([(response(), ''), (response('ok'), 'diff')]), 0)
        self.assertEqual(self.events[-2:], ['tests', 'review'])

    def test_empty_resumes_stop_at_two(self):
        self.assertEqual(o.CLAUDE_NO_DIFF_RESUMES, 2)
        self.assertEqual(self.pipeline([(response(), '')]*3), 1)
        self.assert_stopped('NO_PROGRESS')
        self.assertEqual(len(self.commands), 3)
        self.assertEqual(self.saved['resume_count'], 2)
        self.assertEqual(self.saved['session_id'], SESSION)
        self.assertEqual(self.saved['stage'], 'implementation')
        self.assertEqual(self.saved['round'], 0)
        self.assertTrue((self.root/'state/runs/test-run'/self.saved['prompt_file']).is_file())

    def test_resume_returns_success_but_no_diff_stops_immediately(self):
        self.assertEqual(self.pipeline([(response(), ''), (response('ok'), '')]), 1)
        self.assert_stopped('NO_PROGRESS')
        self.assertEqual(len(self.commands), 2)

    def test_missing_session_has_clear_reason(self):
        self.assertEqual(self.pipeline([(response(session=None), '')]), 1)
        self.assert_stopped('SESSION_ID_UNAVAILABLE')
        self.assertEqual(len(self.commands), 1)

    def test_unsafe_session_is_not_passed_to_cli(self):
        self.assertEqual(self.pipeline([(response(session='--bad & command'), '')]), 1)
        self.assert_stopped('SESSION_ID_UNAVAILABLE')
        with mock.patch.object(o, '_resolved_command', return_value=['claude']):
            with self.assertRaises(o.ClaudeExecutionError):
                o._claude_implementation_command('--bad')

    def test_quota_stops_without_provider_retries_even_with_diff(self):
        self.assertEqual(self.pipeline([(response('error', message='Credit balance is too low'), 'diff')]), 1)
        self.assert_stopped('PROVIDER_QUOTA')
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.saved['session_id'], SESSION)

    def test_quota_on_resume_preserves_session_and_stops(self):
        self.assertEqual(self.pipeline([(response(), ''), (response('error', returncode=0, message="You've hit your limit"), '')]), 1)
        self.assert_stopped('PROVIDER_QUOTA')
        self.assertEqual(len(self.commands), 2)
        self.assertEqual(self.saved['session_id'], SESSION)

    def test_quota_variants_and_successful_prose(self):
        for text in ('insufficient_quota', 'quota exceeded', 'credits exhausted', 'usage limit reached', 'spending limit reached'):
            with self.subTest(text=text):
                self.assertTrue(o._claude_quota_error(response('error', message=text)))
        self.assertFalse(o._claude_quota_error(response('ok', message='Fixed credit balance is too low handling')))
        self.assertFalse(o._looks_like_max_turns(response('ok', message='Fixed maximum number of turns handling')))

    def test_resume_failure_is_distinct(self):
        self.assertEqual(self.pipeline([(response(), ''), (response('error', message='Session not found'), '')]), 1)
        self.assert_stopped('RESUME_FAILED')
        self.assertEqual(len(self.commands), 2)
        self.assertEqual(self.saved['session_id'], SESSION)

    def test_provider_failure_is_distinct(self):
        self.assertEqual(self.pipeline([(response('error', message='Connection failed'), '')]), 1)
        self.assert_stopped('PROVIDER_ERROR')

    def test_resume_startup_failure_is_distinct(self):
        self.assertEqual(self.pipeline([(response(), ''), (o.OrchestratorError('failed to start'), '')]), 1)
        self.assert_stopped('RESUME_FAILED')
        self.assertEqual(self.saved['session_id'], SESSION)

    def test_session_mismatch_does_not_adopt_new_session(self):
        other = '87654321-1234-1234-1234-123456789abc'
        self.assertEqual(self.pipeline([(response(), ''), (response(session=other), 'diff')]), 1)
        self.assert_stopped('RESUME_FAILED')
        self.assertEqual(self.saved['session_id'], SESSION)

    def test_zero_exit_max_turns_is_also_recoverable(self):
        self.assertEqual(self.pipeline([(response(returncode=0), ''), (response('ok'), 'diff')]), 0)
        self.assertEqual(len(self.commands), 2)

    def test_malformed_json_cannot_start_tests(self):
        bad = o.CommandResult(('claude',), 0, 'not json', '')
        self.assertEqual(self.pipeline([(bad, 'diff')]), 1)
        self.assert_stopped('PROVIDER_ERROR')


if __name__ == '__main__':
    unittest.main()
