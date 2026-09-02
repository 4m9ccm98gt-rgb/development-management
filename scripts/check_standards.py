#!/usr/bin/env python3
"""管理対象リポジトリが development-management の標準を満たすか点検する。

チェック内容:
  1. Python/Windows アプリの3経路（RUN_DEV / ビルド / 配布更新）の有無
  2. 秘密情報らしきパターン（秘密鍵、各種トークン、実 *_settings.json）
  3. PROJECT_STATUS.md の鮮度（development-management のみ）
  4. README / AI_STARTUP の projects/*.md 参照漏れ（development-management のみ）

標準ライブラリのみ。Windows / Linux / GitHub Actions で同一に動く。
ERROR が1件でもあれば終了コード 1。--strict を付けると WARN でも 1。

使い方:
    python scripts/check_standards.py                 # 兄弟リポジトリを全点検
    python scripts/check_standards.py --repo ../foo   # 1リポジトリだけ
    python scripts/check_standards.py --strict
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

try:  # Windows コンソールでも日本語出力を化けさせない
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

DM = Path(__file__).resolve().parents[1]          # development-management
REPOS_DIR = DM.parent                             # .../Development/repos

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__",
             "dist", "build", ".pytest_cache", ".mypy_cache"}
TEXT_EXT = {".py", ".js", ".ts", ".json", ".toml", ".ini", ".cfg", ".md",
            ".txt", ".yml", ".yaml", ".ps1", ".cmd", ".bat", ".env"}
MAX_SCAN_BYTES = 1_000_000
STATUS_MAX_AGE_DAYS = 14

# (severity, label, pattern, skip_tests)
SECRET_PATTERNS = [
    ("ERROR", "private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), False),
    ("ERROR", "GitHub token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), False),
    ("ERROR", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), False),
    ("ERROR", "Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}"), False),
    ("ERROR", "AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), False),
    # 総当たりで誤検知しやすいので WARN。テスト・フィクスチャは除外。
    ("WARN", "generic secret assignment",
     re.compile(r"(?i)(?:api[_-]?key|client[_-]?secret|passwd|password|access[_-]?token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
     True),
]

findings: list[tuple[str, str, str]] = []   # (severity, repo, message)


def add(sev: str, repo: str, msg: str) -> None:
    findings.append((sev, repo, msg))


def _skip_part(part: str) -> bool:
    return part in SKIP_DIRS or part.startswith(".venv") or part == "site-packages"


def _is_test_file(p: Path) -> bool:
    return p.name.startswith("test_") or "tests" in p.parts or "test" in p.parts


def iter_files(root: Path):
    for p in root.rglob("*"):
        if any(_skip_part(part) for part in p.parts):
            continue
        if p.is_file():
            yield p


def check_three_paths(repo: Path) -> None:
    name = repo.name
    has_py = any(repo.glob("*.py")) or any(repo.glob("**/*.py"))
    looks_app = has_py and (
        (repo / "pyproject.toml").exists()
        or (repo / "requirements.txt").exists()
        or any(repo.glob("**/python_app"))
        or any(repo.glob("**/*.spec"))
    )
    if not looks_app:
        return
    names = {p.name.lower() for p in repo.iterdir() if p.is_file()}

    run_ok = any(("run_dev" in n) for n in names)
    build_ok = any(("build" in n and n.endswith((".cmd", ".bat", ".ps1"))) or "build_exe" in n for n in names)
    dist_ok = any(("update" in n and n.endswith((".cmd", ".bat", ".ps1"))) or "update_shared_folder" in n for n in names)

    if not run_ok:
        add("WARN", name, "RUN_DEV.cmd 相当（開発版ワンクリック起動）が無い")
    if not build_ok:
        add("WARN", name, "ビルドのワンクリック（BUILD_*_CLICK_ME.cmd 相当）が無い")
    if not dist_ok:
        add("WARN", name, "配布更新のワンクリック（UPDATE_SHARED_FOLDER.cmd 相当）が無い")


def check_secrets(repo: Path) -> None:
    name = repo.name
    for p in iter_files(repo):
        low = p.name.lower()
        if low in {"master_settings.json", "updater_settings.json"} and ".example." not in low:
            add("WARN", name, f"実 settings らしきファイルが Git 内にある: {p.relative_to(repo)}（*.example.* 化を検討）")
        if p.suffix.lower() not in TEXT_EXT:
            continue
        try:
            if p.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if ".example." in low or low.endswith((".sample", ".template")):
            continue
        is_test = _is_test_file(p)
        for sev, label, pat, skip_tests in SECRET_PATTERNS:
            if skip_tests and is_test:
                continue
            if pat.search(text):
                add(sev, name, f"{label} らしきパターン: {p.relative_to(repo)}")


def check_status_freshness() -> None:
    status = DM / "PROJECT_STATUS.md"
    if not status.exists():
        add("ERROR", DM.name, "PROJECT_STATUS.md が無い")
        return
    m = re.search(r"最終更新[:：]\s*(\d{4})-(\d{2})-(\d{2})", status.read_text(encoding="utf-8"))
    if not m:
        add("WARN", DM.name, "PROJECT_STATUS.md に『最終更新: YYYY-MM-DD』が見つからない")
        return
    age = (date.today() - date(int(m[1]), int(m[2]), int(m[3]))).days
    if age > STATUS_MAX_AGE_DAYS:
        add("WARN", DM.name, f"PROJECT_STATUS.md が {age} 日前（{STATUS_MAX_AGE_DAYS} 日以内に更新する）")


def check_project_refs() -> None:
    proj_dir = DM / "projects"
    if not proj_dir.is_dir():
        return
    refs = ""
    for doc in ("README.md", "AI_STARTUP.md", "SYSTEM_OVERVIEW.md"):
        p = DM / doc
        if p.exists():
            refs += p.read_text(encoding="utf-8")
    for md in sorted(proj_dir.glob("*.md")):
        if md.stem not in refs:
            add("WARN", DM.name, f"projects/{md.name} が README / AI_STARTUP / SYSTEM_OVERVIEW から参照されていない")


def target_repos(arg_repo: str | None) -> list[Path]:
    if arg_repo:
        return [Path(arg_repo).resolve()]
    out = []
    for child in sorted(REPOS_DIR.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            out.append(child)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="1リポジトリだけ点検する")
    ap.add_argument("--strict", action="store_true", help="WARN でも終了コード 1")
    args = ap.parse_args(argv)

    repos = target_repos(args.repo)
    print(f"点検対象: {len(repos)} リポジトリ ({REPOS_DIR})")
    for repo in repos:
        if not repo.exists():
            add("ERROR", repo.name, "パスが存在しない")
            continue
        check_three_paths(repo)
        check_secrets(repo)
        if repo.resolve() == DM.resolve():
            check_status_freshness()
            check_project_refs()

    if not findings:
        print("OK: 指摘なし")
        return 0

    errors = sum(1 for s, _, _ in findings if s == "ERROR")
    warns = sum(1 for s, _, _ in findings if s == "WARN")
    for sev, repo, msg in sorted(findings, key=lambda f: (f[0] != "ERROR", f[1])):
        print(f"  [{sev}] {repo}: {msg}")
    print(f"\nERROR {errors} / WARN {warns}")
    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
