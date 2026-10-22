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
