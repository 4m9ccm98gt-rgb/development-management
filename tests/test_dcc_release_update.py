"""release_update: the DCC common UPDATE engine (dry-run plan -> reviewed execute) on temporary fixtures.

A git repo with a bare origin produces BUILD receipts exactly as DCC records them. `share` is the live
deployment: production v1 deployed by the legacy updater (no DCC manifest yet), with operational data, a
legacy full backup and target-only files that the engine must never touch.

Ports of next-day-setup `tests/test_update_delta.py` (update_delta.ps1 @ 1a03178) are marked [port]."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import uuid

from scripts.dev_control_center import provenance
from scripts.dev_control_center import release_engine as re_
from scripts.dev_control_center import release_update as ru

SAVE = "保存データ"
LOCKS = (".nds-update.lock", ".dcc-release.lock")
PROTECTED = ["保存データ/*", "*/保存データ/*", "print_work/*", "*/print_work/*", "logs/*", "*/logs/*", "log/*",
             "*/log/*", "*.log", "backup/*", "*/backup/*", "_internal/outputs/*",
             "_internal/tools/SumatraPDF-settings.txt", "config/*", "outputs/*"]
NAMES = ["closing_tasks.json", "master_settings.json", "ui_prefs.json"]
CONFIG = re_.normalize_config({
    "engine": "dcc", "artifact": "dist/App", "child_target": "App",
    "managed": ["App.exe", "_internal/**", "*.txt", "*.bat"], "final_swap": ["BUILD_INFO.txt", "App.exe"],
    "commit_file": "App.exe", "in_use": ["App.exe"], "legacy_locks": [".nds-update.lock"], "backup_retention": 3,
    "protected": PROTECTED, "protected_names": NAMES, "critical": NAMES,
    "operational_roots": ["_internal", SAVE, "print_work", "logs", "log"]})
# an app without BUILD_INFO: the engine is common, nothing in it is next-day-setup specific
PLAIN = re_.normalize_config({"artifact": "dist/App", "managed": ["App.exe", "lib/**"], "final_swap": ["App.exe"],
                              "in_use": ["App.exe"], "build_info": "", "protected": ["data/*"], "protected_names": [],
                              "critical": [], "operational_roots": ["data"]})


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def tree(root: Path, *, backups: bool = False) -> dict:
    """Every file with bytes and mtime (lock files ignored; backup/ only when asked)."""
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file() and p.name not in LOCKS
            and (backups or not p.relative_to(root).as_posix().startswith("backup/"))}


def rel_of(key: str) -> str:
    """`_internal__sub__c_dat` -> `_internal/sub/c.dat` (keyword-friendly fixture paths)."""
    folder, _, name = key.replace("__", "/").rpartition("/")
    stem, _, ext = name.rpartition("_")
    return (folder + "/" if folder else "") + stem + "." + ext


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class ReleaseCase(unittest.TestCase):
    config = CONFIG
    V1 = {"App.exe": b"exe-v1", "_internal/a.dat": b"original", "_internal/b.dat": b"same",
          "_internal/sub/c.dat": b"c-v1", "launch.bat": b"@start App.exe", "manual.txt": b"manual v1"}
    OPERATIONAL = {"closing_tasks.json": b"{tasks}", "master_settings.json": b"{settings}", "ui_prefs.json": b"{ui}",
                   f"{SAVE}/20260927.json": b"{day}", "print_work/p.png": b"png", "app.log": b"log",
                   "_internal/outputs/r.pdf": b"pdf", "_internal/closing_tasks.json": b"{legacy}",
                   "_internal/tools/SumatraPDF-settings.txt": b"sumatra", "config/print.json": b"{print}"}
    TARGET_ONLY = {"README.txt": b"legacy readme", "_internal/target-only.dat": b"keep",
                   "DEPLOY_MANIFEST.json": b"{legacy v1 manifest}", "App.exe.previous": b"exe-v0",
                   "backup/update_before_20260801_000000/_internal/huge.bin": b"legacy full backup"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dcc update ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local"),
                                           "AI_ORCHESTRATOR_STATE_ROOT": str(self.root / "orch")})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.root / "src" / "app"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.invalid")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "core.autocrlf", "false")
        (self.repo / ".gitignore").write_text("dist/\n", encoding="utf-8")
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        git(self.repo, "remote", "add", "origin", str(self.origin))
        self.c1 = self.commit("v1")
        self.artifact = self.repo / "dist" / "App"
        self.target = self.root / "share"
        self.emitted: list[str] = []
        self.deploy_legacy(self.V1, self.c1, "v1")

    # ------------------------------------------------------------------ fixture helpers

    def commit(self, text: str) -> str:
        (self.repo / "app.py").write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", text)
        git(self.repo, "push", "-q", "origin", "main")
        return git(self.repo, "rev-parse", "HEAD")

    @staticmethod
    def build_info(commit: str, version: str, exe: bytes) -> bytes:
        return (f"App version: {version}\nGit commit SHA: {commit}\nBuild date/time: 2026-09-28 10:00:00\n"
                f"Git working tree: clean\nEXE SHA-256: {sha(exe)}\n").encode()

    def files_with_info(self, files: dict, commit: str, version: str) -> dict:
        result = dict(files)
        if self.config.get("build_info"):
            result["BUILD_INFO.txt"] = self.build_info(commit, version, files["App.exe"])
        return result

    def deploy_legacy(self, files: dict, commit: str, version: str) -> None:
        """Production as the legacy updater left it: app files, no DCC manifest; DCC knows the commit."""
        for rel, data in {**self.files_with_info(files, commit, version), **self.OPERATIONAL,
                          **self.TARGET_ONLY}.items():
            write(self.target / rel, data)
        provenance.write_json(provenance.production_record_path(self.repo), {
            "schema": 1, "commit": commit, "version": version, "how": "rollback", "target": str(self.target)})

    def build(self, files: dict, version: str = "v2", *, extra: dict | None = None) -> dict:
        """The artifact of HEAD plus DCC's receipt for it (as provenance.build records a ready BUILD)."""
        head = git(self.repo, "rev-parse", "HEAD")
        if self.artifact.exists():
            shutil.rmtree(self.artifact)
        content = {**self.files_with_info(files, head, version), "_internal/master_settings.json": b"{bundled}",
                   "config/print.json": b"{bundled print}", **(extra or {})}
        for rel, data in content.items():
            write(self.artifact / rel, data)
        (self.artifact / SAVE).mkdir(exist_ok=True)
        receipt = {"schema": 1, "repo": str(self.repo.resolve()), "base_head": head, "dirty": False,
                   "build_id": uuid.uuid4().hex, "artifact": str(self.artifact.resolve()), "status": "ready",
                   "artifact_hash": provenance.tree_hash(self.artifact),
                   "inputs_hash": provenance.inputs_hash(self.repo, self.artifact), "candidate_sha": None,
                   "candidate_run_id": None, "build_info_file": "BUILD_INFO.txt", "build_info_sha": head,
                   "finished_at": "2026-09-28T01:00:00+00:00"}
        provenance.write_json(provenance.receipt_path(self.repo), receipt)
        return receipt

    def plan(self, **extra) -> dict:
        values = dict(branch="main", repo_name="app", config=self.config, emit=self.emitted.append)
        values.update(extra)
        return ru.plan(self.repo, self.target, **values)

    def execute(self, body: dict, **extra) -> dict:
        values = dict(config=self.config, emit=self.emitted.append)
        values.update(extra)
        return ru.execute(Path(body["plan_path"]), body["plan_id"][:12], **values)

    def release(self, files: dict, version: str = "v2", text: str | None = None, **plan_extra) -> tuple[dict, dict]:
        self.commit(text or f"{version} {uuid.uuid4().hex[:6]}")
        self.build(files, version)
        body = self.plan(**plan_extra)
        return body, self.execute(body)

    def v2(self, **changes) -> dict:
        files = dict(self.V1)
        files.update({rel_of(k): v for k, v in changes.items()})
        return files

    def production(self) -> dict | None:
        path = provenance.production_record_path(self.repo)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def last_release(self) -> dict:
        return json.loads(provenance.release_record_path(self.repo).read_text(encoding="utf-8"))

    def app_state(self) -> dict:
        return {rel: data for rel, (data, _) in tree(self.target).items()}

    def operational(self) -> dict:
        return {rel: value for rel, value in tree(self.target).items() if rel in self.OPERATIONAL}

    def category(self, body: dict, name: str) -> set[str]:
        return {f["path"] for f in body["files"] if f["category"] == name}

    def assert_untouched_after_failure(self, before: dict, production_before: dict) -> None:
        self.assertEqual(self.app_state(), {rel: data for rel, (data, _) in before.items()})
        self.assertEqual(self.production(), production_before)
        self.assertFalse(ru.inflight_path(self.repo).exists())
        self.assertFalse([p for p in self.target.rglob("*") if p.name.endswith((".dcc-stage", ".dcc-undo"))])
        self.assertFalse((self.target / "DCC_RELEASE_MANIFEST.json").exists()
                         and json.loads((self.target / "DCC_RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
                         ["deployed_commit"] == git(self.repo, "rev-parse", "HEAD"))


# ====================================================================== delta behaviour

class DeltaTests(ReleaseCase):
    def test_port_build_inventory_excludes_operational_data(self):  # [port] build manifest excludes operational data
        self.commit("v2")
        self.build(self.V1, extra={"_internal/logs/a.txt": b"private", "_internal/nested/master_settings.json": b"p",
                                   "print_work/a.txt": b"private", "ui_prefs.json": b"private"})
        prov = ru.verify_provenance(self.repo, "main", self.config)
        files, excluded = ru.build_inventory(self.artifact, self.config, prov)
        self.assertEqual(set(files), set(self.files_with_info(self.V1, prov["base_head"], "v2")))
        self.assertIn("_internal/logs/a.txt", excluded)
        self.assertIn("_internal/nested/master_settings.json", excluded)
        self.assertNotIn("print_work/a.txt", files)       # not managed at all
        self.assertTrue(all(files[r]["sha256"] == sha((self.artifact / r).read_bytes()) for r in files))

    def test_port_first_update_identical_then_one_change_then_new_only(self):  # [port] + spec 1 / 27
        git(self.repo, "reset", "-q", "--hard", self.c1)
        self.build(self.V1, "v1")                          # the very build that is live: nothing to copy
        before = tree(self.target)
        body = self.plan()
        self.assertFalse(body["production"]["manifest_trusted"])
        self.assertEqual(body["summary"]["copied_bytes"], 0)
        self.assertEqual(self.category(body, "modified") | self.category(body, "new"), set())
        result = self.execute(body)
        self.assertEqual(result["changed"], 0)
        self.assertIsNone(result["backup"])
        self.assertFalse(list((self.target / "backup").glob("dcc_release_*")))
        self.assertEqual({r: v for r, v in tree(self.target).items() if r != "DCC_RELEASE_MANIFEST.json"}, before)
        self.assertEqual(self.production()["commit"], self.c1)
        self.assertTrue((self.target / "DCC_RELEASE_MANIFEST.json").exists())

        b_mtime = (self.target / "_internal/b.dat").stat().st_mtime_ns
        body, result = self.release(self.v2(_internal__a_dat=b"changed"), "v2")
        self.assertTrue(body["production"]["manifest_trusted"])
        self.assertEqual(self.category(body, "modified"), {"_internal/a.dat", "BUILD_INFO.txt"})
        backup = Path(result["backup"])
        saved = sorted(p.relative_to(backup).as_posix() for p in backup.rglob("*") if p.is_file())
        self.assertEqual(saved, ["backup_manifest.json", "files/BUILD_INFO.txt", "files/_internal/a.dat"])
        self.assertEqual((backup / "files/_internal/a.dat").read_bytes(), b"original")
        self.assertEqual((self.target / "_internal/b.dat").stat().st_mtime_ns, b_mtime)   # unchanged: never touched
        manifest = json.loads((backup / "backup_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["kind"], "dcc_release_backup")
        self.assertEqual(manifest["release_id"], body["release_id"])
        self.assertEqual(manifest["source_commit"], body["provenance"]["base_head"])
        self.assertEqual(manifest["target_production_commit"], self.c1)
        self.assertTrue(manifest["complete"])
        entry = next(e for e in manifest["modified"] if e["path"] == "_internal/a.dat")
        self.assertEqual(entry, {"path": "_internal/a.dat", "old_sha256": sha(b"original"),
                                 "expected_new_sha256": sha(b"changed"), "backup_sha256": sha(b"original")})
        self.assertEqual(manifest["new"], [])
        self.assertTrue(manifest["created_at"])

        body, result = self.release(self.v2(_internal__a_dat=b"changed", _internal__new_dat=b"new"), "v3")
        self.assertEqual(self.category(body, "new"), {"_internal/new.dat"})
        self.assertEqual(self.category(body, "modified"), {"BUILD_INFO.txt"})
        self.assertEqual(body["summary"]["backup_files"], 1)
        manifest = json.loads((Path(result["backup"]) / "backup_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["new"], [{"path": "_internal/new.dat", "expected_new_sha256": sha(b"new")}])
        for rel, data in {**self.OPERATIONAL, **self.TARGET_ONLY}.items():
            self.assertEqual((self.target / rel).read_bytes(), data, rel)
        self.assertEqual((self.target / "App.exe.previous").read_bytes(), b"exe-v0")   # unchanged EXE never swapped

    def test_new_file_only(self):  # spec 2 (an app without BUILD_INFO: exactly one new file)
        self.use_plain()
        body, result = self.release(self.plain(lib__new_dat=b"new"))
        self.assertEqual(self.category(body, "new"), {"lib/new.dat"})
        self.assertEqual(self.category(body, "modified"), set())
        self.assertEqual(body["summary"]["backup_bytes"], 0)
        self.assertEqual((self.target / "lib/new.dat").read_bytes(), b"new")

    def test_modified_file_only(self):  # spec 3
        self.use_plain()
        body, result = self.release(self.plain(lib__a_dat=b"A2"))
        self.assertEqual(self.category(body, "modified"), {"lib/a.dat"})
        self.assertEqual(self.category(body, "new"), set())
        self.assertEqual(body["summary"]["copied_bytes"], 2)
        self.assertEqual((Path(result["backup"]) / "files/lib/a.dat").read_bytes(), b"A1")

    def test_multiple_modified_files(self):  # spec 4
        self.use_plain()
        body, result = self.release(self.plain(lib__a_dat=b"A2", lib__deep__b_dat=b"B2", App_exe=b"exe-2"))
        self.assertEqual(self.category(body, "modified"), {"lib/a.dat", "lib/deep/b.dat", "App.exe"})
        self.assertEqual(result["modified"], 3)
        self.assertEqual((self.target / "App.exe").read_bytes(), b"exe-2")

    def use_plain(self):
        self.config = PLAIN
        shutil.rmtree(self.target)
        for rel, data in {"App.exe": b"exe-1", "lib/a.dat": b"A1", "lib/deep/b.dat": b"B1",
                          "data/user.db": b"db", "notes.txt": b"target only"}.items():
            write(self.target / rel, data)
        provenance.production_record_path(self.repo).unlink()

    def plain(self, **changes) -> dict:
        files = {"App.exe": b"exe-1", "lib/a.dat": b"A1", "lib/deep/b.dat": b"B1"}
        files.update({rel_of(k): v for k, v in changes.items()})
        return files

    def test_deletion_candidate_stops_and_acknowledged_orphans_are_kept(self):  # spec 5
        self.release(self.v2(_internal__old_dat=b"old"), "v2")
        self.commit("v3")
        self.build(self.v2(), "v3")
        before = tree(self.target)
        body = self.plan()
        self.assertEqual([d["path"] for d in body["deletions"]], ["_internal/old.dat"])
        self.assertTrue(any(r.startswith("DELETION_CANDIDATES") for r in body["stop_reasons"]))
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_BLOCKED")
        self.assertEqual(tree(self.target), before)
        body = self.plan(acknowledge_orphans=True)
        self.assertEqual(body["stop_reasons"], [])
        self.execute(body)
        self.assertEqual((self.target / "_internal/old.dat").read_bytes(), b"old")   # never deleted
        manifest = json.loads((self.target / "DCC_RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertNotIn("_internal/old.dat", {e["path"] for e in manifest["files"]})
        self.commit("v4")                                   # from now on it is an ordinary unmanaged file
        self.build(self.v2(), "v4")
        body = self.plan()
        self.assertEqual(body["deletions"], [])
        self.assertIn("_internal/old.dat", body["retained"])

    def test_unmanaged_target_only_files_are_listed_and_retained(self):  # spec 6
        body, _ = self.release(self.v2(_internal__a_dat=b"changed"))
        for rel in ("README.txt", "_internal/target-only.dat", "DEPLOY_MANIFEST.json", "App.exe.previous"):
            self.assertIn(rel, body["retained"])
            self.assertEqual((self.target / rel).read_bytes(), self.TARGET_ONLY[rel])
        self.assertNotIn("_internal/outputs/r.pdf", body["retained"])        # protected, not "retained"
        self.assertFalse(any(r.startswith("backup/") for r in body["retained"]))

    def test_unmanaged_file_at_a_new_managed_path_stops_once_a_manifest_is_trusted(self):
        self.release(self.v2(), "v2")
        write(self.target / "_internal/plugin.dat", b"put here by hand")
        self.commit("v3")
        self.build(self.v2(_internal__plugin_dat=b"from the build"), "v3")
        body = self.plan()
        self.assertTrue(any("PATH_COLLISION _internal/plugin.dat" in r for r in body["stop_reasons"]))
        with self.assertRaises(re_.ReleaseError):
            self.execute(body)
        self.assertEqual((self.target / "_internal/plugin.dat").read_bytes(), b"put here by hand")

    def test_folder_where_the_build_has_a_file_stops(self):
        (self.target / "_internal/x.dat").mkdir(parents=True)
        self.commit("v2")
        self.build(self.v2(_internal__x_dat=b"file"))
        body = self.plan()
        self.assertTrue(any("PATH_COLLISION _internal/x.dat" in r for r in body["stop_reasons"]))

    def test_port_dry_run_writes_nothing_and_target_drift_is_repaired(self):  # [port]
        self.release(self.v2(), "v2")
        (self.target / "_internal/b.dat").write_bytes(b"damaged")            # a live file changed afterwards
        self.commit("v3")
        self.build(self.v2(), "v3")
        body = self.plan()
        drift = next(f for f in body["files"] if f["path"] == "_internal/b.dat")
        self.assertEqual((drift["category"], drift["drift"]), ("modified", True))
        self.assertEqual(body["summary"]["drift_repaired"], 1)
        self.execute(body)
        self.assertEqual((self.target / "_internal/b.dat").read_bytes(), b"same")

    def test_trusted_manifest_hashes_only_files_whose_metadata_changed(self):
        self.release(self.v2(), "v2")
        self.commit("v3")
        self.build(self.v2(_internal__a_dat=b"v3"), "v3")
        hashed = []
        real = ru.sha256

        def spy(path):
            hashed.append(Path(path).resolve())
            return real(path)

        with mock.patch.object(ru, "sha256", spy):
            body = self.plan()
        share = self.target.resolve()
        live = sorted(p.relative_to(share).as_posix() for p in hashed if p.is_relative_to(share))
        # the manifest trust check reads the manifest, BUILD_INFO and the EXE; every other live file: metadata only
        self.assertEqual(live, ["App.exe", "BUILD_INFO.txt", "DCC_RELEASE_MANIFEST.json"])
        self.assertEqual(body["summary"]["metadata_shortcut_files"], len(body["build_files"]))
        self.assertEqual(self.category(body, "modified"), {"_internal/a.dat", "BUILD_INFO.txt"})


# ====================================================================== manifest trust

class TrustTests(ReleaseCase):
    def test_stale_manifest_falls_back_to_full_verification(self):  # spec 19
        self.release(self.v2(), "v2")
        # a later restore put v1 back: production record and live BUILD_INFO agree, the manifest does not
        info = self.build_info(self.c1, "v1", b"exe-v1")
        (self.target / "BUILD_INFO.txt").write_bytes(info)
        provenance.write_json(provenance.production_record_path(self.repo),
                              {"schema": 1, "commit": self.c1, "version": "v1", "how": "rollback"})
        self.commit("v3")
        self.build(self.v2(), "v3")
        body = self.plan()
        self.assertFalse(body["production"]["manifest_trusted"])
        self.assertTrue(any("manifest commit" in r for r in body["production"]["trust_reasons"]))
        self.assertEqual(body["summary"]["metadata_shortcut_files"], 0)   # every managed file hashed
        self.assertEqual(body["summary"]["hashed_live_bytes"],
                         sum(len(d) for r, d in self.app_state().items() if r in body["build_files"]))
        self.assertEqual(body["deletions"], [])            # an untrusted manifest never yields deletion candidates

    def test_tampered_manifest_is_not_trusted(self):  # spec 20
        self.release(self.v2(), "v2")
        path = self.target / "_internal/b.dat"
        stat = path.stat()
        path.write_bytes(b"SAME")                        # same size, then the old mtime put back
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        manifest_path = self.target / "DCC_RELEASE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append({"path": "_internal/forged.dat", "size": 1, "sha256": "0" * 64, "mtime_ns": 1})
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.commit("v3")
        self.build(self.v2(), "v3")
        body = self.plan()
        self.assertFalse(body["production"]["manifest_trusted"])
        self.assertTrue(any("manifest file hash" in r for r in body["production"]["trust_reasons"]))
        self.assertIn("_internal/b.dat", self.category(body, "modified"))   # found because it was really read
        self.assertEqual(body["deletions"], [])            # the forged entry is never a deletion candidate

    def test_same_metadata_with_other_content_is_caught_when_the_manifest_is_trusted_at_backup(self):
        self.release(self.v2(), "v2")
        path = self.target / "_internal/a.dat"
        stat = path.stat()
        self.commit("v3")
        self.build(self.v2(_internal__a_dat=b"v3-data"), "v3")
        body = self.plan()
        path.write_bytes(b"XXXXXXXX")                      # after the plan, keeping size and mtime
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        before, production = tree(self.target), self.production()
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "SAVE_HASH_MISMATCH")   # the backup copy proves the real content
        self.assert_untouched_after_failure(before, production)

    def test_port_invalid_or_protected_manifest_entries_are_never_trusted(self):  # [port] + spec 8
        self.release(self.v2(), "v2")
        manifest_path = self.target / "DCC_RELEASE_MANIFEST.json"
        original = manifest_path.read_text(encoding="utf-8")
        for rel in ("../escape.txt", "_internal/closing_tasks.json", "_internal/logs/x.txt", "a\\b.txt"):
            with self.subTest(rel=rel):
                manifest = json.loads(original)
                manifest["files"][0]["path"] = rel
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(re_.ReleaseError) as ctx:
                    re_.read_manifest(manifest_path, self.config, "app")
                self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")
                self.commit(f"v3 {rel}")
                self.build(self.v2(), "v3")
                body = self.plan()
                self.assertFalse(body["production"]["manifest_trusted"])
        for rel in ("../x", "/x", "a\\b", "a/./b", "a /b", "a:b"):
            with self.subTest(rel=rel), self.assertRaises(re_.ReleaseError) as ctx:
                re_.safe_join(self.target, rel)
            self.assertEqual(ctx.exception.code, "PATH_INVALID")

    def test_build_info_mismatch_is_refused(self):  # spec 21
        self.commit("v2")
        receipt = self.build(self.v2(), "v2")
        (self.artifact / "BUILD_INFO.txt").write_bytes(self.build_info(self.c1, "v2", b"exe-v1"))
        receipt["artifact_hash"] = provenance.tree_hash(self.artifact)      # a receipt that matches the files
        provenance.write_json(provenance.receipt_path(self.repo), receipt)
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "BUILD_INFO_MISMATCH")
        self.build(self.v2(), "v2")                        # a correct build, but the live BUILD_INFO disagrees with DCC
        (self.target / "BUILD_INFO.txt").write_bytes(self.build_info("f" * 40, "v9", b"exe-v1"))
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "PRODUCTION_MISMATCH")

    def test_exe_that_does_not_match_its_build_info_is_refused(self):
        self.commit("v2")
        receipt = self.build(self.v2(), "v2")
        (self.artifact / "App.exe").write_bytes(b"other exe")
        receipt["artifact_hash"] = provenance.tree_hash(self.artifact)
        provenance.write_json(provenance.receipt_path(self.repo), receipt)
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "BUILD_INFO_MISMATCH")


# ====================================================================== provenance / lifecycle

class LifecycleTests(ReleaseCase):
    def test_port_artifact_changed_after_build_blocks_before_live_changes(self):  # [port] manifest tamper
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        (self.artifact / "_internal/a.dat").write_bytes(b"tampered")
        before = tree(self.target, backups=True)
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "PROVENANCE")
        self.assertEqual(tree(self.target, backups=True), before)

    def test_revoked_build_is_rejected(self):  # spec 24
        head = self.commit("v2")
        self.build(self.v2())
        provenance.write_json(provenance.revoked_path(self.repo), {"revoked": [{"sha": head}]})
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "PROVENANCE")
        self.assertIn("rollback", str(ctx.exception))

    def test_unpushed_or_dirty_build_is_rejected(self):
        self.commit("v2")
        self.build(self.v2())
        (self.repo / "app.py").write_text("local only", encoding="utf-8")
        git(self.repo, "commit", "-q", "-am", "unpushed")
        self.build(self.v2())
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "PROVENANCE")
        self.assertIn("origin/main", str(ctx.exception))
        git(self.repo, "push", "-q", "origin", "main")
        receipt = self.build(self.v2())
        receipt["dirty"] = True
        provenance.write_json(provenance.receipt_path(self.repo), receipt)
        with self.assertRaises(re_.ReleaseError):
            self.plan()

    def test_candidate_or_origin_changed_after_dry_run_stops_before_any_change(self):  # spec 22
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        before, production = tree(self.target), self.production()
        binding = {"expected_sha": body["provenance"]["base_head"], "expected_branch": "main",
                   "candidate_run_id": "r", "approval_at": "t", "run_dev_finished_at": "t"}
        with mock.patch.object(provenance, "candidate_binding", return_value=binding), \
             mock.patch.object(provenance, "_require_candidate_artifact"), self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_DRIFT")
        self.commit("v3 pushed after the plan")            # origin moved on: the build is no longer HEAD
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PROVENANCE")
        self.assert_untouched_after_failure(before, production)

    def test_production_changed_after_dry_run_stops_before_any_change(self):  # spec 23
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        (self.target / "_internal/b.dat").write_bytes(b"someone else's update")
        before, production = tree(self.target), self.production()
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_DRIFT")
        self.assert_untouched_after_failure(before, production)
        body = self.plan()
        record = dict(self.production(), version="edited")
        provenance.write_json(provenance.production_record_path(self.repo), record)
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_DRIFT")

    def test_edited_or_unconfirmed_plan_or_changed_config_is_refused(self):
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        with self.assertRaises(re_.ReleaseError) as ctx:
            ru.execute(Path(body["plan_path"]), body["plan_id"][:8], config=self.config, emit=self.emitted.append)
        self.assertEqual(ctx.exception.code, "NOT_CONFIRMED")
        path = Path(body["plan_path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        data["files"] = [f for f in data["files"] if f["path"] != "_internal/a.dat"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_TAMPERED")
        body = self.plan()
        other = re_.normalize_config(dict(self.config, backup_retention=9))
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body, config=other)
        self.assertEqual(ctx.exception.code, "PLAN_DRIFT")

    def test_failed_update_never_becomes_production(self):  # spec 25
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        production = self.production()
        with mock.patch.object(ru, "_final_checks", side_effect=OSError("verification read failed")), \
             self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "VERIFY_FAILED")
        self.assertEqual(self.production(), production)
        self.assertEqual(self.last_release()["returncode"], 1)
        self.assertEqual(self.last_release()["code"], "VERIFY_FAILED")
        self.assertEqual((self.target / "_internal/a.dat").read_bytes(), b"original")

    def test_success_updates_production_only_at_the_end(self):  # spec 26
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed", App_exe=b"exe-v2"))
        body = self.plan()
        seen = {}
        real = provenance.record_engine_release

        def recorder(repo, plan_body, result, manifest):
            seen["production_before"] = self.production()["commit"]
            seen["target"] = self.app_state()
            seen["manifest_in_target"] = (self.target / "DCC_RELEASE_MANIFEST.json").exists()
            return real(repo, plan_body, result, manifest)

        with mock.patch.object(provenance, "record_engine_release", recorder):
            result = self.execute(body)
        self.assertEqual(seen["production_before"], self.c1)            # untouched until everything verified
        self.assertTrue(seen["manifest_in_target"])
        self.assertEqual(seen["target"]["App.exe"], b"exe-v2")
        production = self.production()
        self.assertEqual(production["commit"], body["provenance"]["base_head"])
        self.assertEqual(production["release_id"], result["release_id"])
        self.assertEqual(production["manifest_sha256"], re_.sha256(self.target / "DCC_RELEASE_MANIFEST.json"))
        self.assertEqual(production["version"], "v2")
        self.assertEqual(self.last_release()["returncode"], 0)
        history = list(provenance.release_record_path(self.repo).parent.glob("release-*.json"))
        self.assertTrue(history)
        manifest = json.loads((self.target / "DCC_RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 2)
        for key in ("release_id", "repo", "deployed_commit", "version", "build_id", "artifact", "provenance",
                    "build_timestamp", "released_at", "engine_version", "previous_release_id", "previous_commit"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["previous_commit"], self.c1)
        entry = next(e for e in manifest["files"] if e["path"] == "App.exe")
        self.assertEqual(entry, {"path": "App.exe", "size": 6, "sha256": sha(b"exe-v2"),
                                 "mtime_ns": (self.target / "App.exe").stat().st_mtime_ns})
        self.assertEqual({e["path"] for e in manifest["files"]}, set(body["build_files"]))

    def test_candidate_release_ends_the_candidate_lifecycle(self):
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        head = git(self.repo, "rev-parse", "HEAD")
        binding = {"expected_sha": head, "expected_branch": "main", "candidate_run_id": "run-1",
                   "approval_at": "t", "run_dev_finished_at": "t"}
        with mock.patch.object(provenance, "candidate_binding", return_value=binding), \
             mock.patch.object(provenance, "_require_candidate_artifact") as gate, \
             mock.patch("scripts.dev_control_center.candidate.mark_deployed") as deployed:
            body = self.plan()
            self.execute(body)
        self.assertEqual(body["provenance"]["route"], "candidate")
        self.assertEqual(gate.call_count, 3)          # proved at dry-run, at execute start and again after staging
        deployed.assert_called_once_with(self.repo.resolve(), head, "run-1", body["provenance"]["build_id"])


# ====================================================================== transactional apply / rollback

class TransactionTests(ReleaseCase):
    def planned(self, **changes):
        self.commit("v2")
        self.build(self.v2(**changes))
        body = self.plan()
        return body, tree(self.target), self.production()

    def test_staging_hash_mismatch_touches_no_live_file(self):  # spec 10
        body, before, production = self.planned(_internal__a_dat=b"changed", _internal__n_dat=b"new")
        real = re_.sha256

        def corrupt(path):
            return "0" * 64 if str(path).endswith(".dcc-stage") else real(path)

        with mock.patch.object(re_, "sha256", corrupt), self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "STAGE_HASH_MISMATCH")
        self.assert_untouched_after_failure(before, production)
        self.assertFalse(list((self.target / "backup").glob("dcc_release_*")))   # the unused backup is removed

    def test_backup_hash_mismatch_touches_no_live_file(self):  # spec 11
        body, before, production = self.planned(_internal__a_dat=b"changed")
        real = re_.sha256

        def corrupt(path):
            return "0" * 64 if "dcc_release_" in str(path) else real(path)

        with mock.patch.object(re_, "sha256", corrupt), self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "SAVE_HASH_MISMATCH")
        self.assert_untouched_after_failure(before, production)

    def test_failure_before_live_mutation_leaves_everything_as_it_was(self):  # spec 12
        body, before, production = self.planned(_internal__a_dat=b"changed", _internal__deep__n_dat=b"new")

        def disk_full(self_, changes):
            raise OSError("disk full while staging")

        with mock.patch.object(re_.Transaction, "_stage", disk_full), self.assertRaises(OSError):
            self.execute(body)
        self.assert_untouched_after_failure(before, production)
        self.assertEqual(self.last_release()["code"], "OSError")

    def test_failure_during_replace_undoes_in_reverse_order(self):  # spec 13 / 14
        body, before, production = self.planned(_internal__a_dat=b"changed", _internal__sub__c_dat=b"c-v2",
                                                 _internal__n_dat=b"new", App_exe=b"exe-v2")
        undone = []
        real_replace = re_.os.replace

        def replace(src, dst):
            if str(src).endswith(".dcc-undo"):
                undone.append(Path(dst).relative_to(self.target).as_posix())
            return real_replace(src, dst)

        applied = []

        def fail_on_fourth(change):
            applied.append(change.rel)
            if len(applied) == 4:
                raise PermissionError("sharing violation")

        with mock.patch.object(re_.os, "replace", replace), self.assertRaises(PermissionError):
            self.execute(body, before_each=fail_on_fourth)
        self.assertEqual(applied[3], "BUILD_INFO.txt")                  # final-swap files after all the others
        expected_undo = [rel for rel in reversed(applied[:3]) if rel != "_internal/n.dat"]
        self.assertEqual(undone, expected_undo)                        # reverse order, from the verified backup
        self.assert_untouched_after_failure(before, production)

    def test_port_failure_at_the_exe_swap_restores_files_and_removes_new_ones(self):  # [port] + spec 16
        self.release(self.v2(), "v2")
        old_manifest = (self.target / "DCC_RELEASE_MANIFEST.json").read_bytes()
        self.commit("v3")
        self.build(self.v2(_internal__a_dat=b"changed", _internal__newdir__n_dat=b"new", App_exe=b"exe-v3"))
        body = self.plan()
        before, production = tree(self.target), self.production()

        def fail_exe(change):
            if change.rel == "App.exe":
                raise OSError("injected swap failure")

        with self.assertRaises(OSError):
            self.execute(body, before_each=fail_exe)
        self.assertEqual((self.target / "DCC_RELEASE_MANIFEST.json").read_bytes(), old_manifest)
        self.assertEqual((self.target / "_internal/a.dat").read_bytes(), b"original")
        self.assertFalse((self.target / "_internal/newdir").exists())    # new file and the folder made for it
        self.assertEqual((self.target / "App.exe").read_bytes(), b"exe-v1")
        self.assert_untouched_after_failure(before, production)

    def test_rollback_incomplete_is_reported_and_blocks_until_cleared(self):  # spec 15
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")

        def fail_exe(change):
            if change.rel == "App.exe":
                raise OSError("injected swap failure")

        with mock.patch.object(re_.Transaction, "undo", return_value=["_internal/a.dat: undo failed"]), \
             self.assertRaises(re_.RollbackIncomplete) as ctx:
            self.execute(body, before_each=fail_exe)
        self.assertEqual(ctx.exception.code, "ROLLBACK_INCOMPLETE")
        backup = next((self.target / "backup").glob("dcc_release_*"))
        self.assertIn(str(backup), str(ctx.exception))                   # the recovery copies are named
        self.assertEqual((backup / "files/_internal/a.dat").read_bytes(), b"original")
        self.assertEqual(self.production(), production)                  # never production
        self.assertEqual(self.last_release()["code"], "ROLLBACK_INCOMPLETE")
        self.assertTrue(ru.inflight_path(self.repo).exists())
        with self.assertRaises(re_.ReleaseError) as stop:     # the next dry-run stops first thing
            self.plan()
        self.assertEqual(stop.exception.code, "INTERRUPTED")
        self.assertIn(str(backup), str(stop.exception))
        with self.assertRaises(re_.ReleaseError) as stop:
            self.execute(body)
        self.assertEqual(stop.exception.code, "INTERRUPTED")
        with self.assertRaises(re_.ReleaseError):
            ru.clear_interrupted(self.repo, "wrong-id-prefix")
        ru.clear_interrupted(self.repo, body["release_id"][:12])
        self.assertFalse(ru.inflight_path(self.repo).exists())

    # ---- Astra review round 1

    def test_unchanged_file_with_same_metadata_but_other_content_stops_before_any_write(self):
        self.release(self.v2(), "v2")
        path = self.target / "_internal/b.dat"
        stat = path.stat()
        path.write_bytes(b"SAME")                          # same size, old mtime put back: looks unchanged
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.commit("v3")
        self.build(self.v2(_internal__a_dat=b"v3"), "v3")
        body = self.plan()
        self.assertEqual(next(f for f in body["files"] if f["path"] == "_internal/b.dat")["category"], "unchanged")
        before, production = tree(self.target), self.production()
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "UNCHANGED_CONTENT_MISMATCH")
        self.assert_untouched_after_failure(before, production)
        body = self.plan()                                 # the contradicted manifest is never trusted again
        self.assertFalse(body["production"]["manifest_trusted"])
        self.assertTrue(any("contradicted" in r for r in body["production"]["trust_reasons"]))
        self.assertIn("_internal/b.dat", self.category(body, "modified"))
        self.execute(body)
        self.assertEqual(path.read_bytes(), b"same")

    def test_failure_while_building_the_manifest_undoes_and_clears_nothing_it_should_keep(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", _internal__n_dat=b"new",
                                                App_exe=b"exe-v2")
        with mock.patch.object(ru, "_manifest_body", side_effect=OSError("share went away")), \
             self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "MANIFEST_WRITE")
        self.assert_untouched_after_failure(before, production)

    def test_unexpected_failure_after_apply_is_undone_and_the_marker_kept_if_undo_fails(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")
        with mock.patch.object(ru, "_undo_or_incomplete", side_effect=KeyError("bug")), \
             mock.patch.object(ru, "_final_checks", side_effect=OSError("x")), self.assertRaises(KeyError):
            self.execute(body)
        self.assert_untouched_after_failure(before, production)     # the generic handler still undid it
        body = self.plan()
        with mock.patch.object(ru, "_final_checks", side_effect=OSError("x")), \
             mock.patch.object(re_.Transaction, "undo", return_value=["App.exe: undo failed"]), \
             self.assertRaises(re_.RollbackIncomplete):
            self.execute(body)
        self.assertTrue(ru.inflight_path(self.repo).exists())

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_the_launch_barrier_holds_through_final_verification_and_undo(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")
        seen = []

        def can_start():
            try:
                open(self.target / "App.exe", "rb").close()
                return True
            except PermissionError:
                return False

        real_checks, real_undo = ru._final_checks, ru._undo_or_incomplete

        def checks(*args, **kwargs):
            seen.append(("verify", can_start()))
            result, detail = real_checks(*args, **kwargs)
            result["forced failure"] = False
            return result, detail

        def undo(*args, **kwargs):
            try:
                return real_undo(*args, **kwargs)
            finally:
                seen.append(("after undo", can_start()))

        with mock.patch.object(ru, "_final_checks", checks), mock.patch.object(ru, "_undo_or_incomplete", undo), \
             self.assertRaises(re_.ReleaseError):
            self.execute(body)
        self.assertEqual(seen, [("verify", False), ("after undo", False)])
        self.assertTrue(can_start())                       # released once the update ended
        self.assert_untouched_after_failure(before, production)

    @unittest.skipUnless(os.name == "nt", "junctions")
    def test_undo_never_writes_through_a_folder_swapped_for_a_junction(self):
        import _winapi

        body, before, production = self.planned(_internal__sub__c_dat=b"c-v2", App_exe=b"exe-v2")
        user = self.target / SAVE / "c.dat"
        write(user, b"user data")
        junction = self.target / "_internal" / "sub"

        def swap_folder_then_fail(change):
            if change.rel == "App.exe":
                os.rename(junction, self.target / "_internal" / "sub_moved")
                _winapi.CreateJunction(str(self.target / SAVE), str(junction))
                raise OSError("injected swap failure")

        try:
            with self.assertRaises(re_.RollbackIncomplete) as ctx:
                self.execute(body, before_each=swap_folder_then_fail)
            self.assertIn("reparse point", str(ctx.exception))
            self.assertEqual(user.read_bytes(), b"user data")          # operational data never written
            self.assertEqual([p.name for p in (self.target / SAVE).iterdir() if p.name.startswith("c.dat.")], [])
            self.assertEqual(self.production(), production)
        finally:
            if junction.exists():
                os.rmdir(junction)

    def test_retention_listing_failure_after_commit_keeps_the_release_successful(self):
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        with mock.patch.object(re_, "engine_backups", side_effect=OSError("listing failed")):
            result = self.execute(body)
        self.assertTrue(result["ok"])
        self.assertTrue(result["retention"]["errors"])
        self.assertEqual(self.production()["commit"], body["provenance"]["base_head"])
        self.assertEqual(self.last_release()["returncode"], 0)

    # ---- Astra review round 2

    def test_hash_verified_unchanged_file_changed_after_the_dry_run_stops_before_any_write(self):
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()                                 # no trusted manifest: b.dat was hashed at dry-run
        item = next(f for f in body["files"] if f["path"] == "_internal/b.dat")
        self.assertEqual((item["category"], item["verified_by"]), ("unchanged", "sha256"))
        path = self.target / "_internal/b.dat"
        stat = path.stat()
        path.write_bytes(b"SAME")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        before, production = tree(self.target), self.production()
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "UNCHANGED_CONTENT_MISMATCH")
        self.assert_untouched_after_failure(before, production)

    @unittest.skipUnless(os.name == "nt", "a real running image")
    def test_a_really_running_exe_is_detected_and_can_not_start_while_held(self):
        exe = self.target / "App.exe"
        original = exe.read_bytes()
        shutil.copyfile(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", exe)
        process = subprocess.Popen([str(exe), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            time.sleep(0.5)
            self.assertTrue(re_.in_use(exe))               # mapped image, no open handle: READ+WRITE probe sees it
        finally:
            process.kill()
            process.wait()
        self.assertFalse(re_.in_use(exe))
        guard = re_.InUseGuard([exe])
        guard.acquire()
        try:
            with self.assertRaises(OSError):               # the launch barrier really prevents a start
                subprocess.Popen([str(exe), "-n", "1", "127.0.0.1"], stdout=subprocess.DEVNULL).wait()
        finally:
            guard.release()
        exe.write_bytes(original)

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_failed_exe_swap_keeps_the_launch_barrier_during_undo(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")
        real_replace, real_undo = re_.os.replace, re_.Transaction.undo
        seen = []

        def replace(src, dst):
            if Path(dst).name == "App.exe" and str(src).endswith(".dcc-stage"):
                raise PermissionError("sharing violation during the swap")
            return real_replace(src, dst)

        def undo(self_):
            try:
                open(self.target / "App.exe", "rb").close()
                seen.append("startable")
            except PermissionError:
                seen.append("held")
            return real_undo(self_)

        with mock.patch.object(re_.os, "replace", replace), mock.patch.object(re_.Transaction, "undo", undo), \
             self.assertRaises(PermissionError):
            self.execute(body)
        self.assertEqual(seen[0], "held")
        self.assert_untouched_after_failure(before, production)

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_app_started_right_after_the_swap_stops_the_rollback_instead_of_changing_files_under_it(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")
        real_replace = re_.os.replace
        holder = {}

        def replace(src, dst):
            real_replace(src, dst)
            if Path(dst).name == "App.exe" and str(src).endswith(".dcc-stage"):
                holder["app"] = open(self.target / "App.exe", "rb")   # someone starts it in that instant

        try:
            with mock.patch.object(re_.os, "replace", replace), self.assertRaises(re_.RollbackIncomplete) as ctx:
                self.execute(body)
        finally:
            holder["app"].close()
        self.assertIn("launch barrier", str(ctx.exception))
        self.assertTrue(ru.inflight_path(self.repo).exists())          # stays interrupted, explicitly
        self.assertEqual(self.production(), production)

    @unittest.skipUnless(os.name == "nt", "junctions")
    def test_retention_never_deletes_through_a_backup_folder_swapped_for_a_junction(self):
        import _winapi

        backups = []
        for number in range(2):
            folder = self.target / "backup" / f"dcc_release_2026010{number}_000000_{number:012d}"
            write(folder / "files" / "x", b"old")
            write(folder / re_.BACKUP_MANIFEST, json.dumps({"kind": re_.BACKUP_KIND, "repo": "app",
                                                            "complete": True}).encode())
            backups.append(folder)
        listed = re_.engine_backups(self.target, dict(self.config, backup_retention=1), "app")
        shutil.rmtree(backups[0])                          # swapped after listing, before deletion
        _winapi.CreateJunction(str(self.target / SAVE), str(backups[0]))
        try:
            with mock.patch.object(re_, "engine_backups", return_value=listed):
                result = re_.prune_backups(self.target, dict(self.config, backup_retention=1), "app")
            self.assertTrue(result["errors"])
            self.assertEqual((self.target / SAVE / "20260927.json").read_bytes(), b"{day}")
        finally:
            os.rmdir(backups[0])

    def test_candidate_record_failure_after_commit_keeps_the_release_and_is_retried(self):
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        head = git(self.repo, "rev-parse", "HEAD")
        binding = {"expected_sha": head, "expected_branch": "main", "candidate_run_id": "run-1",
                   "approval_at": "t", "run_dev_finished_at": "t"}
        with mock.patch.object(provenance, "candidate_binding", return_value=binding), \
             mock.patch.object(provenance, "_require_candidate_artifact"), \
             mock.patch("scripts.dev_control_center.candidate.mark_deployed", side_effect=OSError("state locked")):
            body = self.plan()
            result = self.execute(body)
        self.assertTrue(result["ok"])
        self.assertTrue(result["warnings"])
        self.assertEqual(self.last_release()["returncode"], 0)
        self.assertEqual(self.production()["candidate_pending"]["run_id"], "run-1")
        self.assertFalse(ru.inflight_path(self.repo).exists())
        self.commit("v3")
        self.build(self.v2(), "v3")
        with mock.patch("scripts.dev_control_center.candidate.mark_deployed") as deployed:
            self.plan()                                    # the next dry-run retries the follow-up
        deployed.assert_called_once_with(self.repo.resolve(), head, "run-1", body["provenance"]["build_id"])
        self.assertIsNone(self.production()["candidate_pending"])

    def test_unreadable_revocation_state_fails_closed(self):
        self.commit("v2")
        self.build(self.v2())
        write(provenance.revoked_path(self.repo), b"{not json")
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "PROVENANCE")
        self.assertIn("revoked.json", str(ctx.exception))

    # ---- Astra review round 3

    @unittest.skipUnless(os.name == "nt", "junctions")
    def test_failure_cleanup_never_deletes_through_a_replaced_backup_root(self):
        import _winapi

        body, before, production = self.planned(_internal__a_dat=b"changed")
        outside = self.root / "outside"
        real_stage = re_.Transaction._stage

        def swap_root_then_fail(self_, changes):
            generation = Path(self_.save_root).parent.name
            write(outside / generation / "precious.txt", b"not the engine's")
            os.rename(self.target / "backup", self.target / "backup_moved")
            _winapi.CreateJunction(str(outside), str(self.target / "backup"))
            raise OSError("disk full while staging")

        try:
            with mock.patch.object(re_.Transaction, "_stage", swap_root_then_fail), self.assertRaises(OSError):
                self.execute(body)
            generation = next(outside.iterdir()).name
            self.assertEqual((outside / generation / "precious.txt").read_bytes(), b"not the engine's")
        finally:
            if (self.target / "backup").exists():
                os.rmdir(self.target / "backup")
        self.assertEqual(real_stage, re_.Transaction._stage)

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_rollback_stops_when_the_barrier_is_lost_during_the_exe_undo(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")
        real_replace, real_checks = re_.os.replace, ru._final_checks
        holder = {}

        def replace(src, dst):
            real_replace(src, dst)
            if Path(dst).name == "App.exe" and str(src).endswith(".dcc-undo"):
                holder["app"] = open(self.target / "App.exe", "rb")   # started right after the EXE was put back

        def failing_checks(*args, **kwargs):
            checks, detail = real_checks(*args, **kwargs)
            return dict(checks, **{"forced failure": False}), detail

        try:
            with mock.patch.object(re_.os, "replace", replace), mock.patch.object(ru, "_final_checks", failing_checks), \
                 self.assertRaises(re_.RollbackIncomplete) as ctx:
                self.execute(body)
        finally:
            holder["app"].close()
        self.assertIn("launch barrier", str(ctx.exception))
        self.assertEqual((self.target / "_internal/a.dat").read_bytes(), b"changed")   # not changed under the app
        self.assertTrue(ru.inflight_path(self.repo).exists())
        self.assertEqual(self.production(), production)

    # ---- Astra review round 5

    def test_the_build_lock_is_held_for_the_whole_update(self):
        body, before, production = self.planned(_internal__a_dat=b"changed")
        with provenance.output_lock(self.artifact):          # a DCC BUILD of this artifact is running
            with self.assertRaises(re_.ReleaseError) as ctx:
                self.execute(body)
        self.assertEqual(ctx.exception.code, "LOCKED")
        self.assert_untouched_after_failure(before, production)
        blocked = []

        def build_starts(change):
            try:
                with provenance.output_lock(self.artifact):
                    blocked.append(False)
            except ValueError:
                blocked.append(True)

        self.execute(self.plan(), before_each=build_starts)
        self.assertEqual(blocked, [True, True])            # no BUILD could start while files were replaced

    def test_provenance_change_during_backup_or_staging_stops_before_the_first_replacement(self):
        body, before, production = self.planned(_internal__a_dat=b"changed", App_exe=b"exe-v2")
        real_stage = re_.Transaction.stage

        def stage_then_origin_moves(self_, changes):
            real_stage(self_, changes)
            self.commit("pushed while the update was staging")

        with mock.patch.object(re_.Transaction, "stage", stage_then_origin_moves), \
             self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PROVENANCE")
        self.assert_untouched_after_failure(before, production)
        self.assertFalse(list((self.target / "backup").glob("dcc_release_*")))

    def test_failed_production_write_of_a_first_release_never_becomes_production(self):
        provenance.production_record_path(self.repo).unlink()   # no DCC production record yet
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        real_write = provenance.write_json

        def failing(path, value):
            if Path(path).name == "production.json":
                raise OSError("disk full")
            return real_write(path, value)

        with mock.patch.object(provenance, "write_json", failing), self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "RECORD_FAILED")
        self.assertFalse(provenance.production_record_path(self.repo).exists())   # nothing promoted
        self.assertEqual(self.last_release()["returncode"], 1)
        self.assertTrue(ru.inflight_path(self.repo).exists())                      # reconciled by a person

    def test_an_engine_repo_with_invalid_settings_never_falls_back_to_the_legacy_updater(self):
        registry = self.root / "repos.toml"
        registry.write_text('[release.next-day-setup]\nengine = "dcc"\nmanifest = "保存データ/m.json"\n'
                            'protected = ["保存データ/*"]\n', encoding="utf-8")
        with self.assertRaises(re_.ReleaseError) as ctx:
            re_.release_config("next-day-setup", registry)
        self.assertEqual(ctx.exception.code, "CONFIG_INVALID")
        self.assertTrue(ru.engine_repo("next-day-setup", registry))
        with mock.patch.object(re_, "REGISTRY", registry), self.assertRaises(ValueError) as refused:
            provenance.release_command(self.root / "next-day-setup", self.artifact, self.target)
        self.assertIn("共通UPDATE engine", str(refused.exception))

    def test_an_unreadable_production_record_is_never_treated_as_absent(self):
        self.commit("v2")
        self.build(self.v2())
        for bad in (b"{truncated", b"[]", b'{"commit": 5}'):
            with self.subTest(bad=bad):
                provenance.production_record_path(self.repo).write_bytes(bad)
                with self.assertRaises(re_.ReleaseError) as ctx:
                    self.plan()
                self.assertEqual(ctx.exception.code, "STATE_UNREADABLE")

    def test_new_file_changed_by_someone_is_not_removed_by_undo(self):
        body, before, production = self.planned(_internal__n_dat=b"new", App_exe=b"exe-v2")

        def edit_then_fail(change):
            if change.rel == "App.exe":
                (self.target / "_internal/n.dat").write_bytes(b"someone's own file now")
                raise OSError("injected swap failure")

        with self.assertRaises(re_.RollbackIncomplete) as ctx:
            self.execute(body, before_each=edit_then_fail)
        self.assertIn("_internal/n.dat", str(ctx.exception))
        self.assertEqual((self.target / "_internal/n.dat").read_bytes(), b"someone's own file now")
        self.assertEqual(self.production(), production)

    def test_operational_change_during_update_undoes_the_app_and_keeps_the_data(self):
        body, before, production = self.planned(_internal__a_dat=b"changed")

        def user_saves(change):
            (self.target / "master_settings.json").write_bytes(b"{saved meanwhile}")

        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body, before_each=user_saves)
        self.assertEqual(ctx.exception.code, "OPERATIONAL_CHANGED")
        self.assertEqual((self.target / "master_settings.json").read_bytes(), b"{saved meanwhile}")
        self.assertEqual((self.target / "_internal/a.dat").read_bytes(), b"original")
        self.assertEqual(self.production(), production)

    def test_protected_paths_are_refused_in_every_write_function(self):  # spec 7
        root = self.root / "guard"
        write(root / "_internal/closing_tasks.json", b"x")
        change = re_.Change("_internal/closing_tasks.json", root / "_internal/closing_tasks.json",
                            root / "_internal/closing_tasks.json", sha(b"y"), sha(b"x"))
        transaction = re_.Transaction(root, root / "saved", re_.protected_of(self.config))
        for step in (transaction.save, transaction.stage, transaction.apply):
            with self.subTest(step=step.__name__), self.assertRaises(re_.ReleaseError) as ctx:
                step([change])
            self.assertEqual(ctx.exception.code, "PROTECTED_WRITE")
        self.assertEqual((root / "_internal/closing_tasks.json").read_bytes(), b"x")
        with self.assertRaises(re_.ReleaseError) as ctx:         # the manifest can never be operational data
            re_.normalize_config(dict(self.config, manifest="保存データ/manifest.json"))
        self.assertEqual(ctx.exception.code, "CONFIG_INVALID")
        body, _, _ = self.planned()
        self.assertIn("_internal/master_settings.json", body["protected_in_build"])   # bundled default: never deployed
        self.assertNotIn("_internal/master_settings.json", body["build_files"])

    @unittest.skipUnless(os.name == "nt", "junctions")
    def test_reparse_point_in_the_target_is_refused(self):  # spec 9
        import _winapi

        outside = self.root / "outside"
        outside.mkdir()
        _winapi.CreateJunction(str(outside), str(self.target / "_internal" / "linked"))
        try:
            self.commit("v2")
            self.build(self.v2(_internal__linked__x_dat=b"x"))
            with self.assertRaises(re_.ReleaseError) as ctx:
                self.plan()
            self.assertEqual(ctx.exception.code, "PATH_REPARSE")
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            os.rmdir(self.target / "_internal" / "linked")

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_exe_in_use_stops_before_any_change(self):  # spec 17
        body, before, production = self.planned(_internal__a_dat=b"changed")
        with open(self.target / "App.exe", "rb"):            # the app runs on some PC
            with self.assertRaises(re_.ReleaseError) as ctx:
                self.execute(body)
        self.assertEqual(ctx.exception.code, "IN_USE")
        self.assert_untouched_after_failure(before, production)

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_app_started_after_staging_stops_and_the_guard_blocks_starts_during_apply(self):
        body, before, production = self.planned(_internal__a_dat=b"changed")
        real_stage = re_.Transaction.stage
        holder = {}

        def stage_then_app_starts(self_, changes):
            real_stage(self_, changes)
            holder["handle"] = open(self.target / "App.exe", "rb")

        try:
            with mock.patch.object(re_.Transaction, "stage", stage_then_app_starts), \
                 self.assertRaises(re_.ReleaseError) as ctx:
                self.execute(body)
        finally:
            holder["handle"].close()
        self.assertEqual(ctx.exception.code, "IN_USE")
        self.assert_untouched_after_failure(before, production)
        blocked = []

        def try_to_start(change):
            if change.rel == "_internal/a.dat":
                try:
                    open(self.target / "App.exe", "rb").close()
                except PermissionError:
                    blocked.append(True)

        self.execute(self.plan(), before_each=try_to_start)
        self.assertEqual(blocked, [True])                  # nobody can open the EXE while the folder is mixed

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_lock_collision_stops_before_any_change(self):  # spec 18
        body, before, production = self.planned(_internal__a_dat=b"changed")
        for name in LOCKS:
            with self.subTest(lock=name), re_.ExclusiveLock(self.target / name):
                with self.assertRaises(re_.ReleaseError) as ctx:
                    self.execute(body)
                self.assertEqual(ctx.exception.code, "LOCKED")
        self.assert_untouched_after_failure(before, production)


# ====================================================================== dry-run, progress, retention

class OperationTests(ReleaseCase):
    def test_dry_run_performs_zero_writes_to_the_share_and_never_enters_other_folders(self):  # spec 30
        for rel, data in {"python/Lib/legacy.py": b"legacy", "outputs/x.pdf": b"pdf", "_上書き前バックアップ/x": b"x"}.items():
            write(self.target / rel, data)
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed", _internal__n_dat=b"new"))
        before = tree(self.target, backups=True)
        share = self.target.resolve()
        writes, walked = [], []
        real_open, real_walk, real_scandir = open, os.walk, os.scandir

        def opener(file, mode="r", *a, **k):
            if isinstance(file, (str, Path)) and any(c in mode for c in "wax+"):
                writes.append(Path(file))
            return real_open(file, mode, *a, **k)

        def walk(top, *a, **k):
            walked.append(Path(top))
            return real_walk(top, *a, **k)

        def scandir(path=".", *a, **k):
            walked.append(Path(path))
            return real_scandir(path, *a, **k)

        spies = [mock.patch("builtins.open", opener), mock.patch.object(re_.os, "walk", walk),
                 mock.patch.object(re_.os, "scandir", scandir)]
        for name in ("replace", "rename", "unlink", "mkdir", "makedirs", "rmdir", "remove"):
            real = getattr(os, name)
            spies.append(mock.patch.object(re_.os, name, (lambda real: lambda p, *a, **k: (
                writes.append(Path(p)), real(p, *a, **k))[1])(real)))
        for spy in spies:
            spy.start()
        try:
            body = self.plan()
        finally:
            for spy in reversed(spies):
                spy.stop()
        self.assertEqual([w for w in writes if w.resolve().is_relative_to(share)], [])
        self.assertEqual(tree(self.target, backups=True), before)
        entered = {p.resolve() for p in walked if p.resolve().is_relative_to(share)}
        allowed = {share} | {share / d for d in ("_internal", SAVE, "print_work", "logs", "log")}
        self.assertEqual({p for p in entered if not any(p == a or p.is_relative_to(a) for a in allowed)}, set())
        self.assertTrue(Path(body["plan_path"]).is_file())                # the plan is kept in local DCC state
        self.assertTrue(Path(body["plan_path"]).is_relative_to(Path(os.environ["LOCALAPPDATA"])))
        for key in ("managed", "unchanged", "modified", "new", "deletion_candidates", "retained", "protected_live",
                    "backup_files", "copied_bytes", "backup_bytes"):
            self.assertIn(key, body["summary"])
        self.assertIn("estimated_execute_seconds", body)
        self.assertEqual(body["production"]["live_commit"], self.c1)

    def test_progress_stages_are_emitted_with_counts(self):  # spec 29
        self.commit("v2")
        self.build(self.v2(_internal__a_dat=b"changed"))
        body = self.plan()
        for number, title in enumerate(ru.STAGES, 1):
            self.assertTrue(any(line.startswith(f"[{number}/7] {title}") for line in self.emitted), title)
        self.emitted.clear()
        self.execute(body)
        for number, title in enumerate(ru.STAGES, 1):
            self.assertTrue(any(line.startswith(f"[{number}/7] {title}") for line in self.emitted), title)
        self.assertTrue(any("modified 2 / new 0" in line for line in self.emitted))
        self.assertTrue(any("applied 2 / 2" in line for line in self.emitted))

    def test_backup_retention_keeps_the_newest_engine_backups_only(self):  # spec 28
        foreign = {"backup/dcc_release_20200101_000000_other/backup_manifest.json":
                   json.dumps({"kind": "dcc_release_backup", "repo": "other-app", "complete": True}).encode(),
                   "backup/dcc_release_20200101_000001_partial/x": b"no manifest",
                   "backup/rollback_before_20260928_154236_910d29de78d4/x": b"restore evidence"}
        for rel, data in foreign.items():
            write(self.target / rel, data)
        backups = []
        for number in range(5):
            _, result = self.release(self.v2(_internal__a_dat=f"v{number}".encode()), f"v{number + 2}")
            backups.append(Path(result["backup"]).name)
            time.sleep(1.1)                                  # backup folder names carry a seconds stamp
        kept = sorted(p.name for p in (self.target / "backup").glob("dcc_release_*"))
        self.assertEqual([k for k in kept if k in backups], backups[-3:])
        self.assertTrue((self.target / "backup/update_before_20260801_000000/_internal/huge.bin").exists())
        for rel in foreign:
            self.assertTrue((self.target / rel).exists(), rel)   # other repos / incomplete / legacy never pruned

    def test_the_legacy_update_route_is_refused_for_engine_repos(self):
        with self.assertRaises(ValueError) as ctx:
            provenance.release_command(self.root / "next-day-setup", self.artifact, self.target)
        self.assertIn("共通UPDATE engine", str(ctx.exception))

    def test_the_next_day_setup_configuration_is_valid_and_ports_the_legacy_rules(self):
        config = re_.release_config("next-day-setup")
        self.assertEqual(config["engine"], "dcc")
        self.assertEqual(config["final_swap"][-1], "DinnerSystem.exe")
        self.assertEqual(config["lock"], ".dcc-release.lock")
        self.assertIn(".nds-update.lock", config["legacy_locks"])
        managed = {"DinnerSystem.exe", "_internal/a/b.dll", "BUILD_INFO.txt", "操作説明書.txt", "夕食料飲システム.vbs",
                   "夕食料飲システムを起動.bat", "_internal/config/print_preparation.json"}
        never = {"config/print_preparation.json", "_internal/master_settings.json", "_internal/closing_tasks.json",
                 "ui_prefs.json", "_internal/outputs/x.pdf", "_internal/logs/a.txt", "_internal/x/log/a.txt",
                 "保存データ/a.json", "print_work/a.png", "a.log", "_internal/tools/SumatraPDF-settings.txt",
                 "backup/x.txt", "_internal/backup/x", "sub/x.txt", "DEPLOY_MANIFEST.json", "DinnerSystem.exe.previous"}
        for rel in managed:
            self.assertTrue(re_.managed(config, rel), rel)
        for rel in never:
            self.assertFalse(re_.managed(config, rel), rel)


if __name__ == "__main__":
    unittest.main()
