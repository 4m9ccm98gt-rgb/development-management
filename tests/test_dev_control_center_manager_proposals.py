"""Fake data and widgets only; inherited guards forbid AI/storage/process/network."""
import copy
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from scripts.dev_control_center import manager_inbox as inbox
from scripts.dev_control_center import manager_proposals as proposals
from scripts.dev_control_center import manager_decision as decision
from tests.test_dev_control_center_manager_inbox import GuardedTests, snapshot, model
from tests.test_dev_control_center_manager_overview import task, plan, KEYS, RID
from tests.test_dev_control_center_manager_dashboard_view import Widget
from scripts.dev_control_center import manager_overview as overview


class ProposalTests(GuardedTests):
    def test_state_actions_and_conditional_drafts(self):
        expected = dict(failed='INVESTIGATE_FAILURE', needs_human='REQUEST_HUMAN',
            candidate_ready='REVIEW_CANDIDATE', proposed='REQUEST_APPROVAL', held='CHECK_HOLD',
            approved='CHECK_START', landed='NO_FOLLOWUP', cancelled='NO_FOLLOWUP', running='CHECK_DATA')
        for status, code in expected.items():
            with self.subTest(status=status):
                row = model(snapshot(task('T1', status)))['rows'][0]
                items = row['proposals']
                self.assertEqual(items[0]['action_code'], code)
                self.assertTrue(proposals.validate_proposals(items, row))
                self.assertEqual(len(items), 2 if status in ('failed', 'needs_human') else 1)
                self.assertTrue(all(p['state'] != 'approved' for p in items))
                for p in items:
                    self.assertFalse(set(p) & {'body', 'ops', 'tests', 'base_revision', 'repo_key', 'acceptance'})
                    self.assertEqual(p['basis']['workflow_status'], status)

    def test_failure_draft_never_invents_root_cause_or_fix(self):
        row = model(snapshot(task('T1', 'failed')))['rows'][0]
        draft = row['proposals'][1]
        self.assertEqual(draft['proposal_type'], 'IMPROVEMENT_DRAFT')
        self.assertEqual(draft['state'], 'DRAFT_NEEDS_EVIDENCE')
        self.assertEqual(draft['required_checks'], ['FAILURE_EVIDENCE', 'DRAFT_CONTEXT'])
        text = proposals.proposal_text(row)
        self.assertIn('調査TASKの作成を検討', text)
        self.assertNotIn('コードを修正', text)
        self.assertNotIn('成功条件:', text)

    def test_dependencies_and_runner_order_unchanged(self):
        data = snapshot(task('T1', deps=['T3', 'T4']), task('T2'), task('T3', 'held'), task('T4', 'landed'))
        before = copy.deepcopy(data)
        rows = model(data)['rows']
        self.assertEqual(rows[0]['proposals'][0]['action_code'], 'CHECK_DEPENDENCIES')
        self.assertEqual(rows[0]['proposals'][0]['dependencies'], rows[0]['dependencies'])
        self.assertEqual(rows[0]['proposals'][1]['action_code'], 'CONSIDER_DEPENDENCIES')
        self.assertEqual(rows[1]['proposals'][0]['action_code'], 'CHECK_START')
        expected = decision.suggest_decisions(data, observation_id=42)
        self.assertEqual([r['kind'] for r in rows], [d['kind'] for d in expected])
        self.assertEqual(data, before)
        rows = model(snapshot(task('T1'), task('T2')))['rows']
        self.assertEqual([r['proposals'][0]['action_code'] for r in rows], ['CHECK_START', 'CHECK_PLAN'])

    def test_observed_running_and_terminal_suppress_drafts_and_modifications(self):
        data = overview.build_snapshot([plan(task('T1', 'running'))], registered_keys=KEYS,
            associations={('Plan-1', 'T1'): dict(run_id=RID)},
            observations={RID: dict(record=dict(run_id=RID, stage='testing'), liveness='running')})
        row = model(data, memory_available=True)['rows'][0]
        self.assertEqual([p['action_code'] for p in row['proposals']], ['WAIT_FOR_CHANGE'])
        self.assertEqual(row['proposals'][0]['state'], 'INFORMATION_ONLY')
        self.assertEqual(model(data)['rows'][0]['proposals'][0]['action_code'], 'CHECK_DATA')

    def test_partial_failure_only_requests_collection_confirmation(self):
        data = snapshot(task('T1', 'failed'), task('T2'))
        result = inbox.build_inbox(data, observation_id=1, collection_status='partial')
        for row in result['rows']:
            self.assertEqual(len(row['proposals']), 1)
            self.assertEqual(row['proposals'][0]['action_code'], 'CHECK_DATA')
            self.assertEqual(row['proposals'][0]['priority'], 'PX')
        self.assertEqual(inbox.build_inbox(data, observation_id=2, collection_status='unavailable')['rows'], [])

    def test_stable_identity_deduplication_and_observation_binding(self):
        data = snapshot(task('T1', 'failed'))
        before = copy.deepcopy(data)
        old = inbox.build_inbox(data, observation_id=1, collection_status='available')['rows'][0]
        new = inbox.build_inbox(data, observation_id=2, collection_status='available')['rows'][0]
        self.assertEqual([p['proposal_id'] for p in old['proposals']], [p['proposal_id'] for p in new['proposals']])
        self.assertNotEqual(old['snapshot_id'], new['snapshot_id'])
        self.assertFalse(proposals.validate_proposals(old['proposals'], new))
        self.assertEqual(proposals.build_proposals(new), proposals.build_proposals(new))
        self.assertEqual(len(set(p['proposal_id'] for p in new['proposals'])), len(new['proposals']))
        doubled = new['proposals'] * 2
        self.assertFalse(proposals.validate_proposals(doubled, new))
        changed = model(snapshot(task('T1', 'landed')))['rows'][0]
        self.assertFalse(proposals.validate_proposals(new['proposals'], changed))
        self.assertEqual(data, before)

    def test_tampering_unknown_values_and_extra_free_text_are_rejected(self):
        row = model(snapshot(task('T1', 'failed')))['rows'][0]
        for field, value in (('action_code', 'RUN_COMMAND'), ('body', 'SECRET C:/private'),
                             ('required_checks', ['SECRET']), ('owner_code', 'SECRET'),
                             ('observation_id', True), ('state', 'approved')):
            bad = copy.deepcopy(row)
            bad['proposals'][0][field] = value
            self.assertFalse(proposals.validate_proposals(bad['proposals'], row))
            self.assertNotIn('SECRET', proposals.proposal_text(bad))
        for key in ('plan_id', 'task_id', 'snapshot_id', 'observation_id', 'cause', 'reason_code'):
            bad = dict(row, **{key: ['SECRET']})
            self.assertEqual(proposals.build_proposals(bad), [])
        bad = dict(row, workflow_status='running')
        self.assertEqual(proposals.build_proposals(bad), [])

    def test_detail_updates_and_clears_without_real_widgets(self):
        widgets = SimpleNamespace(**{name: Widget for name in ('Frame', 'Label', 'Treeview', 'Scrollbar')})
        with patch.object(inbox, 'ttk', widgets):
            view = inbox.ManagerInboxView(Widget(), window=Widget())
            view.set_model(model(snapshot(task('T1', 'failed'))))
            view.tree.selection_set('inbox-0')
            view._select()
            self.assertIn('失敗原因を調査する', view.detail.options['text'])
            self.assertIn('提案の根拠: TASK_FAILED', view.detail.options['text'])
            view.set_model(model(snapshot(task('T1', 'landed'))))
            self.assertNotIn('失敗原因', view.detail.options['text'])
            self.assertIn('追加対応なし', view.detail.options['text'])
            for state in ('updating', 'unavailable'):
                view.set_model(inbox.empty_inbox(state))
                self.assertNotIn('対応アクション:', view.detail.options['text'])
                self.assertEqual(view.tree.rows, {})


if __name__ == '__main__':
    unittest.main()
