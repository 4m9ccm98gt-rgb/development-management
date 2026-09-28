"""Restore a deployment's application files from a verified full pre-update backup (DCC rollback).

    plan    : read-only. Proves the backup is exactly the expected build (BUILD_INFO / EXE / DEPLOY_MANIFEST,
              every manifest file hashed), hashes the updater-owned files on both sides, and writes a plan
              of exactly the files that differ. Operational data is only compared (metadata; SHA-256 for
              the critical files) and never planned.
    execute : applies a reviewed plan only (its id must be confirmed): lock, in-use check, re-verification
              against the plan (no drift), verified copies of the current files, staged + verified backup
              copies, in-place replacement with the EXE last, full final verification. The DCC release
              record is written only after everything verified.

Repo specifics (protected paths, critical files, commit file, lock, records) come from
`[release.<repo>]` in dev_control_center_repos.toml.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tomllib

from .release_engine import (
    Change, ExclusiveLock, Progress, Protected, ReleaseError, RollbackIncomplete, Transaction, in_use,
    metadata_diff, now_stamp, read_key_values, safe_join, scan_scope, sha256, stat_files, write_json,
)

REGISTRY = Path(__file__).resolve().parents[1] / "dev_control_center_repos.toml"


def release_config(repo_name: str, registry: Path = REGISTRY) -> dict:
    with registry.open("rb") as handle:
        config = tomllib.load(handle).get("release", {}).get(repo_name)
    if not config:
        raise ReleaseError(f"[release.{repo_name}] is not configured", "CONFIG_MISSING")
    return dict(config)


def protected_of(config: dict) -> Protected:
    return Protected(tuple(config.get("protected", [])), tuple(config.get("protected_names", [])))


def _hash_files(root: Path, rels, progress: Progress, label: str) -> dict[str, str | None]:
    result, rels = {}, sorted(rels)
    for number, rel in enumerate(rels, 1):
        path = safe_join(root, rel)
        result[rel] = sha256(path) if path.is_file() else None
        progress.count(number, len(rels), label)
    return result


def _critical(root: Path, listing: dict, names) -> dict[str, str]:
    wanted = {n.lower() for n in names}
    return {rel: sha256(safe_join(root, rel)) for rel in sorted(listing) if Path(rel).name.lower() in wanted}


def operational_snapshot(target: Path, config: dict) -> dict[str, tuple[int, int]]:
    """Protected operational data of the live deployment: top-level files plus the configured
    `operational_roots` only. The backup root (every generation) and unrelated folders are never entered."""
    protected = protected_of(config)
    listing = scan_scope(target, config.get("operational_roots", []))
    return {rel: value for rel, value in listing.items() if protected(rel) and not rel.lower().startswith("backup/")}


def _changed_protected_hashes(target: Path, before: dict, after: dict) -> dict[str, str | None]:
    """Only files whose metadata differs are hashed (to report what they are now)."""
    diff = metadata_diff(before, after)
    return {rel: (sha256(safe_join(target, rel)) if rel in after else None)
            for rel in diff["changed"] + diff["created"] + diff["missing"]}


def _identity(backup: Path, commit: str, version: str, config: dict) -> tuple[dict, dict]:
    info = read_key_values(backup / config.get("build_info", "BUILD_INFO.txt"))
    manifest_path = backup / config.get("deploy_manifest", "DEPLOY_MANIFEST.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"backup DEPLOY_MANIFEST unreadable: {exc}", "BACKUP_IDENTITY") from exc
    exe = config["commit_file"]
    problems = []
    if info.get("Git commit SHA", "").lower() != commit.lower():
        problems.append(f"BUILD_INFO commit {info.get('Git commit SHA')} != {commit}")
    if version and info.get("App version") != version:
        problems.append(f"BUILD_INFO version {info.get('App version')} != {version}")
    if str(manifest.get("build_commit", "")).lower() != commit.lower():
        problems.append(f"DEPLOY_MANIFEST build_commit {manifest.get('build_commit')} != {commit}")
    if sha256(safe_join(backup, exe)) != info.get("EXE SHA-256", "").upper():
        problems.append("backup EXE does not match BUILD_INFO EXE SHA-256")
    if problems:
        raise ReleaseError("backup is not the expected build: " + "; ".join(problems), "BACKUP_IDENTITY")
    return info, manifest


PLAN_FIELDS = ("repo", "target", "backup", "restore_commit", "restore_version", "files", "expected", "live_stats")


def plan_digest(body: dict) -> str:
    """Canonical digest of everything execution depends on; recomputed at execute time."""
    return hashlib.sha256(json.dumps({k: body.get(k) for k in PLAN_FIELDS}, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def plan(target: Path, backup: Path, repo_name: str, commit: str, version: str, out: Path,
         expect_count: int | None = None, emit=print) -> dict:
    """Read-only dry run over a bounded scope:
      live   : the release-managed files (manifest paths, BUILD_INFO / DEPLOY_MANIFEST, records) and the
               protected operational data under the configured operational roots;
      backup : only the files of this one backup that the restore needs.
    Its own guard proves nothing in that scope changed while it ran (stat before/after of every
    touched file, protected metadata before/after, SHA-256 of critical files before/after)."""
    config = release_config(repo_name)
    protected = protected_of(config)
    progress = Progress(6, emit)
    timing, started = {}, time.monotonic()
    exe = config["commit_file"]

    t = time.monotonic()
    progress.stage(1, "Rollback source identity (BUILD_INFO / EXE / DEPLOY_MANIFEST of this backup only)")
    info, manifest = _identity(backup, commit, version, config)
    manifest_sha = {e["path"]: str(e["sha256"]).upper() for e in manifest["files"]}
    records = set(config.get("records", []))
    candidates = set(manifest_sha) | records
    for rel in sorted(candidates):
        protected.assert_writable(rel)  # plan-time guard: operational data is never a candidate
    guard_before = {"backup": stat_files(backup, candidates), "live": stat_files(target, candidates),
                    "protected": operational_snapshot(target, config)}
    critical_before = _critical(target, guard_before["protected"], config.get("critical", []))
    backup_hashes = _hash_files(backup, candidates, progress, "backup files hashed")
    wrong = sorted(p for p, h in manifest_sha.items() if backup_hashes.get(p) != h)
    if wrong:
        raise ReleaseError(f"backup files differ from its DEPLOY_MANIFEST: {wrong[:10]}", "BACKUP_IDENTITY")
    progress.detail(f"backup = {commit} {info.get('App version')}: {len(manifest_sha)} / {len(manifest_sha)} "
                    "manifest files match")
    timing["backup_hash_s"] = time.monotonic() - t

    t = time.monotonic()
    progress.stage(2, "Hashing the release-managed files of the live deployment")
    current_hashes = _hash_files(target, candidates, progress, "live files hashed")
    timing["live_hash_s"] = time.monotonic() - t

    progress.stage(3, "Restore plan (only files that differ)")
    files = []
    for rel in sorted(candidates):
        if backup_hashes.get(rel) is None or current_hashes.get(rel) == backup_hashes[rel]:
            continue  # not in the backed-up deployment, or already equal: never touched
        files.append({"path": rel, "size": guard_before["backup"][rel][0], "backup_sha256": backup_hashes[rel],
                      "current_sha256": current_hashes.get(rel), "expected_sha256": backup_hashes[rel]})
    for item in files:
        protected.assert_writable(item["path"])
    progress.detail(f"restore: {len(files)} files / {sum(f['size'] for f in files):,} bytes; "
                    f"unchanged: {len(candidates) - len(files)}")
    if expect_count is not None and len(files) != expect_count:
        raise ReleaseError(f"plan has {len(files)} files, expected {expect_count}", "PLAN_COUNT")

    progress.stage(4, "Expected state after restore")
    expected = {
        "build_info": {k: info.get(k) for k in ("App version", "Git commit SHA", "Git branch", "Build date/time",
                                                 "EXE SHA-256")},
        "deploy_manifest_commit": manifest["build_commit"],
        "exe_sha256": backup_hashes[exe],
        "previous_sha256": backup_hashes.get(f"{exe}.previous"),
        "all_candidates": {rel: backup_hashes[rel] for rel in sorted(candidates) if backup_hashes.get(rel)},
    }
    progress.detail(f"{exe} {expected['exe_sha256']} / .previous {expected['previous_sha256']}")

    t = time.monotonic()
    progress.stage(5, "Dry-run guard (nothing in scope changed while planning)")
    guard_after = {"backup": stat_files(backup, candidates), "live": stat_files(target, candidates),
                   "protected": operational_snapshot(target, config)}
    critical_after = _critical(target, guard_after["protected"], config.get("critical", []))
    protected_diff = metadata_diff(guard_before["protected"], guard_after["protected"])
    guard = {
        "backup_files_unchanged": guard_before["backup"] == guard_after["backup"],
        "live_files_unchanged": guard_before["live"] == guard_after["live"],
        "protected_metadata_unchanged": not any(protected_diff.values()),
        "critical_sha256_unchanged": critical_before == critical_after,
        "protected_write_plans": 0,
    }
    guard["ok"] = all(v for k, v in guard.items() if k != "protected_write_plans")
    changed_hashes = _changed_protected_hashes(target, guard_before["protected"], guard_after["protected"])
    for name, ok in guard.items():
        if name not in ("ok", "protected_write_plans"):
            progress.detail(f"{'OK ' if ok else 'NG '} {name}")
    timing["guard_s"] = time.monotonic() - t
    if not (guard["backup_files_unchanged"] and guard["live_files_unchanged"]):
        raise ReleaseError("the deployment or the backup changed while planning; plan again", "PLAN_UNSTABLE")

    progress.stage(6, "Writing the plan (locally; nothing was written to the share)")
    timing["total_s"] = time.monotonic() - started
    restore_bytes = sum(f["size"] for f in files)
    read_rate = sum(v[0] for v in guard_before["backup"].values() if v) / max(timing["backup_hash_s"], 0.1)
    estimate = timing["live_hash_s"] * 2 + timing["guard_s"] * 2 + 6 * restore_bytes / max(read_rate, 1)
    body = {
        "schema": 2, "kind": "restore_plan", "repo": repo_name, "target": str(target), "backup": str(backup),
        "restore_commit": commit, "restore_version": version,
        "current_build_info": read_key_values(target / config.get("build_info", "BUILD_INFO.txt")),
        "files": files, "expected": expected,
        "live_stats": {rel: list(value) if value else None for rel, value in sorted(guard_after["live"].items())},
        "scope": {"live_release_files_stat_and_hashed": len(candidates),
                  "backup_files_stat_and_hashed": len(candidates),
                  "protected_files_stat": len(guard_before["protected"]),
                  "critical_files_hashed": len(critical_before),
                  "operational_roots": list(config.get("operational_roots", [])) + ["(top-level files)"]},
        "operational": {"protected_files": len(guard_before["protected"]), "critical": critical_before,
                        "dry_run_diff": protected_diff, "changed_file_hashes": changed_hashes},
        "guard": guard,
        "timing_seconds": {k: round(v, 1) for k, v in timing.items()},
        "estimated_execute_seconds": round(estimate), "created_at": now_stamp(),
    }
    body["plan_id"] = plan_digest(body)
    write_json(out, body)
    progress.detail(f"plan {body['plan_id'][:12]} -> {out}")
    return body


def execute(plan_path: Path, confirm: str, *, dcc_repo: Path | None = None, emit=print, before_each=None) -> dict:
    body = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not confirm or not body["plan_id"].startswith(confirm) or len(confirm) < 12:
        raise ReleaseError("the plan id was not confirmed (pass --confirm <first 12+ chars of plan_id>)", "NOT_CONFIRMED")
    if "live_stats" not in body or plan_digest(body) != body["plan_id"]:
        raise ReleaseError("the plan content does not match its plan id (edited or from an older format); "
                           "make a new dry-run plan", "PLAN_TAMPERED")
    config = release_config(body["repo"])
    protected = protected_of(config)
    target, backup = Path(body["target"]), Path(body["backup"])
    exe = config["commit_file"]
    progress = Progress(7, emit)

    progress.stage(1, "Lock and in-use check")
    with ExclusiveLock(safe_join(target, config.get("lock", ".dcc-release.lock"))):
        busy = [rel for rel in config.get("in_use", [exe]) if in_use(safe_join(target, rel))]
        if busy:
            raise ReleaseError(f"still in use (close the app on every PC): {busy}", "IN_USE")

        progress.stage(2, "Re-verifying the reviewed plan (backup, current files, operational data)")
        _identity(backup, body["restore_commit"], body["restore_version"], config)
        changes = []
        for number, item in enumerate(body["files"], 1):
            protected.assert_writable(item["path"])
            source = safe_join(backup, item["path"])
            live = safe_join(target, item["path"])
            if sha256(source) != item["backup_sha256"]:
                raise ReleaseError(f"backup changed since the plan: {item['path']}", "PLAN_DRIFT")
            now = sha256(live) if live.is_file() else None
            if now != item["current_sha256"]:
                raise ReleaseError(f"deployment changed since the plan: {item['path']}", "PLAN_DRIFT")
            changes.append(Change(item["path"], source, live, item["expected_sha256"], item["current_sha256"]))
            progress.count(number, len(body["files"]), "re-verified")
        candidates = set(body["expected"]["all_candidates"]) | {f["path"] for f in body["files"]}
        now_stats = stat_files(target, candidates)
        drifted = sorted(rel for rel in candidates
                         if (list(now_stats[rel]) if now_stats.get(rel) else None) != body["live_stats"].get(rel))
        if drifted:  # every managed file the plan relies on, including the unchanged ones
            raise ReleaseError(f"deployment changed since the plan: {drifted[:10]}", "PLAN_DRIFT")
        before = {r: v for r, v in operational_snapshot(target, config).items() if r not in candidates}
        critical_before = _critical(target, before, config.get("critical", []))

        from_commit = (body.get("current_build_info") or {}).get("Git commit SHA", "unknown")[:12]
        save_root = safe_join(target, f"backup/rollback_before_{now_stamp()}_{from_commit}")
        transaction = Transaction(target, save_root, protected, commit_file=exe, progress=progress)
        progress.stage(3, f"Saving the {sum(1 for c in changes if c.before_sha)} current files -> {save_root}")
        transaction.save(changes)
        write_json(save_root / "rollback_manifest.json", {
            "plan_id": body["plan_id"], "from_build_info": body.get("current_build_info"),
            "to_commit": body["restore_commit"], "to_version": body["restore_version"], "created_at": now_stamp(),
            "files": [{"path": c.rel, "saved_sha256": c.before_sha, "restored_sha256": c.expected_sha} for c in changes]})
        progress.stage(4, "Staging verified copies from the backup")
        transaction.stage(changes)
        progress.stage(5, f"Replacing {len(changes)} files ({exe} last)")
        transaction.apply(changes, before_each=before_each)

        progress.stage(6, "Final verification")
        try:
            checks, info, mismatched, exe_sha, op_diff = _final_checks(target, body, config, candidates, before,
                                                                       critical_before)
        except Exception as exc:  # a verification that can not complete counts as failed: undo our changes
            errors = transaction.undo()
            if errors:
                raise RollbackIncomplete(f"final verification could not complete ({exc}); ROLLBACK INCOMPLETE; "
                                         f"recovery copies: {save_root}; " + "; ".join(errors)) from exc
            raise ReleaseError(f"final verification could not complete ({exc}); the pre-restore files were put back",
                               "VERIFY_FAILED") from exc
        for name, ok in checks.items():
            progress.detail(f"{'OK ' if ok else 'NG '} {name}")
        result = {"ok": all(checks.values()), "checks": checks, "mismatched": mismatched, "operational_diff": op_diff,
                  "saved": str(save_root), "exe_sha256": exe_sha, "deployed_commit": info.get("Git commit SHA")}
        if not result["ok"]:
            failed = [k for k, v in checks.items() if not v]
            app_failed = [k for k in failed if "operational" not in k and "critical" not in k]
            if app_failed:  # our own result is wrong: put the pre-restore files back
                errors = transaction.undo()
                if errors:
                    raise RollbackIncomplete(f"final verification failed ({app_failed}); ROLLBACK INCOMPLETE; "
                                             f"recovery copies: {save_root}; " + "; ".join(errors))
                raise ReleaseError(f"final verification failed ({app_failed}); the pre-restore files were put back",
                                   "VERIFY_FAILED")
            raise ReleaseError("operational data changed during the restore (not written by this tool; nothing undone, "
                               f"restore NOT recorded as successful): {failed} {op_diff}", "OPERATIONAL_CHANGED")

    progress.stage(7, "Recording the deployed state in DCC")
    if dcc_repo is not None:
        record_rollback(dcc_repo, body, result)
    emit("RESTORE complete")
    return result


def _final_checks(target: Path, body: dict, config: dict, candidates: set, before: dict, critical_before: dict):
    """Every post-restore check; any exception here is treated by the caller as a failed verification."""
    exe = config["commit_file"]
    mismatched = sorted(rel for rel, h in body["expected"]["all_candidates"].items()
                        if not safe_join(target, rel).is_file() or sha256(safe_join(target, rel)) != h)
    info = read_key_values(target / config.get("build_info", "BUILD_INFO.txt"))
    manifest = json.loads((target / config.get("deploy_manifest", "DEPLOY_MANIFEST.json")).read_text(encoding="utf-8-sig"))
    manifest_exe = next((e["sha256"].upper() for e in manifest["files"] if e["path"] == exe), None)
    exe_sha = sha256(safe_join(target, exe))
    after = {r: v for r, v in operational_snapshot(target, config).items() if r not in candidates}
    op_diff = metadata_diff(before, after)
    critical_after = _critical(target, after, config.get("critical", []))
    checks = {
        "all updater-owned files equal the backup": not mismatched,
        "BUILD_INFO commit": info.get("Git commit SHA", "").lower() == body["restore_commit"].lower(),
        "BUILD_INFO version": info.get("App version") == body["restore_version"],
        "DEPLOY_MANIFEST commit": str(manifest.get("build_commit", "")).lower() == body["restore_commit"].lower(),
        "EXE == BUILD_INFO == DEPLOY_MANIFEST": exe_sha == info.get("EXE SHA-256", "").upper() == manifest_exe,
        "EXE.previous restored": sha256(safe_join(target, f"{exe}.previous")) == body["expected"]["previous_sha256"]
        if body["expected"]["previous_sha256"] else True,
        "critical files unchanged (SHA-256)": critical_after == critical_before,
        "operational metadata unchanged": not any(op_diff.values()),
    }
    return checks, info, mismatched, exe_sha, op_diff


def record_rollback(repo: Path, body: dict, result: dict) -> None:
    """Only after a verified restore. Three durable facts, each independent of later UPDATE attempts:
    the attempt history (last_release + superseded copy), the confirmed production state, and the
    revoked SHA that must never be released again. The rolled-back candidate is ended."""
    from . import candidate as candidate_flow
    from .provenance import release_record_path

    path = release_record_path(repo)
    if path.exists():
        path.replace(path.with_name(f"release-superseded-{now_stamp()}.json"))
    from_commit = (body.get("current_build_info") or {}).get("Git commit SHA", "")
    record = {
        "schema": 1, "kind": "rollback", "repo": str(repo), "target": body["target"], "returncode": 0,
        "deployed_commit": body["restore_commit"], "app_version": body["restore_version"],
        "exe_sha256": result["exe_sha256"], "rolled_back_from": from_commit, "restored_from": body["backup"],
        "saved_before_restore": result["saved"], "plan_id": body["plan_id"], "finished_at": now_stamp(),
        "build_id": None, "candidate_sha": None}
    write_json(path, record)
    record_confirmed_rollback(repo, record)
    candidate_flow.mark_rolled_back(repo, from_commit, body["restore_commit"])


def record_confirmed_rollback(repo: Path, record: dict) -> None:
    """production.json + revoked.json from a verified rollback record (also used to backfill older states)."""
    from .provenance import production_record_path, revoked_path

    write_json(production_record_path(repo), {
        "schema": 1, "commit": record["deployed_commit"], "version": record.get("app_version") or "",
        "how": f"rollback（{str(record.get('rolled_back_from') or '')[:12]} から復旧）", "target": record["target"],
        "exe_sha256": record.get("exe_sha256"), "at": record.get("finished_at")})
    revoked = json.loads(revoked_path(repo).read_text(encoding="utf-8")) if revoked_path(repo).exists() else {"revoked": []}
    if record.get("rolled_back_from") and all(r.get("sha") != record["rolled_back_from"] for r in revoked["revoked"]):
        revoked["revoked"].append({"sha": record["rolled_back_from"], "replaced_by": record["deployed_commit"],
                                   "plan_id": record.get("plan_id"), "at": record.get("finished_at")})
    write_json(revoked_path(repo), revoked)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        getattr(stream, "reconfigure", lambda **_: None)(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("plan", help="read-only dry run: write the restore plan")
    p.add_argument("--repo-name", required=True)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--backup", required=True, type=Path)
    p.add_argument("--commit", required=True)
    p.add_argument("--version", default="")
    p.add_argument("--expect-count", type=int)
    p.add_argument("--out", required=True, type=Path)
    e = sub.add_parser("execute", help="apply a reviewed plan")
    e.add_argument("--plan", required=True, type=Path)
    e.add_argument("--confirm", required=True, help="first 12+ characters of the plan id")
    e.add_argument("--dcc-repo", type=Path, help="source repo whose DCC release record is updated on success")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            plan(args.target, args.backup, args.repo_name, args.commit, args.version, args.out, args.expect_count)
        else:
            execute(args.plan, args.confirm, dcc_repo=args.dcc_repo)
        return 0
    except RollbackIncomplete as exc:
        print(f"STOP ({exc.code}): {exc}", flush=True)
        return 3
    except (ReleaseError, OSError, ValueError, KeyError) as exc:
        print(f"STOP ({getattr(exc, 'code', type(exc).__name__)}): {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
