"""AI Orchestrator: automatic Main / Reviewer development runs in an isolated worktree.

Every run is owned by its own detached worker process (`worker` command). DCC and the
CLI are only clients that start, watch and stop runs through the run directory; closing
either never stops a run. The run ends at a local candidate commit: this tool never
pushes, builds, deploys or updates anything.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field, fields
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from . import runstate as rs
from .common import (
    OrchestratorError, ProcessHooks, StopRequested, git, now_id, process_start_token, read_json,
    resolved_command, run_streaming, slugify, write_json_atomic,
)
from .engine import Engine, NeedsHuman, SafetyViolation, Snapshot
from .review import NO_TESTS_MARKER, zero_tests_ran
from .providers import (
    DEFAULT_MAIN_AGENT, DEFAULT_REVIEW_AGENT, PROVIDER_NAMES, active_api_billing_env, agent_env,
    make_provider, validate_roles,
)
from .taskspec import Spec, extract_target_repo_name, load_spec_file
from .usage import USAGE_PROVIDER_CLASSES, describe, make_usage_provider

DM_ROOT = Path(__file__).resolve().parents[2]
MAX_UNTRACKED_BYTES = 200_000
_REGISTRY_TYPES_PATH = DM_ROOT / "scripts" / "repo_types.toml"
_REGISTRY_BRANCHES_PATH = DM_ROOT / "scripts" / "dev_control_center_repos.toml"


# ------------------------------------------------------------------------- Git helpers

@dataclass(frozen=True)
class RepoBaseline:
    root: Path
    branch: str
    head_sha: str
    origin_sha: str


def _tracked_dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip())


def _fetch_expected_origin_branch(root: Path, branch: str) -> None:
    refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
    result = run_streaming([*resolved_command("git"), "-C", str(root), "fetch", "--prune", "origin", refspec], timeout=300)
    if result.returncode != 0:
        raise OrchestratorError(f"git fetch failed for origin/{branch}: {(result.stderr or result.stdout).strip()}",
                                "GIT_FETCH_FAILED")


_IN_PROGRESS_MARKERS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG")


def repo_toplevel(repo_arg: Path) -> Path:
    repo_arg = repo_arg.expanduser().resolve()
    probe = run_streaming([*resolved_command("git"), "-C", str(repo_arg), "rev-parse", "--show-toplevel"], timeout=120)
    if probe.returncode != 0:
        raise OrchestratorError(f"not a Git repository: {repo_arg}", "NOT_A_GIT_REPO")
    return Path(probe.stdout.strip()).resolve()


def _is_ancestor(root: Path, older: str, newer: str) -> bool:
    result = run_streaming([*resolved_command("git"), "-C", str(root), "merge-base", "--is-ancestor", older, newer],
                           timeout=120)
    if result.returncode not in (0, 1):
        raise OrchestratorError(f"git merge-base failed: {(result.stderr or result.stdout).strip()}", "GIT_FAILED")
    return result.returncode == 0


def prepare_source_branch(root: Path, branch: str | None) -> list[str]:
    """Bring a clean source repo onto the latest `branch` before a run: switch from another
    branch and fast-forward to origin. Only non-destructive Git operations are used (no stash,
    reset, force checkout, merge commit or branch deletion); anything else stops the start.
    Returns what was done, for the run record."""
    if not branch:
        raise OrchestratorError("the repo's managed branch is not configured; cannot prepare the source repo",
                                "BRANCH_UNKNOWN")
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").stdout.strip())
    busy = [name for name in _IN_PROGRESS_MARKERS if (git_dir / name).exists()]
    if busy:
        raise OrchestratorError("a Git operation is in progress in the source repo (" + ", ".join(busy)
                                + "); finish or abort it first", "SOURCE_OPERATION_IN_PROGRESS")
    if _tracked_dirty(root):
        changed = git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip().splitlines()
        raise OrchestratorError("source repo has uncommitted changes; nothing was switched or pulled. "
                                "Commit or discard them yourself first:\n" + "\n".join(changed[:20]), "SOURCE_DIRTY")
    current = git(root, "branch", "--show-current").stdout.strip()
    if not current:
        raise OrchestratorError("source repository is detached; switch to a branch yourself first", "SOURCE_DETACHED")
    _fetch_expected_origin_branch(root, branch)
    remote = git(root, "rev-parse", f"refs/remotes/origin/{branch}").stdout.strip().lower()
    local_probe = run_streaming([*resolved_command("git"), "-C", str(root), "rev-parse", "--verify", "--quiet",
                                 f"refs/heads/{branch}"], timeout=120)
    local = local_probe.stdout.strip().lower() if local_probe.returncode == 0 else ""
    behind = False
    if local and local != remote:
        if _is_ancestor(root, local, remote):
            behind = True
        elif _is_ancestor(root, remote, local):
            raise OrchestratorError(f"local {branch} has commits not on origin/{branch} ({local[:12]} ahead of "
                                    f"{remote[:12]}); push or resolve them yourself", "SOURCE_AHEAD")
        else:
            raise OrchestratorError(f"local {branch} and origin/{branch} have diverged ({local[:12]} / {remote[:12]}); "
                                    "no merge or reset is done automatically", "SOURCE_DIVERGED")
    actions: list[str] = []
    if current != branch:
        args = ("switch", branch) if local else ("switch", "--track", f"origin/{branch}")
        try:
            git(root, *args, timeout=300)
        except OrchestratorError as exc:
            raise OrchestratorError(f"could not switch the source repo from {current} to {branch}: {exc}",
                                    "SOURCE_SWITCH_FAILED") from exc
        actions.append(f"switched {current} -> {branch} ({current} is kept)")
    if behind:
        try:
            git(root, "merge", "--ff-only", f"refs/remotes/origin/{branch}", timeout=300)
        except OrchestratorError as exc:
            raise OrchestratorError(f"fast-forward of {branch} failed: {exc}", "SOURCE_FF_FAILED") from exc
        actions.append(f"fast-forwarded {branch} {local[:12]} -> {remote[:12]}")
    return actions


def repo_baseline(repo_arg: Path, expected_branch: str | None, do_fetch: bool) -> RepoBaseline:
    """Start-time preconditions only: clean tracked tree on the expected branch == origin."""
    repo_arg = repo_arg.expanduser().resolve()
    root = Path(git(repo_arg, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    if _tracked_dirty(root):
        raise OrchestratorError("tracked working tree is dirty; refusing to start", "SOURCE_DIRTY")
    branch = git(root, "branch", "--show-current").stdout.strip()
    if not branch:
        raise OrchestratorError("source repository is detached", "SOURCE_DETACHED")
    if expected_branch and branch != expected_branch:
        raise OrchestratorError(f"wrong branch: expected {expected_branch}, got {branch}", "WRONG_BRANCH")
    if do_fetch:
        _fetch_expected_origin_branch(root, branch)
    head = git(root, "rev-parse", "HEAD").stdout.strip().lower()
    origin = git(root, "rev-parse", f"origin/{branch}").stdout.strip().lower()
    if head != origin:
        raise OrchestratorError(
            f"source HEAD is not synchronized with origin/{branch}: {head[:12]} != {origin[:12]}", "SOURCE_NOT_SYNCED")
    return RepoBaseline(root, branch, head, origin)


def create_worktree(baseline: RepoBaseline, run_id: str) -> tuple[Path, Path]:
    parent = Path(tempfile.mkdtemp(prefix=f"ai-orch-{slugify(baseline.root.name)}-{run_id}-"))
    # Same directory name as the source repo: tests that derive the repo name from their
    # checkout directory (e.g. next-day-setup's SYNC contract test) behave as in the source.
    worktree = parent / baseline.root.name
    git(baseline.root, "worktree", "add", "--detach", str(worktree), baseline.head_sha, timeout=300)
    return parent, worktree


def worktree_head_probe(worktree: Path):
    """Retry only an unexplained (empty stdout/stderr) nonzero exit of this read-only safety probe."""
    command = [*resolved_command("git"), "-C", str(worktree), "rev-parse", "HEAD"]
    for attempt in range(1, 4):
        result = run_streaming(command, timeout=120)
        if result.returncode == 0:
            return result
        detail = result.stderr.strip() or result.stdout.strip()
        if detail or attempt == 3:
            raise OrchestratorError(
                f"git rev-parse HEAD failed: {detail or '<empty stdout/stderr>'} "
                f"(return code {result.returncode}, attempt {attempt}/3)", "GIT_FAILED")
        time.sleep(0.2)
    raise AssertionError("unreachable")


def assert_agent_did_not_commit(worktree: Path, base_sha: str) -> None:
    head = worktree_head_probe(worktree).stdout.strip().lower()
    branch = git(worktree, "branch", "--show-current").stdout.strip()
    if head != base_sha.lower() or branch:
        raise SafetyViolation("agent changed Git history or attached the isolated worktree to a branch; refusing to continue")


def _is_bytecode_cache(rel: str) -> bool:
    """Interpreter caches are never work product: not diffed, not committed."""
    parts = rel.replace("\\", "/").split("/")
    return "__pycache__" in parts[:-1] or parts[-1].endswith((".pyc", ".pyo"))


BYTECODE_EXCLUDES = (":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc", ":(exclude,glob)**/*.pyo")


def diff_snapshot(worktree: Path) -> Snapshot:
    stat = git(worktree, "diff", "--stat", "HEAD").stdout
    diff = git(worktree, "diff", "--no-ext-diff", "--find-renames", "HEAD").stdout
    files = [line for line in git(worktree, "diff", "--name-status", "HEAD").stdout.splitlines() if line.strip()]
    untracked = [rel for rel in git(worktree, "ls-files", "--others", "--exclude-standard").stdout.strip().splitlines()
                 if not _is_bytecode_cache(rel)]
    pieces = [diff]
    for rel in untracked:
        files.append(f"?\t{rel}")
        path = worktree / rel
        if path.is_file():
            try:
                content = path.read_bytes()[:MAX_UNTRACKED_BYTES].decode("utf-8")
            except (OSError, UnicodeDecodeError):
                content = "<binary or unreadable>"
            pieces.append(f"\n# Untracked: {rel}\n{content}")
    return Snapshot(stat, "\n".join(pieces), tuple(files))


def windows_test_command_line(command: str) -> str:
    """The cmd.exe line meaning what the command means in a POSIX shell (Git Bash, where the
    agents run it). cmd.exe does not treat '...' as quoting, so `-p 'test_*.py'` reached the
    program *with* the quotes and matched nothing ("Ran 0 tests"). Only single-quoted
    segments outside double quotes are rewritten, to the equivalent "..." form; everything
    else is kept byte-for-byte. When the meaning cannot be kept exactly (unbalanced quote,
    `"` or `%` inside the segment, backslash-escaped quotes) the command is left unchanged."""
    if "'" not in command or "%" in command or '\\"' in command:
        return command
    out: list[str] = []
    in_double = False
    index = 0
    while index < len(command):
        char = command[index]
        if char == '"':
            in_double = not in_double
        elif char == "'" and not in_double:
            end = command.find("'", index + 1)
            if end < 0:
                return command
            content = command[index + 1:end]
            if '"' in content:
                return command
            trailing = len(content) - len(content.rstrip("\\"))
            out.append('"' + content + "\\" * trailing + '"')  # 2n backslashes before " stay n literal ones
            index = end + 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


PROJECTS_DIR = Path(__file__).resolve().parents[2] / "projects"
_PURPOSE_HEADINGS = ("正式な目的", "目的", "役割", "概要")


def read_project_purpose(repo_name: str, *, projects_dir: Path | None = None, limit: int = 1500) -> str:
    """The first purpose-like section of projects/<repo_name>.md (empty when there is none)."""
    path = (projects_dir or PROJECTS_DIR) / f"{repo_name}.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    for wanted in _PURPOSE_HEADINGS:
        for index, line in enumerate(lines):
            if line.startswith("#") and line.lstrip("# ").strip() == wanted:
                body = []
                for follow in lines[index + 1:]:
                    if follow.startswith("#"):
                        break
                    body.append(follow)
                text = "\n".join(body).strip()
                if text:
                    return text[:limit]
    return ""


class GitHost:
    """Engine host backed by the real isolated worktree."""

    def __init__(self, baseline: RepoBaseline, worktree: Path, run_id: str):
        self.baseline = baseline
        self.worktree = worktree
        self.run_id = run_id

    def snapshot(self) -> Snapshot:
        return diff_snapshot(self.worktree)

    def check_safety(self) -> None:
        assert_agent_did_not_commit(self.worktree, self.baseline.head_sha)

    def normalize_permissions(self) -> None:
        """Windows: files created by a sandboxed agent (Codex) can be owned by its sandbox account and
        unreadable by the user who runs the independent Tests. Grant the current user modify rights on
        exactly the files (and their parent directories) the agent touched. Best effort; no-op elsewhere."""
        if os.name != "nt":
            return
        user = os.environ.get("USERDOMAIN", "") + chr(92) + os.environ.get("USERNAME", "")
        if not os.environ.get("USERNAME"):
            return
        try:
            listing = git(self.worktree, "status", "--porcelain", "-z", "-uall").stdout
        except OrchestratorError:
            return
        targets: set[Path] = set()
        for entry in listing.split("\0"):
            if len(entry) < 4:
                continue
            path = (self.worktree / entry[3:]).resolve()
            targets.add(path)
            for parent in path.parents:
                if parent == self.worktree.resolve() or self.worktree.resolve() not in parent.parents:
                    break
                targets.add(parent)
        # icacls takes one target per call; only the files the agent touched, capped for pathological trees.
        for target in [t for t in sorted(targets) if t.exists()][:400]:
            try:
                run_streaming(["icacls", str(target), "/grant", f"{user}:M", "/C", "/Q"], timeout=60)
            except OrchestratorError:
                return

    def repo_instructions(self) -> str:
        parts = []
        for name in ("AGENTS.md", "OPERATING_CONTRACT.md"):
            path = self.worktree / name
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            parts.append(f"### {name}\n{text[:8000]}")
        return "\n\n".join(parts)

    def project_purpose(self) -> str:
        """What this application is for, taken from the knowledge base (`projects/<repo>.md`), so the AIs
        judge a change against the business purpose without the user retyping it in every Task."""
        return read_project_purpose(self.baseline.root.name)

    def tests_env(self) -> tuple[dict[str, str], Path | None]:
        """Environment of the independent Tests: the source repo's own `.venv` (git-ignored, so absent
        from the worktree) comes first on PATH when it exists, so `python` / `pytest` in the command
        resolve to the repo's interpreter and dependencies. Only the executables come from the source
        repo; the cwd stays the worktree, so the worktree's code is what gets tested."""
        env = agent_env()
        bin_dir = self.baseline.root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        if not (bin_dir / ("python.exe" if os.name == "nt" else "python")).is_file():
            return env, None
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(bin_dir.parent)
        env.pop("PYTHONHOME", None)
        env["AI_ORCHESTRATOR_TEST_VENV_BIN"] = str(bin_dir)
        return env, bin_dir

    def main_env(self) -> dict[str, str]:
        """Extra environment for the Main AI: the source repo's `.venv` first on PATH (empty when there is none)."""
        env, bin_dir = self.tests_env()
        if bin_dir is None:
            return {}
        return {"PATH": env["PATH"], "VIRTUAL_ENV": env["VIRTUAL_ENV"]}

    def run_tests(self, commands: list[str], timeout: int, hooks: ProcessHooks) -> tuple[bool, str]:
        outputs: list[str] = []
        env, venv_bin = self.tests_env()
        for command in commands:
            line = windows_test_command_line(command) if os.name == "nt" else command
            if hooks.on_line:
                hooks.on_line("stdout", f"START {command}" + (f"  [cmd.exe: {line}]" if line != command else "")
                              + (f"  [repo .venv: {venv_bin}]" if venv_bin else ""))
            # One command line string on Windows: with /s cmd strips only the outer quotes, so
            # quotes inside the test command survive (a list would re-escape them as \").
            if os.name == "nt":
                args = f'cmd.exe /d /s /c "{line}"'
            else:  # a login shell may reset PATH from the profile: put the repo venv back in front
                prefix = 'PATH="$AI_ORCHESTRATOR_TEST_VENV_BIN:$PATH"; export PATH; ' if venv_bin else ""
                args = ["/bin/sh", "-lc", prefix + command]
            header = (f"$ {command}" + (f"\n(executed by cmd.exe as: {line})" if line != command else "")
                      + (f"\n(repo-local venv first on PATH: {venv_bin})" if venv_bin else ""))
            try:
                result = run_streaming(args, cwd=self.worktree, timeout=timeout, env=env, hooks=hooks)
            except StopRequested:
                raise
            except OrchestratorError as exc:
                partial = getattr(exc, "partial_output", "")
                marker = f"\nTEST TIMEOUT/HANG after {timeout}s: {command}\n" if exc.code == "COMMAND_TIMEOUT" else f"\n{exc}\n"
                outputs.append(f"{header}\n{partial}{marker}".rstrip())
                return False, "\n\n".join(outputs)
            output = f"{result.stdout}{result.stderr}"
            if zero_tests_ran(output):
                # A green exit code with nothing tested is not a PASS (and a red one gets a diagnosis).
                output = output.rstrip() + "\n" + NO_TESTS_MARKER + f" command: {command}"
                outputs.append(f"{header}\n{output}".rstrip())
                return False, "\n\n".join(outputs)
            outputs.append(f"{header}\n{output}".rstrip())
            if result.returncode != 0:
                return False, "\n\n".join(outputs)
        return True, "\n\n".join(outputs)

    def create_candidate(self, task: str, run_id: str) -> dict:
        branch = f"ai-candidate/{run_id}-{slugify(task, 28)}"
        git(self.worktree, "switch", "-c", branch)
        git(self.worktree, "add", "-A", "--", ".", *BYTECODE_EXCLUDES)
        commit = run_streaming(
            [*resolved_command("git"), "-C", str(self.worktree), "commit", "-m", f"AI candidate: {task[:72]}"],
            timeout=300, env=agent_env())
        if commit.returncode != 0:
            raise OrchestratorError(f"candidate commit failed: {(commit.stderr or commit.stdout).strip()}", "CANDIDATE_FAILED")
        sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip().lower()
        status, detail = self.apply_readiness()
        return {"branch": branch, "sha": sha, "apply_status": status, "apply_detail": detail}

    def apply_readiness(self) -> tuple[str, str]:
        """Normal Development may continue in the source repo while a run works. If it moved,
        applying the result is held (never forced, and the run itself is not failed)."""
        try:
            branch = git(self.baseline.root, "branch", "--show-current").stdout.strip()
            head = git(self.baseline.root, "rev-parse", "HEAD").stdout.strip().lower()
            dirty = _tracked_dirty(self.baseline.root)
        except OrchestratorError as exc:
            return "held", f"source repositoryの状態を確認できません: {exc}"
        if branch != self.baseline.branch or head != self.baseline.head_sha:
            return "held_base_moved", (f"source repoがbase {self.baseline.head_sha[:12]}から変化しています"
                                       f"（現在 {branch}@{head[:12]}）。適用前に再確認してください")
        if dirty:
            return "held_source_dirty", "source repoに未コミットの変更があります。適用前に整理してください"
        return "ready", "baseへfast-forward可能"


