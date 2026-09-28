"""Orchestrator candidate lifecycle: one reviewed SHA from RUN_DEV to UPDATE.

    Orchestrator completed candidate -> RUN_DEV -> human approval -> push -> BUILD -> UPDATE

*Which* commit is the candidate comes only from the Orchestrator's run.json (the newest
`completed / OK` run of the repo: candidate_sha / candidate_branch / base_sha). DCC keeps, per
candidate (keyed by run id, so a new run never inherits an approval), only what happened to it:
RUN_DEV results, the human approval and the push. BUILD / UPDATE facts are the provenance
receipts, which record the SHA they were built from.

Nothing here forces, stashes, resets, rebases, cherry-picks, merges with a merge commit or
deletes a branch. The only writes to the source repo are a detached RUN worktree (Git
metadata only) and, after approval, a fast-forward of the expected branch plus a normal push.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from tools.ai_orchestrator import runstate as rs

from . import processes

SHA_RE = re.compile(r"[0-9a-f]{40}")
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "BISECT_LOG")


class CandidateError(ValueError):
    """The candidate route must stop; the message says why."""

    def __init__(self, message: str, code: str = "CANDIDATE_STOP"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Candidate:
    repo: Path          # source repo root
    run_id: str
    run_dir: Path
    sha: str            # reviewed candidate commit (source of truth: run.json)
    branch: str         # ai-candidate/... branch the Orchestrator created
    base_sha: str       # expected-branch HEAD the run started from
    source_branch: str  # expected branch (main)
    finished_at: str
    worktree: str       # the Orchestrator's own worktree, if it was kept


# ------------------------------------------------------------------ paths / small helpers

def dcc_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShizenDev" / "DCC"


def _repo_key(repo: Path) -> str:
    from .provenance import repo_key

    return repo_key(repo)


def state_path(candidate: Candidate) -> Path:
    return dcc_root() / "candidates" / _repo_key(candidate.repo) / f"{candidate.run_id}.json"


def run_worktree_path(candidate: Candidate) -> Path:
    # Same directory name as the repo: apps and tests that derive their name from the folder behave alike.
    return dcc_root() / "run-worktrees" / candidate.run_id / candidate.repo.name


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, **processes.hidden_options())


def git(repo: Path, *args: str, timeout: int = 120) -> str:
    result = _git(repo, *args, timeout=timeout)
    if result.returncode != 0:
        raise CandidateError(f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}", "GIT_FAILED")
    return result.stdout.strip()


def rev(repo: Path, ref: str) -> str:
    result = _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    return result.stdout.strip().lower() if result.returncode == 0 else ""


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    result = _git(repo, "merge-base", "--is-ancestor", older, newer)
    if result.returncode not in (0, 1):
        raise CandidateError(f"git merge-base failed: {result.stderr.strip()}", "GIT_FAILED")
    return result.returncode == 0


def tracked_dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain", "--untracked-files=no"))


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict) -> None:
    from .provenance import write_json

    write_json(path, value)


# ------------------------------------------------------------------ candidate (source of truth: run.json)

def latest_candidate(repo: Path) -> Candidate | None:
    """The newest completed / OK Orchestrator run of `repo` that produced a candidate."""
    for item in rs.list_runs(repo=str(repo)):
        record = item["record"]
        final = record.get("final_result") or {}
        sha = str(record.get("candidate_sha") or "").strip().lower()
        if record.get("stage") == rs.COMPLETED and final.get("code") == "OK" and SHA_RE.fullmatch(sha):
            return Candidate(
                repo=Path(repo).resolve(), run_id=str(record["run_id"]), run_dir=Path(item["run_dir"]), sha=sha,
                branch=str(record.get("candidate_branch") or ""),
                base_sha=str(record.get("base_sha") or "").strip().lower(),
                source_branch=str(record.get("source_branch") or ""),
                finished_at=str(record.get("finished_at") or ""), worktree=str(record.get("worktree") or ""))
    return None


def verify(candidate: Candidate, expected_branch: str | None = None) -> None:
    """Stop when the candidate commit is gone, its branch moved, or it does not descend from its base."""
    if not rev(candidate.repo, candidate.sha) == candidate.sha:
        raise CandidateError(f"candidate {candidate.sha[:12]} がsource repoにありません（消失・到達不能）", "CANDIDATE_MISSING")
    if candidate.branch:
        branch_sha = rev(candidate.repo, f"refs/heads/{candidate.branch}")
        if branch_sha and branch_sha != candidate.sha:
            raise CandidateError(f"candidate branch {candidate.branch} が {branch_sha[:12]} へ移動しています"
                                 f"（run.jsonは {candidate.sha[:12]}）", "CANDIDATE_BRANCH_MOVED")
    if (not SHA_RE.fullmatch(candidate.base_sha) or candidate.base_sha == candidate.sha
            or not is_ancestor(candidate.repo, candidate.base_sha, candidate.sha)):
        raise CandidateError("candidateがbase SHAの子孫ではありません（run.jsonと不整合）", "CANDIDATE_INCONSISTENT")
    if expected_branch and candidate.source_branch != expected_branch:
        raise CandidateError(f"candidateのbase branch {candidate.source_branch} が管理branch {expected_branch} と"
                             "異なります", "CANDIDATE_INCONSISTENT")


# ------------------------------------------------------------------ DCC-side state per candidate

def load_state(candidate: Candidate) -> dict:
    data = _read_json(state_path(candidate)) or {}
    if data.get("run_id") != candidate.run_id or data.get("candidate_sha") != candidate.sha:
        data = {}  # never reuse RUN / approval / push of another candidate
    base = {"schema": 1, "repo": str(candidate.repo), "run_id": candidate.run_id, "candidate_sha": candidate.sha,
            "candidate_branch": candidate.branch, "base_sha": candidate.base_sha, "run_dev": [], "approval": None,
            "push": None, "discarded": None, "rolled_back": None, "deployed": None}
    base.update({k: v for k, v in data.items() if k in base})
    return base


def save_state(candidate: Candidate, state: dict) -> None:
    _write_json(state_path(candidate), state)


def last_run(state: dict) -> dict | None:
    return state["run_dev"][-1] if state.get("run_dev") else None


def approval_valid(candidate: Candidate, state: dict) -> bool:
    approval, run = state.get("approval"), last_run(state)
    return bool(approval and run and approval.get("sha") == candidate.sha == run.get("sha")
                and run.get("result") == "PASS" and approval.get("run_id") == candidate.run_id
                and approval.get("run_dev_finished_at") == run.get("finished_at"))


def record_run(candidate: Candidate, entry: dict) -> dict:
    """Append one RUN_DEV result. A new RUN always clears the approval (approve what you last ran)."""
    state = load_state(candidate)
    state["run_dev"].append(entry)
    state["approval"] = None
    save_state(candidate, state)
    return state


def start_run(candidate: Candidate, entry: dict) -> dict:
    """Persist the attempt BEFORE the app starts: the approval is gone and, until this attempt completes
    successfully, nothing is approvable (a stopped / crashed RUN stays RUNNING, i.e. not PASS)."""
    return record_run(candidate, dict(entry, result="RUNNING"))


def finish_run(candidate: Candidate, started_at: str, updates: dict) -> dict:
    state = load_state(candidate)
    for entry in reversed(state["run_dev"]):
        if entry.get("started_at") == started_at and entry.get("result") == "RUNNING":
            entry.update(updates)
            break
    else:
        state["run_dev"].append(updates)
    state["approval"] = None
    save_state(candidate, state)
    return state


def approve(candidate: Candidate, expected_sha: str) -> dict:
    """Human approval of exactly the SHA that passed RUN_DEV. Never automatic."""
    verify(candidate)
    state = load_state(candidate)
    run = last_run(state)
    if expected_sha != candidate.sha:
        raise CandidateError("承認しようとしたSHAが現在のcandidateと異なります", "APPROVAL_SHA_MISMATCH")
    _refuse_if_rolled_back(state)
    if state.get("discarded"):
        raise CandidateError("破棄済みのcandidateは承認できません", "CANDIDATE_DISCARDED")
    if run is None:
        raise CandidateError("RUN_DEV未実施のcandidateは承認できません", "RUN_DEV_REQUIRED")
    if run.get("sha") != candidate.sha or run.get("result") != "PASS":
        raise CandidateError(f"最新のRUN_DEVが {run.get('sha', '')[:12]} / {run.get('result')} です。"
                             "PASSしたcandidateだけ承認できます", "RUN_DEV_NOT_PASSED")
    state["approval"] = {"sha": candidate.sha, "run_id": candidate.run_id, "at": now(),
                         "run_dev_finished_at": run.get("finished_at"), "by": os.environ.get("USERNAME", "")}
    save_state(candidate, state)
    return state


def mark_rolled_back(repo: Path, sha: str, to_commit: str) -> bool:
    """After a verified production restore away from `sha`: that candidate's lifecycle is over."""
    candidate = latest_candidate(Path(repo).resolve())
    if candidate is None or not sha or candidate.sha != sha.lower():
        return False
    state = load_state(candidate)
    state["rolled_back"] = {"at": now(), "to_commit": to_commit}
    state["approval"] = None
    save_state(candidate, state)
    return True


