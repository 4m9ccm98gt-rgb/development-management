"""DCC common UPDATE engine: a verified delta release of a BUILD artifact into a deployment folder.

    plan    : dry-run, read-only on the target. Provenance (receipt / candidate / origin / BUILD_INFO),
              production (DCC production record vs the live deployment) and release-manifest trust, then the
              delta of the managed files only. The plan is stored locally and bound to a digest.
    execute : a reviewed plan whose id was confirmed. Everything the plan depends on is proved again before
              the first write; then lock -> changed-only backup -> stage -> in-use guard -> replace (EXE last)
              -> final verification -> release manifest v2 -> DCC production record.
              Any failure undoes exactly what this update applied; an undo that can not complete is
              ROLLBACK_INCOMPLETE (recovery copies named) and nothing is recorded as production.

Repo specifics come only from `[release.<repo>]` (see release_engine.CONFIG_DEFAULTS); the safety
primitives are release_engine's, shared with restore_release.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import time
import uuid

from . import provenance
from .release_engine import (
    BACKUP_KIND, BACKUP_MANIFEST, ENGINE_VERSION, HOOKS, MANIFEST_KIND, MANIFEST_SCHEMA, Change, InUseGuard,
    LockSet, Progress, ReleaseError, RollbackIncomplete, Transaction, backup_folder, config_digest,
    critical_hashes, glob_match, in_use, managed, metadata_diff, now_stamp, operational_snapshot, protected_of,
    prune_backups, read_key_values, read_manifest, release_config, remove_tree, safe_join, scan, scan_scope, sha256,
    stat_files, valid_relative, write_json, write_manifest_atomic,
)

STAGES = ("Provenance verification", "Production verification", "Calculating delta", "Backing up changed files",
          "Staging and verifying", "Applying update", "Final verification")
UNDIGESTED = {"plan_id", "timing_seconds", "created_at", "in_use_now", "estimated_execute_seconds"}
LEFTOVER_SUFFIXES = (".dcc-stage", ".dcc-undo")


# ------------------------------------------------------------------ local DCC state

def engine_repo(repo_name: str) -> bool:
    """DCC's UPDATE of this repo goes through the common engine (`engine = "dcc"` in its [release] table)."""
    try:
        return release_config(repo_name).get("engine") == "dcc"
    except ReleaseError:
        return False


def state_dir(repo: Path) -> Path:
    return provenance.state_root() / provenance.repo_key(repo)


def plans_dir(repo: Path) -> Path:
    return state_dir(repo) / "update-plans"


def inflight_path(repo: Path) -> Path:
    """Present from the first write to the share until the update ended cleanly (success, or failure with a
    complete undo). Left behind by ROLLBACK_INCOMPLETE or a killed process: the next plan stops on it."""
    return state_dir(repo) / "update-inflight.json"


def plan_digest(body: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in body.items() if k not in UNDIGESTED}, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _stop(message: str, code: str) -> ReleaseError:
    return ReleaseError(message, code)


def _stats(values: dict) -> dict:
    return {rel: list(value) if value else None for rel, value in sorted(values.items())}


# ------------------------------------------------------------------ 1. provenance

def verify_provenance(repo: Path, branch: str, config: dict) -> dict:
    """The BUILD to deploy, proved from DCC's receipt: ready, not revoked, artifact and inputs unchanged,
    built from a clean tree whose SHA is local HEAD == origin/<branch> (candidate route: also the approved +
    pushed candidate SHA), and the artifact's BUILD_INFO names exactly that SHA."""
    try:
        receipt = provenance.read_receipt(repo)
        artifact = Path(receipt["artifact"])
        if artifact.resolve() != (repo / config["artifact"]).resolve():
            raise ValueError(f"the receipt's artifact {artifact} is not the configured {config['artifact']}")
        if receipt.get("dirty"):
            raise ValueError("the BUILD was made from a dirty working tree; it is never released")
        binding = provenance.candidate_binding(repo, branch)
        built = str(receipt["base_head"]).lower()
        if binding:
            provenance._require_candidate_artifact(repo, receipt, binding["expected_sha"], binding["expected_branch"])
        head = provenance.git(repo, "rev-parse", "HEAD").lower()
        line = provenance.git(repo, "ls-remote", "origin", f"refs/heads/{branch}")
        origin = line.split()[0].lower() if line else ""
        if not built == head == origin:
            raise ValueError(f"built {built[:12]} / local HEAD {head[:12]} / origin/{branch} {origin[:12]} differ; "
                             "only a pushed commit is released")
    except ReleaseError:
        raise
    except Exception as exc:  # provenance / candidate / git failures all stop the same way
        raise _stop(str(exc), "PROVENANCE") from exc
    info = {}
    if config.get("build_info"):
        info = read_key_values(safe_join(artifact, config["build_info"]))
        keys = config["build_info_keys"]
        if info.get(keys["commit"], "").lower() != built:
            raise _stop(f"the artifact's {config['build_info']} names {info.get(keys['commit']) or '(none)'}, "
                        f"not the built {built[:12]}", "BUILD_INFO_MISMATCH")
    return {"route": "candidate" if binding else "working-tree", "branch": branch, "binding": binding,
            "build_id": receipt["build_id"], "base_head": built, "artifact": str(artifact.resolve()),
            "artifact_hash": receipt["artifact_hash"], "inputs_hash": receipt.get("inputs_hash"),
            "build_finished_at": receipt.get("finished_at"), "head": head, "origin": origin, "build_info": info}


