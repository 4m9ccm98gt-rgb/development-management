import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.dev_control_center import workflow_plan as wf
from tools.ai_orchestrator import taskspec


KEYS = {'sample-repo'}
BODY = '対象リポジトリ: sample-repo\n\n## 受入条件\n- 正しい結果が表示されること\n\n## 範囲外\n- 実行\n'


def task(tid='T1', **fields):
    return dict(task_id=tid, title='表示の修正', repo_key='sample-repo', body=BODY,
                depends_on=[], status='proposed', **fields)


def plan(*tasks):
    return dict(plan_id='Plan-1', name='開発計画', revision=0, tasks=list(tasks))


def proposal(p, *ops):
    return dict(plan_id=p['plan_id'], base_revision=p['revision'], ops=list(ops))


class WorkflowTests(unittest.TestCase):
    def apply(self, p, *ops, actor='human'):
        return wf.apply_proposal(p, proposal(p, *ops), actor=actor, registered_keys=KEYS)

    def validate(self, p):
        wf.validate_plan(p, registered_keys=KEYS)

    def test_roundtrip_and_corrupt_files_fail_closed(self):
        p = plan(task(tests='python -m unittest', main_ai='claude', reviewer_ai='codex'))
        with tempfile.TemporaryDirectory() as tmp:
            wf.save_plan(p, root=tmp, registered_keys=KEYS)
            self.assertEqual(wf.load_plan('Plan-1', root=tmp, registered_keys=KEYS), p)
            file = next(Path(tmp).glob('*.json'))
            for value in (b'{', b'\xff', b'[]', b'{}', b'null',
                          json.dumps(dict(p, revision=True)).encode()):
                file.write_bytes(value)
                with self.assertRaisesRegex(wf.WorkflowStorageError, '^WORKFLOW_STORAGE_ERROR$'):
                    wf.load_plan('Plan-1', root=tmp, registered_keys=KEYS)
            file.unlink()
            with self.assertRaises(wf.WorkflowStorageError):
                wf.load_plan('Plan-1', root=tmp, registered_keys=KEYS)

    def test_atomic_write_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = plan(task())
            wf.save_plan(p, root=tmp, registered_keys=KEYS)
            with patch.object(wf.os, 'replace', side_effect=OSError('private content')):
                with self.assertRaisesRegex(wf.WorkflowStorageError, '^WORKFLOW_STORAGE_ERROR$'):
                    wf.save_plan(dict(p, name='変更'), root=tmp, registered_keys=KEYS)
            self.assertEqual(wf.load_plan('Plan-1', root=tmp, registered_keys=KEYS), p)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_untrusted_fields_rejected(self):
        for field in ('task_id', 'title', 'repo_key', 'depends_on', 'main_ai', 'reviewer_ai'):
            for bad in ('../evil', 'C:\\evil', 'x;whoami', '$(whoami)', 'x\ny', 'x' * 1001, '', None, [], {}):
                with self.subTest(field=field, bad=bad):
                    t = task()
                    t[field] = [bad] if field == 'depends_on' else bad
                    with self.assertRaises(wf.WorkflowError):
                        self.validate(plan(t))
        for field, bad in (('repo_key', 'unregistered'), ('main_ai', 'human'),
                           ('reviewer_ai', 'other'), ('status', 'unknown')):
            t = task()
            t[field] = bad
            with self.assertRaises(wf.WorkflowError):
                self.validate(plan(t))

    def test_limits_types_and_duplicate_ids(self):
        for p in (plan(task(), task()), dict(plan(), revision=True),
                  dict(plan(), plan_id='../x'), dict(plan(), plan_id='x' * 33),
                  dict(plan(), name='x' * 81), plan(*(task(str(i)) for i in range(51)))):
            with self.assertRaises(wf.WorkflowError):
                self.validate(p)
        t = task()
        t['title'] = 'x' * 81
        with self.assertRaises(wf.WorkflowError):
            self.validate(plan(t))

    def test_body_contract_and_existing_taskspec_validator(self):
        with patch.object(taskspec, 'parse_spec_text', wraps=taskspec.parse_spec_text) as parser:
            self.validate(plan(task()))
            self.assertEqual(parser.call_count, 1)
        invalid = ('plain text', BODY.replace('sample-repo', 'other-repo'),
                   BODY.replace('- 正しい結果が表示されること', 'plain'),
                   BODY.replace('## 受入条件', '受入条件'),
                   BODY + '\n受入条件', BODY * 1000,
                   BODY.replace('## 受入条件\n', '## 受入条件\n' + '\n' * 40),
                   '対象リポジトリ: sample-repo\n## 受入条件\n' + '- 条件です\n' * 21,
                   '対象リポジトリ: sample-repo\n## 受入条件\n- ' + '字' * 1001)
        for body in invalid:
            with self.subTest(body=body[:40]):
                t = task()
                t['body'] = body
                with self.assertRaises(wf.WorkflowError):
                    self.validate(plan(t))

    def test_new_tasks_are_only_proposed(self):
        for op in ('add_task', 'insert_after'):
            for status in wf.STATUSES:
                p = plan(task('A'))
                t = task('B')
                t['status'] = status
                raw = dict(op=op, task=t)
                if op == 'insert_after':
                    raw['after'] = 'A'
                if status == 'proposed':
                    result, _ = self.apply(p, raw)
                    self.assertEqual(result['tasks'][1]['status'], 'proposed')
                else:
                    with self.assertRaises(wf.WorkflowError):
                        self.apply(p, raw)
        t = task()
        del t['status']
        result, _ = self.apply(plan(), dict(op='add_task', task=t))
        self.assertEqual(result['tasks'][0]['status'], 'proposed')

    def test_author_is_never_authority(self):
        p = plan(task())
        op = dict(op='approve', task_id='T1')
        with self.assertRaisesRegex(wf.WorkflowError, 'WORKFLOW_HUMAN_REQUIRED'):
            self.apply(p, op, actor='manager')
        forged = proposal(p, op)
        forged['author'] = 'human'
        with self.assertRaises(wf.WorkflowError):
            wf.apply_proposal(p, forged, actor='manager', registered_keys=KEYS)
        with self.assertRaises(wf.WorkflowError):
            self.apply(p, dict(op, actor='human'), actor='manager')
        result, _ = self.apply(p, op)
        self.assertEqual(result['tasks'][0]['status'], 'approved')

    def test_transition_matrix(self):
        for op, (sources, destination) in wf.TRANSITIONS.items():
            for status in wf.STATUSES:
                p = plan(task())
                p['tasks'][0]['status'] = status
                if status in sources:
                    updated, _ = self.apply(p, dict(op=op, task_id='T1'))
                    self.assertEqual(updated['tasks'][0]['status'], destination)
                else:
                    with self.assertRaises(wf.WorkflowError):
                        self.apply(p, dict(op=op, task_id='T1'))

    def test_protected_tasks_cannot_be_modified_or_reordered(self):
        for status in ('running', 'candidate_ready', 'landed', 'cancelled'):
            p = plan(task('A'), task('B'), task('C'))
            p['tasks'][1]['status'] = status
            for op in (dict(op='move', task_id='B', after='C'),
                       dict(op='move', task_id='A', after='C'),
                       dict(op='cancel', task_id='B'), dict(op='approve', task_id='B'),
                       dict(op='hold', task_id='B'), dict(op='release', task_id='B'),
                       dict(op='update_body', task_id='B', body=BODY),
                       dict(op='set_depends_on', task_id='B', depends_on=['A'])):
                with self.subTest(status=status, op=op['op']):
                    with self.assertRaises(wf.WorkflowError):
                        self.apply(p, op)

    def test_dependencies_rejected_atomically(self):
        p = plan(task('A'), task('B'))
        for deps in (['A'], ['missing'], ['B', 'B']):
            with self.assertRaises(wf.WorkflowError):
                self.apply(p, dict(op='set_depends_on', task_id='A', depends_on=deps))
        original = copy.deepcopy(p)
        with self.assertRaises(wf.WorkflowError):
            self.apply(p, dict(op='set_depends_on', task_id='A', depends_on=['B']),
                       dict(op='set_depends_on', task_id='B', depends_on=['A']))
        self.assertEqual(p, original)

    def test_insert_move_preview_and_diff_counts(self):
        p = plan(task('A'), task('C'))
        ops = (dict(op='insert_after', after='A', task=task('B')),
               dict(op='move', task_id='A', after='C'), dict(op='hold', task_id='C'))
        summary = wf.preview_proposal(p, proposal(p, *ops), actor='human', registered_keys=KEYS)
        result, applied_summary = self.apply(p, *ops)
        self.assertEqual([t['task_id'] for t in result['tasks']], ['B', 'C', 'A'])
        self.assertEqual(summary, applied_summary)
        self.assertEqual(summary, {
            'added': {'count': 1, 'task_ids': ['B']},
            'changed': {'count': 1, 'task_ids': ['C']},
            'deleted': {'count': 0, 'task_ids': []},
            'reordered': {'count': 2, 'task_ids': ['C', 'A']}})
        self.assertEqual(wf.diff_summary(result, plan(task('B')))['deleted'],
                         {'count': 2, 'task_ids': ['C', 'A']})
        self.assertEqual(p['revision'], 0)

    def test_stale_and_mid_operation_failure_leave_all_inputs_unchanged(self):
        p = plan(task())
        prop = proposal(p, dict(op='hold', task_id='T1'), dict(op='cancel', task_id='absent'))
        original = copy.deepcopy((p, prop))
        with self.assertRaises(wf.WorkflowError):
            wf.apply_proposal(p, prop, actor='human', registered_keys=KEYS)
        self.assertEqual((p, prop), original)
        prop['base_revision'] = 1
        with self.assertRaisesRegex(wf.WorkflowError, 'WORKFLOW_STALE'):
            wf.apply_proposal(p, prop, actor='human', registered_keys=KEYS)

    def test_revision_bounded_history_and_approval_invalidation(self):
        p = plan(task())
        for i in range(205):
            op = 'hold' if i % 2 == 0 else 'release'
            p, _ = self.apply(p, dict(op=op, task_id='T1'), actor='manager')
            self.assertEqual(p['revision'], i + 1)
        self.assertEqual(len(p['history']), 200)
        self.assertEqual(p['history'][0]['revision'], 6)
        for entry in p['history']:
            self.assertEqual(set(entry), {'revision', 'ops'})
            self.assertIn(entry['ops'], [[{'op': 'hold', 'task_id': 'T1'}],
                                         [{'op': 'release', 'task_id': 'T1'}]])
        p, _ = self.apply(p, dict(op='approve', task_id='T1'))
        p, _ = self.apply(p, dict(op='update_body', task_id='T1', body=BODY + '\n補足'))
        self.assertEqual(p['tasks'][0]['status'], 'proposed')
        with tempfile.TemporaryDirectory() as tmp:
            wf.save_plan(p, root=tmp, registered_keys=KEYS)
            self.assertEqual(wf.load_plan('Plan-1', root=tmp, registered_keys=KEYS), p)

    def test_history_cannot_contain_free_text(self):
        p = plan(task())
        p['revision'] = 1
        p['history'] = [{'revision': 1, 'ops': [{'op': 'hold', 'task_id': 'T1', 'body': BODY}]}]
        with self.assertRaises(wf.WorkflowError):
            self.validate(p)

    def test_safe_ids_cannot_escape_storage_and_ai_defaults_remain_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ('../escape', 'C:\\escape', 'x\ny', 'x' * 33):
                with self.assertRaises(wf.WorkflowError):
                    wf.load_plan(bad, root=tmp, registered_keys=KEYS)
            for name in ('CON', 'Plan', 'plan'):
                p = dict(plan(task()), plan_id=name)
                wf.save_plan(p, root=tmp, registered_keys=KEYS)
                self.assertEqual(wf.load_plan(name, root=tmp, registered_keys=KEYS), p)
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 3)
        p, _ = self.apply(plan(), dict(op='add_task', task=task()))
        self.assertNotIn('main_ai', p['tasks'][0])
        self.assertNotIn('reviewer_ai', p['tasks'][0])


if __name__ == '__main__':
    unittest.main()
