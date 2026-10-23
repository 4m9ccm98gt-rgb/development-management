"""UI-6 sizing/animation tests. Tk and all process/data adapters stay fake."""
import math
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
from scripts.dev_control_center import character, character_layout as layout, sprite_renderer as sprites
from tests import test_dev_control_center_orchestrator_loop as loop_tests

class LayoutTests(unittest.TestCase):
    def test_target_and_clearance_across_window_sizes(self):
        for width,height in [(500,630),(650,630),(800,800),(1000,900),(1200,1000)]:
            factor=layout.character_display_scale(width,height)
            self.assertTrue(layout.fits_character(width,height,factor))
            self.assertLessEqual(factor,1.4)
            self.assertGreaterEqual(factor,.25)
        self.assertEqual(layout.character_display_scale(1000,900),1.4)
        self.assertGreater(layout.character_display_scale(500,630),.5)
        self.assertGreater(layout.character_display_scale(650,630),1)

    def test_all_frames_are_covered_by_profile_and_fractional_resize_preserves_alpha(self):
        for mood in character.MOODS:
            frames=sprites.prepare_frames(character.ASSET_DIR/(mood+'.png'),1)
            for frame in frames:
                alpha=frame.getchannel('A')
                for left,top,right,bottom in layout.SPRITE_BANDS:
                    box=alpha.crop((0,top,240,bottom)).getbbox()
                    if box:
                        self.assertGreaterEqual(box[0],left)
                        self.assertLessEqual(box[2],right)
            enlarged=sprites.prepare_frames(character.ASSET_DIR/(mood+'.png'),1/1.4)
            self.assertEqual(len(enlarged),72)
            self.assertEqual(enlarged[0].size,(336,467))
            self.assertEqual(enlarged[0].getpixel((0,0))[3],0)
            self.assertEqual(enlarged[0].getchannel('A').getextrema()[1],255)

    def test_fractional_dimensions_and_invalid_values(self):
        self.assertEqual(sprites.frame_dimensions(1/1.4),(336,467))
        self.assertEqual(sprites.frame_dimensions(2),(120,167))
        self.assertEqual(sprites.frame_dimensions(1/1.137),(273,379))
        for bad in [True,0,-1,float('nan'),float('inf'),.1,'1']:
            with self.assertRaises(ValueError):sprites.frame_dimensions(bad)

class CharacterTests(unittest.TestCase):
    def test_scale_request_reuses_worker_and_keeps_position_mood_index_timer(self):
        canvas=Mock()
        with patch.object(character.tk,'PhotoImage'):
            obj=character.CharacterView(canvas,canvas=canvas,background='#080f20',asset_dir=Path('missing-ui6-assets'))
        worker=Mock();obj._worker=worker;obj.mood='review';obj.index=18;obj._after_id='timer'
        obj.set_display_scale(1.4)
        worker.request.assert_called_once_with('review',1/1.4)
        obj.set_display_scale(1.4)
        self.assertEqual(worker.request.call_count,1)
        self.assertEqual(obj.index,18);self.assertEqual(obj.mood,'review');self.assertEqual(obj._after_id,'timer')
        canvas.coords.assert_not_called()
        for bad in [True,float('nan'),float('inf'),0,4,'1.4']:obj.set_display_scale(bad)
        self.assertEqual(worker.request.call_count,1)
        obj.destroy();worker.close.assert_called_once()

    def test_tk_cache_has_72_frames_only_for_current_mood_and_size(self):
        canvas=Mock()
        with patch.object(character.tk,'PhotoImage'):
            obj=character.CharacterView(canvas,canvas=canvas,background='#080f20',asset_dir=Path('missing-ui6-assets'))
        obj._worker=Mock();obj._worker.request.return_value=[Mock()]*72;obj.mood='idle'
        with patch('PIL.ImageTk.PhotoImage',side_effect=lambda *a,**k:Mock()) as photo:
            for i in range(216):obj.index=i%72;obj._draw()
            self.assertEqual(photo.call_count,72)
            self.assertEqual(len(obj._tk_frames),72)
            obj.mood='review';obj._draw()
            self.assertEqual(len(obj._tk_frames),1)
            obj.set_display_scale(1.4);obj._draw()
            self.assertEqual(len(obj._tk_frames),1)
        obj.destroy();self.assertEqual(obj._tk_frames,{})

    def test_worker_tick_compensates_upload_time_to_preserve_nominal_fps(self):
        canvas=Mock();canvas.winfo_exists.return_value=True
        with patch.object(character.tk,'PhotoImage'):
            obj=character.CharacterView(canvas,canvas=canvas,background='#080f20',asset_dir=Path('missing-ui6-assets'))
        obj._worker=Mock();obj._draw=Mock()
        with patch.object(character.time,'perf_counter',side_effect=[1,1.04]):obj._tick()
        canvas.after.assert_called_once_with(43,obj._tick)
        obj.destroy()

    def test_fractional_cache_stays_at_two_entries(self):
        def wait_for(fn):
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                result=fn()
                if result is not None:return result
                time.sleep(.002)
            self.fail('worker did not complete')
        with patch.object(sprites,'prepare_frames',return_value=[]):
            worker=sprites.SpriteWorker(Path('unused'));self.addCleanup(worker.close)
            for factor in [1.01,1.137,1.4,1.2,1.0]:
                wait_for(lambda factor=factor:worker.request('idle',1/factor))
            self.assertEqual(len(worker._cache),2)

