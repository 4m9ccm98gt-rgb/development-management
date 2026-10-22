"""Pure Overview projection and local Canvas renderer. No collection or actions."""
from collections import Counter
import tkinter as tk
from tkinter import ttk

from . import manager_decision as decision
from . import manager_proposals as proposals
from .manager_dashboard_view import display_model

DISTRIBUTION = (('not_started', '未実行・承認待ち'), ('waiting', '待機・保留'),
                ('running', '観測できた実行中'), ('needs_human', '人間対応待ち'),
                ('failed', '失敗'), ('completed', '完了'), ('cancelled', '取消'), ('unavailable', '状態不明'))
FOCUS = dict(P1='失敗・人間判断', P2='承認・候補確認', P3='依存待ち・保留・選択待ち', PX='状態不明・確認待ち')
PROPOSALS = dict(check='解決アクションの確認候補', draft='改善TASKの未完成下書き',
                 wait='対応不要・状態変化待ち', data='データ取得確認が必要')


def empty_overview(status='unavailable', memory_available=False):
    return dict(status=status, memory_available=memory_available, kpis=None, distribution=None,
                projects=[], focus=None, reasons={}, proposals=None)


def build_overview(snapshot, inbox, *, observation_id, memory_available=False):
    """Aggregate ONE collection. Counts are known TASK counts, not workload.

    Validate snapshot/provenance before reading IDs/repos. Unknown plans have no
    denominator. In disk mode never count a running assertion as confirmed.
    Inbox partial issues can additionally make TASK confirmation unavailable.
    """
    result = empty_overview(memory_available=memory_available)
    if not isinstance(inbox, dict) or inbox.get('status') not in ('available', 'partial'):
        return result
    try:
        context = decision.build_manager_input(snapshot, observation_id=observation_id)
        if context['availability'] == 'unavailable':
            return result
        rows = inbox['rows']
        expected = {(p['plan_id'], t['task_id']) for p in context['plans'] for t in p['tasks']}
        if not isinstance(rows, list) or len(rows) != len(expected):
            return result
        identities = set()
        for row in rows:
            if (not isinstance(row, dict) or row.get('observation_id') != observation_id
                or row.get('snapshot_id') != context['snapshot_id'] or not proposals.validate_proposals(row.get('proposals'), row)):
                return result
            identities.add((row['plan_id'], row['task_id']))
        if identities != expected:
            return result
    except (decision.DecisionError, KeyError, TypeError, ValueError, RecursionError):
        return result
    counts = Counter({key: 0 for key, _ in DISTRIBUTION})
    unavailable_plans = 0
    projects = []
    unknown_tasks = {(r['plan_id'], r['task_id']) for r in rows if r.get('cause') == 'UNKNOWN'}
    for p in context['plans']:
        pid = p['plan_id'] or '確認待ち'
        if p['availability'] != 'available':
            unavailable_plans += 1
            projects.append(dict(plan_id=pid, repos=[], total=None, completed=None, waiting=None,
                                 running=None, check=None, percent=None))
            continue
        local = Counter({key: 0 for key, _ in DISTRIBUTION})
        for t in p['tasks']:
            # Reuse existing display checks for observed stage/liveness.
            single = dict(schema_version=1, availability='available', plans=[dict(p, tasks=[t])])
            verified = display_model(single)['counts']
            category = t['category'] if not verified['unavailable'] else 'unavailable'
            if (p['plan_id'], t['task_id']) in unknown_tasks or (t['status'] == 'running' and not memory_available):
                category = 'unavailable'
            local[category] += 1
            if category == 'unavailable':
                unknown_tasks.add((p['plan_id'], t['task_id']))
        counts.update(local)
        total = len(p['tasks'])
        projects.append(dict(plan_id=pid, repos=sorted({t['repo_key'] for t in p['tasks']}),
            total=total, completed=local['completed'], waiting=local['waiting'] + local['not_started'],
            running=local['running'], check=len({t['task_id'] for t in p['tasks']
                if t['status'] in ('proposed', 'candidate_ready', 'needs_human', 'failed')
                or (p['plan_id'], t['task_id']) in unknown_tasks}),
            percent=100 * local['completed'] / total if total else None))
    focus = {k: sum(r.get('priority') == k for r in rows) for k in FOCUS}
    reasons = {k: dict(Counter(r['reason_code'] for r in rows if r.get('priority') == k)) for k in FOCUS}
    proposal_counts = dict.fromkeys(PROPOSALS, 0)
    for row in rows:
        for item in row['proposals']:
            bucket = ('draft' if item['proposal_type'] == 'IMPROVEMENT_DRAFT' else
                      'data' if item['action_code'] == 'CHECK_DATA' else
                      'wait' if item['state'] == 'INFORMATION_ONLY' else 'check')
            proposal_counts[bucket] += 1
    result.update(status='partial' if inbox['status'] == 'partial' or unavailable_plans else 'available',
        kpis=dict(total=sum(counts.values()), running=counts['running'],
                  human=sum(r['category'] == 'human' for r in rows), completed=counts['completed'],
                  unavailable_plans=unavailable_plans, unavailable_tasks=len(unknown_tasks)),
        distribution=dict(counts), projects=projects, focus=focus, reasons=reasons, proposals=proposal_counts)
    return result


