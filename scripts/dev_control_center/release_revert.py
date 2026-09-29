"""Revert the latest common-engine release from its changed-only backup (DCC rollback of an engine UPDATE).

The common engine keeps no full backups: its release backup holds the replaced files (verified) and a manifest
naming the files the release added. A revert therefore puts the replaced files back and removes the added ones,
with the same safety as an UPDATE:

    plan    : read-only. The live deployment must be exactly the recorded release (trusted release manifest,
              DCC production record, and every file of the release verified by SHA-256); the backup must be
              complete and its copies must match their recorded hashes. The plan is stored locally, digest-bound.
    execute : a reviewed plan whose id was confirmed. Locks, in-use check, everything re-proved, a restore intent
              written before the first write (clear-interrupted resolves it from the live state), the current
              files saved, the previous ones staged, launch barrier, replace / remove (EXE last), final
              verification, then the DCC records of a rollback: the reverted SHA is revoked, production is the
              previous commit. Any failure undoes exactly what was applied; else ROLLBACK_INCOMPLETE.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from . import provenance
from .release_engine import (
    BACKUP_KIND, BACKUP_MANIFEST, ENGINE_VERSION, Change, InUseGuard, LockSet, Progress, ReleaseError,
    RollbackIncomplete, Transaction, backup_folder, config_digest, critical_hashes, engine_backups, in_use,
    metadata_diff, now_stamp, operational_snapshot, protected_of, read_key_values, release_config, remove_backup,
    safe_join, sha256, stat_files, write_json,
)
from . import release_update as ru

STAGES = ("Release and backup verification", "Production verification", "Revert plan", "Saving current files",
          "Staging previous files", "Reverting", "Final verification")
SHA40 = __import__("re").compile(r"[0-9a-f]{40}")


def _stop(message: str, code: str) -> ReleaseError:
    return ReleaseError(message, code)


def _release_backup(target: Path, config: dict, repo_name: str, release_id: str) -> tuple[Path, dict]:
    for folder in engine_backups(target, config, repo_name):
        data = json.loads((folder / BACKUP_MANIFEST).read_text(encoding="utf-8"))
        if data.get("release_id") == release_id and data.get("operation", "update") == "update":
            return folder, data
    raise _stop(f"no complete backup of release {release_id[:12]} in {config['backup_dir']}/ (a release that changed "
                "nothing has none; an older one may have been removed by retention)", "NO_BACKUP")


def plan_revert(repo: Path, target: Path, *, repo_name: str | None = None, config: dict | None = None,
                out: Path | None = None, emit=print) -> dict:
    repo = Path(repo).resolve()
    repo_name = repo_name or repo.name
    config = config or release_config(repo_name)
    progress = Progress(7, emit)
    if ru.inflight_path(repo).exists() or provenance.restore_intent_path(repo).exists():
        raise _stop("an UPDATE or restore of this repo did not finish; resolve it first", "INTERRUPTED")

    progress.stage(1, STAGES[0])
    target = ru.resolve_target(repo, repo / config["artifact"], Path(target), config)
    production = ru.verify_production(repo, target, config, repo_name)
    if not production["manifest_trusted"]:
        raise _stop("the live deployment is not verifiably the recorded release (" +
                    "; ".join(production["trust_reasons"]) + "); a revert needs exactly that state — use "
                    "restore_release or repair first", "REVERT_UNSAFE")
    record = production["record"]
    release_commit = str(record["commit"]).lower()
    folder, backup = _release_backup(target, config, repo_name, record["release_id"])
    previous_commit = str(backup.get("target_production_commit") or "").lower()
    if not SHA40.fullmatch(previous_commit) or previous_commit == release_commit:
        raise _stop(f"the release backup does not name a different previous commit ({previous_commit[:12] or '?'})",
                    "REVERT_UNSAFE")
    if str(backup.get("source_commit", "")).lower() != release_commit:
        raise _stop("the release backup belongs to another commit than the production record", "REVERT_UNSAFE")
    files_root = folder / backup.get("files_root", "files")
    protected = protected_of(config)
    items = []
    for entry in backup["modified"]:
        protected.assert_writable(entry["path"])
        copy = safe_join(files_root, entry["path"])
        if not copy.is_file() or sha256(copy) != entry["old_sha256"] or entry["backup_sha256"] != entry["old_sha256"]:
            raise _stop(f"backup copy missing or changed: {entry['path']}", "BACKUP_IDENTITY")
        items.append({"path": entry["path"], "action": "restore", "restore_sha256": entry["old_sha256"],
                      "current_sha256": entry["expected_new_sha256"]})
    for entry in backup["new"]:
        protected.assert_writable(entry["path"])
        items.append({"path": entry["path"], "action": "remove", "restore_sha256": None,
                      "current_sha256": entry["expected_new_sha256"]})
    if not items:
        raise _stop("the release changed nothing; there is nothing to revert", "NOTHING_TO_REVERT")

    progress.stage(2, STAGES[1])
    info_rel, exe_rel = config.get("build_info"), (config["final_swap"] or [None])[-1]
    keys = config["build_info_keys"]
    previous_info = {}
    if info_rel:
        saved_info = next((i for i in items if i["path"].lower() == info_rel.lower() and i["action"] == "restore"), None)
        if saved_info is None:
            raise _stop(f"the release backup has no previous {info_rel}", "REVERT_UNSAFE")
        previous_info = read_key_values(safe_join(files_root, saved_info["path"]))
        if previous_info.get(keys["commit"], "").lower() != previous_commit:
            raise _stop(f"the saved {info_rel} names {previous_info.get(keys['commit'])}, not {previous_commit[:12]}",
                        "BACKUP_IDENTITY")
        if exe_rel and keys.get("exe"):
            saved_exe = next((i for i in items if i["path"].lower() == exe_rel.lower()), None)
            exe_sha = saved_exe["restore_sha256"] if saved_exe else None
            if exe_sha is None:  # the EXE did not change in that release: it stays as it is
                exe_sha = sha256(safe_join(target, exe_rel))
            if exe_sha != previous_info.get(keys["exe"], "").upper():
                raise _stop(f"the previous {exe_rel} would not match the previous {info_rel}", "BACKUP_IDENTITY")

    progress.stage(3, STAGES[2])
    for number, item in enumerate(items, 1):  # the live files are exactly what the release wrote
        live = safe_join(target, item["path"])
        if not live.is_file() or sha256(live) != item["current_sha256"]:
            raise _stop(f"{item['path']} is no longer what the release wrote; not reverting over it", "REVERT_UNSAFE")
        progress.count(number, len(items), "release files verified")
    live_stats = stat_files(target, [i["path"] for i in items])
    operational = operational_snapshot(target, config, _scope(target, {"items": items}, config))
    for number, title in enumerate(STAGES[3:], 4):
        progress.stage(number, f"{title} (dry-run: nothing written to the target)")
    body = {
        "schema": 1, "kind": "revert_plan", "engine_version": ENGINE_VERSION, "repo": str(repo), "repo_name": repo_name,
        "target": str(target), "revert_id": uuid.uuid4().hex, "config_digest": config_digest(config),
        "release_id": record["release_id"], "release_commit": release_commit, "previous_commit": previous_commit,
        "previous_version": previous_info.get(keys.get("version", ""), ""), "backup": str(folder),
        "production": {k: v for k, v in production.items() if k != "previous_files"}, "items": items,
        "live_stats": ru._stats(live_stats),
        "summary": {"restore": sum(1 for i in items if i["action"] == "restore"),
                    "remove": sum(1 for i in items if i["action"] == "remove"),
                    "protected_live": len(operational)},
        "in_use_now": [rel for rel in config["in_use"] if in_use(safe_join(target, rel))],
        "stop_reasons": [], "created_at": datetime.now(timezone.utc).isoformat(),
    }
    body["plan_id"] = ru.plan_digest(body)
    out = out or ru.plans_dir(repo) / f"revert-plan-{now_stamp()}-{body['plan_id'][:12]}.json"
    write_json(Path(out), body)
    body["plan_path"] = str(out)
    progress.detail(f"revert {release_commit[:12]} -> {previous_commit[:12]} {body['previous_version']}: restore "
                    f"{body['summary']['restore']} / remove {body['summary']['remove']}; plan {body['plan_id'][:12]}")
    return body


def execute_revert(plan_path: Path, confirm: str, *, config: dict | None = None, emit=print, before_each=None) -> dict:
    body = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if body.get("kind") != "revert_plan" or not body.get("plan_id"):
        raise _stop("not a revert plan", "PLAN_TAMPERED")
    if not confirm or len(confirm) < 12 or not body["plan_id"].startswith(confirm):
        raise _stop("the plan id was not confirmed (first 12+ characters of plan_id)", "NOT_CONFIRMED")
    if ru.plan_digest(body) != body["plan_id"]:
        raise _stop("the plan content does not match its plan id (edited); make a new dry-run", "PLAN_TAMPERED")
    repo, target = Path(body["repo"]), Path(body["target"])
    config = config or release_config(body["repo_name"])
    if config_digest(config) != body["config_digest"]:
        raise _stop("[release] configuration changed since the dry-run; make a new plan", "PLAN_DRIFT")
    intent = provenance.restore_intent_path(repo)
    if ru.inflight_path(repo).exists() or intent.exists():
        raise _stop("an UPDATE or restore of this repo did not finish; resolve it first", "INTERRUPTED")
    progress = Progress(7, emit)
    protected = protected_of(config)
    started = time.monotonic()
    provenance.no_links(target)

    with LockSet(target, config):
        busy = [rel for rel in config["in_use"] if in_use(safe_join(target, rel))]
        if busy:
            raise _stop(f"still in use (close the app on every PC): {busy}", "IN_USE")
        progress.stage(1, STAGES[0] + " (again)")
        folder = Path(body["backup"])
        data = json.loads(safe_join(folder, BACKUP_MANIFEST).read_text(encoding="utf-8"))
        files_root = folder / data.get("files_root", "files")
        progress.stage(2, STAGES[1] + " (again)")
        production = ru.verify_production(repo, target, config, body["repo_name"])
        ru._same("the production state", {k: v for k, v in production.items() if k != "previous_files"},
                 body["production"])
        ru._same("the deployment", ru._stats(stat_files(target, [i["path"] for i in body["items"]])), body["live_stats"])
        progress.stage(3, STAGES[2] + " (re-verified)")
        changes = []
        for item in body["items"]:
            protected.assert_writable(item["path"])
            live = safe_join(target, item["path"])
            if item["action"] == "restore":
                source = safe_join(files_root, item["path"])
                if sha256(source) != item["restore_sha256"]:
                    raise _stop(f"backup copy changed since the plan: {item['path']}", "PLAN_DRIFT")
                changes.append(Change(item["path"], source, live, item["restore_sha256"], item["current_sha256"]))
            else:
                changes.append(Change(item["path"], None, live, None, item["current_sha256"]))
        listing = _scope(target, body, config)
        op_before = operational_snapshot(target, config, listing)
        critical_before = critical_hashes(target, op_before, config["critical"])

        save_root = backup_folder(target, config, body["revert_id"])
        guard = InUseGuard([safe_join(target, rel) for rel in config["in_use"]])
        transaction = Transaction(target, save_root / "files", protected, final=tuple(config["final_swap"]),
                                  progress=progress, guard=guard)
        write_json(intent, {  # before the first write to the deployment: resolvable by clear-interrupted
            "plan_id": body["plan_id"], "target": body["target"], "repo_name": body["repo_name"], "operation": "revert",
            "rolled_back_from": body["release_commit"], "deployed_commit": body["previous_commit"],
            "restore_version": body["previous_version"], "backup": body["backup"], "saved_before_restore": str(save_root),
            "destination": {i["path"]: i["restore_sha256"] for i in body["items"]},
            "source": {i["path"]: i["current_sha256"] for i in body["items"]}, "at": now_stamp()})
        try:
            progress.stage(4, f"{STAGES[3]}: {len(changes)} files -> {save_root}")
            save_root.mkdir(parents=True, exist_ok=False)
            transaction.save(changes)
            write_json(safe_join(target, f"{config['backup_dir']}/{save_root.name}/{BACKUP_MANIFEST}", ancestors=True), {
                "kind": BACKUP_KIND, "operation": "revert", "repo": body["repo_name"], "release_id": body["revert_id"],
                "reverted_release_id": body["release_id"], "plan_id": body["plan_id"], "engine_version": ENGINE_VERSION,
                "source_commit": body["previous_commit"], "target_production_commit": body["release_commit"],
                "created_at": datetime.now(timezone.utc).isoformat(), "complete": True, "files_root": "files",
                "modified": [{"path": c.rel, "old_sha256": c.before_sha, "expected_new_sha256": c.expected_sha,
                              "backup_sha256": c.before_sha} for c in changes], "new": []})
            progress.stage(5, f"{STAGES[4]}: {sum(1 for c in changes if c.expected_sha)} files")
            transaction.stage(changes)
            guard.acquire()
            progress.stage(6, f"{STAGES[5]}: restore {body['summary']['restore']} / remove {body['summary']['remove']}")
            transaction.apply(changes, before_each=before_each)
            progress.stage(7, STAGES[6])
            try:
                checks, op_diff = _final_checks(body, target, config, changes, listing, op_before, critical_before,
                                                transaction._current)
            except Exception as exc:
                errors = transaction.undo()
                if errors:
                    raise RollbackIncomplete(f"final verification could not complete ({exc}); ROLLBACK INCOMPLETE; "
                                             f"recovery copies: {save_root}; " + "; ".join(errors)) from exc
                raise _stop(f"final verification could not complete ({exc}); the release files were put back",
                            "VERIFY_FAILED") from exc
            for name, ok in checks.items():
                progress.detail(f"{'OK ' if ok else 'NG '} {name}")
            if not all(checks.values()):
                failed = [k for k, v in checks.items() if not v]
                errors = transaction.undo()
                if errors:
                    raise RollbackIncomplete(f"final verification failed ({failed}); ROLLBACK INCOMPLETE; "
                                             f"recovery copies: {save_root}; " + "; ".join(errors))
                raise _stop(f"final verification failed ({failed}; {op_diff}); the release files were put back",
                            "VERIFY_FAILED")
            exe_sha = transaction._current(safe_join(target, config["final_swap"][-1])) if config["final_swap"] else None
        except RollbackIncomplete:
            raise  # the intent stays: UPDATE stays blocked, the reverted SHA counts as revoked
        except BaseException as failure:
            if transaction.applied:
                errors = transaction.undo()
                if errors:
                    raise RollbackIncomplete(f"{failure}; ROLLBACK INCOMPLETE; recovery copies: {save_root}; "
                                             + "; ".join(errors)) from failure
            else:
                transaction.cleanup(changes)
                transaction.remove_created_dirs()
                if save_root.exists():
                    try:
                        remove_backup(target, config, save_root.name)
                    except (OSError, ReleaseError):
                        pass
            intent.unlink(missing_ok=True)
            raise
        finally:
            guard.release()

    from .restore_release import record_rollback

    record_rollback(repo, {"target": body["target"], "restore_commit": body["previous_commit"],
                           "restore_version": body["previous_version"], "backup": body["backup"],
                           "plan_id": body["plan_id"], "current_build_info": {"Git commit SHA": body["release_commit"]}},
                    {"exe_sha256": exe_sha, "saved": str(save_root)})
    intent.unlink(missing_ok=True)  # only once the revocation and production are durably recorded
    result = {"ok": True, "reverted_release_id": body["release_id"], "production_commit": body["previous_commit"],
              "revoked": body["release_commit"], "saved": str(save_root), "checks": checks,
              "seconds": round(time.monotonic() - started, 1)}
    progress.detail(f"REVERT complete: production {body['previous_commit'][:12]}; {body['release_commit'][:12]} revoked")
    return result


def _scope(target: Path, body: dict, config: dict) -> dict:
    """Top-level files, the folders the reverted files live in and the operational roots (metadata only)."""
    return ru._scope(target, {item["path"]: None for item in body["items"]}, config)


def _final_checks(body, target, config, changes, listing, op_before, critical_before, current):
    keys = config["build_info_keys"]
    wrong = [c.rel for c in changes if (c.target.exists() if c.expected_sha is None
                                         else (not c.target.is_file() or current(c.target) != c.expected_sha))]
    checks = {"every release file restored or removed": not wrong}
    if config.get("build_info"):
        info = read_key_values(safe_join(target, config["build_info"]))
        checks["live BUILD_INFO commit == previous release"] = info.get(keys["commit"], "").lower() == body["previous_commit"]
        if keys.get("exe") and config["final_swap"]:
            checks["live EXE == BUILD_INFO EXE SHA-256"] = (
                current(safe_join(target, config["final_swap"][-1])) == info.get(keys["exe"], "").upper())
    after = operational_snapshot(target, config, _scope(target, body, config))
    op_diff = metadata_diff(op_before, after)
    checks["critical files unchanged (SHA-256)"] = critical_hashes(target, after, config["critical"]) == critical_before
    checks["operational metadata unchanged"] = not any(op_diff.values())
    return checks, op_diff