# ------------------------------------------------------------------------- start / worker

@dataclass
class StartRequest:
    task: str
    tests: list[str]
    repo: str | None = None  # omitted: resolved from spec.target_repo / the task's "対象リポジトリ:" line
    main_agent: str = DEFAULT_MAIN_AGENT
    review_agent: str = DEFAULT_REVIEW_AGENT
    expected_branch: str | None = None
    limits: rs.Limits = field(default_factory=rs.Limits)
    allow_same_provider: bool = False
    allow_api_billing: bool = False
    fetch: bool = True
    allow_no_tests: bool = False
    prepare_source: bool = False  # switch a clean source repo to expected_branch and fast-forward it (DCC)
    spec: Spec | None = None  # already-loaded fixed-format TaskSpec (criteria, optional target_repo)


def _registry_definitions() -> list:
    """Repositories DCC's Orchestrator screen itself offers (scripts/repo_types.toml x
    scripts/dev_control_center_repos.toml), the same set `active_repo_definitions` builds for
    OrchestratorWindow. A seam for tests: patch this function, not the TOML files."""
    from scripts.dev_control_center.core import active_repo_definitions

    return active_repo_definitions(_REGISTRY_TYPES_PATH, _REGISTRY_BRANCHES_PATH)


def _normalize_repo_name(text: str) -> str:
    return text.strip().casefold()


