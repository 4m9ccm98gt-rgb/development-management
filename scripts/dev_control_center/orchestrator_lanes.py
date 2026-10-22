"""Display-only four lanes. Run lifecycle/permissions remain in existing owners."""
import queue
import re
import threading
import time
from tkinter import ttk
import tkinter as tk

from .manager_collector import ManagerCollector
from .manager_dashboard_preview import preview_data
from .manager_inbox import build_inbox
from .manager_organization_map import build_map, SHORT_ACTIONS

LANES = ('Manager', 'Implementer', 'Reviewer', 'Human')
STAGES = dict(created='作成済み', preflight='事前確認', implementing='実装段階', repairing='修正段階',
              testing='Tests実行（システム工程）', reviewing='レビュー段階', finalizing='最終検証（システム工程）',
              stopping='安全停止処理', stopped='停止・確認待ち', failed='失敗・確認待ち', needs_human='人間判断待ち', completed='完了')


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', value) is not None


def workflow_cards(payload, memory=False):
    data, _ = preview_data(payload, memory_available=memory)
    raw = payload if isinstance(payload, dict) else {}
    box = build_inbox(data, observation_id=raw.get('observation_id'), collection_status=raw.get('status'),
                      memory_available=memory, issues=raw.get('issues', ()))
    model = build_map(data, box, observation_id=raw.get('observation_id'), memory_available=memory)
    if model['total'] is None:
        return [], 'Workflow：取得不能・確認待ち'
    source = {(p['plan_id'], t['task_id']): t for p in data['plans'] for t in p['tasks']}
    cards = []
    for t in model['tasks']:
        s = source[t['identity']]
        lane = ('Human' if t['human'] else 'Implementer' if t['location'] == 'IMPLEMENTER' else
                'Reviewer' if t['location'] == 'REVIEWER' else
                'Implementer' if t['observed'] and t['stage'] == 'testing' else
                'Reviewer' if t['observed'] and t['stage'] == 'finalizing' else 'Manager')
        rid = s['run'].get('run_id')
        stage = STAGES.get(t['stage'], '稼働・所属確認待ち')
        cards.append(dict(key='WF:'+':'.join(t['identity']), run_id=rid if valid_id(rid) else None,
            lane=lane, title=' / '.join(t['identity']), priority=t['priority'], state=stage if t['observed'] else
            '状態・所属確認待ち' if t['unknown'] else STAGES.get(t['status'], dict(proposed='承認待ち', approved='開始条件確認待ち', held='保留', landed='完了', cancelled='取消').get(t['status'], '確認待ち')),
            hint=f'repo: {s["repo_key"]} ／ 担当設定: {t["main_ai"] or "未設定"} / {t["reviewer_ai"] or "未設定"}\n'
                 f'確認済みRun段階: {stage} ／ 理由: {t["reason"]} ／ 次の対応: {SHORT_ACTIONS[t["action_code"]]}',
            detail=t['detail'] + ('\nWorkflow本文・Run履歴はこの安全な集約入力には含まれません。Run未関連の詳細仕様は既存Workflow画面で確認してください。' if not valid_id(rid) else '')))
        cards[-1]['observed_stage'] = t['stage']
    return cards, 'Workflow：' + ('一部取得不能・確認待ち' if model['status'] == 'partial' else '取得済み') + ('／本体メモリ優先' if memory else '／ディスクのみ・メモリ未確認')


