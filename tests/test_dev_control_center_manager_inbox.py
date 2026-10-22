"""Read-only inbox tests: fake data/widgets/scheduling, no AI or real Tk."""
import copy
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.dev_control_center import manager_inbox as inbox
from scripts.dev_control_center import manager_decision as decision
from scripts.dev_control_center import manager_dashboard_view as dashboard
from scripts.dev_control_center import manager_dashboard_preview as preview
from scripts.dev_control_center import manager_overview as overview
from scripts.dev_control_center import workflow_runner as runner
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID
from tests.test_dev_control_center_manager_dashboard_view import Widget, FakeStyle
from tests.test_dev_control_center_manager_dashboard_preview import Scheduler, View


def snapshot(*tasks):
    return overview.build_snapshot([plan(*tasks)], registered_keys=KEYS)


def model(data, **kwargs):
    return inbox.build_inbox(data, observation_id=42, collection_status='available', **kwargs)


class GuardedTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target in ('tkinter.Tk', 'tkinter.Toplevel', 'subprocess.Popen', 'socket.socket',
                       'scripts.dev_control_center.manager_agent.ManagerAgent.infer',
                       'scripts.dev_control_center.workflow_plan.load_plan',
                       'scripts.dev_control_center.workflow_plan.save_plan',
                       'scripts.dev_control_center.workflow_plan.update_plan',
                       'scripts.dev_control_center.candidate.approve',
                       'scripts.dev_control_center.candidate.push',
                       'scripts.dev_control_center.candidate.run_dev',
                       'scripts.dev_control_center.provenance.build',
                       'scripts.dev_control_center.release_update.plan',
                       'tools.ai_orchestrator.orchestrator.start_run'):
            forbidden = stack.enter_context(patch(target, side_effect=AssertionError('FORBIDDEN')))
            self.addCleanup(forbidden.assert_not_called)