def _target_repo_candidates(task: str, spec: Spec | None) -> list[tuple[str, str]]:
    """(label, name) of what the request says its target repository is, in priority order:
    the spec's target_repo first, then the task's own "対象リポジトリ:" line. Empty when neither
    is present."""
    candidates: list[tuple[str, str]] = []
    if spec is not None and spec.target_repo:
        candidates.append(("仕様ファイルのtarget_repo", spec.target_repo))
    task_target = extract_target_repo_name(task)
    if task_target:
        candidates.append(("依頼文の「対象リポジトリ:」行", task_target))
    return candidates


def _check_target_repo(task: str, spec: Spec | None, repo_root: Path) -> None:
    selected = repo_root.name
    for label, name in _target_repo_candidates(task, spec):
        if _normalize_repo_name(name) != _normalize_repo_name(selected):
            raise OrchestratorError(
                f"対象リポジトリが食い違っています。{label}は「{name}」を指していますが、選ばれたリポジトリは"
                f"「{selected}」です。", "TASK_REPO_MISMATCH")


def _resolve_repo_path(task: str, spec: Spec | None) -> Path:
    """Repo path from the registry when none was given explicitly (StartRequest.repo is empty)."""
    candidates = _target_repo_candidates(task, spec)
    names = sorted({d.name for d in _registry_definitions()})
    if not candidates:
        raise OrchestratorError(
            "リポジトリが指定されておらず、仕様ファイルにも依頼文にも対象リポジトリが書かれていません。"
            f"--repo を指定するか、依頼文の先頭10行以内に「対象リポジトリ: <名前>」を書いてください。選べる候補: "
            + (", ".join(names) or "(なし)"), "TASK_REPO_UNRESOLVED")
    label, name = candidates[0]
    matches = [n for n in names if _normalize_repo_name(n) == _normalize_repo_name(name)]
    if not matches:
        raise OrchestratorError(
            f"{label}が指す「{name}」はレジストリに見つかりません。選べる候補: " + (", ".join(names) or "(なし)"),
            "TASK_REPO_UNRESOLVED")
    if len(matches) > 1:
        raise OrchestratorError(
            f"{label}が指す「{name}」に該当するリポジトリが複数あります: {', '.join(matches)}。選べる候補: "
            + ", ".join(names), "TASK_REPO_UNRESOLVED")
    return DM_ROOT.parent / matches[0]