def mark_deployed(repo: Path, sha: str, run_id: str, build_id: str) -> bool:
    """A successful UPDATE of exactly this candidate ends its lifecycle for good (a later ordinary BUILD
    replacing the latest receipt must not revive it)."""
    candidate = latest_candidate(Path(repo).resolve())
    if candidate is None or candidate.sha != sha or candidate.run_id != run_id:
        return False
    state = load_state(candidate)
    state["deployed"] = {"at": now(), "build_id": build_id}
    save_state(candidate, state)
    return True


def revoked_shas(repo: Path) -> set[str]:
    """SHAs taken back out of production: never to be released again. Durable: rolled-back candidate
    states plus the revoked list written by every rollback (independent of the latest release attempt)."""
    from .provenance import revoked_path

    result = set()
    folder = dcc_root() / "candidates" / _repo_key(Path(repo).resolve())
    for path in folder.glob("*.json") if folder.is_dir() else []:
        data = _read_json(path) or {}
        if data.get("rolled_back") and data.get("candidate_sha"):
            result.add(str(data["candidate_sha"]).lower())
    for item in (_read_json(revoked_path(Path(repo).resolve())) or {}).get("revoked", []):
        result.add(str(item.get("sha", "")).lower())
    result.discard("")
    return result


def discard(candidate: Candidate) -> dict:
    """Explicitly leave the candidate route (back to the working-tree route). History is kept."""
    state = load_state(candidate)
    state["discarded"] = {"at": now()}
    state["approval"] = None
    save_state(candidate, state)
    return state


