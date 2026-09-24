"""Focused HOL regressions; all provider execution is mocked (no credits used)."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest import mock

from scripts.dev_control_center import app as dcc
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


class DccReviewResumeButtonStateTests(unittest.TestCase):
    """The resume button is enabled only for an inspected review_pending run on an idle, safe repo."""

    @staticmethod
    def ui(*, plan, busy=False, safe=True, head="a" * 40, origin="a" * 40):
        ui = mock.MagicMock()
        ui.current = mock.MagicMock()
        ui.entrypoints = None  # stop right after the AI / review button block
        ui.active_process = (mock.MagicMock(), "demo", "release") if busy else None
        ui.ai_stop_requested = False
        ui.repo_state.safe_for_lifecycle.return_value = safe
        ui.repo_state.head = head
        ui.repo_state.origin_head = origin
        ui.review_plan = plan
        return ui

    def state_of(self, ui):
        dcc.App._apply_lifecycle_state(ui)
        return ui.review_resume_button.configure.call_args.kwargs["state"]

    def test_enabled_only_when_idle_safe_synced_and_plan_ok(self):
        self.assertEqual(self.state_of(self.ui(plan=dcc.ReviewResumePlan(True, "ok"))), "normal")

    def test_disabled_without_a_plan_or_with_a_rejected_plan(self):
        self.assertEqual(self.state_of(self.ui(plan=None)), "disabled")
        self.assertEqual(self.state_of(self.ui(plan=dcc.ReviewResumePlan(False, "status=running"))), "disabled")

    def test_disabled_while_another_action_is_running(self):
        self.assertEqual(self.state_of(self.ui(plan=dcc.ReviewResumePlan(True, "ok"), busy=True)), "disabled")

    def test_disabled_when_repo_is_not_safe_for_lifecycle(self):
        self.assertEqual(self.state_of(self.ui(plan=dcc.ReviewResumePlan(True, "ok"), safe=False)), "disabled")

    def test_disabled_when_local_head_is_not_origin_head(self):
        ui = self.ui(plan=dcc.ReviewResumePlan(True, "ok"), origin="b" * 40)
        self.assertEqual(self.state_of(ui), "disabled")

    def test_disabled_without_a_selected_repo(self):
        ui = self.ui(plan=dcc.ReviewResumePlan(True, "ok"))
        ui.current = None
        self.assertEqual(self.state_of(ui), "disabled")


class DccResumeAiReviewTests(unittest.TestCase):
    HEAD = "A" * 40

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.run_dir = self.tmp / "runs" / "20260924-120000-000000"
        self.plan = dcc.ReviewResumePlan(
            True,
            "ok",
            run_dir=self.run_dir,
            task="saved task",
            tests=("python -m pytest tests/a.py",),
            max_rounds=7,
            request_id="req-1",
        )
        self.ui = mock.MagicMock()
        self.ui.current.name = "demo"
        self.ui.current.branch = "main"
        self.ui.active_process = None
        self.ui.repo_state.head = self.HEAD
        self.ui.repo_state.origin_head = self.HEAD.lower()
        self.ui.repo_state.safe_for_lifecycle.return_value = True
        self.ui.review_plan = self.plan
        self.ui.ai_output_queue = queue.Queue()
        self.ui.ai_output_queue.put("stale line from an earlier run")
        self.decision = {"request_id": "req-1", "verdict": "PASS", "summary": "reviewed"}
        self.ui.review_decision.get.return_value = json.dumps(self.decision) + "\n"
        self.spawned = []
        self.decision_seen = []
        self.process = mock.MagicMock()

    def run_resume(self, spawn=None):
        def default_spawn(command):
            self.spawned.append(command)
            path = Path(command[command.index("--final-review-decision") + 1])
            self.decision_seen.append((path.is_file(), json.loads(path.read_text(encoding="utf-8"))))
            return self.process

        with mock.patch.object(dcc.messagebox, "showerror") as showerror, \
                mock.patch.object(dcc, "_spawn_ai_process", side_effect=spawn or default_spawn) as spawn_mock, \
                mock.patch.object(dcc.tempfile, "gettempdir", return_value=str(self.tmp)), \
                mock.patch.object(dcc, "REPOS_ROOT", self.tmp / "repos"), \
                mock.patch.object(dcc.threading, "Thread") as thread:
            dcc.App.resume_ai_review(self.ui)
        self.showerror, self.spawn_mock, self.thread = showerror, spawn_mock, thread

    def assert_refused(self):
        self.spawn_mock.assert_not_called()
        self.showerror.assert_called_once()
        self.ui._begin_process.assert_not_called()
        self.assertEqual(list(self.tmp.glob("dcc-ai-review-decision-*.json")), [])

    def test_refused_while_a_process_is_active(self):
        self.ui.active_process = (mock.MagicMock(), "demo", "ai_orchestrator")
        self.run_resume()
        self.spawn_mock.assert_not_called()
        self.ui._begin_process.assert_not_called()

    def test_refused_when_repo_is_not_safe(self):
        self.ui.repo_state.safe_for_lifecycle.return_value = False
        self.run_resume()
        self.assert_refused()

    def test_refused_when_local_head_differs_from_origin_head(self):
        self.ui.repo_state.origin_head = "b" * 40
        self.run_resume()
        self.assert_refused()

    def test_refused_when_the_rechecked_plan_is_not_ok(self):
        self.ui.review_plan = dcc.ReviewResumePlan(False, "status=running")
        self.run_resume()
        self.assert_refused()
        self.ui._refresh_review_plan.assert_called_once()

    def test_refused_when_no_plan_exists(self):
        self.ui.review_plan = None
        self.run_resume()
        self.assert_refused()

    def test_refused_for_invalid_decisions(self):
        bad = [
            "",
            "{not json",
            json.dumps({**self.decision, "request_id": "other"}),
            json.dumps({**self.decision, "verdict": "pass"}),
            json.dumps({**self.decision, "summary": " "}),
        ]
        for text in bad:
            with self.subTest(text=text):
                self.ui.review_decision.get.return_value = text
                self.run_resume()
                self.assert_refused()

    def test_each_verdict_resumes_the_orchestrator_through_the_normal_ai_run_path(self):
        for verdict in ("PASS", "FAIL", "PENDING"):
            with self.subTest(verdict=verdict):
                self.spawned.clear()
                self.decision_seen.clear()
                self.ui.reset_mock()
                self.ui.active_process = None
                self.ui.review_plan = self.plan
                self.ui.ai_output_queue.put("stale")
                decision = {**self.decision, "verdict": verdict}
                self.ui.review_decision.get.return_value = json.dumps(decision)
                self.run_resume()

                self.showerror.assert_not_called()
                self.spawn_mock.assert_called_once()
                command = self.spawned[0]
                self.assertEqual(command[2], "run")
                self.assertEqual(command[command.index("--resume-review") + 1], str(self.run_dir))
                self.assertEqual(command[command.index("--task") + 1], "saved task")
                self.assertEqual(command[command.index("--max-rounds") + 1], "7")
                self.assertEqual(self.decision_seen, [(True, decision)])
                context = self.ui.ai_context
                self.assertEqual(context["repo_name"], "demo")
                self.assertEqual(context["base_sha"], self.HEAD.lower())
                self.assertEqual(context["result_path"].parent, self.tmp)
                self.assertEqual(context["decision_path"].parent, self.tmp)
                # Same action name as a normal AI run: no separate progress / result / candidate path.
                self.ui._begin_process.assert_called_once_with(
                    self.process, "demo", "ai_orchestrator"
                )
                self.assertIn(verdict, self.ui.ai_status_var.set.call_args.args[0])
                self.thread.assert_called_once()
                self.thread.return_value.start.assert_called_once()
                self.ui.master.after.assert_called_once_with(250, self.ui._poll)
                self.assertTrue(self.ui.ai_output_queue.empty())
                self.assertFalse(self.ui.ai_stop_requested)

    def test_resume_never_reads_the_new_task_fields(self):
        self.run_resume()
        self.ui.ai_task.get.assert_not_called()
        self.ui.ai_test_var.get.assert_not_called()

    def test_spawn_failure_removes_the_decision_file_and_shows_an_error(self):
        def failing(command):
            raise OSError("boom")

        self.run_resume(spawn=failing)
        self.showerror.assert_called_once()
        self.assertIn("boom", self.showerror.call_args.args[1])
        self.ui._begin_process.assert_not_called()
        self.assertEqual(list(self.tmp.glob("dcc-ai-review-decision-*.json")), [])


class DccFinishAfterReviewResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.decision_path = self.tmp / "decision.json"

    def ui(self, payload=None, *, decision=True, current="demo"):
        ui = mock.MagicMock()
        ui.ai_stop_requested = False
        ui.current.name = current
        context = {"repo_name": "demo", "result_path": self.tmp / "result.json", "base_sha": "a" * 40}
        if payload is not None:
            context["result_path"].write_text(json.dumps(payload), encoding="utf-8")
        if decision:
            self.decision_path.write_text("{}", encoding="utf-8")
            context["decision_path"] = self.decision_path
        ui.ai_context = context
        return ui

    def test_decision_file_is_removed_after_success_and_failure(self):
        pending = {"status": "review_pending", "run_dir": "C:/runs/x"}
        for rc, payload in ((0, pending), (1, None)):
            with self.subTest(rc=rc), mock.patch.object(dcc.messagebox, "showerror"):
                ui = self.ui(payload)
                self.assertTrue(self.decision_path.exists())
                dcc.App._finish_ai_orchestrator(ui, "demo", rc)
                self.assertFalse(self.decision_path.exists())

    def test_decision_file_is_removed_after_a_safety_stop(self):
        ui = self.ui()
        ui.ai_stop_requested = True
        dcc.App._finish_ai_orchestrator(ui, "demo", 1)
        self.assertFalse(self.decision_path.exists())

    def test_normal_run_without_decision_path_is_unaffected(self):
        ui = self.ui({"status": "review_pending", "run_dir": "C:/runs/x"}, decision=False)
        dcc.App._finish_ai_orchestrator(ui, "demo", 0)
        ui.ai_status_var.set.assert_called_once()

    def test_review_pending_result_fills_run_dir_for_the_selected_repo_and_applies_no_candidate(self):
        ui = self.ui({"status": "review_pending", "run_dir": "C:/runs/x"})
        with mock.patch.object(dcc, "apply_local_candidate") as apply_candidate:
            dcc.App._finish_ai_orchestrator(ui, "demo", 0)
        ui.review_run_dir_var.set.assert_called_once_with("C:/runs/x")
        ui.review_decision.delete.assert_called_once_with("1.0", "end")
        ui.selection.provenance.ai_result.assert_not_called()
        apply_candidate.assert_not_called()
        ui._reload_after.assert_called_once_with("demo")

    def test_review_pending_result_does_not_touch_the_panel_for_another_repo(self):
        ui = self.ui({"status": "review_pending", "run_dir": "C:/runs/x"}, current="other")
        dcc.App._finish_ai_orchestrator(ui, "demo", 0)
        ui.review_run_dir_var.set.assert_not_called()
        ui.review_decision.delete.assert_not_called()

    def test_resumed_pass_result_uses_the_normal_candidate_confirmation(self):
        payload = {"status": "candidate_ready", "candidate_sha": "b" * 40, "base_sha": "a" * 40}
        ui = self.ui(payload)
        ui._confirm_with_guard.return_value = (False, True)  # user declines the fast-forward
        with mock.patch.object(dcc, "apply_local_candidate") as apply_candidate:
            dcc.App._finish_ai_orchestrator(ui, "demo", 0)
        ui.selection.provenance.ai_result.assert_called_once_with("demo", "b" * 40)
        ui._confirm_with_guard.assert_called_once()
        self.assertEqual(ui._confirm_with_guard.call_args.args[0], "ai_apply")
        apply_candidate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
