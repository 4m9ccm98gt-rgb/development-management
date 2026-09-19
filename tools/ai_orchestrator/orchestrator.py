"""Claude implementation + Codex/Astra review orchestrator.

v0.2 intentionally stops at a local candidate commit. It never pushes, builds,
deploys, or updates production resources.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
DEFAULT_TIMEOUT = 1800
MAX_DIFF_CHARS = 200_000
DEFAULT_REVIEW_MODEL = "gpt-6-astra"
DEFAULT_MAX_ROUNDS = 2
ORCHESTRATOR_VERSION = "0.3"
DUAL_REVIEW_REPOS = frozenset({"development-management"})
API_BILLING_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


class OrchestratorError(RuntimeError):
    """Fail-closed orchestration error."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Review:
    verdict: str
    summary: str
    findings: tuple[dict[str, object], ...]

    @property
    def approved(self) -> bool:
        return self.verdict == "approve"


@dataclass(frozen=True)
class RepoBaseline:
    root: Path
    branch: str
    head_sha: str
    origin_sha: str


@dataclass
class UsageCounters:
    claude_calls: int = 0
    codex_calls: int = 0


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _state_root() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ShizenDev" / "AIOrchestrator"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "shizen-ai-orchestrator"
    return Path.home() / ".local" / "state" / "shizen-ai-orchestrator"


def _slugify(value: str, limit: int = 42) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return (text or "task")[:limit].rstrip("-._")


def _resolved_command(name: str) -> list[str]:
    resolved = shutil.which(name)
    if not resolved:
        raise OrchestratorError(f"required command not found: {name}")
    path = Path(resolved)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", str(path)]
    return [str(path)]


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise OrchestratorError(f"command timed out after {timeout}s: {args[0]}") from exc
    except OSError as exc:
        raise OrchestratorError(f"failed to start {args[0]}: {exc}") from exc
    return CommandResult(tuple(args), proc.returncode, proc.stdout or "", proc.stderr or "")


def _git(repo: Path, *args: str, timeout: int = 120) -> CommandResult:
    result = _run([*_resolved_command("git"), "-C", str(repo), *args], timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"git {' '.join(args)} failed: {detail}")
    return result


