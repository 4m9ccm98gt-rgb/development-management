"""Read-only organization map: canonical TASKs and references, never transfers.

Stage attribution is to a role, not proof that the configured provider is the
actual running process. Characters are roles; report inbox integration is absent.
All source access remains in the Collector. No execution or AI APIs are imported.
"""
import tkinter as tk
from tkinter import ttk

from . import manager_decision as decision
from . import manager_proposals as proposals
from .manager_visual_overview import build_overview
from .manager_dashboard_view import STATUS

ROLES = dict(REPORTS='報告箱（システム）', MANAGER='Manager', IMPLEMENTER='Implementer',
             REVIEWER='Reviewer', ORCHESTRATOR='Orchestrator', WORKFLOW='Workflow保管庫')
LOCATIONS = dict(HUMAN='人間の確認先', UNKNOWN='所在／担当確認待ち', WORKFLOW='Workflow記録',
                 IMPLEMENTER='実装段階（実行者未同定）', REVIEWER='レビュー段階（実行者未同定）',
                 ORCHESTRATOR='Run制御段階（実行者未同定）')
SHORT_ACTIONS = dict(INVESTIGATE_FAILURE='失敗内容の調査', REQUEST_HUMAN='人間判断の確認',
    REVIEW_CANDIDATE='候補内容の確認', REQUEST_APPROVAL='承認判断の確認', CHECK_DEPENDENCIES='未完了依存TASKの確認',
    CHECK_HOLD='保留・再開条件の確認', CHECK_PLAN='先行TASK・計画の確認', CHECK_START='開始条件の確認（実行許可ではない）',
    WAIT_FOR_CHANGE='状態変化待ち', NO_FOLLOWUP='追加対応なし', CHECK_DATA='データ・状態の確認')


def empty_map(status='unavailable', memory_available=False):
    return dict(status=status, memory_available=memory_available, tasks=[], lane=[], roles={}, total=None,
                unknown_plans=None, running=None)


def build_map(snapshot, inbox, *, observation_id, memory_available=False):
    """Reuse validated Overview provenance and MGR-7b/7c, no second collection.

    Each TASK appears once in tasks. Lane/role indexes are references; overlapping
    assignment references must never be summed as additional TASKs.
    """
    stats = build_overview(snapshot, inbox, observation_id=observation_id, memory_available=memory_available)
    if stats['kpis'] is None:
        return empty_map(memory_available=memory_available)
    context = decision.build_manager_input(snapshot, observation_id=observation_id)
    source = {(p['plan_id'], t['task_id']): t for p in context['plans'] for t in p['tasks']}
    result = empty_map(stats['status'], memory_available)
    result.update(total=stats['kpis']['total'], running=stats['kpis']['running'], unknown_plans=stats['kpis']['unavailable_plans'])
    for row in inbox['rows']:
        identity = (row['plan_id'], row['task_id'])
        t = source[identity]
        run = t['run']
        known = row['cause'] != 'UNKNOWN'
        observed = (known and memory_available and t['status'] == 'running' and t['availability'] == 'available'
                    and run['availability'] == 'available' and run['liveness'] in ('running', 'starting')
                    and run['stage'] in decision.overview.ACTIVE_STAGES)
        human = known and row['owner'] in ('HUMAN', 'HUMAN_CHECK')
        location = 'UNKNOWN' if not known else 'HUMAN' if human else 'WORKFLOW'
        if observed:
            location = ('IMPLEMENTER' if run['stage'] in ('implementing', 'repairing') and t['main_ai'] else
                        'REVIEWER' if run['stage'] == 'reviewing' and t['reviewer_ai'] else 'ORCHESTRATOR')
        priority = row['priority']
        actions = [p for p in row['proposals'] if p['proposal_type'] == 'ACTION']
        item = dict(identity=identity, status=t['status'], stage=run['stage'] if observed else 'unknown',
                    main_ai=t['main_ai'], reviewer_ai=t['reviewer_ai'], location=location, observed=observed,
                    human=human, unknown=not known, priority=priority,
                    action_code=actions[0]['action_code'], detail=proposals.proposal_text(row),
                    reason=row['reason_code'], cause=row['cause'])
        result['tasks'].append(item)
        if human or not known:
            result['lane'].append(identity)
    for role in ROLES:
        related = [t['identity'] for t in result['tasks'] if
                   role in ('MANAGER', 'WORKFLOW') or
                   role == 'IMPLEMENTER' and t['main_ai'] is not None or
                   role == 'REVIEWER' and t['reviewer_ai'] is not None or
                   role == 'ORCHESTRATOR' and t['observed']]
        names = sorted({t['main_ai' if role == 'IMPLEMENTER' else 'reviewer_ai'] for t in result['tasks']
                        if role in ('IMPLEMENTER', 'REVIEWER') and t['main_ai' if role == 'IMPLEMENTER' else 'reviewer_ai']})
        result['roles'][role] = dict(related=related, names=names,
            stage_count=sum(t['location'] == role and t['observed'] for t in result['tasks']))
    return result


