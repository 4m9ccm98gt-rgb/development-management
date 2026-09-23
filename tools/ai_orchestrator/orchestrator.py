"""Claude main implementation with failure-only Recovery and an external Final Review Gate.

Stops at a local candidate; never pushes, builds, or deploys.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Iterable


HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
DEFAULT_TIMEOUT = 1800
MAX_DIFF_CHARS = 200_000
REVIEW_BUNDLE_CHARS = 90_000
DEFAULT_REVIEW_MODEL = "gpt-6-astra"
DEFAULT_MAX_ROUNDS = 30
DEFAULT_TEST_TIMEOUT = 600
PROVIDER_RETRIES = 30
CLAUDE_IMPLEMENTATION_MAX_TURNS = 12
CLAUDE_NO_DIFF_RESUMES = 2
API_BILLING_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


class OrchestratorError(RuntimeError):
    """Fail-closed orchestration error."""


class ClaudeExecutionError(OrchestratorError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


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
        proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name != "nt"),
            env=env,
        )
        try:
            stdout, stderr = proc.communicate(input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            # Recovery must never overlap with a timed-out provider's children.
            _terminate_process_tree(proc)
            proc.communicate(timeout=10)
            raise
    except subprocess.TimeoutExpired as exc:
        raise OrchestratorError(f"command timed out after {timeout}s: {args[0]}") from exc
    except OSError as exc:
        raise OrchestratorError(f"failed to start {args[0]}: {exc}") from exc
    return CommandResult(tuple(args), proc.returncode, stdout or "", stderr or "")


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
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
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


def _fetch_expected_origin_branch(root: Path, branch: str, *, label: str = "git fetch") -> None:
    refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
    fetch = _run(
        [
            *_resolved_command("git"),
            "-C",
            str(root),
            "fetch",
            "--prune",
            "origin",
            refspec,
        ],
        timeout=300,
    )
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout).strip()
        raise OrchestratorError(f"{label} failed for origin/{branch}: {detail}")


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
        _fetch_expected_origin_branch(root, branch)

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
        _fetch_expected_origin_branch(
            baseline.root,
            baseline.branch,
            label="final git fetch",
        )
    origin_sha = _git(
        baseline.root, "rev-parse", f"origin/{baseline.branch}"
    ).stdout.strip().lower()
    if origin_sha != baseline.origin_sha:
        raise OrchestratorError(
            f"origin/{baseline.branch} moved during orchestration: "
            f"{baseline.origin_sha[:12]} -> {origin_sha[:12]}"
        )


def _worktree_head_probe(worktree: Path) -> CommandResult:
    """Retry only an unexplained nonzero exit from this read-only safety probe."""
    command = [*_resolved_command("git"), "-C", str(worktree), "rev-parse", "HEAD"]
    for attempt in range(1, 4):
        result = _run(command, timeout=120)
        if result.returncode == 0:
            return result
        detail = result.stderr.strip() or result.stdout.strip()
        if detail or attempt == 3:
            raise OrchestratorError(
                f"git rev-parse HEAD failed: {detail or '<empty stdout/stderr>'} "
                f"(return code {result.returncode}, attempt {attempt}/3)"
            )
        time.sleep(0.2)
    raise AssertionError("unreachable")


def _assert_agent_did_not_commit(worktree: Path, base_sha: str) -> None:
    head = _worktree_head_probe(worktree).stdout.strip().lower()
    branch = _git(worktree, "branch", "--show-current").stdout.strip()
    if head != base_sha.lower() or branch:
        raise OrchestratorError(
            "agent changed Git history or attached the isolated worktree to a branch; refusing to continue"
        )


# Non-interactive acceptEdits denies Bash unless allowed here. Only inspection,
# test/static-check and interpreter commands are allowed; git write commands
# (add/commit/push/checkout/reset/...) are deliberately absent.
CLAUDE_ALLOWED_BASH_TOOLS: tuple[str, ...] = tuple(
    f"Bash({prefix}:*)"
    for prefix in (
        "git status",
        "git diff",
        "git log",
        "git show",
        "git ls-files",
        "git grep",
        "git rev-parse",
        "git branch --show-current",
        "python",
        "python3",
        "py",
        "pytest",
        "ruff",
        "ls",
        "dir",
        "cat",
        "head",
        "tail",
        "wc",
        "sed",
        "grep",
        "rg",
        "find",
        "sort",
        "diff",
        "pwd",
        "mkdir",
        "cp",
        "mv",
        "echo",
    )
)


def _claude_implementation_command(session_id: str | None = None) -> list[str]:
    command = [
        *_resolved_command("claude"),
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        ",".join(CLAUDE_ALLOWED_BASH_TOOLS),
        "--max-turns",
        str(CLAUDE_IMPLEMENTATION_MAX_TURNS),
    ]
    if session_id is not None:
        if not _valid_claude_session_id(session_id):
            raise ClaudeExecutionError("SESSION_ID_UNAVAILABLE", "invalid Claude session UUID")
        command.extend(["--resume", session_id])
    return command


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


def _looks_like_max_turns(result: CommandResult) -> bool:
    payload = _claude_payload(result)
    if payload.get("subtype") == "error_max_turns":
        return True
    if not (result.returncode or payload.get("is_error")):
        return False
    text = (str(payload.get("errors", "")) + "\n" + result.stderr).lower()
    return "maximum number of turns" in text or "error_max_turns" in text


def _claude_payload(result: CommandResult) -> dict[str, object]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _valid_claude_session_id(value: object) -> bool:
    # Claude Code 2.1.278 --help: --resume <session-id>; --session-id is a UUID.
    # Installed CLI result schema (including error_max_turns) contains session_id.
    return isinstance(value, str) and re.fullmatch(
        r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", value
    ) is not None


def _claude_quota_error(result: CommandResult) -> bool:
    payload = _claude_payload(result)
    if not (result.returncode or payload.get("is_error")):
        return False
    # Inspect error envelopes, not successful implementation prose about quotas.
    text = "\n".join(str(payload.get(key, "")) for key in ("subtype", "errors", "result"))
    text += "\n" + result.stderr
    if not payload:
        text += "\n" + result.stdout
    return bool(re.search(
        r"credit balance (?:is )?too low|insufficient[_ ](?:quota|credits?)|"
        r"(?:quota|credits?)[^\n]{0,40}(?:exhausted|exceeded|depleted)|"
        r"(?:usage|spending) limit|(?:you(?:'|’)?ve |you have )?hit your limit|"
        r"out of (?:extra usage|credits)|billing[_ ]error|error_max_budget_usd",
        text, re.IGNORECASE,
    ))


def _run_claude_implementation(
    worktree: Path,
    prompt: str,
    timeout: int,
    session_id: str | None = None,
) -> CommandResult:
    # No generic provider retry here, especially for quota/credit failures.
    # Classification happens after raw output/session metadata have been saved.
    return _run(
        _claude_implementation_command(session_id),
        cwd=worktree,
        input_text=prompt,
        timeout=timeout,
        env=_agent_env(),
    )


def _run_claude_diagnosis(worktree: Path, prompt: str, timeout: int) -> CommandResult:
    # Separate read-only capability set; no shell, editor, or sub-agent tool.
    return _run([
        *_resolved_command("claude"), "-p", "--output-format", "json",
        "--permission-mode", "default", "--tools", "Read,Glob,Grep",
        "--allowedTools", "Read,Glob,Grep", "--max-turns", "12",
        "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
    ], cwd=worktree, input_text=prompt, timeout=timeout, env=_agent_env())


def _failure_fingerprint(failure: dict[str, object]) -> str:
    # Test durations and heartbeat counts are not evidence of progress.
    text = json.dumps(failure, sort_keys=True, ensure_ascii=False)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|ms|s)\b", "<duration>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}[T ][\d:.+-]+", "<time>", text)
    return _review_fingerprint(text)


def _final_review_gate(request: dict[str, object], decision_path: str | None) -> dict[str, str]:
    """Provider-neutral, explicit approval of this exact review request only.

    No AI call and no implicit approval when no reviewer is connected.
    The external caller owns the verdict, never the implementation agent.
    """
    if not decision_path:
        return {"verdict": "PENDING", "summary": "Awaiting independent Final Review; request saved in run_dir."}
    try:
        decision = json.loads(Path(decision_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OrchestratorError("Final Review decision is unreadable") from exc
    if not isinstance(decision, dict) or decision.get("request_id") != request["request_id"]:
        raise OrchestratorError("Final Review decision does not match request_id")
    verdict = decision.get("verdict")
    summary = decision.get("summary")
    if verdict not in ("PASS", "FAIL", "PENDING") or not isinstance(summary, str) or not summary.strip():
        raise OrchestratorError("invalid Final Review decision")
    return {"verdict": verdict, "summary": summary}


def _implement_with_progress(
    worktree: Path, prompt: str, timeout: int, *, baseline: RepoBaseline,
    run_dir: Path, round_no: int, max_rounds: int, stage: str,
    counters: UsageCounters, result_payload: dict[str, object],
) -> CommandResult:
    """Only resume a turn-limited, empty implementation; never rerun design."""
    session_id = None
    state: dict[str, object] = {
        "stage": stage, "round": round_no, "session_id": None,
        "resume_count": 0, "max_resumes": CLAUDE_NO_DIFF_RESUMES,
        "max_turns": CLAUDE_IMPLEMENTATION_MAX_TURNS,
    }
    result_payload["claude_state"] = state

    def save(outcome: str) -> None:
        state["outcome"] = outcome
        _write_external_result(str(run_dir / "claude-session.json"), {
            "run_id": result_payload["run_id"], "worktree": str(worktree),
            "base_sha": baseline.head_sha, **state,
        })

    def stop(code: str, detail: str) -> None:
        save(code)
        raise ClaudeExecutionError(code, detail)

    for resume_no in range(CLAUDE_NO_DIFF_RESUMES + 1):
        name = f"round-{round_no:02d}-claude"
        if resume_no:
            name += f"-resume-{resume_no:02d}"
        state.update(resume_count=resume_no, prompt_file=name + "-prompt.md")
        _write_log(run_dir, name + "-prompt.md", prompt)
        save("RESUMING" if resume_no else "IMPLEMENTING")
        counters.claude_calls += 1
        _progress(
            run_dir, stage=f"claude_{stage}",
            message=f"Claude {stage}" + (f" resume {resume_no}/{CLAUDE_NO_DIFF_RESUMES}..." if resume_no else "..."),
            round_no=round_no, max_rounds=max_rounds, counters=counters,
        )
        try:
            result = _run_claude_implementation(worktree, prompt, timeout, session_id)
        except OrchestratorError as exc:
            stop("RESUME_FAILED" if resume_no else "PROVIDER_ERROR", str(exc))
        _write_log(run_dir, name + "-raw.json", result.stdout + "\n" + result.stderr)
        payload = _claude_payload(result)
        returned_id = payload.get("session_id")
        if _valid_claude_session_id(returned_id):
            returned_id = returned_id.lower()
            if session_id and returned_id != session_id:
                stop("RESUME_FAILED", "Claude returned a different session ID")
            session_id = returned_id
            state["session_id"] = session_id
        save("RECEIVED")
        _assert_agent_did_not_commit(worktree, baseline.head_sha)
        _assert_source_unchanged(baseline)
        _, diff = _diff_for_review(worktree)
        state["has_diff"] = bool(diff.strip())
        if _claude_quota_error(result):
            stop("PROVIDER_QUOTA", "Claude quota/credit exhausted; no automatic retry")
        max_turns = _looks_like_max_turns(result)
        if not max_turns and (result.returncode or payload.get("is_error")):
            stop("RESUME_FAILED" if resume_no else "PROVIDER_ERROR",
                 (result.stderr or result.stdout).strip())
        if max_turns:
            save("MAX_TURNS_RECOVERABLE")
            text = "Claude reached max-turns; worktree progress checked."
        else:
            try:
                text = _claude_result_text(result.stdout)
            except OrchestratorError as exc:
                stop("RESUME_FAILED" if resume_no else "PROVIDER_ERROR", str(exc))
        _write_log(run_dir, name + ".txt", text)
        if state["has_diff"]:
            save("IMPLEMENTATION_DIFF")
            return result
        if not max_turns or resume_no == CLAUDE_NO_DIFF_RESUMES:
            stop("NO_PROGRESS", f"no reviewable diff after {resume_no} resume(s); Tests not started")
        if not session_id:
            stop("SESSION_ID_UNAVAILABLE", "max-turns with no diff and no valid session_id; Tests not started")
        prompt = (
            "Continue the implementation from the TaskSpec and recovery findings already in this session. "
            "The previous invocation reached max-turns without a reviewable worktree diff. "
            "Make the required file changes now; do not restart investigation, redesign, or self-review. "
            "Keep all original scope and safety constraints. Do not commit, push, build, or deploy."
        )


def _run_codex_review(
    worktree: Path,
    prompt: str,
    timeout: int,
    model: str,
) -> CommandResult:
    last_detail = ""
    for attempt in range(1, PROVIDER_RETRIES + 1):
        result = _run(
            _codex_review_command(model),
            cwd=worktree,
            input_text=prompt,
            timeout=timeout,
            env=_agent_env(),
        )
        if result.returncode == 0:
            return result
        last_detail = (result.stderr or result.stdout).strip()
        print(
            f"[Astra] provider attempt {attempt}/{PROVIDER_RETRIES} failed; retrying...",
            flush=True,
        )
        if attempt < PROVIDER_RETRIES:
            time.sleep(min(30, 5 * attempt))
    raise OrchestratorError(f"Codex/Astra provider failed after retries: {last_detail}")


def _claude_result_text(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OrchestratorError("Claude did not return valid CLI JSON") from exc
    if not isinstance(payload, dict):
        raise OrchestratorError("Claude CLI JSON must be an object")
    if payload.get("is_error"):
        subtype = str(payload.get("subtype", "")).lower()
        errors = " ".join(str(item) for item in (payload.get("errors") or []))
        if subtype == "error_max_turns" or "maximum number of turns" in errors.lower():
            return "Claude reached max-turns. Partial worktree preserved for tests/review."
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
    verdict = verdict.replace("-", "_").replace(" ", "_")
    if verdict in {"approved", "pass", "passed", "ok"}:
        verdict = "approve"
    elif verdict in {
        "change_requested",
        "request_changes",
        "requested_changes",
        "changes_required",
    }:
        verdict = "changes_requested"
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


def _parse_codex_review(stdout: str) -> Review:
    return _review_from_value(_extract_json_object(stdout), "Codex")


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, 15)
        except (OSError, ProcessLookupError):
            proc.kill()


def _run_test_command(
    worktree: Path,
    command: str,
    timeout: int,
) -> tuple[bool, str]:
    if os.name == "nt":
        args = ["cmd.exe", "/d", "/s", "/c", command]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        start_new_session = False
    else:
        args = ["/bin/sh", "-lc", command]
        creationflags = 0
        start_new_session = True

    proc = subprocess.Popen(
        args,
        cwd=str(worktree),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=_agent_env(),
        creationflags=creationflags,
        start_new_session=start_new_session,
    )
    lines: list[str] = []
    output_queue: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            output_queue.put(line)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    started = time.monotonic()
    last_heartbeat = started

    while True:
        drained = False
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            drained = True
            lines.append(line)
            text = line.rstrip()
            if text:
                print(f"[Tests] {text}", flush=True)

        rc = proc.poll()
        if rc is not None:
            thread.join(timeout=1)
            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    break
                lines.append(line)
                text = line.rstrip()
                if text:
                    print(f"[Tests] {text}", flush=True)
            return rc == 0, "".join(lines)

        now = time.monotonic()
        elapsed = int(now - started)
        if now - last_heartbeat >= 10:
            print(
                f"[Tests] still running — elapsed={elapsed}s command={command}",
                flush=True,
            )
            last_heartbeat = now

        if now - started >= timeout:
            print(
                f"[Tests] HANG/TIMEOUT after {timeout}s — terminating process tree",
                flush=True,
            )
            _terminate_process_tree(proc)
            thread.join(timeout=2)
            while True:
                try:
                    lines.append(output_queue.get_nowait())
                except queue.Empty:
                    break
            lines.append(f"\nTEST TIMEOUT/HANG after {timeout}s: {command}\n")
            return False, "".join(lines)

        if not drained:
            time.sleep(0.1)


def _run_tests(worktree: Path, commands: Iterable[str], timeout: int) -> tuple[bool, str]:
    outputs: list[str] = []
    for command in commands:
        print(f"[Tests] START {command}", flush=True)
        ok, text = _run_test_command(worktree, command, timeout)
        outputs.append(f"$ {command}\n{text}".rstrip())
        if not ok:
            return False, "\n\n".join(outputs)
    return True, "\n\n".join(outputs)


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
    return stat, diff


def _split_review_diff(diff_text: str, limit: int = REVIEW_BUNDLE_CHARS) -> list[str]:
    if len(diff_text) <= limit:
        return [diff_text]
    bundles: list[str] = []
    current: list[str] = []
    size = 0
    for line in diff_text.splitlines(keepends=True):
        if current and size + len(line) > limit:
            bundles.append("".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line)
    if current:
        bundles.append("".join(current))
    return bundles


def _tag_review_findings(review: Review) -> Review:
    tagged: list[dict[str, object]] = []
    for index, finding in enumerate(review.findings, 1):
        item = dict(finding)
        item.setdefault("finding_id", f"F-{index:03d}")
        tagged.append(item)
    return Review(review.verdict, review.summary, tuple(tagged))


def _parse_evaluation(stdout: str) -> dict[str, object]:
    value = _extract_json_object(_claude_result_text(stdout))
    decisions = value.get("decisions")
    if not isinstance(decisions, list):
        raise OrchestratorError("Claude review evaluation did not contain decisions[]")
    for item in decisions:
        if not isinstance(item, dict):
            raise OrchestratorError("Claude review evaluation contains a non-object decision")
        decision = str(item.get("decision", "")).strip().upper()
        if decision not in {"ACCEPT", "DISPUTE", "NEEDS_CLARIFICATION"}:
            raise OrchestratorError(f"invalid Claude finding decision: {decision or '<missing>'}")
    return value


def _parse_design(stdout: str) -> dict[str, object]:
    value = _extract_json_object(stdout)
    design = value.get("design")
    if not isinstance(design, list) or not design:
        raise OrchestratorError("Astra design result must contain a non-empty design[]")
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        raise OrchestratorError("Astra design result must contain evidence[]")
    return value


def _evaluation_has_dispute(value: dict[str, object]) -> bool:
    decisions = value.get("decisions")
    if not isinstance(decisions, list):
        return True
    return any(
        isinstance(item, dict)
        and str(item.get("decision", "")).strip().upper() != "ACCEPT"
        for item in decisions
    )


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
    prefix = (f"[Recovery {round_no}/{max_rounds}]" if round_no else
              "[Preflight]" if stage in {"preflight", "worktree"} else "[Main]")
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
    for name in ("git", "claude"):
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

    resumed = None
    if getattr(args, "resume_review", None):
        run_dir = Path(args.resume_review).resolve()
        resumed = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        if resumed.get("status") != "review_pending":
            raise OrchestratorError("only review_pending runs may resume")
        if (resumed["repo"] != str(baseline.root) or resumed["base_sha"] != baseline.head_sha
                or resumed["source_branch"] != baseline.branch
                or (run_dir / "task.md").read_text(encoding="utf-8").strip() != task):
            raise OrchestratorError("review resume source or TaskSpec mismatch")
        if args.test != resumed["tests"] or args.max_rounds != resumed["max_rounds"]:
            raise OrchestratorError("review resume Verification or Recovery budget mismatch")
        run_id = resumed["run_id"]
    else:
        run_id = _now_id()
        run_dir = _state_root() / "runs" / run_id
    # DCC has no other way to learn this run's durable state directory (needed
    # to record a safety-stop outcome onto status.json/result.json); this line
    # remains stable for DCC's existing safety-stop marker parser.
    print(f"[Preflight] run_dir={run_dir}", flush=True)
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
    if resumed:
        worktree = Path(resumed["worktree"])
        parent = None  # Never infer a recursively removable parent from persisted state.
        saved_request = json.loads((run_dir / "final-review-request.json").read_text(encoding="utf-8"))
        _assert_agent_did_not_commit(worktree, baseline.head_sha)
        if _diff_for_review(worktree)[1] != saved_request["diff"]:
            raise OrchestratorError("worktree changed since pending Final Review")
    else:
        parent, worktree = _create_worktree(baseline, run_id)

    result_payload: dict[str, object] = {
        "status": "running",
        "version": "0.6-recovery",
        "run_id": run_id,
        "repo": str(baseline.root),
        "base_sha": baseline.head_sha,
        "source_branch": baseline.branch,
        "worktree": str(worktree),
        "run_dir": str(run_dir),
        "final_review_gate": "external",
        "recovery_iterations": 0,
        "recovery_history": [],
        "billing_env_override": list(active_billing),
        "tests": list(args.test),
        "max_rounds": args.max_rounds,
    }
    if resumed:
        result_payload.update(resumed)
        result_payload["status"] = "running"
        counters.claude_calls = resumed["claude_calls"]
        counters.codex_calls = resumed["codex_calls"]

    def assert_readonly(before: str, label: str) -> None:
        _, after_diff = _diff_for_review(worktree)
        if _review_fingerprint(after_diff) != before:
            raise OrchestratorError(f"worktree changed during read-only stage: {label}")

    def create_candidate(round_no: int, review: Review) -> int:
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
        print("AI ORCHESTRATOR: CANDIDATE READY", flush=True)
        print(f"branch: {branch}", flush=True)
        print(f"sha:    {sha}", flush=True)
        print(
            f"usage:  Claude calls={counters.claude_calls}, "
            f"Codex calls={counters.codex_calls}",
            flush=True,
        )
        print(f"logs:   {run_dir}", flush=True)
        print("STOP: push / BUILD / UPDATE have not been performed.", flush=True)
        return 0

    round_no = int(result_payload["recovery_iterations"])  # Recovery only.
    history = result_payload["recovery_history"]
    last_error = None

    def persist():
        result_payload.update(recovery_iterations=round_no, rounds_used=round_no,
                              claude_calls=counters.claude_calls, codex_calls=counters.codex_calls)
        _write_external_result(str(run_dir / "result.json"), result_payload)
        _write_external_result(args.result_file, result_payload)

    def progress(stage, message):
        result_payload.update(stage=stage, round=round_no)
        persist()
        _progress(run_dir, stage=stage, message=message, round_no=round_no,
                  max_rounds=args.max_rounds, counters=counters)

    def check_safety():
        _assert_agent_did_not_commit(worktree, baseline.head_sha)
        _assert_source_unchanged(baseline)

    def implement(prompt, stage):
        nonlocal last_error
        progress("claude_" + stage, "Claude " + stage + "...")
        try:
            output = _implement_with_progress(
                worktree, prompt, args.agent_timeout, baseline=baseline,
                run_dir=run_dir, round_no=round_no, max_rounds=args.max_rounds,
                stage=stage, counters=counters, result_payload=result_payload,
            )
            text = _claude_result_text(output.stdout) if not _looks_like_max_turns(output) else ""
            if re.search(r"(?m)^\s*IMPLEMENTATION_STATUS:\s*BLOCKED\s*$", text):
                return {"kind": "IMPLEMENTATION_BLOCKED", "detail": text}
            return None
        except ClaudeExecutionError as exc:
            # Safety/integrity exceptions are deliberately NOT recoverable.
            check_safety()
            if exc.code == "PROVIDER_QUOTA":
                raise
            last_error = exc
            return {"kind": "IMPLEMENTATION_ERROR", "code": exc.code, "detail": str(exc)}

    def verify(previous_verification=None):
        progress("tests", "Running independent Verification with hang watchdog...")
        before = _review_fingerprint(_diff_for_review(worktree)[1])
        try:
            if previous_verification is not None:
                ok, text = True, previous_verification
            else:
                ok, text = _run_tests(worktree, args.test, args.test_timeout)
        except (OSError, OrchestratorError) as exc:
            ok, text = False, str(exc)
        check_safety()
        # Passing tests must describe the same code that was submitted to them.
        if ok and _review_fingerprint(_diff_for_review(worktree)[1]) != before:
            raise OrchestratorError("worktree changed during Verification")
        _write_log(run_dir, f"round-{round_no:02d}-tests.txt", text)
        result_payload["verification"] = {"passed": ok, "result": text}
        persist()
        if not ok:
            return {"kind": "TESTS_HANG" if "HANG/TIMEOUT" in text else "TESTS_FAIL", "detail": text}
        progress("final_review_gate", "Final Review Gate...")
        request = {
            "schema_version": 1, "run_id": run_id, "base_sha": baseline.head_sha,
            "task": task, "diff": _diff_for_review(worktree)[1], "verification": text,
            "recovery_iterations": round_no,
        }
        request["request_id"] = _review_fingerprint(json.dumps(request, sort_keys=True, ensure_ascii=False))
        _write_external_result(str(run_dir / "final-review-request.json"), request)
        decision = _final_review_gate(request, getattr(args, "final_review_decision", None))
        check_safety()
        assert_readonly(before, "Final Review Gate")
        result_payload["final_review"] = decision
        persist()
        if decision["verdict"] == "FAIL":
            args.final_review_decision = None  # Repair requires a fresh review.
            return {"kind": "FINAL_REVIEW_FAIL", "detail": decision["summary"]}
        if decision["verdict"] == "PENDING":
            return {"kind": "FINAL_REVIEW_PENDING", "detail": decision["summary"]}
        return None

    try:
        persist()
        if resumed:
            failure = verify(saved_request["verification"])
        else:
            failure = implement(_read_prompt("main_implementation.md", {"TASK": task}), "implementation")
            if failure is None:
                failure = verify()
        while failure is not None and failure["kind"] != "FINAL_REVIEW_PENDING":
            if round_no >= args.max_rounds:
                if args.max_rounds == 0 and last_error:
                    raise last_error
                raise ClaudeExecutionError("RECOVERY_LIMIT", "Recovery budget exhausted; no candidate")
            round_no += 1
            stat, diff = _diff_for_review(worktree)
            before = _review_fingerprint(diff)
            entry = {"iteration": round_no, "failure": failure, "diagnosis": None,
                     "repair": None, "verification": None, "progress": None,
                     "before_fingerprint": before}
            history.append(entry)
            progress("recovery_diagnosis", "Claude diagnosing the explicit failure...")
            prompt = _read_prompt("recovery_diagnosis.md", {
                "TASK": task, "FAILURE": json.dumps(failure, ensure_ascii=False),
                "DIFF": diff[:MAX_DIFF_CHARS], "HISTORY": json.dumps(history, ensure_ascii=False),
            })
            _write_log(run_dir, f"round-{round_no:02d}-diagnosis-prompt.md", prompt)
            counters.claude_calls += 1
            persist()
            raw = _run_claude_diagnosis(worktree, prompt, args.agent_timeout)
            _write_log(run_dir, f"round-{round_no:02d}-diagnosis-raw.json", raw.stdout + "\n" + raw.stderr)
            check_safety()
            assert_readonly(before, "Claude diagnosis")
            if _claude_quota_error(raw):
                raise ClaudeExecutionError("PROVIDER_QUOTA", "Claude quota exhausted; no retry")
            if raw.returncode or _claude_payload(raw).get("is_error"):
                raise ClaudeExecutionError("DIAGNOSIS_ERROR", "Claude diagnosis failed; see raw log")
            diagnosis = _claude_result_text(raw.stdout).strip()
            if not diagnosis:
                raise ClaudeExecutionError("DIAGNOSIS_ERROR", "empty diagnosis")
            entry["diagnosis"] = diagnosis
            persist()
            failure = implement(_read_prompt("recovery_repair.md", {
                "TASK": task, "FAILURE": json.dumps(entry["failure"], ensure_ascii=False),
                "DIAGNOSIS": diagnosis, "HISTORY": json.dumps(history, ensure_ascii=False),
            }), "recovery_repair")
            check_safety()
            after = _review_fingerprint(_diff_for_review(worktree)[1])
            entry["repair"] = {"after_fingerprint": after, "changed": before != after,
                               "log": f"round-{round_no:02d}-claude.txt"}
            if failure is None:
                failure = verify()
            entry["verification"] = failure or {"kind": "PASS"}
            signature = (_failure_fingerprint(entry["verification"]), after)
            repeated = any(tuple(previous.get("signature", ())) == signature for previous in history[:-1])
            same_failure = _failure_fingerprint(entry["failure"]) == signature[0]
            entry["signature"] = list(signature)
            entry["progress"] = failure is None or (not repeated and (before != after or not same_failure))
            persist()
            if failure and failure["kind"] != "FINAL_REVIEW_PENDING" and not entry["progress"]:
                raise ClaudeExecutionError("RECOVERY_NO_PROGRESS", "Repeated failure and unchanged/repeated repair; stopped")
        if failure:
            result_payload.update(status="review_pending")
            progress("final_review_pending", failure["detail"])
            return 0
        review = Review("approve", result_payload["final_review"]["summary"], ())
        check_safety()
        return create_candidate(round_no, review)
    except Exception as exc:
        result_payload.update(
            {
                "status": "stopped",
                "error": str(exc),
                "error_code": getattr(exc, "code", "ORCHESTRATOR_ERROR"),
                "claude_calls": counters.claude_calls,
                "codex_calls": counters.codex_calls,
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
            stage="stopped",
            round_no=round_no,
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
        if result_payload.get("status") == "candidate_ready" and parent is not None:
            try:
                _git(
                    baseline.root,
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree),
                    timeout=300,
                )
                shutil.rmtree(parent, ignore_errors=True)
            except OrchestratorError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude implementation with failure-only Recovery and Final Review Gate"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check git / claude CLI and billing guard")

    run_parser = sub.add_parser(
        "run",
        help="investigate, design, develop in an isolated worktree, and stop at candidate",
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
        help=f"maximum Recovery iterations (normal path consumes zero) (default {DEFAULT_MAX_ROUNDS})",
    )
    run_parser.add_argument(
        "--review-model",
        default=DEFAULT_REVIEW_MODEL,
        help="legacy compatibility option; does not invoke a reviewer",
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
    run_parser.add_argument("--resume-review", help="resume preserved review_pending run with unchanged TaskSpec, tests and budget")
    run_parser.add_argument("--final-review-decision", help="external JSON verdict bound to final-review-request request_id")
    run_parser.add_argument("--agent-timeout", type=int, default=DEFAULT_TIMEOUT)
    run_parser.add_argument("--test-timeout", type=int, default=DEFAULT_TEST_TIMEOUT)
    run_parser.add_argument("--no-fetch", action="store_true", help="skip origin fetch (not recommended)")
    return parser


def _configure_utf8_stdio() -> None:
    """Match DCC's UTF-8 pipe reader, including direct Windows CLI launches."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        if args.max_rounds < 0 or args.max_rounds > 30:
            raise OrchestratorError("--max-rounds must be between 0 and 30")
        return run(args)
    except (OSError, OrchestratorError) as exc:
        print(f"AI ORCHESTRATOR STOPPED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
