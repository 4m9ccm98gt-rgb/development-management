"""Codex + Claude local development orchestrator.

v0.1 intentionally stops at a local candidate commit. It never pushes, builds,
deploys, or updates production resources.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
DEFAULT_TIMEOUT = 1800
MAX_DIFF_CHARS = 200_000


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


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


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
            [*_resolved_command("git"), "-C", str(root), "fetch", "--prune", "origin", branch],
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


def _assert_agent_did_not_commit(worktree: Path, base_sha: str) -> None:
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip().lower()
    branch = _git(worktree, "branch", "--show-current").stdout.strip()
    if head != base_sha.lower() or branch:
        raise OrchestratorError(
            "agent changed Git history or attached the isolated worktree to a branch; refusing to continue"
        )


def _run_codex(worktree: Path, prompt: str, timeout: int) -> CommandResult:
    command = [
        *_resolved_command("codex"),
        "exec",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "-",
    ]
    result = _run(
        command,
        cwd=worktree,
        input_text=prompt,
        timeout=timeout,
        env=_agent_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"Codex failed: {detail}")
    return result


def _run_claude(worktree: Path, prompt: str, timeout: int) -> CommandResult:
    command = [
        *_resolved_command("claude"),
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--max-turns",
        "8",
    ]
    result = _run(
        command,
        cwd=worktree,
        input_text=prompt,
        timeout=timeout,
        env=_agent_env(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"Claude review failed: {detail}")
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
        raise OrchestratorError("Claude JSON did not contain a review result")
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


def _parse_review(stdout: str) -> Review:
    value = _extract_json_object(_claude_result_text(stdout))
    verdict = str(value.get("verdict", "")).strip().lower()
    if verdict not in {"approve", "changes_requested"}:
        raise OrchestratorError(f"invalid Claude verdict: {verdict or '<missing>'}")
    summary = str(value.get("summary", "")).strip()
    raw_findings = value.get("findings", [])
    if not isinstance(raw_findings, list):
        raise OrchestratorError("review findings must be an array")
    findings = tuple(item for item in raw_findings if isinstance(item, dict))
    if verdict == "approve" and findings:
        raise OrchestratorError("Claude returned approve with findings; refusing ambiguous review")
    return Review(verdict, summary, findings)


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
    stat = _git(worktree, "diff", "--stat").stdout
    diff = _git(worktree, "diff", "--no-ext-diff", "--find-renames").stdout
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


def _write_log(run_dir: Path, name: str, text: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / name).write_text(text, encoding="utf-8")


def _candidate_branch(task: str, run_id: str) -> str:
    return f"ai-candidate/{run_id}-{_slugify(task, 28)}"


def _create_candidate(worktree: Path, baseline: RepoBaseline, task: str, run_id: str) -> tuple[str, str]:
    if not _git(worktree, "status", "--porcelain").stdout.strip():
        raise OrchestratorError("Codex produced no changes")

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

    # Resolve tools before touching Git worktrees.
    _resolved_command("git")
    _resolved_command("codex")
    _resolved_command("claude")

    baseline = _repo_baseline(Path(args.repo), args.expected_branch, not args.no_fetch)
    run_id = _now_id()
    run_dir = _state_root() / "runs" / run_id
    _write_log(run_dir, "task.md", task + "\n")

    parent, worktree = _create_worktree(baseline, run_id)
    result_payload: dict[str, object] = {
        "status": "running",
        "run_id": run_id,
        "repo": str(baseline.root),
        "base_sha": baseline.head_sha,
        "source_branch": baseline.branch,
        "worktree": str(worktree),
        "run_dir": str(run_dir),
    }

    try:
        implement_prompt = _read_prompt(
            "implement.md",
            {
                "TASK": task,
                "BASE_SHA": baseline.head_sha,
                "SOURCE_BRANCH": baseline.branch,
            },
        )
        _write_log(run_dir, "round-01-codex-prompt.md", implement_prompt)
        codex = _run_codex(worktree, implement_prompt, args.agent_timeout)
        _write_log(run_dir, "round-01-codex.txt", codex.stdout + "\n" + codex.stderr)
        _assert_agent_did_not_commit(worktree, baseline.head_sha)
        _assert_source_unchanged(baseline)

        last_review: Review | None = None
        for round_no in range(1, args.max_rounds + 1):
            tests_ok, tests_text = _run_tests(worktree, args.test, args.test_timeout)
            _write_log(run_dir, f"round-{round_no:02d}-tests.txt", tests_text)
            if not tests_ok:
                if round_no >= args.max_rounds:
                    raise OrchestratorError("tests still failing after final round")
                fix_prompt = _read_prompt(
                    "fix_review.md",
                    {
                        "TASK": task,
                        "FEEDBACK": "Automated tests failed. Fix the failures without changing Git history.\n\n" + tests_text,
                    },
                )
                _write_log(run_dir, f"round-{round_no + 1:02d}-codex-prompt.md", fix_prompt)
                codex = _run_codex(worktree, fix_prompt, args.agent_timeout)
                _write_log(
                    run_dir,
                    f"round-{round_no + 1:02d}-codex.txt",
                    codex.stdout + "\n" + codex.stderr,
                )
                _assert_agent_did_not_commit(worktree, baseline.head_sha)
                _assert_source_unchanged(baseline)
                continue

            stat, diff = _diff_for_review(worktree)
            if not diff.strip():
                raise OrchestratorError("Codex produced no reviewable changes")
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
            _write_log(run_dir, f"round-{round_no:02d}-claude-prompt.md", review_prompt)
            claude = _run_claude(worktree, review_prompt, args.agent_timeout)
            _write_log(run_dir, f"round-{round_no:02d}-claude-raw.json", claude.stdout)
            last_review = _parse_review(claude.stdout)
            _write_log(
                run_dir,
                f"round-{round_no:02d}-review.json",
                json.dumps(asdict(last_review), ensure_ascii=False, indent=2),
            )

            if last_review.approved:
                branch, sha = _create_candidate(worktree, baseline, task, run_id)
                result_payload.update(
                    {
                        "status": "candidate_ready",
                        "candidate_branch": branch,
                        "candidate_sha": sha,
                        "review": asdict(last_review),
                        "tests": list(args.test),
                    }
                )
                _write_log(
                    run_dir,
                    "result.json",
                    json.dumps(result_payload, ensure_ascii=False, indent=2),
                )
                print("AI ORCHESTRATOR: CANDIDATE READY")
                print(f"branch: {branch}")
                print(f"sha:    {sha}")
                print(f"logs:   {run_dir}")
                print("STOP: push / BUILD / UPDATE have not been performed.")
                return 0

            if round_no >= args.max_rounds:
                raise OrchestratorError("Claude still requests changes after final review round")

            feedback = json.dumps(asdict(last_review), ensure_ascii=False, indent=2)
            fix_prompt = _read_prompt(
                "fix_review.md",
                {"TASK": task, "FEEDBACK": feedback},
            )
            _write_log(run_dir, f"round-{round_no + 1:02d}-codex-prompt.md", fix_prompt)
            codex = _run_codex(worktree, fix_prompt, args.agent_timeout)
            _write_log(
                run_dir,
                f"round-{round_no + 1:02d}-codex.txt",
                codex.stdout + "\n" + codex.stderr,
            )
            _assert_agent_did_not_commit(worktree, baseline.head_sha)
            _assert_source_unchanged(baseline)

        raise OrchestratorError("orchestration ended without a candidate")
    except Exception as exc:
        result_payload.update({"status": "stopped", "error": str(exc)})
        _write_log(run_dir, "result.json", json.dumps(result_payload, ensure_ascii=False, indent=2))
        print(f"AI ORCHESTRATOR STOPPED: {exc}", file=sys.stderr)
        print(f"isolated worktree preserved: {worktree}", file=sys.stderr)
        print(f"logs: {run_dir}", file=sys.stderr)
        return 1
    finally:
        # Successful candidates keep only the local branch/ref; failed runs keep
        # their isolated worktree for diagnosis.
        if result_payload.get("status") == "candidate_ready":
            try:
                _git(baseline.root, "worktree", "remove", "--force", str(worktree), timeout=300)
                shutil.rmtree(parent, ignore_errors=True)
            except OrchestratorError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex + Claude AI development orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check git / codex / claude CLI availability")

    run_parser = sub.add_parser("run", help="develop in an isolated worktree and stop at candidate")
    run_parser.add_argument("--repo", required=True, help="target Git repository")
    task_group = run_parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="task text")
    task_group.add_argument("--task-file", help="UTF-8 task file")
    run_parser.add_argument("--expected-branch", help="fail if source repo is on another branch")
    run_parser.add_argument("--test", action="append", default=[], help="test command; repeatable")
    run_parser.add_argument("--allow-no-tests", action="store_true")
    run_parser.add_argument("--max-rounds", type=int, default=3)
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
        if args.max_rounds < 1 or args.max_rounds > 8:
            raise OrchestratorError("--max-rounds must be between 1 and 8")
        return run(args)
    except (OSError, OrchestratorError) as exc:
        print(f"AI ORCHESTRATOR STOPPED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
