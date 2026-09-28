"""Child output decoding (UTF-8 + Windows OEM code page), log tailing, the shareable run report
and the worktree directory name."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from scripts.dev_control_center import processes
from tools.ai_orchestrator import common
from tools.ai_orchestrator import orchestrator as orch
from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import OutputDecoder, decode_output, run_streaming, terminate_pid_tree
from tools.ai_orchestrator.review import RUNNER_UNAVAILABLE, classify_runner_problem

from test_ai_orchestrator_host import HostCase

JA = "エラー: プロセスが見つかりませんでした。"


def legacy_bytes(text: str) -> bytes | None:
    """`text` as a Windows console program would write it to a pipe, or None if not representable."""
    try:
        data = text.encode(common.legacy_output_encoding())
    except (UnicodeEncodeError, LookupError):
        return None
    try:
        data.decode("utf-8")
        return None  # not distinguishable from UTF-8 on this machine
    except UnicodeDecodeError:
        return data


class DecodeOutputTests(unittest.TestCase):
    def test_utf8_is_decoded_as_utf8(self):
        self.assertEqual(decode_output(JA.encode("utf-8")), JA)
        self.assertEqual(decode_output(b"plain ascii\n"), "plain ascii\n")

    def test_windows_console_code_page_is_decoded_not_replaced(self):
        data = legacy_bytes(JA)
        if data is None:
            self.skipTest("the OEM code page here can not express Japanese distinctly from UTF-8")
        self.assertEqual(decode_output(data), JA)

    def test_cp932_bytes_are_readable_with_a_cp932_console(self):
        with mock.patch.object(common, "_LEGACY_ENCODING", "cp932"):
            self.assertEqual(decode_output(JA.encode("cp932")), JA)
            # the exact bytes from the failing run (taskkill): 0x83 0x47 ...
            self.assertTrue(decode_output(b"\x83G\x83\x89\x81[: ").startswith("エラー"))

    def test_undecodable_bytes_never_raise(self):
        with mock.patch.object(common, "_LEGACY_ENCODING", "utf-8"):
            self.assertIn("\ufffd", decode_output(b"\xff\xfe\x83"))

    def test_incremental_decoder_keeps_multibyte_characters_and_newlines_whole(self):
        data = ("一行目\r\n" + JA + "\n末尾").encode("utf-8")
        for step in (1, 2, 3, 5, 7):
            decoder = OutputDecoder()
            out = "".join(decoder.decode(data[i:i + step]) for i in range(0, len(data), step))
            out += decoder.decode(b"", final=True)
            with self.subTest(step=step):
                self.assertEqual(out, "一行目\n" + JA + "\n末尾")
                self.assertNotIn("\ufffd", out)

    def test_incremental_decoder_handles_mixed_encodings_per_line(self):
        with mock.patch.object(common, "_LEGACY_ENCODING", "cp932"):
            decoder = OutputDecoder()
            data = "UTF-8の行\n".encode("utf-8") + (JA + "\r\n").encode("cp932") + b"ok\n"
            out = "".join(decoder.decode(data[i:i + 4]) for i in range(0, len(data), 4))
            out += decoder.decode(b"", final=True)
        self.assertEqual(out, "UTF-8の行\n" + JA + "\nok\n")

    def test_partial_utf8_line_is_released_before_its_newline(self):
        decoder = OutputDecoder()
        self.assertEqual(decoder.decode("続行しますか? ".encode("utf-8")), "続行しますか? ")


class ChildProcessEncodingTests(unittest.TestCase):
    def test_run_streaming_decodes_mixed_utf8_and_console_code_page_lines(self):
        data = legacy_bytes(JA)
        if data is None:
            self.skipTest("the OEM code page here can not express Japanese distinctly from UTF-8")
        code = ("import sys; b = sys.stdout.buffer; b.write('UTF-8: 日本語\\n'.encode('utf-8')); "
                f"b.write({data!r} + b'\\r\\n'); b.flush()")
        lines = []
        result = run_streaming([sys.executable, "-c", code], timeout=60,
                               hooks=common.ProcessHooks(on_line=lambda s, t: lines.append(t)))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"UTF-8: 日本語\n{JA}\n")
        self.assertEqual(lines, ["UTF-8: 日本語", JA])

    def test_reader_threads_survive_any_bytes(self):
        errors = []
        previous = threading.excepthook
        threading.excepthook = lambda args: errors.append(args.exc_value)
        try:
            code = "import sys; sys.stdout.buffer.write(bytes(range(256)) + b'\\n'); sys.stderr.buffer.write(b'\\x83\\x47\\n')"
            result = run_streaming([sys.executable, "-c", code], timeout=60)
            terminate_pid_tree(2_000_000_000)  # a PID that does not exist: taskkill reports an error in its code page
        finally:
            threading.excepthook = previous
        self.assertEqual(errors, [])
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout and result.stderr)

    @unittest.skipUnless(os.name == "nt", "cmd.exe")
    def test_cmd_exe_messages_are_readable_and_classified(self):
        result = run_streaming('cmd.exe /d /s /c "no_such_command_for_orchestrator_tests"', timeout=60)
        text = result.stdout + result.stderr
        self.assertNotIn("\ufffd", text)
        self.assertIn("no_such_command_for_orchestrator_tests", text)
        self.assertEqual(classify_runner_problem(text), RUNNER_UNAVAILABLE)

    def test_dcc_stream_decodes_mixed_output(self):
        data = legacy_bytes(JA)
        if data is None:
            self.skipTest("the OEM code page here can not express Japanese distinctly from UTF-8")
        code = f"import sys; b = sys.stdout.buffer; b.write('RUN 開始\\n'.encode('utf-8')); b.write({data!r} + b'\\n')"
        chunks = []
        rc = processes.stream([sys.executable, "-c", code], cwd=Path.cwd(), emit=chunks.append)
        self.assertEqual(rc, 0)
        self.assertEqual("".join(chunks), f"RUN 開始\n{JA}\n")


class TailLogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_long_log_first_read_starts_at_a_line_boundary(self):
        line = "20:00:00 [main:claude] 日本語のログ行です\n"
        (self.dir / "events.log").write_text(line * 400, encoding="utf-8")
        for limit in range(1000, 1060):  # every possible cut position inside a line
            text, offset = rs.tail_log(self.dir, 0, initial_limit=limit)
            with self.subTest(limit=limit):
                self.assertNotIn("\ufffd", text)
                self.assertTrue(text.startswith("20:00:00"))
                self.assertEqual(offset, (self.dir / "events.log").stat().st_size)

    def test_a_line_being_written_is_not_consumed_half(self):
        path = self.dir / "events.log"
        path.write_bytes("完了した行\n".encode("utf-8") + "書き込み中".encode("utf-8")[:4])
        text, offset = rs.tail_log(self.dir, 0)
        self.assertEqual(text, "完了した行\n")
        with open(path, "ab") as handle:
            handle.write("書き込み中".encode("utf-8")[4:] + b"\n")
        more, _ = rs.tail_log(self.dir, offset)
        self.assertEqual(more, "書き込み中\n")

    def test_small_chunks_never_split_characters(self):
        (self.dir / "events.log").write_bytes("あいうえお\nかきくけこ\n".encode("utf-8"))
        text, offset, parts = "", 0, []
        for _ in range(20):
            piece, offset = rs.tail_log(self.dir, offset, chunk=7)
            parts.append(piece)
        self.assertEqual("".join(parts), "あいうえお\nかきくけこ\n")


class RunReportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "20260925-201312-118052"
        self.dir.mkdir()

    def full_run(self):
        record = rs.new_record(run_id=self.dir.name, repo="C:/repos/next-day-setup", task="確認Task", main_agent="claude",
                               review_agent="codex", tests=["python -m unittest discover -s tests -p test_*.py -q"],
                               limits=rs.Limits(), branch="main", base_sha="5949f8f9e9d4" + "0" * 28)
        record.update(stage="completed", source_preparation=["switched chatgpt/x -> main (chatgpt/x is kept)"],
                      final_result={"stage": "completed", "code": "OK", "message": "Tests PASS + Reviewer PASS"},
                      candidate_sha="c" * 40, candidate_branch="ai-candidate/x", apply_status="ready",
                      failure_history=[{"fail_no": 1, "fingerprint": "fp1", "summary": "FAIL: test_a"}],
                      repair_history=[{"iteration": 1, "source": "tests", "changed": True, "summary": "修正"}],
                      review_history=[{"round": 1, "verdict": "PASS", "summary": "レビューOK"}])
        common.write_json_atomic(self.dir / "run.json", record)
        (self.dir / "task.md").write_text("確認Task本文\n", encoding="utf-8")
        (self.dir / "events.log").write_text("20:13:15 [source] switched chatgpt/x -> main\n", encoding="utf-8")
        (self.dir / "worker.out").write_text("worker started\n", encoding="utf-8")
        (self.dir / "tests").mkdir()
        (self.dir / "tests" / "run-001.txt").write_text("Ran 790 tests\nOK\n", encoding="utf-8")

    def test_report_contains_every_main_item(self):
        self.full_run()
        report = rs.run_report(self.dir)
        for expected in (f"run id: {self.dir.name}", "repo: C:/repos/next-day-setup", "stage: completed",
                         "final_result: completed / OK", "source_preparation: switched chatgpt/x -> main",
                         "確認Task本文", "tests: python -m unittest discover -s tests -p test_*.py -q",
                         "## events.log", "20:13:15 [source]", "## worker.out", "worker started",
                         "## failure_history", "fp1", "## repair_history", "修正", "## review_history", "レビューOK",
                         f"candidate: {'c' * 40}", "## latest Tests output (run-001.txt)", "Ran 790 tests"):
            self.assertIn(expected, report)

    def test_missing_files_are_skipped_without_error(self):
        common.write_json_atomic(self.dir / "run.json", rs.new_record(
            run_id=self.dir.name, repo="r", task="t", main_agent="claude", review_agent="codex", tests=["x"],
            limits=rs.Limits()))
        report = rs.run_report(self.dir)
        self.assertIn(f"run id: {self.dir.name}", report)
        self.assertIn("final_result: (未終了)", report)
        for absent in ("## events.log", "## worker.out", "## failure_history", "candidate:", "## latest Tests"):
            self.assertNotIn(absent, report)
        # an empty or even non-existent run dir still yields a report
        (self.dir / "run.json").unlink()
        self.assertIn("run.json: (なし・読込不能)", rs.run_report(self.dir))
        self.assertIn("run id: nothing-here", rs.run_report(self.dir.parent / "nothing-here"))

    def test_preparation_not_requested_and_no_op_are_distinguished(self):
        self.full_run()
        record = rs.read_record(self.dir)
        for value, expected in ((None, "source_preparation: 自動準備なし"),
                                ([], "source_preparation: 変更なし（既に管理branchの最新）")):
            record["source_preparation"] = value
            common.write_json_atomic(self.dir / "run.json", record)
            self.assertIn(expected, rs.run_report(self.dir))


class WorktreeNameTests(HostCase):
    def test_worktree_directory_has_the_source_repo_name(self):
        baseline = orch.repo_baseline(self.repo, "main", False)
        parent, worktree = orch.create_worktree(baseline, "t1")
        self.addCleanup(lambda: orch._remove_worktree(baseline, worktree))
        self.assertEqual(worktree.name, self.repo.name)
        self.assertEqual(Path(subprocess.run(["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
                                             capture_output=True, text=True, check=True).stdout.strip()).name,
                         self.repo.name)

    def test_record_says_whether_preparation_was_requested(self):
        _, record = orch.prepare_run(self.request())
        self.assertIsNone(record["source_preparation"])


if __name__ == "__main__":
    unittest.main()
