"""Four lanes and unchanged operation wiring, with fake Tk/collectors only."""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from scripts.dev_control_center import orchestrator_lanes as lanes
from scripts.dev_control_center import orchestrator_view as view
from scripts.dev_control_center import character
from tests.test_dev_control_center_manager_inbox import GuardedTests
from tests.test_dev_control_center_manager_dashboard_view import FakeCanvas, Widget, FakeStyle
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID
from scripts.dev_control_center import manager_overview as overview
from tests.test_dev_control_center_orchestrator_view import (
    FakeOrchestratorWindowCase, record, item, _FakeStartFormText)


def run(stage, live='running', rid=RID, **kw):
    return item(record(run_id=rid, stage=stage, repo='C:/repos/app', **kw), liveness=live)


class LaneModelTests(GuardedTests):
    def test_stages_unknown_tests_and_conditional_human(self):
        cases = [('created', 'running', 'Manager'), ('implementing', 'running', 'Implementer'),
                 ('repairing', 'running', 'Implementer'), ('testing', 'running', 'Implementer'),
                 ('reviewing', 'running', 'Reviewer'), ('finalizing', 'running', 'Reviewer'),
                 ('failed', 'finished', 'Human'), ('needs_human', 'finished', 'Human'),
                 ('completed', 'finished', 'Manager'), ('implementing', 'lost', 'Manager'),
                 ('testing', 'finished', 'Manager')]
        for stage, live, target in cases:
            with self.subTest(stage=stage, live=live):
                data = lanes.build_lanes([], [run(stage, live)], repo_names={'app'})
                self.assertEqual(len(data[target]), 1)
                self.assertEqual(sum(map(len, data.values())), 1)
                if stage == 'testing' and live == 'running':
                    self.assertIn('システム工程', data[target][0]['state'])
                if live in ('lost',) or stage == 'testing' and live == 'finished':
                    self.assertEqual(data[target][0]['priority'], 'PX')
        data = lanes.build_lanes([], [run('completed', 'finished', candidate_sha='a'*40, apply_status='ready')])
        self.assertEqual(len(data['Human']), 1)

    def test_multiple_cards_dedupe_and_no_free_body_in_normal_view(self):
        runs = [run('implementing'), run('reviewing', rid='20261022-000000-000002'), run('failed', 'finished', rid='20261022-000000-000003')]
        runs[0]['record']['task'] = 'SECRET C:/private'
        data = lanes.build_lanes([], runs+[runs[0]], repo_names={'app'})
        self.assertEqual(sum(map(len, data.values())), 3)
        self.assertNotIn('SECRET', str(data))
        self.assertNotIn('C:/repos', str(data))

    def test_workflow_analysis_association_and_latest_run_conflict(self):
        data = overview.build_snapshot([plan(dict(task('T1', 'running'), main_ai='codex'), task('T2', 'proposed'))],
            registered_keys=KEYS, associations={('Plan-1', 'T1'): dict(run_id=RID)},
            observations={RID: dict(record=dict(run_id=RID, stage='implementing'), liveness='running')})
        before = copy.deepcopy(data)
        cards, notice = lanes.workflow_cards(dict(status='available', observation_id=1, snapshot=data), True)
        result = lanes.build_lanes(cards, [run('implementing')])
        self.assertEqual(sum(map(len, result.values())), 2)
        self.assertEqual(len(result['Implementer']), 1)
        self.assertEqual(len(result['Human']), 1)
        self.assertIn('承認', result['Human'][0]['detail'])
        conflict = lanes.build_lanes(cards, [run('reviewing')])
        self.assertEqual(conflict['Manager'][0]['priority'], 'PX')
        self.assertEqual(len(conflict['Reviewer']), 0)
        self.assertEqual(data, before)

    def test_partial_failure_and_update_feed_stop(self):
        work, clock = [], [0]
        data = overview.build_snapshot([plan(task('T1', 'failed'))], registered_keys=KEYS)
        collector = Mock(side_effect=[dict(status='partial', observation_id=1, snapshot=data), OSError('SECRET')])
        feed = lanes.WorkflowFeed(collector, launch=work.append, now=lambda: clock[0])
        self.assertEqual(feed.poll()[0], [])
        self.assertIsNone(feed.poll())
        self.assertEqual(len(work), 1)
        work.pop()()
        cards, _ = feed.poll()
        self.assertEqual(cards[0]['priority'], 'PX')
        clock[0] = 11
        self.assertEqual(feed.poll()[0][0]['state'], '前回取得・現在状態は確認待ち')
        work.pop()()
        self.assertEqual(feed.poll()[0][0]['priority'], 'PX')
        clock[0] = 30
        feed.poll()
        feed.stop.set()
        work.pop()()
        self.assertIsNone(feed.poll())
        self.assertEqual(collector.call_count, 2)

    def test_invalid_records_and_monitor_failure_are_not_active(self):
        self.assertEqual(sum(map(len, lanes.build_lanes([], [dict(record=dict(run_id='../private'))]).values())), 0)
        data = lanes.build_lanes([], [run('testing')], monitor_ok=False)
        self.assertEqual(data['Manager'][0]['priority'], 'PX')
        self.assertEqual(len(data['Implementer']), 0)

    def test_lane_widgets_scroll_paths_focus_click_and_keyboard(self):
        class Canvas(FakeCanvas):
            def create_window(self, *args, **kw): return self._create(args, kw)
            def itemconfigure(self, *args, **kw): pass
            def yview_scroll(self, *args): pass
            def bbox(self, *args): return (0, 0, 220, 1000)
            def canvasy(self, y): return y
            def winfo_height(self): return 300
            def yview_moveto(self, fraction): self.fraction = fraction
        class Button(Widget):
            def destroy(self): pass
            def pack_forget(self): pass
            def state(self, states): self.options['state'] = states
            def winfo_y(self): return 500
            def winfo_height(self): return 80
        widgets = SimpleNamespace(Frame=Widget, Label=Widget, Scrollbar=Widget, Button=Button, Style=FakeStyle)
        selected = Mock()
        with patch.object(lanes, 'tk', SimpleNamespace(Canvas=Canvas)), patch.object(lanes, 'ttk', widgets):
            board = lanes.LaneBoard(Widget(), selected)
            model = lanes.build_lanes([], [run('testing'), run('testing', rid='20261022-000000-000002')])
            board.set_model(model)
            self.assertEqual(len(board.cards['Implementer']), 2)
            self.assertIn('2件', board.headers['Implementer'].options['text'])
            card = board.cards['Implementer'][0]
            card.bindings['<FocusIn>'](None)
            self.assertEqual(board.canvases['Implementer'].fraction, .5)
            self.assertIn('システム工程', board.hint.options['text'])
            card.options['command']()
            card.bindings['<Return>'](None)
            self.assertEqual(selected.call_count, 2)
            for width in (1000, 1180):
                board._draw_paths(width)
                self.assertGreater(len(board.path.rows), 0)
            board.set_model({name: [] for name in lanes.LANES})
            self.assertEqual(board.cards['Implementer'], [])


