"""Host/agent file handoff: provision a fresh container, never repair agent-owned ACLs."""
from __future__ import annotations

import csv
import os
from pathlib import Path, PureWindowsPath
import re
import stat

from .common import OrchestratorError, git, run_streaming


def _plain_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("directory is a link/reparse point or not a directory")


def prepare_worktree_access(parent: Path) -> None:
    """Called ONLY immediately after mkdtemp, before checkout or any agent runs.

    Windows Python's private temporary directory grants OWNER RIGHTS, which follows
    the *new file's* sandbox owner. Preserve that private DACL and add only this
    worker's SID with inheritable RX. No recursion, ownership change or broad group.
    """
    if os.name != "nt":
        return
    try:
        parent = Path(parent).absolute()
        for part in (parent, *parent.parents):
            _plain_directory(part)
        if any(parent.iterdir()):
            raise ValueError("container is not empty")
        # Do not trust USERNAME/USERDOMAIN supplied by the environment.
        system = Path(os.environ["SystemRoot"]) / "System32"
        identity = run_streaming([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"], timeout=30)
        rows = list(csv.reader(identity.stdout.strip().splitlines()))
        if identity.returncode or len(rows) != 1 or len(rows[0]) != 2:
            raise ValueError("cannot identify worker SID")
        sid = rows[0][1]
        if not re.fullmatch(r"S-1-5-(?:\d+-)*\d+", sid):
            raise ValueError("invalid worker SID")
        result = run_streaming([str(system / "icacls.exe"), str(parent), "/grant",
                                f"*{sid}:(OI)(CI)(RX)", "/Q"], timeout=30)
        if result.returncode or result.stderr.strip():
            # Do not log arbitrary tool output, user names or file contents.
            raise ValueError(f"icacls exit={result.returncode}, stderr_present={bool(result.stderr.strip())}")
    except (OSError, ValueError, KeyError, csv.Error, OrchestratorError) as exc:
        raise OrchestratorError(f"fresh run container access setup failed ({type(exc).__name__}: {exc})",
                                "WORKTREE_ACCESS_SETUP_FAILED") from exc


def verify_worktree_readable(worktree: Path) -> None:
    """Read every Git-visible file as the worker before diff, Tests or candidate.

    No ACL writes. Reject reparse points (including junctions), hard links, device
    paths, ADS and traversal before opening content. Git -z avoids quote/rename
    parsing and the old 400-file cap. Directory checks are cached per invocation.
    """
    root = Path(worktree).absolute()
    checked: set[Path] = set()
    rel = "."
    try:
        _plain_directory(root)
        if root.resolve(strict=True) != root:
            raise ValueError("worktree path resolves elsewhere")
        listing = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if listing.stderr.strip():
            raise OSError("Git could not enumerate the complete worktree")
        for rel in dict.fromkeys(listing.stdout.split("\0")):
            if not rel:
                continue
            windows = PureWindowsPath(rel)
            parts = rel.split("/")
            if (windows.drive or windows.root or "\\" in rel or ":" in rel
                    or any(p in ("", ".", "..") for p in parts)):
                raise ValueError("unsafe Git path")
            path = root.joinpath(*parts)
            missing = False
            for directory in reversed(path.parents):
                if directory == root or root in directory.parents:
                    if directory not in checked:
                        try:
                            _plain_directory(directory)
                        except FileNotFoundError:
                            missing = True
                            break
                        # Verify list access as well as traverse access.
                        with os.scandir(directory) as entries:
                            for _ in entries:
                                pass
                        checked.add(directory)
            if missing:
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                # A deleted tracked file is a valid change; never skip an
                # inaccessible file or a missing parent directory's access error.
                continue
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or getattr(info, "st_file_attributes", 0) & 0x400):
                raise ValueError("file is a link/reparse point or not a regular single-link file")
            with path.open("rb") as handle:
                while handle.read(1024 * 1024):
                    pass
    except ValueError as exc:
        raise OrchestratorError(f"unsafe run worktree entry {ascii(rel)} ({exc})",
                                "WORKTREE_ACCESS_UNSAFE") from exc
    except (OSError, OrchestratorError) as exc:
        raise OrchestratorError(f"run worktree unreadable at {ascii(rel)} "
                                f"(type={type(exc).__name__}, winerror={getattr(exc, 'winerror', None)}, "
                                f"errno={getattr(exc, 'errno', None)}); no ACL repair attempted",
                                "WORKTREE_ACCESS_UNREADABLE") from exc
