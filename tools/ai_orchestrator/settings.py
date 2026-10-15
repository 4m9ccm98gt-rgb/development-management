"""Trusted, per-PC DCC Orchestrator settings (never read from tasks or reports)."""
from __future__ import annotations

import os
from pathlib import Path
import tomllib

from .common import OrchestratorError


def local_settings_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ShizenDev" / "DCC" / "orchestrator_local.toml"


def validate_codex_main_python(value: object) -> str:
    if not isinstance(value, str):
        raise OrchestratorError("codex_main_python must be a path string", "CODEX_MAIN_PYTHON_INVALID")
    if not value.strip():
        return ""
    try:
        path = Path(value.strip()).expanduser()
        if path.name.casefold() != "python.exe" or not path.is_file():
            raise ValueError("expected an existing python.exe file")
        return str(path.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise OrchestratorError("codex_main_python must name an existing python.exe file",
                                "CODEX_MAIN_PYTHON_INVALID") from exc


def load_codex_main_python(path: Path | None = None) -> str:
    target = local_settings_path() if path is None else path
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        raise OrchestratorError("cannot read DCC orchestrator_local.toml",
                                "CODEX_MAIN_PYTHON_CONFIG_INVALID") from exc
    section = data.get("orchestrator", {})
    if not isinstance(section, dict):
        raise OrchestratorError("[orchestrator] must be a table", "CODEX_MAIN_PYTHON_CONFIG_INVALID")
    return validate_codex_main_python(section.get("codex_main_python", ""))