def build_lanes(workflow, runs, *, repo_names=(), monitor_ok=True):
    """One card per Workflow TASK or unmatched Run. No transitions are executed.

    Unknown observations stay in Manager explicitly unconfirmed. A completed Run
    enters Human only for a recorded, unapplied candidate; Human is not mandatory.
    Tests are a system stage, never an independent/active AI employee.
    """
    result = {name: [] for name in LANES}
    current_runs = {i['record']['run_id']: i for i in runs if isinstance(i, dict) and isinstance(i.get('record'), dict)
                    and valid_id(i['record'].get('run_id'))}
    known = set()
    keys = set()
    for c in workflow:
        if c['key'] in keys:
            continue
        keys.add(c['key'])
        item = dict(c)
        latest = current_runs.get(item['run_id'])
        conflict = item.get('observed_stage', 'unknown') != 'unknown' and (
            latest is None or latest.get('liveness') not in ('running', 'starting')
            or latest['record'].get('stage') != item['observed_stage'])
        if item['run_id'] and (not monitor_ok or conflict):
            item.update(lane='Manager', state='Run取得不能・所属確認待ち', priority='PX',
                        hint='WorkflowとRunの最新観測を照合できません。稼働・所属は確認待ちです。',
                        detail='最新のWorkflow状態・Run対応を再取得してください。以前の提案は現在の実行判断に使用できません。')
        result[item['lane']].append(item)
        if item['run_id']:
            known.add(item['run_id'])
    for item in runs:
        r = item.get('record') if isinstance(item, dict) else None
        if not isinstance(r, dict) or not valid_id(r.get('run_id')) or r['run_id'] in known:
            continue
        rid, stage, live = r['run_id'], r.get('stage'), item.get('liveness')
        known.add(rid)
        terminal = ('completed', 'failed', 'needs_human', 'stopped')
        confirmed = (monitor_ok and isinstance(stage, str) and stage in STAGES and
                     (live == 'finished' if stage in terminal else live in ('running', 'starting')))
        lane, priority = 'Manager', 'PX'
        if confirmed:
            if stage in ('failed', 'needs_human', 'stopped'):
                lane, priority = 'Human', 'P1'
            elif stage == 'completed' and isinstance(r.get('candidate_sha'), str) and re.fullmatch(r'[0-9a-f]{40}', r['candidate_sha']) and r.get('apply_status') != 'applied':
                lane, priority = 'Human', 'P2'
            elif live in ('running', 'starting') and stage in ('implementing', 'repairing', 'testing'):
                lane, priority = 'Implementer', 'P4'
            elif live in ('running', 'starting') and stage in ('reviewing', 'finalizing'):
                lane, priority = 'Reviewer', 'P4'
            else:
                priority = 'P4' if stage == 'completed' else 'P3'
        repo = str(r.get('repo', '')).replace('\\', '/').rsplit('/', 1)[-1]
        repo = repo if repo in repo_names else '確認待ち'
        main = r.get('main_agent') if r.get('main_agent') in ('codex', 'claude') else '確認待ち'
        reviewer = r.get('review_agent') if r.get('review_agent') in ('codex', 'claude') else '確認待ち'
        state = STAGES[stage] if confirmed else 'Run稼働・所属確認待ち'
        result[lane].append(dict(key='RUN:'+rid, run_id=rid, lane=lane, title='Run '+rid,
            priority=priority, state=state,
            hint=f'repo: {repo} ／ 担当設定: {main} / {reviewer}\n{state}／Workflow TASKとの紐付け未確認',
            detail='Runの詳細・テスト・レビュー結果・ログは既存の詳細パネルで確認できます。'))
    return result


class WorkflowFeed:
    """Bounded single reader. The background closure never captures Tk objects."""
    def __init__(self, collector, memory=False, launch=None, now=time.monotonic):
        self.collector, self.memory, self.now = collector, memory, now
        self.launch = launch or (lambda job: threading.Thread(target=job, daemon=True, name='orchestrator-workflow-read').start())
        self.queue = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.due = 0

    def poll(self):
        if self.stop.is_set():
            return None
        try:
            payload = self.queue.get_nowait()
        except queue.Empty:
            payload = ...
        if payload is not ...:
            self.busy = False
            self.due = self.now()+10
            return workflow_cards(payload, self.memory)
        if not self.busy and self.now() >= self.due:
            self.busy = True
            collector, output, stopped = self.collector, self.queue, self.stop
            def read():
                if stopped.is_set():
                    return
                try:
                    value = collector()
                except Exception:
                    value = None
                if not stopped.is_set():
                    output.put(value)
            try:
                self.launch(read)
            except Exception:
                self.queue.put(None)
            return [], 'Workflow：更新中・古い状態は未確認'
        return None