# DCC Task 14.3: why resolve_repo_dir_for_app came back None, classified from DCC's own
# registry only -- never a path or exception string (reports_triage.py turns these into the
# fixed Japanese note the dialog shows; see reports_triage.code_unavailable_note).
REPO_DIR_APP_NOT_REGISTERED = "app_not_registered"
REPO_DIR_FOLDER_MISSING = "repo_folder_missing"


def _resolve_repo_dir_for_app_detail(app_key: str) -> tuple[Path | None, str]:
    """Shared lookup behind resolve_repo_dir_for_app and resolve_repo_dir_unavailable_reason:
    app_key (an inbox report's app_key, e.g. "next-day-setup") against DCC's own registry only
    -- never report text or AI output, which this function never even sees.

    Matches the registry the same way _resolve_repo_path already does (_normalize_repo_name:
    casefold, surrounding whitespace stripped), then builds the folder path from the registry's
    own canonical name rather than the raw app_key -- so a config-side spelling difference in
    case or incidental whitespace between reports.<app_key> and [types]/[branches] still
    resolves, instead of silently falling through to "not registered"."""
    names = sorted({d.name for d in _registry_definitions()})
    matches = [n for n in names if _normalize_repo_name(n) == _normalize_repo_name(app_key)]
    if not matches:
        return None, REPO_DIR_APP_NOT_REGISTERED
    path = DM_ROOT.parent / matches[0]
    if path.is_dir():
        return path, ""
    return None, REPO_DIR_FOLDER_MISSING


