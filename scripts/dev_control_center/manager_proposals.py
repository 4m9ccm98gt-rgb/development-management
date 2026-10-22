"""Inert rule proposals, NOT Workflow tasks or Workflow mutation proposals.

Input is the current validated MGR inbox row. Future AI ingestion requires a
separate validator; arbitrary AI text is never rendered. IDs are stable display
identities only. Every proposal also binds its exact observation and snapshot.
Validation against a freshly built inbox is not approval or execution authority.

Workflow handoff (future): humans must supply repo/title/body/acceptance criteria,
new TASK ID and current base_revision, then use Workflow's preview_proposal and
human approval. No body, ops, revision, executable instruction or success criteria
is fabricated here. Drafts cannot be submitted to Workflow as completed TASKs.
"""
from __future__ import annotations

import hashlib
import json
import re

ACTION_LABELS = dict(
    INVESTIGATE_FAILURE='失敗原因を調査する', REQUEST_HUMAN='人間に判断を依頼する',
    REVIEW_CANDIDATE='候補内容を確認する', REQUEST_APPROVAL='TASK内容の承認判断を依頼する',
    CHECK_DEPENDENCIES='未完了の依存TASKを確認する', CHECK_HOLD='保留理由と再開条件を確認する',
    CHECK_PLAN='先行TASK・計画状態を確認する', CHECK_START='既存Workflowに基づく開始可否の確認を提案する',
    WAIT_FOR_CHANGE='完了・状態変化を待つ', NO_FOLLOWUP='追加対応なし',
    CHECK_DATA='データ取得・状態の確認を依頼する',
    CONSIDER_INVESTIGATION='調査TASKの作成を検討（根拠確認が必要）',
    CONSIDER_SPEC='仕様変更の要否を検討（仕様確認が必要）',
    CONSIDER_DEPENDENCIES='依存関係見直しの要否を検討（根拠確認が必要）')
CHECK_LABELS = dict(
    FAILURE_EVIDENCE='失敗の事実・再現条件・関連する確認済み記録',
    HUMAN_CONTEXT='人間判断が必要な論点と元の仕様',
    CANDIDATE_EVIDENCE='候補内容・検証結果・既存の承認条件',
    TASK_REQUIREMENTS='元TASKの内容・受入条件・承認権限',
    DEPENDENCY_STATE='未完了の依存TASKの正本状態と依存の必要性',
    RESUME_CONDITIONS='保留理由・再開条件', PLAN_STATE='先行TASKと計画の正本状態',
    RUNNER_GATES='既存Runnerの最新の許可条件・停止条件（この提案は実行許可ではありません）',
    RUN_OBSERVATION='最新のRun観測と完了状態', COLLECTION_STATE='最新の計画・Run関連付け・本体メモリの確認',
    DRAFT_CONTEXT='調査・仕様確認後に人間が必要性を判断（本文・手順・成功条件は未作成）')
STATE_LABELS = dict(CHECK_REQUIRED='確認待ち', INFORMATION_ONLY='情報提示のみ', DRAFT_NEEDS_EVIDENCE='未完成下書き・根拠確認待ち')
# cause -> exact Workflow statuses, MGR-3 kind/reason, action, evidence
RULES = {
    'FAILED': (('failed',), 'REQUEST_HUMAN', 'TASK_FAILED', 'INVESTIGATE_FAILURE', 'FAILURE_EVIDENCE'),
    'HUMAN': (('needs_human',), 'REQUEST_HUMAN', 'HUMAN_REQUIRED', 'REQUEST_HUMAN', 'HUMAN_CONTEXT'),
    'CANDIDATE': (('candidate_ready',), 'REQUEST_HUMAN', 'HUMAN_REQUIRED', 'REVIEW_CANDIDATE', 'CANDIDATE_EVIDENCE'),
    'APPROVAL': (('proposed',), 'REQUEST_HUMAN', 'APPROVAL_REQUIRED', 'REQUEST_APPROVAL', 'TASK_REQUIREMENTS'),
    'DEPENDENCY': (('approved',), 'WAIT', 'DEPENDENCIES_PENDING', 'CHECK_DEPENDENCIES', 'DEPENDENCY_STATE'),
    'HELD': (('held',), 'WAIT', 'HELD', 'CHECK_HOLD', 'RESUME_CONDITIONS'),
    'QUEUED': (('approved',), 'WAIT', 'QUEUED', 'CHECK_PLAN', 'PLAN_STATE'),
    'START': (('approved',), 'PROPOSE_START', 'APPROVED_READY', 'CHECK_START', 'RUNNER_GATES'),
    'ACTIVE': (('running',), 'WAIT', 'TASK_ACTIVE', 'WAIT_FOR_CHANGE', 'RUN_OBSERVATION'),
    'TERMINAL': (('landed', 'cancelled'), 'NO_ACTION', 'TERMINAL', 'NO_FOLLOWUP', None),
}
DRAFTS = dict(FAILED='CONSIDER_INVESTIGATION', HUMAN='CONSIDER_SPEC', DEPENDENCY='CONSIDER_DEPENDENCIES')
UNKNOWN_REASONS = frozenset(('STATE_UNAVAILABLE', 'COLLECTION_PARTIAL', 'COLLECTION_UNAVAILABLE', 'SNAPSHOT_INVALID', 'TASK_ACTIVE'))


