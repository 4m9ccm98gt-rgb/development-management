"""Read-only organization map with fake Canvas/scheduler; no live services."""
import copy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from scripts.dev_control_center import manager_organization_map as org
from scripts.dev_control_center import manager_dashboard_preview as preview
from scripts.dev_control_center import manager_inbox as inbox
from scripts.dev_control_center import manager_overview as overview
from scripts.dev_control_center.manager_visual_overview import build_overview
from tests.test_dev_control_center_manager_inbox import GuardedTests
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID
from tests.test_dev_control_center_manager_dashboard_view import Widget, FakeCanvas, FakeStyle, snapshot
from tests.test_dev_control_center_manager_dashboard_preview import Scheduler, View


def models(data, memory=False, status='available', generation=1, issues=()):
    safe, _ = preview.preview_data(dict(status=status, snapshot=data), memory_available=memory)
    box = inbox.build_inbox(safe, observation_id=generation, collection_status=status,
                            memory_available=memory, issues=issues)
    return org.build_map(safe, box, observation_id=generation, memory_available=memory), box, build_overview(
        safe, box, observation_id=generation, memory_available=memory)


def observed(stage='implementing', ai='codex', reviewer='claude'):
    t = task('T1', 'running')
    t.update(main_ai=ai, reviewer_ai=reviewer)
    return overview.build_snapshot([plan(t)], registered_keys=KEYS,
        associations={('Plan-1', 'T1'): dict(run_id=RID)},
        observations={RID: dict(record=dict(run_id=RID, stage=stage), liveness='running')})


