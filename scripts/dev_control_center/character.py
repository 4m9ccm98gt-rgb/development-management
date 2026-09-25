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

from tools.ai_orchestrator import runstate as rs

ASSET_DIR = Path(__file__).with_name("assets") / "character"
FRAME_W = 240
FRAME_H = 333
COLUMNS = 12
FRAME_COUNT = 72
FPS = 12

IDLE, IMPLEMENTING, TESTING, REVIEWING, COMPLETED, ERROR = "idle", "impl", "test", "review", "done", "error"
MOODS = (IDLE, IMPLEMENTING, TESTING, REVIEWING, COMPLETED, ERROR)

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

    def __init__(self, master: tk.Misc, *, background: str, asset_dir: Path = ASSET_DIR) -> None:
        self.asset_dir = Path(asset_dir)
        self.widget = tk.Canvas(master, width=FRAME_W, height=FRAME_H, background=background,
                                highlightthickness=0, borderwidth=0)
        self._frame = tk.PhotoImage(master=self.widget, width=FRAME_W, height=FRAME_H)
        self.widget.create_image(0, 0, image=self._frame, anchor="nw")
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
            sheet = tk.PhotoImage(master=self.widget, file=str(self.asset_dir / f"{mood}.png"))
        except (tk.TclError, OSError):
            return None
        if sheet.width() < FRAME_W * COLUMNS or sheet.height() < FRAME_H * (-(-FRAME_COUNT // COLUMNS)):
            return None
        return sheet

    def _draw(self) -> None:
        if self._sheet is None:
            return
        x = (self.index % COLUMNS) * FRAME_W
        y = (self.index // COLUMNS) * FRAME_H
        self._frame.tk.call(self._frame, "copy", self._sheet, "-from", x, y, x + FRAME_W, y + FRAME_H, "-to", 0, 0)

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
            self.widget.destroy()
        except tk.TclError:
            pass
