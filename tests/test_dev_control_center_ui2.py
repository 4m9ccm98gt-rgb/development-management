"""UI-2 uses fake Tk, providers, collectors and schedulers exclusively."""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from scripts.dev_control_center import ui_theme, orchestrator_lanes as lanes, orchestrator_view as view
from scripts.dev_control_center.manager_overview import build_snapshot
from tests.test_dev_control_center_manager_overview import plan, task, KEYS
from tests.test_dev_control_center_manager_dashboard_view import Widget, FakeCanvas, FakeStyle
from tests.test_dev_control_center_orchestrator_view import FakeOrchestratorWindowCase, _FakeCharacterView
from tests.test_dev_control_center_orchestrator_lanes import run


class ThemeTests(unittest.TestCase):
    def test_common_containers_and_states_are_dark_without_switching_theme(self):
        style = FakeStyle()
        with patch.object(style, 'theme_use') as change:
            ui_theme.configure_dark_containers(style)
            change.assert_not_called()
        self.assertEqual(style.configurations['TNotebook']['background'], '#0f1419')
        self.assertEqual(style.configurations['TFrame']['background'], '#0f1419')
        self.assertEqual(style.configurations['TLabelframe']['background'], '#0f1419')
        self.assertEqual(style.configurations['TLabelframe.Label']['foreground'], '#e6edf3')
        for state in ('selected', 'active', 'disabled'):
            self.assertIn(state, [s for s, _ in style.maps['TNotebook.Tab']['background']])
        for orientation in ('Horizontal', 'Vertical'):
            self.assertEqual(style.configurations[orientation+'.TScrollbar']['troughcolor'], '#0f1419')
        before = dict(style.elements)
        ui_theme.configure_dark_containers(style)
        self.assertEqual(style.elements, before)

    def test_maximize_and_failure_fallback(self):
        window = Mock()
        self.assertTrue(view.maximize_window(window, windows=True))
        window.state.assert_called_once_with('zoomed')
        window.state.side_effect = view.tk.TclError('no zoom')
        self.assertFalse(view.maximize_window(window, windows=True))
        window.geometry.assert_called_once_with('1180x840')
        window.reset_mock()
        self.assertFalse(view.maximize_window(window, windows=False))
        window.state.assert_not_called()