def build_inventory(artifact: Path, config: dict, prov: dict) -> tuple[dict, list[str]]:
    """Managed files of the artifact (rel -> size / sha256) and the build files excluded as protected."""
    protected = protected_of(config)
    files, excluded = {}, []
    for rel, (size, _) in sorted(scan(artifact).items()):
        if not valid_relative(rel):
            raise _stop(f"the build contains an invalid path: {rel}", "PATH_INVALID")
        if not any(glob_match(rel, p) for p in config["managed"]):
            continue
        if protected(rel):
            excluded.append(rel)
            continue
        files[rel] = {"size": size, "sha256": sha256(safe_join(artifact, rel))}
    lower = {rel.lower(): rel for rel in files}
    if len(lower) != len(files):
        raise _stop("the build has paths that differ only in case", "PATH_INVALID")
    missing = [rel for rel in config["final_swap"] if rel.lower() not in lower]
    if missing:
        raise _stop(f"the build lacks its final-swap files: {missing}", "BUILD_INCOMPLETE")
    exe_key = config["build_info_keys"].get("exe")
    if config.get("build_info") and exe_key and config["final_swap"]:
        exe = lower[config["final_swap"][-1].lower()]
        if files[exe]["sha256"] != prov["build_info"].get(exe_key, "").upper():
            raise _stop(f"the artifact's {exe} does not match its {config['build_info']} {exe_key}", "BUILD_INFO_MISMATCH")
    return files, excluded


# ------------------------------------------------------------------ 2. production + manifest trust

def resolve_target(repo: Path, artifact: Path, target: Path, config: dict) -> Path:
    provenance.no_links(target)
    target = target.resolve()
    child, exe = config.get("child_target"), (config["final_swap"] or [None])[-1]
    if child and exe and not (target / exe).exists() and (target / child / exe).exists():
        target = target / child
    if not target.is_dir() or (target / ".git").exists():
        raise _stop(f"the target must be an existing deployment folder (not a git repo): {target}", "TARGET_INVALID")
    for source in (repo.resolve(), artifact.resolve()):
        if target.is_relative_to(source) or source.is_relative_to(target):
            raise _stop("the target overlaps the source repo or the artifact", "TARGET_INVALID")
    return target


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify_production(repo: Path, target: Path, config: dict, repo_name: str) -> dict:
    """What is live, and whether the release manifest there may be used as the delta baseline."""
    from .candidate import revoked_shas

    keys = config["build_info_keys"]
    live_info = read_key_values(safe_join(target, config["build_info"])) if config.get("build_info") else {}
    live_commit = live_info.get(keys["commit"], "").lower()
    record = _read_json(provenance.production_record_path(repo))
    if record and config.get("build_info") and str(record.get("commit", "")).lower() != live_commit:
        raise _stop(f"DCC production record {str(record.get('commit'))[:12]} differs from the live "
                    f"{config['build_info']} {live_commit[:12] or '(none)'}; reconcile before any UPDATE",
                    "PRODUCTION_MISMATCH")
    if live_commit and live_commit in revoked_shas(repo):
        raise _stop(f"the live deployment is a revoked SHA {live_commit[:12]}; reconcile before any UPDATE",
                    "PRODUCTION_REVOKED")
    manifest_path = safe_join(target, config["manifest"])
    reasons, manifest, manifest_sha = [], None, None
    try:
        manifest = read_manifest(manifest_path, config, repo_name)
    except ReleaseError as exc:
        if exc.code == "PATH_REPARSE":
            raise
        reasons.append(str(exc))
    if manifest is None and not reasons:
        reasons.append("no DCC release manifest in the target yet")
    if manifest is not None:
        manifest_sha = sha256(manifest_path)
        entries = {e["path"].lower(): e for e in manifest["files"]}
        if config.get("build_info") and str(manifest["deployed_commit"]).lower() != live_commit:
            reasons.append(f"manifest commit {str(manifest['deployed_commit'])[:12]} != live {config['build_info']} "
                           f"{live_commit[:12]}")
        if not record:
            reasons.append("no DCC production record")
        else:
            if str(record.get("commit", "")).lower() != str(manifest["deployed_commit"]).lower():
                reasons.append("manifest commit != DCC production record")
            if record.get("release_id") != manifest["release_id"]:
                reasons.append("manifest release id != DCC production record")
            if str(record.get("manifest_sha256", "")).upper() != manifest_sha:
                reasons.append("manifest file hash != the one recorded at release (edited or replaced)")
        for rel in dict.fromkeys([*config["final_swap"], *([config["build_info"]] if config.get("build_info") else [])]):
            entry, path = entries.get(rel.lower()), safe_join(target, rel)
            if entry is None:
                reasons.append(f"manifest lacks {rel}")
            elif not path.is_file() or sha256(path) != entry["sha256"]:
                reasons.append(f"live {rel} differs from the manifest")
        exe_key = keys.get("exe")
        if config.get("build_info") and exe_key and config["final_swap"]:
            exe = entries.get(config["final_swap"][-1].lower())
            if exe and exe["sha256"] != live_info.get(exe_key, "").upper():
                reasons.append(f"manifest {config['final_swap'][-1]} != live {config['build_info']} {exe_key}")
    trusted = manifest is not None and not reasons
    return {"record": record, "live_build_info": live_info, "live_commit": live_commit,
            "manifest_sha256": manifest_sha, "manifest_trusted": trusted, "trust_reasons": reasons,
            "previous": ({"release_id": manifest["release_id"], "commit": manifest["deployed_commit"]}
                         if trusted else ({"release_id": (record or {}).get("release_id"), "commit": live_commit or None}
                                          if (record or live_commit) else None)),
            "previous_files": ({e["path"]: {k: e[k] for k in ("size", "sha256", "mtime_ns")} for e in manifest["files"]}
                               if trusted else {})}