# ------------------------------------------------------------------ provenance records bound to the SHA

def build_record(repo: Path) -> dict | None:
    from .provenance import receipt_path

    return _read_json(receipt_path(repo))


def release_record(repo: Path) -> dict | None:
    from .provenance import release_record_path

    return _read_json(release_record_path(repo))


def production_state(repo: Path) -> dict | None:
    """What is confirmed deployed: production.json (written only by a successful UPDATE or a verified
    rollback). Failed attempts never change it. Older states without it fall back to the last record."""
    from .provenance import production_record_path

    confirmed = _read_json(production_record_path(Path(repo).resolve()))
    if confirmed:
        return {"commit": str(confirmed.get("commit") or ""), "version": confirmed.get("version") or "",
                "how": confirmed.get("how") or "", "ok": True}
    record = release_record(repo)
    if not record:
        return None
    if record.get("kind") == "rollback":
        return {"commit": str(record.get("deployed_commit") or ""), "version": record.get("app_version") or "",
                "how": f"rollback（{str(record.get('rolled_back_from') or '')[:12]} から復旧）", "ok": record.get("returncode") == 0}
    commit = str(record.get("candidate_sha") or record.get("base_head") or "")
    return {"commit": commit, "version": "", "ok": record.get("returncode") == 0,
            "how": "DCC UPDATE" if record.get("returncode") == 0 else f"DCC UPDATE失敗 rc={record.get('returncode')}"}


