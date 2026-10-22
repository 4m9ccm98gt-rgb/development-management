"""Bounded, background Pillow decoration rendering. Workers never call Tk."""
from collections import OrderedDict
import math
import threading
try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    Image = ImageDraw = ImageFilter = None
BG = '#080f20'

def render_art(key):
    kind, w, h, accent, state = key
    if not (0 < w <= 4096 and 0 < h <= 4096 and w*h <= 4_000_000):
        raise ValueError('ART_SIZE_LIMIT')
    s = 2
    canvas = Image.new('RGBA', (w * s, h * s), BG)
    draw = ImageDraw.Draw(canvas)
    if kind in ('card', 'panel', 'station'):
        margin, radius = (5 * s, 12 * s)
        mask = Image.new('L', canvas.size)
        ImageDraw.Draw(mask).rounded_rectangle((margin, margin, w * s - margin - 1, h * s - margin - 1), radius, fill=255)
        glow = Image.new('RGBA', canvas.size, accent)
        glow.putalpha(mask.filter(ImageFilter.GaussianBlur(4 * s)).point(lambda x: x // (5 if state == 'normal' else 3)))
        canvas = Image.alpha_composite(canvas, glow)
        gradient = Image.new('RGBA', canvas.size)
        gd = ImageDraw.Draw(gradient)
        boost = 10 if state != 'normal' else 0
        rgb = bytes.fromhex(accent[1:]) if kind == 'station' else None
        for y in range(h * s):
            t = y / max(1, h * s - 1)
            base = (int(22 - 11*t)+boost, int(37 - 15*t)+boost, int(66 - 26*t)+boost)
            if kind == 'station':
                tint = .16 - .10*t
                base = tuple(round(value*(1-tint)+channel*tint) for value, channel in zip(base, rgb))
            gd.line((0, y, w*s, y), fill=(*base, 255))
        canvas.paste(gradient, (0, 0), mask)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((margin, margin, w * s - margin - 1, h * s - margin - 1), radius, outline=accent, width=(2 if state == 'selected' else 1) * s)
        if kind == 'card':
            draw.rounded_rectangle((margin + 2 * s, margin + 10 * s, margin + 4 * s, h * s - margin - 10 * s), 2 * s, fill=accent)
    else:
        cx, cy = (w * 0.5, h * 0.53)
        r = max(100, min(w * 0.46, (h - 85) * 0.47))
        glow = Image.new('RGBA', canvas.size)
        gd = ImageDraw.Draw(glow)
        colors = ['#2ba8ff', '#a47aff', '#25dbe5', '#f3b666']
        points = lambda a, rr: ((cx + rr * math.cos(math.radians(a))) * s, (cy - rr * math.sin(math.radians(a))) * s)
        for index, start in enumerate((127, 37, -53, -143)):
            a = tuple(bytes.fromhex(colors[index][1:]))
            b = tuple(bytes.fromhex(colors[(index + 1) % 4][1:]))
            for j in range(70):
                color = tuple((round(a[k] + (b[k] - a[k]) * j / 70) for k in range(3))) + (210,)
                p, q = (points(start - j, r), points(start - j - 1, r))
                gd.line((*p, *q), fill=color, width=5 * s)
            tip = points(start - 70, r)
            left = points(start - 66, r - 10)
            right = points(start - 66, r + 10)
            gd.polygon((tip, left, right), fill=colors[(index + 1) % 4])
        canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(7 * s)))
        canvas = Image.alpha_composite(canvas, glow)
        draw = ImageDraw.Draw(canvas)
        for rr in (r * 0.78, r * 1.05):
            draw.ellipse(((cx - rr) * s, (cy - rr) * s, (cx + rr) * s, (cy + rr) * s), outline='#1c3152', width=s)
        badge_layer = Image.new('RGBA', canvas.size)
        bd = ImageDraw.Draw(badge_layer)
        panel_h = max(75, min(155, (h-150)*.27))
        for index, angle in enumerate((135,45,-45,-135)):
            x,y = points(angle,r*.83)
            y = min(y/s,h-panel_h-58) if angle < 0 else max(108,y/s)
            y *= s
            bd.ellipse((x-44*s,y-44*s,x+44*s,y+44*s),fill=colors[index])
        haze = badge_layer.filter(ImageFilter.GaussianBlur(8*s))
        haze.putalpha(haze.getchannel('A').point(lambda value:value//3))
        canvas = Image.alpha_composite(canvas,haze)
        draw = ImageDraw.Draw(canvas)
        for index, angle in enumerate((135,45,-45,-135)):
            x,y = points(angle,r*.83)
            y = (min(y/s,h-panel_h-58) if angle < 0 else max(108,y/s))*s
            draw.ellipse((x-42*s,y-42*s,x+42*s,y+42*s),fill='#101a35',outline=colors[index],width=2*s)
    return canvas.convert('RGB').resize((w, h), Image.Resampling.LANCZOS)

class ArtWorker:
    """At most 24 requests/images, 8M cached pixels; one daemon worker."""

    def __init__(self):
        self.available = Image is not None
        self._condition = threading.Condition()
        self._pending = OrderedDict()
        self._cache = OrderedDict()
        self._pixels = 0
        self._closed = False
        self._working = None
        if self.available:
            threading.Thread(target=self._work, name='dcc-ui-art', daemon=True).start()

    def request(self, key):
        if not self.available:
            return None
        with self._condition:
            if self._closed:
                return None
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            if self._working == key:
                return None
            if key[0] != 'card':
                # Keep only the latest dimensions for each decorative surface.
                for pending in list(self._pending):
                    if pending[0] == key[0] and pending[3] == key[3]:
                        self._pending.pop(pending)
            self._pending[key] = None
            while len(self._pending) > 24:
                self._pending.popitem(last=False)
            self._condition.notify()
        return None

    def _work(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if self._closed:
                    return
                key, _ = self._pending.popitem(last=False)
                self._working = key
            try:
                result = render_art(key)
            except Exception:
                result = None
                self.available = False
            with self._condition:
                if self._closed:
                    return
                self._working = None
                if result is not None and key not in self._cache:
                    self._cache[key] = result
                    self._pixels += result.width * result.height
                    while len(self._cache) > 24 or self._pixels > 8000000:
                        _, old = self._cache.popitem(last=False)
                        self._pixels -= old.width * old.height

    def close(self):
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._cache.clear()
            self._pixels = 0
            self._condition.notify()