class BoardTests(unittest.TestCase):
    make_board=loop_tests.BoardTests.make_board
    def test_layout_matches_actual_station_geometry_and_center_does_not_move(self):
        from scripts.dev_control_center.orchestrator_loop import STATIONS
        board=self.make_board();agent=Mock();board.attach_character(agent)
        for width,height in [(500,630),(650,630),(800,800),(1000,900)]:
            board.loop.coords=Mock()
            board._resize(SimpleNamespace(width=width,height=height));board._finish_resize()
            board._position_character()
            agent.move.assert_called_with(width/2,height*.53)
            agent.set_display_scale.assert_called_with(layout.character_display_scale(width,height))
            _,panels=layout.loop_obstacles(width,height)
            if board.loop.coords.call_count:
                for name,(left,top,right,bottom) in zip(STATIONS,panels):
                    board.loop.coords.assert_any_call(board._station_items[name],left,top)


class MissingPillowTests(unittest.TestCase):
    """Execute fresh production modules with PIL imports failing, using fake Tk only."""

    def setUp(self):
        import builtins
        import sys
        import tempfile
        import tkinter
        from contextlib import ExitStack
        from types import ModuleType
        from tests import test_dev_control_center_orchestrator_view as windows
        import scripts.dev_control_center as package

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        enter = self.stack.enter_context
        self.root = Path(enter(tempfile.TemporaryDirectory()))
        self.windows = windows
        self.blocked_imports = []
        original_import = builtins.__import__

        def without_pillow(name, *args, **kwargs):
            if name == 'PIL' or name.startswith('PIL.'):
                self.blocked_imports.append(name)
                raise ImportError('Pillow intentionally unavailable')
            return original_import(name, *args, **kwargs)

        enter(patch('builtins.__import__', side_effect=without_pillow))
        enter(patch.object(tkinter, 'Tk', side_effect=AssertionError('real Tk forbidden')))

        class Canvas(loop_tests.Canvas):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.after = Mock(return_value='timer')
                self.after_cancel = Mock()
            def itemconfigure(self, item, **kwargs):
                self.rows[item][1].update(kwargs)
            def focus_set(self): pass
            def pack_forget(self): pass
            def focus_get(self): return None
            def destroy(self): pass
            def winfo_exists(self): return True

        # Canvas subclasses must inherit the fake before their class definitions run.
        enter(patch.object(tkinter, 'Canvas', Canvas))
        enter(patch('tkinter.ttk.Frame', loop_tests.FakeWidget))
        enter(patch('tkinter.font.Font', return_value=Mock(measure=lambda text: len(text)*8)))
        self.modules = {}
        for name in ('orchestrator_art', 'sprite_renderer', 'character',
                     'orchestrator_cards', 'orchestrator_loop', 'orchestrator_view'):
            fullname = package.__name__ + '.' + name
            path = Path(next(iter(package.__path__))) / (name + '.py')
            module = ModuleType(fullname)
            module.__file__ = str(path)
            module.__package__ = package.__name__
            enter(patch.dict(sys.modules, {fullname: module}))
            enter(patch.object(package, name, module))
            exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
            self.modules[name] = module

        self.view = self.modules['orchestrator_view']
        self.loop = self.modules['orchestrator_loop']
        self.art = self.modules['orchestrator_art']
        self.character = self.modules['character']
        self.photo = enter(patch.object(tkinter, 'PhotoImage'))
        self.legacy = enter(patch.object(self.character.CharacterView, '_load',
                                       side_effect=AssertionError('legacy decode forbidden')))
        self.render = enter(patch.object(self.art, 'render_art',
                                       side_effect=AssertionError('raster forbidden')))
        self.prepare = enter(patch.object(self.modules['sprite_renderer'], 'prepare_frames',
                                        side_effect=AssertionError('sprite decode forbidden')))
        enter(patch.object(self.character, 'ASSET_DIR', self.root))
        # Supply all six assets so asset absence cannot mask the Pillow branch.
        for mood in self.character.MOODS:
            (self.root / (mood + '.png')).touch()
        original_character = self.character.CharacterView
        enter(patch.object(self.view, 'CharacterView',
                           side_effect=lambda *a, **k: original_character(*a, asset_dir=self.root, **k)))
        widgets = SimpleNamespace(Frame=loop_tests.FakeWidget, Label=loop_tests.FakeWidget,
                                  Button=loop_tests.FakeWidget, Scrollbar=loop_tests.FakeWidget,
                                  Style=loop_tests.FakeStyle)
        enter(patch.object(self.loop, 'ttk', widgets))
        enter(patch.object(self.view, 'tk', windows._FAKE_START_FORM_TK_MODULE))
        enter(patch.object(self.view, 'ttk', windows._FAKE_START_FORM_TTK_MODULE))
        enter(patch.object(self.view, 'WorkflowFeed')).return_value.poll.return_value = None
        self.monitor = windows.FakeMonitor()
        self.on_apply = Mock(side_effect=AssertionError('candidate action forbidden'))
        self.reports = Mock()
        # No process (including installers, PUSH, BUILD, UPDATE or RELEASE) may run.
        self.process = enter(patch('subprocess.Popen', side_effect=AssertionError('process forbidden')))
        self.start = enter(patch.object(self.view.orch, 'start_run',
                                      side_effect=AssertionError('real run forbidden')))
        self.window = self.view.OrchestratorWindow(
            object(), [SimpleNamespace(name='app', branch='main', initial_ai_task='',
                                       initial_test='python -m unittest')],
            initial_repo='app', drafts={}, on_apply=self.on_apply, monitor=self.monitor,
            repos_root=self.root, auto_usage=False, on_reports_inbox=self.reports,
            workflow_collector=Mock())
        self.addCleanup(self.window.close)

    def test_open_and_fallback_remain_usable_through_selection_resize_and_close(self):
        w = self.window
        self.assertTrue(self.blocked_imports)
        self.assertIsNone(self.art.Image)
        self.assertTrue(w.exists())
        self.assertFalse(w.board._art.available)
        self.assertFalse(w.character.available)
        self.assertIsNone(w.character._worker)
        self.assertIsNone(w.character._after_id)
        self.assertIn('装飾未取得：簡易描画', w.board.hint.options['text'])
        rec = self.windows.record(repo=str(self.root / 'app'))
        it = self.windows.item(rec, run_dir=self.root / 'run')
        w.apply_snapshot(dict(runs=[it], usage={}, selected=None))
        card = w.board.cards['Testing'][0]
        card.bindings['<Return>'](None)
        self.assertEqual(w.selected_run, rec['run_id'])
        self.assertEqual(self.monitor.selected, rec['run_id'])
        self.assertIn(rec['task'], w.selection_text.content)
        self.assertTrue(w.details.grid_info())
        data = next(iter(w.board._data.values()))
        w.board._focus_card(card, w.board.canvases['Testing'], data)
        self.assertIn('装飾未取得：簡易描画', w.board.hint.options['text'])
        card.state(['selected']); card._highlight(True); card._focus(True)
        card._background()
        self.assertIsNone(card._photo)
        card.after.assert_not_called()
        w.board._resize(SimpleNamespace(width=900, height=800)); w.board._finish_resize()
        for surface in w.board._surfaces:
            surface._resize(SimpleNamespace(width=240, height=180)); surface._paint()
            self.assertIsNone(surface._photo)
            self.assertIsNone(surface._job)
        self.assertIsNone(w.board._ring_photo)
        self.assertIsNone(w.board._art_job)
        for mood in self.character.MOODS: w.character.set_mood(mood)
        w.character.set_display_scale(1.4)
        self.assertIsNone(w.character._after_id)
        self.legacy.assert_not_called(); self.render.assert_not_called(); self.prepare.assert_not_called()
        self.photo.assert_called_once()  # blank placeholder only, never a file/data decode
        self.assertNotIn('file', self.photo.call_args.kwargs)
        self.assertNotIn('data', self.photo.call_args.kwargs)
        w.close()
        self.assertFalse(w.exists())
        self.assertTrue(w.character._destroyed)
        self.on_apply.assert_not_called(); self.process.assert_not_called(); self.start.assert_not_called()

    def test_start_roles_usage_log_stop_and_reports_do_not_invoke_candidate_actions(self):
        w = self.window
        w._show_details('form')
        self.assertTrue(w.details.grid_info())
        w.task_text.insert('1.0', 'Task\n受入条件\n- 確認する')
        for main, reviewer in [('Claude', 'Codex'), ('Codex', 'Claude')]:
            w.main_var.set(main); w.review_var.set(reviewer); w._on_role_changed('main')
            w.start_button.command()
            self.assertTrue(w.confirm_frame.grid_info())
            self.assertEqual(w.confirm_tests_var.get(), 'python -m unittest')
            self.assertEqual(w.current_roles(), (main.lower(), reviewer.lower()))
            w._cancel_confirm()
            self.assertTrue(w.input_frame.grid_info())
        rec = self.windows.record(repo=str(self.root / 'app'))
        run_dir = self.root / 'run'
        it = self.windows.item(rec, run_dir=run_dir)
        w.apply_snapshot(dict(runs=[it], selected=None, usage={
            'claude': self.windows.claude_cache(), 'codex': self.windows.codex_cache()}))
        self.assertIn('68% remaining', w.usage_vars['claude'].get())
        self.assertIn('73% remaining', w.usage_vars['codex'].get())
        self.assertEqual(w.usage_role_vars['codex'].get(), 'Main')
        self.assertEqual(w.usage_role_vars['claude'].get(), 'Reviewer')

        def immediate_thread(*, target, **kwargs):
            return SimpleNamespace(start=target)

        with patch.object(self.view.threading, 'Thread', side_effect=immediate_thread), \
             patch.object(self.view.usage_mod, 'make_usage_provider') as provider, \
             patch.object(self.view.rs, 'force_stop', return_value={'stage': 'stopped'}) as stop, \
             patch.object(self.view.rs, 'run_report', return_value='synthetic log') as report, \
             patch.object(self.view.messagebox, 'askyesno', return_value=False) as confirm, \
             patch.object(w.window, 'clipboard_append') as clipboard:
            w.refresh_usage()
            self.assertEqual({c.args[0] for c in provider.call_args_list}, {'claude', 'codex'})
            self.assertEqual(provider.return_value.refresh.call_count, 2)
            w.copy_button.command()
            report.assert_called_once_with(run_dir)
            clipboard.assert_called_once_with('synthetic log')
            w.stop_button.command(); stop.assert_not_called()
            confirm.return_value = True
            w.stop_button.command(); stop.assert_called_once_with(run_dir)
            w._tick()
            self.assertIn('停止処理が完了', w.notice_var.get())
        w._open_reports(); self.reports.assert_called_once_with()
        self.on_apply.assert_not_called(); self.process.assert_not_called(); self.start.assert_not_called()
