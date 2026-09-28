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
import time
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


def release_record_path(repo: Path) -> Path:
    """Result of the last DCC UPDATE of this repo, bound to the build id and the SHA it was built from."""
    return state_root() / repo_key(repo) / "last_release.json"


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


MTIME_SLACK_NS = 2_000_000_000  # file-system timestamp granularity (FAT: 2 s)


def artifact_refreshed(artifact: Path, before: list, started_ns: int, info_file: str | None = None) -> bool:
    """True only when THIS build produced the artifact: it differs from what was there before the build,
    and files in it (the build-info stamp, when the repo writes one) were written after the build started.
    A failed build that leaves the old artifact behind, or only deletes parts of it, is not a refresh."""
    after = artifact_stamp(artifact)
    if not after or after == before:
        return False
    fresh = started_ns - MTIME_SLACK_NS
    if info_file:
        stamp = next((item for item in after if item[0] == info_file), None)
        return stamp is not None and stamp[2] >= fresh
    return any(mtime >= fresh for _, _, mtime in after)


def read_build_info(artifact: Path, spec: dict) -> dict:
    """`Key: value` lines of the artifact's build-info file (e.g. BUILD_INFO.txt), or {} when missing."""
    path = artifact / spec["file"]
    no_links(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    return {key.strip(): value.strip() for key, _, value in (line.partition(":") for line in text.splitlines()) if _}


def _require_head(repo: Path, expected_sha: str) -> None:
    """Candidate route: BUILD only exactly the approved + pushed SHA, from a clean tracked tree."""
    head = git(repo, "rev-parse", "HEAD").lower()
    if head != expected_sha:
        raise ValueError(f"HEAD {head[:12]} が承認・push済みcandidate {expected_sha[:12]} と一致しません。BUILDしません")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("candidate BUILDは未コミット変更の無い作業ツリーだけを対象にします")


def build(repo: Path, entry: Path, artifact: Path, *, expected_sha: str | None = None,
          candidate_run_id: str | None = None, expected_branch: str | None = None) -> dict:
    """Run the repo's non-interactive BUILD body and record whether it produced a usable artifact.

    `entry` is the audited manual CMD (identity check only; it is never executed, so its `pause` can
    not block). The artifact is `ready` only when every condition holds; each failed one is listed in
    `reject_reasons`:
      returncode 0 / inputs unchanged / HEAD unchanged / a newly written artifact / its build-info SHA
      equals the built HEAD (and the candidate) / artifact hash computed.
    With `expected_sha` (Orchestrator candidate), the candidate gate (approved == pushed == local HEAD
    == origin, clean) is re-proved in this worker immediately before building."""
    no_links(repo)
    no_links(entry)
    if not entry.resolve().is_relative_to(repo.resolve()) or entry.suffix.lower() not in {".cmd", ".bat"}:
        raise ValueError("BUILD入口は対象repo内のCMD / BATに限定します")
    git(repo, "ls-files", "--error-unmatch", entry.relative_to(repo).as_posix())
    if expected_sha:
        from . import candidate as candidate_flow

        gate = candidate_flow.build_gate(repo, expected_branch or "main")
        if gate is None or gate.sha != expected_sha:
            raise ValueError(f"承認・push済みcandidate {expected_sha[:12]} を確認できません。BUILDしません")
        _require_head(repo, expected_sha)
    info_spec = entrypoints.build_info_spec(repo)
    with output_lock(artifact):
        record = {"schema": 1, "repo": str(repo.resolve()), "base_head": git(repo, "rev-parse", "HEAD"),
                  "dirty": bool(git(repo, "status", "--porcelain")),
                  "build_id": uuid.uuid4().hex, "started_at": datetime.now(timezone.utc).isoformat(),
                  "artifact": str(artifact.resolve()), "entrypoint": str(entry.resolve()),
                  "status": "building", "artifact_hash": None,
                  "candidate_sha": expected_sha or None, "candidate_run_id": candidate_run_id or None,
                  "build_info_file": (info_spec or {}).get("file")}
        path = receipt_path(repo)
        write_json(path, record)  # invalidate the previous success BEFORE execution
        try:
            old_artifact_stamp = artifact_stamp(artifact)
            started_ns = time.time_ns()
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
            head_after = git(repo, "rev-parse", "HEAD")
            stable = not changed.is_set() and inputs_hash(repo, artifact) == before
            head_unchanged = head_after == record["base_head"] and (not expected_sha or head_after.lower() == expected_sha)
            refreshed = artifact_refreshed(artifact, old_artifact_stamp, started_ns, (info_spec or {}).get("file"))
            reasons = []
            if rc != 0:
                reasons.append(f"returncode {rc}")
            if not stable:
                reasons.append("BUILD中に入力が変化")
            if not head_unchanged:
                reasons.append(f"HEADが変化 {record['base_head'][:12]} -> {head_after[:12]}")
            if not refreshed:
                reasons.append("このBUILDで成果物が生成・更新されていない")
            if info_spec:
                info = read_build_info(artifact, info_spec)
                info_sha = info.get(info_spec.get("sha_key", "Git commit SHA"), "").lower()
                record["build_info_sha"] = info_sha or None
                if info_sha != record["base_head"].lower() or (expected_sha and info_sha != expected_sha):
                    reasons.append(f"{info_spec['file']}のSHA {info_sha[:12] or '(なし)'} がBUILD対象SHAと不一致")
                tree_key = info_spec.get("tree_key")
                if expected_sha and tree_key and info.get(tree_key, "").lower() != "clean":
                    reasons.append(f"{info_spec['file']}の作業ツリーがclean以外: {info.get(tree_key)}")
            try:
                record["artifact_hash"] = tree_hash(artifact)
            except ValueError as exc:
                reasons.append(f"成果物hashを取得できない: {exc}")
            record.update(returncode=rc, inputs_stable=stable, artifact_refreshed=refreshed,
                          head_unchanged=head_unchanged, reject_reasons=reasons,
                          status="rejected" if reasons else "ready")
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
    try:
        release = json.loads(release_record_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        release = {}
    built = str(record.get("base_head") or "").lower()
    if release.get("kind") == "rollback" and built and built == str(release.get("rolled_back_from") or "").lower():
        raise ValueError(f"この成果物（{built[:12]}）は本番からrollback済みのSHAのBUILDです。再配布しません"
                         f"（本番は {str(release.get('deployed_commit'))[:12]}）。新しいBUILDが必要です")
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


def _require_candidate_artifact(repo: Path, record: dict, expected_sha: str, expected_branch: str) -> None:
    """Candidate route: approved == pushed (origin, asked live) == the SHA the artifact was built from."""
    built = str(record.get("base_head") or "").lower()
    stamped = record.get("build_info_sha")
    if (record.get("candidate_sha") != expected_sha or built != expected_sha or record.get("dirty")
            or (record.get("build_info_file") and stamped != expected_sha)):
        raise ValueError(f"成果物は {built[:12]} からのBUILDです（承認・push済みcandidate {expected_sha[:12]} ではない、"
                         "またはdirty）。別SHAの成果物は配布しません")
    head = git(repo, "rev-parse", "HEAD").lower()
    line = git(repo, "ls-remote", "origin", f"refs/heads/{expected_branch}")
    origin = line.split()[0].lower() if line else ""
    if not head == origin == expected_sha:
        raise ValueError(f"local HEAD {head[:12]} / origin/{expected_branch} {origin[:12]} が"
                         f"candidate {expected_sha[:12]} と一致しません。UPDATEを停止します")


def release_snapshot(repo: Path, target: Path, *, expected_sha: str | None = None,
                     expected_branch: str | None = None) -> dict:
    # Links are rejected on the path as given (resolve() would silently follow them); everything
    # recorded below then derives from one canonical target, so an 8.3 short path and its long
    # form (same entity) compare equal while a genuinely different target still does not.
    no_links(target)
    target = target.resolve()
    record = read_receipt(repo)
    if expected_sha:
        _require_candidate_artifact(repo, record, expected_sha, expected_branch or "main")
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
            "destination_detail": detail, "adapter_hash": digest(Path(entrypoints.__file__)),
            "expected_sha": expected_sha or None, "expected_branch": expected_branch or None}


def release(repo: Path, request: dict) -> int:
    with output_lock(Path(request["receipt"]["artifact"])):
        current = release_snapshot(repo, Path(request["target"]), expected_sha=request.get("expected_sha"),
                                   expected_branch=request.get("expected_branch"))
        if current != request:
            raise ValueError("確認後に配布条件が変わりました。UPDATEを停止します")
        receipt = request["receipt"]
        started = datetime.now(timezone.utc).isoformat()
        rc = processes.stream(request["command"], cwd=Path(__file__).resolve().parents[2], emit=processes.forward)
        write_json(release_record_path(repo), {
            "schema": 1, "repo": receipt["repo"], "build_id": receipt["build_id"], "base_head": receipt["base_head"],
            "candidate_sha": receipt.get("candidate_sha"), "candidate_run_id": receipt.get("candidate_run_id"),
            "artifact_hash": receipt["artifact_hash"], "target": request["target"], "returncode": rc,
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat()})
        return rc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "release"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--entry", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--expect-sha", help="candidate route: BUILD only this approved + pushed SHA")
    parser.add_argument("--candidate-run", help="Orchestrator run id of the candidate (recorded)")
    parser.add_argument("--expect-branch", help="candidate route: branch whose origin must equal the SHA")
    args = parser.parse_args()
    try:
        if args.action == "build":
            result = build(args.repo, args.entry, args.artifact,
                           expected_sha=(args.expect_sha or "").lower() or None, candidate_run_id=args.candidate_run,
                           expected_branch=args.expect_branch)
            for reason in result.get("reject_reasons") or ([result["error"]] if result.get("error") else []):
                print(f"[DCC] BUILD rejected: {reason}", file=sys.stderr)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ready" else (result.get("returncode") or 1)
        request = json.loads(args.request.read_text(encoding="utf-8"))
        return release(args.repo, request)
    except Exception as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
