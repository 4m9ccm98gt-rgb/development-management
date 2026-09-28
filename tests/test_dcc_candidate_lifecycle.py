"""Orchestrator candidate lifecycle in DCC: one reviewed SHA from RUN_DEV through push, BUILD and UPDATE.

Real Git (a bare origin, a source clone, a second clone that moves the base), real run files and a
real temporary venv. Nothing touches the user's repositories; push goes to the temporary bare origin.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.dev_control_center import app as dcc_app
from scripts.dev_control_center import candidate as cf
from scripts.dev_control_center import entrypoints, provenance
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import write_json_atomic

APP = ("import json, os, pathlib, sys\n"
       "pathlib.Path(os.environ['PROBE_OUT']).write_text(json.dumps({'exe': sys.executable, 'cwd': os.getcwd(),"
       " 'file': __file__, 'marker': pathlib.Path('marker.txt').read_text().strip(),"
       " 'setting': pathlib.Path('local.json').read_text() if pathlib.Path('local.json').exists() else None}))\n"
       "data = pathlib.Path('data')\n"
       "if data.is_dir(): (data / 'state.txt').write_text((data / 'state.txt').read_text() + 'run\\n')\n"
       "sys.exit(int(os.environ.get('APP_RC', '0')))\n")
SPEC = {"demoapp": {"cwd": ".", "entry": "app.py", "probe": "import json"}}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class LifecycleCase(unittest.TestCase):
    IGNORE = ".venv/\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"AI_ORCHESTRATOR_STATE_ROOT": str(self.tmp / "orch"),
                                           "LOCALAPPDATA": str(self.tmp / "local"), "PROBE_OUT": str(self.tmp / "probe.json")})
        env.start()
        self.addCleanup(env.stop)
        self.origin = self.tmp / "origin.git"
        self.repo = self.tmp / "demoapp"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(self.origin), str(self.repo)], check=True, capture_output=True)
        self.configure(self.repo)
        (self.repo / ".gitignore").write_text(self.IGNORE, encoding="utf-8")
        (self.repo / "app.py").write_text(APP, encoding="utf-8")
        (self.repo / "marker.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "base")
        git(self.repo, "push", "-u", "origin", "main")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.sha = self.make_candidate("candidate")
        self.addCleanup(self.remove_worktrees)
        specs = mock.patch.object(entrypoints, "run_specs", return_value=SPEC)
        specs.start()
        self.addCleanup(specs.stop)

    @staticmethod
    def configure(repo):
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")

    def remove_worktrees(self):
        for line in git(self.repo, "worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree ") and Path(line[9:]).resolve() != self.repo.resolve():
                subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force", line[9:]], capture_output=True)

    def make_candidate(self, text, run_id="20260926-165346-534560", *, stage=rs.COMPLETED, code="OK", force_add=()):
        """What the Orchestrator leaves behind: an ai-candidate branch on base, and a completed run.json."""
        branch = f"ai-candidate/{run_id}-x"
        git(self.repo, "switch", "-q", "-c", branch, self.base)
        (self.repo / "marker.txt").write_text(text + "\n", encoding="utf-8")
        for name in force_add:
            (self.repo / name).write_text("tracked by the candidate", encoding="utf-8")
            git(self.repo, "add", "-f", name)
        git(self.repo, "commit", "-qam", f"AI candidate: {text}")
        sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")
        record = rs.new_record(run_id=run_id, repo=str(self.repo), task="t", main_agent="claude", review_agent="codex",
                               tests=["python -m pytest -q"], limits=rs.Limits(), branch="main", base_sha=self.base)
        record.update(stage=stage, candidate_sha=sha if stage == rs.COMPLETED else "", candidate_branch=branch,
                      final_result={"stage": stage, "code": code, "message": "m"}, finished_at="2026-09-26T16:56:15")
        run_dir = rs.runs_root() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(run_dir / "run.json", record)
        return sha

    def candidate(self):
        return cf.latest_candidate(self.repo)

    def make_venv(self):
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.repo / ".venv")], check=True,
                       capture_output=True)

    def in_process_runner(self, rc=0):
        def runner(target, name, venv_root):
            with mock.patch.dict(os.environ, {"APP_RC": str(rc)}), \
                 mock.patch.object(entrypoints.processes, "forward", lambda text: None):
                try:
                    return entrypoints.run(target, name=name, venv_root=venv_root)
                except subprocess.CalledProcessError as exc:
                    return exc.returncode
        return runner

    def run_dev(self, rc=0):
        with mock.patch("builtins.print"):
            return cf.run_dev(self.repo, "main", self.sha, runner=self.in_process_runner(rc))

    def approve(self):
        return cf.approve(self.candidate(), self.sha)

    def push(self, sha=None):
        with mock.patch("builtins.print"):
            return cf.push(self.repo, "main", sha or self.sha)


class CandidateSourceTests(LifecycleCase):
    def test_completed_run_candidate_is_the_verification_target(self):
        candidate = self.candidate()
        self.assertEqual(candidate.sha, self.sha)
        self.assertEqual(candidate.run_id, "20260926-165346-534560")
        self.assertTrue(candidate.branch.startswith("ai-candidate/"))
        self.assertEqual((candidate.base_sha, candidate.source_branch), (self.base, "main"))
        snap = cf.snapshot(self.repo, "main")
        self.assertTrue(snap["active"] and snap["can_run"])
        self.assertEqual(snap["stages"][0][1], self.sha)

    def test_expected_branch_head_never_replaces_the_candidate(self):
        # main / origin/main are at the base; an open PR or branch HEAD are not candidate sources here
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), self.base)
        snap = cf.snapshot(self.repo, "main")
        self.assertEqual(snap["candidate"].sha, self.sha)
        self.assertNotEqual(snap["candidate"].sha, self.base)
        self.assertIn("base（未push）", snap["stages"][3][2])
        self.assertEqual(dcc_app.candidate_run_label(snap), f"RUN_DEV {self.sha[:8]}")

    def test_only_completed_ok_runs_count_and_the_newest_wins(self):
        self.make_candidate("broken", run_id="20260927-000000-000001", stage=rs.NEEDS_HUMAN, code="TASK_BLOCKED")
        self.assertEqual(self.candidate().sha, self.sha)
        newer = self.make_candidate("newer", run_id="20260927-000000-000002")
        self.assertEqual(self.candidate().sha, newer)

    def test_missing_moved_or_inconsistent_candidate_stops(self):
        candidate = self.candidate()
        git(self.repo, "branch", "-f", candidate.branch, self.base)
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.verify(candidate)
        self.assertEqual(ctx.exception.code, "CANDIDATE_BRANCH_MOVED")
        snap = cf.snapshot(self.repo, "main")
        self.assertTrue(snap["active"] and snap["error"])  # still gates BUILD / RUN: a safe stop
        gone = cf.Candidate(**{**candidate.__dict__, "sha": "f" * 40, "branch": ""})
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.verify(gone)
        self.assertEqual(ctx.exception.code, "CANDIDATE_MISSING")


class RunDevTests(LifecycleCase):
    def test_run_dev_runs_the_candidate_worktree_with_the_repo_venv_and_records_the_sha(self):
        self.make_venv()
        source_status = git(self.repo, "status", "--porcelain", "--ignored")
        source_head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.run_dev(), 0)
        probe = json.loads((self.tmp / "probe.json").read_text(encoding="utf-8"))
        target = cf.run_worktree_path(self.candidate())
        self.assertEqual(Path(probe["cwd"]).resolve(), target.resolve())                          # cwd = candidate worktree
        self.assertTrue(Path(probe["file"]).resolve().is_relative_to(target.resolve()))          # its code runs
        self.assertEqual(probe["marker"], "candidate")                                          # not base / main
        self.assertTrue(Path(probe["exe"]).resolve().is_relative_to((self.repo / ".venv").resolve()))  # repo venv
        self.assertEqual(git(target, "rev-parse", "HEAD"), self.sha)
        run = cf.last_run(cf.load_state(self.candidate()))
        self.assertEqual((run["sha"], run["result"], run["returncode"]), (self.sha, "PASS", 0))
        self.assertEqual((run["head_before"], run["head_after"]), (self.sha, self.sha))
        self.assertEqual(Path(run["target"]).resolve(), target.resolve())
        self.assertTrue(run["entrypoint"].endswith("app.py") and "python" in run["command"])
        # the source repo is untouched: same branch, HEAD and status; the candidate is not checked out there
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), source_head)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(git(self.repo, "status", "--porcelain", "--ignored"), source_status)
        self.assertFalse((target / ".venv").exists())

    def test_missing_entrypoint_stops_before_start_and_records_nothing(self):
        self.make_venv()
        with mock.patch.object(entrypoints, "run_specs", return_value={"demoapp": {"entry": "missing_app.py"}}):
            with self.assertRaises(cf.CandidateError) as ctx:
                self.run_dev()
        self.assertEqual(ctx.exception.code, "RUN_ENTRYPOINT_MISSING")
        self.assertFalse((self.tmp / "probe.json").exists())
        self.assertEqual(cf.load_state(self.candidate())["run_dev"], [])

    def test_missing_source_venv_stops_without_installing(self):
        with self.assertRaises(ValueError):
            entrypoints.run(self.repo, name="demoapp", venv_root=self.repo)
        self.assertFalse((self.repo / ".venv").exists())

    def test_candidate_changed_after_confirmation_stops(self):
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.run_dev(self.repo, "main", self.base, runner=self.in_process_runner())
        self.assertEqual(ctx.exception.code, "CANDIDATE_CHANGED")


class ApprovalTests(LifecycleCase):
    def test_approval_requires_a_passed_run_of_the_same_sha(self):
        self.make_venv()
        with self.assertRaises(cf.CandidateError) as ctx:
            self.approve()
        self.assertEqual(ctx.exception.code, "RUN_DEV_REQUIRED")
        self.assertNotEqual(self.run_dev(rc=3), 0)
        with self.assertRaises(cf.CandidateError) as ctx:
            self.approve()
        self.assertEqual(ctx.exception.code, "RUN_DEV_NOT_PASSED")
        self.assertFalse(cf.snapshot(self.repo, "main")["can_approve"])
        self.assertEqual(self.run_dev(), 0)
        self.assertTrue(cf.snapshot(self.repo, "main")["can_approve"])
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.approve(self.candidate(), self.base)
        self.assertEqual(ctx.exception.code, "APPROVAL_SHA_MISMATCH")
        state = self.approve()
        self.assertEqual(state["approval"]["sha"], self.sha)
        self.assertTrue(cf.approval_valid(self.candidate(), state))

    def test_rerun_or_a_new_candidate_invalidates_the_approval(self):
        self.make_venv()
        self.run_dev()
        self.approve()
        self.run_dev()  # approve what you last ran
        self.assertFalse(cf.approval_valid(self.candidate(), cf.load_state(self.candidate())))
        self.approve()
        newer = self.make_candidate("newer", run_id="20260927-000000-000002")
        candidate = self.candidate()
        self.assertEqual(candidate.sha, newer)
        state = cf.load_state(candidate)
        self.assertEqual((state["run_dev"], state["approval"]), ([], None))
        self.assertFalse(cf.snapshot(self.repo, "main")["can_push"])


class PushTests(LifecycleCase):
    def approved(self):
        self.make_venv()
        self.run_dev()
        self.approve()

    def test_push_requires_approval(self):
        self.make_venv()
        self.run_dev()
        with self.assertRaises(cf.CandidateError) as ctx:
            self.push()
        self.assertEqual(ctx.exception.code, "NOT_APPROVED")
        self.assertEqual(cf.remote_head(self.repo, "main"), self.base)

    def test_only_the_approved_sha_can_be_pushed(self):
        self.approved()
        with self.assertRaises(cf.CandidateError) as ctx:
            self.push(sha=self.base)
        self.assertEqual(ctx.exception.code, "CANDIDATE_CHANGED")
        self.assertEqual(cf.remote_head(self.repo, "main"), self.base)

    def test_base_moved_stops_without_merge_rebase_or_reset(self):
        self.approved()
        other = self.tmp / "other"
        subprocess.run(["git", "clone", str(self.origin), str(other)], check=True, capture_output=True)
        self.configure(other)
        (other / "other.txt").write_text("x", encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-m", "normal development")
        git(other, "push", "origin", "main")
        moved = git(other, "rev-parse", "HEAD")
        with self.assertRaises(cf.CandidateError) as ctx:
            self.push()
        self.assertEqual(ctx.exception.code, "BASE_MOVED")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.base)         # local main untouched
        self.assertEqual(cf.remote_head(self.repo, "main"), moved)               # origin untouched
        self.assertTrue(cf.snapshot(self.repo, "main")["stale"])

    def test_fast_forward_push_keeps_the_exact_sha_and_verifies_origin(self):
        self.approved()
        state = self.push()
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.sha)           # no new commit / rebase / cherry-pick
        self.assertEqual(git(self.repo, "rev-parse", "HEAD^"), self.base)
        self.assertEqual(git(self.repo, "rev-list", "--merges", "HEAD"), "")
        self.assertEqual(cf.remote_head(self.repo, "main"), self.sha)
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), self.sha)
        self.assertEqual(state["push"]["sha"], self.sha)
        snap = cf.snapshot(self.repo, "main")
        self.assertTrue(snap["pushed"] and snap["active"])
        self.assertIn("push済み", snap["stages"][3][2])

    def test_dirty_or_wrong_branch_source_stops_before_touching_it(self):
        self.approved()
        (self.repo / "marker.txt").write_text("local edit\n", encoding="utf-8")
        with self.assertRaises(cf.CandidateError) as ctx:
            self.push()
        self.assertEqual(ctx.exception.code, "SOURCE_DIRTY")
        git(self.repo, "checkout", "--", "marker.txt")
        git(self.repo, "switch", "-q", "-c", "feature")
        with self.assertRaises(cf.CandidateError) as ctx:
            self.push()
        self.assertEqual(ctx.exception.code, "WRONG_BRANCH")
        self.assertEqual(cf.remote_head(self.repo, "main"), self.base)


class BuildAndReleaseGateTests(LifecycleCase):
    def pushed(self):
        self.make_venv()
        self.run_dev()
        self.approve()
        self.push()

    def test_build_gate_requires_approved_pushed_and_matching_local_and_origin(self):
        self.make_venv()
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.build_gate(self.repo, "main")
        self.assertEqual(ctx.exception.code, "NOT_APPROVED")
        self.run_dev()
        self.approve()
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.build_gate(self.repo, "main")
        self.assertEqual(ctx.exception.code, "NOT_PUSHED")
        self.push()
        self.assertEqual(cf.build_gate(self.repo, "main").sha, self.sha)
        (self.repo / "late.txt").write_text("x", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "local commit after push")
        with self.assertRaises(cf.CandidateError) as ctx:
            cf.build_gate(self.repo, "main")
        self.assertEqual(ctx.exception.code, "SHA_MISMATCH")

    def test_build_worker_refuses_a_head_other_than_the_expected_sha(self):
        self.pushed()
        with self.assertRaises(ValueError):
            provenance._require_head(self.repo, self.base)
        provenance._require_head(self.repo, self.sha)
        (self.repo / "marker.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            provenance._require_head(self.repo, self.sha)

    def test_no_candidate_keeps_the_working_tree_route(self):
        cf.discard(self.candidate())
        self.assertIsNone(cf.build_gate(self.repo, "main"))
        self.assertIsNone(cf.release_expectation(self.repo, "main"))
        self.assertFalse(cf.snapshot(self.repo, "main")["active"])

    def test_update_refuses_an_artifact_of_another_sha(self):
        self.pushed()
        good = {"candidate_sha": self.sha, "base_head": self.sha, "dirty": False}
        provenance._require_candidate_artifact(self.repo, good, self.sha, "main")
        for bad in ({**good, "base_head": self.base}, {**good, "candidate_sha": None}, {**good, "dirty": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                provenance._require_candidate_artifact(self.repo, bad, self.sha, "main")
        self.assertEqual(cf.release_expectation(self.repo, "main").sha, self.sha)

    def test_flow_shows_every_stage_with_its_sha_and_ends_after_deploy(self):
        self.pushed()
        root = provenance.receipt_path(self.repo)
        provenance.write_json(root, {"repo": str(self.repo.resolve()), "status": "ready", "build_id": "b1",
                                     "base_head": self.sha, "candidate_sha": self.sha,
                                     "candidate_run_id": self.candidate().run_id, "dirty": False})
        provenance.write_json(provenance.release_record_path(self.repo),
                              {"build_id": "b1", "candidate_sha": self.sha, "returncode": 0})
        snap = cf.snapshot(self.repo, "main")
        text = dcc_app.flow_text(snap)
        for name in ("Orchestrator candidate", "RUN_DEV", "Human approval", "origin/main", "BUILD", "UPDATE / DEPLOY"):
            self.assertIn(name, text)
        self.assertEqual(text.count(self.sha[:12]), 7)  # 6 stages + the production line
        self.assertIn("SUCCESS", text)
        self.assertTrue(snap["deployed"])
        self.assertFalse(snap["active"])  # the lifecycle is complete: back to the normal route

    def test_verified_rollback_records_the_real_deployment_and_ends_the_candidate(self):
        from scripts.dev_control_center import restore_release

        self.pushed()
        provenance.write_json(provenance.release_record_path(self.repo),
                              {"build_id": "b1", "candidate_sha": self.sha, "returncode": 0})
        body = {"target": "T", "backup": "B", "restore_commit": self.base, "restore_version": "v1.4.0",
                "plan_id": "p" * 64, "current_build_info": {"Git commit SHA": self.sha}}
        with mock.patch("builtins.print"):
            restore_release.record_rollback(self.repo, body, {"exe_sha256": "E" * 64, "saved": "S"})
        record = json.loads(provenance.release_record_path(self.repo).read_text(encoding="utf-8"))
        self.assertEqual((record["kind"], record["deployed_commit"], record["rolled_back_from"]),
                         ("rollback", self.base, self.sha))
        self.assertTrue(list(provenance.release_record_path(self.repo).parent.glob("release-superseded-*.json")))
        snap = cf.snapshot(self.repo, "main")
        self.assertFalse(snap["active"])
        self.assertIn("rollback済み", dcc_app.flow_text(snap))
        self.assertIsNone(cf.build_gate(self.repo, "main"))

    def rolled_back(self):
        from scripts.dev_control_center import restore_release

        self.pushed()
        provenance.write_json(provenance.receipt_path(self.repo), {
            "repo": str(self.repo.resolve()), "status": "ready", "build_id": "b1", "base_head": self.sha,
            "candidate_sha": self.sha, "candidate_run_id": self.candidate().run_id, "dirty": False})
        provenance.write_json(provenance.release_record_path(self.repo),
                              {"build_id": "b1", "candidate_sha": self.sha, "returncode": 0})
        body = {"target": "T", "backup": "B", "restore_commit": self.base, "restore_version": "v1.4.0",
                "plan_id": "p" * 64, "current_build_info": {"Git commit SHA": self.sha}}
        with mock.patch("builtins.print"):
            restore_release.record_rollback(self.repo, body, {"exe_sha256": "E" * 64, "saved": "S"})

    def test_production_differs_from_main_and_is_shown_as_such(self):
        self.rolled_back()
        self.assertEqual(git(self.repo, "rev-parse", "origin/main"), self.sha)      # main = the rolled-back SHA
        snap = cf.snapshot(self.repo, "main")
        self.assertEqual(snap["production"]["commit"], self.base)                   # production = restored build
        text = dcc_app.flow_text(snap)
        self.assertIn(f"production (DCC記録)", text)
        self.assertIn(self.base[:12], text.splitlines()[0])
        self.assertIn("配布後に本番からrollback済み", text)                         # never "未実施" (undeployed)
        self.assertNotIn("未実施", [line for line in text.splitlines() if line.startswith("UPDATE")][0])

    def test_rolled_back_candidate_never_comes_back(self):
        self.rolled_back()
        candidate = self.candidate()
        for _ in range(3):  # reloads, DCC restarts: the state is durable
            snap = cf.snapshot(self.repo, "main")
            self.assertFalse(snap["active"] or snap["can_run"] or snap["can_approve"] or snap["can_push"])
        self.assertEqual(dcc_app.candidate_run_label(snap), "RUN")
        self.assertIsNone(cf.build_gate(self.repo, "main"))
        self.assertIsNone(cf.release_expectation(self.repo, "main"))
        for action in (lambda: cf.approve(candidate, self.sha),
                       lambda: cf.run_dev(self.repo, "main", self.sha, runner=self.in_process_runner()),
                       lambda: cf.push(self.repo, "main", self.sha)):
            with self.assertRaises(cf.CandidateError) as ctx, mock.patch("builtins.print"):
                action()
            self.assertEqual(ctx.exception.code, "CANDIDATE_ROLLED_BACK")
        self.assertTrue(cf.load_state(candidate)["rolled_back"])

    def test_the_rolled_back_build_can_not_be_released_again(self):
        self.rolled_back()
        with self.assertRaises(ValueError) as ctx:
            provenance.read_receipt(self.repo)
        self.assertIn("rollback済み", str(ctx.exception))

    def test_a_new_candidate_after_the_rollback_starts_fresh(self):
        self.rolled_back()
        newer = self.make_candidate("v1.4.1 integration", run_id="20260929-000000-000001")
        snap = cf.snapshot(self.repo, "main")
        self.assertEqual(snap["candidate"].sha, newer)
        self.assertIsNone(snap["state"]["rolled_back"])
        self.assertEqual(snap["production"]["commit"], self.base)

    def test_a_sha_change_on_the_way_is_shown_and_stops(self):
        self.pushed()
        provenance.write_json(provenance.receipt_path(self.repo), {
            "status": "ready", "build_id": "b2", "base_head": self.base, "candidate_sha": self.sha,
            "candidate_run_id": self.candidate().run_id})
        snap = cf.snapshot(self.repo, "main")
        self.assertIn("BUILD", snap["mismatch"])
        self.assertFalse(snap["can_run"])
        self.assertIn("SHA不一致で停止", dcc_app.flow_text(snap))


class SeedTests(LifecycleCase):
    """next-day-setup keeps git-ignored runtime data next to its code: RUN_DEV gets a one-way copy."""

    IGNORE = ".venv/\nlocal.json\ndata/\nnotes.txt\nabsent.json\n"
    SEED = ["local.json", "data", "absent.json"]

    def setUp(self):
        super().setUp()
        (self.repo / "local.json").write_text('{"printer": "real"}', encoding="utf-8")
        (self.repo / "data" / "sub").mkdir(parents=True)
        (self.repo / "data" / "state.txt").write_text("source\n", encoding="utf-8")
        (self.repo / "data" / "sub" / "saved.sqlite3").write_bytes(b"\x00db")
        self.make_venv()

    def spec(self, seed):
        return mock.patch.object(entrypoints, "run_specs", return_value={"demoapp": {**SPEC["demoapp"], "seed": seed}})

    def source_bytes(self):
        return {p.relative_to(self.repo).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in [self.repo / "local.json", *(self.repo / "data").rglob("*")] if p.is_file()}

    def test_runtime_data_is_copied_into_the_candidate_and_never_back(self):
        before = self.source_bytes()
        with self.spec(self.SEED):
            self.assertEqual(self.run_dev(), 0)
        probe = json.loads((self.tmp / "probe.json").read_text(encoding="utf-8"))
        self.assertEqual(probe["setting"], '{"printer": "real"}')                  # the app saw the seeded settings
        target = cf.run_worktree_path(self.candidate())
        self.assertEqual((target / "data" / "state.txt").read_text(encoding="utf-8"), "source\nrun\n")  # it wrote the copy
        self.assertEqual((target / "data" / "sub" / "saved.sqlite3").read_bytes(), b"\x00db")
        self.assertEqual(self.source_bytes(), before)                                # source: same bytes and mtimes
        run = cf.last_run(cf.load_state(self.candidate()))
        self.assertEqual({i["path"]: i["status"] for i in run["seeded"]},
                         {"local.json": "copied", "data": "copied", "absent.json": "missing"})
        self.assertEqual(run["source_seed_changed"], [])
        self.assertEqual(git(target, "status", "--porcelain"), "")                  # copies stay ignored in the candidate

    def test_every_run_dev_refreshes_the_copy_from_the_source(self):
        with self.spec(self.SEED):
            self.run_dev()
            target = cf.run_worktree_path(self.candidate())
            (target / "data" / "stale.txt").write_text("left by the previous RUN", encoding="utf-8")
            self.run_dev()
        self.assertFalse((target / "data" / "stale.txt").exists())
        self.assertEqual((target / "data" / "state.txt").read_text(encoding="utf-8"), "source\nrun\n")
        self.assertEqual((self.repo / "data" / "state.txt").read_text(encoding="utf-8"), "source\n")

    def test_unignored_or_escaping_paths_stop_before_start(self):
        cases = {"marker.txt": "SEED_NOT_IGNORED",       # tracked code: would overwrite the candidate
                 "app.py": "SEED_NOT_IGNORED",
                 "../outside.json": "SEED_INVALID",
                 str(self.tmp / "abs.json"): "SEED_INVALID"}
        for seed, code in cases.items():
            with self.subTest(seed=seed), self.spec([seed]), self.assertRaises(cf.CandidateError) as ctx:
                self.run_dev()
            self.assertEqual(ctx.exception.code, code)
        self.assertFalse((self.tmp / "probe.json").exists())
        self.assertEqual(cf.load_state(self.candidate())["run_dev"], [])

    def test_a_path_the_candidate_tracks_is_never_overwritten(self):
        # ignored in the source, but the candidate commit tracks it (force-added)
        self.sha = self.make_candidate("tracks notes", run_id="20260927-000000-000003", force_add=("notes.txt",))
        (self.repo / "notes.txt").write_text("source copy", encoding="utf-8")
        with self.spec(["notes.txt"]), self.assertRaises(cf.CandidateError) as ctx:
            self.run_dev()
        self.assertEqual(ctx.exception.code, "SEED_TRACKED")
        target = cf.run_worktree_path(self.candidate())
        self.assertEqual((target / "notes.txt").read_text(encoding="utf-8"), "tracked by the candidate")
        self.assertFalse((self.tmp / "probe.json").exists())

    def test_links_inside_seed_data_are_refused(self):
        link = self.repo / "data" / "link"
        try:
            if os.name == "nt":  # a junction needs no privilege; it is the usual link on Windows
                import _winapi

                _winapi.CreateJunction(str(self.tmp), str(link))
                self.addCleanup(os.rmdir, link)  # remove the junction itself, never its target
            else:
                os.symlink(self.tmp, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create a link here: {exc}")
        with self.spec(["data"]), self.assertRaises(cf.CandidateError) as ctx:
            self.run_dev()
        self.assertEqual(ctx.exception.code, "SEED_LINK")

    def test_normal_run_of_the_source_is_not_seeded(self):
        # seeding belongs to candidate RUN_DEV only; the working-tree RUN already uses the source data in place
        self.assertNotIn("seed", entrypoints.RunPlan.__dataclass_fields__)


class RegisteredRunTests(unittest.TestCase):
    def test_next_day_setup_runs_hotel_app_entry_from_its_venv(self):
        # v1.4.1+: the production entry (breakfast forfeit) that RUN_DEV.cmd and build_exe.py also use
        spec = entrypoints.run_specs()["next-day-setup"]
        self.assertEqual((spec["cwd"], spec["entry"]), (".", "dinner_system/hotel_app_entry.py"))
        source = Path(__file__).resolve().parents[2] / "next-day-setup"
        if not (source / "dinner_system" / "hotel_app_entry.py").is_file():
            self.skipTest("next-day-setup checkout with hotel_app_entry.py not present")
        plan = entrypoints.plan_run(source)
        self.assertEqual(plan.args, ["dinner_system/hotel_app_entry.py"])
        self.assertEqual(plan.python, source / "." / ".venv" / "Scripts" / "python.exe")

    def test_next_day_setup_seeds_only_ignored_runtime_data(self):
        seed = entrypoints.run_specs()["next-day-setup"]["seed"]
        self.assertIn("dinner_system/master_settings.json", seed)
        self.assertIn("dinner_system/\u4fdd\u5b58\u30c7\u30fc\u30bf", seed)
        for generated in ("print_work", "outputs", ".log", "shared_folder_path"):
            self.assertFalse(any(generated in item for item in seed), generated)
        source = Path(__file__).resolve().parents[2] / "next-day-setup"
        if not (source / ".git").exists():
            self.skipTest("next-day-setup checkout not present")
        for item in seed:
            with self.subTest(item=item):
                self.assertEqual(subprocess.run(["git", "-C", str(source), "check-ignore", "-q", "--", item]).returncode, 0)
                self.assertEqual(git(source, "ls-files", "--", item), "")

    def test_every_registered_python_run_names_its_entry(self):
        for name, spec in entrypoints.run_specs().items():
            with self.subTest(name=name):
                self.assertTrue(spec.get("entry") or spec.get("module"))
                self.assertNotIn("build_exe_entry", str(spec))  # the old branch-only shim is not used


if __name__ == "__main__":
    unittest.main()