def _refuse_if_rolled_back(state: dict) -> None:
    if state.get("rolled_back"):
        raise CandidateError(f"本番からrollback済みのcandidateです（→ {state['rolled_back']['to_commit'][:12]}）。"
                             "再利用しません（新しいcandidate / BUILDが必要）", "CANDIDATE_ROLLED_BACK")


# ------------------------------------------------------------------ snapshot for DCC (no network)

def snapshot(repo: Path, expected_branch: str) -> dict:
    """Everything DCC shows / gates on, from durable facts. Uses local refs only (no fetch)."""
    repo = Path(repo).resolve()
    candidate = latest_candidate(repo)
    result: dict = {"candidate": None, "active": False, "error": "", "stages": [], "state": None,
                    "can_run": False, "can_approve": False, "can_push": False, "pushed": False,
                    "stale": False, "deployed": False, "mismatch": "", "production": production_state(repo)}
    if candidate is None:
        return result
    result["candidate"] = candidate
    state = load_state(candidate)
    terminal = next((k for k in ("rolled_back", "deployed", "discarded") if state.get(k)), None)
    try:
        verify(candidate, expected_branch)
    except CandidateError as exc:
        if terminal:  # history only: a finished candidate never blocks or re-enters the flow
            result.update(state=state, stages=[("Orchestrator candidate", candidate.sha,
                                                f"{terminal}（終了済み）／参考: {exc}")])
            return result
        result.update(active=True, error=str(exc))
        result["stages"] = [("Orchestrator candidate", candidate.sha, f"停止: {exc}")]
        return result
    result["state"] = state
    origin = rev(repo, f"refs/remotes/origin/{expected_branch}")
    integrated = bool(origin) and is_ancestor(repo, candidate.sha, origin)
    build = build_record(repo) or {}
    build_bound = build.get("candidate_sha") == candidate.sha and build.get("candidate_run_id") == candidate.run_id
    release = release_record(repo) or {}
    release_bound = build_bound and release.get("build_id") == build.get("build_id") \
        and release.get("candidate_sha") == candidate.sha
    deployed = bool(state.get("deployed")) or (release_bound and release.get("returncode") == 0)
    run = last_run(state)
    approved = approval_valid(candidate, state)
    pushed = bool(state.get("push")) and state["push"].get("sha") == candidate.sha
    stale = not integrated and origin not in ("", candidate.base_sha)
    active = (not state.get("discarded") and not state.get("rolled_back") and not deployed
              and (pushed or approved or not integrated))
    stages = [
        ("Orchestrator candidate", candidate.sha, f"completed / OK  run {candidate.run_id}  base {candidate.base_sha[:12]}"),
        ("RUN_DEV", run.get("sha", "") if run else "", (f"{run.get('result')} rc={run.get('returncode')}  {run.get('finished_at')}"
                                                        if run else "未実施")),
        ("Human approval", state["approval"]["sha"] if approved else "", "APPROVED" if approved else "未承認"),
        (f"origin/{expected_branch}", origin, "candidateと一致（push済み）" if origin == candidate.sha
         else ("candidateを含む" if integrated else ("base（未push）" if origin == candidate.base_sha
                                                   else "baseから移動（fast-forward不可の可能性）"))),
        ("BUILD", build.get("base_head", "") if build_bound else "",
         (f"{build.get('status')}  build {str(build.get('build_id', ''))[:8]}" if build_bound else "未実施")),
        ("UPDATE / DEPLOY", release.get("candidate_sha", "") if release_bound else "",
         (("SUCCESS" if deployed else f"FAILED rc={release.get('returncode')}") if release_bound else "未実施")),
    ]
    if state.get("rolled_back"):  # it was deployed and then taken back out of production
        stages[-1] = ("UPDATE / DEPLOY", candidate.sha,
                      f"配布後に本番からrollback済み（本番は {state['rolled_back']['to_commit'][:12]}）")
    mismatch = [name for name, sha, _ in stages if sha and name != f"origin/{expected_branch}" and sha != candidate.sha]
    if pushed and origin != candidate.sha:
        mismatch.append(f"origin/{expected_branch}")
    result.update(
        active=active, stale=stale, deployed=deployed, pushed=pushed, stages=stages,
        mismatch=", ".join(mismatch),
        can_run=active and not mismatch,
        can_approve=active and not mismatch and bool(run) and run.get("sha") == candidate.sha
        and run.get("result") == "PASS" and not approved,
        can_push=active and not mismatch and approved and not (pushed and origin == candidate.sha) and not stale,
    )
    if state.get("rolled_back"):
        result["stages"].append(("candidate", candidate.sha, f"本番からrollback済み → {state['rolled_back']['to_commit'][:12]}"
                                                             f"  {state['rolled_back']['at']}（通常ルート）"))
    if state.get("discarded"):
        result["stages"].append(("candidate", candidate.sha, f"破棄済み {state['discarded'].get('at')}（作業ツリー通常ルート）"))
    return result