def resolve_repo_dir_for_app(app_key: str) -> Path | None:
    """The repository folder DCC's own registry maps an inbox report's app_key (e.g.
    "next-day-setup") to, or None when app_key is not a registered repo name or that repo's
    folder does not exist on disk. Used by reports_triage.py (DCC Task 14) to pick a read-only
    investigation working folder from DCC's own configuration only -- never from report text or
    AI output, which this function never even sees."""
    path, _reason = _resolve_repo_dir_for_app_detail(app_key)
    return path


def resolve_repo_dir_unavailable_reason(app_key: str) -> str:
    """DCC Task 14.3: REPO_DIR_APP_NOT_REGISTERED / REPO_DIR_FOLDER_MISSING classifying why
    resolve_repo_dir_for_app(app_key) is None, or "" when it would actually resolve. Used by
    reports_triage.py to choose the fixed Japanese note shown on screen -- this function itself
    never produces or sees a path string or exception text, only the kind."""
    _path, reason = _resolve_repo_dir_for_app_detail(app_key)
    return reason


def resolve_target_repo(task: str, spec: Spec | None, repo: str | None = None) -> Path:
    """What prepare_run will pick as the target repository, and whether it agrees with the
    task's own "対象リポジトリ:" line / the spec's target_repo -- without creating a run or
    taking the repo lock, so a start-confirmation screen can show it first. Raises the same
    TASK_REPO_MISMATCH / TASK_REPO_UNRESOLVED errors prepare_run raises for the same inputs.
    Deliberately skips repo_toplevel's git call (prepare_run still does that once a run is
    actually prepared): a path given by the caller is already the repo root here."""
    repo_arg = Path(repo) if repo else _resolve_repo_path(task, spec)
    _check_target_repo(task, spec, repo_arg)
    return repo_arg


