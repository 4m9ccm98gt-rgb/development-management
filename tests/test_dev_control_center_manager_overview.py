import copy
import json
import unittest
from unittest.mock import patch

from scripts.dev_control_center import manager_overview as overview
from scripts.dev_control_center import workflow_plan as wf

KEYS = {'sample-repo'}
RID = '20261021-123331-908753'
SECRET = 'PRIVATE body C:\\secret\\data\nAI output'


def task(tid, status='approved', deps=None):
    return dict(task_id=tid, title='修正', repo_key='sample-repo',
                body='対象リポジトリ: sample-repo\n## 受入条件\n- 正しい結果\n',
                status=status, depends_on=deps or [])


def plan(*tasks):
    return dict(plan_id='Plan-1', name='計画', revision=0, tasks=list(tasks))


class OverviewTests(unittest.TestCase):
    def snapshot(self, plans, **kwargs):
        return overview.build_snapshot(plans, registered_keys=KEYS, **kwargs)

    def test_statuses_dependencies_roles_and_no_mutation(self):
        source = [plan(task('T1', 'landed'), task('T2', deps=['T1']),
                       task('T3', 'failed'), task('T4', 'needs_human'),
                       task('T5', 'proposed'), task('T6', 'candidate_ready'),
                       task('T7', 'held'), task('T8', 'cancelled'), task('T9', deps=['T3']))]
        source[0]['tasks'][0].update(main_ai='claude', reviewer_ai='codex')
        before = copy.deepcopy(source)
        rows = self.snapshot(source)['plans'][0]['tasks']
        self.assertEqual([r['category'] for r in rows], [
            'completed', 'waiting', 'failed', 'needs_human', 'not_started',
            'needs_human', 'waiting', 'cancelled', 'waiting'])
        self.assertEqual(rows[1]['dependency_state'], 'satisfied')
        self.assertEqual(rows[-1]['dependencies'], [dict(task_id='T3', status='failed')])
        self.assertEqual(rows[-1]['dependency_state'], 'waiting')
        self.assertEqual(rows[0]['main_ai'], 'claude')
        self.assertIsNone(rows[1]['main_ai'])
        self.assertEqual(source, before)
        rows[0]['dependencies'].append({})
        self.assertEqual(source, before)

    def test_multiple_plans_and_partial_availability(self):
        other = plan(task('T2', 'landed'))
        other['plan_id'] = 'Plan-2'
        result = self.snapshot([plan(task('T1')), other, None])
        self.assertEqual(result['availability'], 'partial')
        self.assertEqual(result['plans'][1]['tasks'][0]['category'], 'completed')
        self.assertEqual(result['plans'][0]['tasks'][0]['plan_id'], 'Plan-1')

    def test_unavailable_collection_and_empty(self):
        self.assertEqual(self.snapshot(None)['availability'], 'unavailable')
        self.assertEqual(self.snapshot([])['availability'], 'available')

    def test_invalid_plans_fail_closed(self):
        base = plan(task('T1', 'landed'))
        bad_values = [None, {}, [], dict(base, tasks=None), dict(base, revision=True),
                      dict(base, plan_id='../private'), dict(base, tasks=[task('T1', SECRET)]),
                      plan(task('T1', deps=['missing'])), plan(task('T1', deps=['T1'])),
                      plan(task('T1'), task('T1')), plan(dict(task('T1'), repo_key='unknown')),
                      plan(dict(task('T1'), main_ai=SECRET))]
        for bad in bad_values:
            with self.subTest(bad=bad):
                result = self.snapshot([bad])
                self.assertEqual(result['plans'][0]['availability'], 'unavailable')
                self.assertEqual(result['plans'][0]['category'], 'check_required')
                self.assertEqual(result['plans'][0]['tasks'], [])
                self.assertNotIn(SECRET, json.dumps(result))

    def test_duplicate_plan_ids(self):
        result = self.snapshot([plan(task('T1')), plan(task('T2'))])
        self.assertTrue(all(p['availability'] == 'unavailable' for p in result['plans']))

    def test_body_and_metadata_are_not_exported(self):
        source = plan(task('T1'))
        source['tasks'][0]['body'] += '\n## 範囲外\n' + SECRET
        source['tasks'][0]['tests'] = 'private/path'
        result = json.dumps(self.snapshot([source]))
        self.assertNotIn('PRIVATE', result)
        self.assertNotIn('private/path', result)
        self.assertEqual(self.snapshot([source])['plans'][0]['availability'], 'available')

    def test_run_requires_association_matching_record_and_liveness(self):
        source = [plan(task('T1', 'running'))]
        assoc = {('Plan-1', 'T1'): dict(run_id=RID, reason=SECRET)}
        observation = {RID: dict(record=dict(run_id=RID, stage='testing', body=SECRET),
                                 liveness='running', reason=SECRET)}
        before = copy.deepcopy((source, assoc, observation))
        row = self.snapshot(source, associations=assoc, observations=observation)['plans'][0]['tasks'][0]
        self.assertEqual(row['category'], 'running')
        self.assertEqual(row['run']['stage'], 'testing')
        self.assertNotIn('PRIVATE', json.dumps(row))
        self.assertEqual((source, assoc, observation), before)
        for stage, live in [('testing', 'lost'), ('testing', 'unresponsive'),
                            ('completed', 'finished'), (SECRET, 'running'), ('testing', SECRET)]:
            observation[RID]['record']['stage'] = stage
            observation[RID]['liveness'] = live
            row = self.snapshot(source, associations=assoc, observations=observation)['plans'][0]['tasks'][0]
            self.assertEqual(row['category'], 'check_required')
            self.assertNotIn('PRIVATE', json.dumps(row))

    def test_malformed_associations_and_observations(self):
        for assoc in (None, [], {}, {'run_id': '../secret'}, {'run_id': RID}):
            for observation in (None, [], {}, {'record': {'run_id': 'wrong', 'stage': 'completed'}}):
                row = self.snapshot([plan(task('T1', 'running'))],
                    associations={('Plan-1', 'T1'): assoc}, observations={RID: observation})['plans'][0]['tasks'][0]
                self.assertEqual(row['category'], 'check_required')
                self.assertEqual(row['run']['availability'], 'unavailable')

    def test_run_quota_bucket_is_exposed_only_for_needs_human_stage(self):
        """DCC Task UI-D2 (C3): build_snapshot's own task['run'] carries quota_bucket/quota_label
        exactly as given for a needs_human stage, and never for any other stage (even if an
        observation maliciously sets them)."""
        source = [plan(task('T1', 'needs_human'))]
        assoc = {('Plan-1', 'T1'): dict(run_id=RID)}
        observation = {RID: dict(record=dict(run_id=RID, stage='needs_human'), liveness='finished',
                                 quota_bucket='quota_waiting', quota_label='使用枠待ち（再実行まで約15分）')}
        row = self.snapshot(source, associations=assoc, observations=observation)['plans'][0]['tasks'][0]
        self.assertEqual(row['run']['quota_bucket'], 'quota_waiting')
        self.assertEqual(row['run']['quota_label'], '使用枠待ち（再実行まで約15分）')
        # An unknown bucket word is never forwarded, even for a needs_human stage.
        observation[RID]['quota_bucket'] = 'SECRET'
        row = self.snapshot(source, associations=assoc, observations=observation)['plans'][0]['tasks'][0]
        self.assertIsNone(row['run']['quota_bucket'])
        self.assertEqual(row['run']['quota_label'], '')
        # A non-needs_human stage never exposes quota_bucket/quota_label, even if present.
        source2 = [plan(task('T1', 'running'))]
        observation2 = {RID: dict(record=dict(run_id=RID, stage='testing'), liveness='running',
                                  quota_bucket='quota_waiting', quota_label='使用枠待ち')}
        row2 = self.snapshot(source2, associations=assoc, observations=observation2)['plans'][0]['tasks'][0]
        self.assertIsNone(row2['run']['quota_bucket'])
        self.assertEqual(row2['run']['quota_label'], '')

    def test_no_storage_or_execution_calls(self):
        with patch.object(wf, 'load_plan', side_effect=AssertionError), \
             patch.object(wf, 'save_plan', side_effect=AssertionError), \
             patch('builtins.open', side_effect=AssertionError), \
             patch('subprocess.Popen', side_effect=AssertionError):
            self.assertEqual(self.snapshot([plan(task('T1'))])['availability'], 'available')