class ModelTests(GuardedTests):
    def test_causes_owners_priorities_and_stable_order(self):
        statuses = ('landed', 'cancelled', 'failed', 'needs_human', 'candidate_ready',
                    'proposed', 'held', 'running', 'approved')
        data = snapshot(*(task(f'T{i}', status) for i, status in enumerate(statuses)))
        before = copy.deepcopy(data)
        rows = model(data)['rows']
        self.assertEqual([r['task_id'] for r in rows], [f'T{i}' for i in range(len(statuses))])
        self.assertEqual([r['priority'] for r in rows], ['P4', 'P4', 'P1', 'P1', 'P2', 'P2', 'P3', 'PX', 'P3'])
        self.assertEqual([r['cause'] for r in rows], ['TERMINAL', 'TERMINAL', 'FAILED', 'HUMAN',
            'CANDIDATE', 'APPROVAL', 'HELD', 'UNKNOWN', 'QUEUED'])
        self.assertEqual([r['owner'] for r in rows], ['NONE', 'NONE', 'HUMAN', 'HUMAN', 'HUMAN',
            'HUMAN', 'HUMAN_CHECK', 'UNKNOWN', 'UNKNOWN'])
        self.assertEqual(data, before)

    def test_multiple_dependencies_and_single_runner_candidate(self):
        data = snapshot(task('T1', deps=['T3', 'T4']), task('T2'), task('T3', 'held'), task('T4', 'landed'))
        rows = model(data)['rows']
        self.assertEqual((rows[0]['cause'], rows[0]['owner'], rows[0]['priority']), ('DEPENDENCY', 'DEPENDENCY', 'P3'))
        self.assertEqual(rows[0]['dependencies'], [dict(task_id='T3', status='held'), dict(task_id='T4', status='landed')])
        self.assertEqual((rows[1]['cause'], rows[1]['owner']), ('START', 'START_CHECK'))
        self.assertEqual([r['task_id'] for r in rows if r['kind'] == 'PROPOSE_START'], ['T2'])

    def test_ai_setting_requires_confirmed_run_and_is_not_permission(self):
        for ai, owner in (('codex', 'AI_CODEX'), ('claude', 'AI_CLAUDE'), (None, 'UNKNOWN')):
            p = plan(dict(task('T1', 'running'), main_ai=ai))
            if ai is None:
                p['tasks'][0].pop('main_ai')
            data = overview.build_snapshot([p], registered_keys=KEYS,
                associations={('Plan-1', 'T1'): dict(run_id=RID)},
                observations={RID: dict(record=dict(run_id=RID, stage='testing'), liveness='running')})
            row = model(data, memory_available=True)['rows'][0]
            self.assertEqual((row['priority'], row['cause'], row['owner'], row['action']), ('P4', 'ACTIVE', owner, 'WAIT'))
            self.assertEqual(model(data)['rows'][0]['priority'], 'PX')
            data['plans'][0]['tasks'][0]['run']['liveness'] = 'unknown'
            self.assertEqual(model(data, memory_available=True)['status'], 'unavailable')
            self.assertEqual(inbox.analyze_task(data['plans'][0]['tasks'][0], 'TASK_ACTIVE', memory_available=True)['priority'], 'PX')
        data = snapshot(dict(task('T1'), main_ai='codex'))
        self.assertEqual(model(data)['rows'][0]['owner'], 'START_CHECK')

    def test_partial_and_unknown_analysis_are_unranked_no_free_text(self):
        result = inbox.build_inbox(snapshot(task('T1', 'failed')), observation_id=1, collection_status='partial')
        self.assertEqual((result['rows'][0]['priority'], result['rows'][0]['cause']), ('PX', 'UNKNOWN'))
        raw = dict(priority='SECRET', cause=['SECRET'], owner='C:/private', action='SECRET',
                   dependencies=[dict(task_id='../SECRET', status='SECRET')])
        self.assertEqual(inbox.analysis_values(raw), ('PX', '状態を確定できない', '確認待ち', '不明'))
        self.assertNotIn('SECRET', inbox.dependency_text(raw))
        self.assertEqual(inbox.analyze_task(None, 'SECRET', memory_available=True)['priority'], 'PX')

    def test_classification_preserves_existing_decisions_and_input(self):
        data = snapshot(task('T1', 'landed'), task('T2', 'cancelled'), task('T3', 'failed'),
                        task('T4', 'needs_human'), task('T5', 'proposed'), task('T6', 'held'),
                        task('T7', 'running'), task('T8'))
        before = copy.deepcopy(data)
        result = model(data)
        self.assertEqual([r['category'] for r in result['rows']],
                         ['done', 'done', 'human', 'human', 'human', 'waiting', 'unknown', 'waiting'])
        suggestions = decision.suggest_decisions(data, observation_id=42)
        for row, suggested in zip(result['rows'], suggestions):
            for field in ('kind', 'reason_code', 'plan_id', 'task_id', 'snapshot_id'):
                self.assertEqual(row[field], suggested[field])
            self.assertEqual(set(row), {'plan_id', 'task_id', 'kind', 'reason_code', 'category',
                                        'source', 'snapshot_id', 'observation_id', 'priority',
                                        'cause', 'owner', 'action', 'dependencies', 'workflow_status', 'proposals'})
        self.assertEqual(data, before)

    def test_single_candidate_matches_runner_order_and_dependencies(self):
        for tasks, expected in (([task('T1'), task('T2')], 'T1'),
                                ([task('T1', deps=['T3']), task('T2'), task('T3', 'held')], 'T2')):
            with self.subTest(expected=expected):
                original = plan(*tasks)
                before = copy.deepcopy(original)
                rows = model(overview.build_snapshot([original], registered_keys=KEYS))['rows']
                self.assertEqual([r['task_id'] for r in rows if r['kind'] == 'PROPOSE_START'], [expected])
                self.assertEqual(runner._eligible_task(original)['task_id'], expected)
                self.assertEqual(original, before)
                if expected == 'T2':
                    self.assertEqual(rows[0]['reason_code'], 'DEPENDENCIES_PENDING')

    def test_plan_blockers_and_human_reasons(self):
        for status in ('running', 'failed', 'needs_human', 'candidate_ready'):
            with self.subTest(status=status):
                p = plan(task('T1', status), task('T2'))
                self.assertIsNone(runner._eligible_task(p))
                rows = model(overview.build_snapshot([p], registered_keys=KEYS))['rows']
                self.assertFalse(any(r['kind'] == 'PROPOSE_START' for r in rows))
                self.assertEqual(rows[1]['reason_code'], 'QUEUED')

    def test_partial_unreadable_plan_and_locatable_task_issue(self):
        data = overview.build_snapshot([plan(task('T1')), None], registered_keys=KEYS)
        result = inbox.build_inbox(data, observation_id=1, collection_status='partial')
        self.assertEqual(result['unavailable_plans'], 1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['category'], 'start_candidate')
        result = inbox.build_inbox(snapshot(task('T1'), task('T2')), observation_id=1,
            collection_status='partial', issues=[dict(plan_id='Plan-1', task_id='T1', code='SECRET')])
        self.assertEqual(result['rows'][0]['reason_code'], 'COLLECTION_PARTIAL')
        self.assertEqual(result['rows'][0]['category'], 'unknown')
        self.assertNotIn('SECRET', str(result))

    def test_global_partial_failure_and_malformed_data_are_unconfirmed(self):
        data = snapshot(task('T1'))
        result = inbox.build_inbox(data, observation_id=1, collection_status='partial')
        self.assertEqual(result['rows'][0]['category'], 'unknown')
        for bad in (None, {}, [], dict(data, schema_version=9), preview.UNAVAILABLE):
            self.assertEqual(model(bad)['status'], 'unavailable')
        for status in ('unavailable', None, [], 'SECRET'):
            result = inbox.build_inbox(data, observation_id=1, collection_status=status)
            self.assertEqual(result['rows'], [])
        self.assertEqual(inbox.empty_inbox([])['status'], 'unavailable')

    def test_multiple_plans_and_empty(self):
        other = dict(plan(task('T1')), plan_id='Plan-2')
        data = overview.build_snapshot([plan(task('T1')), other], registered_keys=KEYS)
        self.assertEqual([r['plan_id'] for r in model(data)['rows']], ['Plan-1', 'Plan-2'])
        empty = overview.build_snapshot([], registered_keys=KEYS)
        self.assertEqual(model(empty)['rows'], [])
        self.assertEqual(model(empty)['status'], 'available')

    def test_disk_running_is_unconfirmed_and_safe_display_drops_free_text(self):
        data = overview.build_snapshot([plan(task('T1', 'running'))], registered_keys=KEYS,
            associations={('Plan-1', 'T1'): dict(run_id=RID)},
            observations={RID: dict(record=dict(run_id=RID, stage='testing'), liveness='running')})
        safe, _ = preview.preview_data(dict(status='available', snapshot=data))
        self.assertEqual(model(safe)['rows'][0]['category'], 'unknown')
        self.assertEqual(model(data, memory_available=True)['rows'][0]['reason_code'], 'TASK_ACTIVE')
        secret = 'SECRET C:/private\nAI text'
        row = dict(plan_id=secret, task_id=secret, kind=secret, category=secret, reason_code=secret, body=secret)
        self.assertNotIn('SECRET', str(inbox.row_values(row)))
        self.assertNotIn('SECRET', inbox.inbox_summary(dict(rows=[row])))


