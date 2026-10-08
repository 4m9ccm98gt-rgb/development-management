"""Shared primitives for the AI Orchestrator: errors, paths, atomic JSON, process control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import locale
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Protocol


class OrchestratorError(RuntimeError):
    """Fail-closed orchestration error."""

    code = "ORCHESTRATOR_ERROR"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class StopRequested(OrchestratorError):
    """The user asked for a safe stop; provider / test children are already terminated."""

    code = "USER_SAFETY_STOP"


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


# --- child output decoding -------------------------------------------------------
#
# Children are asked to write UTF-8 (PYTHONUTF8 / PYTHONIOENCODING; git and the node-based
# Claude / Codex CLIs do so natively). Windows console programs (cmd.exe's own messages,
# taskkill, icacls, Windows PowerShell 5.1 writing to a pipe) still write the OEM code page
# (cp932 on Japanese Windows) and can not be switched without a console. One stream can
# carry both, so every line is decoded on its own: UTF-8 first, then the OEM code page;
# only bytes that neither can read are replaced.

_LEGACY_ENCODING: str | None = None


def legacy_output_encoding() -> str:
    """Encoding of Windows console-program output written to a pipe (the OEM code page)."""
    global _LEGACY_ENCODING
    if _LEGACY_ENCODING is None:
        encoding = "utf-8"
        if os.name == "nt":
            try:
                import ctypes

                encoding = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
                "".encode(encoding)
            except (AttributeError, OSError, LookupError):
                encoding = locale.getpreferredencoding(False) or "utf-8"
        _LEGACY_ENCODING = encoding
    return _LEGACY_ENCODING


def decode_output(data: bytes) -> str:
    """Decode one line (or block) of child output; never raises."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    legacy = legacy_output_encoding()
    if legacy.replace("-", "").lower() != "utf8":
        try:
            return data.decode(legacy)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def _newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class OutputDecoder:
    """Incremental, line-wise `decode_output` for streamed output (universal newlines).

    A partial last line is released as soon as it is complete UTF-8 (prompts / progress stay
    visible); otherwise it waits for its newline so a split multibyte character is never
    decoded in halves. `limit` bounds that wait."""

    def __init__(self, limit: int = 65536):
        self._pending = b""
        self._limit = limit

    def decode(self, data: bytes, final: bool = False) -> str:
        buffer = self._pending + data
        self._pending = b""
        if not final and buffer.endswith(b"\r"):
            buffer, self._pending = buffer[:-1], b"\r"  # the \n of a \r\n may arrive with the next read
        cut = max(buffer.rfind(b"\n"), buffer.rfind(b"\r")) + 1
        complete, rest = buffer[:cut], buffer[cut:]
        parts = [decode_output(line) for line in complete.splitlines(keepends=True)]
        if rest:
            try:
                parts.append(rest.decode("utf-8"))
            except UnicodeDecodeError:
                if final or len(rest) >= self._limit:
                    parts.append(decode_output(rest))
                else:
                    self._pending = rest + self._pending
        return _newlines("".join(parts))


def now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def state_root() -> Path:
    override = os.environ.get("AI_ORCHESTRATOR_STATE_ROOT")
    if override:
        return Path(override)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "ShizenDev" / "AIOrchestrator"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "shizen-ai-orchestrator"
    return Path.home() / ".local" / "state" / "shizen-ai-orchestrator"


def slugify(value: str, limit: int = 42) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return (text or "task")[:limit].rstrip("-._")


def resolved_command(name: str) -> list[str]:
    resolved = shutil.which(name)
    if not resolved:
        raise OrchestratorError(f"required command not found: {name}", "COMMAND_NOT_FOUND")
    path = Path(resolved)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", str(path)]
    return [str(path)]


def resolved_command_kind(name: str) -> str:
    """Which file type `name` resolves to on PATH, as `resolved_command` would launch it (DCC
    Task 14.4.1 diagnostic logging): the resolved executable's own suffix, never its path --
    a silent crash that leaves every other field empty still leaves this one fact. "" when
    `name` is not found at all."""
    resolved = shutil.which(name)
    if not resolved:
        return ""
    return Path(resolved).suffix.lower() or "(no-ext)"


# --- atomic JSON --------------------------------------------------------------

def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    last: Exception | None = None
    for attempt in range(20):
        try:
            os.replace(temp, path)
            return
        except PermissionError as exc:  # a reader holds the file open (Windows)
            last = exc
            time.sleep(0.02 * (attempt + 1))
    try:
        temp.unlink()
    except OSError:
        pass
    raise OSError(f"could not replace {path}: {last}")


def read_json(path: Path) -> dict | None:
    """Best-effort read; a partially written or missing file yields None."""
    for attempt in range(4):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.03 * (attempt + 1))
            continue
        return value if isinstance(value, dict) else None
    return None


