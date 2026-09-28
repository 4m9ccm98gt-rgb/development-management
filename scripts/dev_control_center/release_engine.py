"""Transactional file-release primitives shared by DCC release operations.

This is the foundation of the DCC common Release / Update Engine (reference implementation:
next-day-setup `update_delta.ps1` @ 1a03178). `restore_release` (rolling a deployment back to a
verified backup) and `release_update` (the common delta UPDATE) are both built only from these pieces.

Guarantees provided here:
* paths are plain, relative and inside their root; reparse points (symlink / junction) are refused;
* protected (operational) paths are refused twice: when a plan is built and in every write function;
* nothing live is touched until every saved copy and staged copy is verified by SHA-256;
* files are replaced in place (os.replace, same directory), the final-swap files (EXE) last;
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
import re
import stat
import time
import tomllib
import uuid

RESERVED = set('<>:"|?*')
ENGINE_VERSION = "dcc-release-engine/2"
REGISTRY = Path(__file__).resolve().parents[1] / "dev_control_center_repos.toml"


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


def glob_match(rel: str, pattern: str) -> bool:
    """Path-segment aware glob (case-insensitive): `*` / `?` stay inside one segment, `**` spans any depth.
    `*.txt` therefore means top-level text files only, `_internal/**` everything under `_internal`."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.fullmatch("".join(out), rel, re.IGNORECASE) is not None


# ------------------------------------------------------------------ release configuration

CONFIG_DEFAULTS = {
    "managed": [], "protected": [], "protected_names": [], "critical": [], "operational_roots": [],
    "retain": [], "records": [], "in_use": [], "final_swap": [], "legacy_locks": [], "hooks": [],
    "lock": ".dcc-release.lock", "manifest": "DCC_RELEASE_MANIFEST.json", "backup_dir": "backup",
    "backup_retention": 5, "build_info": "BUILD_INFO.txt",
    "build_info_keys": {"commit": "Git commit SHA", "version": "App version", "exe": "EXE SHA-256"},
}


def release_config(repo_name: str, registry: Path = REGISTRY) -> dict:
    """`[release.<repo>]` with the engine defaults filled in and every path it names validated."""
    with registry.open("rb") as handle:
        config = tomllib.load(handle).get("release", {}).get(repo_name)
    if not config:
        raise ReleaseError(f"[release.{repo_name}] is not configured", "CONFIG_MISSING")
    return normalize_config(config)


def normalize_config(config: dict) -> dict:
    result = {key: (dict(value) if isinstance(value, dict) else list(value) if isinstance(value, list) else value)
              for key, value in CONFIG_DEFAULTS.items()}
    result.update(config)
    result["build_info_keys"] = dict(CONFIG_DEFAULTS["build_info_keys"], **dict(config.get("build_info_keys", {})))
    protected = protected_of(result)
    names = [result["lock"], result["manifest"], *result["legacy_locks"], *result["final_swap"], *result["records"],
             *result["in_use"]] + ([result["build_info"]] if result.get("build_info") else [])
    if result.get("commit_file"):
        names.append(result["commit_file"])
    for rel in names:
        if not valid_relative(rel):
            raise ReleaseError(f"[release] invalid path: {rel}", "CONFIG_INVALID")
    for rel in [result["lock"], result["manifest"], *result["legacy_locks"], *result["final_swap"]]:
        if protected(rel):
            raise ReleaseError(f"[release] path is protected operational data: {rel}", "CONFIG_INVALID")
    for rel in [result["lock"], result["manifest"], *result["legacy_locks"]]:
        if managed(result, rel):
            raise ReleaseError(f"[release] engine record is inside the managed set: {rel}", "CONFIG_INVALID")
    if result["managed"] and not all(managed(result, rel) for rel in result["final_swap"]):
        raise ReleaseError("[release] every final_swap file must be managed", "CONFIG_INVALID")
    unknown = [h for h in result["hooks"] if h not in HOOKS]
    if unknown:
        raise ReleaseError(f"[release] unknown hook(s): {unknown} (allowed: {sorted(HOOKS)})", "CONFIG_INVALID")
    if not isinstance(result["backup_retention"], int) or result["backup_retention"] < 1:
        raise ReleaseError("[release] backup_retention must be a positive integer", "CONFIG_INVALID")
    return result


def protected_of(config: dict) -> Protected:
    return Protected(tuple(config.get("protected", [])), tuple(config.get("protected_names", [])))


def managed(config: dict, rel: str) -> bool:
    """A path the release owns: matches an include pattern and is not protected operational data."""
    return any(glob_match(rel, p) for p in config.get("managed", [])) and not protected_of(config)(rel)


