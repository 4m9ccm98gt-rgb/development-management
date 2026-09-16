"""Exercise the real PowerShell sync controller with a deterministic Git double."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
class NonInteractiveSyncTests(unittest.TestCase):
    def run_case(self, scenario, candidate=SHA):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / 'scripts'
            scripts.mkdir()
            shutil.copy2(ROOT / 'scripts/SYNC_CANDIDATE.ps1', scripts)
            fake = root / 'git_double.py'
            fake.write_text('''import json, os, sys
from pathlib import Path
a=sys.argv[1:]; a=a[2:] if a[:1]==['-C'] else a
r=Path(__file__).parent
with (r/'calls.jsonl').open('a') as f: f.write(json.dumps(a)+'\\n')
s=os.environ['DCC_SCENARIO']; sha='a'*40
if a==['rev-parse','--show-toplevel']: print(r)
elif a==['rev-parse','--is-inside-work-tree']: print('true')
elif a==['remote','get-url','origin']: print('https://github.com/example/'+('wrong' if s=='origin' else 'app')+'.git')
elif a==['branch','--show-current']: print('' if s=='detached' else 'wrong' if s=='branch' else 'main')
elif a[:1]==['status']: print(' M tracked.txt' if s=='dirty' else '')
elif a[:1]==['fetch']:
 if s=='fetch': sys.exit(1)
elif a[:1]==['rev-list']: print('1' if (s=='ahead' and a[-1].endswith('..HEAD')) or (s=='behind' and a[-1].startswith('HEAD..') and not (r/'merged').exists()) else '0')
elif a[:1]==['rev-parse']: print('b'*40 if s=='candidate' and a[-1].startswith('refs/') else sha)
elif a[:1]==['merge']:
 assert s=='behind' and a==['merge','--ff-only','refs/remotes/origin/main']
 (r/'merged').touch()
else: raise RuntimeError(str(a))
''', encoding='utf-8')
            (root / 'git.cmd').write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\nexit /b %ERRORLEVEL%\n')
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], DCC_SCENARIO=scenario)
            command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(scripts / 'SYNC_CANDIDATE.ps1'), '-ExpectedRepo', 'example/app', '-TargetBranch', 'main', '-NoPause']
            if candidate:
                command += ['-ExpectedSha', candidate]
            result = subprocess.run(command, env=env, capture_output=True, timeout=20)
            report = (root / 'SYNC_RESULT.txt').read_text()
            calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
            return result.returncode, report, calls

    def test_matching_candidate_succeeds(self):
        code, report, calls = self.run_case('success')
        self.assertEqual(code, 0, report)
        self.assertIn('state: SUCCESS', report)
        self.assertIn(['fetch', '--prune', 'origin', 'main'], calls)

    def test_invalid_states_stop_without_merge(self):
        for scenario in ['origin', 'branch', 'detached', 'dirty', 'ahead', 'candidate', 'fetch']:
            with self.subTest(scenario=scenario):
                code, report, calls = self.run_case(scenario)
                self.assertNotEqual(code, 0, report)
                self.assertIn('state: STOPPED', report)
                self.assertFalse(any(a[0] == 'merge' for a in calls))

    def test_behind_uses_only_fast_forward(self):
        code, report, calls = self.run_case('behind')
        self.assertEqual(code, 0, report)
        self.assertIn(['merge', '--ff-only', 'refs/remotes/origin/main'], calls)

    def test_missing_and_short_sha_do_not_prompt_or_fetch(self):
        for candidate in ['', 'abcdef1']:
            with self.subTest(candidate=candidate):
                code, report, calls = self.run_case('success', candidate)
                self.assertNotEqual(code, 0, report)
                self.assertFalse(any(a[0] == 'fetch' for a in calls))


if __name__ == '__main__':
    unittest.main()