# --- process identity / tree control -----------------------------------------

def process_start_token(pid: int) -> str | None:
    """Stable creation-time token of a *live* process, or None when it is gone.

    PID alone is never proof of identity (PIDs are reused); callers compare this
    token against the value recorded when the process was started.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None  # 259 = STILL_ACTIVE
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        pass
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False)
    except OSError:
        return None
    text = out.stdout.strip()
    return text or None


def pid_matches(pid: int, token: str | None) -> bool:
    return bool(token) and process_start_token(pid) == token


def terminate_pid_tree(pid: int, token: str | None = None) -> bool:
    """Kill exactly this process tree. With `token`, refuse if the PID was reused."""
    if token is not None and not pid_matches(pid, token):
        return False
    if os.name == "nt":
        # The output is not used, and taskkill writes it in the OEM code page: never decode it.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        import signal

        try:
            os.killpg(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                return False
    return True


def terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    terminate_pid_tree(proc.pid)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class ChildRegistry(Protocol):
    def add(self, pid: int, label: str) -> None: ...
    def remove(self, pid: int) -> None: ...


@dataclass
class ProcessHooks:
    """How a child process reports into the owning run."""

    on_line: Callable[[str, str], None] | None = None  # (stream, line)
    stop: threading.Event | None = None
    registry: ChildRegistry | None = None
    label: str = ""


def run_streaming(
    args: list[str] | str,
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int,
    env: dict[str, str] | None = None,
    hooks: ProcessHooks | None = None,
) -> CommandResult:
    """Run a child, streaming lines to `hooks.on_line`, honouring stop and timeout.

    On stop or timeout the child's whole tree is terminated before returning /
    raising, so a later repair can never overlap with leftover provider children.
    """
    hooks = hooks or ProcessHooks()
    program = args if isinstance(args, str) else args[0]
    try:
        proc = subprocess.Popen(
            args, cwd=str(cwd) if cwd else None,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,  # bytes: see decode_output
            start_new_session=(os.name != "nt"), env=env,
        )
    except OSError as exc:
        raise OrchestratorError(f"failed to start {program}: {exc}", "PROCESS_START_FAILED") from exc
    if hooks.registry is not None:
        hooks.registry.add(proc.pid, hooks.label or Path(program.split()[0]).name)
    chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}

    def pump(stream_name: str, stream) -> None:
        try:
            for raw in iter(stream.readline, b""):
                text = _newlines(decode_output(raw))  # line by line: the encoding may differ per line
                chunks[stream_name].append(text)
                if hooks.on_line:
                    for line in text.splitlines():
                        try:
                            hooks.on_line(stream_name, line)
                        except Exception:  # noqa: BLE001 - logging must never kill the reader
                            pass
        except (OSError, ValueError):
            pass

    def feed() -> None:
        try:
            if input_text is not None:
                proc.stdin.write(input_text.encode("utf-8"))
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    threads = [
        threading.Thread(target=pump, args=("stdout", proc.stdout), daemon=True),
        threading.Thread(target=pump, args=("stderr", proc.stderr), daemon=True),
        threading.Thread(target=feed, daemon=True),
    ]
    for thread in threads:
        thread.start()
    started = time.monotonic()
    try:
        while proc.poll() is None:
            if hooks.stop is not None and hooks.stop.is_set():
                terminate_process_tree(proc)
                raise StopRequested("safe stop requested; child process tree terminated")
            if time.monotonic() - started >= timeout:
                terminate_process_tree(proc)
                for thread in threads[:2]:
                    thread.join(timeout=5)
                timeout_error = OrchestratorError(
                    f"command timed out after {timeout}s: {program}", "COMMAND_TIMEOUT")
                timeout_error.partial_output = "".join(chunks["stdout"]) + "".join(chunks["stderr"])
                raise timeout_error
            try:
                proc.wait(timeout=0.1)  # returns the moment the child exits; the timeout is only the stop / deadline poll
            except subprocess.TimeoutExpired:
                pass
    finally:
        if proc.poll() is None:
            terminate_process_tree(proc)
        for thread in threads[:2]:
            thread.join(timeout=5)
        for stream in (proc.stdout, proc.stderr, proc.stdin):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        if hooks.registry is not None:
            hooks.registry.remove(proc.pid)
    return CommandResult((args,) if isinstance(args, str) else tuple(args), proc.returncode, "".join(chunks["stdout"]), "".join(chunks["stderr"]))


def git(repo: Path, *args: str, timeout: int = 120) -> CommandResult:
    result = run_streaming([*resolved_command("git"), "-C", str(repo), *args], timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OrchestratorError(f"git {' '.join(args)} failed: {detail}", "GIT_FAILED")
    return result
