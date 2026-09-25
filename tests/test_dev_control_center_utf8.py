"""UTF-8 boundary tests. Never start an Orchestrator run or an AI provider."""
import ast
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tools.ai_orchestrator import common, providers
from tools.ai_orchestrator import orchestrator as o
from tools.ai_orchestrator import runstate as rs

UNICODE = '日本語 — 調査 → 設計 🙂'


class Utf8BoundaryTests(unittest.TestCase):
    def test_both_ai_providers_receive_utf8_prompt_and_existing_git_safety(self):
        ok = common.CommandResult(('mock',), 0, '', '')
        for provider in (providers.ClaudeProvider(), providers.CodexProvider()):
            with self.subTest(provider=provider.name), \
                    mock.patch.dict(os.environ, {'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp932'}), \
                    mock.patch.object(providers, 'resolved_command', side_effect=lambda name: [name]), \
                    mock.patch.object(providers, 'run_streaming', return_value=ok) as run:
                provider.run_main(Path('.'), UNICODE, timeout=5, hooks=common.ProcessHooks())
                provider.run_review(Path('.'), UNICODE, timeout=5, hooks=common.ProcessHooks())
                self.assertEqual(run.call_count, 2)
                for call in run.call_args_list:
                    self.assertEqual(call.kwargs['input_text'], UNICODE)
                    env = call.kwargs['env']
                    self.assertEqual(env['PYTHONUTF8'], '1')
                    self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')
                    self.assertEqual(env['GIT_CONFIG_VALUE_0'], 'disabled://ai-orchestrator')
                self.assertEqual(os.environ['PYTHONIOENCODING'], 'cp932')

    def test_cp932_stdout_and_stderr_are_reconfigured_losslessly(self):
        buffers = [io.BytesIO(), io.BytesIO()]
        streams = [io.TextIOWrapper(buf, encoding='cp932', errors='strict') for buf in buffers]
        try:
            with mock.patch.object(o.sys, 'stdout', streams[0]), mock.patch.object(o.sys, 'stderr', streams[1]):
                o._configure_utf8_stdio()
                print(UNICODE, file=o.sys.stdout, flush=True)
                print(UNICODE, file=o.sys.stderr, flush=True)
            for stream, buf in zip(streams, buffers):
                self.assertEqual(stream.encoding, 'utf-8')
                self.assertEqual(buf.getvalue().decode('utf-8').strip(), UNICODE)
        finally:
            for stream in streams:
                stream.close()

    def test_missing_or_replaced_stdio_is_safe(self):
        with mock.patch.object(o.sys, 'stdout', None), mock.patch.object(o.sys, 'stderr', io.StringIO()):
            o._configure_utf8_stdio()

    def test_utf8_configuration_precedes_argument_parsing_without_running_main(self):
        tree = ast.parse(Path(o.__file__).read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        self.assertEqual(ast.unparse(main.body[0]), '_configure_utf8_stdio()')

    def test_unicode_prompt_roundtrip_in_plain_python_child_and_utf8_logs(self):
        # Only a tiny echo process is started, never an Orchestrator/provider CLI.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.dict(os.environ, {'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp932'}):
                result = common.run_streaming([
                    sys.executable, '-c',
                    'import sys; text=sys.stdin.read(); print(text); print(text, file=sys.stderr)',
                ], cwd=root, input_text=UNICODE, timeout=60, env=providers.agent_env())
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), UNICODE)
            self.assertEqual(result.stderr.strip(), UNICODE)

    def test_task_and_log_survive_the_run_record_as_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / 'run'
            run_dir.mkdir()
            record = rs.new_record(run_id='r', repo='x', task=UNICODE, main_agent='claude', review_agent='codex',
                                   tests=['t'], limits=rs.Limits())
            recorder = rs.RunRecorder(run_dir, record)
            recorder.save()
            recorder.log(UNICODE)
            self.assertEqual(json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))['task'], UNICODE)
            self.assertIn(UNICODE, (run_dir / 'events.log').read_text(encoding='utf-8'))
            text, _ = rs.tail_log(run_dir)
            self.assertIn(UNICODE, text)


if __name__ == '__main__':
    unittest.main()
