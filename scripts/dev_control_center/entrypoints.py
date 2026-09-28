"""DCC-only, non-interactive adapters. Manual CMD launchers remain untouched.

Known adapters call the same application bodies and prerequisite checks as the
audited manual launchers. Unknown repositories must declare dcc_entrypoints.json;
there is deliberately no fallback to a potentially interactive CMD file.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

from . import processes

REGISTRY = Path(__file__).resolve().parents[1] / "dev_control_center_repos.toml"
BUILDS = {"food-cost-calculation-system", "menu-sheet-generator", "beverage-inventory-ordering-system"}
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


def run_specs(registry: Path = REGISTRY) -> dict[str, dict]:
    """Per-repo Python RUN definitions ([run.<repo>] in dev_control_center_repos.toml)."""
    with registry.open("rb") as handle:
        return dict(tomllib.load(handle).get("run", {}))


@dataclass
class RunPlan:
    """What a Python RUN executes. `target` is where the code comes from (the source repo, or an
    Orchestrator candidate worktree); `python` comes from the `.venv` of `venv_root` (default: target)."""

    name: str
    target: Path
    cwd: Path
    python: Path
    probe: str
    args: list[str]
    entrypoint: str
    env: dict = field(default_factory=dict)

    @property
    def command(self) -> list[str]:
        return [str(self.python), "-u", *self.args]


def plan_run(target: Path, *, name: str | None = None, venv_root: Path | None = None,
             specs: dict | None = None) -> RunPlan:
    """Resolve a registered Python RUN against `target`; a missing entrypoint stops before start."""
    name = name or target.name
    spec = (specs if specs is not None else run_specs()).get(name)
    if spec is None:
        raise ValueError("RUN非対話entrypoint未登録: dev_control_center_repos.toml の [run.<repo>] "
                         "またはdcc_entrypoints.jsonを追加してください")
    relative = str(spec.get("cwd", "."))
    cwd = _local(target, relative)
    if not cwd.is_dir():
        raise ValueError(f"RUNのcwdがありません: {cwd}")
    env = {key: (str(_local(target, value)) if key == "PYTHONPATH" else value)
           for key, value in dict(spec.get("env", {})).items()}
    if spec.get("module"):
        args, entry = ["-m", str(spec["module"])], f"-m {spec['module']}"
    else:
        script = _local(cwd, str(spec["entry"]))
        if not script.is_file():
            raise ValueError(f"RUN entrypointがありません（起動しません）: {script}")
        args, entry = [str(spec["entry"])], str(script)
    python = (venv_root or target) / relative / ".venv" / "Scripts" / "python.exe"
    return RunPlan(name, target, cwd, python, str(spec.get("probe", "")), args, entry, env)


def build_specs(registry: Path = REGISTRY) -> dict[str, dict]:
    """Per-repo Python BUILD bodies ([build.<repo>] in dev_control_center_repos.toml): the same script the
    manual BUILD CMD runs, but called directly — the CMD wrapper (and its `pause`) is never executed."""
    with registry.open("rb") as handle:
        return dict(tomllib.load(handle).get("build", {}))


def build_info_spec(repo: Path, *, name: str | None = None) -> dict | None:
    """How the build stamps its artifact with the commit it was built from (e.g. BUILD_INFO.txt)."""
    spec = build_specs().get(name or repo.name)
    if spec is None:
        manifest = repo / "dcc_entrypoints.json"
        if manifest.is_file():
            spec = (json.loads(manifest.read_text(encoding="utf-8-sig")).get("build") or {})
    info = (spec or {}).get("build_info")
    return dict(info) if info else None


def plan_build(repo: Path, *, name: str | None = None) -> tuple[list[str], Path]:
    spec = build_specs()[name or repo.name]
    cwd = _local(repo, str(spec.get("cwd", ".")))
    script = _local(cwd, str(spec["script"]))
    if not script.is_file():
        raise ValueError(f"BUILD本体がありません（起動しません）: {script}")
    return [str(_venv(cwd, create=False)), "-u", str(script), *[str(a) for a in spec.get("args", [])]], cwd


def supported(repo: Path, action: str, *, name: str | None = None) -> bool:
    name = name or repo.name
    if declared(repo, action) is not None:
        return True
    if action == "run":
        return name in run_specs() or name in {"development-management", "menu-sheet-generator"}
    return action == "build" and (name in BUILDS or name in build_specs())


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


def run(repo: Path, *, name: str | None = None, venv_root: Path | None = None) -> int:
    """RUN `repo`: the source repo, or a candidate worktree (then `name` is the registered repo and
    `venv_root` the source repo). A candidate RUN never creates or installs into a venv: the source
    repo's `.venv` must already provide the dependencies, otherwise it stops before starting."""
    name = name or repo.name
    custom = declared(repo, "run")
    if custom:
        _check(*custom)
        return 0
    if name == "development-management":
        _check([processes.console_python(), "-u", str(repo / "DEV_CONTROL_CENTER.pyw")], repo)
        return 0
    if name == "menu-sheet-generator":
        _check(["dotnet", "run", "--project", str(repo / "MenuPrinterWpf.csproj")], repo)
        return 0
    plan = plan_run(repo, name=name, venv_root=venv_root)
    folder, env = plan.cwd, dict(plan.env)
    if name == "beverage-inventory-ordering-system":
        database = (venv_root or repo).parent / "qr-supply-ordering-system" / "database" / "qr_supply.sqlite3"
        if not database.is_file():
            raise ValueError("Local supply test database is missing; no production fallback")
        env.update(BEVERAGE_DATA_DIR=str(folder / "data"), BEVERAGE_SUPPLY_DB_PROFILE=None,
                   QR_SUPPLY_DB_PATH=str(database), SUPPLY_QR_DISABLE_NETWORK="1", BEVERAGE_DISABLE_RUNTIME=None)
    if venv_root is None:
        python = _venv(folder, create=True)
    elif not plan.python.is_file():
        raise ValueError(f"source repoの.venvがありません: {plan.python}（通常RUNで一度準備してください）")
    else:
        python = plan.python
    if plan.probe:
        rc = processes.stream([str(python), "-u", "-c", plan.probe], cwd=folder, emit=processes.forward, env=env)
        if rc and venv_root is not None:
            raise ValueError("source repoの.venvに依存関係が不足しています（candidate RUNではinstallしません）。"
                             "通常RUNで依存関係を準備してから再実行してください")
        if rc:
            _check([str(python), "-m", "pip", "install", "-r", "requirements.txt"], folder, env)
    _check([str(python), "-u", *plan.args], folder, env)
    return 0


def build(repo: Path) -> int:
    custom = declared(repo, "build")
    if custom:
        _check(*custom)
        return 0
    if repo.name in build_specs():
        _check(*plan_build(repo))
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
    parser.add_argument("--name", help="registered repo name when --repo is a candidate worktree")
    parser.add_argument("--venv-root", type=Path, help="repo whose .venv provides Python (candidate RUN)")
    args = parser.parse_args()
    try:
        if args.action == "menu-update":
            return menu_update(args.repo, args.artifact, args.target)
        if args.action == "run":
            return run(args.repo, name=args.name, venv_root=args.venv_root)
        return build(args.repo)
    except subprocess.CalledProcessError as exc:
        print(f"[DCC] {args.action.upper()} failed rc={exc.returncode}", flush=True)
        return exc.returncode if 0 < exc.returncode < 256 else 1
    except Exception as exc:
        print(f"[DCC] {args.action.upper()} stopped: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
