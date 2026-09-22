"""UTF-8 boundary tests. Never start Orchestrator or an AI provider."""
import ast
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts.dev_control_center import app as dcc
from tools.ai_orchestrator import orchestrator as o

UNICODE = '日本語 — 調査 → 設計 🙂'


class Utf8BoundaryTests(unittest.TestCase):
    def test_dcc_launch_explicitly_sets_child_utf8_without_changing_parent(self):
        ui = mock.MagicMock()
        ui.current = SimpleNamespace(name='test-repo', branch='main')
        ui.active_process = None
        ui.repo_state.head = ui.repo_state.origin_head = 'a'*40
        ui.repo_state.safe_for_lifecycle.return_value = True
        ui.ai_task.get.return_value = UNICODE
        ui.ai_test_var.get.return_value = 'python -m unittest'
        import queue
        ui.ai_output_queue.get_nowait.side_effect = queue.Empty
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.dict(os.environ, {'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp932'}), \
                mock.patch.object(dcc.tempfile, 'gettempdir', return_value=temp), \
                mock.patch.object(dcc.subprocess, 'Popen') as popen, \
                mock.patch.object(dcc.threading, 'Thread'):
            dcc.App.launch_ai_orchestrator(ui)
            popen.assert_called_once()
            command = popen.call_args.args[0]
            kwargs = popen.call_args.kwargs
            self.assertIn(UNICODE, command)
            self.assertEqual(kwargs['env']['PYTHONUTF8'], '1')
            self.assertEqual(kwargs['env']['PYTHONIOENCODING'], 'utf-8')
            self.assertEqual(kwargs['encoding'], 'utf-8')
            self.assertEqual(os.environ['PYTHONUTF8'], '0')
            self.assertEqual(os.environ['PYTHONIOENCODING'], 'cp932')

    def test_both_ai_providers_receive_utf8_and_existing_git_safety(self):
        result = o.CommandResult(('mock',), 0, '{}', '')
        with mock.patch.dict(os.environ, {'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp932'}), \
                mock.patch.object(o, '_resolved_command', side_effect=lambda name: [name]), \
                mock.patch.object(o, '_run', return_value=result) as run:
            o._run_claude_implementation(Path('.'), UNICODE, 5)
            o._run_codex_review(Path('.'), UNICODE, 5, o.DEFAULT_REVIEW_MODEL)
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
                result = o._run([
                    sys.executable, '-c',
                    'import sys; text=sys.stdin.read(); print(text); print(text, file=sys.stderr)',
                ], cwd=root, input_text=UNICODE, env=o._agent_env())
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), UNICODE)
            self.assertEqual(result.stderr.strip(), UNICODE)
            o._write_log(root, 'unicode.log', result.stdout)
            self.assertEqual((root/'unicode.log').read_text(encoding='utf-8').strip(), UNICODE)
            o._write_external_result(str(root/'result.json'), {'detail': UNICODE})
            self.assertEqual(json.loads((root/'result.json').read_text(encoding='utf-8'))['detail'], UNICODE)


if __name__ == '__main__':
    unittest.main()
