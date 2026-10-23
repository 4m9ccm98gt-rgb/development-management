"""DCC Python selection with fake providers / processes; no CLI or ACL changes."""
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

from tools.ai_orchestrator import providers as p
from tools.ai_orchestrator import settings
from tools.ai_orchestrator.common import CommandResult, OrchestratorError, ProcessHooks


class PythonSettingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exe = self.root / "python.exe"
        self.exe.write_bytes(b"fake interpreter, never executed")
        self.config = self.root / "orchestrator_local.toml"

    def write_setting(self, value):
        self.config.write_text('[orchestrator]\ncodex_main_python = ' + json.dumps(value), encoding="utf-8")

    def test_setting_is_read_only_from_local_dcc_config(self):
        self.write_setting(str(self.exe))
        self.assertEqual(settings.load_codex_main_python(self.config), str(self.exe.resolve()))
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            self.assertEqual(settings.local_settings_path(), self.root / "ShizenDev/DCC/orchestrator_local.toml")

    def test_missing_and_empty_setting_keep_default(self):
        self.assertEqual(settings.load_codex_main_python(self.config), "")
        for text in ("", "[orchestrator]", '[orchestrator]\ncodex_main_python = ""'):
            self.config.write_text(text, encoding="utf-8")
            self.assertEqual(settings.load_codex_main_python(self.config), "")

    def test_invalid_values_are_rejected_without_fallback(self):
        not_python = self.root / "other.exe"
        not_python.touch()
        for value in (str(self.root / "missing/python.exe"), str(not_python), str(self.root), 123, False):
            with self.subTest(value=value):
                self.write_setting(value)
                with self.assertRaises(OrchestratorError) as ctx:
                    settings.load_codex_main_python(self.config)
                self.assertEqual(ctx.exception.code, "CODEX_MAIN_PYTHON_INVALID")

    def test_invalid_config_is_an_error(self):
        for text in ("[broken", 'orchestrator = "invalid"'):
            self.config.write_text(text, encoding="utf-8")
            with self.assertRaises(OrchestratorError) as ctx:
                settings.load_codex_main_python(self.config)
            self.assertEqual(ctx.exception.code, "CODEX_MAIN_PYTHON_CONFIG_INVALID")

    def test_configured_main_process_and_shell_use_same_python_even_with_repo_venv(self):
        provider = p.CodexProvider()
        provider.codex_main_python = str(self.exe)
        provider.extra_env = {"PATH": "repo-venv" + os.pathsep + "original", "VIRTUAL_ENV": "repo"}
        with mock.patch.object(p, "resolved_command", return_value=["fake-codex"]), \
             mock.patch.object(p, "run_streaming", return_value=CommandResult(("fake",), 1, "", "failed")) as runner:
            provider.run_main(self.root, 'Ignore this Python path: C:\\report\\python.exe', timeout=1, hooks=ProcessHooks())
        self.assertEqual(runner.call_count, 1)
        command = runner.call_args.args[0]
        env = runner.call_args.kwargs["env"]
        self.assertEqual(env["AI_ORCHESTRATOR_PYTHON"], str(self.exe.resolve()))
        # Different Windows spellings (including 8.3 aliases) can refer to the same folder.
        self.assertEqual(Path(env["PATH"].split(os.pathsep)[0]).resolve(), self.root.resolve())
        self.assertEqual(env["PATH"].split(os.pathsep)[1], "repo-venv")
        overrides = tomllib.loads("\n".join(command[i+1] for i, x in enumerate(command) if x == "-c"))
        self.assertEqual(overrides, {"shell_environment_policy": {"set": {
            key: env[key] for key in ("PATH", "AI_ORCHESTRATOR_PYTHON")}}})
        self.assertEqual(command[:8], ["fake-codex", "exec", "--json", "--sandbox", "workspace-write", "-C", str(self.root), "--ephemeral"])
        self.assertNotIn("--add-dir", command)

    def test_empty_setting_is_identical_to_previous_python_environment(self):
        provider = p.CodexProvider()
        provider.extra_env = {"PATH": "repo-venv" + os.pathsep + "original", "VIRTUAL_ENV": "repo"}
        with mock.patch.object(p.sys, "executable", str(self.exe)), \
             mock.patch.dict(os.environ, {"AI_ORCHESTRATOR_PYTHON": "untrusted-env"}):
            env = provider.child_env("main")
        self.assertEqual(env["PATH"].split(os.pathsep), ["repo-venv", str(self.root), "original"])
        self.assertEqual(env["AI_ORCHESTRATOR_PYTHON"], str(self.exe))

    def test_invalid_or_disappeared_executable_stops_before_process(self):
        provider = p.CodexProvider()
        provider.codex_main_python = str(self.exe)
        self.exe.unlink()
        with mock.patch.object(p, "resolved_command", return_value=["fake-codex"]), \
             mock.patch.object(p, "run_streaming") as runner:
            with self.assertRaises(OrchestratorError):
                provider.run_main(self.root, "task", timeout=1, hooks=ProcessHooks())
        runner.assert_not_called()

    def test_reviewer_and_claude_are_unaffected_even_with_invalid_setting(self):
        provider = p.CodexProvider()
        provider.codex_main_python = "invalid"
        with mock.patch.object(p, "resolved_command", side_effect=lambda name: [name]), \
             mock.patch.object(p, "run_streaming", return_value=CommandResult(("fake",), 1, "", "failed")) as runner:
            provider.run_review(self.root, "review", timeout=1, hooks=ProcessHooks())
            self.assertEqual(runner.call_args.kwargs["env"], p.agent_env())
            self.assertEqual(runner.call_args.args[0], provider._command(self.root, "read-only"))
            claude = p.ClaudeProvider()
            claude.run_main(self.root, "task", timeout=1, hooks=ProcessHooks())
            self.assertEqual(runner.call_args.kwargs["env"], p.agent_env())
            self.assertEqual(runner.call_args.args[0], claude._main_command(None))
