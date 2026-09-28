"""restore_release (DCC rollback from a verified full backup) and the release_engine primitives it uses.

A fixture deployment: `backup` is a verified v1.4.0 build (BUILD_INFO / DEPLOY_MANIFEST / EXE), `target`
is the same folder after an unwanted update of a few app files, with operational data and target-only
files that the restore must never touch."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from scripts.dev_control_center import release_engine as re_
from scripts.dev_control_center import restore_release as rr

OLD, NEW = "1a03178deb31fe8c3592bf57c957565b00f43bdc", "910d29de78d45b6497a97e79786da94ca506483c"
SAVE = "保存データ"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def tree(root: Path) -> dict:
    """Every file with bytes and mtime; the lock file (created on first use, present on production) is ignored."""
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file() and p.name != ".nds-update.lock"}


class RestoreCase(unittest.TestCase):
    APP = {"_internal/base_library.zip": b"lib-v140", "_internal/ucrtbase.dll": b"crt-v140",
           "_internal/unchanged.dll": b"same", "launch.bat": b"@echo v140"}
    CHANGED = {"_internal/base_library.zip": b"lib-v130", "_internal/ucrtbase.dll": b"crt-v130"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dcc restore ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.target = self.root / "share"
        self.backup = self.target / "backup" / "update_before_20260928_125309"
        self.write_build(self.backup, OLD, "v1.4.0", b"exe-v140", previous=b"exe-v13x-old")
        for rel, data in {"closing_tasks.json": b"{tasks}", "master_settings.json": b"{settings}",
                          f"{SAVE}/20260927.json": b"{day}", "print_work/p.png": b"png", "app.log": b"log",
                          "_internal/outputs/r.pdf": b"pdf", "_internal/closing_tasks.json": b"{legacy}",
                          "README.txt": b"legacy file outside the build"}.items():
            self.write(self.backup / rel, data)
        # the live folder = backup contents, then an unwanted update of some app files
        for path in list(self.backup.rglob("*")):
            if path.is_file():
                dest = self.target / path.relative_to(self.backup)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        for rel, data in self.CHANGED.items():
            self.write(self.target / rel, data)
        self.write(self.target / "DinnerSystem.exe.previous", b"exe-v140")
        self.write(self.target / "DinnerSystem.exe", b"exe-v130")
        self.write(self.target / "BUILD_INFO.txt", self.build_info(NEW, "v1.3.0", b"exe-v130"))
        self.write(self.target / "_internal/new_only_in_target.txt", b"target-only")
        self.plan_path = self.root / "plan.json"
        record = mock.patch.object(rr, "record_rollback")
        self.record = record.start()
        self.addCleanup(record.stop)

    @staticmethod
    def write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    @staticmethod
    def build_info(commit, version, exe) -> bytes:
        return (f"App version: {version}\nGit commit SHA: {commit}\nGit branch: b\nBuild date/time: t\n"
                f"Git working tree: clean\nEXE SHA-256: {sha(exe)}\n").encode()

    def write_build(self, root: Path, commit, version, exe, previous=None):
        files = dict(self.APP)
        files["DinnerSystem.exe"] = exe
        files["BUILD_INFO.txt"] = self.build_info(commit, version, exe)
        for rel, data in files.items():
            self.write(root / rel, data)
        if previous:
            self.write(root / "DinnerSystem.exe.previous", previous)
        manifest = {"schema_version": 1, "build_commit": commit,
                    "files": [{"path": rel, "sha256": sha(data), "size": len(data)} for rel, data in files.items()]}
        self.write(root / "DEPLOY_MANIFEST.json", json.dumps(manifest).encode())

    def plan(self, **extra):
        values = dict(target=self.target, backup=self.backup, repo_name="next-day-setup", commit=OLD, version="v1.4.0",
                      out=self.plan_path, emit=lambda text: None)
        values.update(extra)
        return rr.plan(**values)

    def execute(self, body, **extra):
        return rr.execute(self.plan_path, body["plan_id"][:12], dcc_repo=self.root / "repo", emit=lambda t: None, **extra)

    def operational(self):
        return {rel: v for rel, v in tree(self.target).items()
                if not rel.startswith("backup/") and rel not in rr.release_config("next-day-setup")["records"]
                and (rr.protected_of(rr.release_config("next-day-setup"))(rel) or rel == "README.txt")}


class PlanTests(RestoreCase):
    def test_plan_lists_exactly_the_changed_app_files_and_writes_nothing(self):
        before = tree(self.target)
        body = self.plan(expect_count=5)
        self.assertEqual(tree(self.target), before)                         # dry run: nothing written (backup included)
        planned = {f["path"]: f for f in body["files"]}
        self.assertEqual(set(planned), {"_internal/base_library.zip", "_internal/ucrtbase.dll", "DinnerSystem.exe",
                                        "DinnerSystem.exe.previous", "BUILD_INFO.txt"})
        self.assertEqual(planned["DinnerSystem.exe"]["current_sha256"], sha(b"exe-v130"))
        self.assertEqual(planned["DinnerSystem.exe"]["expected_sha256"], sha(b"exe-v140"))
        self.assertEqual(body["expected"]["exe_sha256"], sha(b"exe-v140"))
        self.assertEqual(body["expected"]["previous_sha256"], sha(b"exe-v13x-old"))
        self.assertEqual(body["expected"]["build_info"]["Git commit SHA"], OLD)
        self.assertEqual(body["expected"]["deploy_manifest_commit"], OLD)
        for untouched in ("closing_tasks.json", f"{SAVE}/20260927.json", "_internal/outputs/r.pdf", "README.txt",
                          "_internal/unchanged.dll", "DEPLOY_MANIFEST.json"):
            self.assertNotIn(untouched, planned)
        self.assertNotIn("_internal/new_only_in_target.txt", planned)         # target-only: never planned
        self.assertTrue(body["guard"]["ok"])
        self.assertEqual(body["guard"]["protected_write_plans"], 0)
        self.assertEqual(body["operational"]["dry_run_diff"], {"changed": [], "created": [], "missing": []})
        self.assertEqual(set(body["operational"]["critical"]),
                         {"closing_tasks.json", "master_settings.json", "_internal/closing_tasks.json"})

    def test_dry_run_never_scans_the_whole_share_or_other_backup_generations(self):
        unrelated = {"backup/update_before_20260801_000000/_internal/huge.bin": b"old generation",
                     "backup/closing_task_master_20260801.json": b"{old}",
                     "python/Lib/legacy.py": b"legacy layout", "dinner_system/old.py": b"legacy",
                     "config/print_preparation.json": b"{cfg}"}
        for rel, data in unrelated.items():
            self.write(self.target / rel, data)
        before = tree(self.target)
        walked, stated, opened, writes = [], [], [], []
        real_walk, real_scandir, real_stat, real_open = os.walk, os.scandir, os.stat, open

        def walk(top, *a, **k):
            walked.append(Path(top))
            return real_walk(top, *a, **k)

        def scandir(path=".", *a, **k):
            walked.append(Path(path))
            return real_scandir(path, *a, **k)

        def stat(path, *a, **k):
            stated.append(Path(path))
            return real_stat(path, *a, **k)

        def opener(file, mode="r", *a, **k):
            if isinstance(file, (str, Path)):
                opened.append(Path(file))
                if any(c in mode for c in "wax+"):
                    writes.append(Path(file))
            return real_open(file, mode, *a, **k)

        with mock.patch.object(re_.os, "walk", walk), mock.patch.object(re_.os, "scandir", scandir), \
             mock.patch("os.stat", stat), mock.patch("builtins.open", opener):
            body = self.plan(expect_count=5)
        self.assertEqual(tree(self.target), before)
        share = self.target.resolve()
        touched = [p.resolve() for p in walked + stated + opened if p.resolve().is_relative_to(share)]
        forbidden = [share / "backup" / "update_before_20260801_000000", share / "python", share / "dinner_system",
                     share / "config", share / "backup" / "closing_task_master_20260801.json"]
        for path in touched:
            for bad in forbidden:
                self.assertFalse(path == bad or path.is_relative_to(bad), f"touched {path}")
        roots = {p.resolve() for p in walked}
        allowed = {share} | {share / d for d in ("_internal", SAVE, "print_work", "logs", "log")}
        outside = {p for p in roots if p.is_relative_to(share) and p != share
                   and not any(p.is_relative_to(root) for root in allowed - {share})}
        self.assertEqual(outside, set())                                    # only the configured roots are entered
        self.assertNotIn(share / "backup", roots)                            # the backup root is never walked
        self.assertNotIn(self.backup.resolve(), roots)                      # nor the rollback source as a tree
        self.assertEqual([w for w in writes if w.resolve().is_relative_to(share)], [])   # 0 writes to the share
        self.assertEqual(body["scope"]["backup_files_stat_and_hashed"], body["scope"]["live_release_files_stat_and_hashed"])

    def test_change_during_the_dry_run_is_caught_by_its_guard(self):
        real = rr._hash_files
        calls = []

        def hash_and_disturb(root, rels, progress, label):
            calls.append(label)
            if len(calls) == 1:
                self.write(self.target / SAVE / "20260927.json", b"{edited while planning}")
            return real(root, rels, progress, label)

        with mock.patch.object(rr, "_hash_files", hash_and_disturb):
            body = self.plan()
        self.assertFalse(body["guard"]["ok"])
        self.assertEqual(body["operational"]["dry_run_diff"]["changed"], [f"{SAVE}/20260927.json"])
        self.assertIn(f"{SAVE}/20260927.json", body["operational"]["changed_file_hashes"])

    def test_backup_that_is_not_exactly_the_expected_build_is_refused(self):
        cases = {
            "commit": lambda: self.plan(commit=NEW),
            "version": lambda: self.plan(version="v1.3.0"),
            "tampered file": lambda: (self.write(self.backup / "_internal/unchanged.dll", b"tampered"), self.plan())[1],
        }
        for name, run in cases.items():
            with self.subTest(name), self.assertRaises(re_.ReleaseError) as ctx:
                run()
            self.assertEqual(ctx.exception.code, "BACKUP_IDENTITY")

    def test_unexpected_plan_size_stops(self):
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.plan(expect_count=46)
        self.assertEqual(ctx.exception.code, "PLAN_COUNT")

    def test_a_protected_path_can_never_become_a_candidate(self):
        config = dict(rr.release_config("next-day-setup"), records=["closing_tasks.json"])
        with mock.patch.object(rr, "release_config", return_value=config), self.assertRaises(re_.ReleaseError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, "PROTECTED_WRITE")


class ExecuteTests(RestoreCase):
    def test_restore_brings_back_exactly_the_backup_and_keeps_operational_data(self):
        body = self.plan()
        operational = self.operational()
        result = self.execute(body)
        self.assertTrue(result["ok"], result)
        for rel, expected in body["expected"]["all_candidates"].items():
            self.assertEqual(re_.sha256(self.target / rel), expected, rel)
        self.assertEqual((self.target / "DinnerSystem.exe").read_bytes(), b"exe-v140")
        self.assertEqual((self.target / "DinnerSystem.exe.previous").read_bytes(), b"exe-v13x-old")
        self.assertIn(OLD, (self.target / "BUILD_INFO.txt").read_text())
        self.assertEqual(self.operational(), operational)                   # bytes and mtimes untouched
        saved = Path(result["saved"])
        self.assertEqual((saved / "DinnerSystem.exe").read_bytes(), b"exe-v130")  # the 9/28 files are kept
        manifest = json.loads((saved / "rollback_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual({f["path"] for f in manifest["files"]}, {f["path"] for f in body["files"]})
        self.assertEqual(sorted(p.name for p in saved.rglob("*") if p.is_file()),
                         sorted([Path(f["path"]).name for f in body["files"]] + ["rollback_manifest.json"]))
        self.record.assert_called_once()
        self.assertFalse(list(self.target.rglob("*.dcc-stage")))

    def test_confirmation_of_the_reviewed_plan_is_required(self):
        body = self.plan()
        with self.assertRaises(re_.ReleaseError) as ctx:
            rr.execute(self.plan_path, "wrong", emit=lambda t: None)
        self.assertEqual(ctx.exception.code, "NOT_CONFIRMED")
        self.assertEqual((self.target / "DinnerSystem.exe").read_bytes(), b"exe-v130")

    def test_edited_plan_is_refused_even_with_the_original_id(self):
        body = self.plan()
        before = tree(self.target)
        for field, value in (("target", str(self.root / "elsewhere")), ("files", body["files"][:1]),
                             ("restore_version", "v9")):
            with self.subTest(field=field):
                edited = dict(body, **{field: value})
                self.plan_path.write_text(json.dumps(edited), encoding="utf-8")
                with self.assertRaises(re_.ReleaseError) as ctx:
                    rr.execute(self.plan_path, body["plan_id"][:12], emit=lambda t: None)
                self.assertEqual(ctx.exception.code, "PLAN_TAMPERED")
        self.assertEqual(tree(self.target), before)

    def test_an_unchanged_managed_file_changing_after_the_plan_stops_before_any_change(self):
        body = self.plan()
        (self.target / "DEPLOY_MANIFEST.json").unlink()   # not a restore target, but relied on by verification
        before = tree(self.target)
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_DRIFT")
        self.assertEqual(tree(self.target), before)

    def test_verification_that_can_not_complete_undoes_the_restore(self):
        body = self.plan()
        before = tree(self.target)

        def break_manifest(change):
            if change.rel == "DinnerSystem.exe":
                (self.target / "DEPLOY_MANIFEST.json").write_text("{broken", encoding="utf-8")

        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body, before_each=break_manifest)
        self.assertEqual(ctx.exception.code, "VERIFY_FAILED")
        after = tree(self.target)
        for rel, (data, _) in before.items():
            if not rel.startswith("backup/") and rel != "DEPLOY_MANIFEST.json":
                self.assertEqual(after[rel][0], data, rel)                  # every restored file put back
        self.record.assert_not_called()

    def test_drift_after_the_dry_run_stops_before_any_change(self):
        body = self.plan()
        self.write(self.target / "_internal/ucrtbase.dll", b"someone else")
        before = tree(self.target)
        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "PLAN_DRIFT")
        self.assertEqual(tree(self.target), before)
        self.record.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "share-mode semantics")
    def test_running_app_or_held_lock_stops_before_any_change(self):
        body = self.plan()
        before = tree(self.target)
        with open(self.target / "DinnerSystem.exe", "rb"):          # the app is open somewhere
            with self.assertRaises(re_.ReleaseError) as ctx:
                self.execute(body)
        self.assertEqual(ctx.exception.code, "IN_USE")
        with re_.ExclusiveLock(self.target / ".nds-update.lock"):   # another updater holds the lock
            with self.assertRaises(re_.ReleaseError) as ctx:
                self.execute(body)
        self.assertEqual(ctx.exception.code, "LOCKED")
        self.assertEqual(tree(self.target), before)

    def assert_back_to_pre_restore(self, before):
        after = tree(self.target)
        for rel, (data, _) in before.items():
            if not rel.startswith("backup/"):
                self.assertEqual(after[rel][0], data, rel)
        self.assertFalse(list(self.target.rglob("*.dcc-stage")))
        self.record.assert_not_called()

    def test_failure_in_the_middle_of_several_files_undoes_every_applied_file(self):
        body = self.plan()
        before = tree(self.target)
        calls = []

        def fail_third(change):
            calls.append(change.rel)
            if len(calls) == 3:
                raise OSError("network share dropped")

        with self.assertRaises(OSError):
            self.execute(body, before_each=fail_third)
        self.assert_back_to_pre_restore(before)

    def test_replace_failure_of_the_exe_after_the_others_undoes_them(self):
        body = self.plan()
        before = tree(self.target)
        real = os.replace

        def replace(src, dst, *a, **k):
            if Path(dst).name == "DinnerSystem.exe" and ".dcc-stage" in Path(src).name:
                raise PermissionError("EXE locked while replacing")
            return real(src, dst, *a, **k)

        with mock.patch.object(re_.os, "replace", side_effect=replace), self.assertRaises(PermissionError):
            self.execute(body)
        self.assert_back_to_pre_restore(before)
        self.assertEqual((self.target / "DinnerSystem.exe.previous").read_bytes(), b"exe-v140")

    def test_staged_copy_hash_mismatch_touches_no_live_file(self):
        body = self.plan()
        before = tree(self.target)
        real = re_.Transaction.stage

        def corrupt(self_, changes):
            changes[0].expected_sha = "0" * 64
            return real(self_, changes)

        with mock.patch.object(re_.Transaction, "stage", corrupt), self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body)
        self.assertEqual(ctx.exception.code, "STAGE_HASH_MISMATCH")
        self.assert_back_to_pre_restore(before)

    def test_operational_change_during_restore_is_reported_not_recorded(self):
        body = self.plan()

        def user_saves(change):
            if change.rel == "DinnerSystem.exe":
                self.write(self.target / SAVE / "20260928.json", b"{new day}")

        with self.assertRaises(re_.ReleaseError) as ctx:
            self.execute(body, before_each=user_saves)
        self.assertEqual(ctx.exception.code, "OPERATIONAL_CHANGED")
        self.assertEqual((self.target / SAVE / "20260928.json").read_bytes(), b"{new day}")  # never reverted
        self.record.assert_not_called()


class PrimitiveTests(unittest.TestCase):
    def test_protected_paths_are_refused_in_every_write_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "closing_tasks.json").write_bytes(b"x")
            change = re_.Change("closing_tasks.json", root / "closing_tasks.json", root / "closing_tasks.json",
                                sha(b"y"), sha(b"x"))
            transaction = re_.Transaction(root, root / "saved", re_.Protected(names=("closing_tasks.json",)))
            for step in (transaction.save, transaction.stage, transaction.apply):
                with self.subTest(step=step.__name__), self.assertRaises(re_.ReleaseError) as ctx:
                    step([change])
                self.assertEqual(ctx.exception.code, "PROTECTED_WRITE")
            self.assertEqual((root / "closing_tasks.json").read_bytes(), b"x")

    def test_invalid_and_linked_paths_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("../x", "/x", "a\\b", "a/./b", "a /b", "a:b"):
                with self.subTest(rel=rel), self.assertRaises(re_.ReleaseError):
                    re_.safe_join(root, rel)
            if os.name == "nt":
                import _winapi

                (root / "real").mkdir()
                _winapi.CreateJunction(str(root / "real"), str(root / "link"))
                try:
                    with self.assertRaises(re_.ReleaseError) as ctx:
                        re_.safe_join(root, "link/file")
                    self.assertEqual(ctx.exception.code, "PATH_REPARSE")
                finally:
                    os.rmdir(root / "link")  # the junction itself, never its target

    def test_metadata_diff_detects_presence_size_and_mtime(self):
        before = {"a": (1, 0), "b": (2, 0), "c": (3, 0)}
        after = {"a": (1, 1_000), "b": (5, 0), "d": (1, 0)}
        self.assertEqual(re_.metadata_diff(before, after), {"changed": ["b"], "created": ["d"], "missing": ["c"]})


if __name__ == "__main__":
    unittest.main()
