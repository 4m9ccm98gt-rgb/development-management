"""The automatic Main / Reviewer loop.

    Main implements -> Tests
      Tests FAIL #1      : Main analyses and repairs itself -> Tests
      Tests FAIL #2 (+)  : Reviewer analyses (read-only) -> Main repairs -> Tests
      Tests PASS         : Reviewer final review
        Reviewer FAIL    : Main repairs -> Tests -> Reviewer ...
        Reviewer PASS    : safety checks -> completed

The engine only knows roles (`main`, `reviewer`); provider names never appear here.
Every loop is bounded by `runstate.Limits`. A Tests PASS or Reviewer PASS is bound to
the exact diff it examined: any change sends the work back through Tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Protocol

from .common import OrchestratorError, ProcessHooks, StopRequested
from .providers import (
    ERR_AUTH, ERR_QUOTA, ERR_TRANSIENT, AgentResult, Provider,
)
from .review import (
    ReviewParseError, ReviewVerdict, extract_acceptance, failure_fingerprint, head, parse_review, tail,
)
from .runstate import (
    COMPLETED, FAILED, FINALIZING, IMPLEMENTING, NEEDS_HUMAN, PREFLIGHT, REPAIRING, REVIEWING, STOPPED,
    STOPPING, TESTING, Limits, RunRecorder, kill_owned_children,
)
from .usage import UsageProvider

PROMPTS = Path(__file__).resolve().parent / "prompts"
MAX_DIFF_CHARS = 150_000
MAX_TESTS_CHARS = 14_000
MAX_INSTRUCTION_CHARS = 8_000
RESUME_PROMPT = (
    "Continue the work from the previous instructions in this session. The previous invocation "
    "reached max-turns without a reviewable change. Make the required file changes now; do not "
    "restart investigation, redesign, or self-review. Keep all original scope and safety constraints. "
    "Do not commit, push, build, or deploy."
)
OPERATING_CONTRACT_TEXT = (
    "The Orchestrator runs in an isolated detached worktree. Agents never commit, push, deploy, BUILD or UPDATE, "
    "never change the source repository or the user's data, and never weaken tests. Completion requires Tests PASS, "
    "Reviewer PASS and the Orchestrator's own safety checks, all on the same final diff."
)


class NeedsHuman(OrchestratorError):
    """Automatic operation must end and hand the run back to a person."""

    code = "NEEDS_HUMAN"


class SafetyViolation(NeedsHuman):
    code = "SAFETY_VIOLATION"


@dataclass(frozen=True)
class Snapshot:
    stat: str
    diff: str
    files: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.diff.encode("utf-8")).hexdigest()


class Host(Protocol):
    """Everything that touches the real worktree / Git; replaced by a fake in unit tests."""

    worktree: Path

    def run_tests(self, commands: list[str], timeout: int, hooks: ProcessHooks) -> tuple[bool, str]: ...
    def snapshot(self) -> Snapshot: ...
    def check_safety(self) -> None: ...
    def normalize_permissions(self) -> None: ...
    def repo_instructions(self) -> str: ...
    def create_candidate(self, task: str, run_id: str) -> dict: ...


def render(template: str, values: dict[str, str]) -> str:
    """Single-pass substitution so inserted text is never re-interpreted as a placeholder."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def read_prompt(name: str, values: dict[str, str]) -> str:
    return render((PROMPTS / name).read_text(encoding="utf-8"), values)


