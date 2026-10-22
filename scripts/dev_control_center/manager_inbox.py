"""Pure, fixed-schema Manager inbox projection. No AI, persistence or action APIs.

Rows are advisory data only. Unreadable plans have no known TASK identities and
are counted separately instead of inventing TASKs. Future AI ingestion must use
its own validation before producing this schema; no AI adapter is connected here.
"""
from __future__ import annotations

import re
from tkinter import ttk

from . import manager_decision as decision
from .manager_dashboard_view import apply_table_theme

GROUPS = (('human', '人間の確認が必要'), ('start_candidate', '開始提案の候補'),
          ('waiting', '待機・保留'), ('done', '完了・対応不要'), ('unknown', '取得不能・確認待ち'))
KINDS_TO_GROUP = {'NO_ACTION': 'done', 'PROPOSE_START': 'start_candidate',
                  'REQUEST_HUMAN': 'human', 'WAIT': 'waiting'}
INBOX_REASONS = frozenset(('COLLECTION_UNAVAILABLE', 'COLLECTION_PARTIAL', 'SNAPSHOT_INVALID'))
STATUS_TEXT = {'available': '取得済み', 'partial': '一部取得不能・確認待ち',
               'unavailable': '取得不能・確認待ち', 'updating': '更新中・判断未確認'}


def _id(value, limit):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) else '確認待ち'


def empty_inbox(status='unavailable'):
    return dict(schema_version=1, status=status if isinstance(status, str) and status in STATUS_TEXT else 'unavailable',
                source='rules', scope='disk', rows=[], unavailable_plans=0)


def build_inbox(snapshot, *, observation_id, collection_status, memory_available=False, issues=()):
    """Reuse suggest_decisions, retaining plan order and Runner's single candidate.

    Caller supplies the same disk-provisional snapshot as the preview. Collection
    issues override affected TASKs, never become free-text display reasons.
    Partial collection without locatable issues is conservatively unconfirmed.
    """
    model = empty_inbox()
    model['scope'] = 'memory' if memory_available else 'disk'
    if collection_status not in ('available', 'partial'):
        return model
    if not isinstance(snapshot, dict) or snapshot.get('availability') not in ('available', 'partial'):
        return model
    if snapshot['availability'] == 'partial':
        collection_status = 'partial'
    try:
        decisions = decision.suggest_decisions(snapshot, observation_id=observation_id)
    except (decision.DecisionError, TypeError, KeyError, RecursionError):
        return model
    model['status'] = collection_status
    unavailable_plans = sum(p['availability'] != 'available' for p in snapshot['plans'])
    model['unavailable_plans'] = unavailable_plans
    if unavailable_plans:
        model['status'] = 'partial'
    affected = set()
    global_issue = False
    if collection_status == 'partial':
        if not isinstance(issues, (list, tuple)) or not issues:
            global_issue = not unavailable_plans
        else:
            for issue in issues:
                if not isinstance(issue, dict):
                    global_issue = True
                    continue
                pid, tid = issue.get('plan_id'), issue.get('task_id')
                if _id(pid, 32) == '確認待ち':
                    global_issue = True
                else:
                    affected.add((pid, tid if _id(tid, 16) != '確認待ち' else None))
    for item in decisions:
        pid, tid = item['plan_id'], item['task_id']
        uncertain = global_issue or (pid, tid) in affected or (pid, None) in affected
        reason, kind = item['reason_code'], item['kind']
        group = KINDS_TO_GROUP[kind]
        if reason == 'STATE_UNAVAILABLE':
            group = 'unknown'
        if uncertain:
            group, kind, reason = 'unknown', 'REQUEST_HUMAN', 'COLLECTION_PARTIAL'
        model['rows'].append(dict(plan_id=pid, task_id=tid, kind=kind, reason_code=reason,
            category=group, source='rules', snapshot_id=item['snapshot_id'], observation_id=observation_id))
    return model