class OrganizationMapView:
    """Independent map, fixed Human Lane, and scrollable selection details."""
    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.header = ttk.Label(self.frame, wraplength=1000)
        self.header.grid(row=0, column=0, sticky='ew')
        self._panels = []
        self.map = self._panel(1)
        ttk.Label(self.frame, text='Human Action Lane — あなたが確認すること／不明は承認待ちと別扱い').grid(row=2, column=0, sticky='w')
        self.lane = self._panel(3, 78)
        self.detail = self._panel(4, 80)
        self._model = empty_map('updating')
        self._role = None
        self._selected = None
        self._width = 1060
        self._palette = ('#ffffff', '#eeeeee', '#111111', '#777777', '#2458a6', '#a03b00')
        self.map.bind('<Configure>', self._resize)
        self._draw()

    def _panel(self, row, height=None):
        frame = ttk.Frame(self.frame)
        frame.grid(row=row, column=0, sticky='nsew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        c = tk.Canvas(frame, highlightthickness=0, **(dict(height=height) if height else {}))
        c.grid(row=0, column=0, sticky='nsew')
        h = ttk.Scrollbar(frame, orient='horizontal', command=c.xview)
        v = ttk.Scrollbar(frame, orient='vertical', command=c.yview)
        h.grid(row=1, column=0, sticky='ew')
        v.grid(row=0, column=1, sticky='ns')
        c.configure(xscrollcommand=h.set, yscrollcommand=v.set)
        c.bind('<MouseWheel>', lambda e, canvas=c: self._wheel(canvas, e, False))
        c.bind('<Shift-MouseWheel>', lambda e, canvas=c: self._wheel(canvas, e, True))
        self._panels.append((c, h, v))
        return c

    def _wheel(self, canvas, event, horizontal):
        (canvas.xview if horizontal else canvas.yview)('scroll', -int(event.delta / 120), 'units')
        return 'break'

    def _resize(self, event):
        if self._width != event.width:
            self._width = event.width
            self.header.configure(wraplength=max(300, event.width-20))
            self._draw()

    def apply_theme(self, style):
        from .app import DARK_BG, DARK_SURFACE, DARK_FG, DARK_BORDER, DARK_ACCENT
        dark = style.lookup('TFrame', 'background') == DARK_BG
        self._palette = ((DARK_BG, DARK_SURFACE, DARK_FG, DARK_BORDER, DARK_ACCENT, '#d29922') if dark else
                         ('#ffffff', '#eeeeee', '#111111', '#777777', '#2458a6', '#a03b00'))
        for c, h, v in self._panels:
            c.configure(background=self._palette[0])
            h.configure(style='Manager.Horizontal.TScrollbar' if dark else 'Horizontal.TScrollbar')
            v.configure(style='Manager.Vertical.TScrollbar' if dark else 'Vertical.TScrollbar')
        self._draw()

    def set_model(self, model):
        if model != self._model:
            self._model = model
            self._selected = None
            if model['total'] is None:
                self._role = None
            self._draw()

    def select_role(self, role):
        if role in ROLES:
            self._role, self._selected = role, None
            self._draw()

    def select_task(self, identity):
        if any(t['identity'] == identity for t in self._model['tasks']):
            self._selected = identity
            self._draw()

    def _text(self, c, x, y, text, width=200, size=10, tag=None):
        return c.create_text(x, y, text=text, anchor='nw', fill=self._palette[2],
                             font=('Yu Gothic UI', size), width=width, tags=(tag,) if tag else ())

    def _character(self, x, y, role, tag):
        c = self.map
        _, surface, fg, border, accent, warning = self._palette
        if role in ('MANAGER', 'IMPLEMENTER', 'REVIEWER'):
            c.create_oval(x+20, y, x+44, y+24, fill=fg, outline=border, tags=tag)
            c.create_polygon(x+12, y+28, x+52, y+28, x+60, y+62, x+4, y+62, fill=accent, outline=fg, tags=tag)
            if role == 'MANAGER':
                c.create_polygon(x+29, y+28, x+35, y+28, x+38, y+50, x+32, y+56, x+26, y+50, fill=warning, tags=tag)
            elif role == 'IMPLEMENTER':
                c.create_rectangle(x+7, y+38, x+57, y+64, fill=surface, outline=fg, tags=tag)
                self._text(c, x+15, y+40, '>_', 35, 12, tag)
            else:
                c.create_rectangle(x+37, y+25, x+65, y+60, fill=surface, outline=fg, tags=tag)
                self._text(c, x+40, y+30, '✓', 25, 14, tag)
        elif role == 'REPORTS':
            c.create_polygon(x+5, y+25, x+5, y+3, x+23, y+16, x+42, y+16, x+58, y+3, x+58, y+35, fill=warning, outline=fg, tags=tag)
            c.create_oval(x+4, y+15, x+59, y+62, fill=warning, outline=fg, tags=tag)
            for xx in (19, 42):
                c.create_oval(x+xx, y+32, x+xx+4, y+38, fill=surface, tags=tag)
            c.create_line(x+29, y+43, x+33, y+47, x+37, y+43, fill=surface, width=2, tags=tag)
            for yy in (43, 49):
                c.create_line(x-3, y+yy, x+17, y+yy-2, fill=fg, tags=tag)
                c.create_line(x+46, y+yy-2, x+66, y+yy, fill=fg, tags=tag)
        else:
            c.create_rectangle(x, y+4, x+67, y+62, fill=surface, outline=accent, width=2, tags=tag)
            if role == 'ORCHESTRATOR':
                c.create_rectangle(x+7, y+12, x+60, y+43, fill=accent, tags=tag)
                self._text(c, x+15, y+16, 'RUN', 45, 11, tag)
            else:
                for yy in (17, 33, 49):
                    c.create_line(x+5, y+yy, x+62, y+yy, fill=fg, width=2, tags=tag)

    def _draw(self):
        m, c = self._model, self.map
        bg, surface, fg, border, accent, warning = self._palette
        c.delete('all')
        self.lane.delete('all')
        state = {'available': '取得済み（確認できた範囲）', 'partial': '一部取得不能・確認待ちあり',
                 'updating': '更新中・古い稼働表示は消去', 'unavailable': '取得不能・全て確認待ち'}[m['status']]
        scope = '本体メモリ優先' if m['memory_available'] else 'ディスクのみ・本体メモリ未確認'
        summary = 'TASK件数は確認待ち' if m['total'] is None else f'既知TASK {m["total"]}／観測済み実行 {m["running"]}／人間・確認待ち {len(m["lane"])}／取得不能計画 {m["unknown_plans"]}'
        self.header.configure(text=f'{state}　{summary}　{scope}')
        positions = dict(REPORTS=(20, 85), MANAGER=(340, 4), IMPLEMENTER=(255, 140),
                         REVIEWER=(550, 140), ORCHESTRATOR=(815, 8), WORKFLOW=(815, 143))
        # Dotted lines are architecture only, never observed TASK movement.
        for left, right in (('REPORTS', 'MANAGER'), ('MANAGER', 'IMPLEMENTER'), ('MANAGER', 'REVIEWER'),
                            ('IMPLEMENTER', 'ORCHESTRATOR'), ('REVIEWER', 'ORCHESTRATOR'), ('ORCHESTRATOR', 'WORKFLOW')):
            x, y = positions[left]; xx, yy = positions[right]
            c.create_line(x+90, y+45, xx+50, yy+45, fill=border, dash=(4, 4), width=2)
        selected = next((t for t in m['tasks'] if t['identity'] == self._selected), None)
        if selected and selected['observed']:
            x, y = positions[selected['location']]
            xx, yy = positions['WORKFLOW']
            c.create_line(x+105, y+64, xx+105, yy+64, fill=accent, width=3)
        elif selected and selected['human']:
            c.create_line(447, 132, 447, 270, fill=warning, width=3)
            self._text(c, 452, 253, '人間の確認先', 150, 9)
        for role, (x, y) in positions.items():
            tag = 'role-' + role
            c.create_rectangle(x, y, x+215, y+128, fill=surface, outline=accent if self._role == role else border, width=2, tags=tag)
            self._character(x+8, y+8, role, tag)
            self._text(c, x+80, y+8, ROLES[role], 128, tag=tag)
            role_data = m['roles'].get(role, {})
            names = ' / '.join({'codex': 'Codex', 'claude': 'Claude'}[n] for n in role_data.get('names', [])) or '設定なし／確認待ち'
            note = ('接続未実装・件数不明' if role == 'REPORTS' else
                    f'固定ルールで整理・提案\nAI推論無効／参照TASK {m["total"] if m["total"] is not None else "不明"}' if role == 'MANAGER' else
                    f'担当設定: {names}\nRun段階確認: {role_data.get("stage_count", 0) if m["total"] is not None else "不明"}（実行者未同定）' if role in ('IMPLEMENTER', 'REVIEWER') else
                    f'Run段階観測 {sum(t["observed"] for t in m["tasks"]) if m["total"] is not None else "不明"}\n制御・起動なし' if role == 'ORCHESTRATOR' else
                    f'TASK正本・読取専用\n既知TASK {m["total"] if m["total"] is not None else "不明"}')
            self._text(c, x+8, y+76, note, 199, 9, tag)
            c.tag_bind(tag, '<Button-1>', lambda e, r=role: self.select_role(r))
        self._text(c, 20, 276, '点線＝構成／実線＝選択TASKの確認済み関係・対応先（移動履歴ではない）。担当設定≠実行者。', 1000, 9)
        y = 302
        if self._role:
            related = m['roles'].get(self._role, {}).get('related', [])
            description = ('報告箱は接続未実装・報告件数不明' if self._role == 'REPORTS' else '参照対象は確認待ち' if m['total'] is None else
                           f'{ROLES[self._role]}の参照対象 {len(related)}件（担当設定の関連を含む・総数へ加算しません）')
            self._text(c, 20, y, description, 1000)
            y += 30
            for i, task in enumerate(t for t in m['tasks'] if t['identity'] in related):
                self._card(c, 20+(i % 4)*255, y+(i // 4)*90, task)
            y += ((len(related)+3)//4)*90
        c.configure(scrollregion=(0, 0, max(1060, self._width), max(302, y)))
        lane_tasks = [t for t in m['tasks'] if t['identity'] in m['lane']]
        for i, task in enumerate(lane_tasks):
            self._card(self.lane, i*255+8, 4, task)
        if not lane_tasks:
            self._text(self.lane, 12, 10, '確認待ち（取得・更新中）' if m['total'] is None else '既知TASKの人間対応・状態確認候補なし', 900)
        self.lane.configure(scrollregion=(0, 0, max(1060, len(lane_tasks)*255+8), 86))
        self._draw_detail()

    def _card(self, canvas, x, y, task):
        tag = f'task-{len(task["identity"][0])}-{task["identity"][0]}-{task["identity"][1]}'
        canvas.create_rectangle(x, y, x+245, y+80, fill=self._palette[1],
                                outline=self._palette[5] if task['human'] else self._palette[3], tags=tag)
        pid, tid = task['identity']
        compact = lambda value: value if len(value) <= 12 else value[:11] + '…'
        title = f'{task["priority"]}  {compact(pid)} / {compact(tid)}'
        self._text(canvas, x+6, y+3, title, 233, 9, tag)
        short = '確認待ち' if task['unknown'] else STATUS[task['status']]
        location = dict(HUMAN='人間確認', UNKNOWN='所在確認待ち', WORKFLOW='正本記録', IMPLEMENTER='実装段階',
                        REVIEWER='レビュー段階', ORCHESTRATOR='Run制御段階')[task['location']]
        self._text(canvas, x+6, y+24, f'{short} ／ {location}', 233, 9, tag)
        self._text(canvas, x+6, y+48, SHORT_ACTIONS[task['action_code']], 233, 9, tag)
        canvas.tag_bind(tag, '<Button-1>', lambda e, identity=task['identity']: self.select_task(identity))

    def _draw_detail(self):
        c = self.detail
        c.delete('all')
        task = next((t for t in self._model['tasks'] if t['identity'] == self._selected), None)
        if task:
            from .manager_inbox import CAUSES
            text = (f'{task["identity"][0]} / {task["identity"][1]}　Workflow記録: {STATUS[task["status"]]}（Run確定とは別）\n'
                    f'確認優先度: {task["priority"]}（業務重要度ではありません）／{LOCATIONS[task["location"]]}\n'
                    f'確認済み段階: {task["stage"]}／担当設定 Implementer: {task["main_ai"] or "未設定"}・Reviewer: {task["reviewer_ai"] or "未設定"}\n'
                    f'原因: {CAUSES[task["cause"]]}／理由コード: {task["reason"]}\n{task["detail"]}')
        else:
            text = 'キャラクターで参照対象を絞り、TASKカードで理由・次の提案・確認事項を表示します。承認・実行操作はありません。'
        item = self._text(c, 12, 6, text, max(700, self._width-45), 9)
        bbox = c.bbox(item)
        c.configure(scrollregion=(0, 0, max(740, self._width), (bbox[3]+12) if bbox else 100))
