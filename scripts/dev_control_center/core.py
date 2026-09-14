"""Core logic for the local Development Control Center.

The GUI discovers and launches each repository's tracked, formal lifecycle
entrypoints. It does not reimplement SYNC / RUN / BUILD / UPDATE.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Callable, Iterable
from urllib.parse import quote

DEFAULT_OWNER = "4m9ccm98gt-rgb"
ACTIVE_TYPES = {"desktop", "web", "service"}
SKIP_DIR_NAMES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".pytest_cache"
}
SCRIPT_SUFFIXES = {".cmd", ".bat"}
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", re.IGNORECASE)
CI_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}


class ControlCenterConfigError(ValueError):
    """Raised when the central repository registry is incomplete."""


@dataclass(frozen=True)
class RepoDefinition:
    name: str
    repo_type: str
    branch: str
    owner: str = DEFAULT_OWNER

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
    is_draft: bool
    url: str


@dataclass(frozen=True)
class GitHubState:
    branch_sha: str = ""
    ci_state: str = "UNKNOWN"
    check_count: int = 0
    latest_pr: PullRequestInfo | None = None
    error: str = ""

    @property
    def candidate_ready(self) -> bool:
        return bool(self.branch_sha) and self.ci_state == "GREEN" and not self.error


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
        branches = tomllib.load(f).get("branches", {})

    definitions: list[RepoDefinition] = []
    for name, repo_type in sorted(types.items()):
        repo_type = str(repo_type).strip()
        branch = str(branches.get(name, "")).strip()
        if repo_type in ACTIVE_TYPES and not branch:
            raise ControlCenterConfigError(
                f"{name}: explicit candidate branch is missing from {branches_path.name}"
            )
        definitions.append(RepoDefinition(str(name), repo_type, branch, owner))
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
    return bool(SHA_RE.fullmatch(value.strip()))


def parse_github_repo(remote_url: str) -> str:
    match = GITHUB_REMOTE_RE.search(remote_url.strip())
    return match.group(1) if match else ""


def _run_process(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
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


def _run_gh_json(args: list[str]) -> object:
    proc = _run_process(["gh", *args])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise RuntimeError(detail)
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned invalid JSON") from exc


def list_github_repositories(owner: str = DEFAULT_OWNER) -> list[RemoteRepo]:
    """List non-archived, non-fork repositories visible to authenticated gh."""
    payload = _run_gh_json([
        "repo", "list", owner,
        "--limit", "200",
        "--json", "name,isArchived,isFork,defaultBranchRef",
    ])
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


def _latest_open_pr(full_name: str) -> PullRequestInfo | None:
    payload = _run_gh_json([
        "pr", "list",
        "--repo", full_name,
        "--state", "open",
        "--limit", "1",
        "--json", "number,title,headRefName,isDraft,url",
    ])
    if not isinstance(payload, list) or not payload:
        return None
    item = payload[0]
    if not isinstance(item, dict):
        return None
    return PullRequestInfo(
        number=int(item.get("number", 0) or 0),
        title=str(item.get("title", "") or ""),
        head_branch=str(item.get("headRefName", "") or ""),
        is_draft=bool(item.get("isDraft")),
        url=str(item.get("url", "") or ""),
    )


def fetch_github_state(definition: RepoDefinition) -> GitHubState:
    """Fetch expected-branch HEAD, CI rollup and latest open PR via GitHub CLI."""
    try:
        branch_name = quote(definition.branch, safe="")
        branch_payload = _run_gh_json([
            "api", f"repos/{definition.full_name}/branches/{branch_name}",
        ])
        if not isinstance(branch_payload, dict):
            raise RuntimeError("branch response had an unexpected shape")
        commit = branch_payload.get("commit") or {}
        branch_sha = str(commit.get("sha", "") if isinstance(commit, dict) else "").strip()
        if not candidate_sha_is_valid(branch_sha):
            raise RuntimeError(f"expected branch '{definition.branch}' has no usable HEAD SHA")

        check_runs = _run_gh_json([
            "api", f"repos/{definition.full_name}/commits/{branch_sha}/check-runs?per_page=100",
        ])
        combined_status = _run_gh_json([
            "api", f"repos/{definition.full_name}/commits/{branch_sha}/status",
        ])
        ci_state, check_count = summarize_ci_state(check_runs, combined_status)
        try:
            latest_pr = _latest_open_pr(definition.full_name)
        except RuntimeError:
            latest_pr = None
        return GitHubState(
            branch_sha=branch_sha,
            ci_state=ci_state,
            check_count=check_count,
            latest_pr=latest_pr,
        )
    except RuntimeError as exc:
        return GitHubState(error=str(exc))


def build_startup_prompt(definition: RepoDefinition) -> str:
    """Create the reusable startup-set prompt for an already-managed repository."""
    return (
        f"対象repo: {definition.full_name}\n"
        f"candidate branch: {definition.branch}\n\n"
        "このrepoの開発を続けます。development-management を開発運用の正本として扱ってください。\n"
        "最初に OPERATING_CONTRACT.md / STARTUP_HANDOFF_POLICY.md / AGENT_EFFICIENCY_POLICY.md を確認し、"
        "現在工程と T0〜T3 を判定してください。T3なら AI_STARTUP.md のフル開始チェーン、"
        "T0/T1なら読み込み予算を守ってください。\n"
        "GitHub上で完結する①設計→②開発・PR・CI greenまではChatGPT側で進め、"
        "③SYNC / ④実機確認 / ⑤BUILD・UPDATEは正式ワンクリック入口を使う工程境界を維持してください。\n"
        "②完了時は candidate branch / candidate SHA / CI結果 / ④で確認する項目を明示してください。\n"
        "このあと私が開発内容を続けて指示します。"
    )


def build_new_repo_setup_prompt(remote: RemoteRepo, local_path: Path) -> str:
    branch_text = remote.default_branch or "未確定（GitHub上で確認して明示設定すること）"
    return (
        "新規repoをdevelopment-managementの正式管理対象へセットアップしてください。\n"
        f"GitHub: {remote.github_url}\n"
        f"正式ローカル候補: {local_path}\n"
        f"GitHub default branch: {branch_text}\n\n"
        "PROJECT_BOOTSTRAP.md / STARTUP_HANDOFF_POLICY.md / OPERATING_CONTRACT.md を正本として、"
        "repo種別を確定し、scripts/repo_types.toml と scripts/dev_control_center_repos.toml へ正式登録してください。"
        "candidate branchは推測せず明示してください。\n"
        "Windowsアプリなら SYNC / RUN_DEV / BUILD / UPDATE・DEPLOY の各入口を READY / N/A / MISSING で監査し、"
        "恒久入口がMISSINGならローカル代用品ではなくGitHub側の②開発として整備してください。\n"
        "秘密情報・実運用データはGit管理しないでください。GitHub側の実装・PR・CI greenまで進め、"
        "ローカルの初回準備が別途必要なら⓪スタートアップのhandoffを作って停止してください。"
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


def _filesystem_scripts(repo_root: Path) -> list[Path]:
    return [path for path in repo_root.rglob("*") if path.is_file()]


def _tracked_files(repo_root: Path) -> list[Path] | None:
    """Return tracked files for a Git repo; None means this is not a Git repo.

    Discovery in real repositories must never promote an untracked command file
    to a formal lifecycle entrypoint.
    """
    if not (repo_root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    items = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return [repo_root / item for item in items if item]


def _iter_scripts(repo_root: Path, max_depth: int = 3) -> list[Path]:
    if not repo_root.is_dir():
        return []
    source = _tracked_files(repo_root)
    candidates = source if source is not None else _filesystem_scripts(repo_root)
    found: list[Path] = []
    for path in candidates:
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


def discover_entrypoints(repo_root: Path, repo_type: str) -> RepoEntrypoints:
    """Conservatively find formal user-facing lifecycle entrypoints."""
    scripts = _iter_scripts(repo_root)
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

    if repo_type == "desktop":
        release_label = "UPDATE"
        release = _choose(repo_root, scripts, [
            _exact("UPDATE_SHARED_FOLDER.cmd"),
            _exact("UPDATE_HDD_CLICK_ME.cmd"),
            _regex(r"UPDATE.*CLICK_ME\.(?:CMD|BAT)"),
            _regex(r"UPDATE_[A-Z0-9_]+\.(?:CMD|BAT)"),
        ])
    elif repo_type == "web":
        release_label = "DEPLOY"
        release = _choose(repo_root, scripts, [
            _exact("DEPLOY_CLICK_ME.cmd"),
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
    return RepoEntrypoints(sync, run, build, release, release_label)


def _run_git(repo_root: Path, *args: str, allow_fail: bool = False) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (proc.stdout or "").strip()
    if proc.returncode != 0 and not allow_fail:
        detail = (proc.stderr or output or f"exit {proc.returncode}").strip()
        raise RuntimeError(f"git {' '.join(args)}: {detail}")
    return output if proc.returncode == 0 else ""


def inspect_repo(repo_root: Path, definition: RepoDefinition) -> RepoState:
    if not repo_root.is_dir():
        return RepoState(False, False, error="local repository directory is missing")
    if not (repo_root / ".git").exists():
        return RepoState(True, False, error=".git is missing")
    try:
        branch = _run_git(repo_root, "branch", "--show-current")
        if not branch:
            return RepoState(True, True, error="detached HEAD")
        head = _run_git(repo_root, "rev-parse", "HEAD")
        origin_repo = parse_github_repo(_run_git(repo_root, "remote", "get-url", "origin"))
        tracked = _run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
        all_status = _run_git(repo_root, "status", "--porcelain", "--untracked-files=all")
        untracked_count = sum(1 for line in all_status.splitlines() if line.startswith("?? "))
        origin_head = _run_git(
            repo_root,
            "rev-parse",
            f"refs/remotes/origin/{definition.branch}",
            allow_fail=True,
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


def short_sha(value: str) -> str:
    return value[:12] if value else "-"


def choice_text(choice: EntryPointChoice, repo_root: Path) -> str:
    if choice.ready and choice.path:
        return f"READY  {choice.path.relative_to(repo_root)}"
    if choice.state == "MULTIPLE":
        rels = ", ".join(str(p.relative_to(repo_root)) for p in choice.candidates)
        return f"MULTIPLE  {rels}"
    return choice.state
