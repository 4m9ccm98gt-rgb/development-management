"""DCC-only, non-interactive adapters. Manual CMD launchers remain untouched.

Known adapters call the same application bodies and prerequisite checks as the
audited manual launchers. Unknown repositories must declare dcc_entrypoints.json;
there is deliberately no fallback to a potentially interactive CMD file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from . import processes


PYTHON_RUNS = {
    "next-day-setup": (".", "import openpyxl; import reportlab; import PIL", ["dinner_system/hotel_app_entry.py"]),
    "food-cost-calculation-system": (".", "import PySide6; import cv2; import PIL; import pytesseract; import flask; import qrcode", ["-m", "food_cost_app.main"]),
    "inventory-reconciliation-system": (".", "import openpyxl", ["room_inventory_reconcile.py"]),
    "qr-supply-ordering-system": (".", "import flask", ["run.py"]),
    "beverage-inventory-ordering-system": ("python_app", "import PySide6; assert PySide6.__version__.startswith('6.8.')", ["app.py"]),
}
BUILDS = {"next-day-setup", "food-cost-calculation-system", "menu-sheet-generator", "beverage-inventory-ordering-system"}
MENU_FILES = ("MenuPrinterWpf.exe", "MenuPrinterWpf.dll", "official_vertical_logo_trimmed.png", "tenyu_stamp.png")


def _local(repo: Path, relative: str) -> Path:
    path = repo / relative
    if not path.resolve().is_relative_to(repo.resolve()):
        raise ValueError("DCC entrypoint must stay inside its repository")
    for component in (path, *path.parents):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError("DCC entrypoint cannot traverse a link")
    return path


def declared(repo: Path, action: str, *, artifact: Path | None = None, target: Path | None = None) -> tuple[list[str], Path] | None:
    manifest = repo / "dcc_entrypoints.json"
    if not manifest.is_file():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if data.get("schema") != 1:
        raise ValueError("dcc_entrypoints.json: unsupported schema")
    spec = data.get(action)
    if spec is None:
        return None
    script = _local(repo, spec["script"])
    cwd = _local(repo, spec.get("cwd", "."))
    if not script.is_file() or not cwd.is_dir():
        raise ValueError("DCC entrypoint / cwd is missing")
    values = {"repo": str(repo), "artifact": str(artifact or ""), "target": str(target or "")}
    args = [arg.format_map(values) for arg in spec.get("args", [])]
    if script.suffix.lower() == ".py":
        interpreter = spec.get("python")
        python = str(_local(repo, interpreter)) if interpreter else processes.console_python()
        return [python, "-u", str(script), *args], cwd
    if script.suffix.lower() == ".ps1":
        return processes.powershell(script, *args), cwd
    raise ValueError("DCC entrypoints must be non-interactive Python or PowerShell bodies, not CMD wrappers")


def supported(repo: Path, action: str) -> bool:
    if declared(repo, action) is not None:
        return True
    if action == "run":
        return repo.name in PYTHON_RUNS or repo.name in {"development-management", "menu-sheet-generator"}
    return action == "build" and repo.name in BUILDS


def _check(command: list[str], cwd: Path, env: dict | None = None) -> None:
    print("[DCC] " + " ".join(command), flush=True)
    processes.checked(command, cwd=cwd, env=env)


def _venv(folder: Path, *, create: bool) -> Path:
    python = folder / ".venv" / "Scripts" / "python.exe"
    if not python.is_file() and create:
        _check([processes.console_python(), "-m", "venv", ".venv"], folder)
    if not python.is_file():
        raise ValueError(f"Python environment is missing: {python}")
    return python


def run(repo: Path) -> int:
    custom = declared(repo, "run")
    if custom:
        _check(*custom)
        return 0
    if repo.name == "development-management":
        _check([processes.console_python(), "-u", str(repo / "DEV_CONTROL_CENTER.pyw")], repo)
        return 0
    if repo.name == "menu-sheet-generator":
        _check(["dotnet", "run", "--project", str(repo / "MenuPrinterWpf.csproj")], repo)
        return 0
    if repo.name not in PYTHON_RUNS:
        raise ValueError("RUN非対話entrypoint未登録: dcc_entrypoints.jsonを追加してください")
    relative, probe, args = PYTHON_RUNS[repo.name]
    folder = repo / relative
    env = {}
    if repo.name == "beverage-inventory-ordering-system":
        database = repo.parent / "qr-supply-ordering-system" / "database" / "qr_supply.sqlite3"
        if not database.is_file():
            raise ValueError("Local supply test database is missing; no production fallback")
        env.update(BEVERAGE_DATA_DIR=str(folder / "data"), BEVERAGE_SUPPLY_DB_PROFILE=None,
                   QR_SUPPLY_DB_PATH=str(database), SUPPLY_QR_DISABLE_NETWORK="1", BEVERAGE_DISABLE_RUNTIME=None)
    if repo.name == "food-cost-calculation-system":
        env["PYTHONPATH"] = str(repo / "src")
    python = _venv(folder, create=True)
    rc = processes.stream([str(python), "-u", "-c", probe], cwd=folder, emit=processes.forward, env=env)
    if rc:
        _check([str(python), "-m", "pip", "install", "-r", "requirements.txt"], folder, env)
    _check([str(python), "-u", *args], folder, env)
    return 0


def build(repo: Path) -> int:
    custom = declared(repo, "build")
    if custom:
        _check(*custom)
        return 0
    if repo.name == "next-day-setup":
        _check([str(_venv(repo, create=False)), "-u", str(repo / "build_exe_entry.py")], repo)
    elif repo.name == "food-cost-calculation-system":
        _check(processes.powershell(repo / "tools/release/build_release.ps1"), repo)
    elif repo.name == "menu-sheet-generator":
        project = str(repo / "MenuPrinterWpf.csproj")
        _check(["dotnet", "build", project, "-c", "Release"], repo)
        _check(["dotnet", "publish", project, "-c", "Release", "-r", "win-x64", "--self-contained", "true",
                "-p:PublishSingleFile=false", "-o", str(repo / "publish")], repo)
        for name in MENU_FILES:
            if not (repo / "publish" / name).is_file():
                raise ValueError(f"Missing build artifact: {name}")
    elif repo.name == "beverage-inventory-ordering-system":
        folder = repo / "python_app"
        python = str(_venv(folder, create=True))
        _check([python, "-m", "pip", "install", "--upgrade", "pip"], folder)
        _check([python, "-m", "pip", "install", "-r", "requirements-dev.txt"], folder)
        _check([python, "-u", "tools/write_release_manifest.py", "--check-clean"], folder)
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                         **processes.hidden_options()).decode().strip()
        _check([python, "-m", "pytest", "-q"], folder)
        _check([python, "-c", "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')"], folder)
        _check([python, "-u", "tools/build_exe.py", "--commit", commit], folder)
    else:
        raise ValueError("BUILD非対話entrypoint未登録: dcc_entrypoints.jsonを追加してください")
    return 0


def menu_update(repo: Path, artifact: Path, target: Path) -> int:
    # Same four-file, no-delete operation as UPDATE.cmd, with an explicit target
    # and no console prompts/pause. The provenance worker already holds its lock.
    from .provenance import no_links
    if repo.name != "menu-sheet-generator" or artifact.resolve() != (repo / "publish").resolve():
        raise ValueError("Invalid menu distribution source")
    no_links(target)
    if not target.is_dir() or (target / "menu-edit.lock").exists():
        raise ValueError("Distribution folder missing or application is locked")
    for name in MENU_FILES:
        no_links(artifact / name); no_links(target / name)
        if not (artifact / name).is_file():
            raise ValueError(f"Missing source: {name}")
    for name in MENU_FILES:
        print(f"Copying {name}", flush=True)
        shutil.copy2(artifact / name, target / name)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "build", "menu-update"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "menu-update":
            return menu_update(args.repo, args.artifact, args.target)
        return run(args.repo) if args.action == "run" else build(args.repo)
    except subprocess.CalledProcessError as exc:
        print(f"[DCC] {args.action.upper()} failed rc={exc.returncode}", flush=True)
        return exc.returncode if 0 < exc.returncode < 256 else 1
    except Exception as exc:
        print(f"[DCC] {args.action.upper()} stopped: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
