"""Rendering regression/performance invariants. No real Tk, provider, or data store."""
import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image
from scripts.dev_control_center import orchestrator_art as art, orchestrator_cards as cards
from scripts.dev_control_center import sprite_renderer as sprites, character
from tests import test_dev_control_center_orchestrator_loop as loop_tests
from tests import test_dev_control_center_orchestrator_view as window_tests
from tests.test_dev_control_center_orchestrator_lanes import run
from scripts.dev_control_center import orchestrator_lanes as lanes


def wait_for(fn):
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        result=fn()
        if result is not None:return result
        time.sleep(.002)
    raise AssertionError('worker did not complete')

class RasterTests(unittest.TestCase):
    def test_card_panel_ring_sizes_gradients_and_states(self):
        for kind,w,h in [('card',192,108),('panel',220,650),('ring',650,630)]:
            image=art.render_art((kind,w,h,'#2ba8ff','normal'))
            self.assertEqual(image.size,(w,h))
            self.assertGreater(len(image.getcolors(w*h)),100)
        normal=art.render_art(('card',192,108,'#2ba8ff','normal'))
        selected=art.render_art(('card',192,108,'#2ba8ff','selected'))
        hover=art.render_art(('card',192,108,'#2ba8ff','hover'))
        self.assertNotEqual(normal.tobytes(),selected.tobytes())
        self.assertNotEqual(normal.tobytes(),hover.tobytes())
        self.assertNotEqual(normal.getpixel((25,25)),normal.getpixel((25,85)))

    def test_station_panels_have_distinct_tinted_gradients(self):
        from scripts.dev_control_center.orchestrator_loop import COLORS, STATIONS
        samples=[]
        for name in STATIONS:
            image=art.render_art(('station',192,130,COLORS[name],'normal'))
            self.assertEqual(image.size,(192,130))
            self.assertNotEqual(image.getpixel((40,20)),image.getpixel((40,110)))
            self.assertNotEqual(image.getpixel((0,0)),image.getpixel((40,20)))
            samples.append(image.getpixel((40,20)))
        self.assertEqual(len(set(samples)),4)

    def test_raster_size_guard(self):
        with self.assertRaises(ValueError):art.render_art(('ring',8000,8000,'#000000','normal'))

    def test_worker_cache_limits_close_and_no_duplicate_inflight(self):
        entered,release=threading.Event(),threading.Event()
        def render(key):
            entered.set();release.wait(1)
            return Image.new('RGB',(10,10))
        with patch.object(art,'render_art',side_effect=render) as factory:
            worker=art.ArtWorker();self.addCleanup(worker.close)
            key=('card',64,108,'#000000','normal')
            worker.request(key);self.assertTrue(entered.wait(1))
            for _ in range(50):worker.request(key)
            self.assertEqual(len(worker._pending),0)
            release.set();wait_for(lambda:worker.request(key))
            self.assertEqual(factory.call_count,1)
            for i in range(35):
                wait_for(lambda i=i:worker.request(('card',i+1,1,'#000000','normal')))
            self.assertLessEqual(len(worker._cache),24)
            self.assertLessEqual(worker._pixels,8_000_000)
            worker.close();self.assertIsNone(worker.request(key))
            self.assertEqual(worker._cache,{})

    def test_pending_and_pixel_budgets(self):
        entered, release = threading.Event(), threading.Event()
        def render(key):
            entered.set();release.wait(1)
            return SimpleNamespace(width=3_000_000,height=1)
        with patch.object(art,'render_art',side_effect=render):
            worker=art.ArtWorker();self.addCleanup(worker.close)
            worker.request(('card',1,1,'#000000','normal'))
            self.assertTrue(entered.wait(1))
            for i in range(2,70):worker.request(('card',i,1,'#000000','normal'))
            self.assertLessEqual(len(worker._pending),24)
            release.set()
            wait_for(lambda:worker.request(('card',69,1,'#000000','normal')))
            self.assertLessEqual(worker._pixels,8_000_000)
            self.assertLessEqual(len(worker._cache),2)

    def test_missing_pillow_and_render_failure_fallback(self):
        with patch.object(art,'Image',None):
            worker=art.ArtWorker();self.assertFalse(worker.available);worker.close()
        with patch.object(art,'render_art',side_effect=ValueError('private path')):
            worker=art.ArtWorker();self.addCleanup(worker.close)
            worker.request(('card',10,10,'#000000','normal'))
            wait_for(lambda:True if not worker.available else None)
            self.assertFalse(worker.available)