# ------------------------------------------------------------------ RUN_DEV

def _worktree_head(path: Path) -> str:
    return rev(path, "HEAD")


def run_target(candidate: Candidate) -> Path:
    """A worktree whose HEAD is exactly the candidate: the Orchestrator's own if it was kept,
    otherwise a DCC-owned detached worktree. The source repo's working tree is never touched."""
    verify(candidate)
    kept = Path(candidate.worktree) if candidate.worktree else None
    if kept and kept.is_dir() and _worktree_head(kept) == candidate.sha and not tracked_dirty(kept):
        return kept
    path = run_worktree_path(candidate)
    if path.exists():
        if _worktree_head(path) == candidate.sha and not tracked_dirty(path):
            return path
        raise CandidateError(f"RUN用worktree {path} がcandidate {candidate.sha[:12]} と一致しません（手動確認が必要）",
                             "RUN_TARGET_MISMATCH")
    path.parent.mkdir(parents=True, exist_ok=True)
    git(candidate.repo, "worktree", "add", "--detach", str(path), candidate.sha, timeout=300)
    if _worktree_head(path) != candidate.sha:
        raise CandidateError("RUN用worktreeのHEADがcandidateと一致しません", "RUN_TARGET_MISMATCH")
    return path


def _seed_path(root: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if not relative or Path(relative).is_absolute() or Path(relative).drive or ".." in parts:
        raise CandidateError(f"seed pathはrepo内の相対パスだけです: {relative}", "SEED_INVALID")
    path = root / relative
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise CandidateError(f"seed pathにリンクは使えません: {relative}", "SEED_LINK")
    if not path.resolve().is_relative_to(root.resolve()):
        raise CandidateError(f"seed pathがrepo外です: {relative}", "SEED_INVALID")
    return path


def _seed_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    found = []
    for folder, dirs, files in os.walk(path):
        for name in (*dirs, *files):
            item = Path(folder) / name
            if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                raise CandidateError(f"seed内にリンクがあります（コピーしません）: {item}", "SEED_LINK")
        found += [Path(folder) / name for name in files]
    return found


def seed_stamp(repo: Path, paths: list[str]) -> dict:
    """Size / mtime of every source seed file: proof that RUN_DEV wrote nothing back."""
    stamp = {}
    for relative in paths:
        path = _seed_path(repo, relative)
        if path.exists():
            for item in _seed_files(path):
                st = item.stat()
                stamp[item.relative_to(repo).as_posix()] = (st.st_size, st.st_mtime_ns)
    return stamp


def seed_runtime_data(candidate: Candidate, target: Path, paths: list[str]) -> list[dict]:
    """One-way copy of the repo's git-ignored runtime data (settings, saved data) from the source repo
    into the candidate worktree, refreshed on every RUN_DEV. The RUN works on the copies only; nothing
    is ever copied back. A path that Git tracks could overwrite candidate code, so it is refused."""
    source = candidate.repo
    if target.resolve() == source.resolve():
        raise CandidateError("RUN対象がsource repoです（seedしません）", "RUN_TARGET_MISMATCH")
    results = []
    for relative in paths:
        src, dst = _seed_path(source, relative), _seed_path(target, relative)
        if _git(source, "check-ignore", "-q", "--", relative).returncode != 0:
            raise CandidateError(f"seed {relative} はsourceでgit管理外（ignored）ではありません", "SEED_NOT_IGNORED")
        if git(target, "ls-files", "--", relative):
            raise CandidateError(f"seed {relative} はcandidateでGit管理されています（上書きしません）", "SEED_TRACKED")
        if not src.exists():
            results.append({"path": relative, "status": "missing"})
            continue
        files = _seed_files(src)
        if dst.is_dir():
            shutil.rmtree(dst)  # inside the candidate worktree only: refresh from the source every RUN
        elif dst.exists():
            dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        results.append({"path": relative, "status": "copied", "files": len(files),
                        "bytes": sum(item.stat().st_size for item in files)})
    return results


def _run_entrypoint(target: Path, name: str, venv_root: Path) -> int:
    """The registered RUN body on the candidate worktree, with the source repo's `.venv`."""
    command = [processes.console_python(), "-u", "-B", "-m", "scripts.dev_control_center.entrypoints", "run",
               "--repo", str(target), "--name", name, "--venv-root", str(venv_root)]
    return processes.stream(command, cwd=Path(__file__).resolve().parents[2], emit=processes.forward)


def run_dev(repo: Path, expected_branch: str, expected_sha: str, *, runner=None) -> int:
    """Worker body of RUN_DEV: prove the target is the candidate, run it, prove it still is, record."""
    candidate = latest_candidate(Path(repo).resolve())
    if candidate is None:
        raise CandidateError("Orchestrator candidateがありません", "CANDIDATE_MISSING")
    if candidate.sha != expected_sha:
        raise CandidateError(f"開始確認後にcandidateが {expected_sha[:12]} → {candidate.sha[:12]} へ変わりました",
                             "CANDIDATE_CHANGED")
    verify(candidate, expected_branch)
    _refuse_if_rolled_back(load_state(candidate))
    if load_state(candidate).get("discarded"):
        raise CandidateError("破棄済みのcandidateです", "CANDIDATE_DISCARDED")
    from . import entrypoints

    target = run_target(candidate)
    name = candidate.repo.name
    try:
        plan = entrypoints.plan_run(target, name=name, venv_root=candidate.repo)
        entry, command, cwd = plan.entrypoint, " ".join(plan.command), str(plan.cwd)
    except ValueError as exc:
        if name in entrypoints.run_specs():
            raise CandidateError(str(exc), "RUN_ENTRYPOINT_MISSING") from exc
        entry, command, cwd = "(registered non-Python RUN)", "entrypoints.run", str(target)
    head_before = _worktree_head(target)
    if head_before != candidate.sha:
        raise CandidateError("RUN対象のHEADがcandidateと一致しません", "RUN_TARGET_MISMATCH")
    if tracked_dirty(target):
        raise CandidateError("RUN対象worktreeのGit管理ファイルが変更されています（candidateそのものではない）",
                             "RUN_TARGET_DIRTY")
    seeds = list(entrypoints.run_specs().get(name, {}).get("seed", []))
    source_before = seed_stamp(candidate.repo, seeds)
    seeded = seed_runtime_data(candidate, target, seeds)
    started = now()
    for line in (f"run id: {candidate.run_id}", f"repo: {candidate.repo}", f"candidate SHA: {candidate.sha}",
                 f"candidate branch: {candidate.branch}", f"RUN target: {target}", f"cwd: {cwd}",
                 f"entrypoint: {entry}", f"command: {command}", f"start: {started}"):
        print(f"[RUN_DEV] {line}", flush=True)
    for item in seeded:
        detail = f"{item['files']} files / {item['bytes']:,} bytes" if item["status"] == "copied" else "sourceに無いためskip"
        print(f"[RUN_DEV] seed (source → candidate、一方向): {item['path']}  {detail}", flush=True)
    attempt = {"sha": candidate.sha, "run_id": candidate.run_id, "target": str(target), "cwd": cwd,
               "entrypoint": entry, "command": command, "head_before": head_before, "seeded": seeded,
               "started_at": started}
    start_run(candidate, attempt)  # interrupted from here on = not approvable
    rc = (runner or _run_entrypoint)(target, name, candidate.repo)
    head_after = _worktree_head(target)
    clean_after = not tracked_dirty(target)
    finished = now()
    source_after = seed_stamp(candidate.repo, seeds)
    source_changed = sorted(k for k in set(source_before) | set(source_after) if source_before.get(k) != source_after.get(k))
    result = "PASS" if rc == 0 and head_after == candidate.sha and clean_after else "FAIL"
    finish_run(candidate, started, dict(attempt, result=result, returncode=rc, head_after=head_after,
                                        tracked_clean_after=clean_after, source_seed_changed=source_changed,
                                        finished_at=finished))
    print(f"[RUN_DEV] stop: {finished}  exit code: {rc}  executed SHA: {head_after}  result: {result}", flush=True)
    if not clean_after:
        print("[RUN_DEV] STOP: RUN中にGit管理ファイルが変更されました（検証したコードがcandidateと一致しない）。承認できません",
              flush=True)
    if source_changed:
        print("[RUN_DEV] 注意: RUN中にsource側のランタイムデータが変わりました（DCCは書き戻していません。"
              f"source側で別途アプリ等が動いていた可能性）: {', '.join(source_changed[:10])}", flush=True)
    if head_after != candidate.sha:
        print(f"[RUN_DEV] STOP: RUN中にHEADが {head_after[:12]} へ変わりました。承認できません", flush=True)
    return 0 if result == "PASS" else (rc or 1)


# ------------------------------------------------------------------ push (same SHA, fast-forward only)

def _fetch(repo: Path, branch: str) -> str:
    refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
    git(repo, "fetch", "--prune", "origin", refspec, timeout=300)
    return rev(repo, f"refs/remotes/origin/{branch}")


def remote_head(repo: Path, branch: str) -> str:
    line = git(repo, "ls-remote", "origin", f"refs/heads/{branch}", timeout=300)
    return line.split()[0].lower() if line else ""


def check_source(repo: Path, branch: str) -> None:
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    busy = [name for name in IN_PROGRESS if (git_dir / name).exists()]
    if busy:
        raise CandidateError("source repoでGit操作が進行中です: " + ", ".join(busy), "SOURCE_OPERATION_IN_PROGRESS")
    current = git(repo, "branch", "--show-current")
    if current != branch:
        raise CandidateError(f"source repoが {current or 'detached'} です。{branch} へ切り替えてから再実行してください",
                             "WRONG_BRANCH")
    if tracked_dirty(repo):
        raise CandidateError("source repoに未コミット変更があります（stash / resetは行いません）", "SOURCE_DIRTY")


def push(repo: Path, expected_branch: str, expected_sha: str) -> dict:
    """Fast-forward the expected branch to the approved candidate and push exactly that SHA."""
    candidate = latest_candidate(Path(repo).resolve())
    if candidate is None or candidate.sha != expected_sha:
        raise CandidateError("push確認後にcandidateが変わりました", "CANDIDATE_CHANGED")
    verify(candidate, expected_branch)
    state = load_state(candidate)
    _refuse_if_rolled_back(state)
    if state.get("discarded"):
        raise CandidateError("破棄済みのcandidateです", "CANDIDATE_DISCARDED")
    if not approval_valid(candidate, state):
        raise CandidateError("RUN_DEVで承認されたcandidateではありません（承認前・RUN後の再承認待ち・SHA不一致）",
                             "NOT_APPROVED")
    sha, repo = candidate.sha, candidate.repo
    print(f"[PUSH] candidate SHA: {sha}  approved: {state['approval']['at']}  run {candidate.run_id}", flush=True)
    check_source(repo, expected_branch)
    origin = _fetch(repo, expected_branch)
    local = rev(repo, "HEAD")
    print(f"[PUSH] local {expected_branch}: {local}  origin/{expected_branch}: {origin}  base: {candidate.base_sha}",
          flush=True)
    if origin not in (candidate.base_sha, sha) or local not in (candidate.base_sha, sha):
        raise CandidateError(f"{expected_branch} がOrchestrator開始時のbase {candidate.base_sha[:12]} から移動しています"
                             f"（local {local[:12]} / origin {origin[:12]}）。fast-forwardできないため停止します。"
                             "再Orchestratorまたは人間の判断が必要です", "BASE_MOVED")
    if local != sha:
        git(repo, "merge", "--ff-only", sha, timeout=300)
    if rev(repo, "HEAD") != sha:
        raise CandidateError("fast-forward後のHEADがcandidateと一致しません", "FF_MISMATCH")
    if origin != sha:
        git(repo, "push", "origin", f"{sha}:refs/heads/{expected_branch}", timeout=600)  # never --force
    pushed = remote_head(repo, expected_branch)
    fetched = _fetch(repo, expected_branch)
    if not (pushed == fetched == sha):
        raise CandidateError(f"push後のorigin/{expected_branch} ({pushed[:12]}) がcandidateと一致しません", "PUSH_MISMATCH")
    state = load_state(candidate)
    state["push"] = {"sha": sha, "origin_sha": pushed, "from": origin, "at": now()}
    save_state(candidate, state)
    print(f"[PUSH] origin/{expected_branch} == candidate {sha}", flush=True)
    return state


# ------------------------------------------------------------------ BUILD / UPDATE gates

def build_gate(repo: Path, expected_branch: str) -> Candidate | None:
    """None: no active candidate (working-tree route). Otherwise the candidate BUILD may use,
    after proving approved == pushed == local HEAD == origin (fresh) and a clean tree."""
    snap = snapshot(repo, expected_branch)
    if not snap["active"]:
        return None
    candidate = snap["candidate"]
    if snap["error"]:
        raise CandidateError(snap["error"], "CANDIDATE_STOP")
    state = snap["state"]
    if not approval_valid(candidate, state):
        raise CandidateError(f"Orchestrator candidate {candidate.sha[:12]} がRUN_DEV承認前です。"
                             "RUN_DEV → 承認 → push の後にBUILDします（破棄すれば作業ツリーの通常ルート）", "NOT_APPROVED")
    if not snap["pushed"]:
        raise CandidateError(f"承認済みcandidate {candidate.sha[:12]} が未pushです。pushしてからBUILDします", "NOT_PUSHED")
    check_source(candidate.repo, expected_branch)
    local, remote = rev(candidate.repo, "HEAD"), remote_head(candidate.repo, expected_branch)
    values = {"approved": state["approval"]["sha"], "pushed": state["push"]["sha"], "local": local, "origin": remote}
    if set(values.values()) != {candidate.sha}:
        raise CandidateError("SHA不一致のためBUILDしません: " + ", ".join(f"{k}={v[:12]}" for k, v in values.items()),
                             "SHA_MISMATCH")
    return candidate


def release_expectation(repo: Path, expected_branch: str) -> Candidate | None:
    """None: working-tree route. Otherwise UPDATE must deploy the BUILD of exactly this candidate."""
    snap = snapshot(repo, expected_branch)
    if not snap["active"]:
        return None
    if snap["error"]:
        raise CandidateError(snap["error"], "CANDIDATE_STOP")
    candidate, state = snap["candidate"], snap["state"]
    if not (approval_valid(candidate, state) and snap["pushed"]):
        raise CandidateError(f"Orchestrator candidate {candidate.sha[:12]} が承認・push前です。UPDATEしません", "NOT_PUSHED")
    return candidate


# ------------------------------------------------------------------ CLI (DCC workers)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run-dev", "push"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--expect-sha", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "run-dev":
            return run_dev(args.repo, args.branch, args.expect_sha.lower())
        push(args.repo, args.branch, args.expect_sha.lower())
        return 0
    except CandidateError as exc:
        print(f"[{args.action.upper()}] STOP ({exc.code}): {exc}", flush=True)
        return 1
    except subprocess.TimeoutExpired as exc:
        print(f"[{args.action.upper()}] STOP: timeout {exc}", flush=True)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        getattr(stream, "reconfigure", lambda **_: None)(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(main())