# ------------------------------------------------------------------ 3. delta

def _collisions(target: Path, build: dict) -> list[str]:
    found = []
    for rel in build:
        path = safe_join(target, rel)
        if path.exists() and not path.is_file():
            found.append(f"{rel}: a folder is where the build has a file")
        for parent in PurePosixPath(rel).parents:
            if str(parent) != "." and safe_join(target, parent.as_posix()).is_file():
                found.append(f"{rel}: {parent.as_posix()} is a file")
                break
    return found


def compute_delta(target: Path, build: dict, production: dict, config: dict, progress: Progress) -> dict:
    protected = protected_of(config)
    previous = production["previous_files"]
    trusted = production["manifest_trusted"]
    prev_lower = {rel.lower(): rel for rel in previous}
    build_lower = {rel.lower() for rel in build}
    considered = sorted(set(build) | set(previous))
    for rel in considered:
        protected.assert_writable(rel)  # plan-time guard: operational data is never a candidate
    collisions = _collisions(target, build)
    stop_reasons = [f"PATH_COLLISION {c}" for c in collisions]
    colliding = {c.split(":", 1)[0] for c in collisions}
    live = stat_files(target, considered)
    files, hashed, hash_seconds, shortcut = [], 0, 0.0, 0
    for number, rel in enumerate(sorted(build), 1):
        item = {"path": rel, "size": build[rel]["size"], "build_sha256": build[rel]["sha256"],
                "live_sha256": None, "live_stat": list(live[rel]) if live[rel] else None, "drift": False}
        prev = previous.get(prev_lower.get(rel.lower(), ""))
        if rel in colliding:
            item["category"] = "collision"  # a stop reason; never read or written
        elif live[rel] is None:
            item["category"] = "new"
        else:
            if trusted and prev is None:
                stop_reasons.append(f"PATH_COLLISION {rel}: an unmanaged file is where the build adds a new file")
            if trusted and prev and list(live[rel]) == [prev["size"], prev["mtime_ns"]]:
                item["live_sha256"] = prev["sha256"]  # metadata equals the verified release: no read needed
                shortcut += 1
            else:
                started = time.monotonic()
                item["live_sha256"] = sha256(safe_join(target, rel))
                hash_seconds += time.monotonic() - started
                hashed += live[rel][0]
                item["drift"] = bool(trusted and prev and item["live_sha256"] != prev["sha256"])
            item["category"] = "unchanged" if item["live_sha256"] == item["build_sha256"] else "modified"
        files.append(item)
        progress.count(number, len(build), "managed files compared")
    deletions, gone = [], []
    for rel in sorted(previous):
        if rel.lower() in build_lower or protected(rel):
            continue
        if live.get(rel) is None:
            gone.append(rel)
        else:
            deletions.append({"path": rel, "size": previous[rel]["size"], "sha256": previous[rel]["sha256"]})
    return {"files": files, "deletions": deletions, "gone": gone, "live": live, "stop_reasons": stop_reasons,
            "hashed_bytes": hashed, "hash_seconds": hash_seconds, "shortcut": shortcut}


