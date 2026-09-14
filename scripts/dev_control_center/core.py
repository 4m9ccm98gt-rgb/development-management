"""Core logic for the local Development Control Center.

The GUI only discovers and launches each repository's tracked, formal
lifecycle entrypoints. It does not reimplement SYNC / RUN / BUILD / UPDATE.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Callable, Iterable

DEFAULT_OWNER = "4m9ccm98gt-rgb"
ACTIVE_TYPES = {"desktop", "web", "service"}
SKIP_DIR_NAMES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".pytest_cache"
}
SCRIPT_SUFFIXES = {".cmd", ".bat"}
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", re.IGNORECASE)


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


def _iter_scripts(repo_root: Path, max_depth: int = 3) -> list[Path]:
    if not repo_root.is_dir():
        return []
    found: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCRIPT_SUFFIXES:
            continue
        rel = path.relative_to(repo_root)
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
