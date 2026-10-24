"""Pure, fixed-schema Manager inbox projection. No AI, persistence or action APIs.

Rows are advisory data only. Unreadable plans have no known TASK identities and
are counted separately instead of inventing TASKs. Future AI ingestion must use
its own validation before producing this schema; no AI adapter is connected here.
"""
from __future__ import annotations

import re
from tkinter import ttk

from . import manager_decision as decision
from . import manager_proposals as proposals
from .manager_dashboard_view import apply_table_theme, STATUS

GROUPS = (('human', '人間の確認が必要'), ('start_candidate', '開始提案の候補'),
          ('waiting', '待機・保留'), ('done', '完了・対応不要'), ('unknown', '取得不能・確認待ち'))
KINDS_TO_GROUP = {'NO_ACTION': 'done', 'PROPOSE_START': 'start_candidate',
                  'REQUEST_HUMAN': 'human', 'WAIT': 'waiting'}
INBOX_REASONS = frozenset(('COLLECTION_UNAVAILABLE', 'COLLECTION_PARTIAL', 'SNAPSHOT_INVALID'))
STATUS_TEXT = {'available': '取得済み', 'partial': '一部取得不能・確認待ち',
               'unavailable': '取得不能・確認待ち', 'updating': '更新中・判断未確認'}
CAUSES = dict(UNKNOWN='状態を確定できない', APPROVAL='人間の承認が必要', FAILED='失敗内容の確認が必要',
              HUMAN='人間の判断が必要', CANDIDATE='候補への対応が必要', DEPENDENCY='先行TASKが未完了',
              ACTIVE='処理中（Run観測済み）', HELD='保留状態', START='Runner基準の開始候補',
              QUEUED='Runnerの選択待ち', TERMINAL='現在の対応不要',
              # DCC Task UI-D2 (C1/C2): a needs_human TASK whose Run stopped on PROVIDER_QUOTA,
              # reclassified via orchestrator_requeue.quota_bucket (see analyze_task below).
              QUOTA_WAITING='使用枠待ち（自動再実行を予定）',
              QUOTA_MANUAL='手動で再投入が必要')
OWNERS = dict(UNKNOWN='確認待ち', HUMAN='人間', HUMAN_CHECK='人間／確認待ち', DEPENDENCY='依存TASK',
              AI_CODEX='Codex（実行担当設定）', AI_CLAUDE='Claude（実行担当設定）',
              START_CHECK='開始判断の確認先（未特定）', NONE='なし')
ACTIONS = dict(UNKNOWN='不明', CHECK='確認候補', WAIT='待機', NONE='対応不要')
# Confirmation priority, never business importance or execution permission.
# Preserve source plan/TASK order; PX is explicitly unranked, never below P4.
PRIORITIES = frozenset(('P1', 'P2', 'P3', 'P4', 'PX'))


def analyze_task(task, reason, *, memory_available):
    """Pure analysis of already validated Workflow data and MGR-3 reasons.

    No failure text is available. QUEUED explains only Runner selection, not
    permission/config/quota/repo conflicts. AI names are assignment, not liveness.
    """
    result = dict(priority='PX', cause='UNKNOWN', owner='UNKNOWN', action='UNKNOWN', dependencies=[])
    if not isinstance(task, dict):
        return result
    deps = task.get('dependencies')
    if isinstance(deps, list):
        result['dependencies'] = [dict(task_id=d['task_id'], status=d['status']) for d in deps
            if isinstance(d, dict) and _id(d.get('task_id'), 16) != '確認待ち'
            and isinstance(d.get('status'), str) and d['status'] in decision.wf.STATUSES]
    if task.get('availability') != 'available':
        return result
    rules = {
        'TERMINAL': ('P4', 'TERMINAL', 'NONE', 'NONE'),
        'TASK_FAILED': ('P1', 'FAILED', 'HUMAN', 'CHECK'),
        'HUMAN_REQUIRED': ('P1' if task.get('status') == 'needs_human' else 'P2',
                           'HUMAN' if task.get('status') == 'needs_human' else 'CANDIDATE', 'HUMAN', 'CHECK'),
        'APPROVAL_REQUIRED': ('P2', 'APPROVAL', 'HUMAN', 'CHECK'),
        'DEPENDENCIES_PENDING': ('P3', 'DEPENDENCY', 'DEPENDENCY', 'WAIT'),
        'HELD': ('P3', 'HELD', 'HUMAN_CHECK', 'WAIT'),
        'APPROVED_READY': ('P2', 'START', 'START_CHECK', 'CHECK'),
        'QUEUED': ('P3', 'QUEUED', 'UNKNOWN', 'WAIT'),
    }
    # DCC Task UI-D2 (C1/C2/C4): a needs_human TASK whose Run stopped on PROVIDER_QUOTA is
    # reclassified using orchestrator_requeue's own already-computed bucket (manager_overview._run
    # -> task['run']['quota_bucket'], never re-derived here). candidate_ready and every other
    # reason are completely untouched; so is a needs_human TASK whose Run carries no quota_bucket
    # at all (C4 -- every non-PROVIDER_QUOTA needs_human reason falls straight through to the
    # original HUMAN_REQUIRED rule above).
    if reason == 'HUMAN_REQUIRED' and task.get('status') == 'needs_human':
        run = task.get('run')
        quota = run.get('quota_bucket') if isinstance(run, dict) else None
        if quota == 'quota_waiting':
            # C1: removed from the human-facing cause/owner entirely -- the Manager's own
            # 動いているタスク view (overview.running_tasks) is where 使用枠待ち with its ETA
            # actually shows; this inbox row only needs to stop looking like 人の確認が必要.
            rules['HUMAN_REQUIRED'] = ('P4', 'QUOTA_WAITING', 'NONE', 'WAIT')
        elif quota in ('manual_temporary', 'manual_permanent'):
            # C2: stays owned by HUMAN (human side keeps 人の確認が必要 unchanged) -- only the
            # cause text changes, to the Manager-facing 手動で再投入が必要 sentence. The
            # temporary/permanent distinction itself lives in task['run']['quota_bucket'], not in
            # a second display cause (both share the one fixed sentence).
            rules['HUMAN_REQUIRED'] = ('P1', 'QUOTA_MANUAL', 'HUMAN', 'CHECK')
    if reason == 'TASK_ACTIVE':
        run = task.get('run')
        if (not memory_available or not isinstance(run, dict) or run.get('availability') != 'available'
            or run.get('liveness') not in ('running', 'starting') or run.get('stage') not in decision.overview.ACTIVE_STAGES):
            return result
        ai = task.get('main_ai')
        owner = {'codex': 'AI_CODEX', 'claude': 'AI_CLAUDE'}.get(ai) if isinstance(ai, str) else None
        rules['TASK_ACTIVE'] = ('P4', 'ACTIVE', owner or 'UNKNOWN', 'WAIT')
    values = rules.get(reason) if isinstance(reason, str) else None
    if values:
        result.update(zip(('priority', 'cause', 'owner', 'action'), values))
    return result