def _scope(target: Path, build: dict, config: dict) -> dict:
    """Metadata of the top-level files, the folders the release manages and the operational roots only."""
    dirs = {PurePosixPath(rel).parts[0] for rel in build if "/" in rel} | set(config["operational_roots"])
    return scan_scope(target, sorted(d for d in dirs if safe_join(target, d).is_dir()))


# ------------------------------------------------------------------ plan (dry-run)

def plan(repo: Path, target: Path, *, branch: str = "main", repo_name: str | None = None, config: dict | None = None,
         acknowledge_orphans: bool = False, out: Path | None = None, emit=print) -> dict:
    """Read-only on the target. Writes the plan to local DCC state and returns it."""
    repo = Path(repo).resolve()
    repo_name = repo_name or repo.name
    config = config or release_config(repo_name)
    progress = Progress(7, emit)
    timing, started = {}, time.monotonic()
    stop_reasons = []
    if inflight_path(repo).exists():  # before anything else: the target may be half updated
        marker = _read_json(inflight_path(repo)) or {}
        raise _stop(f"a previous UPDATE did not finish (release {str(marker.get('release_id', '?'))[:12]}, target "
                    f"{marker.get('target')}, recovery copies {marker.get('backup')}). Verify the target, restore it "
                    "if needed, then clear the marker (release_update clear-interrupted)", "INTERRUPTED")

    t = time.monotonic()
    progress.stage(1, STAGES[0])
    prov = verify_provenance(repo, branch, config)
    artifact = Path(prov["artifact"])
    build, protected_in_build = build_inventory(artifact, config, prov)
    progress.detail(f"BUILD {prov['build_id'][:8]} = {prov['base_head'][:12]} ({prov['route']}; local HEAD == "
                    f"origin/{branch}); {len(build)} managed files, {len(protected_in_build)} protected build files excluded")
    timing["provenance_s"] = time.monotonic() - t

    t = time.monotonic()
    progress.stage(2, STAGES[1])
    target = resolve_target(repo, artifact, Path(target), config)
    production = verify_production(repo, target, config, repo_name)
    progress.detail(f"production {production['live_commit'][:12] or '(none)'} -> new build {prov['base_head'][:12]}")
    progress.detail("release manifest: " + ("trusted (metadata shortcut enabled)" if production["manifest_trusted"]
                                            else "not trusted -> full managed-file verification ("
                                            + "; ".join(production["trust_reasons"]) + ")"))
    timing["production_s"] = time.monotonic() - t

    t = time.monotonic()
    progress.stage(3, STAGES[2])
    listing_before = _scope(target, build, config)
    operational_before = operational_snapshot(target, config, listing_before)
    critical = critical_hashes(target, operational_before, config["critical"])
    delta = compute_delta(target, build, production, config, progress)
    stop_reasons += delta["stop_reasons"]
    if delta["deletions"] and not acknowledge_orphans:
        stop_reasons.append("DELETION_CANDIDATES managed by the previous release but not in the new build: "
                            + ", ".join(d["path"] for d in delta["deletions"][:10]))
    known = {rel.lower() for rel in build} | {rel.lower() for rel in production["previous_files"]}
    engine_names = {config["lock"].lower(), config["manifest"].lower(), *(n.lower() for n in config["legacy_locks"])}
    protected = protected_of(config)
    leftovers = sorted(rel for rel in listing_before if rel.lower().endswith(LEFTOVER_SUFFIXES))
    if leftovers:
        stop_reasons.append(f"LEFTOVER staging files of an interrupted operation: {leftovers[:10]}")
    retained = sorted(rel for rel in listing_before
                      if rel.lower() not in known and rel.lower() not in engine_names and not protected(rel)
                      and not rel.lower().endswith(LEFTOVER_SUFFIXES))
    timing["delta_s"] = time.monotonic() - t

    guard_after = stat_files(target, [f["path"] for f in delta["files"]] + [d["path"] for d in delta["deletions"]]
                             + delta["gone"])
    if any(guard_after[rel] != delta["live"].get(rel) for rel in guard_after):
        raise _stop("the deployment changed while planning; plan again", "PLAN_UNSTABLE")
    operational_after = operational_snapshot(target, config, _scope(target, build, config))

    counts = {c: [f for f in delta["files"] if f["category"] == c] for c in ("unchanged", "modified", "new")}
    summary = {
        "managed": len(build), "unchanged": len(counts["unchanged"]), "modified": len(counts["modified"]),
        "new": len(counts["new"]), "deletion_candidates": len(delta["deletions"]), "gone": len(delta["gone"]),
        "retained": len(retained), "protected_live": len(operational_before),
        "protected_in_build": len(protected_in_build), "drift_repaired": sum(1 for f in counts["modified"] if f["drift"]),
        "backup_files": len(counts["modified"]),
        "copied_bytes": sum(f["size"] for f in counts["modified"] + counts["new"]),
        "backup_bytes": sum(f["live_stat"][0] for f in counts["modified"]),
        "hashed_live_bytes": delta["hashed_bytes"], "metadata_shortcut_files": delta["shortcut"],
    }
    for name in ("unchanged", "modified", "new", "deletion_candidates", "retained", "protected_live"):
        progress.detail(f"{name}: {summary[name]}")
    progress.detail(f"copy {summary['copied_bytes']:,} bytes / backup {summary['backup_files']} files "
                    f"{summary['backup_bytes']:,} bytes")
    for number, title in enumerate(STAGES[3:], 4):
        progress.stage(number, f"{title} (dry-run: nothing written to the target)")
    rate = delta["hashed_bytes"] / delta["hash_seconds"] if delta["hash_seconds"] > 0.05 else 20_000_000
    estimate = (2 * summary["backup_bytes"] + 3 * summary["copied_bytes"]) / max(rate, 1_000_000) \
        + 2 * timing["production_s"] + timing["delta_s"] + 2
    body = {
        "schema": 1, "kind": "update_plan", "engine_version": ENGINE_VERSION, "repo": str(repo), "repo_name": repo_name,
        "branch": branch, "target": str(target), "release_id": uuid.uuid4().hex, "config_digest": config_digest(config),
        "provenance": prov, "build_files": build, "protected_in_build": protected_in_build,
        "production": {k: v for k, v in production.items() if k != "previous_files"},
        "previous_files": production["previous_files"], "files": delta["files"], "deletions": delta["deletions"],
        "gone": delta["gone"], "acknowledge_orphans": bool(acknowledge_orphans), "retained": retained,
        "live_stats": _stats(delta["live"]), "critical": critical,
        "operational": {"protected_files": len(operational_before),
                        "changed_during_dry_run": metadata_diff(operational_before, operational_after)},
        "stop_reasons": stop_reasons, "summary": summary,
        "in_use_now": [rel for rel in config["in_use"] if in_use(safe_join(target, rel))],
        "timing_seconds": {k: round(v, 2) for k, v in dict(timing, total_s=time.monotonic() - started).items()},
        "estimated_execute_seconds": round(estimate, 1), "created_at": datetime.now(timezone.utc).isoformat(),
    }
    body["plan_id"] = plan_digest(body)
    out = out or plans_dir(repo) / f"plan-{now_stamp()}-{body['plan_id'][:12]}.json"
    write_json(Path(out), body)
    body["plan_path"] = str(out)
    if body["in_use_now"]:
        progress.detail(f"NOTE in use now (UPDATE would stop): {body['in_use_now']}")
    for reason in stop_reasons:
        progress.detail(f"STOP {reason}")
    progress.detail(f"plan {body['plan_id'][:12]} -> {out} (estimated execute {body['estimated_execute_seconds']} s)")
    return body