class OverviewView:
    """A single scrollable Canvas: text + bars, no widget rebuild per refresh.

    Model generation is separate. Configure redraws at actual width; a minimum
    logical width preserves text with a horizontal scrollbar on small windows.
    No global wheel bindings or theme changes; all calls belong to Tk's thread.
    """
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.frame, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.horizontal = ttk.Scrollbar(self.frame, orient='horizontal', command=self.canvas.xview)
        self.vertical = ttk.Scrollbar(self.frame, orient='vertical', command=self.canvas.yview)
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(xscrollcommand=self.horizontal.set, yscrollcommand=self.vertical.set)
        self.canvas.bind('<Configure>', self._resize)
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Shift-MouseWheel>', self._wheel_horizontal)
        self._width = 1000
        self._model = empty_overview('updating')
        self._palette = ('#ffffff', '#eeeeee', '#111111', '#777777', '#2458a6')

    def _wheel(self, event):
        self.canvas.yview('scroll', -int(event.delta / 120), 'units')
        return 'break'

    def _wheel_horizontal(self, event):
        self.canvas.xview('scroll', -int(event.delta / 120), 'units')
        return 'break'

    def _resize(self, event):
        if event.width != self._width:
            self._width = event.width
            self._draw()

    def apply_theme(self, style):
        from .app import DARK_BG, DARK_SURFACE, DARK_FG, DARK_BORDER, DARK_SELECTION
        dark = style.lookup('TFrame', 'background') == DARK_BG
        self._palette = ((DARK_BG, DARK_SURFACE, DARK_FG, DARK_BORDER, DARK_SELECTION) if dark else
                         (style.lookup('TFrame', 'background') or '#ffffff', '#eeeeee', '#111111', '#777777', '#2458a6'))
        self.horizontal.configure(style='Manager.Horizontal.TScrollbar' if dark else 'Horizontal.TScrollbar')
        self.vertical.configure(style='Manager.Vertical.TScrollbar' if dark else 'Vertical.TScrollbar')
        self.canvas.configure(background=self._palette[0])
        self._draw()

    def set_model(self, model):
        if model != self._model:
            self._model = model
            self._draw()

    def _draw(self):
        c, m = self.canvas, self._model
        bg, surface, fg, border, accent = self._palette
        width = max(900, self._width)
        c.delete('all')
        def text(x, y, value, size=10, color=fg, wrap=None):
            return c.create_text(x, y, text=value, anchor='nw', fill=color,
                                 font=('Yu Gothic UI', size), width=wrap or width - x - 18)
        def box(x, y, w, h):
            c.create_rectangle(x, y, x+w, y+h, fill=surface, outline=border)
        text(16, 8, 'Organization Overview · 固定ルール／Manager AI推論なし', 12)
        scope = '本体メモリ優先' if m['memory_available'] else 'ディスクのみ・本体メモリ未確認'
        state = dict(available='取得済み（既知分）', partial='一部取得不能・既知分のみ',
                     updating='更新中・前回数値は未確認', unavailable='取得不能・確認待ち').get(m['status'], '確認待ち')
        text(16, 34, f'{state} ／ {scope}')
        if m['kpis'] is None:
            text(16, 78, 'KPI・分布・進捗・提案集計：確認待ち（0件とは扱いません）', 12)
            c.configure(scrollregion=(0, 0, width, 160))
            return
        k = m['kpis']
        cards = [('TASK総数（既知）', str(k['total'])), ('観測済み実行中', str(k['running'])),
                 ('人間の確認が必要', str(k['human'])), ('完了TASK', str(k['completed'])),
                 ('取得不能・確認待ち', f'計画 {k["unavailable_plans"]} / TASK {k["unavailable_tasks"]}')]
        card_width = (width - 48) / 5
        for i, (label, value) in enumerate(cards):
            x = 16 + i * (card_width + 4)
            box(x, 62, card_width, 62)
            text(x+10, 69, label, wrap=card_width-18)
            text(x+10, 91, value, 14, wrap=card_width-18)
        half = width / 2
        text(16, 136, 'TASK状態分布（件数）', 11)
        total = max(1, k['total'])
        colors = ('#9ba7b4', '#c9a227', '#2f81f7', '#d29922', '#f85149', '#3fb950', '#8b949e', '#bc8cff')
        for i, ((key, label), color) in enumerate(zip(DISTRIBUTION, colors)):
            y = 162 + i * 23
            value = m['distribution'][key]
            text(16, y, f'{label}  {value}', wrap=200)
            c.create_rectangle(216, y+4, half-20, y+15, fill=border, outline='')
            if value:
                c.create_rectangle(216, y+4, 216+(half-236)*value/total, y+15, fill=color, outline='')
        text(half+10, 136, 'Manager注視項目 · 確認優先度（業務重要度ではない）', 10)
        for i, (key, label) in enumerate(FOCUS.items()):
            reason = ' / '.join(m['reasons'][key]) or '該当なし'
            text(half+10, 160+i*30, f'{key}: {m["focus"][key]}　{label}\n{reason}', 9, wrap=half-28)
        text(half+10, 284, 'Manager提案 · 表示のみ／実行済みではありません', 10)
        for i, (key, label) in enumerate(PROPOSALS.items()):
            text(half+10, 307+i*19, f'{label}: {m["proposals"][key]}', 9)
        text(16, 395, '計画別進捗 · 完了TASK数 / 既知TASK数（工数・売上・開発完成度ではありません）', 10)
        y = 423
        for p in m['projects']:
            repos = ' / '.join(p['repos']) or '確認待ち'
            # Canvas text wraps arbitrary-length repo lists; measure before placing
            # the count line so multiple repos never overlap the progress bar.
            box_id = c.create_rectangle(16, y, width-16, y+70, fill=surface, outline=border)
            title = text(26, y+6, f'{p["plan_id"]}　repo: {repos}', wrap=width-54)
            bounds = c.bbox(title)
            line_y = max(y+28, bounds[3]+4 if bounds else y+28)
            if p['total'] is None:
                text(26, line_y, '取得不能・TASK総数／進捗率は確認待ち')
            else:
                rate = f'{p["percent"]:.1f}%' if p['percent'] is not None else '算出なし（TASKなし）'
                count_item = text(26, line_y, f'TASK {p["total"]} / 完了 {p["completed"]} / 待機 {p["waiting"]} / 実行 {p["running"]} / 要確認 {p["check"]}　完了割合 {rate}', wrap=width-54)
                count_bounds = c.bbox(count_item)
                line_y = max(line_y, count_bounds[3]-18 if count_bounds else line_y)
                c.create_rectangle(26, line_y+24, width-26, line_y+30, fill=border, outline='')
                if p['percent']:
                    c.create_rectangle(26, line_y+24, 26+(width-52)*p['percent']/100, line_y+30, fill=accent, outline='')
            bottom = line_y+38
            c.coords(box_id, 16, y, width-16, bottom)
            y = bottom+8
        if not m['projects']:
            text(16, y, '保存済み計画なし')
            y += 30
        c.configure(scrollregion=(0, 0, width, y+12))