def row_values(row):
    """Allowlist again at the widget boundary; never stringify raw dicts/AI output."""
    row = row if isinstance(row, dict) else {}
    category = row.get('category')
    category = category if isinstance(category, str) else 'unknown'
    group = dict(GROUPS).get(category, dict(GROUPS)['unknown'])
    kind = row.get('kind')
    kind = kind if isinstance(kind, str) and kind in decision.KINDS else '確認待ち'
    reason = row.get('reason_code')
    reason = reason if isinstance(reason, str) and reason in decision.REASONS | INBOX_REASONS else 'SNAPSHOT_INVALID'
    return (group, _id(row.get('plan_id'), 32), _id(row.get('task_id'), 16), kind, reason)


def inbox_summary(model):
    rows = model.get('rows', []) if isinstance(model, dict) else []
    rows = rows if isinstance(rows, list) else []
    counts = {label: 0 for _, label in GROUPS}
    for row in rows:
        counts[row_values(row)[0]] += 1
    return '　'.join(f'{label}: {count}' for label, count in counts.items())


class ManagerInboxView:
    def __init__(self, parent, *, window):
        self.window = window
        self.frame = ttk.Frame(parent, padding=8)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        ttk.Label(self.frame, text='固定ルールによる読み取り専用の提案。開始候補は実行許可ではありません。',
                  wraplength=700).grid(row=0, column=0, sticky='w')
        self.summary = ttk.Label(self.frame, wraplength=700)
        self.summary.grid(row=1, column=0, sticky='ew', pady=6)
        table = ttk.Frame(self.frame)
        table.grid(row=2, column=0, sticky='nsew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ('category', 'plan', 'task', 'kind', 'reason')
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='browse')
        for key, label in zip(columns, ('分類', '計画 ID', 'TASK ID', '判断種別', '固定理由コード')):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=200 if key in ('category', 'kind', 'reason') else 120, minwidth=90)
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        self.vertical = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.tree.configure(xscrollcommand=self.horizontal.set, yscrollcommand=self.vertical.set)
        self.detail = ttk.Label(self.frame, wraplength=700, justify='left')
        self.detail.grid(row=3, column=0, sticky='ew', pady=8)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        self.set_model(empty_inbox('updating'))

    def apply_theme(self, style):
        apply_table_theme(self.window, self.tree, self.horizontal, self.vertical, style)

    def set_model(self, model):
        selected = self.tree.selection()
        identity = self._rows.get(selected[0], (None,))[0] if selected and hasattr(self, '_rows') else None
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        status = model.get('status') if isinstance(model, dict) else None
        status = status if isinstance(status, str) and status in STATUS_TEXT else 'unavailable'
        rows = model.get('rows', []) if isinstance(model, dict) and status in ('available', 'partial') else []
        rows = rows if isinstance(rows, list) else []
        count = model.get('unavailable_plans') if isinstance(model, dict) else 0
        count = count if type(count) is int and count >= 0 else 0
        self.summary.configure(text=STATUS_TEXT[status] + '\n' + inbox_summary(dict(rows=rows)) + f'　取得不能な計画: {count}')
        scope = '本体メモリ優先' if isinstance(model, dict) and model.get('scope') == 'memory' else 'ディスクのみ・本体メモリ未確認'
        self._rows = {}
        for index, row in enumerate(rows):
            values = row_values(row)
            key = (values[1], values[2])
            detail = ('固定ルールによる提案（承認・実行は行いません）\n'
                      f'計画 ID: {values[1]}　TASK ID: {values[2]}\n'
                      f'分類: {values[0]}　判断種別: {values[3]}\n理由コード: {values[4]}\n観測範囲: {scope}')
            iid = f'inbox-{index}'
            self._rows[iid] = (key, detail)
            self.tree.insert('', 'end', iid=iid, values=values)
            if identity == key:
                self.tree.selection_set(iid)
        self._select()

    def _select(self, _event=None):
        selected = self.tree.selection()
        row = self._rows.get(selected[0]) if selected else None
        self.detail.configure(text=row[1] if row else 'TASKを選択してください（確認・実行操作はありません）')
