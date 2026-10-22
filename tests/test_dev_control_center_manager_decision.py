"""Pure fake responses only: no provider, Tk, persistent state or process."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts.dev_control_center import manager_decision as md
from scripts.dev_control_center import manager_overview as overview
from scripts.dev_control_center import workflow_plan as wf
from scripts.dev_control_center import workflow_runner as wr
from scripts.dev_control_center import reports_auto as auto
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID


def snapshot(*tasks):
    return overview.build_snapshot([plan(*tasks)], registered_keys=KEYS)


class DecisionTests(unittest.TestCase):
    def decision(self, source):
        return md.suggest_decisions(source, observation_id=1)[0]

    def validate(self, value, source, **kwargs):
        return md.validate_ai_response(json.dumps(value), source, observation_id=1, **kwargs)

    def test_multiple_tasks_and_plans_and_fixed_suggestions(self):
        source = snapshot(task('T1', 'landed'), task('T2', 'failed'), task('T3', 'needs_human'),
                          task('T4', 'proposed'), task('T5', 'held'), task('T6', 'approved', ['T4']),
                          task('T7', 'approved'), task('T8', 'running'), task('T9', 'candidate_ready'),
                          task('T10', 'cancelled'))
        other = overview.build_snapshot([dict(plan(task('A1')), plan_id='Plan-2')], registered_keys=KEYS)
        source['plans'] += other['plans']
        decisions = md.suggest_decisions(source, observation_id=1)
        self.assertEqual(len(decisions), 11)
        self.assertEqual([d['reason_code'] for d in decisions], [
            'TERMINAL', 'TASK_FAILED', 'HUMAN_REQUIRED', 'APPROVAL_REQUIRED', 'HELD',
            'DEPENDENCIES_PENDING', 'QUEUED', 'STATE_UNAVAILABLE', 'HUMAN_REQUIRED',
            'TERMINAL', 'APPROVED_READY'])
        for value in decisions:
            self.assertTrue(self.validate(value, source)['accepted'])

    def assert_candidates_match_runner(self, original, expected):
        source = overview.build_snapshot([original], registered_keys=KEYS)
        before = copy.deepcopy((original, source))
        selected_before = copy.deepcopy(wr._eligible_task(original))
        decisions = md.suggest_decisions(source, observation_id=1)
        self.assertEqual([d['task_id'] for d in decisions if d['kind'] == 'PROPOSE_START'], expected)
        self.assertEqual(expected, [selected_before['task_id']] if selected_before else [])
        for decision in decisions:
            self.assertTrue(self.validate(decision, source)['accepted'])
            if decision['task_id'] not in expected:
                forged = dict(decision, kind='PROPOSE_START', reason_code='APPROVED_READY')
                self.assertEqual(self.validate(forged, source)['code'], 'STATE_CONFLICT')
        self.assertEqual(wr._eligible_task(original), selected_before)
        self.assertEqual((original, source), before)
        return decisions

    def test_only_first_ready_approved_task_is_start_candidate(self):
        decisions = self.assert_candidates_match_runner(plan(task('T1'), task('T2')), ['T1'])
        self.assertEqual((decisions[1]['kind'], decisions[1]['reason_code']), ('WAIT', 'QUEUED'))
        self.assert_candidates_match_runner(plan(task('T2'), task('T1')), ['T2'])

    def test_pending_dependency_is_skipped_for_later_ready_task(self):
        decisions = self.assert_candidates_match_runner(
            plan(task('T1', deps=['D1']), task('T2'), task('D1', 'proposed')), ['T2'])
        self.assertEqual((decisions[0]['kind'], decisions[0]['reason_code']), ('WAIT', 'DEPENDENCIES_PENDING'))

    def test_plan_blockers_prevent_all_start_candidates(self):
        for status in ('running', 'failed', 'needs_human', 'candidate_ready'):
            for tasks in ((task('B1', status), task('T1'), task('T2')),
                          (task('T1'), task('T2'), task('B1', status))):
                with self.subTest(status=status, first=tasks[0]['task_id']):
                    self.assert_candidates_match_runner(plan(*tasks), [])

    def test_proposals_do_not_change_runner_permission_or_execute(self):
        original = plan(task('T1'), task('T2'))
        source = overview.build_snapshot([original], registered_keys=KEYS)
        kwargs = dict(global_config=auto.AutoModeConfig(enabled=False),
                      runner_config=wr.WorkflowRunnerConfig(), today='2026-10-21',
                      resolve_repo_dir=lambda _: None, busy_fn=lambda _: True,
                      repo_run_blocked_fn=lambda _: True)
        before = wr.plan_start_block_reason(original, **kwargs)
        with patch.object(wr, 'plan_start_block_reason', side_effect=AssertionError), \
             patch.object(wr, 'run_workflow_runner_once', side_effect=AssertionError), \
             patch.object(wr, '_start_eligible_task', side_effect=AssertionError), \
             patch.object(wr, '_set_task_status', side_effect=AssertionError), \
             patch('subprocess.Popen', side_effect=AssertionError):
            decisions = md.suggest_decisions(source, observation_id=1)
            self.assertEqual(decisions[0]['kind'], 'PROPOSE_START')
            self.assertTrue(self.validate(decisions[0], source)['accepted'])
        self.assertEqual(wr.plan_start_block_reason(original, **kwargs), before)
        self.assertEqual(before.code, wr.START_BLOCK_GLOBAL_OFF)
        self.assertTrue(all(t['status'] == 'approved' for t in original['tasks']))

    def test_confirmed_running_is_wait(self):
        source = overview.build_snapshot([plan(task('T1', 'running'))], registered_keys=KEYS,
            associations={('Plan-1', 'T1'): {'run_id': RID}},
            observations={RID: {'record': {'run_id': RID, 'stage': 'testing'}, 'liveness': 'running'}})
        value = self.decision(source)
        self.assertEqual((value['kind'], value['reason_code']), ('WAIT', 'TASK_ACTIVE'))
        self.assertTrue(self.validate(value, source)['accepted'])

    def test_empty_unavailable_plans_never_invent_decisions(self):
        source = overview.build_snapshot([None], registered_keys=KEYS)
        self.assertEqual(md.suggest_decisions(source, observation_id=1), [])
        self.assertEqual(md.build_manager_input(source, observation_id=1)['plans'][0]['availability'], 'unavailable')

    def test_input_projection_and_fingerprint(self):
        source = snapshot(task('T1'), task('T2', 'held'))
        source['plans'][0]['tasks'][0].update(body='SECRET', path='C:/SECRET', exception='SECRET')
        before = copy.deepcopy(source)
        context = md.build_manager_input(source, observation_id=1)
        self.assertNotIn('SECRET', json.dumps(context))
        self.assertEqual(source, before)
        self.assertEqual(len(context['snapshot_id']), 64)
        self.assertEqual(context, md.build_manager_input(source, observation_id=1))
        self.assertNotEqual(context['snapshot_id'], md.build_manager_input(source, observation_id=2)['snapshot_id'])
        context['plans'][0]['tasks'].clear()
        self.assertEqual(source, before)

    def test_stale_state_generation_roles_and_run(self):
        source = snapshot(task('T1'))
        value = self.decision(source)
        self.assertEqual(md.validate_ai_response(json.dumps(value), source, observation_id=2)['code'], 'STALE_SNAPSHOT')
        for replacement in (snapshot(task('T1', 'held')), snapshot(task('T1', 'failed'))):
            self.assertEqual(self.validate(value, replacement)['code'], 'STALE_SNAPSHOT')
        source['plans'][0]['tasks'][0]['main_ai'] = 'codex'
        self.assertEqual(self.validate(value, source)['code'], 'STALE_SNAPSHOT')

    def test_strict_json_schema_and_unknown_commands(self):
        source = snapshot(task('T1'))
        valid = self.decision(source)
        for text in ('{}', '[]', 'null', '{', 'NaN', json.dumps(valid)[:-1] + ',"kind":"WAIT"}', 'x' * 16001):
            self.assertFalse(md.validate_ai_response(text, source, observation_id=1)['accepted'])
        for field, value in [('kind', 'RUN'), ('reason_code', 'run shell'), ('task_id', 'missing'),
                             ('plan_id', 'other'), ('change', {'command': 'PUSH'}), ('kind', []),
                             ('reason_code', {}), ('task_id', '../path')]:
            bad = dict(valid, **{field: value})
            self.assertFalse(self.validate(bad, source)['accepted'])
        for extra in ('command', 'repo_key', 'path', 'permissions', 'body', 'exception'):
            self.assertEqual(self.validate(dict(valid, **{extra: 'SECRET'}), source)['code'], 'INVALID_SCHEMA')

    def test_state_conflicting_and_wrong_reason(self):
        source = snapshot(task('T1', 'landed'))
        value = self.decision(source)
        for kind, reason in [('PROPOSE_START', 'APPROVED_READY'), ('WAIT', 'TASK_ACTIVE'), ('NO_ACTION', 'TASK_FAILED')]:
            self.assertEqual(self.validate(dict(value, kind=kind, reason_code=reason), source)['code'], 'STATE_CONFLICT')

    def change(self, source, op='hold'):
        return dict(self.decision(source), kind='PROPOSE_TASK_CHANGE', reason_code='WORKFLOW_CHANGE',
            change=dict(plan_id='Plan-1', base_revision=0, ops=[dict(op=op, task_id='T1')]))

    def test_workflow_changes_delegate_preview_manager_and_preserve_source(self):
        for status, op in [('approved', 'hold'), ('held', 'release'), ('failed', 'cancel')]:
            original = plan(task('T1', status))
            source = overview.build_snapshot([original], registered_keys=KEYS)
            value = self.change(source, op)
            before = copy.deepcopy((original, source, value))
            with patch.object(wf, 'preview_proposal', wraps=wf.preview_proposal) as preview:
                result = self.validate(value, source, workflow_plans=[original], registered_keys=KEYS)
                self.assertTrue(result['accepted'])
                self.assertEqual(preview.call_args.kwargs['actor'], 'manager')
            self.assertEqual((original, source, value), before)
            result['decision']['change']['ops'].clear()
            self.assertEqual((original, source, value), before)

    def test_workflow_missing_stale_conflict_and_locked(self):
        source = snapshot(task('T1'))
        value = self.change(source)
        self.assertEqual(self.validate(value, source)['code'], 'WORKFLOW_CONTEXT_REQUIRED')
        original = plan(task('T1'))
        value['change']['base_revision'] = 2
        self.assertEqual(self.validate(value, source, workflow_plans=[original], registered_keys=KEYS)['code'], 'INVALID_WORKFLOW')
        value['change']['base_revision'] = 0
        original['tasks'][0]['status'] = 'held'
        self.assertEqual(self.validate(value, source, workflow_plans=[original], registered_keys=KEYS)['code'], 'STATE_CONFLICT')
        original = plan(task('T1', 'landed'))
        source = overview.build_snapshot([original], registered_keys=KEYS)
        self.assertEqual(self.validate(self.change(source), source, workflow_plans=[original], registered_keys=KEYS)['code'], 'INVALID_WORKFLOW')

    def test_unsupported_changes_never_grant_approval(self):
        source = snapshot(task('T1', 'proposed'))
        for op in ('approve', 'add_task', 'update_body', 'set_depends_on', 'move', 'RUN', 'permissions'):
            self.assertEqual(self.validate(self.change(source, op), source)['code'], 'UNSUPPORTED_CHANGE')
        value = self.change(source)
        value['change']['ops'][0]['path'] = 'C:/SECRET'
        result = self.validate(value, source)
        self.assertEqual(result, dict(accepted=False, code='INVALID_SCHEMA', decision=None))

    def test_invalid_snapshot_and_dependencies_fail_closed(self):
        for source in (None, {}, {'schema_version': True}):
            self.assertEqual(md.validate_ai_response('{}', source, observation_id=1)['code'], 'INVALID_SNAPSHOT')
        base = snapshot(task('T1'), task('T2', 'approved', ['T1']))
        for field, value in [('status', 'completed'), ('main_ai', 'SECRET'), ('task_id', '../SECRET'),
                             ('category', 'completed'), ('run', {}), ('dependencies', []), ('status', [])]:
            source = copy.deepcopy(base)
            source['plans'][0]['tasks'][1][field] = value
            self.assertFalse(md.validate_ai_response('{}', source, observation_id=1)['accepted'])
        source = copy.deepcopy(base)
        source['plans'][0]['tasks'][1]['dependencies'][0]['status'] = 'landed'
        self.assertFalse(md.validate_ai_response('{}', source, observation_id=1)['accepted'])

    def test_cycles_duplicate_identity_and_inconsistent_collection(self):
        base = snapshot(task('T1'), task('T2'))
        for edit in ('cycle', 'duplicate', 'collection'):
            source = copy.deepcopy(base)
            tasks = source['plans'][0]['tasks']
            if edit == 'cycle':
                tasks[0]['dependencies'] = [dict(task_id='T2', status='approved')]
                tasks[1]['dependencies'] = [dict(task_id='T1', status='approved')]
                for t in tasks:
                    t['dependency_state'] = 'waiting'
            elif edit == 'duplicate':
                tasks[1]['task_id'] = 'T1'
            else:
                source['availability'] = 'unavailable'
            self.assertEqual(md.validate_ai_response('{}', source, observation_id=1)['code'], 'INVALID_SNAPSHOT')

    def test_no_storage_or_external_calls(self):
        source = snapshot(task('T1'))
        original = plan(task('T1'))
        value = self.change(source)
        with patch('builtins.open', side_effect=AssertionError), \
             patch('subprocess.Popen', side_effect=AssertionError), \
             patch.object(wf, 'save_plan', side_effect=AssertionError), \
             patch.object(wf, 'update_plan', side_effect=AssertionError):
            self.assertTrue(self.validate(value, source, workflow_plans=[original], registered_keys=KEYS)['accepted'])
            self.assertEqual(self.decision(source)['kind'], 'PROPOSE_START')


if __name__ == '__main__':
    unittest.main()