class OperationWiringTests(FakeOrchestratorWindowCase):
    def test_candidate_and_stop_still_use_existing_entrypoints(self):
        self.window.run_items = [run('completed', 'finished', candidate_sha='a'*40, apply_status='ready')]
        self.window.selected_run = RID
        self.window.apply_candidate()
        self.on_apply.assert_called_once_with(self.window.run_items[0]['record'], self.window.run_items[0]['run_dir'])
        self.window.run_items = [run('testing')]
        with patch.object(view.messagebox, 'askyesno', return_value=False), patch.object(view.rs, 'force_stop') as stop:
            self.window.stop_run()
            stop.assert_not_called()
        with patch.object(view.messagebox, 'askyesno', return_value=True), \
             patch.object(view.rs, 'force_stop', return_value=dict(stage='stopped')) as stop, \
             patch.object(view.threading, 'Thread') as thread:
            self.window.stop_run()
            thread.call_args.kwargs['target']()
            stop.assert_called_once_with(self.window.run_items[0]['run_dir'])

    def test_callback_optional_and_detail_selection_never_starts(self):
        callback = Mock()
        self.window._on_reports_inbox = callback
        self.window._open_reports()
        callback.assert_called_once_with()
        self.window._on_reports_inbox = None
        self.window._open_reports()
        callback.assert_called_once()
        self.window.run_items = [run('testing')]
        card = lanes.build_lanes([], self.window.run_items)['Implementer'][0]
        with patch.object(view.orch, 'start_run') as start, patch.object(view.rs, 'force_stop') as stop:
            self.window._select_card(card)
            self.assertEqual(self.window.selected_run, RID)
            self.assertEqual(self.monitor.selected, RID)
            self.assertIn('Run記録', self.window.selection_text.content)
            start.assert_not_called()
            stop.assert_not_called()
        self.window._hide_details()
        self.assertFalse(self.window.details.grid_info())

    def test_workflow_plan_and_automation_status_header_buttons_forward_to_their_callbacks(self):
        """DCC Task UI-C C2/C7: 開発計画 and 自動処理の状況 in the Orchestrator header only ever
        forward to the existing open_workflow_plan / open_automation_status DCC already had --
        same optional-callback shape as 報告箱, and neither one starts a run or touches
        approve/push/BUILD/UPDATE/RELEASE."""
        workflow_plan = Mock()
        automation_status = Mock()
        window = view.OrchestratorWindow(
            object(), self.definitions, initial_repo="app", drafts=self.drafts, on_apply=self.on_apply,
            monitor=self.monitor, repos_root=Path("C:/repos"), auto_usage=False,
            on_workflow_plan=workflow_plan, on_automation_status=automation_status)
        self.assertTrue(window.workflow_plan_button.instate(['!disabled']))
        self.assertTrue(window.automation_status_button.instate(['!disabled']))
        with patch.object(view.orch, 'start_run') as start:
            window._open_workflow_plan()
            window._open_automation_status()
            start.assert_not_called()
        workflow_plan.assert_called_once_with()
        automation_status.assert_called_once_with()

    def test_workflow_plan_and_automation_status_buttons_disable_without_a_callback(self):
        # self.window (built in setUp via make_window) never supplies either callback.
        self.assertTrue(self.window.workflow_plan_button.instate(['disabled']))
        self.assertTrue(self.window.automation_status_button.instate(['disabled']))
        self.window._open_workflow_plan()  # a missing callback is a no-op, not an error
        self.window._open_automation_status()

    def test_error_clears_lanes_and_disables_stale_selected_run(self):
        self.window.run_items = [run('testing')]
        self.window.selected_run = RID
        self.window.apply_snapshot(dict(error='read failed'))
        self.assertEqual(self.window.run_items, [])
        self.assertFalse(self.window._monitor_ok)
        self.assertTrue(self.window.stop_button.instate(['disabled']))

    def test_close_stops_only_readers_not_run(self):
        with patch.object(view.rs, 'force_stop') as stop, patch.object(view.orch, 'start_run') as start:
            self.window.close()
            self.window._workflow_feed.stop.set.assert_called()
            self.assertFalse(self.monitor.stopped)  # injected/shared monitor ownership is unchanged
            stop.assert_not_called()
            start.assert_not_called()

    def test_close_never_touches_dccs_own_periodic_processing(self):
        """DCC Task UI-C C6: closing the Orchestrator window must never reach into DCC's own
        periodic processing. Rather than reinventing a disconnected tick, this drives the real
        App._heartbeat_tick -- the actual Tk-main-thread stop-flag-plus-reschedule loop App wires
        up via master.after(HEARTBEAT_MS, self._heartbeat_tick) -- against a fake App-shaped
        fixture (fake master/selection/heartbeat, same SimpleNamespace-as-self convention
        test_app_callback_and_existing_window_reuse below already uses for unbound App methods).
        A real OrchestratorWindow is opened from that fixture through the real App.open_orchestrator
        (tk/ttk/LaneBoard/WorkflowFeed/CharacterView are the fakes FakeOrchestratorWindowCase.setUp
        already installs) and closed through its own real close(). The fixture's stop flag, its
        heartbeat processing, and its next-tick reservation are driven and checked both before and
        after that close -- no real Tk, thread, AI or Orchestrator run is started."""
        from scripts.dev_control_center.app import App

        master = Mock()
        holder = SimpleNamespace(
            orchestrator_window=None, master=master, definitions=self.definitions,
            ai_drafts={}, apply_ai_candidate=Mock(), _requeue_label=Mock(),
            _workflow_runner_state=object(), open_reports_inbox=Mock(),
            open_workflow_plan=Mock(), open_automation_status=Mock(), current=None,
            _closed=False, _heartbeat=Mock(beat=Mock(return_value=0.0)),
            selection=Mock(), _drain_lifecycle_events=Mock(), _drain_orchestrator_badge=Mock(),
            _set_button_states=Mock(), _current_orchestrator_roles=Mock(return_value=('codex', 'claude')))
        holder._heartbeat_tick = lambda: App._heartbeat_tick(holder)  # self._heartbeat_tick, bound to holder

        holder._heartbeat_tick()
        self.assertEqual(master.after.call_count, 1)
        self.assertEqual(master.after.call_args.args[1], holder._heartbeat_tick)
        self.assertEqual(holder._heartbeat.beat.call_count, 1)
        self.assertFalse(holder._closed)

        App.open_orchestrator(holder)
        window = holder.orchestrator_window
        self.assertIsNotNone(window)

        with patch.object(view.rs, 'force_stop') as stop, patch.object(view.orch, 'start_run') as start:
            window.close()
            stop.assert_not_called()
            start.assert_not_called()

        # DCC's own stop flag is unchanged, its processing still runs, and it still reserves
        # its next tick -- the window's close() never reached into any of this.
        self.assertFalse(holder._closed)
        holder._heartbeat_tick()
        self.assertEqual(holder._heartbeat.beat.call_count, 2)
        self.assertEqual(holder.selection.pump.call_count, 2)
        self.assertEqual(master.after.call_count, 2)

        # The "Orchestrator" button can still open a fresh window afterwards (C6's other half).
        window.exists = Mock(return_value=False)
        App.open_orchestrator(holder)
        self.assertIsNot(holder.orchestrator_window, window)