class CardDiffTests(unittest.TestCase):
    def make_board(self):
        class Canvas(FakeCanvas):
            def create_window(self, *args, **kwargs): return self._create(args, kwargs)
            def itemconfigure(self, *args, **kwargs): pass
            def yview_scroll(self, *args): pass
            def bbox(self, *args): return (0, 0, 200, 1000)
            def canvasy(self, y): return y
            def winfo_height(self): return 300
            def yview_moveto(self, fraction): pass
        class Button(Widget):
            focused = None
            def __init__(self, master, **kwargs):
                super().__init__(**kwargs)
                self.master = master
                self.destroyed = False
                self.packs = 0
                self.updates = 0
            def configure(self, **kwargs):
                self.updates += 1
                super().configure(**kwargs)
            def pack(self, **kwargs): self.packs += 1
            def pack_forget(self): pass
            def destroy(self): self.destroyed = True
            def state(self, states): self.options['state'] = states
            def focus_get(self): return Button.focused
            def focus_set(self): Button.focused = self
            def winfo_y(self): return 0
            def winfo_height(self): return 80
        widgets = SimpleNamespace(Frame=Widget, Label=Widget, Button=Button, Scrollbar=Widget, Style=FakeStyle)
        context = patch.object(lanes, 'ttk', widgets)
        context.start(); self.addCleanup(context.stop)
        context = patch.object(lanes, 'tk', SimpleNamespace(Canvas=Canvas))
        context.start(); self.addCleanup(context.stop)
        return lanes.LaneBoard(Widget(), Mock())

    def test_unchanged_update_move_add_delete_and_selection_reuse(self):
        board = self.make_board()
        model = lanes.build_lanes([], [run('testing'), run('reviewing', rid='20261022-000000-000002')])
        board.set_model(model)
        first = board.cards['Implementer'][0]
        other = board.cards['Reviewer'][0]
        first.focus_set()
        board._activate(model['Implementer'][0]['key'])
        count = first.updates
        board.set_model(copy.deepcopy(model))
        self.assertIs(board.cards['Implementer'][0], first)
        self.assertEqual(first.updates, count)
        changed = copy.deepcopy(model)
        changed['Implementer'][0]['state'] = '更新中・確認待ち'
        board.set_model(changed)
        self.assertIs(board.cards['Implementer'][0], first)
        self.assertIs(board.cards['Reviewer'][0], other)
        self.assertIs(first.focus_get(), first)
        self.assertEqual(board._selected_key, changed['Implementer'][0]['key'])
        moved = copy.deepcopy(changed)
        card = moved['Implementer'].pop()
        card['lane'] = 'Manager'
        moved['Manager'].append(card)
        board.set_model(moved)
        self.assertTrue(first.destroyed)  # only reparented card needs a new Tk parent
        self.assertIs(board.cards['Reviewer'][0], other)
        self.assertEqual(board.cards['Manager'][0].options['state'], ['selected'])
        self.assertIs(board.cards['Manager'][0].focus_get(), board.cards['Manager'][0])
        board.set_model({name: [] for name in lanes.LANES})
        self.assertEqual(board._widgets, {})

    def test_feed_retains_ids_marks_stale_and_failure_has_last_time(self):
        jobs, clock = [], [0]
        payload = dict(status='available', observation_id=1,
                       snapshot=build_snapshot([plan(task('T1', 'failed'))], registered_keys=KEYS))
        collector = Mock(side_effect=[payload, OSError('SECRET')])
        feed = lanes.WorkflowFeed(collector, launch=jobs.append, now=lambda: clock[0])
        feed.poll(); jobs.pop()()
        original, notice = feed.poll()
        self.assertIsNotNone(feed.last_success)
        clock[0] = 11
        stale, notice = feed.poll()
        self.assertEqual(stale[0]['key'], original[0]['key'])
        self.assertEqual(stale[0]['lane'], original[0]['lane'])
        self.assertEqual(stale[0]['priority'], 'PX')
        self.assertIn('最終取得', notice)
        jobs.pop()()
        failed, notice = feed.poll()
        self.assertEqual(failed[0]['key'], original[0]['key'])
        self.assertIn('取得不能', notice)
        self.assertNotIn('SECRET', str(failed)+notice)
        self.assertEqual(original[0]['priority'], 'P1')