class LaneBoard:
    def __init__(self, parent, on_select):
        from .app import DARK_BG, DARK_FIELD, DARK_FG, DARK_BORDER, DARK_SELECTION
        self.frame = ttk.Frame(parent)
        self.frame.rowconfigure(2, weight=1)
        self.hint = ttk.Label(self.frame, text='Manager AI推論は無効。点線は構成上の経路であり、TASKの移動履歴ではありません。', wraplength=1100)
        self.hint.grid(row=3, column=0, columnspan=4, sticky='ew')
        self.path = tk.Canvas(self.frame, height=38, highlightthickness=0, background=DARK_BG)
        self.path.grid(row=0, column=0, columnspan=4, sticky='ew')
        self.path.bind('<Configure>', lambda e: self._draw_paths(e.width))
        self._draw_paths(1100)
        self.headers, self.bodies, self.canvases, self.cards = {}, {}, {}, {}
        self.review_header = None
        self.on_select = on_select
        self._last = None
        style = ttk.Style(parent)
        elements = set(style.element_names())
        prefix = 'OrchestratorLane.Vertical.Scrollbar'
        for part in ('trough', 'thumb', 'uparrow', 'downarrow'):
            if prefix+'.'+part not in elements:
                style.element_create(prefix+'.'+part, 'from', 'clam', 'Vertical.Scrollbar.'+part)
        style.layout('OrchestratorLane.Vertical.TScrollbar', [(prefix+'.trough', dict(sticky='nswe', children=[
            (prefix+'.uparrow', dict(side='top', sticky='')), (prefix+'.downarrow', dict(side='bottom', sticky='')),
            (prefix+'.thumb', dict(expand=1, sticky='nswe'))]))])
        style.configure('OrchestratorLane.Vertical.TScrollbar', background=DARK_FIELD, troughcolor=DARK_BG,
                        arrowcolor=DARK_FG, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.map('OrchestratorLane.Vertical.TScrollbar', background=[('active', DARK_SELECTION), ('!active', DARK_FIELD)],
                  arrowcolor=[('!active', DARK_FG), ('active', DARK_FG)])
        for col, name in enumerate(LANES):
            self.frame.columnconfigure(col, weight=1, uniform='lanes')
            heading = ttk.Frame(self.frame)
            heading.grid(row=1, column=col, sticky='ew', padx=3)
            icon = ('♙ 銀髪Manager画像枠' if name == 'Manager' else '⚒ 実装担当画像枠' if name == 'Implementer' else
                    'Reviewer／選択Run工程画像\nTestsはシステム工程' if name == 'Reviewer' else '♙ 人間の確認先')
            ttk.Label(heading, text=icon).pack(anchor='w')
            label = ttk.Label(heading, text=name+'：確認待ち')
            label.pack(anchor='w')
            self.headers[name] = label
            if name == 'Reviewer':
                self.review_header = heading
            panel = ttk.Frame(self.frame)
            panel.grid(row=2, column=col, sticky='nsew', padx=3)
            panel.rowconfigure(0, weight=1)
            panel.columnconfigure(0, weight=1)
            canvas = tk.Canvas(panel, highlightthickness=0, width=220, background=DARK_BG)
            canvas.grid(row=0, column=0, sticky='nsew')
            scrollbar = ttk.Scrollbar(panel, orient='vertical', command=canvas.yview, style='OrchestratorLane.Vertical.TScrollbar')
            scrollbar.grid(row=0, column=1, sticky='ns')
            canvas.configure(yscrollcommand=scrollbar.set)
            body = ttk.Frame(canvas)
            item = canvas.create_window(0, 0, anchor='nw', window=body)
            canvas.bind('<Configure>', lambda e, c=canvas, i=item: c.itemconfigure(i, width=e.width))
            body.bind('<Configure>', lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
            canvas.bind('<MouseWheel>', lambda e, c=canvas: c.yview_scroll(-int(e.delta/120), 'units'))
            self.bodies[name], self.canvases[name] = body, canvas
            self.cards[name] = []

    def set_model(self, model):
        if model == self._last:
            return
        self._last = model
        self.hint.configure(text='最新レーン表示。カードのホバー・フォーカス・クリックで詳細確認。担当設定は稼働証明ではありません。')
        for name in LANES:
            self.headers[name].configure(text=f'{name}：{len(model[name])}件')
            for widget in self.cards[name]:
                widget.destroy()
            self.cards[name] = []
            for card in model[name]:
                title = card['title'] if len(card['title']) <= 30 else card['title'][:29]+'…'
                button = ttk.Button(self.bodies[name], text=f'{title}\n{card["state"]}\n{card["priority"]} ／ {name}',
                                    command=lambda c=card: self.on_select(c))
                button.pack(fill='x', pady=4, padx=2)
                show = lambda e, c=card: self.hint.configure(text=c['hint'])
                button.bind('<Enter>', show)
                button.bind('<FocusIn>', lambda e, b=button, cv=self.canvases[name], c=card: self._focus_card(b, cv, c))
                button.bind('<Return>', lambda e, c=card: self.on_select(c))
                button.bind('<MouseWheel>', lambda e, c=self.canvases[name]: c.yview_scroll(-int(e.delta/120), 'units'))
                self.cards[name].append(button)

    def _focus_card(self, button, canvas, card):
        self.hint.configure(text=card['hint'])
        bounds = canvas.bbox('all')
        if bounds:
            y, top = button.winfo_y(), canvas.canvasy(0)
            if y < top or y+button.winfo_height() > top+canvas.winfo_height():
                canvas.yview_moveto(max(0, y)/max(1, bounds[3]))

    def _draw_paths(self, width):
        self.hint.configure(wraplength=max(400, width-20))
        self.path.delete('all')
        centers = [width*(i+.5)/4 for i in range(4)]
        for left, right in ((0, 1), (1, 2)):
            self.path.create_line(centers[left], 9, centers[right], 9, fill='#58a6ff', dash=(4, 3), arrow='last')
        self.path.create_line(centers[2], 27, centers[1], 27, fill='#9ba7b4', dash=(4, 3), arrow='last')
        self.path.create_line(centers[2]+20, 9, centers[3], 9, fill='#d29922', dash=(4, 3), arrow='last')
        self.path.create_text(centers[3], 27, text='各レーンから必要時のみ', fill='#9ba7b4', font=('Yu Gothic UI', 9))
