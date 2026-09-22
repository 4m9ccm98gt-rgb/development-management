"""Bounded read-only Git safety probe tests; no providers or Orchestrator runs."""
from pathlib import Path
import unittest
from unittest import mock

from tools.ai_orchestrator import orchestrator as o

BASE = 'a' * 40


def result(rc=0, stdout='', stderr=''):
    return o.CommandResult(('git',), rc, stdout, stderr)


class WorktreeHeadProbeTests(unittest.TestCase):
    def setUp(self):
        self.worktree = Path('isolated-test-worktree')
        self.runner = self.enterContext(mock.patch.object(o, '_run'))
        self.sleep = self.enterContext(mock.patch.object(o.time, 'sleep'))
        self.enterContext(mock.patch.object(o, '_resolved_command', return_value=['git']))

    def check(self):
        o._assert_agent_did_not_commit(self.worktree, BASE)

    def test_empty_error_then_success_still_checks_head_and_detached_branch(self):
        self.runner.side_effect = [result(1), result(stdout=BASE), result()]
        self.check()
        self.assertEqual(self.runner.call_count, 3)
        self.sleep.assert_called_once_with(0.2)
        commands = [call.args[0] for call in self.runner.call_args_list]
        self.assertEqual(commands[0], ['git', '-C', str(self.worktree), 'rev-parse', 'HEAD'])
        self.assertEqual(commands[0], commands[1])
        self.assertEqual(commands[2][-2:], ['branch', '--show-current'])

    def test_persistent_empty_error_stops_after_three_attempts(self):
        self.runner.return_value = result(1, ' \n', '\t')
        with self.assertRaisesRegex(o.OrchestratorError, 'return code 1, attempt 3/3'):
            self.check()
        self.assertEqual(self.runner.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [mock.call(0.2), mock.call(0.2)])

    def test_explicit_error_in_either_stream_stops_without_retry(self):
        for stdout, stderr in [('', 'fatal: not a git repository'), ('fatal: bad revision', ' \n')]:
            with self.subTest(stdout=stdout, stderr=stderr):
                self.runner.reset_mock()
                self.runner.return_value = result(128, stdout, stderr)
                with self.assertRaisesRegex(o.OrchestratorError, 'fatal:'):
                    self.check()
                self.runner.assert_called_once()
                self.sleep.assert_not_called()

    def test_changed_head_after_retry_still_fails_closed(self):
        self.runner.side_effect = [result(1), result(stdout='b'*40), result()]
        with self.assertRaisesRegex(o.OrchestratorError, 'agent changed Git history'):
            self.check()

    def test_attached_branch_still_fails_closed(self):
        self.runner.side_effect = [result(stdout=BASE), result(stdout='main')]
        with self.assertRaisesRegex(o.OrchestratorError, 'agent changed Git history'):
            self.check()
        self.sleep.assert_not_called()

    def test_zero_exit_without_head_cannot_pass_safety_check(self):
        self.runner.side_effect = [result(), result()]
        with self.assertRaisesRegex(o.OrchestratorError, 'agent changed Git history'):
            self.check()
        self.sleep.assert_not_called()

    def test_timeout_or_start_failure_is_not_retried(self):
        self.runner.side_effect = o.OrchestratorError('command timed out')
        with self.assertRaisesRegex(o.OrchestratorError, 'timed out'):
            self.check()
        self.runner.assert_called_once()
        self.sleep.assert_not_called()

    def test_general_git_write_command_is_never_retried(self):
        self.runner.return_value = result(1)
        with self.assertRaises(o.OrchestratorError):
            o._git(self.worktree, 'checkout', 'example')
        self.runner.assert_called_once()
        self.sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
