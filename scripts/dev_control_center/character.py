"""Animated idle character for the Orchestrator window.

The character is a loop of pre-rendered frames (one sprite sheet per mood under
`assets/character/`). Tk only copies one frame per tick, so nothing heavy runs on the UI
thread and the animation never touches a run. Missing or unreadable assets simply hide the
character; they must never break the window.

Sprite sheet layout: `COLUMNS` frames per row, `FRAME_COUNT` frames of `FRAME_W` x `FRAME_H`,
played at `FPS` as a seamless loop.
"""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
import base64
import struct
import zlib

from tools.ai_orchestrator import runstate as rs

ASSET_DIR = Path(__file__).with_name("assets") / "character"
FRAME_W = 240
FRAME_H = 333
COLUMNS = 12
FRAME_COUNT = 72
FPS = 12

IDLE, IMPLEMENTING, TESTING, REVIEWING, COMPLETED, ERROR = "idle", "impl", "test", "review", "done", "error"
MOODS = (IDLE, IMPLEMENTING, TESTING, REVIEWING, COMPLETED, ERROR)


def transparent_sprite(data):
    """In-memory palette key for shipped opaque sprites; never rewrite assets.

    Only near-navy background palette entries become transparent. This cheap
    per-sheet operation preserves encoded frames and avoids per-pixel Tk calls.
    Very dark costume pixels may share the key (a known rendering limitation).
    """
    if data[:8] != b'\x89PNG\r\n\x1a\n' or len(data) < 33 or data[25] != 3:
        return data
    pos, chunks, alpha = 8, [], None
    while pos+12 <= len(data):
        size = struct.unpack('>I', data[pos:pos+4])[0]
        end = pos+size+12
        if end > len(data):
            return data
        kind, value = data[pos+4:pos+8], data[pos+8:pos+8+size]
        if kind == b'tRNS':
            return data  # already has authored transparency
        if kind == b'PLTE':
            alpha = bytes(0 if r <= 24 and g <= 30 and b <= 55 else 255 for r, g, b in zip(value[0::3], value[1::3], value[2::3]))
        if kind == b'IDAT' and alpha is not None:
            payload = b'tRNS'+alpha
            chunks.append(struct.pack('>I', len(alpha))+payload+struct.pack('>I', zlib.crc32(payload)))
            alpha = None
        chunks.append(data[pos:end])
        pos = end
    return data[:8]+b''.join(chunks)

_STAGE_MOOD = {
    rs.IMPLEMENTING: IMPLEMENTING,
    rs.REPAIRING: IMPLEMENTING,
    rs.TESTING: TESTING,
    rs.REVIEWING: REVIEWING,
    rs.FINALIZING: REVIEWING,
    rs.COMPLETED: COMPLETED,
    rs.NEEDS_HUMAN: ERROR,
    rs.FAILED: ERROR,
}


def mood_for(stage: str | None, liveness: str | None) -> str:
    """Map a run's stage / liveness to the character mood. No run selected -> idle."""
    if liveness in (rs.LIVE_LOST, rs.LIVE_UNRESPONSIVE):
        return ERROR
    return _STAGE_MOOD.get(stage or "", IDLE)


class CharacterView:
    """A Canvas that plays the sprite sheet of the current mood."""

    def __init__(self, master: tk.Misc, *, background: str, asset_dir: Path = ASSET_DIR, scale: int = 1,
                 canvas=None, position=(0, 0)) -> None:
        if type(scale) is not int or scale < 1:
            raise ValueError('INVALID_CHARACTER_SCALE')
        self.scale = scale
        self.asset_dir = Path(asset_dir)
        self._owns_widget = canvas is None
        self.widget = canvas if canvas is not None else tk.Canvas(master, width=(FRAME_W+scale-1)//scale, height=(FRAME_H+scale-1)//scale, background=background,
                                highlightthickness=0, borderwidth=0)
        self._frame = tk.PhotoImage(master=self.widget, width=(FRAME_W+scale-1)//scale, height=(FRAME_H+scale-1)//scale)
        self._image_id = self.widget.create_image(*position, image=self._frame, anchor='nw' if self._owns_widget else 'center')
        self._sheet: tk.PhotoImage | None = None
        self._after_id: str | None = None
        self._destroyed = False
        self.mood: str | None = None
        self.index = 0
        self.available = all((self.asset_dir / f"{mood}.png").is_file() for mood in MOODS)
        if self.available:
            self.set_mood(IDLE)
            self._after_id = self.widget.after(1000 // FPS, self._tick)

    def set_mood(self, mood: str) -> None:
        if self._destroyed or not self.available:
            return
        mood = mood if mood in MOODS else IDLE
        if mood == self.mood:
            return
        sheet = self._load(mood)
        if sheet is None:
            return
        # Keep only the playing sheet in memory (each one is ~23 MB decoded).
        self._sheet = sheet
        self.mood = mood
        self.index = 0
        self._draw()

    def _load(self, mood: str) -> tk.PhotoImage | None:
        try:
            if self._owns_widget:
                sheet = tk.PhotoImage(master=self.widget, file=str(self.asset_dir / f"{mood}.png"))
            else:
                data = transparent_sprite((self.asset_dir / f'{mood}.png').read_bytes())
                sheet = tk.PhotoImage(master=self.widget, data=base64.b64encode(data), format='png')
        except (tk.TclError, OSError):
            return None
        if sheet.width() < FRAME_W * COLUMNS or sheet.height() < FRAME_H * (-(-FRAME_COUNT // COLUMNS)):
            return None
        return sheet

    def move(self, x, y):
        if not self._destroyed:
            self.widget.coords(self._image_id, x, y)

    def set_scale(self, scale):
        if type(scale) is not int or not 1 <= scale <= 4 or self._destroyed or self.scale == scale:
            return
        self.scale = scale
        self._frame = tk.PhotoImage(master=self.widget, width=(FRAME_W+scale-1)//scale, height=(FRAME_H+scale-1)//scale)
        self.widget.itemconfigure(self._image_id, image=self._frame)
        if self._owns_widget:
            self.widget.configure(width=(FRAME_W+scale-1)//scale, height=(FRAME_H+scale-1)//scale)
        self._draw()

    def _draw(self) -> None:
        if self._sheet is None:
            return
        x = (self.index % COLUMNS) * FRAME_W
        y = (self.index // COLUMNS) * FRAME_H
        self._frame.tk.call(self._frame, "copy", self._sheet, "-from", x, y, x + FRAME_W, y + FRAME_H, "-to", 0, 0,
                            '-compositingrule', 'set', '-subsample', self.scale, self.scale)

    def _tick(self) -> None:
        if self._destroyed:
            return
        try:
            if not self.widget.winfo_exists():
                return
            self.index = (self.index + 1) % FRAME_COUNT
            self._draw()
            self._after_id = self.widget.after(1000 // FPS, self._tick)
        except tk.TclError:
            self._after_id = None

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self._after_id = None
        self._sheet = None
        self._frame = None
        try:
            if self._owns_widget:
                self.widget.destroy()
            else:
                self.widget.delete(self._image_id)
        except tk.TclError:
            pass