# ------------------------------------------------------------------ execute

def _load_plan(plan_path: Path, confirm: str) -> dict:
    body = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if body.get("kind") != "update_plan" or not body.get("plan_id"):
        raise _stop("not an UPDATE plan", "PLAN_TAMPERED")
    if not confirm or len(confirm) < 12 or not body["plan_id"].startswith(confirm):
        raise _stop("the plan id was not confirmed (first 12+ characters of plan_id)", "NOT_CONFIRMED")
    if plan_digest(body) != body["plan_id"]:
        raise _stop("the plan content does not match its plan id (edited); make a new dry-run", "PLAN_TAMPERED")
    if body["stop_reasons"]:
        raise _stop("the plan has stop reasons: " + "; ".join(body["stop_reasons"]), "PLAN_BLOCKED")
    return body


def _same(label: str, now, planned) -> None:
    if json.loads(json.dumps(now, sort_keys=True)) != json.loads(json.dumps(planned, sort_keys=True)):
        raise _stop(f"{label} changed since the dry-run; make a new plan", "PLAN_DRIFT")


def execute(plan_path: Path, confirm: str, *, config: dict | None = None, emit=print, before_each=None,
            record: bool = True) -> dict:
    body = _load_plan(plan_path, confirm)
    repo, target = Path(body["repo"]), Path(body["target"])
    config = config or release_config(body["repo_name"])
    if config_digest(config) != body["config_digest"]:
        raise _stop("[release] configuration changed since the dry-run; make a new plan", "PLAN_DRIFT")
    if inflight_path(repo).exists():
        raise _stop("a previous UPDATE did not finish (update-inflight.json); verify the target and clear it", "INTERRUPTED")
    progress = Progress(7, emit)
    protected = protected_of(config)
    started = time.monotonic()

    progress.stage(1, STAGES[0] + " (again, immediately before the update)")
    prov = verify_provenance(repo, body["branch"], config)
    _same("the BUILD / candidate / origin", prov, body["provenance"])
    build, _ = build_inventory(Path(prov["artifact"]), config, prov)
    _same("the artifact", build, body["build_files"])
    provenance.no_links(target)
    try:
        with LockSet(target, config):
            busy = [rel for rel in config["in_use"] if in_use(safe_join(target, rel))]
            if busy:
                raise _stop(f"still in use (close the app on every PC): {busy}", "IN_USE")
            return _execute_locked(body, repo, target, config, build, protected, progress, started, before_each, record)
    except Exception as exc:
        if record:  # the attempt is history; production.json is never touched by a failed UPDATE
            provenance.record_engine_attempt(repo, body, getattr(exc, "code", type(exc).__name__), str(exc))
        raise


