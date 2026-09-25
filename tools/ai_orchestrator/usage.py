"""Provider usage adapters (auxiliary information only).

Two different things are kept structurally apart and never merged:

* ``account``: plan / rate-limit window / credit state of the *account*.
* ``context``: token use of a *session / call* against the model's context window.

Only values the provider itself reported are stored. A missing value is shown as
``取得不能`` with a reason; an old value is shown as ``last known``. Usage lookups
never fail or stop a run, hold no credentials, and never decide quota (the real
provider response is the only authority for that).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import time
from typing import Callable

from .common import (
    OrchestratorError, ProcessHooks, read_json, resolved_command, run_streaming, state_root,
    terminate_process_tree, write_json_atomic,
)

FRESH_SECONDS = 180          # older than this is shown as "last known"
LOW_REMAINING_PERCENT = 15.0
MIN_PROBE_INTERVAL = {"claude": 600, "codex": 45}   # be gentle with the providers
UNAVAILABLE = "取得不能"


def usage_dir() -> Path:
    return state_root() / "usage"


class UsageProvider:
    name = ""
    display = ""

    def __init__(self, directory: Path | None = None, clock: Callable[[], float] = time.time):
        self._dir = directory
        self._clock = clock

    @property
    def path(self) -> Path:
        return (self._dir or usage_dir()) / f"{self.name}.json"

    # --- storage: {"account": {...}|None, "context": {...}|None, "errors": {...}} ---
    def load(self) -> dict:
        data = read_json(self.path) or {}
        return {"provider": self.name, "account": data.get("account"), "context": data.get("context"),
                "errors": data.get("errors") or {}, "last_attempt": data.get("last_attempt")}

    def _save(self, data: dict) -> None:
        try:
            write_json_atomic(self.path, data)
        except OSError:
            pass  # auxiliary information: a failed cache write must never matter

    def record_account(self, account: dict | None, error: str = "") -> dict:
        data = self.load()
        if account is not None:
            data["account"] = {**account, "observed_at": self._clock()}
            data["errors"].pop("account", None)
        elif error:
            data["errors"]["account"] = error
        self._save(data)
        return data

    def record_context(self, context: dict | None, error: str = "") -> dict:
        data = self.load()
        if context is not None:
            data["context"] = {**context, "observed_at": self._clock()}
            data["errors"].pop("context", None)
        elif error:
            data["errors"]["context"] = error
        self._save(data)
        return data

    def ingest(self, result) -> None:
        """Absorb facts a real Main / Reviewer call reported. No extra provider call."""
        raise NotImplementedError

    def refresh(self, *, force: bool = False) -> dict:
        """Ask the provider for the account state. Never raises; rate limited."""
        data = self.load()
        now = self._clock()
        last = data.get("last_attempt") or 0
        if not force and now - last < MIN_PROBE_INTERVAL.get(self.name, 60):
            return data
        if force and now - last < min(MIN_PROBE_INTERVAL.get(self.name, 60), 60) / 2:
            return data  # even a forced refresh is debounced
        data["last_attempt"] = now
        self._save(data)
        try:
            self._probe()
        except Exception as exc:  # noqa: BLE001 - usage is auxiliary; report, don't propagate
            self.record_account(None, f"{type(exc).__name__}: {exc}"[:300])
        return self.load()

    def _probe(self) -> None:
        raise NotImplementedError


class ClaudeUsageProvider(UsageProvider):
    """Claude Code reports rate-limit windows only inside a real call (stream-json
    ``rate_limit_event``); there is no free query. So values come from the run's own
    calls, plus an explicit, throttled one-token probe."""

    name = "claude"
    display = "Claude"

    def ingest(self, result) -> None:
        if getattr(result, "provider", "") != self.name:
            return
        account = self.account_from_rate_limit(result.rate_limit)
        if account:
            self.record_account(account)
        if result.context:
            self.record_context(result.context)

    @staticmethod
    def account_from_rate_limit(info: dict | None) -> dict | None:
        if not isinstance(info, dict):
            return None
        windows = []
        unified = info.get("unifiedWindows")
        if isinstance(unified, dict):
            for key, label in (("five_hour", "5時間枠"), ("seven_day", "週間枠")):
                win = unified.get(key)
                if isinstance(win, dict) and isinstance(win.get("utilization"), (int, float)):
                    windows.append({"key": key, "label": label,
                                    "used_percent": round(float(win["utilization"]) * 100, 1),
                                    "resets_at": win.get("resetsAt")})
        elif isinstance(info.get("utilization"), (int, float)):
            windows.append({"key": str(info.get("rateLimitType", "window")), "label": str(info.get("rateLimitType", "window")),
                            "used_percent": round(float(info["utilization"]) * 100, 1), "resets_at": info.get("resetsAt")})
        if not windows:
            return None
        return {"source": "claude stream-json rate_limit_event", "windows": windows,
                "status": info.get("status"), "credits": None, "plan": None}

    def _probe(self) -> None:
        # One minimal call, outside any project (no CLAUDE.md), nothing persisted.
        empty_mcp = Path(tempfile.gettempdir()) / "ai-orchestrator-empty-mcp.json"
        empty_mcp.write_text('{"mcpServers":{}}', encoding="utf-8")
        result = run_streaming(
            [*resolved_command("claude"), "-p", "--output-format", "stream-json", "--verbose",
             "--max-turns", "1", "--tools", "", "--no-session-persistence", "--disable-slash-commands",
             "--strict-mcp-config", "--mcp-config", str(empty_mcp)],
            cwd=Path(tempfile.gettempdir()), input_text="Reply with exactly: OK", timeout=90,
            hooks=ProcessHooks(label="claude-usage-probe"),
        )
        from .providers import ClaudeProvider

        parsed = ClaudeProvider.parse("probe", result)
        account = self.account_from_rate_limit(parsed.rate_limit)
        if account:
            self.record_account(account)
        else:
            self.record_account(None, "Claudeがrate limit情報を返しませんでした" + (f": {parsed.error_detail}" if parsed.error_detail else ""))


class CodexUsageProvider(UsageProvider):
    """`codex app-server` JSON-RPC `account/rateLimits/read` returns the account
    windows, reset times and credit state without spending any tokens."""

    name = "codex"
    display = "Codex"

    def ingest(self, result) -> None:
        if getattr(result, "provider", "") != self.name or not result.context:
            return
        used = result.context.get("used_tokens")
        window = self._context_window()
        context = {"used_tokens": used, "window_tokens": window, "model": self._configured_model()}
        self.record_context(context)

    @staticmethod
    def _configured_model() -> str | None:
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        try:
            for line in (home / "config.toml").read_text(encoding="utf-8").splitlines():
                if line.startswith("["):
                    break  # only the top-level table; nothing else is read
                match = re.match(r'\s*model\s*=\s*"([^"]+)"', line)
                if match:
                    return match.group(1)
        except OSError:
            pass
        return None

    def _context_window(self) -> int | None:
        model = self._configured_model()
        if not model:
            return None
        try:
            result = run_streaming([*resolved_command("codex"), "debug", "models"], timeout=30,
                                   hooks=ProcessHooks(label="codex-models"))
            catalog = json.loads(result.stdout)
        except (OrchestratorError, ValueError):
            return None
        models = catalog.get("models", catalog) if isinstance(catalog, dict) else catalog
        for item in models if isinstance(models, list) else []:
            if isinstance(item, dict) and item.get("slug") == model and item.get("context_window"):
                percent = item.get("effective_context_window_percent") or 100
                return int(int(item["context_window"]) * percent / 100)
        return None

    def _probe(self) -> None:
        account = self.read_rate_limits()
        self.record_account(account)

    @staticmethod
    def account_from_response(result: dict) -> dict:
        snapshot = result.get("rateLimits") or {}
        windows = []
        for key, label in (("primary", "5時間枠"), ("secondary", "週間枠")):
            win = snapshot.get(key)
            if isinstance(win, dict) and isinstance(win.get("usedPercent"), (int, float)):
                minutes = win.get("windowDurationMins")
                if minutes:
                    label = f"{int(minutes) // 60}時間枠" if minutes < 1440 else f"{round(int(minutes) / 1440)}日枠"
                windows.append({"key": key, "label": label, "used_percent": float(win["usedPercent"]),
                                "resets_at": win.get("resetsAt")})
        credits = snapshot.get("credits")
        credit = None
        if isinstance(credits, dict):
            credit = {"has_credits": credits.get("hasCredits"), "unlimited": credits.get("unlimited"),
                      "balance": credits.get("balance")}
        return {"source": "codex app-server account/rateLimits/read", "windows": windows,
                "credits": credit, "plan": snapshot.get("planType"),
                "ordinary_usage_allowed": result.get("ordinaryUsageAllowed")}

    def read_rate_limits(self, timeout: float = 25.0) -> dict:
        import subprocess

        command = [*resolved_command("codex"), "app-server", "--stdio"]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                start_new_session=(os.name != "nt"))
        lines: queue.Queue = queue.Queue()

        def pump() -> None:
            try:
                for line in proc.stdout:
                    lines.put(line)
            except (OSError, ValueError):
                pass
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()

        def send(payload: dict) -> None:
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()

        def wait_for(request_id: int) -> dict:
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise OrchestratorError("codex app-server did not answer in time")
                try:
                    line = lines.get(timeout=left)
                except queue.Empty:
                    raise OrchestratorError("codex app-server did not answer in time") from None
                if line is None:
                    raise OrchestratorError("codex app-server exited early")
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get("id") == request_id:
                    if "error" in message:
                        raise OrchestratorError(f"codex app-server error: {message['error']}")
                    return message.get("result") or {}

        try:
            send({"id": 1, "method": "initialize",
                  "params": {"clientInfo": {"name": "dm-ai-orchestrator", "title": None, "version": "1"},
                             "capabilities": None}})
            wait_for(1)
            send({"method": "initialized"})
            send({"id": 2, "method": "account/rateLimits/read", "params": None})
            return self.account_from_response(wait_for(2))
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            terminate_process_tree(proc)  # the whole tree: node shim + codex.exe
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass


USAGE_PROVIDER_CLASSES = {cls.name: cls for cls in (ClaudeUsageProvider, CodexUsageProvider)}


def make_usage_provider(name: str, **kwargs) -> UsageProvider:
    return USAGE_PROVIDER_CLASSES[name](**kwargs)


# --- presentation (pure functions; the UI only formats what is here) ---------------

def _age_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}秒前"
    if seconds < 5400:
        return f"{seconds // 60}分前"
    return f"{seconds // 3600}時間前"


def _reset_text(epoch, now: float) -> str:
    if not isinstance(epoch, (int, float)):
        return UNAVAILABLE
    stamp = time.strftime("%m/%d %H:%M", time.localtime(epoch))
    return f"{stamp}（あと{_age_text(epoch - now).replace('前', '')}）" if epoch > now else f"{stamp}（リセット済みの可能性）"


def describe(data: dict, now: float | None = None) -> list[tuple[str, str]]:
    """Rows of (label, text). Account rows and Context rows are separate namespaces."""
    now = time.time() if now is None else now
    rows: list[tuple[str, str]] = []
    account = data.get("account")
    errors = data.get("errors") or {}
    if account:
        age = now - float(account.get("observed_at", 0))
        note = "" if age <= FRESH_SECONDS else f"  [last known {_age_text(age)}]"
        for win in account.get("windows") or []:
            used = win.get("used_percent")
            remaining = f"{max(0.0, 100 - used):.0f}% remaining" if isinstance(used, (int, float)) else UNAVAILABLE
            rows.append((f"Usage {win.get('label')}", remaining + note))
            rows.append((f"Reset {win.get('label')}", _reset_text(win.get("resets_at"), now)))
        credits = account.get("credits")
        if isinstance(credits, dict):
            if credits.get("unlimited"):
                rows.append(("Credits", "unlimited" + note))
            elif credits.get("balance") is not None:
                rows.append(("Credits", f"{credits['balance']}" + note))
            else:
                rows.append(("Credits", UNAVAILABLE))
        else:
            rows.append(("Credits", UNAVAILABLE))
        if account.get("plan"):
            rows.append(("Plan", str(account["plan"])))
    else:
        rows.append(("Usage", UNAVAILABLE + (f"（{errors['account']}）" if errors.get("account") else "（未取得）")))
    if errors.get("account") and account:
        rows.append(("Usage更新", f"失敗（last knownを表示）: {errors['account']}"))
    context = data.get("context")
    if context and isinstance(context.get("used_tokens"), int):
        age = now - float(context.get("observed_at", 0))
        note = "" if age <= FRESH_SECONDS else f"  [last known {_age_text(age)}]"
        window = context.get("window_tokens")
        if window:
            rows.append(("Context", f"{max(0.0, 100 - 100 * context['used_tokens'] / window):.0f}% remaining "
                                    f"({context['used_tokens']:,}/{window:,} tokens){note}"))
        else:
            rows.append(("Context", f"{context['used_tokens']:,} tokens 使用（window {UNAVAILABLE}）{note}"))
    else:
        rows.append(("Context", UNAVAILABLE + "（呼出し実績なし）"))
    return rows


def warnings(data: dict, role_label: str, now: float | None = None) -> list[str]:
    """Only from provider-reported account windows; never a reason to switch or stop."""
    now = time.time() if now is None else now
    account = data.get("account") or {}
    out = []
    for win in account.get("windows") or []:
        used = win.get("used_percent")
        if isinstance(used, (int, float)) and 100 - used < LOW_REMAINING_PERCENT:
            out.append(f"{role_label}の利用可能量が少ないため（{win.get('label')} 残り{max(0, 100 - used):.0f}%）、"
                       "長時間Taskを完走できない可能性があります。")
    return out