class MapTests(GuardedTests):
    def test_unique_tasks_human_lane_and_proposals_match(self):
        data = snapshot()
        before = copy.deepcopy(data)
        m, box, stats = models(data)
        self.assertEqual(m['total'], stats['kpis']['total'])
        self.assertEqual(len(m['tasks']), len({t['identity'] for t in m['tasks']}))
        self.assertEqual(len(m['lane']), len(set(m['lane'])))
        self.assertEqual(len(m['lane']), 4)  # needs_human, failed, proposed, unknown running
        for t, r in zip(m['tasks'], box['rows']):
            self.assertIn(t['action_code'], [p['action_code'] for p in r['proposals']])
            if t['unknown']:
                self.assertEqual(t['location'], 'UNKNOWN')
                self.assertFalse(t['human'])
        self.assertEqual(data, before)

    def test_configured_roles_distinct_even_same_ai_without_inferred_activity(self):
        data = observed(ai='codex', reviewer='codex')
        disk, _, _ = models(data)
        self.assertEqual(disk['roles']['IMPLEMENTER']['names'], ['codex'])
        self.assertEqual(disk['roles']['REVIEWER']['names'], ['codex'])
        self.assertEqual(disk['roles']['IMPLEMENTER']['stage_count'], 0)
        self.assertFalse(disk['tasks'][0]['observed'])
        self.assertEqual(disk['tasks'][0]['location'], 'UNKNOWN')
        active, _, _ = models(data, memory=True)
        self.assertEqual(active['roles']['IMPLEMENTER']['stage_count'], 1)
        self.assertEqual(active['roles']['REVIEWER']['stage_count'], 0)
        self.assertEqual(active['tasks'][0]['location'], 'IMPLEMENTER')

    def test_only_verified_stages_are_attributed_to_roles(self):
        for stage, location in (('implementing', 'IMPLEMENTER'), ('repairing', 'IMPLEMENTER'),
                                ('reviewing', 'REVIEWER'), ('testing', 'ORCHESTRATOR'), ('preflight', 'ORCHESTRATOR')):
            with self.subTest(stage=stage):
                m, _, _ = models(observed(stage), memory=True)
                self.assertEqual(m['tasks'][0]['stage'], stage)
                self.assertEqual(m['tasks'][0]['location'], location)

    def test_partial_unknown_distribution_and_map_match(self):
        m, box, stats = models(snapshot(), status='partial')
        self.assertEqual(stats['distribution']['unavailable'], 7)
        self.assertEqual(stats['distribution']['completed'], 0)
        self.assertEqual(stats['kpis']['completed'], 0)
        self.assertEqual(stats['kpis']['running'], 0)
        self.assertEqual(stats['projects'][0]['percent'], 0)
        self.assertTrue(all(t['unknown'] and t['priority'] == 'PX' for t in m['tasks']))
        self.assertTrue(all(t['action_code'] == 'CHECK_DATA' for t in m['tasks']))
        self.assertEqual(len(m['lane']), 7)
        self.assertEqual(stats['focus']['PX'], len(box['rows']))

    def test_localized_partial_issue_only_hides_affected_state(self):
        issue = dict(plan_id='Plan-1', task_id='T1', code='RUN_UNAVAILABLE')
        m, _, stats = models(snapshot(), status='partial', issues=[issue])
        self.assertTrue(m['tasks'][0]['unknown'])
        self.assertEqual(stats['distribution']['completed'], 0)
        self.assertEqual(stats['distribution']['unavailable'], 2)
        self.assertEqual(stats['distribution']['failed'], 1)

    def test_failed_or_stale_collection_has_no_old_tasks(self):
        for status in ('unavailable', 'SECRET'):
            m, _, _ = models(snapshot(), status=status)
            self.assertIsNone(m['total'])
            self.assertEqual(m['tasks'], [])
            self.assertEqual(m['lane'], [])
        m, box, _ = models(snapshot())
        self.assertIsNone(org.build_map(snapshot(), box, observation_id=2)['total'])

    def make_view(self):
        widgets = SimpleNamespace(Frame=Widget, Label=Widget, Scrollbar=Widget)
        with patch.object(org, 'ttk', widgets), patch.object(org.tk, 'Canvas', FakeCanvas):
            return org.OrganizationMapView(Widget())

    def test_characters_role_click_task_click_and_fixed_lane(self):
        view = self.make_view()
        view.set_model(models(snapshot())[0])
        for role in org.ROLES:
            self.assertIn(('role-'+role, '<Button-1>'), view.map.bindings)
        view.map.bindings[('role-MANAGER', '<Button-1>')](None)
        self.assertEqual(view._role, 'MANAGER')
        bindings = [cb for key, cb in view.lane.bindings.items() if isinstance(key, tuple) and key[0].startswith('task-')]
        bindings[0](None)
        self.assertIsNotNone(view._selected)
        self.assertIn('提案の根拠', str(view.detail.rows))
        self.assertIn('人間の', str(view.detail.rows))
        self.assertIsNot(view.map, view.lane)
        self.assertIn('移動履歴ではない', str(view.map.rows))

    def test_report_inbox_unknown_no_fabricated_report_count(self):
        view = self.make_view()
        view.set_model(models(snapshot())[0])
        view.select_role('REPORTS')
        self.assertIn('報告件数不明', str(view.map.rows))
        self.assertNotIn('報告箱（システム）の参照対象 0', str(view.map.rows))

    def test_resize_scroll_dark_light_and_many_tasks(self):
        data = overview.build_snapshot([plan(*(task(f'T{i}', 'needs_human') for i in range(50)))], registered_keys=KEYS)
        view = self.make_view()
        view.set_model(models(data)[0])
        self.assertGreater(view.lane.options['scrollregion'][2], 10000)
        for width in (1150, 760):
            view._resize(SimpleNamespace(width=width))
            self.assertGreaterEqual(view.map.options['scrollregion'][2], 1060)
        style = FakeStyle()
        view.apply_theme(style)
        for c, h, v in view._panels:
            self.assertEqual(c.options['background'], '#0f1419')
            self.assertEqual(v.options['style'], 'Manager.Vertical.TScrollbar')
            with patch.object(c, 'xview') as scroll:
                view._wheel(c, SimpleNamespace(delta=120), True)
                scroll.assert_called_once_with('scroll', -1, 'units')
        style.bg = '#ffffff'
        view.apply_theme(style)
        self.assertEqual(view._panels[0][2].options['style'], 'Vertical.TScrollbar')
        view.select_role('MANAGER')
        self.assertGreater(view.map.options['scrollregion'][3], 1000)

    def test_update_clears_selection_and_old_activity(self):
        view = self.make_view()
        m, _, _ = models(observed(), memory=True)
        view.set_model(m)
        view.select_role('IMPLEMENTER')
        view.select_task(('Plan-1', 'T1'))
        self.assertIn('implementing', str(view.detail.rows))
        for state in ('updating', 'unavailable'):
            view.set_model(org.empty_map(state))
            self.assertIsNone(view._selected)
            self.assertNotIn('implementing', str(view.detail.rows))
            self.assertNotIn('TASK Plan-1', str(view.lane.rows))

    def test_controller_single_collection_map_statistics_inbox_and_close(self):
        view, scheduler, work = View(), Scheduler(), []
        view.organization_map, view.overview, view.inbox = Mock(), Mock(), Mock()
        collector = Mock()
        collector.collect.side_effect = [dict(status='available', observation_id=1, snapshot=snapshot()), OSError('SECRET')]
        controller = preview.PreviewController(view, collector=collector, scheduler=scheduler, launch=work.append)
        self.assertEqual(view.organization_map.set_model.call_args.args[0]['status'], 'updating')
        work.pop()()
        scheduler.run(preview.POLL_MS)
        self.assertEqual(collector.collect.call_count, 1)
        self.assertEqual(view.organization_map.set_model.call_args.args[0]['total'], view.overview.set_model.call_args.args[0]['kpis']['total'])
        scheduler.run(preview.INTERVAL_MS)
        self.assertEqual(view.organization_map.set_model.call_args.args[0]['tasks'], [])
        work.pop()()
        scheduler.run(preview.POLL_MS)
        self.assertEqual(view.organization_map.set_model.call_args.args[0]['status'], 'unavailable')
        controller.close()
        self.assertEqual(scheduler.jobs, {})


if __name__ == '__main__':
    unittest.main()