OTHER_RID = '20261021-123332-908753'
THIRD_RID = '20261021-123333-908753'


class TaskOriginTests(unittest.TestCase):
    """DCC Task UI-D1 (C1): 計画 for a plan-linked run_id, 報告 for a report-started run_id,
    依頼 for anything else, including anything unidentifiable."""

    def test_plan_wins_report_and_unknown_falls_back_to_request(self):
        self.assertEqual(overview.task_origin(RID, plan_run_ids={RID}, report_run_ids=set()),
                         overview.ORIGIN_PLAN)
        self.assertEqual(overview.task_origin(RID, plan_run_ids=set(), report_run_ids={RID}),
                         overview.ORIGIN_REPORT)
        self.assertEqual(overview.task_origin(RID, plan_run_ids=set(), report_run_ids=set()),
                         overview.ORIGIN_REQUEST)
        self.assertEqual(overview.task_origin(RID, plan_run_ids={RID}, report_run_ids={RID}),
                         overview.ORIGIN_PLAN)

    def test_non_string_or_unrecognized_run_id_is_a_request(self):
        for bad in (None, 123, [], {}):
            self.assertEqual(overview.task_origin(bad, plan_run_ids={RID}, report_run_ids={RID}),
                             overview.ORIGIN_REQUEST)
        self.assertEqual(overview.task_origin(OTHER_RID, plan_run_ids={RID}, report_run_ids={RID}),
                         overview.ORIGIN_REQUEST)

    def test_none_sets_never_raise(self):
        self.assertEqual(overview.task_origin(RID, plan_run_ids=None, report_run_ids=None),
                         overview.ORIGIN_REQUEST)