class Notebook(Widget):
    def add(self, child, **kwargs):
        self.rows[kwargs['text']] = child


class WidgetTests(GuardedTests):
    def widgets(self):
        return SimpleNamespace(**{name: Widget for name in
            ('Frame', 'Label', 'LabelFrame', 'Treeview', 'Scrollbar')}, Notebook=Notebook, Style=FakeStyle)

    def test_select_refresh_clear_and_reopen_without_actions(self):
        with patch.object(inbox, 'ttk', self.widgets()):
            view = inbox.ManagerInboxView(Widget(), window=Widget())
            view.set_model(model(snapshot(task('T1'), task('T2', 'held'))))
            view.tree.selection_set('inbox-1')
            view._select()
            self.assertIn('TASK ID: T2', view.detail.options['text'])
            self.assertIn('確認優先度: P3', view.detail.options['text'])
            self.assertIn('原因: 保留状態', view.detail.options['text'])
            self.assertIn('対応先: 人間／確認待ち', view.detail.options['text'])
            self.assertIn('本体メモリ未確認', view.detail.options['text'])
            view.set_model(model(snapshot(task('T1'), task('T2', 'landed'))))
            self.assertIn('TERMINAL', view.detail.options['text'])
            self.assertIn('確認優先度: P4', view.detail.options['text'])
            self.assertNotIn('保留状態', view.detail.options['text'])
            view.set_model(inbox.empty_inbox('updating'))
            self.assertEqual(view.tree.rows, {})
            self.assertNotIn('TERMINAL', view.detail.options['text'])
            self.assertNotIn('確認優先度:', view.detail.options['text'])
            reopened = inbox.ManagerInboxView(Widget(), window=Widget())
            self.assertEqual(reopened.tree.rows, {})
            reopened.set_model(model(snapshot(task('T3'))))
            self.assertEqual(len(reopened.tree.rows), 1)

    def test_dashboard_opt_in_tabs_and_shared_theme(self):
        with patch.object(dashboard, 'tk', SimpleNamespace(Toplevel=Widget)), \
             patch.object(dashboard, 'ttk', self.widgets()), patch.object(inbox, 'ttk', self.widgets()), \
             patch.object(inbox, 'apply_table_theme') as theme:
            window = dashboard.ManagerDashboardWindow(Widget(), snapshot(task('T1')), inbox=True)
            self.assertIsInstance(window.inbox, inbox.ManagerInboxView)
            theme.assert_called_once()

    def test_both_tables_keep_scroll_wiring_across_refresh_resize_and_theme_change(self):
        style = FakeStyle()
        widgets = self.widgets()
        widgets.Style = lambda *args: style
        with patch.object(dashboard, 'tk', SimpleNamespace(Toplevel=Widget)), \
             patch.object(dashboard, 'ttk', widgets), patch.object(inbox, 'ttk', widgets):
            window = dashboard.ManagerDashboardWindow(Widget(), snapshot(task('T1')), inbox=True)
            self.assertEqual(set(window.notebook.rows), {'TASK一覧', '判断受信箱'})
            self.assertEqual(window.notebook.options['style'], 'Manager.TNotebook')
            for table in (window, window.inbox):
                self.assertEqual(table.horizontal.options['style'], 'Manager.Horizontal.TScrollbar')
                self.assertEqual(table.vertical.options['style'], 'Manager.Vertical.TScrollbar')
                # Standard ttk bindings and bidirectional fraction callbacks stay
                # intact; no custom wheel, drag or geometry implementation.
                self.assertEqual(table.horizontal.options['command'], table.tree.xview)
                self.assertEqual(table.vertical.options['command'], table.tree.yview)
                self.assertEqual(table.tree.options['xscrollcommand'], table.horizontal.set)
                self.assertEqual(table.tree.options['yscrollcommand'], table.vertical.set)
            for count in (0, 40, 1):
                data = snapshot(*(task(f'T{i}') for i in range(count)))
                window.set_snapshot(data)
                window.inbox.set_model(model(data))
                window.window.geometry('800x480')
                window._apply_theme()
                self.assertEqual(len(window.tree.rows), count)
                self.assertEqual(len(window.inbox.tree.rows), count)
            style.bg = '#ffffff'
            window._apply_theme()
            self.assertEqual(window.notebook.options['style'], 'TNotebook')
            for table in (window, window.inbox):
                self.assertEqual(table.horizontal.options['style'], 'Horizontal.TScrollbar')
                self.assertEqual(table.vertical.options['style'], 'Vertical.TScrollbar')
            style.bg = '#0f1419'
            window._apply_theme()
            self.assertEqual(window.inbox.vertical.options['style'], 'Manager.Vertical.TScrollbar')
            self.assertEqual(window.notebook.options['style'], 'Manager.TNotebook')
            self.assertEqual(len(style.elements), 13)


