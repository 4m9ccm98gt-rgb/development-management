"""Interactive Canvas cards with shared, asynchronously prepared decoration."""
from collections import OrderedDict
import tkinter as tk
from tkinter import font
from .orchestrator_art import BG, Image
if Image is not None:
    from PIL import ImageTk

class TextLayout:
    """Shared font and bounded measured-text cache for one stable card container."""
    def __init__(self, master):
        self.font = font.Font(master, family='Yu Gothic UI', size=9)
        self.cache = OrderedDict()

    def fit(self, text, width):
        key = (text, width)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        short = text
        if self.font.measure(text) > width and self.font.measure('…') > width:
            short = ''
        elif self.font.measure(text) > width:
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo+hi+1)//2
                if self.font.measure(text[:mid]+'…') <= width:
                    lo = mid
                else:
                    hi = mid-1
            short = text[:lo]+'…'
        self.cache[key] = short
        while len(self.cache) > 512:
            self.cache.popitem(last=False)
        return short

class CanvasCard(tk.Canvas):

    def __init__(self, master, *, command, accent, art, style=None):
        super().__init__(master, height=108, width=155, background=BG, highlightthickness=0, takefocus=True, cursor='hand2')
        self._command = command
        self._accent = accent
        self._art = art
        self._selected = False
        self._hover = False
        self._focused = False
        self._job = None
        self._closed = False
        self._photo = None
        self._painted = None
        self._text = ''
        self._width = 160
        if not hasattr(master, '_ui5_text_layout'):
            master._ui5_text_layout = TextLayout(master)
        self._layout = master._ui5_text_layout
        self._font = self._layout.font
        self._image = self.create_image(0, 0, anchor='nw')
        self._fallback = self.create_rectangle(5, 5, 155, 103, fill='#101c32', outline=accent)
        self._dot = self.create_oval(14, 14, 21, 21, fill=accent, outline='')
        self._lines = [self.create_text(29 if i == 0 else 15, 18 + i * 22, anchor='w', fill='#dfebff' if i < 2 else '#9caed2', font=self._font) for i in range(4)]
        self.bind('<Configure>', self._resize)
        self.bind('<Button-1>', lambda e: (self.focus_set(), self._command()))
        self.bind('<space>', lambda e: self._command())
        self.bind('<Enter>', lambda e: self._highlight(True))
        self.bind('<Leave>', lambda e: self._highlight(False))
        self.bind('<FocusIn>', lambda e: self._focus(True))
        self.bind('<FocusOut>', lambda e: self._focus(False))

    def _resize(self, event):
        width = max(40, event.width)
        if width != self._width:
            self._width = width
            self.coords(self._fallback, 5, 5, width - 5, 103)
            self._labels()
            self._background()

    def _labels(self):
        for i, item in enumerate(self._lines):
            line = (self._text.split('\n') + [''] * 4)[i]
            limit = max(5, self._width - (44 if i == 0 else 30))
            short = self._layout.fit(line, limit)
            self.itemconfigure(item, text=short)

    def configure(self, cnf=None, **kwargs):
        if 'text' in kwargs:
            text = kwargs.pop('text')
            if text != self._text:
                self._text = text
                self._labels()
        if cnf is not None or kwargs:
            return super().configure(cnf, **kwargs)
    config = configure

    def state(self, states):
        selected = self._selected
        if 'selected' in states:
            self._selected = True
        if '!selected' in states:
            self._selected = False
        if selected != self._selected:
            self._background()

    def _highlight(self, active):
        if self._hover != active:
            self._hover = active
            self._background()

    def _focus(self, active):
        if self._focused != active:
            self._focused = active
            self._background()

    def _background(self):
        if self._closed:
            return
        state = 'selected' if self._selected else 'hover' if self._hover or self._focused else 'normal'
        key = ('card', max(32, self._width // 16 * 16), 108, self._accent, state)
        if key == self._painted:
            return
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        raster = self._art.request(key)
        if raster is None:
            self.itemconfigure(self._fallback, outline=self._accent, width=2 if self._selected else 1)
            if self._art.available:
                self._job = self.after(60, self._background)
            return
        self._photo = ImageTk.PhotoImage(raster, master=self)
        self.coords(self._image, (self._width - key[1]) / 2, 0)
        self.itemconfigure(self._image, image=self._photo)
        self.itemconfigure(self._fallback, state='hidden')
        self._painted = key

    def destroy(self):
        self._closed = True
        if self._job is not None:
            self.after_cancel(self._job)
        self._photo = None
        super().destroy()

class PanelSurface(tk.Canvas):
    """Rounded static panel border; content widgets stay stable inside the inset."""

    def __init__(self, master, *, art, accent, kind='panel', inset=12, visible=True):
        from tkinter import ttk
        super().__init__(master, background=BG, highlightthickness=0, width=210, height=580)
        self._art = art
        self._accent = accent
        self._kind = kind
        self._inset = inset
        self._visible = visible
        self._job = None
        self._closed = False
        self._photo = None
        self._painted = None
        self._size = (210, 580)
        self._image = self.create_image(0, 0, anchor='nw')
        self.content = ttk.Frame(self, style='OrchestratorLoop.TFrame')
        self._content = self.create_window(inset, inset, window=self.content, anchor='nw')
        self.bind('<Configure>', self._resize)

    def _resize(self, event):
        size = (max(40, event.width), max(40, event.height))
        if size == self._size and self._painted is not None:
            return
        self._size = size
        self.itemconfigure(self._content, width=max(10, size[0] - 2*self._inset), height=max(10, size[1] - 2*self._inset))
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(90, self._paint) if self._visible else None

    def set_visible(self, visible):
        if self._closed or self._visible == visible:
            return
        self._visible = visible
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(90, self._paint) if visible else None

    def _paint(self):
        self._job = None
        if self._closed or not self._visible:
            return
        key = (self._kind, *self._size, self._accent, 'normal')
        if key == self._painted:
            return
        raster = self._art.request(key)
        if raster is None:
            if self._art.available:
                self._job = self.after(60, self._paint)
            return
        self._photo = ImageTk.PhotoImage(raster, master=self)
        self.itemconfigure(self._image, image=self._photo)
        self._painted = key

    def close(self):
        self._closed = True
        if self._job is not None:
            self.after_cancel(self._job)
        self._photo = None