def analysis_values(row):
    """Allowlist the extended display schema again at the UI boundary."""
    row = row if isinstance(row, dict) else {}
    def label(key, words):
        value = row.get(key)
        return words.get(value, words['UNKNOWN']) if isinstance(value, str) else words['UNKNOWN']
    priority = row.get('priority')
    priority = priority if isinstance(priority, str) and priority in PRIORITIES else 'PX'
    return priority, label('cause', CAUSES), label('owner', OWNERS), label('action', ACTIONS)


def dependency_text(row):
    deps = row.get('dependencies') if isinstance(row, dict) else None
    if not isinstance(deps, list):
        return '確認待ち'
    parts = []
    for dep in deps:
        if not isinstance(dep, dict):
            parts.append('確認待ち')
            continue
        status = dep.get('status')
        status = status if isinstance(status, str) and status in decision.wf.STATUSES else '確認待ち'
        parts.append(f'{_id(dep.get("task_id"), 16)}: {status}')
    return '、'.join(parts) or 'なし'


def _id(value, limit):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9-]{1,' + str(limit) + '}', value) else '確認待ち'


def empty_inbox(status='unavailable'):
    return dict(schema_version=3, status=status if isinstance(status, str) and status in STATUS_TEXT else 'unavailable',
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
    tasks = {(p['plan_id'], t['task_id']): t for p in snapshot['plans'] for t in p['tasks']}
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
            category=group, source='rules', snapshot_id=item['snapshot_id'], observation_id=observation_id,
            workflow_status=tasks[(pid, tid)]['status'],
            **analyze_task(tasks[(pid, tid)], reason, memory_available=memory_available)))
        # DCC Task UI-D2 (C1/C3): a PROVIDER_QUOTA run with an actually-scheduled requeue moves
        # out of the human-facing group entirely -- analyze_task already set cause to
        # QUOTA_WAITING only for exactly that case, never for any other reason/cause.
        if model['rows'][-1]['cause'] == 'QUOTA_WAITING':
            model['rows'][-1]['category'] = 'waiting'
        model['rows'][-1]['proposals'] = proposals.build_proposals(model['rows'][-1])
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
        columns = ('category', 'plan', 'task', 'kind', 'reason', 'priority', 'cause', 'owner', 'action')
        self.tree = ttk.Treeview(table, columns=columns,
            displaycolumns=('priority', 'plan', 'task', 'cause', 'owner', 'action'), show='headings', selectmode='browse')
        for key, label in zip(columns, ('分類', '計画 ID', 'TASK ID', '判断種別', '固定理由コード',
                                       '確認優先度', '停滞・待機理由', '対応先', '対応可否')):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=170 if key in ('cause', 'owner') else 95, minwidth=65)
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
            values = row_values(row) + analysis_values(row)
            key = (values[1], values[2])
            state = row.get('workflow_status') if isinstance(row, dict) else None
            state = STATUS.get(state, '確認待ち') if isinstance(state, str) else '確認待ち'
            detail = ('固定ルールによる提案（承認・実行は行いません）\n'
                      f'計画 ID: {values[1]}　TASK ID: {values[2]}\n'
                      f'現在のWorkflow記録: {state}（Runの稼働確定とは別）\n'
                      f'分類: {values[0]}　判断種別: {values[3]}\n理由コード: {values[4]}\n'
                      f'確認優先度: {values[5]}（業務重要度ではありません。PXは未確定）\n'
                      f'原因: {values[6]}\n対応先: {values[7]}\n対応可否: {values[8]}（実行許可ではありません）\n'
                      f'依存TASK: {dependency_text(row)}\n観測範囲: {scope}\n'
                      + proposals.proposal_text(row))
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