def prepare_run(request: StartRequest) -> tuple[Path, dict]:
    """Validate everything that can be validated without AI, take the repo lock, and write
    the initial run record. Raises before anything is created if the request is unsafe."""
    task = request.task.strip()
    if not task:
        raise OrchestratorError("task is empty", "TASK_EMPTY")
    if not request.tests and not request.allow_no_tests:
        raise OrchestratorError("at least one test command is required", "TESTS_MISSING")
    validate_roles(request.main_agent, request.review_agent, allow_same=request.allow_same_provider)
    for name in {request.main_agent, request.review_agent}:
        make_provider(name).preflight()
    resolved_command("git")
    active = active_api_billing_env()
    if active and not request.allow_api_billing:
        raise OrchestratorError("API/third-party billing environment detected: " + ", ".join(active)
                                + ". Refusing to start.", "API_BILLING_ENV")
    # Line numbering for the "対象リポジトリ:" check must match the original text (including any
    # leading blank lines), not the stripped-for-storage `task`: stripping would shift what counts
    # as "the first 10 lines".
    repo_arg = Path(request.repo) if request.repo else _resolve_repo_path(request.task, request.spec)
    root = repo_toplevel(repo_arg)
    _check_target_repo(request.task, request.spec, root)
    run_id = now_id()
    # Lock before touching the source repo: its branch is never moved under another live run.
    lock = rs.acquire_repo_lock(str(root), run_id)
    try:
        preparation = prepare_source_branch(root, request.expected_branch) if request.prepare_source else []
        baseline = repo_baseline(root, request.expected_branch, request.fetch and not request.prepare_source)
        run_dir = rs.runs_root() / run_id
        run_dir.mkdir(parents=True)
        record = rs.new_record(
            run_id=run_id, repo=str(baseline.root), task=task, main_agent=request.main_agent,
            review_agent=request.review_agent, tests=request.tests, limits=request.limits,
            branch=baseline.branch, base_sha=baseline.head_sha)
        if request.spec is not None:
            record["criteria"] = list(request.spec.criteria)
            record["criteria_source"] = "spec"
        record["billing_env_override"] = list(active)
        record["same_provider_override"] = request.main_agent == request.review_agent
        record["source_preparation"] = preparation if request.prepare_source else None  # None: not requested
        (run_dir / "task.md").write_text(task + "\n", encoding="utf-8")
        if request.spec is not None:
            write_json_atomic(run_dir / "spec.json", request.spec.to_record())
        write_json_atomic(run_dir / "run.json", record)
    except BaseException:
        lock.unlink(missing_ok=True)
        raise
    return run_dir, record


def _worker_python() -> str:
    exe = Path(sys.executable)
    return str(exe.with_name("python.exe")) if exe.name.lower() == "pythonw.exe" else str(exe)


_SPAWNED_WORKERS: list[subprocess.Popen] = []  # keeps Popen objects alive; the workers themselves are independent


