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
from .providers import (
    DEFAULT_MAIN_AGENT, DEFAULT_REVIEW_AGENT, PROVIDER_NAMES, active_api_billing_env, agent_env,
    make_provider, validate_roles,
)
from .usage import USAGE_PROVIDER_CLASSES, describe, make_usage_provider

DM_ROOT = Path(__file__).resolve().parents[2]
MAX_UNTRACKED_BYTES = 200_000


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
    worktree = parent / "worktree"
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

    def run_tests(self, commands: list[str], timeout: int, hooks: ProcessHooks) -> tuple[bool, str]:
        outputs: list[str] = []
        for command in commands:
            if hooks.on_line:
                hooks.on_line("stdout", f"START {command}")
            # One command line string on Windows: with /s cmd strips only the outer quotes, so
            # quotes inside the test command survive (a list would re-escape them as \").
            args = f'cmd.exe /d /s /c "{command}"' if os.name == "nt" else ["/bin/sh", "-lc", command]
            try:
                result = run_streaming(args, cwd=self.worktree, timeout=timeout, env=agent_env(), hooks=hooks)
            except StopRequested:
                raise
            except OrchestratorError as exc:
                partial = getattr(exc, "partial_output", "")
                marker = f"\nTEST TIMEOUT/HANG after {timeout}s: {command}\n" if exc.code == "COMMAND_TIMEOUT" else f"\n{exc}\n"
                outputs.append(f"$ {command}\n{partial}{marker}".rstrip())
                return False, "\n\n".join(outputs)
            outputs.append(f"$ {command}\n{result.stdout}{result.stderr}".rstrip())
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
    repo: str
    task: str
    tests: list[str]
    main_agent: str = DEFAULT_MAIN_AGENT
    review_agent: str = DEFAULT_REVIEW_AGENT
    expected_branch: str | None = None
    limits: rs.Limits = field(default_factory=rs.Limits)
    allow_same_provider: bool = False
    allow_api_billing: bool = False
    fetch: bool = True
    allow_no_tests: bool = False


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
    baseline = repo_baseline(Path(request.repo), request.expected_branch, request.fetch)
    run_id = now_id()
    lock = rs.acquire_repo_lock(str(baseline.root), run_id)
    try:
        run_dir = rs.runs_root() / run_id
        run_dir.mkdir(parents=True)
        record = rs.new_record(
            run_id=run_id, repo=str(baseline.root), task=task, main_agent=request.main_agent,
            review_agent=request.review_agent, tests=request.tests, limits=request.limits,
            branch=baseline.branch, base_sha=baseline.head_sha)
        record["billing_env_override"] = list(active)
        record["same_provider_override"] = request.main_agent == request.review_agent
        (run_dir / "task.md").write_text(task + "\n", encoding="utf-8")
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
    task = Path(args.task_file).read_text(encoding="utf-8").strip() if args.task_file else args.task
    limits = rs.Limits(**{f.name: getattr(args, "limit_" + f.name) for f in fields(rs.Limits)})
    return StartRequest(
        repo=args.repo, task=task or "", tests=list(args.test), main_agent=args.main, review_agent=args.reviewer,
        expected_branch=args.expected_branch, limits=limits, allow_same_provider=args.allow_same_provider,
        allow_api_billing=args.allow_api_billing, fetch=not args.no_fetch, allow_no_tests=args.allow_no_tests)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Orchestrator: automatic Main / Reviewer development")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check git / provider CLIs and the billing guard")
    for name, help_text in (("start", "start a detached run and return its run dir"),
                            ("run", "start a run and stay attached until it finishes (worker runs in-process)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--repo", required=True)
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
