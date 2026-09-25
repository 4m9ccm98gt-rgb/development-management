"""Shared fakes for AI Orchestrator tests (no paid AI, no network).

`FakeHost` replaces the real worktree; `ScriptedProvider` plays a Main or Reviewer role.
Also usable as AI_ORCHESTRATOR_EXTRA_PROVIDERS for real detached worker processes:
providers `fakemain` / `fakereview` act on the worktree with plain files.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from tools.ai_orchestrator import runstate as rs
from tools.ai_orchestrator.common import ProcessHooks
from tools.ai_orchestrator.engine import Snapshot, SafetyViolation
from tools.ai_orchestrator.providers import AgentResult, Provider


class FakeHost:
    def __init__(self, test_results, worktree: Path | None = None):
        self.worktree = worktree or Path("fake-worktree")
        self.diff = ""
        self._results = list(test_results)
        self.test_calls = 0
        self.unsafe = False
        self.candidates = 0

    def snapshot(self) -> Snapshot:
        return Snapshot("1 file changed", self.diff, ("M\tapp.py",))

    def run_tests(self, commands, timeout, hooks):
        self.test_calls += 1
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        return result

    def check_safety(self):
        if self.unsafe:
            raise SafetyViolation("unsafe")

    def normalize_permissions(self):
        pass

    def repo_instructions(self):
        return "repo rules"

    def create_candidate(self, task, run_id):
        self.candidates += 1
        return {"branch": "ai-candidate/x", "sha": "a" * 40, "apply_status": "ready", "apply_detail": ""}


def review_json(verdict="PASS", summary="checked the diff and Tests", findings=None, instructions="", **extra):
    body = {"verdict": verdict, "summary": summary, "findings": findings or [],
            "instructions_for_main": instructions, **extra}
    return json.dumps(body)


FAIL_REVIEW = review_json(
    "FAIL", "requirement gap", instructions="Handle the empty input in app.py",
    findings=[{"severity": "major", "file": "app.py", "problem": "empty input crashes", "instruction": "guard it"}])


class ScriptedProvider(Provider):
    """Main: each call pops (mutation, text | AgentResult). Reviewer: pops raw reply text."""

    supports_resume = False

    def __init__(self, name: str, host: FakeHost, main_script=(), review_script=()):
        self.name = name
        self.display = name.capitalize()
        self.host = host
        self.main_script = list(main_script)
        self.review_script = list(review_script)
        self.main_prompts: list[str] = []
        self.review_prompts: list[str] = []
        self.review_mutates = False

    def run_main(self, worktree, prompt, *, timeout, hooks, session_id=None):
        self.main_prompts.append(prompt)
        step = self.main_script.pop(0) if len(self.main_script) > 1 else self.main_script[0]
        mutation, reply = step
        if mutation:
            self.host.diff += mutation
        if isinstance(reply, AgentResult):
            return reply
        return AgentResult(self.name, "main", True, text=reply)

    def run_review(self, worktree, prompt, *, timeout, hooks):
        self.review_prompts.append(prompt)
        if self.review_mutates:
            self.host.diff += "!reviewer-edit"
        reply = self.review_script.pop(0) if len(self.review_script) > 1 else self.review_script[0]
        if isinstance(reply, AgentResult):
            return reply
        return AgentResult(self.name, "review", True, text=reply)


def error_result(provider, role, kind, detail="boom"):
    return AgentResult(provider, role, False, error_kind=kind, error_detail=detail, raw=detail)


def make_recorder(directory: Path, *, main="claude", reviewer="codex", limits=None, tests=("python -m unittest",)):
    run_dir = Path(directory) / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    record = rs.new_record(run_id="20260101-000000-000000", repo=str(directory / "repo"), task="Implement feature X.\n## 受入条件\n- works",
                           main_agent=main, review_agent=reviewer, tests=list(tests), limits=limits or rs.Limits(),
                           branch="main", base_sha="b" * 40)
    return rs.RunRecorder(run_dir, record)


# Providers for real detached worker processes live in ai_orchestrator_fake_providers.py
from ai_orchestrator_fake_providers import PROVIDERS  # noqa: E402,F401
