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
                       'scripts.dev_control_center.workflow_plan.apply_and_save_proposal',
                       'scripts.dev_control_center.workflow_runner._start_eligible_task',
                       'scripts.dev_control_center.candidate.approve',
                       'scripts.dev_control_center.candidate.push',
                       'scripts.dev_control_center.candidate.run_dev',
                       'scripts.dev_control_center.provenance.build',
                       'scripts.dev_control_center.release_update.plan',
                       'tools.ai_orchestrator.orchestrator.start_run',
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

    def test_quota_display_fn_flows_through_collect_for_a_plan_linked_task(self):
        """DCC Task UI-D2 (C3): the actual model-generation path for a Workflow-plan TASK (not a
        hand-built snapshot) -- a real RequeueState through orchestrator_requeue.quota_display,
        injected as quota_display_fn, reaching collect()'s own snapshot (and so 判断受信箱 /
        組織図, which both read snapshot['plans'][*]['tasks'][*]['run'] directly)."""
        from scripts.dev_control_center import orchestrator_requeue as requeue
        from datetime import datetime, timezone

        state = requeue.RequeueState()
        state.excluded_at_startup.add(RID)

        def quota_record(rid):
            return dict(record=dict(run_id=rid, stage='needs_human',
                                    final_result=dict(stage='needs_human', code='PROVIDER_QUOTA', message='')),
                       liveness='finished')

        result = self.collector([plan(task('T1', 'needs_human'))],
            read_association=lambda *args: {'run_id': RID}, inspect_run=quota_record,
            quota_display_fn=lambda record: requeue.quota_display(
                record, state=state, now=datetime(2026, 3, 10, 16, 50, 0, tzinfo=timezone.utc))
        ).collect()
        run = result['snapshot']['plans'][0]['tasks'][0]['run']
        self.assertEqual(run['quota_bucket'], 'manual_permanent')
        self.assertEqual(run['quota_label'], '手動で再投入が必要')

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

    def test_unchanged_response_accepted_against_original_issue_once(self):
        collector = self.collector()
        first = collector.collect()
        response = json.dumps(md.suggest_decisions(first['snapshot'], observation_id=first['observation_id'])[0])
        result = collector.revalidate(response)
        self.assertTrue(result['validation']['accepted'])
        self.assertEqual(result['validation']['decision']['snapshot_id'], first['snapshot_id'])
        self.assertGreater(result['collection']['observation_id'], first['observation_id'])
        self.assertEqual(collector.revalidate(response)['validation']['code'], 'OBSERVATION_UNKNOWN')

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
        issued = collector.collect()
        value = md.suggest_decisions(issued['snapshot'], observation_id=issued['observation_id'])[0]
        value.update(kind='PROPOSE_TASK_CHANGE', reason_code='WORKFLOW_CHANGE',
            change=dict(plan_id='Plan-1', base_revision=0, ops=[dict(op='hold', task_id='T1')]))
        before = copy.deepcopy(original)
        with patch.object(wf, 'preview_proposal', wraps=wf.preview_proposal) as preview:
            result = collector.revalidate(json.dumps(value))
        self.assertTrue(result['validation']['accepted'])
        self.assertEqual(preview.call_args.kwargs['actor'], 'manager')
        self.assertEqual(original, before)

    def response(self, issued):
        return json.dumps(md.suggest_decisions(issued['snapshot'], observation_id=issued['observation_id'])[0])

    def test_plan_content_revision_and_task_state_changes_rejected(self):
        for change in ('status', 'revision', 'body'):
            with self.subTest(change=change):
                original = plan(task('T1'))
                collector = self.collector([original])
                issued = collector.collect()
                if change == 'status':
                    original['tasks'][0]['status'] = 'held'
                elif change == 'revision':
                    original['revision'] += 1
                else:
                    original['tasks'][0]['body'] += '\n## 範囲外\n' + SECRET
                result = collector.revalidate(self.response(issued))
                self.assertEqual(result['validation']['code'], 'STATE_CHANGED')
                self.assertNotIn('SECRET', str(result))

    def test_run_stage_and_association_metadata_changes_rejected(self):
        for change in ('stage', 'liveness', 'association', 'candidate_sha'):
            with self.subTest(change=change):
                association = {'run_id': RID, 'candidate_sha': 'a' * 40}
                observation = observed()
                collector = self.collector([plan(task('T1', 'running'))],
                    read_association=lambda *args: association,
                    inspect_run=lambda rid: dict(observation, record=dict(observation['record'], run_id=rid)))
                issued = collector.collect()
                if change == 'stage':
                    observation['record']['stage'] = 'reviewing'
                elif change == 'liveness':
                    observation['liveness'] = 'starting'
                elif change == 'association':
                    association['run_id'] = OTHER_RID
                else:
                    association['candidate_sha'] = 'b' * 40
                self.assertEqual(collector.revalidate(self.response(issued))['validation']['code'], 'STATE_CHANGED')

    def test_new_collect_invalidates_old_and_unknown_response_consumes_issue(self):
        collector = self.collector()
        first = collector.collect()
        latest = collector.collect()
        self.assertEqual(collector.revalidate(self.response(first))['validation']['code'], 'STALE_SNAPSHOT')
        self.assertEqual(collector.revalidate(self.response(latest))['validation']['code'], 'OBSERVATION_UNKNOWN')
        another = self.collector()
        self.assertEqual(another.revalidate(self.response(first))['validation']['code'], 'OBSERVATION_UNKNOWN')

    def test_expiry_backward_invalid_clock_and_slow_collection(self):
        for times, expected in (([0, 10], 'OBSERVATION_EXPIRED'),
                                ([10, 9], 'OBSERVATION_EXPIRED'),
                                ([0, float('nan')], 'CLOCK_UNAVAILABLE'),
                                ([0, 9], 'ACCEPTED')):
            collector = self.collector(now=Mock(side_effect=times), max_age_seconds=10)
            issued = collector.collect()
            self.assertEqual(collector.revalidate(self.response(issued))['validation']['code'], expected)
        collector = self.collector(now=lambda: float('nan'))
        result = collector.collect()
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['manager_input'])

    def test_membership_change_and_invalid_attempt_revoke_issue(self):
        ids = ['Plan-1']
        collector = self.collector(list_plans=lambda: ids)
        issued = collector.collect()
        ids.clear()
        self.assertEqual(collector.revalidate(self.response(issued))['validation']['code'], 'STATE_CHANGED')
        issued = self.collector()
        observation = issued.collect()
        self.assertEqual(issued.revalidate('{}')['validation']['code'], 'INVALID_SCHEMA')
        self.assertEqual(issued.revalidate(self.response(observation))['validation']['code'], 'OBSERVATION_UNKNOWN')

    def test_returned_payload_mutation_cannot_change_issued_snapshot(self):
        collector = self.collector()
        issued = collector.collect()
        response = self.response(issued)
        issued['snapshot']['plans'].clear()
        self.assertTrue(collector.revalidate(response)['validation']['accepted'])

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


