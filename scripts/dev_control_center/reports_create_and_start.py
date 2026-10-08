"""DCC Task 14.5: turn a completed AI investigation (reports_triage.py) into a one-click
"作成して開始" action -- (1) write the acceptance-criteria spec file with the existing Task 11
machinery (reports_inbox.create_spec_file), then (2) start the Orchestrator through its existing
entry point (tools.ai_orchestrator.orchestrator.start_run), both only after a human has reviewed
and confirmed in a dialog. No automatic start exists anywhere in this module: every function here
either answers a question (is the button enabled, what should the confirmation dialog show) or
performs the two actions above, and only when its caller explicitly invokes it.

Security posture (same as reports_triage.py and reports_inbox.py, restated here because this
module is the one that actually starts a run):
 - The repository is decided only from DCC's own registry (orchestrator.resolve_repo_dir_for_app /
   resolve_repo_definition, keyed by the report's app_key), never from report text or AI output.
 - The AI's suggested criteria (ai_suggested_criteria, built from TriageResult.suspected_locations
   and .criteria_draft) may be offered as editable, clearly-unconfirmed starting text for the
   human to keep, edit or delete -- never written anywhere by itself. Only the criteria lines the
   caller passes to create_and_start (after the human has seen and confirmed them) reach the spec
   file; the report body and the AI's reply_draft never reach this module at all.
 - The generated task text (build_task_text) contains only a fixed Japanese template plus the
   report's own `kind` label (one of the two fixed strings in reports_inbox.KIND_LABELS) -- never
   the report's title/body or any AI output.
 - Every failure path returns one of the fixed Japanese REASON_* strings below, never a path or
   exception's own text (same policy as reports_inbox.SpecCreateError / reports_triage.TriageParseError).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import reports_inbox as inbox
from . import reports_triage as triage

# DCC Task 14.5仕様1: only these two classifications mean "the AI investigation concluded there is
# something to act on" -- 質問 (spec_misunderstanding), 情報不足 (insufficient_info) and a failed
# investigation (outcome.result is None) all leave the button disabled.
STARTABLE_CLASSIFICATIONS = ("bug", "feature_request")

REASON_SPEC_FAILED = "仕様ファイルの作成に失敗しました。開始しません。"
REASON_REPO_UNAVAILABLE = "対象リポジトリの場所が分かりませんでした。開始しません。"
REASON_ALREADY_RUNNING = "対象リポジトリでは既にOrchestratorのrunが実行中です（1リポジトリ1 Run）。開始しません。"
REASON_TESTS_MISSING = "対象リポジトリの独立Testsコマンドが未設定です。開始しません。"
REASON_START_FAILED = "Orchestratorを開始できませんでした。開始しません。"
SPEC_CREATED_NOTE = "仕様ファイルは作成されました。"

ROLE_LABELS = {"claude": "Claude", "codex": "Codex"}

AI_GUESS_HEADING = "AIの推測（未確認）"

TASK_TITLE_TEMPLATE = "DCC報告対応"


def role_label(name: str) -> str:
    return ROLE_LABELS.get(name, name)


def button_enabled(outcome: "triage.TriageOutcome | None") -> bool:
    """Whether 作成して開始 is enabled for the current investigation outcome (DCC Task
    14.5仕様1/C4): only a completed investigation (outcome.result is not None) classified as
    バグ or 変更要望 (feature_request) enables it. A still-running investigation (outcome is
    None), a failed one (outcome.result is None), 質問 (spec_misunderstanding), and 情報不足
    (insufficient_info) all leave it disabled."""
    if outcome is None or outcome.result is None:
        return False
    return outcome.result.classification in STARTABLE_CLASSIFICATIONS


def build_task_title(report: "inbox.Report") -> str:
    """固定のひな形 + 報告の種類 (C6): `report.kind_label` is always one of the two fixed strings
    in reports_inbox.KIND_LABELS (kind is validated against reports_inbox.KINDS when the report
    is parsed) -- never free text from the report or the AI."""
    return f"{TASK_TITLE_TEMPLATE}（{report.kind_label}）"


def build_task_text(report: "inbox.Report") -> str:
    """The Orchestrator task text for 作成して開始 (DCC Task 14.5仕様3): a fixed Japanese template
    plus build_task_title's fixed title -- never the report's title/body, never any AI output.
    Acceptance criteria live in the spec file this run starts with, not in this text."""
    return (
        f"{build_task_title(report)}\n\n"
        "目的: 受け取った利用者からの報告に対応する。\n"
        "受入条件はこのTaskに添付された仕様ファイルに従うこと。報告の本文はこの依頼文には含めない。\n"
    )


def ai_suggested_criteria(result: "triage.TriageResult") -> list[str]:
    """Candidate受入条件 lines built from the AI investigation's own criteria_draft and
    suspected_locations (DCC Task 14.5仕様1/C7) -- offered to the human under the
    AI_GUESS_HEADING, editable, never written anywhere unless the human keeps them and presses
    作成して開始. Both source fields are already sanitized and length-bounded by
    reports_triage._validate_payload (_clean), so no further cleanup is needed here."""
    lines = list(result.criteria_draft)
    lines += [f"修正箇所の候補: {loc}" for loc in result.suspected_locations]
    return lines


@dataclass(frozen=True)
class ConfirmInfo:
    """What the 作成して開始 confirmation dialog shows (C6): never a path, never AI output beyond
    the already-reviewed criteria lines the caller supplies separately."""

    app_display_name: str
    repo_display_name: str
    main_agent: str
    review_agent: str
    task_title: str

    @property
    def roles_text(self) -> str:
        return f"Main = {role_label(self.main_agent)} / Reviewer = {role_label(self.review_agent)}"


REPO_DISPLAY_NAME_UNKNOWN = "（不明）"


def _default_resolve_repo_dir(app_key: str) -> Path | None:
    from tools.ai_orchestrator.orchestrator import resolve_repo_dir_for_app

    return resolve_repo_dir_for_app(app_key)


def build_confirm_info(report: "inbox.Report", *, main_agent: str, review_agent: str,
                        resolve_repo_dir: Callable[[str], Path | None] | None = None) -> ConfirmInfo:
    """Build the confirmation dialog's display info. The repository is looked up only from DCC's
    own registry (resolve_repo_dir, defaulting to the real orchestrator.resolve_repo_dir_for_app)
    keyed by report.app_key -- never from report text or AI output; only the resolved directory's
    own *name* is shown (never its path, C6). When it cannot be resolved yet, a fixed placeholder
    is shown instead -- the real reason is only surfaced when 作成して開始 is actually pressed
    (create_and_start)."""
    resolve_repo_dir = resolve_repo_dir or _default_resolve_repo_dir
    try:
        repo_dir = resolve_repo_dir(report.app_key)
    except Exception:  # noqa: BLE001 - registry trouble must degrade, never crash the dialog
        repo_dir = None
    repo_display_name = repo_dir.name if repo_dir is not None else REPO_DISPLAY_NAME_UNKNOWN
    return ConfirmInfo(
        app_display_name=report.app_display_name, repo_display_name=repo_display_name,
        main_agent=main_agent, review_agent=review_agent, task_title=build_task_title(report),
    )


@dataclass(frozen=True)
class StartResult:
    ok: bool
    reason: str = ""
    spec_path: Path | None = None
    run_dir: Path | None = None

    @property
    def spec_created_note(self) -> str:
        return SPEC_CREATED_NOTE if (not self.ok and self.spec_path is not None) else ""


def _default_start_run(*, repo: str, task: str, main_agent: str, review_agent: str, spec) -> Path:
    """The real "既存のOrchestrator起動と同じ入口" (C11): the identical function
    orchestrator_view.OrchestratorWindow._confirm_start calls, with the same prepare_source /
    fetch defaults it uses (a human is not manually preparing the source branch here either).
    Tests / tests / branch default come from DCC's own registry only (resolve_repo_definition),
    matched by `repo`'s own directory name -- the same lookup orchestrator_view.start_run already
    does when a human leaves the Tests field blank."""
    from tools.ai_orchestrator.common import OrchestratorError
    from tools.ai_orchestrator.orchestrator import StartRequest, resolve_repo_definition
    from tools.ai_orchestrator.orchestrator import start_run as orch_start_run

    definition = resolve_repo_definition(Path(repo).name)
    tests = getattr(definition, "initial_test", "") if definition else ""
    if not tests:
        raise OrchestratorError(REASON_TESTS_MISSING, "TESTS_MISSING")
    branch = getattr(definition, "branch", None) if definition else None
    request = StartRequest(
        repo=repo, task=task, tests=[tests], main_agent=main_agent, review_agent=review_agent,
        expected_branch=branch, prepare_source=True, fetch=True, spec=spec,
    )
    return orch_start_run(request)


def create_and_start(
    report: "inbox.Report",
    criteria_lines: list[str],
    *,
    main_agent: str,
    review_agent: str,
    resolve_repo_dir: Callable[[str], Path | None] | None = None,
    create_spec_file: Callable[..., Path] | None = None,
    start_run: Callable[..., Path] | None = None,
) -> StartResult:
    """(1) write the spec file, (2) start the Orchestrator -- only ever called after a human has
    reviewed the criteria and pressed 作成して開始 in the confirmation dialog (DCC Task
    14.5仕様3). Never raises: every failure becomes a StartResult with one of the fixed REASON_*
    Japanese strings above, never a path or exception's own text (C15).

    The repository is resolved only from DCC's own registry (resolve_repo_dir, keyed by
    report.app_key) -- criteria_lines (human-confirmed, possibly AI-suggested-then-edited text)
    never influence it (C19). create_spec_file defaults to reports_inbox.create_spec_file, which
    never overwrites an existing spec file (C10) and never includes the report body (C19).
    start_run defaults to _default_start_run, the same entry point a human's own 開始 button uses
    (C11); it is called at most once, only after the spec file was written successfully."""
    from tools.ai_orchestrator import taskspec
    from tools.ai_orchestrator.common import OrchestratorError
    from tools.ai_orchestrator.runstate import ActiveRunExists

    resolve_repo_dir = resolve_repo_dir or _default_resolve_repo_dir
    create_spec_file = create_spec_file or inbox.create_spec_file
    start_run = start_run or _default_start_run

    reason = inbox.validate_criteria_lines(criteria_lines)
    if reason:
        return StartResult(False, reason)

    try:
        spec_path = create_spec_file(criteria_lines, report.app_key, report.identity)
    except inbox.SpecCreateError as exc:
        return StartResult(False, str(exc))
    except Exception:  # noqa: BLE001 - never let an unexpected write failure crash the dialog
        return StartResult(False, REASON_SPEC_FAILED)

    try:
        repo_dir = resolve_repo_dir(report.app_key)
    except Exception:  # noqa: BLE001 - registry trouble must degrade, never crash the dialog
        repo_dir = None
    if repo_dir is None:
        return StartResult(False, REASON_REPO_UNAVAILABLE, spec_path=spec_path)

    try:
        spec = taskspec.load_spec_file(spec_path)
    except taskspec.SpecError:
        return StartResult(False, REASON_SPEC_FAILED, spec_path=spec_path)

    task_text = build_task_text(report)
    try:
        run_dir = start_run(repo=str(repo_dir), task=task_text, main_agent=main_agent,
                             review_agent=review_agent, spec=spec)
    except ActiveRunExists:
        return StartResult(False, REASON_ALREADY_RUNNING, spec_path=spec_path)
    except OrchestratorError as exc:
        reason = str(exc) if str(exc) == REASON_TESTS_MISSING else REASON_START_FAILED
        return StartResult(False, reason, spec_path=spec_path)
    except Exception:  # noqa: BLE001 - never show a raw exception to the user (C15)
        return StartResult(False, REASON_START_FAILED, spec_path=spec_path)

    return StartResult(True, "", spec_path=spec_path, run_dir=run_dir)
