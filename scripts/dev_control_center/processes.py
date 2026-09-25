"""Hidden, non-interactive subprocess transport shared by DCC workers."""
from __future__ import annotations

import codecs
import io
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Callable


def hidden_options() -> dict:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startup}


def console_python() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return str(executable)


def child_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               PIP_NO_INPUT="1", GIT_TERMINAL_PROMPT="0", DOTNET_NOLOGO="1")
    if extra:
        for key, value in extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    return env


def stream(command: list[str], *, cwd: Path, emit: Callable[[str], None], env: dict | None = None,
           cancel: threading.Event | None = None) -> int:
    """Run off the UI thread; emit even partial lines and drain before returning rc."""
    with subprocess.Popen(command, cwd=cwd, env=child_env(env), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                          **hidden_options()) as process:
        def stop_when_requested():
            while process.poll() is None:
                if cancel.wait(0.1):
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_options())
                    else:
                        process.terminate()
                    return

        monitor = None
        if cancel is not None:
            monitor = threading.Thread(target=stop_when_requested, daemon=True)
            monitor.start()
        decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder("utf-8")(errors="replace"), translate=True)
        while True:
            data = process.stdout.read(4096)
            if not data:
                break
            text = decoder.decode(data)
            if text:
                emit(text)
        final = decoder.decode(b"", final=True)
        if final:
            emit(final)
        rc = process.wait()
        if monitor is not None:
            monitor.join(timeout=1)
        return rc


def forward(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def checked(command: list[str], *, cwd: Path, env: dict | None = None) -> None:
    rc = stream(command, cwd=cwd, env=env, emit=forward)
    if rc:
        raise subprocess.CalledProcessError(rc, command)


def powershell(script: Path, *args: str) -> list[str]:
    return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