class SpriteTests(unittest.TestCase):
    def test_exterior_key_preserves_enclosed_dark_costume_and_authored_alpha(self):
        mask=Image.new('L',(7,7),0)
        for x in range(1,6):
            for y in range(1,6):mask.putpixel((x,y),255)
        mask.putpixel((3,3),0)
        alpha=sprites.exterior_alpha(mask)
        self.assertEqual(alpha.getpixel((0,0)),0)
        self.assertEqual(alpha.getpixel((3,3)),255)
        self.assertEqual(alpha.getpixel((2,2)),255)
        with tempfile.TemporaryDirectory() as folder:
            source=Image.new('RGBA',(character.FRAME_W*character.COLUMNS,character.FRAME_H*6),(10,20,30,123))
            path=Path(folder)/'idle.png';source.save(path)
            frames=sprites.prepare_frames(path,2)
            self.assertEqual(len(frames),72)
            self.assertEqual(frames[0].getpixel((5,5))[3],123)

    def test_shipped_six_moods_and_72_frames_have_exterior_alpha(self):
        for mood in character.MOODS:
            with self.subTest(mood=mood):
                frames=sprites.prepare_frames(character.ASSET_DIR/(mood+'.png'),2)
                self.assertEqual(len(frames),72)
                self.assertEqual(frames[0].size,(120,167))
                self.assertEqual(frames[0].getpixel((0,0))[3],0)
                self.assertGreater(frames[0].getchannel('A').getextrema()[1],0)

    def test_preparation_cancels_and_worker_is_bounded(self):
        self.assertIsNone(sprites.prepare_frames(character.ASSET_DIR/'idle.png',1,lambda:True))
        with patch.object(sprites,'prepare_frames',return_value=[Image.new('RGBA',(2,2))]):
            worker=sprites.SpriteWorker(Path('unused'));self.addCleanup(worker.close)
            for mood in character.MOODS:wait_for(lambda mood=mood:worker.request(mood,1))
            self.assertEqual(len(worker._cache),2)
            worker.close();self.assertIsNone(worker.request('idle',1))

    def test_cached_mood_cancels_unneeded_preparation(self):
        entered,release=threading.Event(),threading.Event()
        frame=[Image.new('RGBA',(2,2))]
        def prepare(path,scale,stop):
            entered.set();release.wait(1)
            return None if stop() else frame
        with patch.object(sprites,'prepare_frames',side_effect=prepare):
            worker=sprites.SpriteWorker(Path('unused'));self.addCleanup(worker.close)
            with worker._condition:worker._cache[('idle',1)]=frame
            worker.request('review',1);self.assertTrue(entered.wait(1))
            self.assertIs(worker.request('idle',1),frame)
            release.set()
            wait_for(lambda:True if worker._working is None else None)
            self.assertNotIn(('review',1),worker._failed)
            self.assertIsNone(worker._pending)

    def test_missing_pillow_does_not_decode_a_full_sheet_on_tk_thread(self):
        canvas=Mock()
        with patch.object(Path,'is_file',return_value=True), patch.object(sprites,'Image',None), patch.object(character.tk,'PhotoImage') as photo:
            obj=character.CharacterView(canvas,canvas=canvas,background='#080f20')
            self.assertFalse(obj.available)
            photo.assert_called_once()
            self.assertNotIn('file',photo.call_args.kwargs)
            canvas.after.assert_not_called()
            obj.destroy()

    def test_animation_reuses_tk_image_and_does_not_prepare_on_main_thread(self):
        # The default missing-assets constructor does not spawn any worker.
        canvas=Mock();canvas.create_image.return_value=1
        with patch.object(character.tk,'PhotoImage'):
            obj=character.CharacterView(canvas,canvas=canvas,background='#080f20',asset_dir=Path('missing-assets'))
        obj._worker=Mock();obj._worker.request.return_value=[Image.new('RGBA',(2,2))]*72
        obj.mood='idle'
        with patch('PIL.ImageTk.PhotoImage') as photo:
            obj._draw();obj.index=1;obj._draw()
            photo.assert_called_once()
            photo.return_value.paste.assert_called_once()
            canvas.itemconfigure.assert_called_once()
        obj.destroy();obj._worker.close.assert_called_once()