def _execute_locked(body, repo, target, config, build, protected, progress, started, before_each, record) -> dict:
    progress.stage(2, STAGES[1] + " (production record, live BUILD_INFO, manifest, every planned file)")
    production = verify_production(repo, target, config, body["repo_name"])
    _same("the production state", {k: v for k, v in production.items() if k != "previous_files"}, body["production"])
    _same("the previous release manifest", production["previous_files"], body["previous_files"])
    considered = list(body["live_stats"])
    _same("the deployment", _stats(stat_files(target, considered)), body["live_stats"])

    progress.stage(3, STAGES[2] + " (re-verified from the reviewed plan)")
    artifact = Path(body["provenance"]["artifact"])
    changes = []
    for item in body["files"]:
        if item["category"] not in ("modified", "new"):
            continue
        protected.assert_writable(item["path"])
        changes.append(Change(item["path"], safe_join(artifact, item["path"]), safe_join(target, item["path"]),
                              item["build_sha256"], item["live_sha256"] if item["category"] == "modified" else None))
    modified = [c for c in changes if c.before_sha]
    listing = _scope(target, build, config)
    op_before = operational_snapshot(target, config, listing)
    critical_before = critical_hashes(target, op_before, config["critical"])
    progress.detail(f"modified {len(modified)} / new {len(changes) - len(modified)} / unchanged "
                    f"{body['summary']['unchanged']} of {body['summary']['managed']} managed files")

    save_root = backup_folder(target, config, body["release_id"]) if changes else None
    marker = {"release_id": body["release_id"], "plan_id": body["plan_id"], "target": str(target),
              "backup": str(save_root) if save_root else None, "started_at": datetime.now(timezone.utc).isoformat()}
    write_json(inflight_path(repo), marker)
    # saved copies under files/ so no managed path can collide with the backup manifest itself
    transaction = Transaction(target, (save_root / "files") if save_root else target, protected,
                              final=tuple(config["final_swap"]),
                              progress=progress)
    guard = InUseGuard([safe_join(target, rel) for rel in config["in_use"]])
    in_use_names = {rel.lower() for rel in config["in_use"]}
    try:
        progress.stage(4, f"{STAGES[3]}: {len(modified)} files -> {save_root or '(none)'}")
        if changes:
            backup = {"kind": BACKUP_KIND, "repo": body["repo_name"], "release_id": body["release_id"],
                      "plan_id": body["plan_id"], "engine_version": ENGINE_VERSION,
                      "source_commit": body["provenance"]["base_head"], "build_id": body["provenance"]["build_id"],
                      "target_production_commit": body["production"]["live_commit"],
                      "created_at": datetime.now(timezone.utc).isoformat(), "complete": False, "files_root": "files",
                      "modified": [{"path": c.rel, "old_sha256": c.before_sha, "expected_new_sha256": c.expected_sha,
                                    "backup_sha256": None} for c in modified],
                      "new": [{"path": c.rel, "expected_new_sha256": c.expected_sha} for c in changes if not c.before_sha]}
            save_root.mkdir(parents=True, exist_ok=False)
            transaction.save(changes)  # every saved copy verified against the live hash before anything live changes
            for entry, change in zip(backup["modified"], modified):
                entry["backup_sha256"] = sha256(change.saved)
                if entry["backup_sha256"] != change.before_sha:
                    raise _stop(f"backup hash mismatch: {change.rel}", "SAVE_HASH_MISMATCH")
            backup["complete"] = True
            write_json(save_root / BACKUP_MANIFEST, backup)
        progress.stage(5, f"{STAGES[4]}: {len(changes)} files")
        transaction.stage(changes)
        try:
            guard.acquire()  # from here until the final swap no PC can start the app
        except BaseException:
            transaction.cleanup(changes)
            transaction.remove_created_dirs()
            raise
        progress.stage(6, f"{STAGES[5]}: {len(changes)} files ({', '.join(config['final_swap'])} last)")
        transaction.apply(changes, before_each=before_each,
                          before_touch=lambda change: guard.release() if change.rel.lower() in in_use_names else None)
        guard.release()

        progress.stage(7, STAGES[6])
        try:
            checks, detail = _final_checks(body, target, config, changes, listing, op_before, critical_before)
        except Exception as exc:
            _undo_or_incomplete(transaction, save_root, f"final verification could not complete ({exc})")
            raise _stop(f"final verification could not complete ({exc}); the previous files were put back",
                        "VERIFY_FAILED") from exc
        for name, ok in checks.items():
            progress.detail(f"{'OK ' if ok else 'NG '} {name}")
        if not all(checks.values()):
            failed = [k for k, v in checks.items() if not v]
            _undo_or_incomplete(transaction, save_root, f"final verification failed ({failed})")
            if any("operational" in k or "critical" in k for k in failed) and all(
                    "operational" in k or "critical" in k for k in failed):
                raise _stop("operational data changed during the update (not written by the engine; kept as it is). "
                            f"The application files were put back; nothing recorded: {detail['operational_diff']}",
                            "OPERATIONAL_CHANGED")
            raise _stop(f"final verification failed ({failed}); the previous files were put back", "VERIFY_FAILED")

        manifest = _manifest_body(body, target, config, build)
        try:
            manifest_sha = write_manifest_atomic(target, config, manifest, body["repo_name"])
        except Exception as exc:
            _undo_or_incomplete(transaction, save_root, f"writing the release manifest failed ({exc})")
            raise _stop(f"writing the release manifest failed ({exc}); the previous files were put back",
                        "MANIFEST_WRITE") from exc
    except RollbackIncomplete:
        raise  # the inflight marker stays: the next plan stops until someone verified the target
    except BaseException:
        if not transaction.applied and save_root is not None and save_root.exists():
            try:  # nothing live was changed: the partial backup holds only this update's copies
                remove_tree(save_root)
            except (OSError, ReleaseError):
                pass
        inflight_path(repo).unlink(missing_ok=True)  # nothing applied, or everything applied was undone
        raise
    finally:
        guard.release()

    result = {"ok": True, "release_id": body["release_id"], "plan_id": body["plan_id"],
              "deployed_commit": body["provenance"]["base_head"], "manifest_sha256": manifest_sha,
              "backup": str(save_root) if save_root else None, "changed": len(changes), "modified": len(modified),
              "new": len(changes) - len(modified), "copied_bytes": body["summary"]["copied_bytes"],
              "backup_bytes": body["summary"]["backup_bytes"], "checks": checks,
              "operational_diff": detail["operational_diff"], "version": manifest["version"],
              "seconds": round(time.monotonic() - started, 1)}
    if record:
        provenance.record_engine_release(repo, body, result, manifest)
    inflight_path(repo).unlink(missing_ok=True)
    result["retention"] = prune_backups(target, config, body["repo_name"], keep_path=save_root)
    for error in result["retention"]["errors"]:
        progress.detail(f"NOTE backup retention: {error}")
    progress.detail(f"UPDATE complete: {len(changes)} files ({len(modified)} modified, "
                    f"{len(changes) - len(modified)} new) in {result['seconds']} s")
    return result


