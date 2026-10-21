"""Only fakes and temporary directories; never access DCC's production roots."""
import copy
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.dev_control_center import manager_collector as mc
from scripts.dev_control_center import manager_decision as md
from scripts.dev_control_center import workflow_plan as wf
from scripts.dev_control_center import workflow_runner as wr
from tools.ai_orchestrator import runstate
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID

OTHER_RID = '20261021-123332-908753'
SECRET = 'SECRET C:\\private\\data\nAI output'


def observed(rid=RID, stage='testing', live='running'):
    return dict(record=dict(run_id=rid, stage=stage, body=SECRET), liveness=live, reason=SECRET)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        # Readers that touch production defaults and execution/writer APIs are forbidden.
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('subprocess.Popen', 'socket.socket',
                       'scripts.dev_control_center.workflow_plan.plans_root',
                       'scripts.dev_control_center.workflow_plan.save_plan',
                       'scripts.dev_control_center.workflow_plan.update_plan',
                       'scripts.dev_control_center.workflow_runner._save_record',
                       'scripts.dev_control_center.workflow_runner._refresh_hot_task',
                       'scripts.dev_control_center.workflow_runner._hot_record',
                       'scripts.dev_control_center.workflow_runner.run_workflow_runner_once',
                       'tools.ai_orchestrator.runstate.runs_root',
                       'tools.ai_orchestrator.runstate.write_json_atomic',
                       'tools.ai_orchestrator.runstate.reconcile_lost'):
            forbidden = self.stack.enter_context(patch(target, side_effect=AssertionError('FORBIDDEN')))
            self.addCleanup(forbidden.assert_not_called)

    def collector(self, plans=None, **kwargs):
        plans = plans if plans is not None else [plan(task('T1'))]
        by_id = {p['plan_id']: p for p in plans}
        defaults = dict(registered_keys=KEYS, list_plans=lambda: list(by_id),
            load_plan=lambda pid: copy.deepcopy(by_id[pid]), read_association=lambda pid, tid: None,
            inspect_run=lambda rid: observed(rid), next_observation=itertools.count(1).__next__)
        defaults.update(kwargs)
        return mc.ManagerCollector(**defaults)

    def test_all_saved_plans_without_auto_permission_and_safe_output(self):
        first = plan(task('T1'), task('T2', 'held'))
        first['tasks'][0]['body'] += '\n## 範囲外\n' + SECRET
        second = dict(plan(task('T3', 'landed')), plan_id='Plan-2', revision=4)
        collector = self.collector([first, second])
        payload = collector.collect()
        self.assertEqual(payload['status'], 'available')
        self.assertIsNotNone(payload['manager_input'])
        self.assertEqual([p['plan_id'] for p in payload['snapshot']['plans']], ['Plan-1', 'Plan-2'])
        self.assertEqual(payload['revisions'], [dict(plan_id='Plan-1', revision=0), dict(plan_id='Plan-2', revision=4)])
        self.assertNotIn('SECRET', json.dumps(payload))
        self.assertNotIn('body', json.dumps(payload))
        self.assertEqual(payload['snapshot_id'], md.build_manager_input(payload['snapshot'], observation_id=1)['snapshot_id'])

    def test_hot_run_wins_without_reading_disk_and_never_writes(self):
        state = wr.WorkflowRunnerState()
        state.remember_run('Plan-1', 'T1', run_id=RID, reason=SECRET)
        disk = Mock(return_value={'run_id': OTHER_RID})
        inspector = Mock(side_effect=lambda rid: observed(rid))
        collector = self.collector([plan(task('T1', 'running'))], runner_state=state,
                                   read_association=disk, inspect_run=inspector)
        before = state.hot_run('Plan-1', 'T1')
        result = collector.collect()
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['snapshot']['plans'][0]['tasks'][0]['run']['run_id'], RID)
        disk.assert_not_called()
        self.assertEqual(state.hot_run('Plan-1', 'T1'), before)
        self.assertTrue(all(c.args == (RID,) for c in inspector.call_args_list))
        self.assertNotIn('SECRET', str(result))

    def test_no_memory_record_falls_back_to_disk(self):
        disk = Mock(return_value={'run_id': RID})
        result = self.collector([plan(task('T1', 'running'))], runner_state=wr.WorkflowRunnerState(),
                                read_association=disk).collect()
        self.assertEqual(result['status'], 'available')
        self.assertEqual(disk.call_count, 2)

    def test_invalid_memory_does_not_fall_back_to_disk(self):
        state = Mock()
        state.hot_run.return_value = {'run_id': '../SECRET'}
        disk = Mock(return_value={'run_id': RID})
        result = self.collector([plan(task('T1', 'running'))], runner_state=state, read_association=disk).collect()
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['manager_input'])
        self.assertEqual(result['snapshot']['plans'][0]['tasks'][0]['category'], 'check_required')
        disk.assert_not_called()
        self.assertNotIn('SECRET', str(result))

    def test_fixed_run_states_and_conflicts(self):
        for status, stage, live, expected in (
            ('running', 'testing', 'running', 'available'),
            ('running', 'created', 'starting', 'available'),
            ('candidate_ready', 'completed', 'finished', 'available'),
            ('failed', 'stopped', 'finished', 'available'),
            ('failed', 'failed', 'finished', 'available'),
            ('running', 'testing', 'lost', 'partial'),
            ('running', 'testing', 'unresponsive', 'partial'),
            ('running', 'testing', 'unknown', 'partial'),
            ('running', 'completed', 'finished', 'partial'),
            ('candidate_ready', 'testing', 'running', 'partial'),
            ('running', 'testing', 'finished', 'partial')):
            with self.subTest(status=status, stage=stage, live=live):
                result = self.collector([plan(task('T1', status))],
                    read_association=lambda *args: {'run_id': RID},
                    inspect_run=lambda rid: observed(rid, stage, live)).collect()
                self.assertEqual(result['status'], expected)
                self.assertNotIn('SECRET', str(result))

    def test_missing_corrupt_and_mismatched_run_never_normal(self):
        for assoc, obs in ((None, observed()), ({'run_id': 'C:/SECRET'}, observed()),
                           ({'run_id': RID}, None), ({'run_id': RID}, observed(OTHER_RID)),
                           ({'run_id': RID}, observed(stage=SECRET))):
            inspector = Mock(return_value=obs)
            result = self.collector([plan(task('T1', 'running'))],
                read_association=lambda *args: assoc, inspect_run=inspector).collect()
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['snapshot']['plans'][0]['tasks'][0]['category'], 'check_required')
            self.assertNotIn('SECRET', str(result))
            if assoc is None or assoc.get('run_id') != RID:
                inspector.assert_not_called()

    def test_list_failure_corruption_and_invalid_plan(self):
        broken = Mock(side_effect=OSError(SECRET))
        result = self.collector(list_plans=broken).collect()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['snapshot']['availability'], 'unavailable')
        result = self.collector(list_plans=lambda: ['Plan-1', None]).collect()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['snapshot']['availability'], 'partial')
        result = self.collector(load_plan=lambda pid: dict(plan(task('T1')), revision=True)).collect()
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('SECRET', str(result))

    def test_revision_or_body_change_during_read_discards_plan(self):
        for field in ('revision', 'body'):
            first = plan(task('T1'))
            changed = copy.deepcopy(first)
            if field == 'revision':
                changed['revision'] = 1
            else:
                changed['tasks'][0]['body'] += '\n## 範囲外\n' + SECRET
            reader = Mock(side_effect=[first, changed])
            result = self.collector(load_plan=reader).collect()
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['revisions'], [])
            self.assertEqual(result['snapshot']['plans'][0]['tasks'], [])
            self.assertIn('PLAN_CHANGED', [i['code'] for i in result['issues']])

    def test_list_run_and_association_changes_are_detected(self):
        collector = self.collector(list_plans=Mock(side_effect=[['Plan-1'], []]))
        self.assertEqual(collector.collect()['status'], 'unavailable')
        collector = self.collector([plan(task('T1', 'running'))],
            read_association=Mock(side_effect=[{'run_id': RID}, {'run_id': OTHER_RID}]))
        result = collector.collect()
        self.assertIn('ASSOCIATION_CHANGED', [i['code'] for i in result['issues']])
        collector = self.collector([plan(task('T1', 'running'))], read_association=lambda *args: {'run_id': RID},
            inspect_run=Mock(side_effect=[observed(), observed(stage='completed', live='finished')]))
        result = collector.collect()
        self.assertIn('RUN_CHANGED', [i['code'] for i in result['issues']])
        self.assertEqual(result['snapshot']['plans'][0]['tasks'][0]['category'], 'check_required')

    def test_duplicate_run_ownership_and_invalid_second_association(self):
        collector = self.collector([plan(task('T1', 'running'), task('T2', 'running'))],
            read_association=lambda *args: {'run_id': RID})
        self.assertIn('ASSOCIATION_CONFLICT', [i['code'] for i in collector.collect()['issues']])
        collector = self.collector(read_association=Mock(side_effect=[None, {'run_id': '../SECRET'}]))
        result = collector.collect()
        self.assertEqual(result['status'], 'partial')
        self.assertNotIn('SECRET', str(result))

    def test_invalid_list_and_inspector_exception_fail_closed(self):
        result = self.collector(list_plans=lambda: ['../SECRET']).collect()
        self.assertEqual(result['status'], 'unavailable')
        result = self.collector([plan(task('T1', 'running'))],
            read_association=lambda *args: {'run_id': RID},
            inspect_run=Mock(side_effect=OSError(SECRET))).collect()
        self.assertEqual(result['status'], 'partial')
        self.assertNotIn('SECRET', str(result))

    def test_generations_unique_and_reused_generation_rejected(self):
        collector = self.collector()
        first, second = collector.collect(), collector.collect()
        self.assertNotEqual(first['observation_id'], second['observation_id'])
        self.assertNotEqual(first['snapshot_id'], second['snapshot_id'])
        self.assertEqual(first['task_state_id'], second['task_state_id'])
        self.assertEqual(second['changes'], [])
        self.assertNotEqual(mc.ObservationClock()(), mc.ObservationClock()())
        collector = self.collector(next_observation=lambda: 1)
        collector.collect()
        result = collector.collect()
        self.assertIsNone(result['observation_id'])
        self.assertIn('GENERATION_UNAVAILABLE', [i['code'] for i in result['issues']])
        self.assertEqual(collector.revalidate('{}')['validation']['code'], 'COLLECTION_UNAVAILABLE')

    def test_components_distinguish_revision_task_run_changes(self):
        source = plan(task('T1', 'running'))
        run = observed()
        collector = self.collector([source], read_association=lambda *args: {'run_id': RID}, inspect_run=lambda rid: run)
        collector.collect()
        source['revision'] += 1
        self.assertEqual(collector.collect()['changes'], ['REVISION_CHANGED'])
        source['tasks'][0]['status'] = 'failed'
        run = observed(stage='failed', live='finished')
        changes = collector.collect()['changes']
        self.assertIn('TASK_STATE_CHANGED', changes)
        self.assertIn('RUN_STATE_CHANGED', changes)

    def test_revalidate_recollects_and_never_rebinds_old_decision(self):
        collector = self.collector()
        first = collector.collect()
        response = json.dumps(md.suggest_decisions(first['snapshot'], observation_id=first['observation_id'])[0])
        result = collector.revalidate(response)
        self.assertEqual(result['validation']['code'], 'STALE_SNAPSHOT')
        self.assertGreater(result['collection']['observation_id'], first['observation_id'])

    def test_failure_after_success_has_no_cached_fallback(self):
        reader = Mock(side_effect=[plan(task('T1')), plan(task('T1')), OSError(SECRET)])
        collector = self.collector(load_plan=reader)
        first = collector.collect()
        response = json.dumps(md.suggest_decisions(first['snapshot'], observation_id=first['observation_id'])[0])
        result = collector.revalidate(response)
        self.assertEqual(result['validation'], dict(accepted=False, code='COLLECTION_UNAVAILABLE', decision=None))
        self.assertEqual(result['collection']['snapshot']['plans'][0]['tasks'], [])
        self.assertNotIn('SECRET', str(result))

    def test_same_collection_plan_revision_and_workflow_preview_passed(self):
        original = plan(task('T1'))
        collector = self.collector([original])
        real = md.validate_ai_response
        def validate(text, snapshot, **kwargs):
            # Fake an AI reply tied to this very observation to exercise delegation.
            value = md.suggest_decisions(snapshot, observation_id=kwargs['observation_id'])[0]
            value.update(kind='PROPOSE_TASK_CHANGE', reason_code='WORKFLOW_CHANGE',
                change=dict(plan_id='Plan-1', base_revision=0, ops=[dict(op='hold', task_id='T1')]))
            return real(json.dumps(value), snapshot, **kwargs)
        before = copy.deepcopy(original)
        with patch.object(md, 'validate_ai_response', side_effect=validate), \
             patch.object(wf, 'preview_proposal', wraps=wf.preview_proposal) as preview:
            result = collector.revalidate('fake response')
        self.assertTrue(result['validation']['accepted'])
        self.assertEqual(preview.call_args.kwargs['actor'], 'manager')
        self.assertEqual(original, before)

    def test_default_readers_use_only_temporary_files_and_existing_inspect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plans, records, runs = root / 'plans', root / 'records', root / 'runs'
            plans.mkdir()
            original = plan(task('T1', 'candidate_ready'))
            wf._plan_path('Plan-1', plans).write_text(json.dumps(original), encoding='utf-8')
            path = wr._record_path('Plan-1', 'T1', root=records)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'run_id': RID}), encoding='utf-8')
            run_dir = runs / RID
            run_dir.mkdir(parents=True)
            (run_dir / 'run.json').write_text(json.dumps({'run_id': RID, 'stage': 'completed', 'body': SECRET}), encoding='utf-8')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            collector = mc.ManagerCollector(registered_keys=KEYS, plans_root=plans, records_root=records, runs_root=runs)
            with patch.object(runstate, 'inspect_run', wraps=runstate.inspect_run) as inspect:
                result = collector.collect()
            self.assertEqual(result['status'], 'available')
            self.assertEqual(inspect.call_count, 2)
            self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
            self.assertNotIn('SECRET', str(result))
            (plans / 'broken.json').write_text('{', encoding='utf-8')
            self.assertEqual(collector.collect()['status'], 'partial')
            (plans / 'broken.json').unlink()
            (plans / 'wrong-name.json').write_text(json.dumps(original), encoding='utf-8')
            self.assertEqual(collector.collect()['status'], 'partial')
            (plans / 'wrong-name.json').unlink()
            path.write_text('{', encoding='utf-8')
            self.assertEqual(collector.collect()['status'], 'partial')


if __name__ == '__main__':
    unittest.main()