def spawn_worker(run_dir: Path) -> subprocess.Popen:
    """Start the run's own worker, fully detached from the caller (DCC / CLI).

    The worker has no console, no shared stdio pipe and, where the OS allows it, is not
    part of the caller's job object, so closing DCC cannot end the run."""
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    command = [_worker_python(), "-u", "-B", "-m", "tools.ai_orchestrator.orchestrator", "worker", "--run-dir", str(run_dir)]
    out = open(run_dir / "worker.out", "ab")
    try:
        if os.name == "nt":
            base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                return subprocess.Popen(command, cwd=DM_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                        stderr=subprocess.STDOUT, creationflags=base | 0x01000000)  # BREAKAWAY_FROM_JOB
            except OSError:
                return subprocess.Popen(command, cwd=DM_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                        stderr=subprocess.STDOUT, creationflags=base)
        return subprocess.Popen(command, cwd=DM_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        out.close()


def start_run(request: StartRequest, *, wait: float = 30.0) -> Path:
    """Create a run and hand it to a detached worker. Returns once the worker has registered."""
    import time

    run_dir, record = prepare_run(request)
    try:
        _SPAWNED_WORKERS[:] = [w for w in _SPAWNED_WORKERS if w.poll() is None]
        _SPAWNED_WORKERS.append(spawn_worker(run_dir))
    except OSError as exc:
        rs.reconcile_lost(run_dir)
        raise OrchestratorError(f"could not start the run worker: {exc}", "WORKER_START_FAILED") from exc
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        current = rs.read_record(run_dir) or {}
        if (current.get("worker") or {}).get("pid") or current.get("stage") in rs.TERMINAL_STAGES:
            return run_dir
        time.sleep(0.2)
    raise OrchestratorError(f"run worker did not register within {wait:.0f}s: {run_dir}", "WORKER_START_TIMEOUT")


def _remove_worktree(baseline: RepoBaseline, worktree: Path) -> None:
    try:
        git(baseline.root, "worktree", "remove", "--force", str(worktree), timeout=300)
        shutil.rmtree(worktree.parent, ignore_errors=True)
    except OrchestratorError:
        pass


def worker_main(run_dir: Path, *, engine_factory=None, refresh_usage: bool = True) -> int:
    """Body of the detached worker. Owns the run until it reaches a terminal stage."""
    record = rs.read_record(run_dir)
    if record is None:
        print(f"run.json not found: {run_dir}", file=sys.stderr)
        return 2
    rec = rs.RunRecorder(run_dir, record)
    pid = os.getpid()
    rec.update(worker={"pid": pid, "token": process_start_token(pid), "started_at": rs.now_iso(),
                       "python": sys.executable}, started_at=rs.now_iso())
    rec.start_heartbeat()
    baseline = RepoBaseline(Path(record["repo"]), record["source_branch"], record["base_sha"], record["base_sha"])
    parent = worktree = None
    try:
        rec.transition(rs.PREFLIGHT, "CLI・worktreeを準備中")
        for action in record.get("source_preparation") or []:
            rec.log(f"[source] {action}")
        main = make_provider(record["main_agent"])
        reviewer = make_provider(record["review_agent"])
        validate_roles(record["main_agent"], record["review_agent"], allow_same=bool(record.get("same_provider_override")))
        main.preflight()
        reviewer.preflight()
        usage = {name: make_usage_provider(name) for name in {record["main_agent"], record["review_agent"]}
                 if name in USAGE_PROVIDER_CLASSES}
        try:  # the free Codex account query; Claude values come from its own calls
            if refresh_usage and "codex" in usage:
                usage["codex"].refresh()
        except Exception:  # noqa: BLE001 - auxiliary
            pass
        parent, worktree = create_worktree(baseline, record["run_id"])
        rec.update(worktree=str(worktree))
        host = GitHost(baseline, worktree, record["run_id"])
        engine = (engine_factory or Engine)(rec, host, main, reviewer, usage)
        engine.run()
    except StopRequested:
        rec.record["stopped_by_user"] = True
        rec.finish(rs.STOPPED, "USER_SAFETY_STOP", "ユーザーによるAI安全停止", stopped_by_user=True)
    except NeedsHuman as exc:
        rec.finish(rs.NEEDS_HUMAN, exc.code, str(exc))
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "ORCHESTRATOR_ERROR")
        rec.finish(rs.FAILED, code, f"{type(exc).__name__}: {exc}")
    finally:
        final = (rec.record.get("final_result") or {}).get("stage")
        if final == rs.COMPLETED and worktree is not None:
            _remove_worktree(baseline, worktree)  # the candidate branch survives in the source repo
        rec.stop_heartbeat()
        rs.release_repo_lock(record["repo"], record["run_id"])
    final = (rec.record.get("final_result") or {}).get("stage")
    return 0 if final in (rs.COMPLETED, rs.NEEDS_HUMAN, rs.STOPPED) else 1


# ------------------------------------------------------------------------- CLI

def doctor() -> int:
    rows, failed = [], False
    for name in ("git", *PROVIDER_NAMES):
        try:
            result = run_streaming([*resolved_command(name), "--version"], timeout=60)
            detail = (result.stdout or result.stderr).strip().splitlines()
            rows.append((name, detail[0] if detail else f"rc={result.returncode}"))
            failed = failed or result.returncode != 0
        except OrchestratorError as exc:
            rows.append((name, str(exc)))
            failed = True
    active = active_api_billing_env()
    rows.append(("billing", "BLOCKED by default: " + ", ".join(active) if active
                 else "subscription guard OK (no API billing env detected)"))
    failed = failed or bool(active)
    for name, detail in rows:
        print(f"{name:8} {detail}")
    return 1 if failed else 0


