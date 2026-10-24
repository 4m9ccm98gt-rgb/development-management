"""Reference-led circular UI. Positions show observed stages, never transitions.

The four-lane projection remains the operational boundary; this module only
partitions display cards. Feedback contains failure/stop confirmation, not an
invented human reply. Archive is a view filter, never a Workflow operation.
"""
import math
import tkinter as tk
from tkinter import ttk

from .orchestrator_lanes import LaneBoard, LANES, human_row_lines
from .orchestrator_art import ArtWorker, Image
from .orchestrator_cards import CanvasCard, PanelSurface
from .character_layout import character_display_scale
if Image is not None:
    from PIL import ImageTk

BG = '#080f20'
SURFACE = '#101c32'
FG = '#dfebff'
MUTED = '#9caed2'
SIMPLE_RENDERING_NOTICE = ' ／ 装飾未取得：簡易描画'
COLORS = dict(Implementing='#2ba8ff', Testing='#a47aff', Reviewing='#25dbe5', Repairing='#f3b666',
              ManagerPlan='#7086ff', ManagerWait='#7086ff', Approval='#a47aff', Decision='#a47aff',
              Feedback='#f3b666', Archive='#66799e')
LABELS = dict(ManagerPlan='計画・開始条件の確認', ManagerWait='待機・確認待ち', Implementing='実装', Testing='テスト（システム工程）',
              Reviewing='レビュー・検証', Repairing='修正', Approval='承認・候補確認待ち', Decision='判断待ち',
              Feedback='フィードバック／失敗・停止の確認', Archive='Archive（処理済み）')
GROUPS = tuple(LABELS)
STATIONS = ('Implementing', 'Testing', 'Reviewing', 'Repairing')


def project_loop(model, previous=None):
    """Pure, unique partition. Unknown data is never promoted into a loop stage.

    During refresh keep prior placement with explicit PX/stale labeling. No
    observer can infer a past transfer from these architectural arrows.
    """
    result = {name: [] for name in GROUPS}
    seen = set()
    for lane in LANES:
        for original in model[lane]:
            if original['key'] in seen:
                continue
            seen.add(original['key'])
            stage = original.get('observed_stage', 'unknown')
            status = original.get('workflow_status')
            group = 'ManagerWait'
            if original.get('stale'):
                old = (previous or {}).get(original['key'])
                group = old[0] if old and old[0] in result else 'ManagerWait'
            elif original.get('task_unknown') or original.get('priority') == 'PX':
                pass
            elif lane == 'Human':
                group = ('Approval' if status in ('proposed', 'candidate_ready') or stage == 'completed' else
                         'Feedback' if status == 'failed' or stage in ('failed', 'stopped') else 'Decision')
            elif status in ('landed', 'cancelled') or stage == 'completed':
                group = 'Archive'
            elif stage in ('implementing', 'testing', 'reviewing', 'repairing', 'finalizing'):
                group = dict(implementing='Implementing', testing='Testing', reviewing='Reviewing',
                             repairing='Repairing', finalizing='Reviewing')[stage]
            elif original.get('cause') == 'START' or stage in ('created', 'preflight'):
                group = 'ManagerPlan'
            result[group].append(dict(original, lane=group, logical_lane=lane))
    return result


def configure_loop_styles(style):
    style.configure('OrchestratorLoop.TFrame', background=BG)
    style.configure('OrchestratorLoop.Toolbar.TFrame', background=BG)
    style.configure('OrchestratorLoop.TLabel', background=BG, foreground=FG)
    style.configure('OrchestratorLoop.Title.TLabel', background=BG, foreground=FG, font=('Segoe UI', 17, 'bold'))
    style.configure('OrchestratorLoop.Section.TLabel', background=BG, foreground=MUTED)
    # Native Windows buttons may ignore colors. Copy drawing elements locally.
    from .ui_theme import _copy
    for part in ('border', 'focus', 'padding', 'label'):
        _copy(style, 'OrchestratorLoop.Button.'+part, 'Button.'+part)
    for group, accent in COLORS.items():
        name = f'Loop{group}.TButton'
        style.layout(name, [('OrchestratorLoop.Button.border', dict(sticky='nswe', children=[
            ('OrchestratorLoop.Button.focus', dict(sticky='nswe', children=[
                ('OrchestratorLoop.Button.padding', dict(sticky='nswe', children=[
                    ('OrchestratorLoop.Button.label', dict(sticky='nswe'))]))]))]))])
        style.configure(name, background=SURFACE, foreground=FG, bordercolor=accent, lightcolor=accent,
                        darkcolor=accent, borderwidth=1, relief='solid', padding=(10, 8))
        style.map(name, background=[('selected', '#223354'), ('active', '#1a2b48'), ('!active', SURFACE)],
                  foreground=[('disabled', MUTED), ('!disabled', FG)], bordercolor=[('!disabled', accent)])