class SelectionAndUsageTests(FakeOrchestratorWindowCase):
    def snapshot(self, runs, **extra):
        return dict(runs=runs, usage={}, selected=None, log='', log_reset=False, **extra)

    def test_usage_is_below_provider_and_above_actions_no_extra_query(self):
        self.assertIs(self.window.usage_frame.master, self.window.input_frame)
        self.assertEqual(set(self.window.usage_labels), {'claude', 'codex'})
        self.assertEqual(self.window.start_button.master.grid_options['row'], self.window.usage_frame.grid_options['row']+1)
        with patch.object(view.usage_mod, 'make_usage_provider') as provider:
            self.window._show_details('form')
            self.window._on_role_changed('main')
            provider.assert_not_called()
        self.assertIn('Main', self.window.usage_role_vars['claude'].get())
        self.assertIn('Reviewer', self.window.usage_role_vars['codex'].get())

    def test_usage_refresh_uses_only_existing_provider_queries(self):
        adapters = {'claude': Mock(), 'codex': Mock()}
        with patch.object(view.usage_mod, 'make_usage_provider', side_effect=lambda name: adapters[name]) as factory, \
             patch.object(view.threading, 'Thread') as thread:
            self.window.refresh_usage()
            thread.call_args.kwargs['target']()
        self.assertEqual(factory.call_count, 2)
        for adapter in adapters.values(): adapter.refresh.assert_called_once_with(force=True)

    def test_usage_unavailable_old_cache_and_role_labels_use_existing_formatting(self):
        cache = dict(account=dict(observed_at=1, windows=[dict(label='5時間枠', used_percent=25, resets_at=2)]),
                     context=None, errors={})
        self.window.apply_snapshot(dict(self.snapshot([]), usage={'claude': cache, 'codex': dict(account=None, context=None, errors={})}))
        self.assertIn('75% remaining', self.window.usage_vars['claude'].get())
        self.assertIn('last known', self.window.usage_vars['claude'].get())
        self.assertIn('未取得', self.window.usage_vars['codex'].get())
        self.assertFalse(self.window.start_button.instate(['disabled']))

    def test_header_copy_uses_selected_run_report_only(self):
        r = run('testing')
        self.window.apply_snapshot(self.snapshot([r]))
        with patch.object(view.rs, 'run_report', return_value='report') as report:
            self.window.copy_run_log()
            report.assert_called_once_with(r['run_dir'])
            self.window._select_card(dict(key='WF:Plan-1:T2', run_id=None, title='T2', lane='Manager',
                                          state='保留', priority='P3', hint='hint', detail='detail'))
            self.window.copy_run_log()
            self.assertEqual(report.call_count, 1)

    def test_copy_header_and_single_loop_character(self):
        self.assertIs(self.window.copy_button.master, self.window.stop_button.master)
        self.assertIsNot(self.window.copy_button.master, self.window.apply_button.master)
        self.assertTrue(self.window.copy_button.instate(['disabled']))
        with patch.object(view, 'CharacterView', wraps=_FakeCharacterView) as factory:
            second = self.make_window(initial_repo='app')
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['scale'], 1)
        second.close()

    def test_unlinked_task_clears_stop_copy_and_poll_never_reselects_run(self):
        r = run('testing')
        self.window.apply_snapshot(self.snapshot([r]))
        linked = lanes.build_lanes([], [r])['Implementer'][0]
        self.window._select_card(linked)
        self.assertEqual(self.window.selected_run, r['record']['run_id'])
        unrelated = dict(key='WF:Plan-1:T2', run_id=None, title='Plan-1/T2', lane='Manager',
                         state='待機', priority='P3', hint='hint', detail='detail')
        self.window._workflow_cards = [unrelated]
        self.window._select_card(unrelated)
        self.assertIsNone(self.window.selected_run)
        self.assertIsNone(self.monitor.selected)
        self.assertTrue(self.window.stop_button.instate(['disabled']))
        self.assertTrue(self.window.copy_button.instate(['disabled']))
        for _ in range(2):
            self.window.apply_snapshot(dict(self.snapshot([r]), selected=r['record']['run_id'], log='old run log'))
            self.assertIsNone(self.window.selected_run)
        self.assertNotIn('old run log', self.window.log.content)
        self.window.run_list.selection_set(0)
        self.window._on_run_selected()
        self.assertEqual(self.window.selected_run, r['record']['run_id'])

    def test_missing_run_and_failed_poll_clear_operation_target(self):
        r = run('testing')
        self.window.apply_snapshot(self.snapshot([r]))
        self.window.apply_snapshot(self.snapshot([]))
        self.assertIsNone(self.window.selected_run)
        self.assertTrue(self.window.copy_button.instate(['disabled']))
        self.window._selection_explicit = False
        self.window.apply_snapshot(self.snapshot([r]))
        self.window.apply_snapshot(dict(error='unreadable'))
        self.assertIsNone(self.window.selected_run)
        self.assertIsNone(self.monitor.selected)
        self.assertTrue(self.window.stop_button.instate(['disabled']))
        self.assertEqual(self.window.run_list.size(), 0)

    def test_new_run_pending_until_observed(self):
        rid = '20261022-000000-000001'
        self.window._events.put(('ok', Path('C:/runs')/rid))
        self.window._tick()
        self.assertIsNone(self.window.selected_run)
        self.assertEqual(self.monitor.selected, rid)
        self.assertTrue(self.window.stop_button.instate(['disabled']))
        self.window.apply_snapshot(self.snapshot([run('testing', rid=rid)]))
        self.assertEqual(self.window.selected_run, rid)
        self.assertFalse(self.window.copy_button.instate(['disabled']))


if __name__ == '__main__':
    unittest.main()