def _read_prompt(name: str, replacements: dict[str, str]) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _agent_env() -> dict[str, str]:
    """Child-only Git safety overlay.

    Even if an agent ignores the prompt and invokes `git push origin ...`,
    Git receives an invalid push URL. This does not modify repository config.
    """
    env = os.environ.copy()
    env["AI_ORCHESTRATOR"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "remote.origin.pushurl"
    env["GIT_CONFIG_VALUE_0"] = "disabled://ai-orchestrator"
    return env


def _active_api_billing_env() -> tuple[str, ...]:
    return tuple(name for name in API_BILLING_ENV_VARS if os.environ.get(name))


def _enforce_billing_guard(allow_api_billing: bool) -> tuple[str, ...]:
    active = _active_api_billing_env()
    if active and not allow_api_billing:
        raise OrchestratorError(
            "API/third-party billing environment detected: "
            + ", ".join(active)
            + ". Refusing to start. Remove those variables or explicitly pass "
            "--allow-api-billing."
        )
    return active


def _tracked_dirty(repo: Path) -> bool:
    return bool(_git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip())


def _repo_baseline(repo_arg: Path, expected_branch: str | None, do_fetch: bool) -> RepoBaseline:
    repo_arg = repo_arg.expanduser().resolve()
    root_text = _git(repo_arg, "rev-parse", "--show-toplevel").stdout.strip()
    root = Path(root_text).resolve()

    if _tracked_dirty(root):
        raise OrchestratorError("tracked working tree is dirty; refusing to start")

    branch = _git(root, "branch", "--show-current").stdout.strip()
    if not branch:
        raise OrchestratorError("source repository is detached")
    if expected_branch and branch != expected_branch:
        raise OrchestratorError(f"wrong branch: expected {expected_branch}, got {branch}")

    if do_fetch:
        fetch = _run(
            [*_resolved_command("git"), "-C", str(root), "fetch", "--prune", "origin"],
            timeout=300,
        )
        if fetch.returncode != 0:
            detail = (fetch.stderr or fetch.stdout).strip()
            raise OrchestratorError(f"git fetch failed: {detail}")

    head_sha = _git(root, "rev-parse", "HEAD").stdout.strip().lower()
    origin_sha = _git(root, "rev-parse", f"origin/{branch}").stdout.strip().lower()
    if head_sha != origin_sha:
        raise OrchestratorError(
            f"source HEAD is not synchronized with origin/{branch}: "
            f"{head_sha[:12]} != {origin_sha[:12]}"
        )
    return RepoBaseline(root, branch, head_sha, origin_sha)


def _create_worktree(baseline: RepoBaseline, run_id: str) -> tuple[Path, Path]:
    parent = Path(tempfile.mkdtemp(prefix=f"ai-orch-{_slugify(baseline.root.name)}-{run_id}-"))
    worktree = parent / "worktree"
    _git(baseline.root, "worktree", "add", "--detach", str(worktree), baseline.head_sha, timeout=300)
    return parent, worktree


def _assert_source_unchanged(baseline: RepoBaseline) -> None:
    branch = _git(baseline.root, "branch", "--show-current").stdout.strip()
    head = _git(baseline.root, "rev-parse", "HEAD").stdout.strip().lower()
    if branch != baseline.branch or head != baseline.head_sha or _tracked_dirty(baseline.root):
        raise OrchestratorError(
            "source repository changed during orchestration; stopped before candidate creation"
        )


def _assert_origin_unchanged(baseline: RepoBaseline, do_fetch: bool) -> None:
    if do_fetch:
        fetch = _run(
            [*_resolved_command("git"), "-C", str(baseline.root), "fetch", "--prune", "origin"],
            timeout=300,
        )
        if fetch.returncode != 0:
            detail = (fetch.stderr or fetch.stdout).strip()
            raise OrchestratorError(f"final git fetch failed: {detail}")
    origin_sha = _git(
        baseline.root, "rev-parse", f"origin/{baseline.branch}"
    ).stdout.strip().lower()
    if origin_sha != baseline.origin_sha:
        raise OrchestratorError(
            f"origin/{baseline.branch} moved during orchestration: "
            f"{baseline.origin_sha[:12]} -> {origin_sha[:12]}"
        )


def _assert_agent_did_not_commit(worktree: Path, base_sha: str) -> None:
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip().lower()
    branch = _git(worktree, "branch", "--show-current").stdout.strip()
    if head != base_sha.lower() or branch:
        raise OrchestratorError(
            "agent changed Git history or attached the isolated worktree to a branch; refusing to continue"
        )


def _claude_implementation_command() -> list[str]:
    return [
        *_resolved_command("claude"),
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--max-turns",
        "30",
    ]


def _claude_review_command() -> list[str]:
    return [
        *_resolved_command("claude"),
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--max-turns",
        "15",
    ]


def _codex_review_command(model: str) -> list[str]:
    return [
        *_resolved_command("codex"),
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "-m",
        model,
        "-",
    ]


def _run_claude_implementation(
    worktree: Path,
    prompt: str,
    timeout: int,
) -> CommandResult:
    result = _run(
        _claude_implementation_command(),
        cwd=worktree,
        input_text=prompt,
        timeout=timeout,
        env=_agent_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"Claude implementation failed: {detail}")
    return result


def _run_claude_review(
    worktree: Path,
    prompt: str,
    timeout: int,
) -> CommandResult:
    result = _run(
        _claude_review_command(),
        cwd=worktree,
        input_text=prompt,
        timeout=timeout,
        env=_agent_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"Claude review failed: {detail}")
    return result


def _run_codex_review(
    worktree: Path,
    prompt: str,
    timeout: int,
    model: str,
) -> CommandResult:
    result = _run(
        _codex_review_command(model),
        cwd=worktree,
        input_text=prompt,
        timeout=timeout,
        env=_agent_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"Codex review failed: {detail}")
    return result


def _claude_result_text(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OrchestratorError("Claude did not return valid CLI JSON") from exc
    if not isinstance(payload, dict) or payload.get("is_error"):
        raise OrchestratorError("Claude returned an error result")
    text = payload.get("result")
    if not isinstance(text, str) or not text.strip():
        raise OrchestratorError("Claude JSON did not contain a result")
    return text.strip()


def _extract_json_object(text: str) -> dict[str, object]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise OrchestratorError("review result did not contain a JSON object")
        try:
            value = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OrchestratorError("review result JSON could not be parsed") from exc
    if not isinstance(value, dict):
        raise OrchestratorError("review result must be a JSON object")
    return value


def _review_from_value(value: dict[str, object], reviewer: str) -> Review:
    verdict = str(value.get("verdict", "")).strip().lower()
    if verdict not in {"approve", "changes_requested"}:
        raise OrchestratorError(
            f"invalid {reviewer} verdict: {verdict or '<missing>'}"
        )
    summary = str(value.get("summary", "")).strip()
    raw_findings = value.get("findings", [])
    if not isinstance(raw_findings, list):
        raise OrchestratorError("review findings must be an array")
    findings = tuple(item for item in raw_findings if isinstance(item, dict))
    if verdict == "approve" and findings:
        raise OrchestratorError(
            f"{reviewer} returned approve with findings; refusing ambiguous review"
        )
    return Review(verdict, summary, findings)


def _parse_claude_review(stdout: str) -> Review:
    return _review_from_value(
        _extract_json_object(_claude_result_text(stdout)),
        "Claude",
    )


def _parse_codex_review(stdout: str) -> Review:
    return _review_from_value(_extract_json_object(stdout), "Codex")


def _requires_dual_review(repo_root: Path) -> bool:
    return repo_root.name.lower() in DUAL_REVIEW_REPOS


def _reviews_approved(claude_review: Review | None, codex_review: Review) -> bool:
    return codex_review.approved and (
        claude_review is None or claude_review.approved
    )


def _combined_review_feedback(
    claude_review: Review | None,
    codex_review: Review,
) -> str:
    payload: dict[str, object] = {
        "codex_astra_review": asdict(codex_review),
    }
    if claude_review is not None:
        payload["claude_review"] = asdict(claude_review)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _run_reviewers(
    worktree: Path,
    *,
    prompt: str,
    run_dir: Path,
    round_no: int,
    max_rounds: int,
    counters: UsageCounters,
    timeout: int,
    review_model: str,
    dual_review: bool,
    reviewed_fingerprint: str,
    base_sha: str,
) -> tuple[Review | None, Review]:
    claude_review: Review | None = None

    if dual_review:
        _write_log(
            run_dir,
            f"round-{round_no:02d}-claude-review-prompt.md",
            prompt,
        )
        counters.claude_calls += 1
        _progress(
            run_dir,
            stage="claude_review",
            message="Claude reviewing (read-only plan mode)...",
            round_no=round_no,
            max_rounds=max_rounds,
            counters=counters,
        )
        claude = _run_claude_review(worktree, prompt, timeout)
        _write_log(
            run_dir,
            f"round-{round_no:02d}-claude-review-raw.json",
            claude.stdout,
        )
        claude_review = _parse_claude_review(claude.stdout)
        _write_log(
            run_dir,
            f"round-{round_no:02d}-claude-review.json",
            json.dumps(asdict(claude_review), ensure_ascii=False, indent=2),
        )
        _assert_agent_did_not_commit(worktree, base_sha)
        _, after_claude_diff = _diff_for_review(worktree)
        if _review_fingerprint(after_claude_diff) != reviewed_fingerprint:
            raise OrchestratorError(
                "worktree changed during Claude read-only review; refusing unreviewed candidate"
            )

    _write_log(
        run_dir,
        f"round-{round_no:02d}-codex-review-prompt.md",
        prompt,
    )
    counters.codex_calls += 1
    _progress(
        run_dir,
        stage="codex_review",
        message=f"Codex/Astra reviewing with {review_model} (read-only)...",
        round_no=round_no,
        max_rounds=max_rounds,
        counters=counters,
    )
    codex = _run_codex_review(worktree, prompt, timeout, review_model)
    _write_log(
        run_dir,
        f"round-{round_no:02d}-codex-review.txt",
        codex.stdout + "\n" + codex.stderr,
    )
    codex_review = _parse_codex_review(codex.stdout)
    _assert_agent_did_not_commit(worktree, base_sha)
    _write_log(
        run_dir,
        f"round-{round_no:02d}-codex-review.json",
        json.dumps(asdict(codex_review), ensure_ascii=False, indent=2),
    )
    _, after_codex_diff = _diff_for_review(worktree)
    if _review_fingerprint(after_codex_diff) != reviewed_fingerprint:
        raise OrchestratorError(
            "worktree changed during Codex read-only review; refusing unreviewed candidate"
        )

    return claude_review, codex_review


def _run_tests(worktree: Path, commands: Iterable[str], timeout: int) -> tuple[bool, str]:
    outputs: list[str] = []
    ok = True
    for command in commands:
        if os.name == "nt":
            args = ["cmd.exe", "/d", "/s", "/c", command]
        else:
            args = ["/bin/sh", "-lc", command]
        result = _run(args, cwd=worktree, timeout=timeout, env=_agent_env())
        outputs.append(
            f"$ {command}\n[rc={result.returncode}]\n{result.stdout}\n{result.stderr}".rstrip()
        )
        if result.returncode != 0:
            ok = False
            break
    return ok, "\n\n".join(outputs)


def _diff_for_review(worktree: Path) -> tuple[str, str]:
    stat = _git(worktree, "diff", "--stat", "HEAD").stdout
    diff = _git(worktree, "diff", "--no-ext-diff", "--find-renames", "HEAD").stdout
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard").stdout.strip().splitlines()
    if untracked:
        pieces = [diff, "\n# Untracked files\n" + "\n".join(untracked)]
        for rel in untracked:
            path = worktree / rel
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    content = "<binary or unreadable>"
                pieces.append(f"\n# Untracked: {rel}\n{content}")
        diff = "\n".join(pieces)
    if len(diff) > MAX_DIFF_CHARS:
        raise OrchestratorError(
            f"review diff is too large ({len(diff)} chars); split the task before continuing"
        )
    return stat, diff


def _review_fingerprint(diff_text: str) -> str:
    return hashlib.sha256(diff_text.encode("utf-8")).hexdigest()


def _write_log(run_dir: Path, name: str, text: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / name).write_text(text, encoding="utf-8")


def _write_external_result(path_arg: str | None, payload: dict[str, object]) -> None:
    """Write a machine-readable result for callers such as DCC."""
    if not path_arg:
        return
    path = Path(path_arg).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def _write_status(
    run_dir: Path,
    *,
    stage: str,
    round_no: int,
    max_rounds: int,
    counters: UsageCounters,
    detail: str = "",
) -> None:
    payload = {
        "stage": stage,
        "round": round_no,
        "max_rounds": max_rounds,
        "claude_calls": counters.claude_calls,
        "codex_calls": counters.codex_calls,
        "detail": detail,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_log(run_dir, "status.json", json.dumps(payload, ensure_ascii=False, indent=2))


def _progress(
    run_dir: Path | None,
    *,
    stage: str,
    message: str,
    round_no: int,
    max_rounds: int,
    counters: UsageCounters,
) -> None:
    prefix = f"[Round {round_no}/{max_rounds}]" if round_no else "[Preflight]"
    print(
        f"{prefix} {message} "
        f"(Claude calls: {counters.claude_calls}, Codex calls: {counters.codex_calls})",
        flush=True,
    )
    if run_dir is not None:
        _write_status(
            run_dir,
            stage=stage,
            round_no=round_no,
            max_rounds=max_rounds,
            counters=counters,
            detail=message,
        )


def _candidate_branch(task: str, run_id: str) -> str:
    return f"ai-candidate/{run_id}-{_slugify(task, 28)}"


def _create_candidate(
    worktree: Path,
    baseline: RepoBaseline,
    task: str,
    run_id: str,
    *,
    verify_origin: bool,
) -> tuple[str, str]:
    if not _git(worktree, "status", "--porcelain").stdout.strip():
        raise OrchestratorError("implementation produced no changes")

    _assert_source_unchanged(baseline)
    _assert_origin_unchanged(baseline, verify_origin)

    branch = _candidate_branch(task, run_id)
    _git(worktree, "switch", "-c", branch)
    _git(worktree, "add", "-A")
    commit = _run(
        [*_resolved_command("git"), "-C", str(worktree), "commit", "-m", f"AI candidate: {task[:72]}"],
        timeout=300,
        env=_agent_env(),
    )
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout).strip()
        raise OrchestratorError(f"candidate commit failed: {detail}")
    sha = _git(worktree, "rev-parse", "HEAD").stdout.strip().lower()
    _assert_source_unchanged(baseline)
    return branch, sha


def doctor() -> int:
    rows: list[tuple[str, str]] = []
    failed = False
    for name in ("git", "codex", "claude"):
        try:
            cmd = _resolved_command(name)
            result = _run([*cmd, "--version"], timeout=60)
            detail = (result.stdout or result.stderr).strip().splitlines()
            rows.append((name, detail[0] if detail else f"rc={result.returncode}"))
            failed = failed or result.returncode != 0
        except OrchestratorError as exc:
            rows.append((name, str(exc)))
            failed = True

    active = _active_api_billing_env()
    if active:
        rows.append(("billing", "BLOCKED by default: " + ", ".join(active)))
        failed = True
    else:
        rows.append(("billing", "subscription guard OK (no API billing env detected)"))

    for name, detail in rows:
        print(f"{name:7} {detail}")
    return 1 if failed else 0


def run(args: argparse.Namespace) -> int:
    if not args.test and not args.allow_no_tests:
        raise OrchestratorError(
            "at least one --test command is required; use --allow-no-tests only for an intentional exception"
        )

    task = args.task
    if args.task_file:
        task = Path(args.task_file).read_text(encoding="utf-8").strip()
    if not task:
        raise OrchestratorError("task is empty")

    counters = UsageCounters()
    _progress(
        None,
        stage="preflight",
        message="Checking CLI tools and billing guard...",
        round_no=0,
        max_rounds=args.max_rounds,
        counters=counters,
    )

    _resolved_command("git")
    _resolved_command("codex")
    _resolved_command("claude")
    active_billing = _enforce_billing_guard(args.allow_api_billing)

    _progress(
        None,
        stage="preflight",
        message="Checking source repo, branch, cleanliness, and origin sync...",
        round_no=0,
        max_rounds=args.max_rounds,
        counters=counters,
    )
    baseline = _repo_baseline(Path(args.repo), args.expected_branch, not args.no_fetch)

    run_id = _now_id()
    run_dir = _state_root() / "runs" / run_id
    _write_log(run_dir, "task.md", task + "\n")
    _write_status(
        run_dir,
        stage="preflight",
        round_no=0,
        max_rounds=args.max_rounds,
        counters=counters,
        detail="source repo verified",
    )

    _progress(
        run_dir,
        stage="worktree",
        message="Creating isolated worktree...",
        round_no=0,
        max_rounds=args.max_rounds,
        counters=counters,
    )
    parent, worktree = _create_worktree(baseline, run_id)

    result_payload: dict[str, object] = {
        "status": "running",
        "version": ORCHESTRATOR_VERSION,
        "run_id": run_id,
        "repo": str(baseline.root),
        "base_sha": baseline.head_sha,
        "source_branch": baseline.branch,
        "worktree": str(worktree),
        "run_dir": str(run_dir),
        "review_model": args.review_model,
        "dual_review": _requires_dual_review(baseline.root),
        "billing_env_override": list(active_billing),
    }

    try:
        for round_no in range(1, args.max_rounds + 1):
            if round_no == 1:
                implement_prompt = _read_prompt(
                    "implement.md",
                    {
                        "TASK": task,
                        "BASE_SHA": baseline.head_sha,
                        "SOURCE_BRANCH": baseline.branch,
                    },
                )
            else:
                raise OrchestratorError(
                    "internal state error: fix round must be entered through feedback path"
                )

            _write_log(run_dir, f"round-{round_no:02d}-claude-prompt.md", implement_prompt)
            counters.claude_calls += 1
            _progress(
                run_dir,
                stage="claude_implementation",
                message="Claude implementing...",
                round_no=round_no,
                max_rounds=args.max_rounds,
                counters=counters,
            )
            claude = _run_claude_implementation(worktree, implement_prompt, args.agent_timeout)
            _write_log(
                run_dir,
                f"round-{round_no:02d}-claude-raw.json",
                claude.stdout,
            )
            _write_log(
                run_dir,
                f"round-{round_no:02d}-claude.txt",
                _claude_result_text(claude.stdout),
            )
            _assert_agent_did_not_commit(worktree, baseline.head_sha)
            _assert_source_unchanged(baseline)

            while True:
                _progress(
                    run_dir,
                    stage="tests",
                    message="Running automated tests...",
                    round_no=round_no,
                    max_rounds=args.max_rounds,
                    counters=counters,
                )
                tests_ok, tests_text = _run_tests(worktree, args.test, args.test_timeout)
                _write_log(run_dir, f"round-{round_no:02d}-tests.txt", tests_text)
                if tests_ok:
                    print(
                        f"[Round {round_no}/{args.max_rounds}] Tests: PASS",
                        flush=True,
                    )
                    break

                print(
                    f"[Round {round_no}/{args.max_rounds}] Tests: FAIL",
                    flush=True,
                )
                if round_no >= args.max_rounds:
                    raise OrchestratorError("tests still failing after final round")

                round_no += 1
                fix_prompt = _read_prompt(
                    "fix_review.md",
                    {
                        "TASK": task,
                        "FEEDBACK": (
                            "Automated tests failed. Fix the failures without changing Git history.\n\n"
                            + tests_text
                        ),
                    },
                )
                _write_log(run_dir, f"round-{round_no:02d}-claude-prompt.md", fix_prompt)
                counters.claude_calls += 1
                _progress(
                    run_dir,
                    stage="claude_fix",
                    message="Claude fixing test failures...",
                    round_no=round_no,
                    max_rounds=args.max_rounds,
                    counters=counters,
                )
                claude = _run_claude_implementation(worktree, fix_prompt, args.agent_timeout)
                _write_log(
                    run_dir,
                    f"round-{round_no:02d}-claude-raw.json",
                    claude.stdout,
                )
                _write_log(
                    run_dir,
                    f"round-{round_no:02d}-claude.txt",
                    _claude_result_text(claude.stdout),
                )
                _assert_agent_did_not_commit(worktree, baseline.head_sha)
                _assert_source_unchanged(baseline)

            stat, diff = _diff_for_review(worktree)
            if not diff.strip():
                raise OrchestratorError("Claude produced no reviewable changes")

            reviewed_fingerprint = _review_fingerprint(diff)
            review_prompt = _read_prompt(
                "review.md",
                {
                    "TASK": task,
                    "BASE_SHA": baseline.head_sha,
                    "DIFF_STAT": stat,
                    "DIFF": diff,
                    "TEST_RESULTS": tests_text or "(no tests configured)",
                },
            )
            _write_log(run_dir, f"round-{round_no:02d}-codex-review-prompt.md", review_prompt)
            counters.codex_calls += 1
            _progress(
                run_dir,
                stage="codex_review",
                message=f"Codex/Astra reviewing with {args.review_model} (read-only)...",
                round_no=round_no,
                max_rounds=args.max_rounds,
                counters=counters,
            )
            codex = _run_codex_review(
                worktree,
                review_prompt,
                args.agent_timeout,
                args.review_model,
            )
            _write_log(
                run_dir,
                f"round-{round_no:02d}-codex-review.txt",
                codex.stdout + "\n" + codex.stderr,
            )
            review = _parse_codex_review(codex.stdout)
            _write_log(
                run_dir,
                f"round-{round_no:02d}-review.json",
                json.dumps(asdict(review), ensure_ascii=False, indent=2),
            )
            _assert_agent_did_not_commit(worktree, baseline.head_sha)
            _, after_review_diff = _diff_for_review(worktree)
            if _review_fingerprint(after_review_diff) != reviewed_fingerprint:
                raise OrchestratorError(
                    "worktree changed during Codex read-only review; refusing unreviewed candidate"
                )

            if review.approved:
                print(
                    f"[Round {round_no}/{args.max_rounds}] Codex/Astra: APPROVE",
                    flush=True,
                )
                _progress(
                    run_dir,
                    stage="candidate",
                    message="Creating local candidate commit...",
                    round_no=round_no,
                    max_rounds=args.max_rounds,
                    counters=counters,
                )
                branch, sha = _create_candidate(
                    worktree,
                    baseline,
                    task,
                    run_id,
                    verify_origin=not args.no_fetch,
                )
                result_payload.update(
                    {
                        "status": "candidate_ready",
                        "candidate_branch": branch,
                        "candidate_sha": sha,
                        "review": asdict(review),
                        "tests": list(args.test),
                        "claude_calls": counters.claude_calls,
                        "codex_calls": counters.codex_calls,
                        "rounds_used": round_no,
                    }
                )
                _write_log(
                    run_dir,
                    "result.json",
                    json.dumps(result_payload, ensure_ascii=False, indent=2),
                )
                _write_external_result(args.result_file, result_payload)
                _write_status(
                    run_dir,
                    stage="candidate_ready",
                    round_no=round_no,
                    max_rounds=args.max_rounds,
                    counters=counters,
                    detail=f"candidate {sha}",
                )
                print("AI ORCHESTRATOR: CANDIDATE READY")
                print(f"branch: {branch}")
                print(f"sha:    {sha}")
                print(
                    f"usage:  Claude calls={counters.claude_calls}, "
                    f"Codex calls={counters.codex_calls}"
                )
                print(f"logs:   {run_dir}")
                print("STOP: push / BUILD / UPDATE have not been performed.")
                return 0

            print(
                f"[Round {round_no}/{args.max_rounds}] "
                f"Codex/Astra: CHANGES_REQUESTED ({len(review.findings)} findings)",
                flush=True,
            )
            if round_no >= args.max_rounds:
                raise OrchestratorError(
                    "Codex/Astra still requests changes after final review round"
                )

            next_round = round_no + 1
            feedback = json.dumps(asdict(review), ensure_ascii=False, indent=2)
            fix_prompt = _read_prompt(
                "fix_review.md",
                {"TASK": task, "FEEDBACK": feedback},
            )
            _write_log(run_dir, f"round-{next_round:02d}-claude-prompt.md", fix_prompt)
            counters.claude_calls += 1
            _progress(
                run_dir,
                stage="claude_fix",
                message="Claude fixing Codex/Astra review findings...",
                round_no=next_round,
                max_rounds=args.max_rounds,
                counters=counters,
            )
            claude = _run_claude_implementation(worktree, fix_prompt, args.agent_timeout)
            _write_log(
                run_dir,
                f"round-{next_round:02d}-claude-raw.json",
                claude.stdout,
            )
            _write_log(
                run_dir,
                f"round-{next_round:02d}-claude.txt",
                _claude_result_text(claude.stdout),
            )
            _assert_agent_did_not_commit(worktree, baseline.head_sha)
            _assert_source_unchanged(baseline)

            _progress(
                run_dir,
                stage="tests",
                message="Running automated tests after review fixes...",
                round_no=next_round,
                max_rounds=args.max_rounds,
                counters=counters,
            )
            tests_ok, tests_text = _run_tests(worktree, args.test, args.test_timeout)
            _write_log(run_dir, f"round-{next_round:02d}-tests.txt", tests_text)
            if not tests_ok:
                raise OrchestratorError(
                    "tests failed after review fixes; stopped at round limit boundary"
                )
            print(
                f"[Round {next_round}/{args.max_rounds}] Tests: PASS",
                flush=True,
            )

            stat, diff = _diff_for_review(worktree)
            reviewed_fingerprint = _review_fingerprint(diff)
            review_prompt = _read_prompt(
                "review.md",
                {
                    "TASK": task,
                    "BASE_SHA": baseline.head_sha,
                    "DIFF_STAT": stat,
                    "DIFF": diff,
                    "TEST_RESULTS": tests_text or "(no tests configured)",
                },
            )
            _write_log(run_dir, f"round-{next_round:02d}-codex-review-prompt.md", review_prompt)
            counters.codex_calls += 1
            _progress(
                run_dir,
                stage="codex_review",
                message=f"Codex/Astra re-reviewing with {args.review_model} (read-only)...",
                round_no=next_round,
                max_rounds=args.max_rounds,
                counters=counters,
            )
            codex = _run_codex_review(
                worktree,
                review_prompt,
                args.agent_timeout,
                args.review_model,
            )
            _write_log(
                run_dir,
                f"round-{next_round:02d}-codex-review.txt",
                codex.stdout + "\n" + codex.stderr,
            )
            review = _parse_codex_review(codex.stdout)
            _write_log(
                run_dir,
                f"round-{next_round:02d}-review.json",
                json.dumps(asdict(review), ensure_ascii=False, indent=2),
            )
            _assert_agent_did_not_commit(worktree, baseline.head_sha)
            _, after_review_diff = _diff_for_review(worktree)
            if _review_fingerprint(after_review_diff) != reviewed_fingerprint:
                raise OrchestratorError(
                    "worktree changed during Codex read-only review; refusing unreviewed candidate"
                )
            if not review.approved:
                raise OrchestratorError(
                    "Codex/Astra still requests changes after final review round"
                )

            print(
                f"[Round {next_round}/{args.max_rounds}] Codex/Astra: APPROVE",
                flush=True,
            )
            _progress(
                run_dir,
                stage="candidate",
                message="Creating local candidate commit...",
                round_no=next_round,
                max_rounds=args.max_rounds,
                counters=counters,
            )
            branch, sha = _create_candidate(
                worktree,
                baseline,
                task,
                run_id,
                verify_origin=not args.no_fetch,
            )
            result_payload.update(
                {
                    "status": "candidate_ready",
                    "candidate_branch": branch,
                    "candidate_sha": sha,
                    "review": asdict(review),
                    "tests": list(args.test),
                    "claude_calls": counters.claude_calls,
                    "codex_calls": counters.codex_calls,
                    "rounds_used": next_round,
                }
            )
            _write_log(
                run_dir,
                "result.json",
                json.dumps(result_payload, ensure_ascii=False, indent=2),
            )
            _write_external_result(args.result_file, result_payload)
            _write_status(
                run_dir,
                stage="candidate_ready",
                round_no=next_round,
                max_rounds=args.max_rounds,
                counters=counters,
                detail=f"candidate {sha}",
            )
            print("AI ORCHESTRATOR: CANDIDATE READY")
            print(f"branch: {branch}")
            print(f"sha:    {sha}")
            print(
                f"usage:  Claude calls={counters.claude_calls}, "
                f"Codex calls={counters.codex_calls}"
            )
            print(f"logs:   {run_dir}")
            print("STOP: push / BUILD / UPDATE have not been performed.")
            return 0

        raise OrchestratorError("orchestration ended without a candidate")
    except Exception as exc:
        result_payload.update(
            {
                "status": "stopped",
                "error": str(exc),
                "claude_calls": counters.claude_calls,
                "codex_calls": counters.codex_calls,
            }
        )
        _write_log(run_dir, "result.json", json.dumps(result_payload, ensure_ascii=False, indent=2))
        _write_external_result(args.result_file, result_payload)
        _write_status(
            run_dir,
            stage="stopped",
            round_no=min(args.max_rounds, max(1, counters.codex_calls)),
            max_rounds=args.max_rounds,
            counters=counters,
            detail=str(exc),
        )
        print(f"AI ORCHESTRATOR STOPPED: {exc}", file=sys.stderr)
        print(
            f"usage: Claude calls={counters.claude_calls}, "
            f"Codex calls={counters.codex_calls}",
            file=sys.stderr,
        )
        print(f"isolated worktree preserved: {worktree}", file=sys.stderr)
        print(f"logs: {run_dir}", file=sys.stderr)
        return 1
    finally:
        if result_payload.get("status") == "candidate_ready":
            try:
                _git(baseline.root, "worktree", "remove", "--force", str(worktree), timeout=300)
                shutil.rmtree(parent, ignore_errors=True)
            except OrchestratorError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude implementation + Codex/Astra review orchestrator"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check git / codex / claude CLI and billing guard")

    run_parser = sub.add_parser(
        "run",
        help="develop in an isolated worktree and stop at candidate",
    )
    run_parser.add_argument("--repo", required=True, help="target Git repository")
    task_group = run_parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="task text")
    task_group.add_argument("--task-file", help="UTF-8 task file")
    run_parser.add_argument("--expected-branch", help="fail if source repo is on another branch")
    run_parser.add_argument("--test", action="append", default=[], help="test command; repeatable")
    run_parser.add_argument("--allow-no-tests", action="store_true")
    run_parser.add_argument(
        "--max-rounds",
        type=int,
        default=DEFAULT_MAX_ROUNDS,
        help=f"maximum Claude->Codex review rounds (default {DEFAULT_MAX_ROUNDS})",
    )
    run_parser.add_argument(
        "--review-model",
        default=DEFAULT_REVIEW_MODEL,
        help=f"Codex review model (default {DEFAULT_REVIEW_MODEL})",
    )
    run_parser.add_argument(
        "--allow-api-billing",
        action="store_true",
        help="explicitly allow detected API/third-party billing environment variables",
    )
    run_parser.add_argument(
        "--result-file",
        help="optional JSON result path for machine callers such as DCC",
    )
    run_parser.add_argument("--agent-timeout", type=int, default=DEFAULT_TIMEOUT)
    run_parser.add_argument("--test-timeout", type=int, default=900)
    run_parser.add_argument("--no-fetch", action="store_true", help="skip origin fetch (not recommended)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        if args.max_rounds < 1 or args.max_rounds > 2:
            raise OrchestratorError("--max-rounds must be 1 or 2 in v0.2")
        return run(args)
    except (OSError, OrchestratorError) as exc:
        print(f"AI ORCHESTRATOR STOPPED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
