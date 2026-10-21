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

    def test_no_storage_or_execution_calls(self):
        with patch.object(wf, 'load_plan', side_effect=AssertionError), \
             patch.object(wf, 'save_plan', side_effect=AssertionError), \
             patch('builtins.open', side_effect=AssertionError), \
             patch('subprocess.Popen', side_effect=AssertionError):
            self.assertEqual(self.snapshot([plan(task('T1'))])['availability'], 'available')


if __name__ == '__main__':
    unittest.main()
