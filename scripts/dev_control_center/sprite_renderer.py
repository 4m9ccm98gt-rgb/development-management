"""Prepare only the requested sprite in a worker; no Tk or business data."""
from collections import OrderedDict
import threading
import re
import math
from .orchestrator_art import Image, ImageDraw

def exterior_alpha(mask):
    """Flood fill horizontal spans, scanning pixels in C via regex (no per-pixel Python BFS)."""
    w, h = mask.size
    data = mask.tobytes()
    rows = [[(m.start(), m.end()) for m in re.finditer(b'\x00+', data[y * w:(y + 1) * w])] for y in range(h)]
    pending = [(y, i) for y, row in enumerate(rows) for i, (left, right) in enumerate(row) if y in (0, h - 1) or left == 0 or right == w]
    seen = set(pending)
    alpha = bytearray(b'\xff' * (w * h))
    while pending:
        y, i = pending.pop()
        left, right = rows[y][i]
        alpha[y * w + left:y * w + right] = b'\x00' * (right - left)
        for ny in (y - 1, y + 1):
            if not 0 <= ny < h:
                continue
            for ni, (a, b) in enumerate(rows[ny]):
                if a >= right:
                    break
                if b > left and (ny, ni) not in seen:
                    seen.add((ny, ni))
                    pending.append((ny, ni))
    return Image.frombytes('L', (w, h), bytes(alpha))

def frame_dimensions(scale):
    """Legacy reciprocal scale accepts finite fractional divisors as well."""
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .5 <= scale <= 4:
        raise ValueError('INVALID_CHARACTER_SCALE')
    from .character import FRAME_W, FRAME_H
    return math.ceil(FRAME_W/scale-1e-9), math.ceil(FRAME_H/scale-1e-9)


def prepare_frames(path, scale, stop=lambda: False):
    """Remove only navy connected to the frame exterior, preserving dark details."""
    from .character import FRAME_W, FRAME_H, COLUMNS, FRAME_COUNT
    size = frame_dimensions(scale)
    frames = []
    with Image.open(path) as sheet:
        sheet.load()
        palette = sheet.getpalette() if sheet.mode == 'P' and 'transparency' not in sheet.info else None
        lut = None
        if palette:
            lut = [0 if r <= 24 and g <= 30 and (b <= 55) else 255 for r, g, b in zip(palette[::3], palette[1::3], palette[2::3])]
            lut += [255] * (256 - len(lut))
        for index in range(FRAME_COUNT):
            if stop():
                return None
            x, y = (index % COLUMNS * FRAME_W, index // COLUMNS * FRAME_H)
            source = sheet.crop((x, y, x + FRAME_W, y + FRAME_H))
            rgba = source.convert('RGBA')
            if lut:
                mask = source.point(lut, 'L')
                rgba.putalpha(exterior_alpha(mask))
            if scale != 1:
                rgba = rgba.resize(size, Image.Resampling.LANCZOS)
            frames.append(rgba)
    return frames

class SpriteWorker:
    """Two prepared moods/scales at most, latest request only. No credentials/I/O outside assets."""

    def __init__(self, asset_dir):
        self.asset_dir = asset_dir
        self._cache = OrderedDict()
        self._failed = OrderedDict()
        self._pending = None
        self._desired = None
        self._working = None
        self._closed = False
        self._condition = threading.Condition()
        threading.Thread(target=self._work, name='dcc-ui-sprite', daemon=True).start()

    def request(self, mood, scale):
        frame_dimensions(scale)
        key = (mood, scale)
        with self._condition:
            if self._closed or key in self._failed:
                return None
            self._desired = key
            if key in self._cache:
                self._pending = None
                self._cache.move_to_end(key)
                return self._cache[key]
            self._pending = key if self._working != key else None
            self._condition.notify()
        return None

    def _work(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                key = self._pending
                self._pending = None
                self._working = key
            try:
                frames = prepare_frames(self.asset_dir / (key[0] + '.png'), key[1], lambda: self._closed or self._desired != key)
            except Exception:
                frames = None
            with self._condition:
                if self._closed:
                    return
                self._working = None
                if frames is None and self._desired == key:
                    self._failed[key] = None
                    while len(self._failed) > 8:
                        self._failed.popitem(last=False)
                if frames is not None:
                    self._cache[key] = frames
                    while len(self._cache) > 2:
                        self._cache.popitem(last=False)

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._cache.clear()
            self._condition.notify()