def _matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def build_proposals(row):
    """One action and at most one conditional draft per current inbox TASK."""
    if not isinstance(row, dict):
        return []
    pid, tid, sid, generation = (row.get(k) for k in ('plan_id', 'task_id', 'snapshot_id', 'observation_id'))
    if (not _matches(pid, r'[A-Za-z0-9-]{1,32}') or not _matches(tid, r'[A-Za-z0-9-]{1,16}')
        or not _matches(sid, r'[0-9a-f]{64}') or type(generation) is not int or generation < 0):
        return []
    cause, reason = row.get('cause'), row.get('reason_code')
    if not isinstance(cause, str) or not isinstance(reason, str):
        return []
    if cause == 'UNKNOWN' and reason in UNKNOWN_REASONS:
        action, check = 'CHECK_DATA', 'COLLECTION_STATE'
    elif cause in RULES:
        statuses, kind, expected_reason, action, check = RULES[cause]
        if row.get('workflow_status') not in statuses or row.get('kind') != kind or reason != expected_reason:
            return []
    else:
        return []
    priority, owner = row.get('priority'), row.get('owner')
    if not isinstance(priority, str) or priority not in ('P1', 'P2', 'P3', 'P4', 'PX'):
        return []
    if not isinstance(owner, str) or owner not in ('UNKNOWN', 'HUMAN', 'HUMAN_CHECK', 'DEPENDENCY', 'AI_CODEX', 'AI_CLAUDE', 'START_CHECK', 'NONE'):
        return []
    deps = row.get('dependencies')
    if not isinstance(deps, list) or len(deps) > 50:
        return []
    clean_deps = []
    for dep in deps:
        if (not isinstance(dep, dict) or set(dep) != {'task_id', 'status'}
            or not _matches(dep.get('task_id'), r'[A-Za-z0-9-]{1,16}')
            or dep.get('status') not in ('proposed', 'approved', 'held', 'running', 'candidate_ready', 'landed', 'failed', 'needs_human', 'cancelled')):
            return []
        clean_deps.append(dict(dep))
    result = []
    choices = [('ACTION', action, [check] if check else [])]
    if cause in DRAFTS:
        choices.append(('IMPROVEMENT_DRAFT', DRAFTS[cause], [check, 'DRAFT_CONTEXT']))
    for kind, code, checks in choices:
        identity = json.dumps([pid, tid, reason, kind, code], separators=(',', ':'))
        result.append(dict(schema_version=1, proposal_id=hashlib.sha256(identity.encode()).hexdigest(),
            plan_id=pid, task_id=tid, proposal_type=kind, action_code=code, reason_code=reason,
            priority=priority, owner_code=owner, required_checks=checks, dependencies=[dict(d) for d in clean_deps],
            state='DRAFT_NEEDS_EVIDENCE' if kind == 'IMPROVEMENT_DRAFT' else
                  'INFORMATION_ONLY' if code in ('NO_FOLLOWUP', 'WAIT_FOR_CHANGE') else 'CHECK_REQUIRED',
            observation_id=generation, snapshot_id=sid,
            basis=dict(workflow_status=row.get('workflow_status') if row.get('workflow_status') in
                ('proposed', 'approved', 'held', 'running', 'candidate_ready', 'landed', 'failed', 'needs_human', 'cancelled') else 'unknown',
                reason_code=reason, cause_code=cause)))
    return result


def validate_proposals(proposals, current_row):
    """Exact equality to current rule output, including observation; no authority.

    Caller must supply the latest rebuilt inbox row, never a stored old row.
    This is display validation, not MGR-4 revalidation or a Workflow permission.
    """
    expected = build_proposals(current_row)
    try:
        return bool(expected) and json.dumps(proposals, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        return False


def proposal_text(row):
    """Render only validated codes; never interpolate raw output or extra fields."""
    items = row.get('proposals') if isinstance(row, dict) else None
    if not validate_proposals(items, row):
        return '解決アクション: 確認待ち（提案を確認できません）'
    lines = []
    for item in items:
        label = '対応アクション' if item['proposal_type'] == 'ACTION' else '改善TASK下書き（作成・適用は行いません）'
        lines.append(f'{label}: {ACTION_LABELS[item["action_code"]]}／{STATE_LABELS[item["state"]]}')
        lines.append('提案の根拠: ' + item['reason_code'])
        lines.append('追加確認: ' + '、'.join(CHECK_LABELS[c] for c in item['required_checks']) if item['required_checks'] else '追加確認: なし')
    return '\n'.join(lines)
