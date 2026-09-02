#!/usr/bin/env python3
"""開発版の起動・ビルド・配布更新・点検を1経路にまとめるテンプレート。

標準サブコマンド:
    run      正式ソースを .venv から起動する（日常の開発確認）
    doctor   Python / .venv / Git 状態など環境情報を表示する
    build    正式 EXE ビルド（既存の実績スクリプトがあればそれを呼ぶ）
    dist     配布先更新（既存の実績スクリプトがあればそれを呼ぶ）
    check    development-management の check_standards.py をこのリポジトリへ適用する

方針:
    - このファイルは「起点」。プロジェクト固有の部分は project.toml と、必要なら
      このスクリプトの TODO 箇所で調整する。
    - build / dist は、既に実績のある .cmd / .ps1 があるなら再利用する。
      ゼロから作り直さない（development-management の再利用ルール）。
    - 標準ライブラリのみ。Python 3.11+ が前提（tomllib を使用）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    cfg_path = REPO / "project.toml"
    if not cfg_path.exists():
        sys.exit("project.toml が見つからない。テンプレートからコピーして実値へ書き換える。")
    with cfg_path.open("rb") as f:
        cfg = tomllib.load(f)
    local = REPO / "project.local.toml"
    if local.exists():
        with local.open("rb") as f:
            _deep_update(cfg, tomllib.load(f))
    return cfg


def _deep_update(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def venv_python(cfg: dict) -> Path:
    venv = REPO / cfg["project"].get("venv", ".venv")
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def ensure_venv(cfg: dict) -> Path:
    py = venv_python(cfg)
    if py.exists():
        return py
    print(f"[dev] .venv が無いので作成する: {py.parent.parent}")
    subprocess.check_call([sys.executable, "-m", "venv", str(REPO / cfg["project"].get("venv", ".venv"))])
    dev = cfg.get("dev", {})
    req = dev.get("requirements", "")
    mode = dev.get("install", "editable")
    if mode == "editable":
        subprocess.check_call([str(py), "-m", "pip", "install", "-e", "."])
    elif mode == "requirements" and req:
        subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REPO / req)])
    return py


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True, text=True, check=False,
    ).stdout.strip()


def cmd_run(cfg: dict, rest: list[str]) -> int:
    py = ensure_venv(cfg)
    entry = cfg["project"]["entry"]
    print(f"[dev] {entry} を起動する")
    return subprocess.call([str(py), "-m", entry, *rest], cwd=REPO)


def cmd_doctor(cfg: dict, rest: list[str]) -> int:
    py = venv_python(cfg)
    print("repo            :", REPO)
    print("expected python :", cfg["project"].get("python", "?"))
    print("system python   :", sys.version.split()[0], "@", sys.executable)
    print(".venv python    :", py if py.exists() else "(未作成)")
    print("git branch      :", git("rev-parse", "--abbrev-ref", "HEAD"))
    print("git status      :", git("status", "--porcelain") or "(clean)")
    print("git ahead/behind:", git("rev-list", "--left-right", "--count", "@{u}...HEAD") or "(no upstream)")
    return 0


def cmd_build(cfg: dict, rest: list[str]) -> int:
    build = cfg.get("build", {})
    if build.get("refuse_dirty_tree", True) and git("status", "--porcelain"):
        return _fail("dirty working tree。正式ビルドは commit 後に行う。")
    tool = build.get("tool", "existing")
    if tool == "existing":
        script = build.get("existing_cmd")
        if not script or not (REPO / script).exists():
            return _fail(f"既存ビルドスクリプトが見つからない: {script!r}。project.toml を確認する。")
        rc = _run_script(REPO / script, rest)
    else:
        # TODO: nuitka / pyinstaller をこのプロジェクト用に実装する。
        return _fail(f"build.tool={tool!r} は未実装。既存スクリプトを existing で呼ぶか、ここを実装する。")
    if rc == 0:
        _report_artifact(cfg)
    return rc


def cmd_dist(cfg: dict, rest: list[str]) -> int:
    dist = cfg.get("dist", {})
    script = dist.get("existing_cmd")
    if not script or not (REPO / script).exists():
        return _fail(f"既存の配布更新スクリプトが見つからない: {script!r}。")
    print("[dev] 配布物と業務データを分離すること。共有フォルダ全体への /MIR は使わない。")
    return _run_script(REPO / script, rest)


def cmd_check(cfg: dict, rest: list[str]) -> int:
    # development-management/scripts/check_standards.py をこのリポジトリへ適用する。
    for base in (REPO.parent / "development-management", REPO.parent.parent / "development-management"):
        checker = base / "scripts" / "check_standards.py"
        if checker.exists():
            return subprocess.call([sys.executable, str(checker), "--repo", str(REPO), *rest])
    return _fail("check_standards.py が見つからない。development-management を clone しているか確認する。")


def _run_script(path: Path, rest: list[str]) -> int:
    if path.suffix.lower() == ".ps1":
        return subprocess.call(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *rest],
            cwd=REPO,
        )
    return subprocess.call([str(path), *rest], cwd=REPO, shell=(os.name == "nt"))


def _report_artifact(cfg: dict) -> None:
    art = cfg.get("build", {}).get("artifact")
    if not art:
        return
    p = REPO / art
    if not p.exists():
        print(f"[dev] 警告: 成果物が見つからない: {p}")
        return
    data = p.read_bytes()
    print("artifact :", p)
    print("size     :", f"{len(data):,} bytes")
    print("mtime    :", datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).astimezone().isoformat())
    print("sha256   :", hashlib.sha256(data).hexdigest())
    print("built@   :", git("rev-parse", "HEAD"))


def _fail(msg: str) -> int:
    print(f"[dev] {msg}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dev.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "doctor", "build", "dist", "check"])
    args, rest = parser.parse_known_args(argv)
    cfg = load_config()
    return {
        "run": cmd_run,
        "doctor": cmd_doctor,
        "build": cmd_build,
        "dist": cmd_dist,
        "check": cmd_check,
    }[args.command](cfg, rest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
