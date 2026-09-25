"""Local build receipts and explicit release adapters. No deployment on import.

Receipts contain hashes, never source/configuration contents. Existing repo
scripts still own dependencies, packaging and protection of operational data.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

from . import processes, entrypoints


PROFILES = {
    "next-day-setup": ("dist/DinnerSystem", "update_shared_folder.ps1", "powershell"),
    "beverage-inventory-ordering-system": (
        "python_app/dist/在庫発注管理アプリ", "python_app/update_shared_folder.ps1", "powershell"),
    "menu-sheet-generator": ("publish", "UPDATE.cmd", "cmd-target"),
    "food-cost-calculation-system": ("../../releases", "tools/release/update_hdd.ps1", "hdd"),
}


def state_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC" / "builds"


def repo_key(repo: Path) -> str:
    return hashlib.sha256(str(repo.resolve()).casefold().encode()).hexdigest()


def receipt_path(repo: Path) -> Path:
    return state_root() / repo_key(repo) / "latest.json"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def no_links(path: Path) -> None:
    for part in (path.absolute(), *path.absolute().parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError(f"リンク経由のパスは使用できません: {path}")


def tree_hash(root: Path) -> str:
    no_links(root)
    if not root.is_dir():
        raise ValueError(f"成果物フォルダがありません: {root}")
    result = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        no_links(path)
        if path.is_file():
            result.update(path.relative_to(root).as_posix().encode())
            result.update(b"\0" + digest(path).encode() + b"\0")
            count += 1
    if not count:
        raise ValueError("成果物が空です")
    return result.hexdigest()


def artifact_stamp(root: Path) -> list:
    if not root.exists():
        return []
    no_links(root)
    result = []
    for path in sorted(root.rglob("*")):
        no_links(path)
        if path.is_file():
            stat = path.stat()
            result.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return result


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], encoding="utf-8", timeout=30, **processes.hidden_options()).strip()


def inputs_hash(repo: Path, artifact: Path) -> str:
    # Git-managed and non-ignored new inputs. Ignored local build settings can
    # be explicitly listed (relative paths) in .dcc-build-inputs.json.
    names = set(git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"))
    settings = repo / ".dcc-build-inputs.json"
    if settings.exists():
        extra = json.loads(settings.read_text(encoding="utf-8"))
        if not isinstance(extra, list) or not all(isinstance(n, str) for n in extra):
            raise ValueError(".dcc-build-inputs.json は相対ファイルパスの配列が必要です")
        names.update(extra)
    value = hashlib.sha256(git(repo, "rev-parse", "HEAD").encode())
    for name in sorted(names):
        if not name:
            continue
        path = repo / name
        no_links(path)
        if not path.resolve().is_relative_to(repo.resolve()):
            raise ValueError("build inputがrepo外です")
        if path.resolve().is_relative_to(artifact.resolve()):
            continue
        value.update(name.encode() + b"\0")
        value.update((digest(path) if path.is_file() else "MISSING").encode())
    return value.hexdigest()


@contextmanager
def output_lock(artifact: Path):
    """Cross-process lock for DCC builds/updates sharing an output directory."""
    folder = state_root() / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (repo_key(artifact) + ".lock")
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0"); stream.flush(); stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("同じ出力先でBUILD / UPDATEが実行中です") from exc
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def cmd_command(entry: Path, args: list[str] | None = None) -> str:
    values = [str(entry), *(args or [])]
    if any(any(c in v for c in '\r\n"%&|<>^!') for v in values):
        raise ValueError("CMDに安全に渡せない文字がパスに含まれています")
    return 'cmd.exe /d /s /c "' + " ".join('"' + v + '"' for v in values) + '"'


def build(repo: Path, entry: Path, artifact: Path) -> dict:
    no_links(repo)
    no_links(entry)
    if not entry.resolve().is_relative_to(repo.resolve()) or entry.suffix.lower() not in {".cmd", ".bat"}:
        raise ValueError("BUILD入口は対象repo内のCMD / BATに限定します")
    git(repo, "ls-files", "--error-unmatch", entry.relative_to(repo).as_posix())
    with output_lock(artifact):
        record = {"schema": 1, "repo": str(repo.resolve()), "base_head": git(repo, "rev-parse", "HEAD"),
                  "dirty": bool(git(repo, "status", "--porcelain")),
                  "build_id": uuid.uuid4().hex, "started_at": datetime.now(timezone.utc).isoformat(),
                  "artifact": str(artifact.resolve()), "entrypoint": str(entry.resolve()),
                  "status": "building", "artifact_hash": None}
        path = receipt_path(repo)
        write_json(path, record)  # invalidate the previous success BEFORE execution
        try:
            old_artifact_stamp = artifact_stamp(artifact)
            before = inputs_hash(repo, artifact)
            record["inputs_hash"] = before
            changed = threading.Event()
            done = threading.Event()

            def watch():
                while not done.wait(0.5):
                    try:
                        if inputs_hash(repo, artifact) != before:
                            changed.set()
                    except Exception:
                        changed.set()

            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            try:
                command = [processes.console_python(), "-u", "-m", "scripts.dev_control_center.entrypoints", "build", "--repo", str(repo)]
                rc = processes.stream(command, cwd=Path(__file__).resolve().parents[2], emit=processes.forward)
            finally:
                done.set(); watcher.join()
            record["returncode"] = rc
            stable = not changed.is_set() and inputs_hash(repo, artifact) == before
            refreshed = artifact_stamp(artifact) != old_artifact_stamp
            record.update(returncode=rc, inputs_stable=stable, artifact_refreshed=refreshed,
                          artifact_hash=tree_hash(artifact),
                          status="ready" if rc == 0 and stable and refreshed else "rejected")
        except Exception as exc:
            record.update(status="rejected", error=str(exc))
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, record)
        write_json(path.with_name(record["build_id"] + ".json"), record)
        return record


def read_receipt(repo: Path) -> dict:
    record = json.loads(receipt_path(repo).read_text(encoding="utf-8"))
    if record.get("repo") != str(repo.resolve()) or record.get("status") != "ready":
        raise ValueError("UPDATE可能なBUILD記録がありません。BUILDを確認してください")
    artifact = Path(record["artifact"])
    if tree_hash(artifact) != record.get("artifact_hash"):
        raise ValueError("BUILD後に成果物が変わりました。UPDATEを停止します")
    if inputs_hash(repo, artifact) != record.get("inputs_hash"):
        raise ValueError("BUILD後に入力が変わりました。再BUILDしてください")
    return record


def release_command(repo: Path, artifact: Path, target: Path) -> tuple[list[str] | str, Path]:
    profile = PROFILES.get(repo.name)
    if profile is None:
        raise ValueError("このrepoの配布引数は未登録です。正式entrypointとの接続確認が必要です")
    output, script, kind = profile
    if artifact.resolve() != (repo / output).resolve():
        raise ValueError("成果物が登録済み配布元と一致しません")
    no_links(target)
    if not target.is_dir() or (target / ".git").exists():
        raise ValueError("既存の配布先フォルダを選択してください（Git repoは不可）")
    for source in (repo.resolve(), artifact.resolve()):
        if target.resolve().is_relative_to(source) or source.is_relative_to(target.resolve()):
            raise ValueError("配布先とソース／成果物が重なっています")
    entry = repo / script
    no_links(entry)
    if not entry.is_file():
        raise ValueError("正式更新スクリプトがありません")
    if kind == "cmd-target":
        return [processes.console_python(), "-u", "-m", "scripts.dev_control_center.entrypoints", "menu-update", "--repo", str(repo), "--artifact", str(artifact), "--target", str(target)], entry
    options = ["-SourceRoot", str(artifact), "-HddRoot", str(target)] if kind == "hdd" else [
        "-SourcePath", str(artifact), "-TargetPath", str(target)]
    return processes.powershell(entry, *options), entry


def release_snapshot(repo: Path, target: Path) -> dict:
    record = read_receipt(repo)
    artifact = Path(record["artifact"])
    # Mirror the existing next-day updater's documented child-folder selection
    # before asking for approval, then pass that exact folder to the script.
    if repo.name == "next-day-setup":
        direct = (target / "DinnerSystem.exe").exists() and (target / "_internal").exists()
        child = target / "DinnerSystem"
        if not direct and (child / "DinnerSystem.exe").exists() and (child / "_internal").exists():
            target = child
    command, entry = release_command(repo, artifact, target)
    stat = target.stat()
    detail = str(target.resolve())
    if repo.name == "food-cost-calculation-system":
        versions = sorted(p.name for p in artifact.iterdir() if p.is_dir() and re.fullmatch(r"俺伝-\d{4}-\d{2}-\d{2}-\d{4}", p.name))
        updaters = sorted(p.name for p in artifact.iterdir() if p.is_dir() and re.fullmatch(r"俺伝-Updater-\d{4}-\d{2}-\d{2}-\d{4}", p.name))
        if not versions or not updaters:
            raise ValueError("配布するアプリとUpdaterのreleaseが揃っていません")
        detail = str(target / "FoodCostCalculation" / versions[-1]) + "\n" + str(target / "FoodCostCalculation" / "Updater")
    return {"receipt": record, "target": str(target.resolve()), "command": command,
            "entry_hash": digest(entry), "target_identity": [stat.st_dev, stat.st_ino],
            "destination_detail": detail, "adapter_hash": digest(Path(entrypoints.__file__))}


def release(repo: Path, request: dict) -> int:
    with output_lock(Path(request["receipt"]["artifact"])):
        if release_snapshot(repo, Path(request["target"])) != request:
            raise ValueError("確認後に配布条件が変わりました。UPDATEを停止します")
        return processes.stream(request["command"], cwd=Path(__file__).resolve().parents[2], emit=processes.forward)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "release"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--entry", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--request", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "build":
            result = build(args.repo, args.entry, args.artifact)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ready" else (result.get("returncode") or 1)
        request = json.loads(args.request.read_text(encoding="utf-8"))
        return release(args.repo, request)
    except Exception as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