class ThumbnailTests(unittest.TestCase):
    def test_thumbnail_uses_existing_sprite_copy_with_subsample(self):
        sprite = object.__new__(character.CharacterView)
        sprite._sheet, sprite._frame = Mock(), Mock()
        sprite.index, sprite.scale = 0, 4
        sprite._draw()
        args = sprite._frame.tk.call.call_args.args
        self.assertEqual(args[-3:], ('-subsample', 4, 4))


class AppAndMonitorTests(unittest.TestCase):
    def test_app_callback_and_existing_window_reuse(self):
        from scripts.dev_control_center.app import App
        holder = SimpleNamespace(orchestrator_window=None, master=Mock(), definitions=[], ai_drafts={},
            apply_ai_candidate=Mock(), _requeue_label=Mock(), _workflow_runner_state=object(),
            open_reports_inbox=Mock(), open_workflow_plan=Mock(), open_automation_status=Mock(), current=None)
        with patch.object(view, 'OrchestratorWindow') as factory:
            App.open_orchestrator(holder)
            self.assertIs(factory.call_args.kwargs['on_reports_inbox'], holder.open_reports_inbox)
            self.assertIs(factory.call_args.kwargs['on_workflow_plan'], holder.open_workflow_plan)
            self.assertIs(factory.call_args.kwargs['on_automation_status'], holder.open_automation_status)
            self.assertIs(factory.call_args.kwargs['runner_state'], holder._workflow_runner_state)
            App.open_orchestrator(holder)
            self.assertEqual(factory.call_count, 1)
            factory.return_value.focus.assert_called_once()
            # DCC Task UI-C C6: once the window reports itself closed, the Orchestrator button
            # must be able to open a fresh one again (not stay stuck reusing the dead window).
            factory.return_value.exists.return_value = False
            App.open_orchestrator(holder)
            self.assertEqual(factory.call_count, 2)
        reports = SimpleNamespace(reports_window=Mock())
        App.open_reports_inbox(reports)
        reports.reports_window.focus.assert_called_once()

    def test_monitor_uses_existing_log_and_selection_without_run_changes(self):
        monitor = view.RunMonitor(list_runs=lambda **kw: [run('testing')], usage_names=())
        monitor.select(RID)
        with patch.object(view.rs, 'tail_log', return_value=('log', 12)), \
             patch.object(view.rs, 'reconcile_lost') as reconcile, patch.object(view.rs, 'force_stop') as stop:
            data = monitor.poll_once()
            self.assertEqual(data['selected'], RID)
            self.assertEqual(data['log'], 'log')
            reconcile.assert_not_called()
            stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