def _undo_or_incomplete(transaction: Transaction, save_root, what: str) -> None:
    errors = transaction.undo()
    if errors:
        raise RollbackIncomplete(f"{what}; ROLLBACK INCOMPLETE; recovery copies: {save_root}; " + "; ".join(errors))


def _final_checks(body, target, config, changes, listing_before, op_before, critical_before):
    """Every post-update check; an exception here counts as a failed verification (the caller undoes)."""
    keys = config["build_info_keys"]
    wrong = [c.rel for c in changes if not c.target.is_file() or sha256(c.target) != c.expected_sha]
    unchanged = [f["path"] for f in body["files"] if f["category"] == "unchanged"]
    moved = [rel for rel, value in stat_files(target, unchanged).items()
             if (list(value) if value else None) != body["live_stats"].get(rel)]
    final_ok = all(sha256(safe_join(target, rel)) == body["build_files"][_key(body["build_files"], rel)]["sha256"]
                   for rel in config["final_swap"])
    checks = {"changed files equal the build (SHA-256)": not wrong,
              "unchanged files untouched": not moved,
              "final-swap files equal the build": final_ok}
    if config.get("build_info"):
        info = read_key_values(safe_join(target, config["build_info"]))
        checks["live BUILD_INFO commit == new build"] = info.get(keys["commit"], "").lower() == body["provenance"]["base_head"]
        if keys.get("exe") and config["final_swap"]:
            checks["live EXE == BUILD_INFO EXE SHA-256"] = (
                sha256(safe_join(target, config["final_swap"][-1])) == info.get(keys["exe"], "").upper())
    listing = _scope(target, body["build_files"], config)
    after = operational_snapshot(target, config, listing)
    op_diff = metadata_diff(op_before, after)
    checks["critical files unchanged (SHA-256)"] = critical_hashes(target, after, config["critical"]) == critical_before
    checks["operational metadata unchanged"] = not any(op_diff.values())
    leftovers = [rel for rel in listing if rel.lower().endswith(LEFTOVER_SUFFIXES)]
    checks["no staging leftovers"] = not leftovers
    for name in config["hooks"]:
        problems = HOOKS[name](target, body)
        checks[f"hook {name}"] = not problems
    return checks, {"wrong": wrong, "moved": moved, "operational_diff": op_diff, "leftovers": leftovers}


