#!/usr/bin/env python3
"""管理対象リポジトリが development-management の標準を満たすか点検する。

チェック内容:
  1. アプリ種別ごとに必要なワンクリック経路の有無
     - desktop : 起動 / EXEビルド / 配布更新
     - web     : 起動 / デプロイ
     - service : 起動 / 常駐登録
     - lib     : なし
     種別は pyproject.toml の [tool.devstandards] type、無ければ
     scripts/repo_types.toml、無ければ依存関係から自動判定、それでも不明なら警告。
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
import tomllib
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


APP_MARKERS = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")


def _has_py(d: Path) -> bool:
    for p in d.rglob("*.py"):
        if not any(_skip_part(x) for x in p.parts):
            return True
    return False


def find_app_roots(repo: Path) -> list[Path]:
    """アプリの置き場所（パッケージ設定 or *.spec がある場所、2階層まで）を返す。"""
    roots: set[Path] = set()
    for marker in (*APP_MARKERS, "*.spec"):
        for hit in repo.rglob(marker):
            if any(_skip_part(x) for x in hit.parts):
                continue
            if len(hit.relative_to(repo).parts) - 1 <= 2:
                roots.add(hit.parent)
    roots = {r for r in roots if _has_py(r)}
    if not roots and _has_py(repo):
        roots = {repo}
    return sorted(roots)


# アプリ種別ごとに要求するワンクリック経路
REQUIRED_BY_TYPE = {
    "desktop": ["run", "build", "dist"],
    "web":     ["run", "deploy"],
    "service": ["run", "install"],
    "lib":     [],
}
PATH_LABEL = {
    "run":     "RUN_DEV.cmd 相当（開発版ワンクリック起動）",
    "build":   "EXEビルドのワンクリック（BUILD_*_CLICK_ME.cmd 相当）",
    "dist":    "配布更新のワンクリック（UPDATE_SHARED_FOLDER.cmd 相当）",
    "deploy":  "デプロイ手順（DEPLOY 相当 / Dockerfile / compose / Procfile）",
    "install": "常駐登録手順（INSTALL 相当 / タスクスケジューラ XML / register_task）",
}


def _load_repo_types() -> dict:
    p = Path(__file__).resolve().parent / "repo_types.toml"
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f).get("types", {})
    except tomllib.TOMLDecodeError:
        return {}


REPO_TYPES = _load_repo_types()


def _read_type_marker(d: Path) -> str | None:
    pp = d / "pyproject.toml"
    if pp.exists():
        try:
            with pp.open("rb") as f:
                t = tomllib.load(f).get("tool", {}).get("devstandards", {}).get("type")
            if t:
                return t
        except tomllib.TOMLDecodeError:
            pass
    ds = d / ".devstandards.toml"
    if ds.exists():
        try:
            with ds.open("rb") as f:
                t = tomllib.load(f).get("type")
            if t:
                return t
        except tomllib.TOMLDecodeError:
            pass
    return None


def resolve_type(repo: Path, app: Path) -> str:
    for d in (app, repo):                       # 1. リポジトリ内のマーカー
        t = _read_type_marker(d)
        if t:
            return t
    if repo.name in REPO_TYPES:                 # 2. development-management の暫定マップ
        return REPO_TYPES[repo.name]
    reqs = ""                                   # 3. 自動判定（強いシグナルのみ）
    for rf in ("requirements.txt", "requirements-dev.txt", "pyproject.toml"):
        fp = app / rf
        if not fp.exists():
            fp = repo / rf
        if fp.exists():
            reqs += fp.read_text(encoding="utf-8", errors="ignore").lower()
    if any(k in reqs for k in ("flask", "django", "fastapi", "uvicorn", "gunicorn", "starlette")):
        return "web"
    if any(k in reqs for k in ("pyside6", "pyside2", "pyqt5", "pyqt6", "wxpython")):
        return "desktop"
    if any(app.glob("*.spec")) or any(repo.glob("*.spec")):
        return "desktop"
    return "unknown"


def _path_satisfied(kind: str, names: set[str], app: Path, repo: Path) -> bool:
    if kind == "run":
        return any("run_dev" in n for n in names)
    if kind == "build":
        return any("build" in n and n.endswith((".cmd", ".bat", ".ps1")) for n in names)
    if kind == "dist":
        return any("update" in n and n.endswith((".cmd", ".bat", ".ps1")) for n in names)
    if kind == "deploy":
        if any("deploy" in n for n in names):
            return True
        return any((d / f).exists()
                   for d in (app, repo)
                   for f in ("Dockerfile", "docker-compose.yml", "compose.yml", "Procfile"))
    if kind == "install":
        if any(("install" in n or "register_task" in n) for n in names):
            return True
        return any(app.glob("*.xml")) or any((repo / "deploy").glob("*.xml"))
    return True


def check_paths(repo: Path) -> None:
    if repo.resolve() == DM.resolve():
        return  # 管理リポジトリ自身はアプリではない
    for app in find_app_roots(repo):
        rel = app.relative_to(repo).as_posix()
        loc = "" if rel == "." else f"{rel}/: "
        t = resolve_type(repo, app)
        if t == "unknown":
            add("WARN", repo.name,
                f'{loc}アプリ種別が未設定（pyproject.toml に [tool.devstandards] type = "desktop|web|service|lib"）')
            continue
        if t not in REQUIRED_BY_TYPE:
            add("WARN", repo.name, f"{loc}未知のアプリ種別 type={t!r}")
            continue
        names: set[str] = set()
        for d in {app, repo}:
            names |= {p.name.lower() for p in d.iterdir() if p.is_file()}
        for kind in REQUIRED_BY_TYPE[t]:
            if not _path_satisfied(kind, names, app, repo):
                add("WARN", repo.name, f"{loc}[{t}] {PATH_LABEL[kind]} が無い")


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
        check_paths(repo)
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
