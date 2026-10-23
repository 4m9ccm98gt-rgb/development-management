"""DCC Task UI-C: whether DCC opens the Orchestrator window once, automatically, right after its
own startup finishes. Same settings convention as reports_auto.AutoModeConfig: a tiny JSON file
under this module's own %LOCALAPPDATA%\\ShizenDev\\DCC\\startup_display\\ root, read with every
error degrading to the default (here: ON, unlike reports_auto's OFF default) instead of raising,
written atomically. This module only loads/saves the setting -- App._show_orchestrator_on_startup
(app.py) is the only caller and must never let a read failure block DCC's own startup.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile


def _root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "startup_display"


def settings_path() -> Path:
    return _root() / "config.json"


@dataclass(frozen=True)
class StartupDisplaySettings:
    """show_orchestrator: open the Orchestrator window once, after DCC's own startup finishes
    (初期値ON)。OFFなら自動では開かない。"""

    show_orchestrator: bool = True


def load_startup_display_settings(path: Path | None = None) -> StartupDisplaySettings:
    """Never raises: a missing or unreadable/corrupt file degrades to the ON default."""
    target = path if path is not None else settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return StartupDisplaySettings()
    if not isinstance(data, dict):
        return StartupDisplaySettings()
    return StartupDisplaySettings(show_orchestrator=bool(data.get("show_orchestrator", True)))


def save_startup_display_settings(settings: StartupDisplaySettings, path: Path | None = None) -> None:
    target = path if path is not None else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"show_orchestrator": settings.show_orchestrator}, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