class BoardTests(loop_tests.BoardTests):
    def test_5_20_50_cards_are_reused_with_no_unchanged_header_draw(self):
        for count in (5,20,50):
            board=self.make_board()
            model=lanes.build_lanes([], [run('testing',rid=f'20261022-000000-{i:06}') for i in range(count)])
            board.set_model(model);before=dict(board._widgets)
            with patch.object(board,'_update_headers') as headers:
                board.set_model(copy.deepcopy(model));headers.assert_not_called()
            self.assertEqual(board._widgets,before)

    def test_station_zero_hides_whole_area_and_restores_without_moving_ring(self):
        from scripts.dev_control_center import orchestrator_loop as loop
        board=self.make_board()
        items=dict(board._station_items)
        for item in items.values():self.assertEqual(board.loop.rows[item][1]['state'],'hidden')
        agent=Mock();board.attach_character(agent);agent.reset_mock()
        stages=['implementing','testing','reviewing','repairing','testing']
        model=lanes.build_lanes([], [run(stage,rid=f'20261022-000000-{i:06}') for i,stage in enumerate(stages)])
        board.loop.itemconfigure=Mock();board.loop.coords=Mock()
        with patch.object(board,'_draw_ring') as ring:
            board.set_model(model)
            for name in loop.STATIONS:
                board.loop.itemconfigure.assert_any_call(items[name],state='normal')
            self.assertEqual(len(board.cards['Testing']),2)
            first=board.cards['Testing'][0]
            board.set_model(copy.deepcopy(model))
            self.assertIs(board.cards['Testing'][0],first)
            for surface in board._station_surfaces.values():surface.set_visible.assert_called_once_with(True)
            saved=board.cards['Reviewing'][0]
            empty={name:[] for name in lanes.LANES}
            board.set_model(empty)
            for name in loop.STATIONS:
                board.loop.itemconfigure.assert_any_call(items[name],state='hidden')
                self.assertFalse(board._station_visible[name])
            board.set_model(model)
            self.assertEqual(board._station_items,items)
            self.assertEqual(len(board.cards['Testing']),2)
            self.assertTrue(saved.destroyed)
            ring.assert_not_called();agent.move.assert_not_called();board.loop.coords.assert_not_called()

    def test_station_removal_only_changes_that_station_visibility(self):
        board=self.make_board()
        model=lanes.build_lanes([], [run('testing'),run('reviewing',rid='20261022-000000-000002')])
        board.set_model(model)
        review=board.cards['Reviewing'][0]
        board.loop.itemconfigure=Mock()
        board.set_model(lanes.build_lanes([], [run('reviewing',rid='20261022-000000-000002')]))
        board.loop.itemconfigure.assert_called_once_with(board._station_items['Testing'],state='hidden')
        self.assertIs(board.cards['Reviewing'][0],review)
        self.assertTrue(board._station_visible['Reviewing'])

    def test_resize_burst_one_draw_same_size_cached_and_close_cancels(self):
        board=self.make_board()
        board.loop.after=Mock(return_value='resize');board.loop.after_cancel=Mock()
        with patch.object(board,'_draw_ring',wraps=board._draw_ring) as draw:
            for i in range(100):board._resize(SimpleNamespace(width=700+i,height=700))
            draw.assert_not_called()
            board._finish_resize();self.assertEqual(draw.call_count,1)
            count=len(board.loop.rows)
            board._draw_ring();self.assertEqual(len(board.loop.rows),count)
        board._resize(SimpleNamespace(width=900,height=800));board.close()
        board.loop.after_cancel.assert_called_with('resize')
        board._art.close.assert_called_once()

class TickTests(window_tests.FakeOrchestratorWindowCase):
    def test_combined_feed_and_run_tick_projects_once_and_idle_does_nothing(self):
        window=self.window
        window._workflow_feed.poll.return_value=([], 'ok')
        window.monitor.queue.put(dict(runs=[run('testing')],usage={},selected=None))
        with patch.object(window,'_refresh_board',wraps=window._refresh_board) as refresh:
            window._tick();self.assertEqual(refresh.call_count,1)
            window._workflow_feed.poll.return_value=None
            refresh.reset_mock();window._tick();refresh.assert_not_called()

    def test_standalone_snapshot_projects_once(self):
        with patch.object(self.window,'_refresh_board',wraps=self.window._refresh_board) as refresh:
            self.window.apply_snapshot(dict(runs=[run('testing')],usage={},selected=None))
            self.assertEqual(refresh.call_count,1)