def _limit_args(parser: argparse.ArgumentParser) -> None:
    defaults = rs.Limits()
    for f in fields(rs.Limits):
        parser.add_argument("--" + f.name.replace("_", "-"), dest="limit_" + f.name, type=int,
                            default=getattr(defaults, f.name), help=f"default {getattr(defaults, f.name)}")


def _request_from_args(args: argparse.Namespace) -> StartRequest:
    # Kept unstripped (prepare_run strips only for storage): the "対象リポジトリ:" line check
    # counts lines against the original text, and stripping leading blank lines here would
    # shift that count.
    task = Path(args.task_file).read_text(encoding="utf-8") if args.task_file else args.task
    limits = rs.Limits(**{f.name: getattr(args, "limit_" + f.name) for f in fields(rs.Limits)})
    spec = load_spec_file(Path(args.spec_file)) if args.spec_file else None
    return StartRequest(
        task=task or "", tests=list(args.test), repo=args.repo, main_agent=args.main, review_agent=args.reviewer,
        expected_branch=args.expected_branch, limits=limits, allow_same_provider=args.allow_same_provider,
        allow_api_billing=args.allow_api_billing, fetch=not args.no_fetch, allow_no_tests=args.allow_no_tests,
        prepare_source=args.prepare_source, spec=spec)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Orchestrator: automatic Main / Reviewer development")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check git / provider CLIs and the billing guard")
    for name, help_text in (("start", "start a detached run and return its run dir"),
                            ("run", "start a run and stay attached until it finishes (worker runs in-process)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--repo", help="omit to resolve from --spec-file target_repo / the task's "
                                      "対象リポジトリ: line against the registry")
        p.add_argument("--spec-file", help="fixed-format JSON TaskSpec (schema_version, criteria, target_repo)")
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--task")
        group.add_argument("--task-file")
        p.add_argument("--expected-branch")
        p.add_argument("--test", action="append", default=[], help="test command; repeatable")
        p.add_argument("--allow-no-tests", action="store_true")
        p.add_argument("--main", choices=PROVIDER_NAMES, default=DEFAULT_MAIN_AGENT, help="Main AI")
        p.add_argument("--reviewer", choices=PROVIDER_NAMES, default=DEFAULT_REVIEW_AGENT, help="Reviewer AI")
        p.add_argument("--allow-same-provider", action="store_true", help="permit Main == Reviewer (not independent)")
        p.add_argument("--allow-api-billing", action="store_true")
        p.add_argument("--no-fetch", action="store_true")
        p.add_argument("--prepare-source", action="store_true",
                       help="if the source repo is clean, switch it to --expected-branch and fast-forward to origin")
        _limit_args(p)
    worker = sub.add_parser("worker", help="(internal) run one prepared run to completion")
    worker.add_argument("--run-dir", required=True)
    stop = sub.add_parser("stop", help="AI safe stop of one run")
    stop.add_argument("--run-dir", required=True)
    status = sub.add_parser("status", help="print run status as JSON")
    status.add_argument("--run-dir")
    status.add_argument("--repo")
    usage = sub.add_parser("usage", help="print provider usage (account and context, kept separate)")
    usage.add_argument("--refresh", action="store_true")
    return parser


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "start":
            run_dir = start_run(_request_from_args(args))
            print(json.dumps({"run_id": run_dir.name, "run_dir": str(run_dir)}, ensure_ascii=False))
            return 0
        if args.command == "run":
            run_dir, _ = prepare_run(_request_from_args(args))
            print(f"run_dir={run_dir}", flush=True)
            return worker_main(run_dir)
        if args.command == "worker":
            return worker_main(Path(args.run_dir))
        if args.command == "stop":
            record = rs.force_stop(Path(args.run_dir))
            print(json.dumps(record.get("final_result"), ensure_ascii=False))
            return 0
        if args.command == "status":
            if args.run_dir:
                info = rs.inspect_run(Path(args.run_dir))
                print(json.dumps({"liveness": info["liveness"], "reason": info["reason"], "record": info["record"]},
                                 ensure_ascii=False, indent=2))
            else:
                for item in rs.list_runs(repo=args.repo):
                    r = item["record"]
                    print(f"{r['run_id']}  {item['liveness']:<12} {r['stage']:<12} {r['repo']}  main={r['main_agent']} review={r['review_agent']}")
            return 0
        if args.command == "usage":
            for name in USAGE_PROVIDER_CLASSES:
                provider = make_usage_provider(name)
                data = provider.refresh(force=True) if args.refresh else provider.load()
                print(f"[{provider.display}]")
                for label, text in describe(data):
                    print(f"  {label}: {text}")
            return 0
    except (OSError, OrchestratorError) as exc:
        print(f"AI ORCHESTRATOR STOPPED: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