THIRD_RID = '20261021-123334-908753'
TERMINAL_RID = '20261021-123335-908753'


class CollectRunningTasksTests(unittest.TestCase):
    """DCC Task UI-D1 (C2/C3/C4): collect_running_tasks is independent of collect()/revalidate --
    display data only. Only RUNNING_STAGES survive, each tagged with its fixed-word 出どころ."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('subprocess.Popen', 'socket.socket',
                       'scripts.dev_control_center.workflow_plan.save_plan',
                       'scripts.dev_control_center.workflow_plan.update_plan',
                       'scripts.dev_control_center.workflow_runner._save_record',
                       'tools.ai_orchestrator.runstate.write_json_atomic',
                       'tools.ai_orchestrator.orchestrator.start_run'):
            forbidden = self.stack.enter_context(patch(target, side_effect=AssertionError('FORBIDDEN')))
            self.addCleanup(forbidden.assert_not_called)

    def collector(self, plans=None, **kwargs):
        plans = plans if plans is not None else [plan(task('T1'))]
        by_id = {p['plan_id']: p for p in plans}
        defaults = dict(registered_keys=KEYS, list_plans=lambda: list(by_id),
            load_plan=lambda pid: copy.deepcopy(by_id[pid]), read_association=lambda pid, tid: None,
            list_active_runs=lambda: [], report_run_ids=lambda: set(),
            inspect_run=lambda rid: observed(rid), next_observation=itertools.count(1).__next__)
        defaults.update(kwargs)
        return mc.ManagerCollector(**defaults)

    def test_tags_plan_report_and_request_origins_and_filters_terminal(self):
        all_runs = [
            dict(run_id=RID, stage='implementing', liveness='running', repo='sample-repo'),
            dict(run_id=OTHER_RID, stage='testing', liveness='running', repo='other-repo'),
            dict(run_id=THIRD_RID, stage='reviewing', liveness='starting', repo='sample-repo'),
            dict(run_id=TERMINAL_RID, stage='completed', liveness='finished', repo='sample-repo'),
        ]
        collector = self.collector([plan(task('T1'))], read_association=lambda pid, tid: {'run_id': RID},
            list_active_runs=lambda: all_runs, report_run_ids=lambda: {OTHER_RID})
        rows = collector.collect_running_tasks()
        by_run = {r['run_id']: r for r in rows}
        self.assertEqual(set(by_run), {RID, OTHER_RID, THIRD_RID})
        self.assertEqual(by_run[RID]['origin'], '計画')
        self.assertEqual(by_run[OTHER_RID]['origin'], '報告')
        self.assertEqual(by_run[THIRD_RID]['origin'], '依頼')

    def test_plan_association_read_through_hot_runner_state_counts_as_plan_origin(self):
        state = wr.WorkflowRunnerState()
        state.remember_run('Plan-1', 'T1', run_id=RID, reason='because')
        disk = Mock(return_value=None)
        collector = self.collector([plan(task('T1'))], runner_state=state, read_association=disk,
            list_active_runs=lambda: [dict(run_id=RID, stage='testing', liveness='running')])
        rows = collector.collect_running_tasks()
        self.assertEqual(rows[0]['origin'], '計画')
        disk.assert_not_called()

    def test_broken_plan_listing_never_raises_and_falls_back_to_request(self):
        collector = self.collector(list_plans=Mock(side_effect=OSError('broken')),
            list_active_runs=lambda: [dict(run_id=RID, stage='testing', liveness='running')])
        rows = collector.collect_running_tasks()
        self.assertEqual(rows[0]['origin'], '依頼')

    def test_broken_active_run_listing_or_report_lookup_never_raises(self):
        collector = self.collector(list_active_runs=Mock(side_effect=OSError('broken')))
        self.assertEqual(collector.collect_running_tasks(), [])
        collector = self.collector(list_active_runs=lambda: [dict(run_id=RID, stage='testing', liveness='running')],
            report_run_ids=Mock(side_effect=OSError('broken')))
        self.assertEqual(collector.collect_running_tasks()[0]['origin'], '依頼')

    def test_independent_of_collect_generation_and_revalidate(self):
        collector = self.collector(list_active_runs=lambda: [dict(run_id=RID, stage='testing', liveness='running')])
        first = collector.collect()
        response = json.dumps(md.suggest_decisions(first['snapshot'], observation_id=first['observation_id'])[0])
        collector.collect_running_tasks()  # must not consume the generation or revoke the pending issue
        self.assertTrue(collector.revalidate(response)['validation']['accepted'])
        second = collector.collect()
        self.assertEqual(second['observation_id'], first['observation_id'] + 2)  # +1 from revalidate's own collect
        self.assertEqual(collector.collect_running_tasks(), collector.collect_running_tasks())

    def test_default_readers_use_only_temporary_files_and_never_write(self):
        from scripts.dev_control_center import reports_auto_start as auto_start
        import time as time_module
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plans, records, runs, reports = root / 'plans', root / 'records', root / 'runs', root / 'reports'
            plans.mkdir()
            wf._plan_path('Plan-1', plans).write_text(json.dumps(plan(task('T1'))), encoding='utf-8')
            assoc_path = wr._record_path('Plan-1', 'T1', root=records)
            assoc_path.parent.mkdir(parents=True)
            assoc_path.write_text(json.dumps({'run_id': RID}), encoding='utf-8')
            # No worker/heartbeat recorded, so inspect_run reports 'starting' liveness as long as
            # created_at is within STARTING_GRACE_SECONDS -- enough to prove liveness flows through.
            created_at = time_module.strftime('%Y-%m-%dT%H:%M:%S', time_module.localtime())
            for rid, stage, repo in ((RID, 'implementing', 'sample-repo'), (OTHER_RID, 'testing', 'other-repo')):
                run_dir = runs / rid
                run_dir.mkdir(parents=True)
                (run_dir / 'run.json').write_text(
                    json.dumps({'run_id': rid, 'stage': stage, 'repo': repo, 'created_at': created_at}),
                    encoding='utf-8')
            auto_start._save_record(auto_start.AutoStartRecord('app', 'r1', '2026-01-01T00:00:00Z', OTHER_RID),
                                    root=reports)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            collector = mc.ManagerCollector(registered_keys=KEYS, plans_root=plans, records_root=records,
                runs_root=runs, report_run_ids=lambda: auto_start.started_run_ids(root=reports))
            rows = collector.collect_running_tasks()
            by_run = {r['run_id']: r for r in rows}
            self.assertEqual(set(by_run), {RID, OTHER_RID})
            self.assertEqual(by_run[RID]['origin'], '計画')
            self.assertEqual(by_run[OTHER_RID]['origin'], '報告')
            self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)

    def test_dead_worker_liveness_is_not_shown_as_running_even_though_stage_still_looks_active(self):
        """Repair regression: inspect_run's liveness must reach the running-tasks judgment -- a
        saved stage of 'testing' whose worker is lost/unresponsive/unknown must not render as
        動いている just because no one has rewritten the stage field yet. Uses the real default
        _active_runs_reader (runs_root points at a temp directory) with a fake inspect_run, per
        the reviewer's instruction to exercise this through fake inspect results."""
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            (runs / RID).mkdir()
            for live in ('lost', 'unresponsive', 'unknown'):
                with self.subTest(live=live):
                    collector = self.collector(runs_root=runs, list_active_runs=None,
                        inspect_run=lambda rid, live=live: observed(rid, stage='testing', live=live))
                    self.assertEqual(collector.collect_running_tasks(), [])
            for live in ('running', 'starting'):
                with self.subTest(live=live):
                    collector = self.collector(runs_root=runs, list_active_runs=None,
                        inspect_run=lambda rid, live=live: observed(rid, stage='testing', live=live))
                    rows = collector.collect_running_tasks()
                    self.assertEqual([r['run_id'] for r in rows], [RID])

    def test_quota_display_fn_flows_through_the_real_active_runs_reader(self):
        """DCC Task UI-D2 (C3): the actual model-generation path -- a real RequeueState through
        orchestrator_requeue.quota_display, injected as quota_display_fn, reaching
        collect_running_tasks()'s own output via the real default _active_runs_reader (not a
        hand-built row)."""
        from scripts.dev_control_center import orchestrator_requeue as requeue
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 3, 10, 16, 50, 0, tzinfo=timezone.utc)
        state = requeue.RequeueState()
        state.pending[RID] = requeue._Pending(
            scheduled_at=now + timedelta(minutes=15), lineage_root=RID, attempt=1)

        def quota_record(rid):
            return dict(record=dict(run_id=rid, stage='needs_human', repo='sample-repo',
                                    final_result=dict(stage='needs_human', code='PROVIDER_QUOTA', message='')),
                       liveness='finished')

        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            (runs / RID).mkdir()
            collector = self.collector(runs_root=runs, list_active_runs=None,
                inspect_run=quota_record,
                quota_display_fn=lambda record: requeue.quota_display(record, state=state, now=now))
            rows = collector.collect_running_tasks()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['run_id'], RID)
            self.assertEqual(rows[0]['quota_bucket'], 'quota_waiting')
            self.assertEqual(rows[0]['quota_label'], '使用枠待ち（再実行まで約15分）')

    def test_running_run_beyond_200_newer_finished_runs_still_appears(self):
        """Repair regression: a run-directory cap must not drop a still-running task just
        because 200+ newer runs have since finished. Uses the real default _active_runs_reader
        against a temp runs_root with 210 newer finished directories plus one older running one."""
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            old_rid = '20260101-000000-000001'
            (runs / old_rid).mkdir()
            newer_finished_ids = []
            for i in range(210):
                rid = f'20270101-{i:06d}-000000'
                (runs / rid).mkdir()
                newer_finished_ids.append(rid)
            observations = {old_rid: observed(old_rid, stage='testing', live='running')}
            for rid in newer_finished_ids:
                observations[rid] = observed(rid, stage='completed', live='finished')
            collector = self.collector(runs_root=runs, list_active_runs=None,
                inspect_run=lambda rid: observations[rid])
            rows = collector.collect_running_tasks()
            self.assertEqual([r['run_id'] for r in rows], [old_rid])


if __name__ == '__main__':
    unittest.main()