class LoopBoard(LaneBoard):
    groups = GROUPS
    group_labels = LABELS
    # UI-E1: the right-side Human panel's own sections (not Archive's own operational meaning --
    # Archive is still just a view filter; it gets the same row-scoped copy button as the others).
    human_groups = ('Approval', 'Decision', 'Feedback', 'Archive')

    def __init__(self, parent, on_select, *, on_copy_report=None):
        configure_loop_styles(ttk.Style(parent))
        self.frame = ttk.Frame(parent, style='OrchestratorLoop.TFrame')
        self.frame.rowconfigure(0, weight=1)
        for col, weight, minimum in ((0, 2, 200), (1, 6, 500), (2, 2, 210)):
            self.frame.columnconfigure(col, weight=weight, minsize=minimum)
        self._art = ArtWorker()
        self._resize_job = None
        self._art_job = None
        self._closed = False
        self._ring_photo = None
        self._ring_key = None
        self._drawn_size = None
        self._last_source = None
        self._header_text = {}
        self._surfaces = []
        self.on_select = on_select
        self._on_copy_report = on_copy_report
        self.headers, self.bodies, self.canvases, self.cards = {}, {}, {}, {}
        self._widgets, self._data, self._positions, self._report_buttons = {}, {}, {}, {}
        self._last = None
        self._selected_key = None
        self._archive_open = False
        self._character = None
        self._size = (650, 630)
        self.hint = ttk.Label(self.frame, style='OrchestratorLoop.TLabel', wraplength=1100,
            text=self._hint_text('円形矢印は工程構成です。実際の失敗・移動履歴を示しません。Manager AIの自律実行は未実装です。'))
        self.hint.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(6, 0))
        left, left_canvas = self._side(0, 'Manager', '読み取り・分析・提案のみ／自動指揮なし')
        self._section(left, left_canvas, 'ManagerPlan')
        self._section(left, left_canvas, 'ManagerWait')
        right, right_canvas = self._side(2, 'Human', '必要時のみの判断・確認先')
        for name in ('Approval', 'Decision', 'Feedback', 'Archive'):
            self._section(right, right_canvas, name, collapsible=name == 'Archive')
        self.loop = tk.Canvas(self.frame, background=BG, highlightthickness=0, width=600, height=580)
        self.loop.grid(row=0, column=1, sticky='nsew', padx=8)
        loop_scroll = ttk.Scrollbar(self.frame, orient='vertical', command=self.loop.yview)
        loop_scroll.grid(row=0, column=1, sticky='nse')
        self.loop.configure(yscrollcommand=loop_scroll.set)
        self.loop.bind('<MouseWheel>', lambda e: self.loop.yview_scroll(-int(e.delta/120), 'units'))
        self.loop.bind('<Configure>', self._resize)
        self._station_items = {}
        self._station_surfaces = {}
        for name in STATIONS:
            surface = PanelSurface(self.loop, art=self._art, accent=COLORS[name], kind='station', inset=8)
            self._surfaces.append(surface)
            self._station_surfaces[name] = surface
            panel = surface.content
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(1, weight=1)
            label = ttk.Label(panel, style='OrchestratorLoop.Section.TLabel', wraplength=165)
            label.grid(row=0, column=0, columnspan=2, sticky='ew')
            c = tk.Canvas(panel, background=BG, highlightthickness=0, width=160, height=120)
            c.grid(row=1, column=0, sticky='nsew')
            scroll = ttk.Scrollbar(panel, orient='vertical', command=c.yview)
            scroll.grid(row=1, column=1, sticky='ns')
            c.configure(yscrollcommand=scroll.set)
            body = self._scroll_body(c)
            self.headers[name], self.bodies[name], self.canvases[name], self.cards[name] = label, body, c, []
            self._station_items[name] = self.loop.create_window(0, 0, anchor='nw', window=surface, state='normal')
        self.character_host = self.loop
        self.character_background = BG
        self.review_header = self.frame  # compatibility only; no second character
        self._update_headers()
        self._draw_ring()

    def _scroll_body(self, canvas):
        body = ttk.Frame(canvas, style='OrchestratorLoop.TFrame')
        item = canvas.create_window(0, 0, anchor='nw', window=body)
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units'))
        return body

    def _side(self, col, title, note):
        surface = PanelSurface(self.frame, art=self._art, accent='#7086ff' if col == 0 else '#a47aff')
        surface.grid(row=0, column=col, sticky='nsew')
        self._surfaces.append(surface)
        panel = surface.content
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        ttk.Label(panel, text=title, style='OrchestratorLoop.Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(panel, text=note, style='OrchestratorLoop.Section.TLabel', wraplength=210).grid(row=1, column=0, sticky='ew', pady=8)
        canvas = tk.Canvas(panel, background=BG, highlightthickness=0, width=200)
        canvas.grid(row=2, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(panel, orient='vertical', command=canvas.yview)
        scroll.grid(row=2, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scroll.set)
        return self._scroll_body(canvas), canvas

    def _section(self, parent, canvas, name, collapsible=False):
        section = ttk.Frame(parent, style='OrchestratorLoop.TFrame')
        section.pack(fill='x', pady=(4, 8))
        if collapsible:
            label = ttk.Button(section, command=self.toggle_archive, style='LoopArchive.TButton')
        else:
            label = ttk.Label(section, style='OrchestratorLoop.Section.TLabel', wraplength=200)
        label.pack(fill='x', pady=6)
        body = ttk.Frame(section, style='OrchestratorLoop.TFrame')
        if not collapsible:
            body.pack(fill='x')
        self.headers[name], self.bodies[name], self.canvases[name], self.cards[name] = label, body, canvas, []

    def toggle_archive(self):
        self._archive_open = not self._archive_open
        if self._archive_open:
            self.bodies['Archive'].pack(fill='x')
        else:
            self.bodies['Archive'].pack_forget()
        self._update_headers()

    def _card_text(self, card, name, title):
        if name in self.human_groups:
            # UI-E1 (C2): repo / start・stop / elapsed・state -- never the assigned AI.
            return '\n'.join(human_row_lines(card, title))
        ai = card.get('reviewer_ai') if name == 'Reviewing' else card.get('assigned_ai')
        ai = ai if ai in ('codex', 'claude') else '未設定・確認待ち'
        label = 'システム工程' if name == 'Testing' else '担当設定: '+ai
        return f"{card['title']}\n{card['state']}\n{label}\n{card['priority']} ／ 確認用カード"

    def _make_card(self, name, key):
        return CanvasCard(self.bodies[name], accent=COLORS[name], art=self._art, command=lambda:self._activate(key))

    def _card_style(self, name):
        return f'Loop{name}.TButton'

    def set_model(self, model):
        if model == self._last_source:
            return
        self._last_source = {group: [dict(card) for card in cards] for group, cards in model.items()}
        grouped = project_loop(model, self._positions)
        super().set_model(grouped)
        self.hint.configure(text=self._hint_text('円形矢印＝工程構成（移動履歴ではありません）。Testsはシステム工程。Manager AIの自律実行は未実装。'))
        self._update_headers()

    def _update_headers(self):
        for name in GROUPS:
            values = [c for c in self._data.values() if c['lane'] == name]
            uncertain = sum(c.get('stale', False) or c.get('task_unknown', False) or c['priority'] == 'PX' for c in values)
            mark = ('▼ ' if self._archive_open else '▶ ') if name == 'Archive' else ''
            text = f'{mark}{LABELS[name]}  {len(values)}件' + (f'／未確認 {uncertain}' if uncertain else '')
            if self._header_text.get(name) != text:
                self.headers[name].configure(text=text)
                self._header_text[name] = text

    def _hint_text(self, text):
        return text + (SIMPLE_RENDERING_NOTICE if not self._art.available else '')

    def _focus_card(self, button, canvas, card):
        self.hint.configure(text=self._hint_text(card['hint']))
        bounds = canvas.bbox('all')
        if bounds:
            y = button.winfo_rooty() - canvas.winfo_rooty() + canvas.canvasy(0)
            top = canvas.canvasy(0)
            if y < top or y+button.winfo_height() > top+canvas.winfo_height():
                canvas.yview_moveto(max(0, y)/max(1, bounds[3]))

    def attach_character(self, character):
        self._character = character
        self._position_character()

    def _position_character(self):
        if self._character is not None:
            w, h = self._size
            self._character.set_display_scale(character_display_scale(w, h))
            self._character.move(w/2, h*.53)

    def _resize(self, event):
        self._pending_size = (max(500, event.width), max(630, event.height))
        if self._pending_size == self._size:
            return
        if self._resize_job is not None:
            self.loop.after_cancel(self._resize_job)
        self._resize_job = self.loop.after(90, self._finish_resize)

    def _finish_resize(self):
        self._resize_job = None
        if self._closed or self._pending_size == self._size:
            return
        self._size = self._pending_size
        self.loop.configure(scrollregion=(0, 0, *self._size))
        self._draw_ring()

    def _paint_art(self):
        self._art_job = None
        if self._closed or not self._art.available:
            return
        key = ('ring', *self._size, '#000000', 'normal')
        if self._ring_key == key:
            return
        raster = self._art.request(key)
        if raster is None:
            self._art_job = self.loop.after(60, self._paint_art)
            return
        self._ring_photo = ImageTk.PhotoImage(raster, master=self.loop)
        self.loop.itemconfigure(self._background_item, image=self._ring_photo)
        self._ring_key = key

    def close(self):
        self._closed = True
        for job in (self._resize_job, self._art_job):
            if job is not None:
                self.loop.after_cancel(job)
        for card in self._widgets.values():
            card.destroy()
        for button in self._report_buttons.values():
            button.destroy()
        for surface in self._surfaces:
            surface.close()
        self._art.close()
        self._ring_photo = None

    def _draw_ring(self):
        if self._drawn_size == self._size:
            return
        self._drawn_size = self._size
        c = self.loop
        if self._art_job is not None:
            c.after_cancel(self._art_job)
            self._art_job = None
        if not hasattr(self, '_background_item'):
            self._background_item = c.create_image(0, 0, anchor='nw')
        self._paint_art()
        c.delete('ring')
        w, h = self._size
        cx, cy = w/2, h*.53
        radius = max(100, min(w*.46, (h-85)*.47))
        def point(angle, r=radius):
            a = math.radians(angle)
            return cx+r*math.cos(a), cy-r*math.sin(a)
        c.create_text(cx, 20, text='Development Loop', fill=FG, font=('Segoe UI', 18, 'bold'), tags='ring')
        c.create_text(cx, 48, text='実測段階のみ表示 ／ 自動指揮・架空の進捗なし', fill=MUTED, font=('Yu Gothic UI', 9), tags='ring')
        if not self._art.available:
            c.create_oval(cx-radius*.78, cy-radius*.78, cx+radius*.78, cy+radius*.78, outline='#20375e', dash=(2, 5), tags='ring')
        panel_h = max(75, min(155, (h-150)*.27))
        badge_y = {}
        for name, start in zip(STATIONS, (135, 45, -45, -135)):
            coords = [n for angle in range(start-8, start-79, -3) for n in point(angle)]
            if not self._art.available:
                c.create_line(*coords, fill=COLORS[name], width=3, smooth=True, arrow='last', tags='ring')
            x, y = point(start, radius*.83)
            y = min(y, h-panel_h-58) if start < 0 else max(108, y)
            badge_y[name] = y
            if not self._art.available:
                c.create_oval(x-42, y-42, x+42, y+42, fill='#101a35', outline=COLORS[name], width=2, tags='ring')
            icon = dict(Implementing='</>', Testing='⚗', Reviewing='✓', Repairing='⚒')[name]
            title = dict(Implementing='実装', Testing='テスト', Reviewing='レビュー', Repairing='修正')[name]
            c.create_text(x, y-9, text=icon, fill=COLORS[name], font=('Segoe UI', 19, 'bold'), tags='ring')
            c.create_text(x, y+19, text=title, fill=FG, font=('Yu Gothic UI', 11, 'bold'), tags='ring')
        panel_w = max(155, w*.29)
        panel_h = max(75, min(155, (h-150)*.27))
        top = badge_y['Implementing']+48
        bottom = badge_y['Repairing']+48
        for name, x, y in (('Implementing', 8, top), ('Testing', w-panel_w-8, top),
                            ('Repairing', 8, bottom), ('Reviewing', w-panel_w-8, bottom)):
            c.coords(self._station_items[name], x, y)
            c.itemconfigure(self._station_items[name], width=panel_w, height=panel_h)
        c.tag_lower('ring')
        c.tag_lower(self._background_item)
        self._position_character()