class Engine:
    def __init__(self, rec: RunRecorder, host: Host, main: Provider, reviewer: Provider,
                 usage: dict[str, UsageProvider] | None = None, *, sleep=None, clock=time.monotonic):
        self.rec = rec
        self.host = host
        self.main = main
        self.reviewer = reviewer
        self.usage = usage or {}
        self.limits = Limits(**rec.record["limits"])
        self.task = rec.record["task"]
        self.tests = list(rec.record["tests"])
        self._clock = clock
        self._t0 = clock()
        self._sleep = sleep or self._interruptible_sleep
        self.last_tests_ok = False
        self.last_tests_text = ""
        self.tested_fp = ""
        self.reviewed_fp = ""
        self.last_main_summary = ""

    # ------------------------------------------------------------------ top level
    def run(self) -> str:
        rec = self.rec
        try:
            self._implement()
            while True:
                self._guard()
                if self._test():
                    verdict = self._review(final=True)
                    if verdict.passed:
                        self._finalize()
                        return COMPLETED
                    self._repair(source="review", review=verdict)
                    continue
                self._check_failure_limits()
                record = rec.record
                if not record["reviewer_engaged"] and record["tests_fail_count"] < self.limits.reviewer_trigger_fails:
                    self._repair(source="tests")
                else:
                    verdict = self._review(final=False)
                    self._repair(source="tests+review", review=verdict)
        except StopRequested:
            return self._stopped()
        except NeedsHuman as exc:
            rec.finish(NEEDS_HUMAN, exc.code, str(exc), **self._counters())
            return NEEDS_HUMAN
        except OrchestratorError as exc:
            rec.finish(FAILED, exc.code, str(exc), **self._counters())
            return FAILED
        except Exception as exc:  # noqa: BLE001 - never leave a run without a final state
            rec.finish(FAILED, "ORCHESTRATOR_ERROR", f"{type(exc).__name__}: {exc}", **self._counters())
            return FAILED

    def _counters(self) -> dict:
        r = self.rec.record
        return {"tests_run_count": r["tests_run_count"], "tests_fail_count": r["tests_fail_count"],
                "repair_iteration": r["repair_iteration"], "main_calls": r["main_calls"],
                "review_calls": r["review_calls"]}

    def _stopped(self) -> str:
        rec = self.rec
        previous = rec.stage
        rec.record["stopped_by_user"] = True
        rec.transition(STOPPING, "safe stop: terminating this run's processes")
        outcomes = kill_owned_children(rec.record)
        rec.finish(STOPPED, "USER_SAFETY_STOP", "ユーザーによるAI安全停止", stopped_by_user=True,
                   stage_at_stop=previous, process_results=outcomes, **self._counters())
        return STOPPED

    def _guard(self) -> None:
        if self.rec.stop_event.is_set():
            raise StopRequested("safe stop requested")
        if (self._clock() - self._t0) / 60 > self.limits.max_runtime_minutes:
            raise NeedsHuman(f"最大実行時間 {self.limits.max_runtime_minutes} 分に到達しました", "MAX_RUNTIME")

    def _interruptible_sleep(self, seconds: float) -> None:
        if self.rec.stop_event.wait(seconds):
            raise StopRequested("safe stop requested")

    # ------------------------------------------------------------------ providers
    def _hooks(self, role: str, provider: Provider | None) -> ProcessHooks:
        tag = f"{role}:{provider.name}" if provider is not None else role

        def line(stream: str, text: str) -> None:
            self.rec.log(f"[{tag}] {text}")
        return ProcessHooks(on_line=line, stop=self.rec.stop_event, registry=self.rec, label=tag.replace(":", "-"))

    def _ingest_usage(self, result: AgentResult) -> None:
        for adapter in self.usage.values():
            try:
                adapter.ingest(result)
            except Exception:  # noqa: BLE001 - usage is auxiliary and must never affect the run
                pass

    def _invoke(self, role: str, provider: Provider, call, label: str) -> AgentResult:
        """One logical provider call: counted, logged, safety-checked, error-classified.

        Only `transient` errors are retried (bounded); quota / auth / other errors end automatic
        operation immediately and are recorded in the run."""
        counter = "main_calls" if role == "main" else "review_calls"
        for attempt in range(self.limits.max_provider_retries + 1):
            self._guard()
            call_no = self.rec.incr(counter)
            self.rec.log(f"[{role}:{provider.name}] call #{call_no} {label}" + (f" (retry {attempt})" if attempt else ""))
            result = call()
            self.rec.write_text(f"calls/{role}-{call_no:03d}.log", result.raw)
            self._ingest_usage(result)
            self.host.check_safety()
            if result.ok or result.max_turns:
                return result
            entry = {"role": role, "provider": provider.name, "kind": result.error_kind,
                     "detail": result.error_detail, "call": call_no, "attempt": attempt,
                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self.rec.append("quota_errors" if result.error_kind == ERR_QUOTA else "provider_errors", entry)
            self.rec.log(f"[{role}:{provider.name}] {result.error_kind}: {result.error_detail}")
            who = f"{provider.display or provider.name}（{'Main' if role == 'main' else 'Reviewer'}）"
            if result.error_kind == ERR_QUOTA:
                raise NeedsHuman(f"{who}の利用枠・クレジットが不足しています。自動再試行・自動切替は行いません: "
                                 f"{result.error_detail}", "PROVIDER_QUOTA")
            if result.error_kind == ERR_AUTH:
                raise NeedsHuman(f"{who}の認証を確認してください: {result.error_detail}", "PROVIDER_AUTH")
            if result.error_kind == ERR_TRANSIENT and attempt < self.limits.max_provider_retries:
                self._sleep(20 * (attempt + 1))
                continue
            raise NeedsHuman(f"{who}が異常終了しました（{result.error_kind}）: {result.error_detail}", "PROVIDER_ERROR")
        raise NeedsHuman("provider retries exhausted", "PROVIDER_ERROR")  # pragma: no cover

    def _call_main(self, prompt: str, label: str, *, implementation: bool) -> str:
        session = None
        before = self.host.snapshot().fingerprint
        for resume in range(self.limits.max_main_resumes + 1):
            text_prompt = prompt if session is None else RESUME_PROMPT
            result = self._invoke(
                "main", self.main,
                lambda p=text_prompt, s=session: self.main.run_main(
                    self.host.worktree, p, timeout=self.limits.agent_timeout,
                    hooks=self._hooks("main", self.main), session_id=s),
                label + (f" resume {resume}" if resume else ""))
            session = result.session_id or session
            self.host.normalize_permissions()
            snap = self.host.snapshot()
            changed = snap.fingerprint != before
            if result.max_turns and not changed:
                if self.main.supports_resume and session and resume < self.limits.max_main_resumes:
                    continue
                raise NeedsHuman("Main AIがturn上限に達し、変更を出せませんでした", "MAIN_NO_PROGRESS")
            text = result.text or "Main reached max-turns; partial worktree changes are kept for Tests."
            self.last_main_summary = text
            self.rec.write_text(f"calls/main-summary-{self.rec.record['main_calls']:03d}.txt", text)
            if re.search(r"(?m)^\s*IMPLEMENTATION_STATUS:\s*BLOCKED\s*$", text):
                raise NeedsHuman("Main AIがTaskを人間判断なしには進められないと報告しました: " + head(text, 600),
                                 "TASK_BLOCKED")
            if implementation and not snap.diff.strip():
                raise NeedsHuman("Main AIの実装で変更が発生しませんでした", "NO_CHANGES")
            return text
        raise NeedsHuman("Main AIが進展しませんでした", "MAIN_NO_PROGRESS")  # pragma: no cover

    # ------------------------------------------------------------------ steps
    def _implement(self) -> None:
        self.rec.transition(IMPLEMENTING, f"Main AI ({self.main.display}) が実装中")
        self._call_main(read_prompt("main_implementation.md", {"TASK": self.task}), "implementation",
                        implementation=True)

    def _test(self) -> bool:
        rec = self.rec
        rec.transition(TESTING, "独立Tests実行中")
        before = self.host.snapshot().fingerprint
        try:
            ok, text = self.host.run_tests(self.tests, self.limits.test_timeout, self._hooks("tests", None))
        except StopRequested:
            raise
        except OrchestratorError as exc:
            ok, text = False, f"Tests could not run: {exc}"
        self.host.check_safety()
        if self.host.snapshot().fingerprint != before:
            raise SafetyViolation("worktree changed during Tests; the result no longer describes the code")
        number = rec.incr("tests_run_count")
        rec.write_text(f"tests/run-{number:03d}.txt", text)
        self.last_tests_ok, self.last_tests_text, self.tested_fp = ok, text, before
        if ok:
            rec.update(tests_consecutive_fail_count=0, current_failure_fingerprint=None)
            rec.log(f"[tests] PASS (run #{number})")
            return True
        fails = rec.incr("tests_fail_count")
        rec.incr("tests_consecutive_fail_count")
        fingerprint, summary = failure_fingerprint(text)
        counts = dict(rec.record["failure_fingerprint_counts"])
        counts[fingerprint] = counts.get(fingerprint, 0) + 1
        rec.update(current_failure_fingerprint=fingerprint, failure_fingerprint_counts=counts)
        rec.append("failure_history", {"tests_run": number, "fail_no": fails, "fingerprint": fingerprint,
                                       "occurrence": counts[fingerprint], "summary": summary,
                                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        rec.log(f"[tests] FAIL #{fails} (run #{number}) fingerprint={fingerprint} x{counts[fingerprint]}: {summary}")
        return False

    def _check_failure_limits(self) -> None:
        fingerprint = self.rec.record["current_failure_fingerprint"]
        count = self.rec.record["failure_fingerprint_counts"].get(fingerprint, 0)
        if count >= self.limits.max_same_failure:
            raise NeedsHuman(f"同じfailure fingerprint({fingerprint})が{count}回繰り返されました。自動修正では進展しません",
                             "SAME_FAILURE_REPEATED")

    def _history_text(self) -> str:
        record = self.rec.record
        lines = []
        for item in record["failure_history"][-8:]:
            lines.append(f"- Tests FAIL #{item['fail_no']} fp={item['fingerprint']} (x{item['occurrence']}): {item['summary']}")
        for item in record["repair_history"][-8:]:
            lines.append(f"- Repair {item['iteration']} ({item['source']}): "
                         f"{'changed the diff' if item['changed'] else 'NO CHANGE to the diff'}; {item['summary']}")
        for item in record["review_history"][-6:]:
            lines.append(f"- Review {item['round']} ({item['mode']}): {item['verdict']} fp={item['fingerprint']}: {item['summary'][:200]}")
        return "\n".join(lines) or "(none yet)"

    def _repair(self, *, source: str, review: ReviewVerdict | None = None) -> None:
        rec = self.rec
        if rec.record["repair_iteration"] >= self.limits.max_repair_iterations:
            raise NeedsHuman(f"最大repair iteration({self.limits.max_repair_iterations})に到達しました", "MAX_REPAIR_ITERATIONS")
        if review is not None and review.needs_human:
            raise NeedsHuman("Reviewerが人間判断を要求しました: " + review.needs_human_reason, "REVIEWER_NEEDS_HUMAN")
        iteration = rec.incr("repair_iteration")
        rec.transition(REPAIRING, f"Main AI ({self.main.display}) が修正中 (repair {iteration}/{self.limits.max_repair_iterations}, {source})")
        before = self.host.snapshot().fingerprint
        if source == "review":
            trigger = "The Reviewer AI rejected the current work although Tests passed."
        elif review is None:
            trigger = f"Independent Tests failed (Tests FAIL #{rec.record['tests_fail_count']}). Analyse and repair it yourself."
        else:
            trigger = (f"Independent Tests failed (Tests FAIL #{rec.record['tests_fail_count']}) and the Reviewer AI "
                       "analysed the failure.")
        prompt = read_prompt("main_repair.md", {
            "TASK": self.task,
            "TRIGGER": trigger,
            "FAILURE": tail(self.last_tests_text, MAX_TESTS_CHARS) if not self.last_tests_ok
            else "(Tests passed on the current diff; the rejection comes from the review.)",
            "REVIEW": head(review.instructions, MAX_INSTRUCTION_CHARS) if review
            else "(none — analyse the Tests failure yourself)",
            "HISTORY": self._history_text(),
        })
        summary = self._call_main(prompt, f"repair {iteration}", implementation=False)
        after = self.host.snapshot().fingerprint
        changed = after != before
        no_change = 0 if changed else rec.record["no_change_repairs"] + 1
        rec.update(no_change_repairs=no_change)
        rec.append("repair_history", {"iteration": iteration, "source": source, "changed": changed,
                                      "review_fingerprint": review.fingerprint if review else None,
                                      "summary": " ".join(summary.split())[:300],
                                      "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if no_change >= self.limits.max_no_change_repairs:
            raise NeedsHuman(f"Main AIが{no_change}回連続で差分を変更しませんでした。進展がないため停止します", "NO_PROGRESS")

    def _review(self, *, final: bool) -> ReviewVerdict:
        rec = self.rec
        if rec.record["review_rounds"] >= self.limits.max_review_rounds:
            raise NeedsHuman(f"最大レビュー回数({self.limits.max_review_rounds})に到達しました", "MAX_REVIEW_ROUNDS")
        round_no = rec.incr("review_rounds")
        mode = "final_review" if final else "failure_analysis"
        rec.update(reviewer_engaged=True)
        rec.transition(REVIEWING, f"Reviewer AI ({self.reviewer.display}) が{'最終レビュー' if final else '失敗分析'}中 (round {round_no})")
        snap = self.host.snapshot()
        before = snap.fingerprint
        if final and (not self.last_tests_ok or before != self.tested_fp):
            raise SafetyViolation("final review requested on a diff that Tests did not pass")
        prompt = read_prompt("reviewer.md", {
            "MODE": ("FINAL REVIEW: Tests passed on this exact diff. Decide PASS or FAIL." if final else
                     "FAILURE ANALYSIS: Tests are failing. Find the root cause and tell Main what to change (verdict FAIL, or NEEDS_HUMAN)."),
            "TASK": self.task,
            "ACCEPTANCE": extract_acceptance(self.task) or "(no explicit section; derive the conditions from the TaskSpec)",
            "BASE": f"{rec.record['source_branch']} @ {rec.record['base_sha']}",
            "FILES": "\n".join(snap.files) or "(none)",
            "STAT": snap.stat or "(none)",
            "DIFF": head(snap.diff, MAX_DIFF_CHARS),
            "TESTS": f"Result: {'PASS' if self.last_tests_ok else 'FAIL'} "
                     f"(run #{rec.record['tests_run_count']}, FAIL count {rec.record['tests_fail_count']})\n"
                     + tail(self.last_tests_text, MAX_TESTS_CHARS),
            "MAIN_SUMMARY": head(self.last_main_summary, 3000) or "(none)",
            "FAILURE_HISTORY": "\n".join(
                f"- FAIL #{f['fail_no']} fp={f['fingerprint']} x{f['occurrence']}: {f['summary']}"
                for f in rec.record["failure_history"][-10:]) or "(no Tests failure so far)",
            "REPAIR_HISTORY": self._history_text(),
            "CONTRACT": OPERATING_CONTRACT_TEXT,
            "REPO_INSTRUCTIONS": self.host.repo_instructions() or "(none)",
        })
        verdict = None
        for attempt in range(2):
            result = self._invoke(
                "review", self.reviewer,
                lambda p=prompt: self.reviewer.run_review(
                    self.host.worktree, p, timeout=self.limits.review_timeout,
                    hooks=self._hooks("review", self.reviewer)),
                mode)
            if self.host.snapshot().fingerprint != before:
                raise SafetyViolation("the read-only Reviewer changed the worktree")
            try:
                verdict = parse_review(result.text, failure_mode=not final)
                break
            except ReviewParseError as exc:
                rec.append("provider_errors", {"role": "review", "provider": self.reviewer.name, "kind": "protocol",
                                               "detail": str(exc), "call": rec.record["review_calls"],
                                               "attempt": attempt, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
                rec.log(f"[review] unusable reply: {exc}")
                prompt += f"\n\nYour previous reply could not be used ({exc}). Reply with the single JSON object only."
        if verdict is None:
            raise NeedsHuman("Reviewerの回答を解釈できませんでした", "REVIEW_UNPARSABLE")
        rec.append("review_history", {
            "round": round_no, "mode": mode, "verdict": verdict.verdict, "summary": verdict.summary,
            "findings": list(verdict.findings), "fingerprint": verdict.fingerprint, "instructions": verdict.instructions,
            "tests_ok": self.last_tests_ok, "diff_fingerprint": before[:16], "reviewer": self.reviewer.name,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        rec.log(f"[review] {verdict.verdict} ({mode}): {verdict.summary[:200]}")
        if verdict.needs_human:
            raise NeedsHuman("Reviewerが人間判断を要求しました: " + verdict.needs_human_reason, "REVIEWER_NEEDS_HUMAN")
        if verdict.passed:
            self.reviewed_fp = before
            return verdict
        counts = dict(rec.record["review_fingerprint_counts"])
        counts[verdict.fingerprint] = counts.get(verdict.fingerprint, 0) + 1
        rec.update(review_fingerprint_counts=counts)
        if counts[verdict.fingerprint] >= self.limits.max_same_review:
            raise NeedsHuman(f"Reviewerが同じ指摘({verdict.fingerprint})を{counts[verdict.fingerprint]}回繰り返しました。"
                             "MainとReviewerが進展なくループしています", "REVIEW_LOOP")
        return verdict

    def _finalize(self) -> None:
        rec = self.rec
        rec.transition(FINALIZING, "安全チェック中")
        self.host.check_safety()
        snap = self.host.snapshot()
        if not snap.diff.strip():
            raise NeedsHuman("完成対象の差分がありません", "NO_CHANGES")
        if not (self.last_tests_ok and snap.fingerprint == self.tested_fp == self.reviewed_fp):
            raise SafetyViolation("Tests PASS / Reviewer PASS do not describe the final diff")
        candidate = self.host.create_candidate(self.task, rec.record["run_id"])
        rec.update(candidate_branch=candidate.get("branch", ""), candidate_sha=candidate.get("sha", ""),
                   apply_status=candidate.get("apply_status", ""), apply_detail=candidate.get("apply_detail", ""))
        rec.finish(COMPLETED, "OK", "Tests PASS + Reviewer PASS + 安全チェックPASS",
                   candidate_sha=candidate.get("sha", ""), **self._counters())
