"""Fake providers loaded by real worker processes via AI_ORCHESTRATOR_EXTRA_PROVIDERS.

Kept free of engine / test-fixture imports: the orchestrator imports this file while its own
provider module is still initialising.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

from tools.ai_orchestrator.common import ProcessHooks
from tools.ai_orchestrator.providers import AgentResult, Provider


class _FileProvider(Provider):
    """Provider that edits real files in the worktree; behaviour is selected by keywords in the prompt.

    SLEEP        non-cooperative: sleeps in-process (only a forced stop can end it)
    STREAM-CHILD cooperative: runs a child tree through run_streaming (registered, stop-aware);
                 the child and grandchild PIDs are written to <run>/pids.txt
    """

    def preflight(self):
        pass

    def run_main(self, worktree, prompt, *, timeout, hooks, session_id=None):
        worktree = Path(worktree)
        if "STREAM-CHILD" in prompt:
            from tools.ai_orchestrator.common import run_streaming

            code = "\n".join([
                "import subprocess, sys, time",
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])",
                "print('PIDS', __import__('os').getpid(), g.pid, flush=True)",
                "time.sleep(600)",
            ])

            def on_line(stream, line):
                if line.startswith("PIDS "):
                    (worktree.parent / "pids.txt").write_text(line[5:], encoding="utf-8")

            run_streaming([sys.executable, "-c", code], cwd=worktree, timeout=900,
                          hooks=ProcessHooks(on_line=on_line, stop=hooks.stop, registry=hooks.registry, label="fake-tree"))
        if "SLEEP" in prompt:
            (worktree.parent / "sleeping.flag").write_text("1")
            time.sleep(60)
        (worktree / "feature.txt").write_text("done\n", encoding="utf-8")
        return AgentResult(self.name, "main", True, text="implemented feature.txt")

    def run_review(self, worktree, prompt, *, timeout, hooks):
        return AgentResult(self.name, "review", True, text=json.dumps({"verdict": "PASS", "summary": "fake review of the worktree", "findings": []}))


class FakeMain(_FileProvider):
    name = "fakemain"
    display = "FakeMain"


class FakeReview(_FileProvider):
    name = "fakereview"
    display = "FakeReview"


PROVIDERS = [FakeMain, FakeReview]