def config_digest(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# Explicit, reviewed repo hooks (read-only checks run during final verification). A repo can only
# name hooks registered here; nothing is imported from configuration.
HOOKS: dict = {}


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


def operational_snapshot(target: Path, config: dict, listing: dict | None = None) -> dict[str, tuple[int, int]]:
    """Protected operational data of the live deployment: top-level files plus the configured
    `operational_roots` only. The backup root (every generation) and unrelated folders are never entered."""
    protected = protected_of(config)
    if listing is None:
        listing = scan_scope(target, config.get("operational_roots", []))
    backup = config.get("backup_dir", "backup").lower() + "/"
    return {rel: value for rel, value in listing.items() if protected(rel) and not rel.lower().startswith(backup)}


def critical_hashes(root: Path, listing: dict, names) -> dict[str, str]:
    wanted = {n.lower() for n in names}
    return {rel: sha256(safe_join(root, rel)) for rel in sorted(listing) if PurePosixPath(rel).name.lower() in wanted}


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


class LockSet:
    """The common `.dcc-release.lock` plus any legacy updater locks of the repo, all held together."""

    def __init__(self, target: Path, config: dict):
        names = [config.get("lock", ".dcc-release.lock"), *config.get("legacy_locks", [])]
        self.locks = [ExclusiveLock(safe_join(target, name)) for name in dict.fromkeys(names)]
        self._held: list[ExclusiveLock] = []

    def __enter__(self):
        try:
            for lock in self.locks:
                lock.__enter__()
                self._held.append(lock)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        for lock in reversed(self._held):
            lock.__exit__(None, None, None)
        self._held.clear()
        return False


class InUseGuard:
    """Holds the in-use files (the EXE) open with FileShare none from the in-use check until just before
    they are swapped, so no PC can start the application in between (its start fails instead of
    loading a half-updated folder). `release()` is called right before the final swap."""

    def __init__(self, paths: list[Path]):
        self.paths = paths
        self._handles: list = []

    def acquire(self) -> None:
        busy = []
        for path in self.paths:
            if not path.exists():
                continue
            if os.name != "nt":
                continue
            import _winapi

            try:
                self._handles.append(_winapi.CreateFile(str(path), 0x80000000, 0, 0, 3, 0x80, 0))
            except OSError:
                busy.append(path.name)
        if busy:
            self.release()
            raise ReleaseError(f"still in use (close the app on every PC): {busy}", "IN_USE")

    def release(self) -> None:
        if os.name == "nt":
            import _winapi

            for handle in self._handles:
                _winapi.CloseHandle(handle)
        self._handles.clear()


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
    final: tuple[str, ...] = ()               # swapped after everything else, in this order (EXE last)
    created_dirs: list[Path] = field(default_factory=list)

    def _emit(self, done, total, label):
        if self.progress:
            self.progress.count(done, total, label)

    def order(self, changes: list[Change]) -> list[Change]:
        final = [f.lower() for f in self.final]
        if self.commit_file and self.commit_file.lower() not in final:
            final.append(self.commit_file.lower())
        return sorted(changes, key=lambda c: final.index(c.rel.lower()) + 1 if c.rel.lower() in final else 0)

    def _make_parents(self, path: Path) -> None:
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for folder in reversed(missing):
            folder.mkdir()
            self.created_dirs.append(folder)

    def remove_created_dirs(self) -> None:
        """Folders this transaction created for new files, when they are empty again (deepest first)."""
        for folder in sorted(set(self.created_dirs), key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass

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
            self.remove_created_dirs()
            raise

    def _stage(self, changes: list[Change]) -> None:
        for number, change in enumerate(changes, 1):
            self.protected.assert_writable(change.rel)
            target = safe_join(self.target_root, change.rel)
            self._make_parents(target)
            staged = target.with_name(f"{target.name}.{uuid.uuid4().hex[:12]}.dcc-stage")
            change.staged = staged
            with open(change.source, "rb") as src, open(staged, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            if sha256(staged) != change.expected_sha:
                raise ReleaseError(f"staged copy hash mismatch: {change.rel}", "STAGE_HASH_MISMATCH")
            self._emit(number, len(changes), "staged")

    def apply(self, changes: list[Change], *, before_each=None, before_touch=None) -> None:
        """Replace targets (final-swap files last). Any failure undoes exactly what was applied, then raises.
        `before_touch(change)` runs before the target is first read (e.g. to let go of an in-use guard)."""
        ordered = self.order(changes)
        try:
            for number, change in enumerate(ordered, 1):
                self.protected.assert_writable(change.rel)
                if before_touch:
                    before_touch(change)
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
            self.cleanup(changes)  # unapplied staged copies first, so folders created for new files can go too
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
                    # only a file this transaction created, and only while it is still exactly what was written
                    if sha256(change.target) != change.expected_sha:
                        raise ReleaseError("a new file was changed by someone else after it was written; not removed")
                    change.target.unlink()
            except Exception as exc:  # noqa: BLE001 - collect every failure, keep undoing the rest
                errors.append(f"{change.rel}: {exc}")
        if not errors:
            self.remove_created_dirs()
        return errors

    @staticmethod
    def cleanup(changes: list[Change]) -> None:
        for change in changes:
            if change.staged is not None and change.staged.exists():
                try:
                    change.staged.unlink()
                except OSError:
                    pass


# ------------------------------------------------------------------ release manifest (schema v2)

MANIFEST_SCHEMA = 2
MANIFEST_KIND = "dcc_release_manifest"
SHA_RE = re.compile(r"^[0-9A-F]{64}$")


def validate_manifest(data, config: dict, repo_name: str) -> dict:
    """A DCC release manifest v2, structurally sound: every entry a plain managed path, unique, sized and
    hashed. Raises MANIFEST_INVALID otherwise (the caller then never trusts it)."""
    problems = []
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA or data.get("kind") != MANIFEST_KIND:
        raise ReleaseError("not a DCC release manifest v2", "MANIFEST_INVALID")
    for key in ("release_id", "deployed_commit", "build_id", "files"):
        if not data.get(key):
            problems.append(f"missing {key}")
    if data.get("repo") != repo_name:
        problems.append(f"repo {data.get('repo')} != {repo_name}")
    seen = set()
    for entry in data.get("files") or []:
        rel = entry.get("path") if isinstance(entry, dict) else None
        if (not isinstance(rel, str) or not valid_relative(rel) or not managed(config, rel) or rel.lower() in seen
                or not SHA_RE.match(str(entry.get("sha256", ""))) or not isinstance(entry.get("size"), int)
                or not isinstance(entry.get("mtime_ns"), int)):
            problems.append(f"bad entry {rel!r}")
            break
        seen.add(rel.lower())
    if problems:
        raise ReleaseError("release manifest rejected: " + "; ".join(problems), "MANIFEST_INVALID")
    return data


def read_manifest(path: Path, config: dict, repo_name: str) -> dict | None:
    """None when there is no manifest; ReleaseError(MANIFEST_INVALID) when there is one that is not sound."""
    if _is_reparse(path):
        raise ReleaseError(f"reparse point not allowed: {path}", "PATH_REPARSE")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"release manifest unreadable: {exc}", "MANIFEST_INVALID") from exc
    return validate_manifest(data, config, repo_name)


def write_manifest_atomic(target: Path, config: dict, body: dict, repo_name: str) -> str:
    """Validate, write next to the live manifest, verify the written bytes, then one os.replace.
    Returns the SHA-256 of the manifest file (recorded in production.json: the trust anchor)."""
    validate_manifest(body, config, repo_name)
    name = config["manifest"]
    protected_of(config).assert_writable(name)
    final = safe_join(target, name)
    data = json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8")
    temp = final.with_name(f"{final.name}.{uuid.uuid4().hex[:12]}.dcc-stage")
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        digest = hashlib.sha256(data).hexdigest().upper()
        if sha256(temp) != digest:
            raise ReleaseError("manifest temp copy hash mismatch", "MANIFEST_WRITE")
        os.replace(temp, final)
    finally:
        temp.unlink(missing_ok=True)
    return digest


# ------------------------------------------------------------------ changed-only backups and retention

BACKUP_PREFIX = "dcc_release_"
BACKUP_MANIFEST = "backup_manifest.json"
BACKUP_KIND = "dcc_release_backup"


def backup_folder(target: Path, config: dict, release_id: str) -> Path:
    return safe_join(target, f"{config.get('backup_dir', 'backup')}/{BACKUP_PREFIX}{now_stamp()}_{release_id[:12]}")


def engine_backups(target: Path, config: dict, repo_name: str) -> list[Path]:
    """Backup folders this engine created for this repo (by prefix AND a matching backup manifest), oldest
    first. Anything else in the backup root (legacy `update_before_*`, `rollback_before_*`, ...) is never listed."""
    root = safe_join(target, config.get("backup_dir", "backup"))
    if not root.is_dir():
        return []
    found = []
    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.name.startswith(BACKUP_PREFIX) or not entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path)
            if _is_reparse(path):
                continue
            try:
                data = json.loads((path / BACKUP_MANIFEST).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("kind") == BACKUP_KIND and data.get("repo") == repo_name and data.get("complete") is True:
                found.append(path)
    return sorted(found, key=lambda p: p.name)


def remove_tree(path: Path) -> None:
    """Delete one engine backup folder; refuses (before deleting anything) if it contains a reparse point."""
    for folder, dirs, files in os.walk(path):
        for name in dirs + files:
            if _is_reparse(Path(folder) / name):
                raise ReleaseError(f"reparse point inside a backup; not removed: {Path(folder) / name}", "PATH_REPARSE")
    for folder, dirs, files in os.walk(path, topdown=False):
        for name in files:
            os.unlink(Path(folder) / name)
        for name in dirs:
            os.rmdir(Path(folder) / name)
    os.rmdir(path)


def prune_backups(target: Path, config: dict, repo_name: str, keep_path: Path | None = None) -> dict:
    """Keep the newest `backup_retention` engine backups (always including `keep_path`). Only folders
    listed by engine_backups can be removed; failures are reported, never raised."""
    backups = engine_backups(target, config, repo_name)
    keep = set(backups[-int(config.get("backup_retention", 5)):])
    if keep_path is not None:
        keep.add(keep_path)
    removed, errors = [], []
    for path in backups:
        if path in keep:
            continue
        try:
            remove_tree(path)
            removed.append(path.name)
        except (OSError, ReleaseError) as exc:
            errors.append(f"{path.name}: {exc}")
    return {"kept": sorted(p.name for p in keep), "removed": removed, "errors": errors}