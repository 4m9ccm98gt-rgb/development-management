"""Real Git/path boundaries plus fault injection for the host read handoff."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.ai_orchestrator import worktree_access as access
from tools.ai_orchestrator.common import CommandResult, OrchestratorError
from tools.ai_orchestrator.orchestrator import GitHost, RepoBaseline, create_worktree
from ai_orchestrator_fakes import FakeHost, ScriptedProvider, make_recorder
from tools.ai_orchestrator.engine import Engine
from tools.ai_orchestrator import runstate as rs


class ReadGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def test_files_spaces_unicode_multiple_and_deleted_directory(self):
        for rel in ('space name.py', '日本語/test.py', 'nested/sub/new.py'):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('VALUE = 42\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        (self.root / 'nested/sub/new.py').unlink()
        (self.root / 'nested/sub').rmdir()
        access.verify_worktree_readable(self.root)

    def test_read_failure_is_not_an_unreadable_diff_placeholder(self):
        p = self.root / 'new.py'
        p.write_text('secret content must not enter diagnostics')
        host = GitHost(RepoBaseline(self.root, 'main', '', ''), self.root, 'test')
        original = Path.open
        def deny(path, *args, **kwargs):
            if path == p:
                raise PermissionError(13, 'denied')
            return original(path, *args, **kwargs)
        for call in (host.snapshot, lambda: host.run_tests(['unused'], 1, None),
                     lambda: host.create_candidate('unused', 'unused')):
            with self.subTest(call=call), patch.object(Path, 'open', deny):
                with self.assertRaises(OrchestratorError) as caught:
                    call()
                self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_UNREADABLE')
                self.assertNotIn('secret content', str(caught.exception))

    def test_hardlink_is_rejected_without_touching_external_file(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / 'outside.txt'
            outside.write_text('outside')
            os.link(outside, self.root / 'link.txt')
            with self.assertRaises(OrchestratorError) as caught:
                access.verify_worktree_readable(self.root)
            self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_UNSAFE')
            self.assertEqual(outside.read_text(), 'outside')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction')
    def test_junction_is_rejected_without_following_it(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / 'outside.txt'
            outside.write_text('outside')
            link = self.root / 'junction'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), other], check=True, capture_output=True)
            try:
                # Simulate a tracked path whose ancestor the agent replaced.
                result = CommandResult((), 0, 'junction/outside.txt\0', '')
                with patch.object(access, 'git', return_value=result):
                    with self.assertRaises(OrchestratorError) as caught:
                        access.verify_worktree_readable(self.root)
                self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_UNSAFE')
                self.assertEqual(outside.read_text(), 'outside')
            finally:
                link.rmdir()

    def test_unsafe_names_and_enumeration_warning_fail_closed(self):
        for name in ('../outside', '/absolute', 'C:/outside', 'file:stream', 'a\\b', 'a/../b'):
            with self.subTest(name=name):
                with patch.object(access, 'git', return_value=CommandResult((), 0, name+'\0', '')):
                    with self.assertRaises(OrchestratorError) as caught:
                        access.verify_worktree_readable(self.root)
                    self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_UNSAFE')
        with patch.object(access, 'git', return_value=CommandResult((), 0, '', 'cannot open directory')):
            with self.assertRaises(OrchestratorError) as caught:
                access.verify_worktree_readable(self.root)
            self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_UNREADABLE')

    def test_no_file_count_cap(self):
        for index in range(405):
            (self.root / f'{index:04}.txt').write_text('x')
        original = Path.open
        opened = []
        def track(path, *args, **kwargs):
            opened.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', track):
            access.verify_worktree_readable(self.root)
        self.assertEqual(len(opened), 405)


@unittest.skipUnless(os.name == 'nt', 'Windows ACL setup')
class SetupTests(unittest.TestCase):
    def test_acl_failure_stops_before_checkout(self):
        with patch('tools.ai_orchestrator.orchestrator.prepare_worktree_access',
                   side_effect=OrchestratorError('denied', 'WORKTREE_ACCESS_SETUP_FAILED')), \
             patch('tools.ai_orchestrator.orchestrator.git') as git_call:
            with self.assertRaises(OrchestratorError) as caught:
                create_worktree(RepoBaseline(Path('repo'), 'main', 'a'*40, 'a'*40), 'test')
            self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_SETUP_FAILED')
            git_call.assert_not_called()

    def test_nonzero_icacls_and_nonempty_container_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            identity = CommandResult((), 0, '"host","S-1-5-21-1-2-3-1001"\n', '')
            for denied in (CommandResult((), 5, '', 'denied'), CommandResult((), 0, '', 'denied')):
                with patch.object(access, 'run_streaming', side_effect=[identity, denied]):
                    with self.assertRaises(OrchestratorError) as caught:
                        access.prepare_worktree_access(Path(folder))
                    self.assertEqual(caught.exception.code, 'WORKTREE_ACCESS_SETUP_FAILED')
            (Path(folder) / 'existing').write_text('x')
            with patch.object(access, 'run_streaming') as process:
                with self.assertRaises(OrchestratorError):
                    access.prepare_worktree_access(Path(folder))
                process.assert_not_called()


class EngineFailureTests(unittest.TestCase):
    def test_access_failure_stops_before_tests_review_and_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            rec = make_recorder(Path(folder))
            rec.transition(rs.PREFLIGHT)
            host = FakeHost([(True, 'Ran 1 test\nOK')])
            main = ScriptedProvider('main', host, [('+file', 'implemented')])
            review = ScriptedProvider('review', host)
            with patch.object(host, 'normalize_permissions', side_effect=OrchestratorError(
                    'unreadable file', 'WORKTREE_ACCESS_UNREADABLE')):
                self.assertEqual(Engine(rec, host, main, review).run(), rs.FAILED)
            self.assertEqual(rec.record['final_result']['code'], 'WORKTREE_ACCESS_UNREADABLE')
            self.assertEqual(host.test_calls, 0)
            self.assertEqual(host.candidates, 0)
            self.assertEqual(rec.record['review_calls'], 0)
