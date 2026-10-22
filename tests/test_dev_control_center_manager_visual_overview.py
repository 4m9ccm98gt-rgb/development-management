"""Pure aggregation, fake Canvas and scheduler only. No real data or Tk."""
import copy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from scripts.dev_control_center import manager_visual_overview as visual
from scripts.dev_control_center import manager_dashboard_preview as preview
from scripts.dev_control_center import manager_inbox as inbox
from scripts.dev_control_center import manager_overview as overview
from tests.test_dev_control_center_manager_inbox import GuardedTests
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID
from tests.test_dev_control_center_manager_dashboard_view import snapshot, FakeCanvas, Widget, FakeStyle
from tests.test_dev_control_center_manager_dashboard_preview import Scheduler, View


def project(data, generation=1, memory=False, status='available', issues=()):
    safe, _ = preview.preview_data(dict(snapshot=data, status=status), memory_available=memory)
    box = inbox.build_inbox(safe, observation_id=generation, collection_status=status,
                            memory_available=memory, issues=issues)
    return visual.build_overview(safe, box, observation_id=generation, memory_available=memory)


class OverviewTests(GuardedTests):
    def test_kpis_distribution_priorities_proposals_and_no_mutation(self):
        data = snapshot()
        before = copy.deepcopy(data)
        result = project(data)
        self.assertEqual(result['kpis'], dict(total=7, running=0, human=3, completed=1,
                                             unavailable_plans=0, unavailable_tasks=1))
        self.assertEqual(result['distribution'], dict(not_started=1, waiting=1, running=0,
            needs_human=1, failed=1, completed=1, cancelled=1, unavailable=1))
        self.assertEqual(result['focus'], dict(P1=2, P2=1, P3=1, PX=1))
        self.assertEqual(result['proposals'], dict(check=4, draft=2, wait=2, data=1))
        self.assertEqual(result['projects'][0]['percent'], 100/7)
        self.assertEqual(result['projects'][0]['completed'], 1)
        self.assertEqual(result['projects'][0]['total'], 7)
        self.assertEqual(data, before)

    def test_all_mapped_states_and_known_count_denominator(self):
        statuses = ['proposed', 'approved', 'held', 'running', 'candidate_ready', 'landed', 'failed', 'needs_human', 'cancelled']
        data = overview.build_snapshot([plan(*(task(f'T{i}', s) for i, s in enumerate(statuses)))], registered_keys=KEYS)
        result = project(data)
        self.assertEqual(sum(result['distribution'].values()), 9)
        self.assertEqual(result['distribution']['waiting'], 2)
        self.assertEqual(result['distribution']['needs_human'], 2)
        self.assertEqual(result['projects'][0]['percent'], 100/9)

    def test_multiple_repos_unreadable_plan_and_empty_plan_have_no_fake_progress(self):
        second = task('T2')
        second.update(repo_key='other-repo', body=second['body'].replace('sample-repo', 'other-repo'))
        mixed = plan(task('T1', 'landed'), second)
        empty = dict(plan(), plan_id='Plan-2')
        data = overview.build_snapshot([mixed, empty, None], registered_keys=KEYS | {'other-repo'})
        result = project(data, status='partial')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['kpis']['unavailable_plans'], 1)
        self.assertEqual(result['projects'][0]['repos'], ['other-repo', 'sample-repo'])
        self.assertEqual(result['projects'][0]['percent'], 50)
        self.assertIsNone(result['projects'][1]['percent'])
        self.assertIsNone(result['projects'][2]['total'])
        self.assertIsNone(result['projects'][2]['percent'])
        self.assertEqual(project(overview.build_snapshot([], registered_keys=KEYS))['kpis']['total'], 0)

    def test_partial_unknown_is_not_normal_and_failure_is_not_zero(self):
        result = project(snapshot(), status='partial')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['kpis']['unavailable_tasks'], 7)
        self.assertEqual(result['focus']['PX'], 7)
        result = project(snapshot(), status='unavailable')
        self.assertIsNone(result['kpis'])
        self.assertIsNone(result['distribution'])
        self.assertEqual(result['projects'], [])

    def test_disk_run_observation_is_not_memory_confirmation(self):
        data = overview.build_snapshot([plan(task('T1', 'running'))], registered_keys=KEYS,
            associations={('Plan-1', 'T1'): dict(run_id=RID)},
            observations={RID: dict(record=dict(run_id=RID, stage='testing'), liveness='running')})
        self.assertEqual(project(data)['kpis']['running'], 0)
        self.assertEqual(project(data)['kpis']['unavailable_tasks'], 1)
        self.assertEqual(project(data, memory=True)['kpis']['running'], 1)
        self.assertEqual(project(data, memory=True)['proposals']['wait'], 1)

    def test_stale_invalid_snapshot_and_free_text_fail_closed(self):
        data = snapshot()
        box = inbox.build_inbox(data, observation_id=1, collection_status='available')
        for bad in (None, {}, dict(data, schema_version=9)):
            self.assertIsNone(visual.build_overview(bad, box, observation_id=1)['kpis'])
        self.assertIsNone(visual.build_overview(data, box, observation_id=2)['kpis'])
        for field in ('plan_id', 'repo_key', 'category'):
            bad = copy.deepcopy(data)
            bad['plans'][0]['tasks'][0][field] = 'SECRET C:/private'
            output = project(bad)
            self.assertIsNone(output['kpis'])
            self.assertNotIn('SECRET', str(output))

    def fake_view(self):
        widgets = SimpleNamespace(Frame=Widget, Scrollbar=Widget)
        with patch.object(visual, 'ttk', widgets), patch.object(visual.tk, 'Canvas', FakeCanvas):
            return visual.OverviewView(Widget())

    def test_canvas_cards_bars_scroll_resize_theme_and_no_redundant_redraw(self):
        view = self.fake_view()
        style = FakeStyle()
        view.apply_theme(style)
        view.set_model(project(snapshot()))
        texts = str(view.canvas.rows)
        self.assertIn('Manager AI推論なし', texts)
        self.assertIn('本体メモリ未確認', texts)
        self.assertIn('P1: 2', texts)
        self.assertIn('Plan-1', texts)
        self.assertEqual(view.vertical.options['style'], 'Manager.Vertical.TScrollbar')
        self.assertEqual(view.horizontal.options['command'], view.canvas.xview)
        self.assertEqual(view.vertical.options['command'], view.canvas.yview)
        with patch.object(view.canvas, 'delete', wraps=view.canvas.delete) as redraw:
            view.set_model(project(snapshot()))
            redraw.assert_not_called()
        view._resize(SimpleNamespace(width=760))
        self.assertEqual(view.canvas.options['scrollregion'][2], 900)
        view._resize(SimpleNamespace(width=1150))
        self.assertEqual(view.canvas.options['scrollregion'][2], 1150)
        with patch.object(view.canvas, 'yview') as scroll:
            self.assertEqual(view._wheel(SimpleNamespace(delta=-120)), 'break')
            scroll.assert_called_once_with('scroll', 1, 'units')
        with patch.object(view.canvas, 'xview') as scroll:
            view._wheel_horizontal(SimpleNamespace(delta=120))
            scroll.assert_called_once_with('scroll', -1, 'units')
        style.bg = '#ffffff'
        view.apply_theme(style)
        self.assertEqual(view.vertical.options['style'], 'Vertical.TScrollbar')
        view.set_model(visual.empty_overview('updating'))
        self.assertNotIn('Plan-1', str(view.canvas.rows))
        self.assertIn('0件とは扱いません', str(view.canvas.rows))

    def test_many_projects_expand_scrollregion_and_do_not_recreate_canvas(self):
        data = overview.build_snapshot([dict(plan(task('T1')), plan_id=f'Plan-{i}') for i in range(40)], registered_keys=KEYS)
        view = self.fake_view()
        canvas = view.canvas
        view.set_model(project(data))
        self.assertGreater(view.canvas.options['scrollregion'][3], 2000)
        view.set_model(project(snapshot()))
        self.assertIs(view.canvas, canvas)
        self.assertLess(view.canvas.options['scrollregion'][3], 1000)

    def test_controller_same_collection_update_failure_and_close(self):
        view, scheduler, work = View(), Scheduler(), []
        view.overview, view.inbox = Mock(), Mock()
        collector = Mock()
        collector.collect.side_effect = [dict(status='available', observation_id=1, snapshot=snapshot()), OSError('SECRET')]
        controller = preview.PreviewController(view, collector=collector, scheduler=scheduler, launch=work.append)
        self.assertEqual(view.overview.set_model.call_args.args[0]['status'], 'updating')
        calls = view.overview.set_model.call_count
        work.pop()()
        self.assertEqual(view.overview.set_model.call_count, calls)
        scheduler.run(preview.POLL_MS)
        self.assertEqual(collector.collect.call_count, 1)
        self.assertEqual(view.overview.set_model.call_args.args[0]['kpis']['total'], 7)
        scheduler.run(preview.INTERVAL_MS)
        self.assertIsNone(view.overview.set_model.call_args.args[0]['kpis'])
        work.pop()()
        scheduler.run(preview.POLL_MS)
        self.assertIsNone(view.overview.set_model.call_args.args[0]['kpis'])
        self.assertEqual(view.overview.set_model.call_args.args[0]['status'], 'unavailable')
        controller.close()
        self.assertEqual(scheduler.jobs, {})


if __name__ == '__main__':
    unittest.main()