class RunningTasksTests(unittest.TestCase):
    """DCC Task UI-D1 (C2/C4): only RUNNING_STAGES rows with ALIVE_LIVENESS survive, each
    origin-tagged; terminal stages (completed/failed/stopped/needs_human), created and stopping
    never appear, and neither does a stage that merely looks active while its worker is not
    provably alive."""

    def test_filters_to_running_stages_and_tags_origin(self):
        all_runs = [
            dict(run_id=RID, stage='implementing', liveness='running', repo='sample-repo',
                 main_agent='claude', review_agent='codex'),
            dict(run_id=OTHER_RID, stage='testing', liveness='starting', repo='other-repo'),
            dict(run_id=THIRD_RID, stage='completed', liveness='finished', repo='sample-repo'),
        ]
        rows = overview.running_tasks(all_runs, plan_run_ids={RID}, report_run_ids={OTHER_RID})
        self.assertEqual({r['run_id'] for r in rows}, {RID, OTHER_RID})
        by_id = {r['run_id']: r for r in rows}
        self.assertEqual(by_id[RID]['origin'], overview.ORIGIN_PLAN)
        self.assertEqual(by_id[OTHER_RID]['origin'], overview.ORIGIN_REPORT)
        self.assertEqual(by_id[RID]['main_agent'], 'claude')

    def test_excludes_created_and_stopping_stages(self):
        for stage in ('created', 'stopping', 'needs_human', 'failed', 'stopped', 'completed', 'unknown', None):
            rows = overview.running_tasks([dict(run_id=RID, stage=stage, liveness='running')],
                                          plan_run_ids=set(), report_run_ids=set())
            self.assertEqual(rows, [])

    def test_excludes_lost_unresponsive_unknown_and_finished_liveness(self):
        """A saved stage that still looks active (e.g. 'testing') must not render as 動いている
        once the worker is lost, unresponsive, or its liveness cannot be determined -- a dead or
        unreachable worker is not a running task just because no one updated its stage field."""
        for live in ('lost', 'unresponsive', 'unknown', 'finished', None, 'not-a-liveness'):
            rows = overview.running_tasks([dict(run_id=RID, stage='testing', liveness=live)],
                                          plan_run_ids=set(), report_run_ids=set())
            self.assertEqual(rows, [], f'liveness={live!r} must not be shown as running')

    def test_malformed_entries_are_dropped_not_guessed(self):
        bad_entries = [None, [], {}, dict(run_id='not-a-run-id', stage='testing', liveness='running'),
                       dict(run_id=RID, liveness='running'), dict(stage='testing', liveness='running')]
        for entry in bad_entries:
            with self.subTest(entry=entry):
                self.assertEqual(overview.running_tasks([entry], plan_run_ids=set(), report_run_ids=set()), [])
        self.assertEqual(overview.running_tasks(None, plan_run_ids=set(), report_run_ids=set()), [])
        self.assertEqual(overview.running_tasks('not-a-list', plan_run_ids=set(), report_run_ids=set()), [])

    def test_duplicate_run_id_keeps_only_first(self):
        rows = overview.running_tasks(
            [dict(run_id=RID, stage='testing', liveness='running'),
             dict(run_id=RID, stage='reviewing', liveness='running')],
            plan_run_ids=set(), report_run_ids=set())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['stage'], 'testing')

    def test_repo_path_is_reduced_to_a_safe_name_or_dropped(self):
        rows = overview.running_tasks(
            [dict(run_id=RID, stage='testing', liveness='running', repo='C:\\dev\\sample-repo')],
            plan_run_ids=set(), report_run_ids=set())
        self.assertEqual(rows[0]['repo'], 'sample-repo')
        rows = overview.running_tasks(
            [dict(run_id=RID, stage='testing', liveness='running', repo=SECRET)],
            plan_run_ids=set(), report_run_ids=set())
        self.assertIsNone(rows[0]['repo'])
        self.assertNotIn('PRIVATE', json.dumps(rows))

    def test_invalid_main_or_review_agent_is_dropped(self):
        rows = overview.running_tasks(
            [dict(run_id=RID, stage='testing', liveness='running', main_agent=SECRET, review_agent='codex')],
            plan_run_ids=set(), report_run_ids=set())
        self.assertIsNone(rows[0]['main_agent'])
        self.assertEqual(rows[0]['review_agent'], 'codex')
        self.assertNotIn('PRIVATE', json.dumps(rows))

    def test_quota_waiting_run_is_included_despite_terminal_stage(self):
        """DCC Task UI-D2 (C1): a run tagged quota_bucket == QUOTA_WAITING upstream is kept even
        though its own stage (needs_human) and liveness (finished) are otherwise excluded."""
        rows = overview.running_tasks(
            [dict(run_id=RID, stage='needs_human', liveness='finished', repo='sample-repo',
                 quota_bucket='quota_waiting', quota_label='使用枠待ち（再実行まで約15分）')],
            plan_run_ids={RID}, report_run_ids=set())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['quota_bucket'], overview.QUOTA_WAITING)
        self.assertEqual(rows[0]['quota_label'], '使用枠待ち（再実行まで約15分）')
        self.assertEqual(rows[0]['origin'], overview.ORIGIN_PLAN)

    def test_quota_waiting_requires_the_exact_shape_or_is_excluded(self):
        base = dict(run_id=RID, stage='needs_human', liveness='finished', quota_bucket='quota_waiting',
                    quota_label='使用枠待ち（再実行まで約15分）')
        for bad in (dict(base, quota_bucket='manual_temporary'), dict(base, quota_bucket='manual_permanent'),
                    dict(base, quota_bucket=None), dict(base, liveness='running'),
                    dict(base, quota_label=''), dict(base, quota_label=None), dict(base, stage='failed')):
            self.assertEqual(overview.running_tasks([bad], plan_run_ids=set(), report_run_ids=set()), [],
                             f'must be excluded: {bad}')

    def test_manual_quota_buckets_do_not_appear_in_running_tasks(self):
        for bucket in ('manual_temporary', 'manual_permanent', None):
            rows = overview.running_tasks(
                [dict(run_id=RID, stage='needs_human', liveness='finished', quota_bucket=bucket,
                     quota_label='手動で再投入が必要')],
                plan_run_ids=set(), report_run_ids=set())
            self.assertEqual(rows, [])


if __name__ == '__main__':
    unittest.main()
