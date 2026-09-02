#!/usr/bin/env python3
"""クロスプラットフォームの補助コマンド（標準ライブラリのみ）。

    doctor   Python / .venv / Git 状態を表示する
    check    development-management の check_standards.py をこのリポジトリへ適用する

起動・ビルド・配布更新は自己完結の RUN_DEV.cmd / BUILD_EXE_CLICK_ME.cmd /
UPDATE_SHARED_FOLDER.cmd を使う（Windows 実機前提）。この dev.py は Linux sandbox
や CI でも動く点検用。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=False).stdout.strip()


def doctor() -> int:
    venv = REPO / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    print("repo          :", REPO)
    print("system python :", sys.version.split()[0], "@", sys.executable)
    print(".venv python  :", venv if venv.exists() else "(未作成 — RUN_DEV.cmd が作成する)")
    print("git branch    :", git("rev-parse", "--abbrev-ref", "HEAD"))
    print("git status    :", git("status", "--porcelain") or "(clean)")
    print("ahead/behind  :", git("rev-list", "--left-right", "--count", "@{u}...HEAD") or "(no upstream)")
    return 0


def check(rest: list[str]) -> int:
    for base in (REPO.parent / "development-management", REPO.parent.parent / "development-management"):
        checker = base / "scripts" / "check_standards.py"
        if checker.exists():
            return subprocess.call([sys.executable, str(checker), "--repo", str(REPO), *rest])
    print("check_standards.py が見つからない。development-management を clone しているか確認する。", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"doctor", "check"}:
        print(__doc__)
        return 2
    return doctor() if argv[0] == "doctor" else check(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
