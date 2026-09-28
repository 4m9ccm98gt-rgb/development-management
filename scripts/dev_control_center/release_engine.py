"""Transactional file-release primitives shared by DCC release operations.

This is the foundation of the DCC common Release / Update Engine (reference implementation:
next-day-setup `update_delta.ps1` @ 1a03178). It is used first by `restore_release` (rolling a
deployment back to a verified backup); the delta planner for UPDATE builds on the same pieces.

Guarantees provided here:
* paths are plain, relative and inside their root; reparse points (symlink / junction) are refused;
* protected (operational) paths are refused twice: when a plan is built and in every write function;
* nothing live is touched until every saved copy and staged copy is verified by SHA-256;
* files are replaced in place (os.replace, same directory), the commit file (EXE) last;
* on failure only what this transaction applied is undone, from verified saved copies;
* an exclusive lock and an in-use check (visible across PCs on a share) guard the whole operation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import uuid

RESERVED = set('<>:"|?*')


class ReleaseError(RuntimeError):
    """A release / restore must stop; nothing is (or remains) half applied unless the message says so."""

    def __init__(self, message: str, code: str = "RELEASE_STOP"):
        super().__init__(message)
        self.code = code


class RollbackIncomplete(ReleaseError):
    def __init__(self, message: str):
        super().__init__(message, "ROLLBACK_INCOMPLETE")


# ------------------------------------------------------------------ hashing / paths

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def valid_relative(rel: str) -> bool:
    if not rel or "\\" in rel or rel.startswith("/") or any(c in RESERVED for c in rel):
        return False
    return all(part and part not in (".", "..") and part.rstrip(" .") == part for part in rel.split("/"))


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def safe_join(root: Path, rel: str) -> Path:
    """`root/rel`, refusing invalid names and any reparse point on the way (existing components)."""
    if not valid_relative(rel):
        raise ReleaseError(f"invalid relative path: {rel}", "PATH_INVALID")
    if _is_reparse(root):
        raise ReleaseError(f"reparse point not allowed: {root}", "PATH_REPARSE")
    path = root
    for part in PurePosixPath(rel).parts:
        path = path / part
        if _is_reparse(path):
            raise ReleaseError(f"reparse point not allowed: {path}", "PATH_REPARSE")
    return path


@dataclass(frozen=True)
class Protected:
    """Operational data the release machinery must never write: glob patterns (posix, case-insensitive)
    on the relative path, plus file names protected wherever they are."""

    patterns: tuple[str, ...] = ()
    names: tuple[str, ...] = ()

    def __call__(self, rel: str) -> bool:
        low = rel.lower()
        if PurePosixPath(low).name in {n.lower() for n in self.names}:
            return True
        return any(fnmatch.fnmatchcase(low, p.lower()) for p in self.patterns)

    def assert_writable(self, rel: str) -> None:
        if self(rel):
            raise ReleaseError(f"protected operational path must not be written: {rel}", "PROTECTED_WRITE")


# ------------------------------------------------------------------ inventories

def scan(root: Path, *, skip_top: tuple[str, ...] = ()) -> dict[str, tuple[int, int]]:
    """rel -> (size, mtime_ns) of every file under root (metadata only, nothing is read)."""
    skip = {s.lower() for s in skip_top}
    result: dict[str, tuple[int, int]] = {}
    for folder, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(folder, root).replace("\\", "/")
        if rel_dir == ".":
            dirs[:] = [d for d in dirs if d.lower() not in skip]
        for name in files:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            try:
                info = os.stat(Path(folder) / name)
            except OSError:
                continue
            result[rel] = (info.st_size, info.st_mtime_ns)
    return result


def scan_scope(root: Path, dirs, *, top_files: bool = True) -> dict[str, tuple[int, int]]:
    """Metadata of the top-level files of `root` plus everything under the listed sub-directories only.
    Unlisted directories (e.g. the backup root with all its generations) are never entered."""
    result: dict[str, tuple[int, int]] = {}
    if top_files:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    result[entry.name] = (info.st_size, info.st_mtime_ns)
    for folder in dirs:
        base = safe_join(root, folder)
        if base.is_dir():
            result.update({f"{folder}/{rel}": value for rel, value in scan(base).items()})
    return result


def stat_files(root: Path, rels) -> dict[str, tuple[int, int] | None]:
    """(size, mtime_ns) of exactly these files (None: absent). Nothing else is looked at."""
    result = {}
    for rel in sorted(rels):
        path = safe_join(root, rel)
        try:
            info = os.stat(path)
        except FileNotFoundError:
            result[rel] = None
            continue
        result[rel] = (info.st_size, info.st_mtime_ns)
    return result


def metadata_diff(before: dict, after: dict, *, tolerance_ns: int = 2_000_000_000) -> dict[str, list[str]]:
    """Files whose presence / size / mtime differ (mtime within `tolerance_ns` counts as equal)."""
    changed = sorted(r for r in before.keys() & after.keys()
                     if before[r][0] != after[r][0] or abs(before[r][1] - after[r][1]) > tolerance_ns)
    return {"changed": changed, "created": sorted(after.keys() - before.keys()),
            "missing": sorted(before.keys() - after.keys())}


def read_key_values(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    return {k.strip(): v.strip() for k, sep, v in (line.partition(":") for line in text.splitlines()) if sep}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


# ------------------------------------------------------------------ lock / in-use (Windows share aware)

class ExclusiveLock:
    """An exclusive handle on `path` (FileShare none on Windows): a second DCC release, or the legacy
    PowerShell updater that opens the same lock file with FileShare.None, cannot run at the same time."""

    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def __enter__(self):
        if os.name == "nt":
            import _winapi

            try:
                self._handle = _winapi.CreateFile(str(self.path), 0x80000000 | 0x40000000, 0, 0, 4, 0x80, 0)  # OPEN_ALWAYS
            except OSError as exc:
                raise ReleaseError(f"another update holds the lock: {self.path} ({exc})", "LOCKED") from exc
        else:
            import fcntl

            self._handle = open(self.path, "a+")
            try:
                fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ReleaseError(f"another update holds the lock: {self.path}", "LOCKED") from exc
        return self

    def __exit__(self, *exc):
        if self._handle is not None:
            if os.name == "nt":
                import _winapi

                _winapi.CloseHandle(self._handle)
            else:
                self._handle.close()
        return False


def in_use(path: Path) -> bool:
    """True when some process (on any PC using the share) has `path` open, e.g. a running EXE."""
    if not path.exists():
        return False
    if os.name == "nt":
        import _winapi

        try:
            handle = _winapi.CreateFile(str(path), 0x80000000, 0, 0, 3, 0x80, 0)  # GENERIC_READ, share none
        except OSError:
            return True
        _winapi.CloseHandle(handle)
        return False
    return False


# ------------------------------------------------------------------ progress

class Progress:
    def __init__(self, total_stages: int, emit=print, every: int = 50):
        self.total = total_stages
        self.emit = emit
        self.every = every
        self.started = time.monotonic()

    def stage(self, number: int, title: str) -> None:
        self.emit(f"[{number}/{self.total}] {title}  (+{time.monotonic() - self.started:.1f}s)")

    def detail(self, text: str) -> None:
        self.emit(f"      {text}")

    def count(self, done: int, total: int, label: str) -> None:
        if done == total or done % self.every == 0:
            self.emit(f"      {label} {done} / {total}")


# ------------------------------------------------------------------ transaction

@dataclass
class Change:
    rel: str
    source: Path            # verified content to install
    target: Path
    expected_sha: str       # hash the target must have afterwards
    before_sha: str | None  # current target hash (None: the file does not exist yet)
    saved: Path | None = None
    staged: Path | None = None


@dataclass
class Transaction:
    """Save -> stage -> replace (commit file last) with undo of exactly the applied set."""

    target_root: Path
    save_root: Path
    protected: Protected
    commit_file: str | None = None
    progress: Progress | None = None
    applied: list[Change] = field(default_factory=list)

    def _emit(self, done, total, label):
        if self.progress:
            self.progress.count(done, total, label)

    def save(self, changes: list[Change]) -> None:
        """Verified copies of every existing file that will be replaced (the rollback material)."""
        existing = [c for c in changes if c.before_sha]
        for number, change in enumerate(existing, 1):
            self.protected.assert_writable(change.rel)
            saved = safe_join(self.save_root, change.rel)
            saved.parent.mkdir(parents=True, exist_ok=True)
            with open(change.target, "rb") as src, open(saved, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            if sha256(saved) != change.before_sha:
                raise ReleaseError(f"saved copy hash mismatch: {change.rel}", "SAVE_HASH_MISMATCH")
            change.saved = saved
            self._emit(number, len(existing), "saved")

    def stage(self, changes: list[Change]) -> None:
        """Copy every new content next to its target and verify it; no live file is touched yet.
        On any failure every staged copy is removed again."""
        try:
            self._stage(changes)
        except BaseException:
            self.cleanup(changes)
            raise

    def _stage(self, changes: list[Change]) -> None:
        for number, change in enumerate(changes, 1):
            self.protected.assert_writable(change.rel)
            target = safe_join(self.target_root, change.rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(f"{target.name}.{uuid.uuid4().hex[:12]}.dcc-stage")
            change.staged = staged
            with open(change.source, "rb") as src, open(staged, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            if sha256(staged) != change.expected_sha:
                raise ReleaseError(f"staged copy hash mismatch: {change.rel}", "STAGE_HASH_MISMATCH")
            self._emit(number, len(changes), "staged")

    def apply(self, changes: list[Change], *, before_each=None) -> None:
        """Replace targets (commit file last). Any failure undoes exactly what was applied, then raises."""
        ordered = sorted(changes, key=lambda c: c.rel == self.commit_file)
        try:
            for number, change in enumerate(ordered, 1):
                self.protected.assert_writable(change.rel)
                if change.before_sha and (not change.target.exists() or sha256(change.target) != change.before_sha):
                    raise ReleaseError(f"target changed after planning: {change.rel}", "TARGET_DRIFT")
                if not change.before_sha and change.target.exists():
                    raise ReleaseError(f"a file appeared where a new one was planned: {change.rel}", "TARGET_DRIFT")
                if before_each:
                    before_each(change)
                self.applied.append(change)
                os.replace(change.staged, change.target)
                if sha256(change.target) != change.expected_sha:
                    raise ReleaseError(f"target hash mismatch after replace: {change.rel}", "TARGET_HASH_MISMATCH")
                self._emit(number, len(ordered), "applied")
        except BaseException as failure:
            errors = self.undo()
            if errors:
                raise RollbackIncomplete(f"{failure}; ROLLBACK INCOMPLETE; recovery copies: {self.save_root}; "
                                         + "; ".join(errors)) from failure
            raise
        finally:
            self.cleanup(changes)

    def undo(self) -> list[str]:
        errors = []
        for change in reversed(self.applied):
            try:
                self.protected.assert_writable(change.rel)
                if change.before_sha:
                    if change.target.exists() and sha256(change.target) == change.before_sha:
                        continue
                    restore = change.target.with_name(f"{change.target.name}.{uuid.uuid4().hex[:12]}.dcc-undo")
                    with open(change.saved, "rb") as src, open(restore, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
                    if sha256(restore) != change.before_sha:
                        restore.unlink(missing_ok=True)
                        raise ReleaseError("undo copy hash mismatch")
                    os.replace(restore, change.target)
                elif change.target.exists():
                    change.target.unlink()  # only a file this transaction created
            except Exception as exc:  # noqa: BLE001 - collect every failure, keep undoing the rest
                errors.append(f"{change.rel}: {exc}")
        return errors

    @staticmethod
    def cleanup(changes: list[Change]) -> None:
        for change in changes:
            if change.staged is not None and change.staged.exists():
                try:
                    change.staged.unlink()
                except OSError:
                    pass
