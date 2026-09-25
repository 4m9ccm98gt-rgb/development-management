"""Provider adapters. The engine only knows roles (main / review), never provider names.

Each adapter turns one non-interactive CLI call into an `AgentResult`, including
error classification (quota / auth / transient ...) and the usage facts the
provider itself reported during that call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile

from .common import (
    CommandResult, OrchestratorError, ProcessHooks, StopRequested, resolved_command, run_streaming,
)

CLAUDE_MAIN_MAX_TURNS = 12
CLAUDE_REVIEW_MAX_TURNS = 16
API_BILLING_ENV_VARS = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)

# Error kinds. Only "transient" is retried (bounded by the engine); everything else
# is reported to the run record and ends automatic operation.
ERR_QUOTA = "quota"
ERR_AUTH = "auth"
ERR_TRANSIENT = "transient"
ERR_TIMEOUT = "timeout"
ERR_PROCESS = "process"
ERR_PROTOCOL = "protocol"

# Non-interactive acceptEdits denies Bash unless allowed. Inspection, tests and
# interpreters only; git write commands are deliberately absent.
CLAUDE_ALLOWED_BASH_TOOLS: tuple[str, ...] = tuple(
    f"Bash({prefix}:*)"
    for prefix in (
        "git status", "git diff", "git log", "git show", "git ls-files", "git grep",
        "git rev-parse", "git branch --show-current", "python", "python3", "py", "pytest",
        "ruff", "ls", "dir", "cat", "head", "tail", "wc", "sed", "grep", "rg", "find",
        "sort", "diff", "pwd", "mkdir", "cp", "mv", "echo",
    )
)


@dataclass
class AgentResult:
    provider: str
    role: str
    ok: bool
    text: str = ""
    error_kind: str | None = None
    error_detail: str = ""
    session_id: str | None = None
    returncode: int = 0
    max_turns: bool = False
    raw: str = ""
    # Facts reported by the provider during this call (never guessed):
    rate_limit: dict | None = None   # Claude: rate_limit_event.rate_limit_info
    context: dict | None = None      # {"used_tokens", "window_tokens", "model"}
    events: list = field(default_factory=list)  # short human log lines already emitted


def agent_env() -> dict[str, str]:
    """Child-only Git safety overlay: `git push origin` receives an invalid push URL."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # Tests / agents must not litter the worktree with __pycache__
    env["AI_ORCHESTRATOR"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "remote.origin.pushurl"
    env["GIT_CONFIG_VALUE_0"] = "disabled://ai-orchestrator"
    return env


def active_api_billing_env() -> tuple[str, ...]:
    return tuple(name for name in API_BILLING_ENV_VARS if os.environ.get(name))


_QUOTA_RE = re.compile(
    r"credit balance (?:is )?too low|insufficient[_ ](?:quota|credits?)|"
    r"(?:quota|credits?)[^\n]{0,40}(?:exhausted|exceeded|depleted)|"
    r"(?:usage|spending|rate) limit|hit your (?:usage )?limit|"
    r"out of (?:extra usage|credits)|billing[_ ]error|error_max_budget_usd|"
    r"usage_limit_reached|rate_limit_exceeded|purchase more credits",
    re.IGNORECASE,
)
_TRANSIENT_RE = re.compile(
    r"another claude code process is refreshing|overloaded|\b52[0-9]\b|\b50[234]\b|"
    r"econnreset|etimedout|socket hang up|stream (?:disconnected|error)|"
    r"temporarily unavailable|connection (?:reset|refused|closed)|network error|"
    r"reconnecting|api_error",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"not logged in|please (?:run )?/?login|invalid[_ ]api[_ ]key|unauthori[sz]ed|"
    r"authentication[_ ]failed|token (?:has )?expired|refresh token|sign in again",
    re.IGNORECASE,
)


def classify_error(text: str) -> str:
    """Quota first (never retried), then transient, then auth, else a plain process error."""
    if _QUOTA_RE.search(text):
        return ERR_QUOTA
    if _TRANSIENT_RE.search(text):
        return ERR_TRANSIENT
    if _AUTH_RE.search(text):
        return ERR_AUTH
    return ERR_PROCESS


def _json_lines(stdout: str) -> list[dict]:
    items = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def _short(text: object, limit: int = 160) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


_SESSION_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


class Provider:
    name = ""
    display = ""
    supports_resume = False

    def run_main(self, worktree: Path, prompt: str, *, timeout: int, hooks: ProcessHooks,
                 session_id: str | None = None) -> AgentResult:
        raise NotImplementedError

    def run_review(self, worktree: Path, prompt: str, *, timeout: int, hooks: ProcessHooks) -> AgentResult:
        raise NotImplementedError

    def preflight(self) -> None:
        resolved_command(self.name)


class ClaudeProvider(Provider):
    name = "claude"
    display = "Claude"
    supports_resume = True

    def _main_command(self, session_id: str | None) -> list[str]:
        command = [
            *resolved_command("claude"), "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "acceptEdits",
            "--allowedTools", ",".join(CLAUDE_ALLOWED_BASH_TOOLS),
            "--max-turns", str(CLAUDE_MAIN_MAX_TURNS),
        ]
        if session_id is not None:
            if not _SESSION_UUID.fullmatch(session_id):
                raise OrchestratorError("invalid Claude session UUID", "SESSION_ID_UNAVAILABLE")
            command += ["--resume", session_id]
        return command

    def _review_command(self) -> list[str]:
        # Read-only capability set: no shell, editor, MCP or sub-agent tool.
        empty_mcp = Path(tempfile.gettempdir()) / "ai-orchestrator-empty-mcp.json"
        empty_mcp.write_text('{"mcpServers":{}}', encoding="utf-8")
        return [
            *resolved_command("claude"), "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "default", "--tools", "Read,Glob,Grep",
            "--allowedTools", "Read,Glob,Grep", "--max-turns", str(CLAUDE_REVIEW_MAX_TURNS),
            "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", str(empty_mcp),
        ]

    def run_main(self, worktree, prompt, *, timeout, hooks, session_id=None):
        return self._call("main", self._main_command(session_id), worktree, prompt, timeout, hooks)

    def run_review(self, worktree, prompt, *, timeout, hooks):
        return self._call("review", self._review_command(), worktree, prompt, timeout, hooks)

    def _call(self, role, command, worktree, prompt, timeout, hooks) -> AgentResult:
        events: list[str] = []
        live = hooks.on_line

        def relay(stream: str, line: str) -> None:
            summary = self._summarize_line(line) if stream == "stdout" else _short(line)
            if summary:
                events.append(summary)
                if live:
                    live(stream, summary)

        proc_hooks = ProcessHooks(on_line=relay, stop=hooks.stop, registry=hooks.registry, label=f"claude-{role}")
        try:
            result = run_streaming(command, cwd=worktree, input_text=prompt, timeout=timeout,
                                   env=agent_env(), hooks=proc_hooks)
        except StopRequested:
            raise
        except OrchestratorError as exc:
            kind = ERR_TIMEOUT if exc.code == "COMMAND_TIMEOUT" else ERR_PROCESS
            return AgentResult(self.name, role, False, error_kind=kind, error_detail=str(exc), events=events)
        return self.parse(role, result, events)

    @staticmethod
    def _summarize_line(line: str) -> str:
        try:
            item = json.loads(line)
        except ValueError:
            return ""
        if not isinstance(item, dict):
            return ""
        kind = item.get("type")
        if kind == "assistant":
            for part in (item.get("message") or {}).get("content") or []:
                if part.get("type") == "tool_use":
                    tool_input = part.get("input") or {}
                    target = tool_input.get("file_path") or tool_input.get("command") or tool_input.get("pattern") or ""
                    return _short(f"tool {part.get('name')} {target}")
                if part.get("type") == "text" and part.get("text", "").strip():
                    return _short(part["text"])
        elif kind == "system" and item.get("subtype") == "api_retry":
            return f"api_retry attempt={item.get('attempt')} status={item.get('error_status')}"
        return ""

    @staticmethod
    def parse(role: str, result: CommandResult, events: list[str] | None = None) -> AgentResult:
        items = _json_lines(result.stdout)
        final = next((i for i in reversed(items) if i.get("type") == "result"), {})
        rate = None
        context_tokens = None
        model = None
        for item in items:
            if item.get("type") == "rate_limit_event" and isinstance(item.get("rate_limit_info"), dict):
                rate = item["rate_limit_info"]
            elif item.get("type") == "system" and item.get("subtype") == "init":
                model = item.get("model") or model
            elif item.get("type") == "assistant" and not item.get("parent_tool_use_id"):
                usage = (item.get("message") or {}).get("usage") or {}
                total = sum(int(usage.get(k) or 0) for k in (
                    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
                if total:
                    context_tokens = total
                model = (item.get("message") or {}).get("model") or model
        window = None
        for name, usage in (final.get("modelUsage") or {}).items():
            if isinstance(usage, dict) and usage.get("contextWindow"):
                window = int(usage["contextWindow"])
                model = model or name
        context = None
        if context_tokens is not None and window:
            context = {"used_tokens": context_tokens, "window_tokens": window, "model": model}
        session = final.get("session_id")
        if not (isinstance(session, str) and _SESSION_UUID.fullmatch(session)):
            session = None
        common = dict(provider="claude", role=role, session_id=session.lower() if session else None,
                      returncode=result.returncode, raw=result.stdout + "\n" + result.stderr,
                      rate_limit=rate, context=context, events=events or [])
        max_turns = final.get("subtype") == "error_max_turns" or "maximum number of turns" in (
            json.dumps(final.get("errors", "")) + result.stderr).lower()
        if max_turns:
            return AgentResult(ok=False, max_turns=True, error_kind=ERR_PROCESS,
                               error_detail="Claude reached max-turns", **common)
        failed = bool(result.returncode) or bool(final.get("is_error")) or not final
        if failed:
            text = "\n".join([str(final.get("subtype", "")), str(final.get("errors", "")),
                              str(final.get("result", "")), result.stderr] +
                             ([] if final else [result.stdout[-2000:]]))
            kind = classify_error(text)
            if kind == ERR_PROCESS and not final:
                kind = ERR_PROTOCOL
            if rate and str(rate.get("status", "allowed")) not in ("allowed", "allowed_warning") and kind != ERR_QUOTA:
                kind = ERR_QUOTA
            return AgentResult(ok=False, error_kind=kind,
                               error_detail=_short(text.strip() or f"rc={result.returncode}", 500), **common)
        answer = final.get("result")
        if not isinstance(answer, str) or not answer.strip():
            return AgentResult(ok=False, error_kind=ERR_PROTOCOL, error_detail="Claude returned no result text", **common)
        return AgentResult(ok=True, text=answer.strip(), **common)


class CodexProvider(Provider):
    name = "codex"
    display = "Codex"
    supports_resume = False

    def _command(self, worktree: Path, sandbox: str, ephemeral: bool = True) -> list[str]:
        command = [*resolved_command("codex"), "exec", "--json", "--sandbox", sandbox, "-C", str(worktree)]
        if ephemeral:
            command.append("--ephemeral")
        command.append("-")
        return command

    def run_main(self, worktree, prompt, *, timeout, hooks, session_id=None):
        return self._call("main", self._command(worktree, "workspace-write"), worktree, prompt, timeout, hooks)

    def run_review(self, worktree, prompt, *, timeout, hooks):
        return self._call("review", self._command(worktree, "read-only"), worktree, prompt, timeout, hooks)

    def _call(self, role, command, worktree, prompt, timeout, hooks) -> AgentResult:
        events: list[str] = []
        live = hooks.on_line

        def relay(stream: str, line: str) -> None:
            summary = self._summarize_line(line) if stream == "stdout" else _short(line)
            if summary:
                events.append(summary)
                if live:
                    live(stream, summary)

        proc_hooks = ProcessHooks(on_line=relay, stop=hooks.stop, registry=hooks.registry, label=f"codex-{role}")
        try:
            result = run_streaming(command, cwd=worktree, input_text=prompt, timeout=timeout,
                                   env=agent_env(), hooks=proc_hooks)
        except StopRequested:
            raise
        except OrchestratorError as exc:
            kind = ERR_TIMEOUT if exc.code == "COMMAND_TIMEOUT" else ERR_PROCESS
            return AgentResult(self.name, role, False, error_kind=kind, error_detail=str(exc), events=events)
        return self.parse(role, result, events)

    @staticmethod
    def _summarize_line(line: str) -> str:
        try:
            item = json.loads(line)
        except ValueError:
            return ""
        if not isinstance(item, dict):
            return ""
        kind = item.get("type")
        if kind == "item.completed":
            inner = item.get("item") or {}
            if inner.get("type") == "agent_message":
                return _short(inner.get("text", ""))
            if inner.get("type") == "command_execution":
                return _short(f"command {inner.get('command', '')}")
            if inner.get("type") == "file_change":
                return _short("file_change " + ", ".join(
                    str(c.get("path", "")) for c in inner.get("changes", []) if isinstance(c, dict)))
        elif kind in {"turn.failed", "error"}:
            return _short(f"{kind} {json.dumps(item, ensure_ascii=False)}")
        return ""

    @staticmethod
    def parse(role: str, result: CommandResult, events: list[str] | None = None) -> AgentResult:
        items = _json_lines(result.stdout)
        messages = [i["item"]["text"] for i in items
                    if i.get("type") == "item.completed" and (i.get("item") or {}).get("type") == "agent_message"
                    and isinstance(i["item"].get("text"), str)]
        errors = [json.dumps(i, ensure_ascii=False) for i in items if i.get("type") in {"turn.failed", "error"}]
        completed = any(i.get("type") == "turn.completed" for i in items)
        used = None
        for item in items:
            if item.get("type") == "turn.completed" and isinstance(item.get("usage"), dict):
                used = int(item["usage"].get("input_tokens") or 0) + int(item["usage"].get("output_tokens") or 0)
        context = {"used_tokens": used, "window_tokens": None, "model": None} if used else None
        common = dict(provider="codex", role=role, returncode=result.returncode,
                      raw=result.stdout + "\n" + result.stderr, context=context, events=events or [])
        # Transient `error` events (e.g. stream reconnect notices) are fine when the turn completed.
        if result.returncode or not completed:
            text = "\n".join(errors + [result.stderr] + ([] if items else [result.stdout[-2000:]]))
            kind = classify_error(text)
            if kind == ERR_PROCESS and not items:
                kind = ERR_PROTOCOL
            return AgentResult(ok=False, error_kind=kind,
                               error_detail=_short(text.strip() or f"rc={result.returncode}", 500), **common)
        if not messages or not messages[-1].strip():
            return AgentResult(ok=False, error_kind=ERR_PROTOCOL, error_detail="Codex returned no message", **common)
        return AgentResult(ok=True, text=messages[-1].strip(), **common)


PROVIDER_CLASSES = {cls.name: cls for cls in (ClaudeProvider, CodexProvider)}


def _load_extra_providers() -> None:
    """Extension point for tests / future providers: a Python file exposing PROVIDERS = [Provider subclasses].

    Only active when AI_ORCHESTRATOR_EXTRA_PROVIDERS names a file; the detached worker inherits the
    variable, so lifecycle tests can run real worker processes without any paid AI."""
    path = os.environ.get("AI_ORCHESTRATOR_EXTRA_PROVIDERS")
    if not path:
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location("ai_orchestrator_extra_providers", path)
    if spec is None or spec.loader is None:
        raise OrchestratorError(f"cannot load extra providers: {path}", "EXTRA_PROVIDERS_INVALID")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for cls in getattr(module, "PROVIDERS", []):
        PROVIDER_CLASSES[cls.name] = cls


_load_extra_providers()
PROVIDER_NAMES = tuple(PROVIDER_CLASSES)
DEFAULT_MAIN_AGENT = "claude"
DEFAULT_REVIEW_AGENT = "codex"


def make_provider(name: str) -> Provider:
    try:
        return PROVIDER_CLASSES[name]()
    except KeyError:
        raise OrchestratorError(f"unknown provider: {name!r} (choose from {', '.join(PROVIDER_NAMES)})",
                                "UNKNOWN_PROVIDER") from None


def validate_roles(main_agent: str, review_agent: str, *, allow_same: bool = False) -> None:
    for name in (main_agent, review_agent):
        make_provider(name)
    if main_agent == review_agent and not allow_same:
        raise OrchestratorError(
            "Main AI and Reviewer AI must be different providers for an independent review",
            "SAME_PROVIDER_ROLES")