class CanvasCardTests(unittest.TestCase):
    def make_card(self):
        obj=object.__new__(cards.CanvasCard)
        obj._closed=False;obj._selected=False;obj._hover=False;obj._focused=False
        obj._job=None;obj._painted=None;obj._accent='#2ba8ff';obj._width=179
        obj._art=Mock(available=True);obj._art.request.return_value=Image.new('RGB',(176,108))
        obj._image=1;obj._fallback=2;obj.coords=Mock();obj.itemconfigure=Mock();obj.after=Mock(return_value=3);obj.after_cancel=Mock()
        return obj

    def test_native_text_clipped_to_measured_width_and_no_extra_lines(self):
        obj=self.make_card();obj._text='長い題名'*40+'\n状態\n担当設定: codex\nP1'
        obj._font=Mock();obj._font.measure.side_effect=lambda text:len(text)*12
        obj._layout=object.__new__(cards.TextLayout);obj._layout.font=obj._font
        obj._layout.cache=__import__('collections').OrderedDict()
        obj._lines=[3,4,5,6];obj._labels()
        for call in obj.itemconfigure.call_args_list:
            self.assertLessEqual(len(call.kwargs['text'])*12,149)
        self.assertIn('…',obj.itemconfigure.call_args_list[0].kwargs['text'])

    def test_background_cached_selection_focus_hover_and_native_scroll_bindings_retained(self):
        obj=self.make_card()
        with patch.object(cards.ImageTk,'PhotoImage') as photo:
            obj._background();obj._background();self.assertEqual(photo.call_count,1)
            obj.state(['selected']);self.assertEqual(photo.call_count,2)
            obj.state(['!selected']);obj._focus(True);obj._highlight(True);obj._highlight(False)
            self.assertEqual(obj._painted[-1],'hover')
            obj.coords.assert_called_with(1,1.5,0)

    def test_text_cache_is_bounded_and_hit_does_not_measure_again(self):
        layout=object.__new__(cards.TextLayout)
        layout.cache=__import__('collections').OrderedDict()
        layout.font=Mock();layout.font.measure.side_effect=lambda text:len(text)*8
        layout.fit('same',100);count=layout.font.measure.call_count
        layout.fit('same',100);self.assertEqual(layout.font.measure.call_count,count)
        for i in range(600):layout.fit(str(i),100)
        self.assertEqual(len(layout.cache),512)

    def test_pending_art_retries_without_generating_pillow_on_ui_thread(self):
        obj=self.make_card();obj._art.request.return_value=None
        obj._background();obj.after.assert_called_once()
        with patch.object(art,'render_art') as render:
            obj._closed=True;obj._background();render.assert_not_called()


class PanelVisibilityTests(unittest.TestCase):
    def make_panel(self):
        obj=object.__new__(cards.PanelSurface)
        obj._closed=False;obj._visible=True;obj._job='previous'
        obj._kind='station';obj._accent='#2ba8ff';obj._size=(192,130);obj._inset=8
        obj._content=1;obj._painted=('station',192,130,'#2ba8ff','normal');obj._photo=object()
        obj._art=Mock();obj.itemconfigure=Mock();obj.after=Mock(return_value='next');obj.after_cancel=Mock()
        return obj

    def test_hide_cancels_pending_paint_and_restore_reuses_cached_image(self):
        obj=self.make_panel();photo=obj._photo
        obj.set_visible(False)
        obj.after_cancel.assert_called_once_with('previous')
        obj.after.assert_not_called()
        obj._paint();obj._art.request.assert_not_called()
        obj.set_visible(True);obj._paint()
        self.assertIs(obj._photo,photo);obj._art.request.assert_not_called()
        obj.after.assert_called_once()
        obj.set_visible(True);obj.after.assert_called_once()

    def test_hidden_resize_updates_dimensions_without_scheduling_render(self):
        obj=self.make_panel();obj._visible=False;obj._job=None
        obj._resize(SimpleNamespace(width=220,height=150))
        self.assertEqual(obj._size,(220,150))
        obj.after.assert_not_called();obj._art.request.assert_not_called()
        obj.itemconfigure.assert_called_once_with(1,width=204,height=134)
