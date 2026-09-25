"""Orchestrator idle character: stage -> mood mapping, sprite playback, missing-asset fallback, window wiring."""

from __future__ import annotations

import gc
from pathlib import Path
import struct
import tempfile
import tkinter as tk
import unittest

from scripts.dev_control_center import character as ch
from tools.ai_orchestrator import runstate as rs


class MoodMappingTests(unittest.TestCase):
    def test_stages_map_to_moods(self):
        cases = {
            rs.CREATED: ch.IDLE, rs.PREFLIGHT: ch.IDLE, rs.IMPLEMENTING: ch.IMPLEMENTING,
            rs.REPAIRING: ch.IMPLEMENTING, rs.TESTING: ch.TESTING, rs.REVIEWING: ch.REVIEWING,
            rs.FINALIZING: ch.REVIEWING, rs.COMPLETED: ch.COMPLETED, rs.NEEDS_HUMAN: ch.ERROR,
            rs.FAILED: ch.ERROR, rs.STOPPING: ch.IDLE, rs.STOPPED: ch.IDLE,
        }
        for stage, mood in cases.items():
            with self.subTest(stage=stage):
                self.assertEqual(ch.mood_for(stage, rs.LIVE_RUNNING), mood)

    def test_lost_or_unresponsive_worker_shows_error_whatever_the_stage(self):
        for liveness in (rs.LIVE_LOST, rs.LIVE_UNRESPONSIVE):
            self.assertEqual(ch.mood_for(rs.TESTING, liveness), ch.ERROR)

    def test_no_run_is_idle(self):
        self.assertEqual(ch.mood_for(None, None), ch.IDLE)
        self.assertEqual(ch.mood_for("unknown-stage", rs.LIVE_RUNNING), ch.IDLE)


class ShippedAssetTests(unittest.TestCase):
    def test_every_mood_has_a_full_sprite_sheet(self):
        rows = -(-ch.FRAME_COUNT // ch.COLUMNS)
        for mood in ch.MOODS:
            with self.subTest(mood=mood):
                data = (ch.ASSET_DIR / f"{mood}.png").read_bytes()[:24]
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                width, height = struct.unpack(">II", data[16:24])
                self.assertEqual((width, height), (ch.FRAME_W * ch.COLUMNS, ch.FRAME_H * rows))


class ViewTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self._destroy)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = Path(self.tmp.name)

    def _destroy(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        gc.collect()

    def write_sheets(self, moods=ch.MOODS):
        rows = -(-ch.FRAME_COUNT // ch.COLUMNS)
        for index, mood in enumerate(moods):
            img = tk.PhotoImage(master=self.root, width=ch.FRAME_W * ch.COLUMNS, height=ch.FRAME_H * rows)
            img.put(f"#{index * 40:02x}2040", to=(0, 0, ch.FRAME_W * ch.COLUMNS, ch.FRAME_H * rows))
            img.write(str(self.assets / f"{mood}.png"), format="png")

    def test_missing_assets_hide_the_character_without_errors(self):
        self.write_sheets(moods=(ch.IDLE,))
        view = ch.CharacterView(self.root, background="#000000", asset_dir=self.assets)
        self.assertFalse(view.available)
        view.set_mood(ch.TESTING)
        self.assertIsNone(view.mood)
        view.destroy()

    def test_plays_frames_and_switches_mood(self):
        self.write_sheets()
        view = ch.CharacterView(self.root, background="#000000", asset_dir=self.assets)
        view.widget.pack()
        self.assertTrue(view.available)
        self.assertEqual(view.mood, ch.IDLE)
        view._tick()
        view._tick()
        self.assertEqual(view.index, 2)
        view.set_mood(ch.COMPLETED)
        self.assertEqual((view.mood, view.index), (ch.COMPLETED, 0))
        view.set_mood("not-a-mood")
        self.assertEqual(view.mood, ch.IDLE)
        for _ in range(ch.FRAME_COUNT):
            view._tick()
        self.assertEqual(view.index, 0)  # loops
        view.destroy()
        view.destroy()  # idempotent
        view._tick()    # a late tick after destroy is harmless

    def test_unreadable_sheet_keeps_the_previous_mood(self):
        self.write_sheets()
        (self.assets / f"{ch.ERROR}.png").write_bytes(b"not a png")
        view = ch.CharacterView(self.root, background="#000000", asset_dir=self.assets)
        view.set_mood(ch.ERROR)
        self.assertEqual(view.mood, ch.IDLE)
        view.destroy()


if __name__ == "__main__":
    unittest.main()