def _key(mapping: dict, rel: str) -> str:
    return next(k for k in mapping if k.lower() == rel.lower())


def _manifest_body(body: dict, target: Path, config: dict, build: dict) -> dict:
    orphans = {d["path"].lower() for d in body["deletions"]} if body["acknowledge_orphans"] else set()
    now = stat_files(target, build)
    files = [{"path": rel, "size": build[rel]["size"], "sha256": build[rel]["sha256"], "mtime_ns": now[rel][1]}
             for rel in sorted(build) if rel.lower() not in orphans]
    info = body["provenance"]["build_info"]
    keys = config["build_info_keys"]
    previous = body["production"].get("previous") or {}
    return {
        "schema_version": MANIFEST_SCHEMA, "kind": MANIFEST_KIND, "engine_version": ENGINE_VERSION,
        "release_id": body["release_id"], "plan_id": body["plan_id"], "repo": body["repo_name"],
        "deployed_commit": body["provenance"]["base_head"], "version": info.get(keys.get("version", ""), ""),
        "build_id": body["provenance"]["build_id"],
        "artifact": {"tree_sha256": body["provenance"]["artifact_hash"],
                     "exe_sha256": build[_key(build, config["final_swap"][-1])]["sha256"] if config["final_swap"] else None,
                     "build_info": info},
        "provenance": {k: body["provenance"][k] for k in ("route", "branch", "head", "origin", "binding")},
        "build_timestamp": info.get("Build date/time") or body["provenance"].get("build_finished_at"),
        "released_at": datetime.now(timezone.utc).isoformat(),
        "previous_release_id": previous.get("release_id"), "previous_commit": previous.get("commit"),
        "files": files,
    }


def clear_interrupted(repo: Path, confirm: str) -> dict:
    """After someone verified the target by hand: forget the marker of an update that did not finish."""
    marker = _read_json(inflight_path(Path(repo).resolve())) or {}
    if not marker:
        raise _stop("no interrupted update is recorded", "NOTHING_TO_CLEAR")
    if not confirm or len(confirm) < 12 or not str(marker.get("release_id", "")).startswith(confirm):
        raise _stop("confirm with the first 12+ characters of the interrupted release id", "NOT_CONFIRMED")
    inflight_path(Path(repo).resolve()).unlink()
    return marker


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        getattr(stream, "reconfigure", lambda **_: None)(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="dry-run: nothing is written to the target; the plan goes to local DCC state")
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--branch", default="main")
    p.add_argument("--acknowledge-orphans", action="store_true",
                   help="leave files the new build no longer has in place, as unmanaged (never deleted)")
    p.add_argument("--out", type=Path)
    e = sub.add_parser("execute", help="apply a reviewed plan")
    e.add_argument("--plan", required=True, type=Path)
    e.add_argument("--confirm", required=True, help="first 12+ characters of the plan id")
    c = sub.add_parser("clear-interrupted", help="forget an interrupted update after verifying the target")
    c.add_argument("--repo", required=True, type=Path)
    c.add_argument("--confirm", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            body = plan(args.repo, args.target, branch=args.branch, acknowledge_orphans=args.acknowledge_orphans,
                        out=args.out)
            return 2 if body["stop_reasons"] else 0
        if args.action == "execute":
            execute(args.plan, args.confirm)
            return 0
        print(json.dumps(clear_interrupted(args.repo, args.confirm), ensure_ascii=False))
        return 0
    except RollbackIncomplete as exc:
        print(f"STOP ({exc.code}): {exc}", flush=True)
        return 3
    except (ReleaseError, OSError, ValueError, KeyError) as exc:
        print(f"STOP ({getattr(exc, 'code', type(exc).__name__)}): {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