class ControllerTests(GuardedTests):
    def test_update_clears_stale_state_change_failure_and_reopen(self):
        views = []
        payloads = [dict(status='available', observation_id=1, snapshot=snapshot(task('T1'))),
                    dict(status='available', observation_id=2, snapshot=snapshot(task('T1', 'needs_human'))),
                    OSError('SECRET C:/private')]
        for run in range(2):
            view, scheduler, work = View(), Scheduler(), []
            view.inbox = Mock()
            collector = Mock()
            collector.collect.side_effect = payloads if run == 0 else [payloads[0]]
            controller = preview.PreviewController(view, collector=collector, scheduler=scheduler, launch=work.append)
            views.append(view)
            for index in range(3 if run == 0 else 1):
                if index:
                    scheduler.run(preview.INTERVAL_MS)
                self.assertEqual(view.inbox.set_model.call_args.args[0]['rows'], [])
                self.assertEqual(view.inbox.set_model.call_args.args[0]['status'], 'updating')
                controller.request_refresh()
                self.assertEqual(len(work), 1)
                calls = view.inbox.set_model.call_count
                work.pop()()
                self.assertEqual(view.inbox.set_model.call_count, calls)
                scheduler.run(preview.POLL_MS)
                result = view.inbox.set_model.call_args.args[0]
                if index < 2:
                    self.assertEqual(result['rows'][0]['category'], 'start_candidate' if index == 0 else 'human')
                else:
                    self.assertEqual(result['rows'], [])
                    self.assertEqual(result['status'], 'unavailable')
                self.assertNotIn('SECRET', str(result))
            controller.request_refresh()
            controller.close()
            calls = view.inbox.set_model.call_count
            work.pop()()
            controller._poll()
            self.assertEqual(view.inbox.set_model.call_count, calls)
            self.assertEqual(scheduler.jobs, {})
        self.assertIsNot(views[0].inbox, views[1].inbox)


if __name__ == '__main__':
    unittest.main()
