"""State-machine acceptance tests: providers mocked, no paid AI calls."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.ai_orchestrator import orchestrator as o
from scripts.dev_control_center import app as dcc


def response(text="implemented", error=False):
    return o.CommandResult(("claude",), int(error), json.dumps({
        "result": text, "is_error": error, "subtype": "error" if error else "success",
    }), "")


class SafetyStop(BaseException):
    pass


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worktree = self.root / "isolated"
        self.worktree.mkdir()
        self.baseline = o.RepoBaseline(self.root / "source", "main", "a" * 40, "a" * 40)
        self.diff = ""
        self.events = []
        self.stages = []
        self.run_dir = self.root / "state/runs/recovery-test"

    def pipeline(self, implementations=None, tests=None, verdicts=None, limit=3,
                 stop_stage=None, safety_error=False, diagnosis_mutates=False,
                 resume=False, real_gate=False, decision=None):
        implementations = iter(implementations or [(response(), "initial diff")])
        tests = iter(tests or [(True, "PASS")])
        verdicts = iter(verdicts or ["PASS"])
        args = o.build_parser().parse_args([
            "run", "--repo", str(self.baseline.root), "--task", "TaskSpec",
            "--test", "independent tests", "--max-rounds", str(limit), "--no-fetch",
            "--result-file", str(self.root / "external.json"),
        ])
        if resume:
            args.resume_review = str(self.run_dir)
        if decision:
            args.final_review_decision = str(decision)

        def implementation(*args):
            self.events.append("implementation")
            output, self.diff = next(implementations)
            if safety_error:
                raise o.OrchestratorError("provider broke safety boundary")
            return output

        def diagnose(*args):
            self.events.append("diagnosis")
            if diagnosis_mutates:
                self.diff += " unauthorized mutation"
            return response("Evidence: wrong boundary. Repair the comparison.")

        def verification(*args):
            self.events.append("verification")
            return next(tests)

        def gate(*args):
            self.events.append("gate")
            return {"verdict": next(verdicts), "summary": "Independent findings"}

        original_progress = o._progress

        def progress(*args, **kwargs):
            original_progress(*args, **kwargs)
            self.stages.append(kwargs["stage"])
            if kwargs["stage"] == stop_stage and kwargs["round_no"] > 0:
                raise SafetyStop()

        self.candidate = mock.Mock(return_value=("ai-candidate/test", "b" * 40))
        patches = {
            "_resolved_command": mock.Mock(side_effect=lambda name: [name]),
            "_enforce_billing_guard": mock.Mock(return_value=()),
            "_repo_baseline": mock.Mock(return_value=self.baseline),
            "_create_worktree": mock.Mock(return_value=(self.root / "parent", self.worktree)),
            "_state_root": mock.Mock(return_value=self.root / "state"),
            "_now_id": mock.Mock(return_value="recovery-test"),
            "_diff_for_review": mock.Mock(side_effect=lambda _: ("stat", self.diff)),
            "_run_claude_implementation": mock.Mock(side_effect=implementation),
            "_run_claude_diagnosis": mock.Mock(side_effect=diagnose),
            "_run_codex_review": mock.Mock(side_effect=AssertionError("Astra must not run")),
            "_assert_agent_did_not_commit": mock.Mock(),
            "_assert_source_unchanged": mock.Mock(),
            "_create_candidate": self.candidate,
            "_run_tests": mock.Mock(side_effect=verification),
            "_progress": mock.Mock(side_effect=progress),
            "_git": mock.Mock(),
        }
        if not real_gate:
            patches["_final_review_gate"] = mock.Mock(side_effect=gate)
        with ExitStack() as stack:
            for name, replacement in patches.items():
                stack.enter_context(mock.patch.object(o, name, replacement))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            try:
                code = o.run(args)
            except SafetyStop:
                # DCC owns durable STOPPED after its process-tree termination.
                dcc._mark_ai_run_stopped(self.run_dir)
                code = -1
        self.result = json.loads((self.run_dir / "result.json").read_text(encoding="utf-8"))
        return code

    def test_one_shot_success_has_zero_recovery_and_no_astra(self):
        self.assertEqual(self.pipeline(limit=0), 0)
        self.assertEqual(self.events, ["implementation", "verification", "gate"])
        self.assertEqual(self.result["recovery_iterations"], 0)
        self.assertEqual(self.result["claude_calls"], 1)
        self.assertEqual(self.result["codex_calls"], 0)
        self.candidate.assert_called_once()

    def test_tests_failure_repairs_and_returns_to_gate(self):
        self.assertEqual(self.pipeline(
            implementations=[(response(), "bad diff"), (response(), "fixed diff")],
            tests=[(False, "assert x"), (True, "PASS")]), 0)
        self.assertEqual(self.events, ["implementation", "verification", "diagnosis",
                                      "implementation", "verification", "gate"])
        entry = self.result["recovery_history"][0]
        self.assertEqual(entry["failure"]["kind"], "TESTS_FAIL")
        self.assertTrue(entry["diagnosis"])
        self.assertTrue(entry["repair"]["changed"])
        self.assertTrue(entry["progress"])
        self.assertEqual(entry["verification"]["kind"], "PASS")

    def test_hang_recovers(self):
        self.pipeline(implementations=[(response(), "bad"), (response(), "good")],
                      tests=[(False, "HANG/TIMEOUT"), (True, "PASS")])
        self.assertEqual(self.result["recovery_history"][0]["failure"]["kind"], "TESTS_HANG")
        self.assertEqual(self.result["status"], "candidate_ready")

    def test_implementation_error_recovers_before_tests(self):
        self.pipeline(implementations=[(response("implementation failed", True), "partial"),
                                       (response(), "fixed")])
        self.assertEqual(self.events, ["implementation", "diagnosis", "implementation", "verification", "gate"])
        self.assertEqual(self.result["status"], "candidate_ready")

    def test_explicit_blocked_recovers(self):
        self.pipeline(implementations=[(response("IMPLEMENTATION_STATUS: BLOCKED"), "partial"),
                                       (response(), "fixed")])
        self.assertEqual(self.result["recovery_history"][0]["failure"]["kind"], "IMPLEMENTATION_BLOCKED")
        self.assertEqual(self.result["status"], "candidate_ready")

    def test_explicit_review_failure_recovers(self):
        self.pipeline(implementations=[(response(), "bad"), (response(), "good")],
                      tests=[(True, "PASS"), (True, "PASS")], verdicts=["FAIL", "PASS"])
        self.assertEqual(self.result["recovery_history"][0]["failure"]["kind"], "FINAL_REVIEW_FAIL")
        self.assertEqual(self.result["status"], "candidate_ready")

    def test_limit_exhaustion_never_creates_candidate(self):
        self.assertEqual(self.pipeline(limit=1,
            implementations=[(response(), "bad"), (response(), "different")],
            tests=[(False, "failure 1"), (False, "failure 2")]), 1)
        self.assertEqual(self.result["error_code"], "RECOVERY_LIMIT")
        self.assertEqual(self.result["recovery_iterations"], 1)
        self.candidate.assert_not_called()

    def test_same_failure_and_same_repair_stop_early_despite_timing_noise(self):
        self.pipeline(implementations=[(response(), "bad"), (response(), "bad")],
                      tests=[(False, "assert x in 0.1s"), (False, "assert x in 0.2s")])
        self.assertEqual(self.result["error_code"], "RECOVERY_NO_PROGRESS")
        self.assertFalse(self.result["recovery_history"][0]["progress"])
        self.candidate.assert_not_called()

    def test_cycle_of_previously_failed_repairs_stops(self):
        self.pipeline(limit=4, implementations=[(response(), x) for x in ["A", "B", "C", "B"]],
                      tests=[(False, "assert x")] * 4)
        self.assertEqual(self.result["error_code"], "RECOVERY_NO_PROGRESS")
        self.assertEqual(self.result["recovery_iterations"], 3)

    def test_unconnected_review_is_pending_without_extra_ai(self):
        self.assertEqual(self.pipeline(real_gate=True), 0)
        self.assertEqual(self.result["status"], "review_pending")
        self.assertEqual(self.result["recovery_iterations"], 0)
        self.assertEqual(self.events, ["implementation", "verification"])
        self.candidate.assert_not_called()
        self.assertTrue(self.worktree.is_dir())

    def test_pending_review_can_resume_with_bound_external_pass(self):
        self.pipeline(real_gate=True)
        request = json.loads((self.run_dir / "final-review-request.json").read_text(encoding="utf-8"))
        decision = self.root / "decision.json"
        decision.write_text(json.dumps({"request_id": request["request_id"], "verdict": "PASS",
                                        "summary": "TaskSpec checked independently"}), encoding="utf-8")
        self.events.clear()
        self.assertEqual(self.pipeline(resume=True, real_gate=True, decision=decision), 0)
        self.assertEqual(self.result["status"], "candidate_ready")
        self.assertEqual(self.events, [])
        self.assertEqual(self.result["claude_calls"], 1)

    def _pending_request_id(self):
        self.pipeline(real_gate=True)
        request = json.loads((self.run_dir / "final-review-request.json").read_text(encoding="utf-8"))
        return request["request_id"]

    def _bad_decisions(self, request_id):
        bad = self.root / "bad-decision.json"
        unreadable = self.root / "missing-decision.json"
        cases = {
            "wrong request_id": {"request_id": "0" * 64, "verdict": "PASS", "summary": "ok"},
            "invalid verdict": {"request_id": request_id, "verdict": "APPROVED", "summary": "ok"},
            "empty summary": {"request_id": request_id, "verdict": "PASS", "summary": " "},
            "not an object": ["PASS"],
        }
        for label, payload in cases.items():
            bad.write_text(json.dumps(payload), encoding="utf-8")
            yield label, bad
        bad.write_text("{not json", encoding="utf-8")
        yield "unparseable file", bad
        yield "unreadable file", unreadable

    def test_bad_decision_file_keeps_review_pending_and_is_resumable(self):
        request_id = self._pending_request_id()
        for label, path in self._bad_decisions(request_id):
            with self.subTest(case=label):
                self.events.clear()
                self.assertEqual(self.pipeline(resume=True, real_gate=True, decision=path), 0)
                self.assertEqual(self.result["status"], "review_pending")
                self.assertNotIn("error_code", self.result)
                error = self.result["final_review_error"]
                self.assertTrue(error["resumable"])
                self.assertEqual(error["code"], "FINAL_REVIEW_DECISION_INVALID")
                self.assertEqual(error["request_id"], request_id)
                self.assertIn(request_id, error["detail"])
                self.assertIn("--resume-review", error["detail"])
                status = json.loads((self.run_dir / "status.json").read_text(encoding="utf-8"))
                self.assertEqual(status["stage"], "final_review_pending")
                self.assertIn(request_id, status["detail"])
                self.assertEqual(self.events, [])
                self.candidate.assert_not_called()
                self.assertTrue(self.worktree.is_dir())

    def test_correct_decision_after_repeated_bad_attempts_reaches_candidate(self):
        request_id = self._pending_request_id()
        for _label, path in self._bad_decisions(request_id):
            self.assertEqual(self.pipeline(resume=True, real_gate=True, decision=path), 0)
            self.assertEqual(self.result["status"], "review_pending")
        good = self.root / "decision.json"
        good.write_text(json.dumps({"request_id": request_id, "verdict": "PASS",
                                    "summary": "TaskSpec checked independently"}), encoding="utf-8")
        self.events.clear()
        self.assertEqual(self.pipeline(resume=True, real_gate=True, decision=good), 0)
        self.assertEqual(self.result["status"], "candidate_ready")
        self.assertEqual(self.events, [])
        self.assertEqual(self.result["claude_calls"], 1)
        self.candidate.assert_called_once()

    def test_changed_pending_worktree_cannot_reuse_approval(self):
        self.pipeline(real_gate=True)
        self.diff = "changed after review request"
        with self.assertRaisesRegex(o.OrchestratorError, "worktree changed"):
            self.pipeline(resume=True, real_gate=True)
        self.candidate.assert_not_called()

    def test_diagnosis_is_enforced_readonly(self):
        self.pipeline(tests=[(False, "failure")], diagnosis_mutates=True)
        self.assertIn("read-only stage", self.result["error"])
        self.candidate.assert_not_called()

    def test_safety_stop_persists_at_every_recovery_stage(self):
        for stage in ("recovery_diagnosis", "claude_recovery_repair", "tests", "final_review_gate"):
            with self.subTest(stage=stage):
                self.diff = ""
                self.assertEqual(self.pipeline(stop_stage=stage,
                    implementations=[(response(), "bad"), (response(), "good")],
                    tests=[(False, "failure"), (True, "PASS")]), -1)
                status = json.loads((self.run_dir / "status.json").read_text(encoding="utf-8"))
                self.assertEqual(status["stage"], stage)
                self.assertEqual(status["round"], 1)
                self.assertEqual(status["status"], "stopped")
                self.assertEqual(self.result["error_code"], "USER_SAFETY_STOP")
                self.assertEqual(self.result["run_id"], "recovery-test")
                self.assertEqual(self.result["worktree"], str(self.worktree))
                self.assertEqual(self.result["base_sha"], "a" * 40)
                self.assertTrue(self.result["recovery_history"])
                self.candidate.assert_not_called()
                self.assertTrue(self.worktree.is_dir())


class ReviewGateTests(unittest.TestCase):
    def test_unbound_or_unknown_verdicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "decision.json"
            for decision in ({"verdict": "PASS", "summary": "ok"},
                             {"request_id": "id", "verdict": "APPROVED", "summary": "ok"},
                             {"request_id": "id", "verdict": "PASS", "summary": ""}):
                with self.subTest(decision=decision):
                    path.write_text(json.dumps(decision), encoding="utf-8")
                    with self.assertRaises(o.OrchestratorError):
                        o._final_review_gate({"request_id": "id"}, str(path))

    @mock.patch.object(o, "_resolved_command", return_value=["claude"])
    @mock.patch.object(o, "_run", return_value=response("diagnosis"))
    def test_diagnosis_has_no_shell_edit_or_agent_tools(self, run, resolve):
        o._run_claude_diagnosis(Path("isolated"), "prompt", 10)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--tools") + 1], "Read,Glob,Grep")
        self.assertNotIn("--resume", command)

    def test_provider_timeout_terminates_process_tree_before_returning(self):
        proc = mock.Mock()
        proc.communicate.side_effect = [subprocess.TimeoutExpired("claude", 1), ("", "")]
        with mock.patch.object(o.subprocess, "Popen", return_value=proc), \
                mock.patch.object(o, "_terminate_process_tree") as terminate:
            with self.assertRaisesRegex(o.OrchestratorError, "timed out"):
                o._run(["claude"], timeout=1)
        terminate.assert_called_once_with(proc)
        self.assertEqual(proc.communicate.call_count, 2)

    def test_dcc_pending_result_never_applies_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "result.json"
            path.write_text(json.dumps({"status": "review_pending", "run_dir": temp}), encoding="utf-8")
            ui = mock.MagicMock()
            ui.ai_stop_requested = False
            ui.ai_context = {"result_path": path}
            with mock.patch.object(dcc, "apply_local_candidate") as apply, \
                    mock.patch.object(dcc.messagebox, "showerror") as error:
                dcc.App._finish_ai_orchestrator(ui, "demo", 0)
            apply.assert_not_called()
            error.assert_not_called()
            ui.selection.provenance.ai_result.assert_not_called()


class RealGitRecoveryTests(unittest.TestCase):
    def test_real_verification_recovery_and_candidate_preserve_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"

            def git(*args):
                return subprocess.run(["git", *args], check=True, capture_output=True,
                                      text=True, encoding="utf-8").stdout.strip()

            git("init", "-b", "main", str(source))
            git("-C", str(source), "config", "user.name", "Recovery fixture")
            git("-C", str(source), "config", "user.email", "fixture@example.invalid")
            (source / "value.py").write_text("VALUE = 0\n", encoding="utf-8")
            (source / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
            (source / "check.py").write_text(
                "from pathlib import Path\nassert Path('value.py').read_text().strip() == 'VALUE = 2'\n",
                encoding="utf-8")
            git("-C", str(source), "add", ".")
            git("-C", str(source), "commit", "-m", "fixture baseline")
            base = git("-C", str(source), "rev-parse", "HEAD")
            remote = root / "origin.git"
            git("clone", "--bare", str(source), str(remote))
            git("-C", str(source), "remote", "add", "origin", str(remote))
            values = iter([1, 2])

            def implementation(worktree, *args):
                (worktree / "value.py").write_text(f"VALUE = {next(values)}\n", encoding="utf-8")
                return response()

            # Read source text rather than import, to avoid timestamp/pyc reuse.
            command = [sys.executable, "check.py"]
            test = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
            args = o.build_parser().parse_args([
                "run", "--repo", str(source), "--expected-branch", "main", "--task", "Set VALUE to 2",
                "--test", test, "--max-rounds", "1", "--result-file", str(root / "result.json"),
            ])
            mkdtemp = tempfile.mkdtemp
            with mock.patch.object(o.tempfile, "mkdtemp", side_effect=lambda **kw: mkdtemp(dir=root, **kw)), \
                    mock.patch.object(o, "_run_claude_implementation", side_effect=implementation), \
                    mock.patch.object(o, "_run_claude_diagnosis", return_value=response("VALUE should be 2")), \
                    mock.patch.object(o, "_final_review_gate", return_value={"verdict": "PASS", "summary": "Expected value checked"}), \
                    mock.patch.object(o, "_state_root", return_value=root / "state"), \
                    mock.patch.object(o, "_enforce_billing_guard", return_value=()), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = o.run(args)
                self.assertEqual(code, 0, (root / "result.json").read_text(encoding="utf-8"))
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            sha = result["candidate_sha"]
            self.assertRegex(sha, r"^[0-9a-f]{40}$")
            self.assertEqual(result["recovery_iterations"], 1)
            self.assertEqual(git("-C", str(source), "show", f"{sha}:value.py"), "VALUE = 2")
            self.assertEqual(git("-C", str(source), "rev-parse", "HEAD"), base)
            self.assertEqual(git("-C", str(source), "branch", "--show-current"), "main")
            self.assertEqual(git("-C", str(source), "status", "--porcelain"), "")
            self.assertEqual(git("--git-dir", str(remote), "rev-parse", "main"), base)
            self.assertEqual((source / "value.py").read_text(encoding="utf-8"), "VALUE = 0\n")


if __name__ == "__main__":
    unittest.main()
