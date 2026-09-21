"""Core logic for the local Development Control Center.

The GUI discovers and launches each repository's tracked, formal lifecycle
entrypoints. It does not reimplement SYNC / RUN / BUILD / UPDATE.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import tomllib
from typing import Callable, Iterable
from urllib.parse import quote

from .timing import TIMING

DEFAULT_OWNER = "4m9ccm98gt-rgb"
ACTIVE_TYPES = {"desktop", "web", "service", "management"}
SKIP_DIR_NAMES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".pytest_cache"
}
SCRIPT_SUFFIXES = {".cmd", ".bat"}
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GITHUB_REMOTE_RE = re.compile(r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?$", re.IGNORECASE)
CI_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}


GIT_TIMEOUT_SECONDS = 15
CANCEL_POLL_SECONDS = 0.2


class ControlCenterConfigError(ValueError):
    """Raised when the central repository registry is incomplete."""


class Cancelled(Exception):
    """Cooperative cancellation of a background load (deliberately not a RuntimeError)."""


@dataclass(frozen=True)
class RepoDefinition:
    name: str
    repo_type: str
    branch: str
    owner: str = DEFAULT_OWNER
    application_implemented: bool = True
    initial_ai_task: str = ""
    initial_test: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.full_name}"


@dataclass(frozen=True)
class RemoteRepo:
    name: str
    default_branch: str = ""
    owner: str = DEFAULT_OWNER
    is_archived: bool = False
    is_fork: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.full_name}"


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    title: str
    head_branch: str
    head_sha: str
    base_branch: str
    is_draft: bool
    url: str


@dataclass(frozen=True)
class GitHubState:
    branch_sha: str = ""
    ci_sha: str = ""
    ci_target: str = ""
    ci_state: str = "UNKNOWN"
    check_count: int = 0
    latest_pr: PullRequestInfo | None = None
    candidate_blocked_by_pr: bool = False
    error: str = ""

    @property
    def candidate_ready(self) -> bool:
        """The expected-branch HEAD can be a candidate without green Actions.

        Open PRs are informational only here. They may change which CI target is
        displayed, but they must never invalidate the already-merged expected
        branch HEAD.
        """
        return candidate_sha_is_valid(self.branch_sha) and not self.error


@dataclass(frozen=True)
class EntryPointChoice:
    state: str
    path: Path | None = None
    candidates: tuple[Path, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state == "READY" and self.path is not None


@dataclass(frozen=True)
class RepoEntrypoints:
    sync: EntryPointChoice
    run: EntryPointChoice
    build: EntryPointChoice
    release: EntryPointChoice
    release_label: str


@dataclass(frozen=True)
class LifecycleDecision:
    """Pure lifecycle decision used by the GUI and tests.

    Candidate selection is derived from durable Git/GitHub state. A valid
    explicit candidate wins; otherwise the expected branch HEAD is restored
    automatically. Open PRs never erase the expected-branch candidate.
    """

    candidate_sha: str = ""
    candidate_source: str = "-"
    sync_enabled: bool = False
    run_enabled: bool = False
    build_enabled: bool = False
    release_enabled: bool = False
    banner: str = ""
    sync_reason: str = ""
    run_reason: str = ""
    build_reason: str = ""
    release_reason: str = ""


@dataclass(frozen=True)
class RepoState:
    exists: bool
    is_git_repo: bool
    branch: str = ""
    head: str = ""
    origin_head: str = ""
    origin_repo: str = ""
    tracked_dirty: bool = False
    untracked_count: int = 0
    error: str = ""

    def safe_for_lifecycle(self, definition: RepoDefinition) -> bool:
        return (
            self.exists
            and self.is_git_repo
            and not self.error
            and self.branch == definition.branch
            and not self.tracked_dirty
            and self.origin_repo.lower() == definition.full_name.lower()
        )


def load_repo_definitions(
    types_path: Path,
    branches_path: Path,
    owner: str = DEFAULT_OWNER,
) -> list[RepoDefinition]:
    """Load app types plus explicitly configured candidate branches."""
    with types_path.open("rb") as f:
        types = tomllib.load(f).get("types", {})
    with branches_path.open("rb") as f:
        registry = tomllib.load(f)
        branches = registry.get("branches", {})
        unimplemented = registry.get("unimplemented", {})
        initial_tasks = registry.get("initial_ai_tasks", {})
        initial_tests = registry.get("initial_tests", {})

    definitions: list[RepoDefinition] = []
    for name, repo_type in sorted(types.items()):
        repo_type = str(repo_type).strip()
        branch = str(branches.get(name, "")).strip()
        if repo_type in ACTIVE_TYPES and not branch:
            raise ControlCenterConfigError(
                f"{name}: explicit candidate branch is missing from {branches_path.name}"
            )
        definitions.append(
            RepoDefinition(
                str(name),
                repo_type,
                branch,
                owner,
                name not in unimplemented,
                str(initial_tasks.get(name, "")).strip(),
                str(initial_tests.get(name, "")).strip(),
            )
        )
    return definitions


def active_repo_definitions(
    types_path: Path,
    branches_path: Path,
    owner: str = DEFAULT_OWNER,
) -> list[RepoDefinition]:
    return [
        d for d in load_repo_definitions(types_path, branches_path, owner)
        if d.repo_type in ACTIVE_TYPES
    ]


def candidate_sha_is_valid(value: str) -> bool:
    """Candidates are always identified by the complete 40-character SHA."""
    return bool(SHA_RE.fullmatch(value.strip()))


def decide_lifecycle(
    definition: RepoDefinition,
    repo_state: RepoState,
    entrypoints: RepoEntrypoints,
    github_state: GitHubState | None = None,
    explicit_candidate: str = "",
    busy: bool = False,
) -> LifecycleDecision:
    """Derive candidate and button state from durable repository state.

    The function intentionally does not depend on GUI memory. This means a DCC
    restart can reconstruct the same lifecycle state from Git/GitHub facts.
    """

    manual = explicit_candidate.strip().lower()
    branch_sha = ""
    github_error = ""
    if github_state is not None:
        branch_sha = github_state.branch_sha.strip().lower()
        github_error = github_state.error

    if manual:
        candidate = manual
        source = "AUTO / branch HEAD" if manual == branch_sha else "MANUAL"
    elif candidate_sha_is_valid(branch_sha) and not github_error:
        candidate = branch_sha
        source = "AUTO / branch HEAD"
    else:
        candidate = ""
        source = "-"

    safe = repo_state.safe_for_lifecycle(definition)
    matches = bool(
        candidate
        and candidate_sha_is_valid(candidate)
        and repo_state.head.strip().lower() == candidate
    )

    def blocked_reason(choice: EntryPointChoice, *, require_match: bool) -> str:
        if busy:
            return "別工程を実行中"
        if not safe:
            return repo_state.error or "repo / branch / origin / tracked clean の安全条件NG"
        if not choice.ready:
            return f"正式入口が {choice.state}"
        if not candidate_sha_is_valid(candidate):
            return "完全40桁candidate SHAが未確定"
        if require_match and not matches:
            return "local HEAD が candidate と不一致"
        if not require_match and matches:
            return "local HEAD は既に candidate と一致"
        return ""

    sync_reason = blocked_reason(entrypoints.sync, require_match=False)
    run_reason = blocked_reason(entrypoints.run, require_match=True)
    build_reason = blocked_reason(entrypoints.build, require_match=True)
    release_reason = blocked_reason(entrypoints.release, require_match=True)

    sync_enabled = not sync_reason
    run_enabled = not run_reason
    build_enabled = not build_reason
    release_enabled = not release_reason

    if busy:
        banner = "工程実行中。完了後に状態を自動再評価します。"
    elif not safe:
        banner = "安全条件NG。repo / branch / origin / tracked clean を確認してください。"
    elif not candidate_sha_is_valid(candidate):
        if github_error:
            banner = "GitHub状態を取得できません。必要なら完全40桁candidate SHAを手入力してください。"
        else:
            banner = "candidateを確定できません。GitHub状態を更新してください。"
    elif not matches:
        banner = f"candidate {short_sha(candidate)} へSYNCしてください。"
    else:
        available: list[str] = []
        if run_enabled:
            available.append("RUN")
        if build_enabled:
            available.append("BUILD")
        if release_enabled:
            available.append(entrypoints.release_label)
        if available:
            banner = f"candidate {short_sha(candidate)} 同期済み。利用可能: {' / '.join(available)}"
        else:
            banner = f"candidate {short_sha(candidate)} 同期済み。正式入口の状態を確認してください。"

    return LifecycleDecision(
        candidate_sha=candidate,
        candidate_source=source,
        sync_enabled=sync_enabled,
        run_enabled=run_enabled,
        build_enabled=build_enabled,
        release_enabled=release_enabled,
        banner=banner,
        sync_reason=sync_reason,
        run_reason=run_reason,
        build_reason=build_reason,
        release_reason=release_reason,
    )


def parse_github_repo(remote_url: str) -> str:
    match = GITHUB_REMOTE_RE.search(remote_url.strip())
    return match.group(1) if match else ""


_CHILDREN: set[subprocess.Popen] = set()
_CHILDREN_LOCK = threading.Lock()


def kill_registered_children() -> None:
    """Kill every cancellable child still running (used when the app closes)."""
    with _CHILDREN_LOCK:
        children = list(_CHILDREN)
    for child in children:
        try:
            child.kill()
        except OSError:
            pass


def _run_cancellable(
    args: list[str],
    timeout: float,
    cancel: threading.Event,
    *,
    text: bool,
) -> subprocess.CompletedProcess:
    """Popen + communicate polling so a cancel Event or timeout terminates the child."""
    kwargs: dict[str, object] = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if text:
        kwargs.update(text=True, encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(args, **kwargs)
    except OSError as exc:
        raise RuntimeError(f"command unavailable: {args[0]}: {exc}") from exc
    with _CHILDREN_LOCK:
        _CHILDREN.add(proc)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel.is_set():
                raise Cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"command timed out: {' '.join(args[:4])}")
            try:
                out, err = proc.communicate(timeout=min(CANCEL_POLL_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                continue
            return subprocess.CompletedProcess(args, proc.returncode, out, err)
    finally:
        with _CHILDREN_LOCK:
            _CHILDREN.discard(proc)
        if proc.poll() is None:
            try:
                proc.kill()
                proc.communicate(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass


def _run_process(
    args: list[str],
    timeout: int = 20,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    if cancel is not None:
        return _run_cancellable(args, timeout, cancel, text=True)
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out: {' '.join(args[:4])}") from exc
    except OSError as exc:
        raise RuntimeError(f"command unavailable: {args[0]}: {exc}") from exc


def _gh_label(args: list[str]) -> str:
    return "gh:" + " ".join(args[:2])


def _run_gh_json(args: list[str], cancel: threading.Event | None = None) -> object:
    with TIMING.span(_gh_label(args)):
        proc = _run_process(["gh", *args], cancel=cancel)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise RuntimeError(detail)
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned invalid JSON") from exc


def list_github_repositories(
    owner: str = DEFAULT_OWNER,
    *,
    cancel: threading.Event | None = None,
) -> list[RemoteRepo]:
    """List non-archived, non-fork repositories visible to authenticated gh."""
    args = [
        "repo", "list", owner,
        "--limit", "200",
        "--json", "name,isArchived,isFork,defaultBranchRef",
    ]
    payload = _run_gh_json(args, cancel=cancel) if cancel is not None else _run_gh_json(args)
    if not isinstance(payload, list):
        raise RuntimeError("GitHub repository list had an unexpected shape")
    result: list[RemoteRepo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        branch_ref = item.get("defaultBranchRef") or {}
        branch = branch_ref.get("name", "") if isinstance(branch_ref, dict) else ""
        repo = RemoteRepo(
            name=str(item.get("name", "")).strip(),
            default_branch=str(branch or "").strip(),
            owner=owner,
            is_archived=bool(item.get("isArchived")),
            is_fork=bool(item.get("isFork")),
        )
        if repo.name and not repo.is_archived and not repo.is_fork:
            result.append(repo)
    return sorted(result, key=lambda item: item.name.lower())


def unmanaged_github_repositories(
    managed_names: Iterable[str],
    remote_repositories: Iterable[RemoteRepo],
) -> list[RemoteRepo]:
    known = {name.lower() for name in managed_names}
    return [
        repo
        for repo in remote_repositories
        if repo.name.lower() not in known and not repo.is_archived and not repo.is_fork
    ]


def summarize_ci_state(check_runs_payload: object, status_payload: object) -> tuple[str, int]:
    """Return GREEN/PENDING/FAILED/NO CHECKS from GitHub check/status payloads."""
    check_runs: list[dict] = []
    if isinstance(check_runs_payload, dict):
        raw_runs = check_runs_payload.get("check_runs", [])
        if isinstance(raw_runs, list):
            check_runs = [item for item in raw_runs if isinstance(item, dict)]

    classic_total = 0
    classic_state = ""
    if isinstance(status_payload, dict):
        try:
            classic_total = int(status_payload.get("total_count", 0) or 0)
        except (TypeError, ValueError):
            classic_total = 0
        classic_state = str(status_payload.get("state", "") or "").lower()

    total = len(check_runs) + classic_total
    if not total:
        return "NO CHECKS", 0

    for run in check_runs:
        status = str(run.get("status", "") or "").lower()
        if status != "completed":
            return "PENDING", total
        conclusion = str(run.get("conclusion", "") or "").lower()
        if conclusion not in CI_SUCCESS_CONCLUSIONS:
            return "FAILED", total

    if classic_total:
        if classic_state in {"failure", "error"}:
            return "FAILED", total
        if classic_state != "success":
            return "PENDING", total

    return "GREEN", total


def _latest_open_pr(
    full_name: str,
    base_branch: str,
    runner: Callable[..., object],
    cancel: threading.Event | None,
) -> PullRequestInfo | None:
    payload = runner([
        "pr", "list",
        "--repo", full_name,
        "--state", "open",
        "--base", base_branch,
        "--limit", "1",
        "--json", "number,title,headRefName,headRefOid,baseRefName,isDraft,url",
    ], cancel=cancel)
    if not isinstance(payload, list) or not payload:
        return None
    item = payload[0]
    if not isinstance(item, dict):
        return None
    return PullRequestInfo(
        number=int(item.get("number", 0) or 0),
        title=str(item.get("title", "") or ""),
        head_branch=str(item.get("headRefName", "") or ""),
        head_sha=str(item.get("headRefOid", "") or ""),
        base_branch=str(item.get("baseRefName", "") or ""),
        is_draft=bool(item.get("isDraft")),
        url=str(item.get("url", "") or ""),
    )


def _ci_for_sha(
    full_name: str,
    sha: str,
    runner: Callable[..., object],
    cancel: threading.Event | None,
) -> tuple[str, int]:
    check_runs = runner([
        "api", f"repos/{full_name}/commits/{sha}/check-runs?per_page=100",
    ], cancel=cancel)
    combined_status = runner([
        "api", f"repos/{full_name}/commits/{sha}/status",
    ], cancel=cancel)
    return summarize_ci_state(check_runs, combined_status)


def fetch_github_state(
    definition: RepoDefinition,
    *,
    cancel: threading.Event | None = None,
    runner: Callable[..., object] | None = None,
) -> GitHubState:
    """Fetch expected-branch HEAD, relevant PR and best-effort CI state.

    ``cancel`` raises Cancelled (never swallowed as a GitHub error); ``runner``
    is injectable for tests and defaults to the ``gh`` JSON runner.
    """
    runner = runner or _run_gh_json
    try:
        branch_name = quote(definition.branch, safe="")
        branch_payload = runner([
            "api", f"repos/{definition.full_name}/branches/{branch_name}",
        ], cancel=cancel)
        if not isinstance(branch_payload, dict):
            raise RuntimeError("branch response had an unexpected shape")
        commit = branch_payload.get("commit") or {}
        branch_sha = str(commit.get("sha", "") if isinstance(commit, dict) else "").strip()
        if not candidate_sha_is_valid(branch_sha):
            raise RuntimeError(f"expected branch '{definition.branch}' has no usable HEAD SHA")

        try:
            latest_pr = _latest_open_pr(definition.full_name, definition.branch, runner, cancel)
        except RuntimeError:
            latest_pr = None

        if latest_pr and candidate_sha_is_valid(latest_pr.head_sha):
            ci_sha = latest_pr.head_sha
            ci_target = f"PR #{latest_pr.number}"
            candidate_blocked_by_pr = True
        else:
            ci_sha = branch_sha
            ci_target = definition.branch
            candidate_blocked_by_pr = False

        try:
            ci_state, check_count = _ci_for_sha(definition.full_name, ci_sha, runner, cancel)
        except RuntimeError:
            ci_state, check_count = "UNAVAILABLE", 0

        return GitHubState(
            branch_sha=branch_sha,
            ci_sha=ci_sha,
            ci_target=ci_target,
            ci_state=ci_state,
            check_count=check_count,
            latest_pr=latest_pr,
            candidate_blocked_by_pr=candidate_blocked_by_pr,
        )
    except RuntimeError as exc:
        return GitHubState(error=str(exc))


def build_new_repo_setup_prompt(remote: RemoteRepo, local_path: Path) -> str:
    """AI request text (for the DCC AI request field) that registers a new repo."""
    branch_text = remote.default_branch or "未確定（GitHub上で確認して明示設定すること）"
    return (
        "新規repoをdevelopment-managementの正式管理対象へ登録してください。\n"
        f"GitHub: {remote.github_url}\n"
        f"正式ローカル: {local_path}\n"
        f"GitHub default branch: {branch_text}\n\n"
        "対象repoのREADMEと構成を確認し、repo種別を確定してください。candidate branchは推測せず明示してください。\n"
        "scripts/repo_types.toml と scripts/dev_control_center_repos.toml の [branches] へ正式登録してください。\n"
        "同じ scripts/dev_control_center_repos.toml の [initial_ai_tasks] / [initial_tests] へ、"
        "このrepoの最初のAI依頼と独立テストコマンドを追加してください。\n"
        "SYNC / RUN_DEV / BUILD / UPDATE・DEPLOYの正式入口の有無を確認し、不足はこのrepo側の最初のAI依頼へ含めてください。"
        "このタスクではdevelopment-management以外のrepoを変更しません。\n"
        "秘密情報・実運用データはGit管理しません。関連する自動テストを追加・更新してください。"
    )


def clone_new_repository(remote: RemoteRepo, repos_root: Path) -> Path:
    """Clone an unmanaged repository into canonical repos root without overwriting."""
    dest = repos_root / remote.name
    if (dest / ".git").exists():
        return dest
    if dest.exists():
        raise RuntimeError(f"{dest} exists but is not a Git repository")
    repos_root.mkdir(parents=True, exist_ok=True)
    proc = _run_process(["gh", "repo", "clone", remote.full_name, str(dest)], timeout=120)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise RuntimeError(f"clone failed: {detail}")
    if not (dest / ".git").exists():
        raise RuntimeError("clone command completed but .git was not created")
    return dest


def _filesystem_scripts(
    repo_root: Path,
    max_depth: int = 3,
    cancel: threading.Event | None = None,
) -> list[Path]:
    """Files of a non-Git tree, pruning skipped and too-deep directories.

    Result-equivalent to a full rglob followed by the SKIP_DIR_NAMES / depth
    filters in _iter_scripts, without descending into node_modules and friends.
    """
    found: list[Path] = []
    root_text = str(repo_root)
    for dirpath, dirnames, filenames in os.walk(root_text):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        depth = 0 if dirpath == root_text else len(Path(dirpath).relative_to(repo_root).parts)
        dirnames[:] = [
            name for name in dirnames
            if name not in SKIP_DIR_NAMES and depth + 1 <= max_depth
        ]
        found.extend(Path(dirpath) / name for name in filenames)
    return found


def _tracked_files(repo_root: Path, cancel: threading.Event | None = None) -> list[Path] | None:
    """Return tracked files for a Git repo; None means this is not a Git repo."""
    if not (repo_root / ".git").exists():
        return None
    args = ["git", "-C", str(repo_root), "ls-files", "-z"]
    try:
        if cancel is not None:
            proc = _run_cancellable(args, GIT_TIMEOUT_SECONDS, cancel, text=False)
        else:
            proc = subprocess.run(
                args, capture_output=True, check=False, timeout=GIT_TIMEOUT_SECONDS
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("git ls-files timed out") from exc
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    items = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return [repo_root / item for item in items if item]


def _iter_scripts(
    repo_root: Path,
    max_depth: int = 3,
    cancel: threading.Event | None = None,
) -> list[Path]:
    if not repo_root.is_dir():
        return []
    source = _tracked_files(repo_root, cancel)
    candidates = source if source is not None else _filesystem_scripts(repo_root, max_depth, cancel)
    found: list[Path] = []
    for index, path in enumerate(candidates):
        if cancel is not None and index % 256 == 0 and cancel.is_set():
            raise Cancelled()
        if not path.is_file() or path.suffix.lower() not in SCRIPT_SUFFIXES:
            continue
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            continue
        if len(rel.parts) - 1 > max_depth:
            continue
        if any(part in SKIP_DIR_NAMES for part in rel.parts):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.relative_to(repo_root).as_posix().lower())


def _choose(
    repo_root: Path,
    files: Iterable[Path],
    levels: Iterable[Callable[[str], bool]],
) -> EntryPointChoice:
    files = list(files)
    for matcher in levels:
        matches = [p for p in files if matcher(p.name.upper())]
        if not matches:
            continue
        min_depth = min(len(p.relative_to(repo_root).parts) for p in matches)
        nearest = sorted(
            [p for p in matches if len(p.relative_to(repo_root).parts) == min_depth],
            key=lambda p: p.relative_to(repo_root).as_posix().lower(),
        )
        if len(nearest) == 1:
            return EntryPointChoice("READY", nearest[0], tuple(matches))
        return EntryPointChoice("MULTIPLE", None, tuple(nearest))
    return EntryPointChoice("MISSING")


def _exact(*names: str) -> Callable[[str], bool]:
    allowed = {name.upper() for name in names}
    return lambda name: name in allowed


def _regex(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda name: bool(rx.fullmatch(name))


def discover_entrypoints(
    repo_root: Path,
    repo_type: str,
    *,
    application_implemented: bool = True,
    cancel: threading.Event | None = None,
) -> RepoEntrypoints:
    """Conservatively find formal user-facing lifecycle entrypoints."""
    scripts = _iter_scripts(repo_root, cancel=cancel)
    sync = _choose(repo_root, scripts, [
        _exact("SYNC_CLICK_ME.cmd"),
        _regex(r"SYNC.*CLICK_ME\.(?:CMD|BAT)"),
    ])
    run = _choose(repo_root, scripts, [
        _exact("RUN_DEV.cmd"),
        _regex(r"(?:RUN|START).*DEV.*\.(?:CMD|BAT)"),
    ])
    build = _choose(repo_root, scripts, [
        _exact("BUILD_EXE_CLICK_ME.cmd"),
        _exact("BUILD_俺伝_CLICK_ME.cmd"),
        _exact("BUILD_RELEASE.cmd"),
        _regex(r"BUILD.*CLICK_ME\.(?:CMD|BAT)"),
    ])

    if repo_type == "management":
        build = EntryPointChoice("N/A")
    elif repo_type in {"web", "service"} and build.state == "MISSING":
        build = EntryPointChoice("N/A")

    if repo_type == "desktop":
        release_label = "UPDATE"
        release = _choose(repo_root, scripts, [
            _exact("UPDATE_SHARED_FOLDER.cmd"),
            _exact("UPDATE_HDD_CLICK_ME.cmd"),
            _exact("UPDATE.cmd"),
            _regex(r"UPDATE.*CLICK_ME\.(?:CMD|BAT)"),
            _regex(r"UPDATE_[A-Z0-9_]+\.(?:CMD|BAT)"),
        ])
    elif repo_type == "web":
        release_label = "DEPLOY"
        release = _choose(repo_root, scripts, [
            _exact("DEPLOY_CLICK_ME.cmd"),
            _exact("DEPLOY.cmd"),
            _regex(r"DEPLOY.*CLICK_ME\.(?:CMD|BAT)"),
        ])
    elif repo_type == "service":
        release_label = "INSTALL / UPDATE"
        release = _choose(repo_root, scripts, [
            _exact("INSTALL_SERVICE_CLICK_ME.cmd"),
            _exact("INSTALL_TASK_CLICK_ME.cmd"),
            _exact("REGISTER_TASK_CLICK_ME.cmd"),
            _regex(r"(?:INSTALL|REGISTER|DEPLOY|UPDATE).*CLICK_ME\.(?:CMD|BAT)"),
        ])
    else:
        release_label = "N/A"
        release = EntryPointChoice("N/A")
    if not application_implemented:
        if build.state == "MISSING":
            build = EntryPointChoice("N/A")
        if release.state == "MISSING":
            release = EntryPointChoice("N/A")
    return RepoEntrypoints(sync, run, build, release, release_label)


def _run_git(
    repo_root: Path,
    *args: str,
    allow_fail: bool = False,
    cancel: threading.Event | None = None,
) -> str:
    command = ["git", "-C", str(repo_root), *args]
    if cancel is not None:
        proc = _run_cancellable(command, GIT_TIMEOUT_SECONDS, cancel, text=True)
    else:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"git {' '.join(args)}: timed out") from exc
    output = (proc.stdout or "").strip()
    if proc.returncode != 0 and not allow_fail:
        detail = (proc.stderr or output or f"exit {proc.returncode}").strip()
        raise RuntimeError(f"git {' '.join(args)}: {detail}")
    return output if proc.returncode == 0 else ""


def inspect_repo(
    repo_root: Path,
    definition: RepoDefinition,
    cancel: threading.Event | None = None,
) -> RepoState:
    if not repo_root.is_dir():
        return RepoState(False, False, error="local repository directory is missing")
    if not (repo_root / ".git").exists():
        return RepoState(True, False, error=".git is missing")
    try:
        branch = _run_git(repo_root, "branch", "--show-current", cancel=cancel)
        if not branch:
            return RepoState(True, True, error="detached HEAD")
        head = _run_git(repo_root, "rev-parse", "HEAD", cancel=cancel)
        origin_repo = parse_github_repo(_run_git(repo_root, "remote", "get-url", "origin", cancel=cancel))
        tracked = _run_git(repo_root, "status", "--porcelain", "--untracked-files=no", cancel=cancel)
        all_status = _run_git(repo_root, "status", "--porcelain", "--untracked-files=all", cancel=cancel)
        untracked_count = sum(1 for line in all_status.splitlines() if line.startswith("?? "))
        origin_head = _run_git(
            repo_root,
            "rev-parse",
            f"refs/remotes/origin/{definition.branch}",
            allow_fail=True,
            cancel=cancel,
        )
        return RepoState(
            True,
            True,
            branch=branch,
            head=head,
            origin_head=origin_head,
            origin_repo=origin_repo,
            tracked_dirty=bool(tracked.strip()),
            untracked_count=untracked_count,
        )
    except (OSError, RuntimeError) as exc:
        return RepoState(True, True, error=str(exc))


def apply_local_candidate(
    repo_root: Path,
    definition: RepoDefinition,
    *,
    base_sha: str,
    candidate_sha: str,
) -> str:
    """Fast-forward only the local expected branch to an Orchestrator candidate.

    This never pushes. It is intentionally strict because it bridges the
    isolated Orchestrator worktree back into the real-machine verification
    working tree.
    """
    base = base_sha.strip().lower()
    candidate = candidate_sha.strip().lower()
    if not candidate_sha_is_valid(base) or not candidate_sha_is_valid(candidate):
        raise RuntimeError("base/candidate must be complete 40-character SHAs")

    state = inspect_repo(repo_root, definition)
    if not state.safe_for_lifecycle(definition):
        raise RuntimeError(
            state.error or "repo / branch / origin / tracked clean safety conditions failed"
        )
    if state.head.strip().lower() != base:
        raise RuntimeError(
            f"local HEAD moved since orchestration started: {short_sha(base)} -> {short_sha(state.head)}"
        )

    resolved = _run_git(repo_root, "rev-parse", "--verify", f"{candidate}^{{commit}}")
    if resolved.strip().lower() != candidate:
        raise RuntimeError("candidate commit could not be resolved exactly")

    ancestry = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", base, candidate],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("candidate is not a fast-forward descendant of the orchestration base")

    merge = subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--ff-only", candidate],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if merge.returncode != 0:
        detail = (merge.stderr or merge.stdout or f"exit {merge.returncode}").strip()
        raise RuntimeError(f"local candidate fast-forward failed: {detail}")

    final = inspect_repo(repo_root, definition)
    if (
        not final.safe_for_lifecycle(definition)
        or final.head.strip().lower() != candidate
        or final.tracked_dirty
    ):
        raise RuntimeError("local candidate fast-forward completed but verification failed")
    return final.head


def suggest_test_command(repo_root: Path) -> str:
    """Return a conservative editable default for the DCC AI test field."""
    pyproject = repo_root / "pyproject.toml"
    pytest_markers = (
        (repo_root / "pytest.ini").exists()
        or (repo_root / "conftest.py").exists()
    )
    if pyproject.is_file():
        try:
            pytest_markers = pytest_markers or "pytest" in pyproject.read_text(
                encoding="utf-8", errors="ignore"
            ).lower()
        except OSError:
            pass
    if pytest_markers:
        return "python -m pytest -q"
    if (repo_root / "tests").is_dir():
        return "python -m unittest discover -s tests -v"
    return ""


def short_sha(value: str) -> str:
    return value[:12] if value else "-"


def choice_text(choice: EntryPointChoice, repo_root: Path) -> str:
    if choice.ready and choice.path:
        return f"READY  {choice.path.relative_to(repo_root)}"
    if choice.state == "MULTIPLE":
        rels = ", ".join(str(p.relative_to(repo_root)) for p in choice.candidates)
        return f"MULTIPLE  {rels}"
    return choice.state
