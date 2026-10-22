"""Independent read-only Tk dashboard for an injected MGR-1 snapshot.

No collection, polling, task mutation or execution. Call ManagerDashboardWindow(
master, snapshot); a future collector may call set_snapshot on the Tk thread.
Summary waiting includes not_started; cancelled is counted separately. Invalid
plans have no known TASK count and are reported separately, never invented rows.
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from . import manager_overview as overview

UNKNOWN = '確認待ち'
MANAGER_TEXT = 'Manager（組織責任者）：未実装'
STATUS = dict(proposed='未実行', approved='承認済み', held='保留', running='実行中',
              candidate_ready='候補あり・人間対応待ち', landed='完了', failed='失敗',
              needs_human='人間対応待ち', cancelled='取消')
STAGES = {s: s for s in overview.ACTIVE_STAGES | overview.TERMINAL_STAGES}
LIVENESS = {s: s for s in overview.LIVENESS}
COUNTS = (('total', 'TASK総数'), ('running', '実行中'), ('waiting', '待機中'),
          ('completed', '完了'), ('needs_human', '人間対応待ち'), ('failed', '失敗'),
          ('unavailable', '状態取得不能'), ('cancelled', '取消'))
COLUMNS = ('task', 'plan', 'repo', 'ai', 'status', 'dependencies', 'run')
HEADINGS = ('TASK ID', '計画 ID', '対象アプリ', '担当AI（設定）', '状態', '依存TASKの状態', 'Run ID')


def _id(value, limit):
    return value if isinstance(value, str) and re.fullmatch(
        r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) else UNKNOWN


def _fixed(value, labels):
    return labels.get(value, UNKNOWN) if isinstance(value, str) else UNKNOWN


def display_model(snapshot):
    """Pure allowlisted presentation; never forward arbitrary snapshot strings."""
    counts = dict.fromkeys((key for key, _ in COUNTS), 0)
    model = dict(counts=counts, rows=[], availability=UNKNOWN, unavailable_plans=0)
    if not isinstance(snapshot, dict) or type(snapshot.get('schema_version')) is not int or snapshot['schema_version'] != 1:
        return model
    model['availability'] = _fixed(snapshot.get('availability'),
        {'available': '取得済み', 'partial': '一部取得不能', 'unavailable': '取得不能'})
    plans = snapshot.get('plans')
    if not isinstance(plans, list):
        model['availability'] = '取得不能'
        return model
    for plan in plans:
        if not isinstance(plan, dict) or plan.get('availability') != 'available' or not isinstance(plan.get('tasks'), list):
            model['unavailable_plans'] += 1
            continue
        for task in plan['tasks']:
            task = task if isinstance(task, dict) else {}
            tid, pid, repo = (_id(task.get('task_id'), 16), _id(task.get('plan_id'), 32), _id(task.get('repo_key'), 80))
            status = _fixed(task.get('status'), STATUS)
            category = task.get('category')
            valid = (task.get('availability') == 'available' and UNKNOWN not in (tid, pid, repo, status)
                     and pid == plan.get('plan_id') and isinstance(category, str)
                     and overview.CATEGORY.get(task.get('status')) == category)
            run = task.get('run') if isinstance(task.get('run'), dict) else {}
            rid = run.get('run_id')
            rid = rid if isinstance(rid, str) and re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9]{6}', rid) else UNKNOWN
            stage = _fixed(run.get('stage'), STAGES)
            live = _fixed(run.get('liveness'), LIVENESS)
            if category == 'running':
                valid = valid and rid != UNKNOWN and run.get('availability') == 'available' and stage in overview.ACTIVE_STAGES and live in ('running', 'starting')
            bucket = ('waiting' if category == 'not_started' else category) if valid else 'unavailable'
            if bucket not in counts:
                bucket = 'unavailable'
            counts['total'] += 1
            counts[bucket] += 1
            deps = task.get('dependencies')
            dependency_text = UNKNOWN
            if isinstance(deps, list) and len(deps) <= 50:
                dependency_text = '、'.join(
                    _id(d.get('task_id'), 16) + ': ' + _fixed(d.get('status'), STATUS)
                    if isinstance(d, dict) else UNKNOWN for d in deps) or 'なし'
            main = _fixed(task.get('main_ai'), {'claude': 'Claude', 'codex': 'Codex'})
            reviewer = _fixed(task.get('reviewer_ai'), {'claude': 'Claude', 'codex': 'Codex'})
            # Missing settings are absence, never proof of an active agent.
            if task.get('main_ai') is None:
                main = '未設定'
            if task.get('reviewer_ai') is None:
                reviewer = '未設定'
            shown_status = status if valid else UNKNOWN
            availability = '取得済み' if valid else '取得不能・確認待ち'
            run_availability = '取得済み' if run.get('availability') == 'available' and rid != UNKNOWN and stage != UNKNOWN and live != UNKNOWN else '取得不能・確認待ち'
            detail = (f'TASK ID: {tid}　計画 ID: {pid}　対象アプリ: {repo}\n'
                      f'固定状態: {shown_status}\n依存関係: {dependency_text}\n'
                      f'状態取得可否: {availability}\n関連Run ID: {rid}\n'
                      f'Run状態: {stage}　稼働観測: {live}　Run取得可否: {run_availability}')
            model['rows'].append(dict(identity=(pid, tid), values=(tid, pid, repo,
                f'Executor: {main} / Reviewer: {reviewer}', shown_status, dependency_text, rid), detail=detail))
    return model


def summary_text(model):
    return '　'.join(f'{label}: {model["counts"][key]}' for key, label in COUNTS)


def apply_table_theme(window, tree, horizontal, vertical, style):
    """Use the same palette/detection as reports_inbox_view, with local styles."""
    from .app import DARK_BG, DARK_SURFACE, DARK_FIELD, DARK_FG, DARK_BORDER, DARK_SELECTION
    dark = style.lookup('TFrame', 'background') == DARK_BG
    if dark:
        style.configure('Manager.Treeview', background=DARK_SURFACE, fieldbackground=DARK_SURFACE,
                        foreground=DARK_FG, bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.map('Manager.Treeview', background=[('selected', DARK_SELECTION)], foreground=[('selected', DARK_FG)])
        style.configure('Manager.Treeview.Heading', background=DARK_FIELD, foreground=DARK_FG,
                        bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
        style.map('Manager.Treeview.Heading', background=[('active', DARK_FIELD), ('pressed', DARK_SELECTION)], foreground=[('active', DARK_FG)])
        for orientation in ('Horizontal', 'Vertical'):
            name = f'Manager.{orientation}.TScrollbar'
            style.configure(name, background=DARK_FIELD, troughcolor=DARK_BG, arrowcolor=DARK_FG,
                            bordercolor=DARK_BORDER, lightcolor=DARK_BORDER, darkcolor=DARK_BORDER)
            style.map(name, background=[('active', DARK_SELECTION), ('pressed', DARK_SELECTION)])
    window.configure(background=DARK_BG if dark else style.lookup('TFrame', 'background'))
    tree.configure(style='Manager.Treeview' if dark else 'Treeview')
    horizontal.configure(style='Manager.Horizontal.TScrollbar' if dark else 'Horizontal.TScrollbar')
    vertical.configure(style='Manager.Vertical.TScrollbar' if dark else 'Vertical.TScrollbar')


class ManagerDashboardWindow:
    def __init__(self, master, snapshot, *, inbox=False):
        self.window = tk.Toplevel(master)
        self.window.title('組織ダッシュボード')
        self.window.geometry('1150x650')
        self.window.minsize(760, 480)
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)
        ttk.Label(frame, text=MANAGER_TEXT).grid(row=0, column=0, sticky='w')
        self.summary = ttk.Label(frame, wraplength=1080)
        self.summary.grid(row=1, column=0, sticky='ew', pady=8)
        self.notice = ttk.Label(frame)
        self.notice.grid(row=2, column=0, sticky='w')
        self.inbox = None
        if inbox:
            from .manager_inbox import ManagerInboxView
            tabs = ttk.Notebook(frame)
            tabs.grid(row=3, column=0, sticky='nsew', pady=8)
            table = ttk.Frame(tabs)
            self.inbox = ManagerInboxView(tabs, window=self.window)
            tabs.add(table, text='TASK一覧')
            tabs.add(self.inbox.frame, text='判断受信箱')
        else:
            table = ttk.Frame(frame)
            table.grid(row=3, column=0, sticky='nsew', pady=8)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=COLUMNS, show='headings', selectmode='browse')
        for key, label in zip(COLUMNS, HEADINGS):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=220 if key in ('ai', 'dependencies', 'run') else 125, minwidth=90)
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        self.vertical = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.tree.configure(xscrollcommand=self.horizontal.set, yscrollcommand=self.vertical.set)
        details = ttk.LabelFrame(frame, text='選択TASKの詳細', padding=8)
        details.grid(row=4, column=0, sticky='ew')
        self.detail = ttk.Label(details, text='TASKを選択してください', justify='left', wraplength=1080)
        self.detail.pack(fill='x')
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        self.window.bind('<<ThemeChanged>>', self._apply_theme, add='+')
        self._apply_theme()
        self.set_snapshot(snapshot)

    def _apply_theme(self, _event=None):
        style = ttk.Style(self.window)
        key = (style.theme_use(), style.lookup('TFrame', 'background'))
        if key != getattr(self, '_theme_key', None):
            self._theme_key = key
            apply_table_theme(self.window, self.tree, self.horizontal, self.vertical, style)
            if self.inbox is not None:
                self.inbox.apply_theme(style)

    def set_snapshot(self, snapshot):
        """Presentation only. Caller owns collection and invokes this on the Tk thread."""
        previous = self.tree.selection()
        identity = self._rows.get(previous[0], {}).get('identity') if previous and hasattr(self, '_rows') else None
        model = display_model(snapshot)
        self.summary.configure(text=summary_text(model))
        self.notice.configure(text=f'スナップショット: {model["availability"]}　取得不能な計画: {model["unavailable_plans"]}　待機中には未実行を含みます')
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._rows = {}
        selected = None
        for index, row in enumerate(model['rows']):
            iid = f'row-{index}'
            self._rows[iid] = row
            self.tree.insert('', 'end', iid=iid, values=row['values'])
            if row['identity'] == identity:
                selected = iid
        if selected is not None:
            self.tree.selection_set(selected)
        self._on_select()

    def _on_select(self, _event=None):
        selected = self.tree.selection()
        row = self._rows.get(selected[0]) if selected else None
        self.detail.configure(text=row['detail'] if row else 'TASKを選択してください')
