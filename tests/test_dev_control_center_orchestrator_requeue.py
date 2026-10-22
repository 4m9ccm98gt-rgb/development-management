"""DCC Task 19b: automatic re-run of a PROVIDER_QUOTA-stopped Orchestrator run
(orchestrator_requeue.py).

Every test here uses only fakes/temp dirs: list_runs_fn, active_runs_fn and start_requeue_fn are
always injected -- never the real Orchestrator, real Tk, or the real %LOCALAPPDATA%. `log_dir`
and `daily_count_path` are always pointed at a tempfile.TemporaryDirectory() whenever a cycle
might actually reach a real start or a persisted count, so nothing here ever touches the real
user profile. No network, no subprocess, no real waiting (a fixed `now` is always passed in).
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts.dev_control_center import activity_log
from scripts.dev_control_center import orchestrator_requeue as req
from scripts.dev_control_center import reports_auto as auto

NOW = datetime(2026, 3, 10, 16, 50, 0, tzinfo=timezone.utc)

# Every generic flow test below uses a message that deliberately does not match the strict
# quota-reset shape, so it always gets the fixed FALLBACK_DELAY_MINUTES (60) wait -- a single,
# predictable schedule shared by every test that is not itself about delay calculation (that is
# DelayCalculationTests' own job, with its own dedicated messages/clocks below).
DEFAULT_MESSAGE = "rate limited, try again later"
DUE_AFTER_FALLBACK = NOW + timedelta(minutes=65)  # safely past the 60-minute fallback wait

# DCC Task WF-6b (reviewer finding 3): every req.run_requeue_once call in this module must pass
# its own tmp-backed activity_log_path -- a forgotten one would otherwise silently fall back to
# activity_log.log_path()'s real %LOCALAPPDATA% default. Patching log_path itself to raise turns
# that fallback into a loud test failure instead of a silent write to real user data.
_log_path_guard = mock.patch.object(
    activity_log, "log_path",
    side_effect=AssertionError("activity_log.log_path() reached -- a test forgot to pass its own "
                               "tmp-backed activity_log_path"))


def setUpModule():
    _log_path_guard.start()


def tearDownModule():
    _log_path_guard.stop()


def make_record(run_id="run-a", repo="C:/repos/app", stage="needs_human", code="PROVIDER_QUOTA",
                 message=DEFAULT_MESSAGE, task="Task本文",
                 tests=("python -m unittest",), main_agent="claude", review_agent="codex",
                 criteria=({"id": "C1", "text": "条件1"},)) -> dict:
    return {
        "run_id": run_id, "repo": repo, "stage": stage,
        "final_result": {"stage": stage, "code": code, "message": message},
        "task": task, "tests": list(tests), "main_agent": main_agent, "review_agent": review_agent,
        "criteria": [dict(c) for c in criteria], "source_branch": "main",
    }


def make_item(**overrides) -> dict:
    return {"record": make_record(**overrides)}


class RequeueConfigTests(unittest.TestCase):
    def test_default_is_off(self):
        config = req.RequeueConfig()
        self.assertFalse(config.enabled)
        self.assertEqual(config.daily_limit, req.DEFAULT_DAILY_LIMIT)

    def test_missing_file_loads_as_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = req.load_requeue_config(Path(tmp) / "no-such-config.json")
            self.assertFalse(config.enabled)

    def test_corrupt_file_degrades_to_defaults_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("not json{{{", encoding="utf-8")
            config = req.load_requeue_config(path)
            self.assertFalse(config.enabled)

    def test_set_enabled_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            req.set_enabled(True, path=path)
            self.assertTrue(req.load_requeue_config(path).enabled)
            req.set_enabled(False, path=path)
            self.assertFalse(req.load_requeue_config(path).enabled)


class IsQuotaStopTests(unittest.TestCase):
    def test_only_needs_human_provider_quota_is_a_candidate(self):
        self.assertTrue(req.is_quota_stop(make_record(stage="needs_human", code="PROVIDER_QUOTA")))
        for stage, code in (
            ("needs_human", "REVIEWER_NEEDS_HUMAN"), ("needs_human", "NO_CHANGES"),
            ("needs_human", "TASK_BLOCKED"), ("failed", "PROVIDER_QUOTA"), ("stopped", "PROVIDER_QUOTA"),
        ):
            with self.subTest(stage=stage, code=code):
                self.assertFalse(req.is_quota_stop(make_record(stage=stage, code=code)))


class RequiredFieldsTests(unittest.TestCase):
    def test_complete_record_passes(self):
        self.assertTrue(req.required_fields_present(make_record()))

    def test_missing_fields_fail(self):
        base = make_record()
        for key, bad in (("task", ""), ("repo", ""), ("main_agent", ""), ("review_agent", ""),
                          ("tests", []), ("criteria", [])):
            with self.subTest(key=key):
                record = dict(base)
                record[key] = bad
                self.assertFalse(req.required_fields_present(record))


class DelayCalculationTests(unittest.TestCase):
    def test_minute_format_parses_tokyo_time_and_computes_delay(self):
        now = datetime(2026, 3, 10, 7, 0, tzinfo=timezone.utc)  # 16:00 JST
        for clock, parsed, delay in (
            ("5:20pm", (17, 20, 540), 85),
            ("5:00pm", (17, 0, 540), 65),
            ("5:59pm", (17, 59, 540), 124),
        ):
            with self.subTest(clock=clock):
                message = f"resets {clock} (Asia/Tokyo)"
                self.assertEqual(req._parse_quota_reset(message), parsed)
                self.assertEqual(req.requeue_delay_minutes(message, now=now), delay)

    def test_twelve_am_and_pm_with_minutes(self):
        for clock, hour, now in (
            ("12:30am", 0, datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc)),
            ("12:30pm", 12, datetime(2026, 3, 10, 3, 0, tzinfo=timezone.utc)),
        ):
            with self.subTest(clock=clock):
                message = f"resets {clock} (Asia/Tokyo)"
                self.assertEqual(req._parse_quota_reset(message), (hour, 30, 540))
                self.assertEqual(req.requeue_delay_minutes(message, now=now), 35)

    def test_hour_only_parsing_is_unchanged(self):
        for clock, hour in (("5pm", 17), ("12am", 0), ("12pm", 12), ("1am", 1)):
            with self.subTest(clock=clock):
                self.assertEqual(req._parse_quota_reset(f"resets {clock} (Asia/Tokyo)"),
                                 (hour, 0, 540))

    def test_invalid_minute_formats_fall_back_to_sixty_minutes(self):
        for phrase in (
            "5:75pm (Asia/Tokyo)", "5:60pm (Asia/Tokyo)",
            "0:20pm (Asia/Tokyo)", "13:20pm (Asia/Tokyo)",
            "05:20pm (Asia/Tokyo)", "5:2pm (Asia/Tokyo)",
            "5:200pm (Asia/Tokyo)", "5:-1pm (Asia/Tokyo)",
            "5:20 (Asia/Tokyo)", "5:20xm (Asia/Tokyo)",
            "5.20pm (Asia/Tokyo)", "5:20pm Asia/Tokyo",
            "5:20pm (Asia/Shanghai)", "5:20pm (America/New_York)",
            "5:20pm (Asia/Tokyo) && echo unsafe",
            "5:20pm (Asia/Tokyo)\nextra text",
        ):
            with self.subTest(phrase=phrase):
                message = f"resets {phrase}"
                self.assertIsNone(req._parse_quota_reset(message))
                self.assertEqual(req.requeue_delay_minutes(message, now=NOW), 60)

    def test_minute_format_preserves_bounds_and_next_day_rollover(self):
        message = "resets 5:20pm (Asia/Tokyo)"
        for hour, minute, second, expected in (
            (8, 19, 59, 6),  # one second away, rounded up, plus the existing 5-minute buffer
            (2, 0, 0, 360),  # more than six hours away
            (8, 20, 0, 360),  # equal to reset: next day, as with hour-only times
            (8, 21, 0, 360),  # already past reset: next day
        ):
            with self.subTest(hour=hour, minute=minute, second=second):
                now = datetime(2026, 3, 10, hour, minute, second, tzinfo=timezone.utc)
                delay = req.requeue_delay_minutes(message, now=now)
                self.assertEqual(delay, expected)
                self.assertGreaterEqual(delay, 5)
                self.assertLessEqual(delay, 360)

    # ------------------------------------------------------------------ C3
    def test_strict_format_computes_minutes_past_the_reset_time_in_its_own_zone(self):
        # 07:00 UTC == 16:00 in Asia/Tokyo (UTC+9): the next 17:00 there is 1h away -- this would
        # be a very different number if the region's own offset were ignored (as it used to be).
        now_early = datetime(2026, 3, 10, 7, 0, 0, tzinfo=timezone.utc)
        message = "AI（Main）の利用枠・クレジットが不足しています。自動再試行・自動切替は行いません: resets 5pm (Asia/Tokyo)"
        minutes = req.requeue_delay_minutes(message, now=now_early)
        self.assertEqual(minutes, 65)  # 1h to 17:00 JST + 5min buffer

    def test_a_different_regions_own_offset_is_used_not_a_hardcoded_one(self):
        # 09:00 UTC == 17:00 in Asia/Shanghai (UTC+8): the next 18:00 there is also 1h away, via a
        # completely different offset than Asia/Tokyo's -- proof the region itself drives the math.
        now_early = datetime(2026, 3, 10, 9, 0, 0, tzinfo=timezone.utc)
        minutes = req.requeue_delay_minutes("resets 6pm (Asia/Shanghai)", now=now_early)
        self.assertEqual(minutes, 65)

    def test_already_past_today_rolls_to_tomorrow_and_clamps_to_max(self):
        later = NOW.replace(hour=17, minute=30)
        minutes = req.requeue_delay_minutes("resets 5pm (Asia/Tokyo)", now=later)
        self.assertEqual(minutes, req.MAX_DELAY_MINUTES)

    def test_unknown_region_falls_back_to_sixty_minutes(self):
        # A well-formed Area/City name is not enough on its own -- only a validated, DST-free
        # region from the known allowlist is ever actually resolved (仕様2: 未知の地域は60分).
        message = "resets 5pm (America/New_York)"
        self.assertEqual(req.requeue_delay_minutes(message, now=NOW), req.FALLBACK_DELAY_MINUTES)

    def test_path_like_text_falls_back_to_sixty_minutes(self):
        message = "C:\\Users\\reports\\resets 5pm (Asia/Tokyo)"
        self.assertEqual(req.requeue_delay_minutes(message, now=NOW), req.FALLBACK_DELAY_MINUTES)

    def test_command_like_text_falls_back_to_sixty_minutes(self):
        message = "resets 5pm (Asia/Tokyo) && rm -rf /"
        self.assertEqual(req.requeue_delay_minutes(message, now=NOW), req.FALLBACK_DELAY_MINUTES)

    def test_command_prefix_without_trailing_text_also_falls_back_to_sixty_minutes(self):
        # No trailing junk this time (unlike the "&& rm -rf /" case above) -- only a bare command
        # name immediately before "resets", with nothing else to catch it. A plain space is not by
        # itself a safe boundary (a shell command's own arguments are space-separated too), so this
        # must still be rejected by the lead-in check, not just the trailing one.
        message = "echo resets 5pm (Asia/Tokyo)"
        self.assertEqual(req.requeue_delay_minutes(message, now=NOW), req.FALLBACK_DELAY_MINUTES)

    def test_multiline_text_falls_back_to_sixty_minutes(self):
        message = "resets 5pm (Asia/Tokyo)\nsome more unrelated text"
        self.assertEqual(req.requeue_delay_minutes(message, now=NOW), req.FALLBACK_DELAY_MINUTES)

    def test_unrelated_text_falls_back_to_sixty_minutes(self):
        self.assertEqual(req.requeue_delay_minutes("rate limited, try again later", now=NOW),
                         req.FALLBACK_DELAY_MINUTES)

    def test_delay_is_always_within_bounds(self):
        for message in ("resets 5pm (Asia/Tokyo)", "no strict format here", "", "resets 12am (Asia/Tokyo)"):
            minutes = req.requeue_delay_minutes(message, now=NOW)
            self.assertGreaterEqual(minutes, req.MIN_DELAY_MINUTES)
            self.assertLessEqual(minutes, req.MAX_DELAY_MINUTES)


class DefaultStartRequeueTests(unittest.TestCase):
    # ------------------------------------------------------------------ C4
    def test_reuses_the_stopped_runs_own_values_unchanged(self):
        record = make_record(run_id="run-x", repo="C:/repos/myrepo", task="元のTask",
                              tests=("pytest -q", "pytest -q tests/x"), main_agent="codex",
                              review_agent="claude", criteria=({"id": "C1", "text": "条件A"},
                                                                {"id": "C2", "text": "条件B"}))
        captured = []

        def fake_start_run(request):
            captured.append(request)
            return Path("/fake/run-dir-new")

        from tools.ai_orchestrator import orchestrator as orch
        with mock.patch.object(orch, "start_run", side_effect=fake_start_run):
            result = req._default_start_requeue(record=record)
        self.assertEqual(result, Path("/fake/run-dir-new"))
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request.repo, "C:/repos/myrepo")
        self.assertEqual(request.task, "元のTask")
        self.assertEqual(request.tests, ["pytest -q", "pytest -q tests/x"])
        self.assertEqual(request.main_agent, "codex")
        self.assertEqual(request.review_agent, "claude")
        self.assertEqual(request.expected_branch, "main")
        self.assertIsNotNone(request.spec)
        self.assertEqual([dict(c) for c in request.spec.criteria],
                         [{"id": "C1", "text": "条件A"}, {"id": "C2", "text": "条件B"}])


class RunRequeueOnceTests(unittest.TestCase):
    def setUp(self):
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.log_dir = self.tmp / "run_log"
        self.addCleanup(self._tmp_ctx.cleanup)

    def _start_fn(self, calls, *, ok=True, run_id="run-new"):
        def fn(*, record):
            calls.append(record["run_id"])
            if not ok:
                raise RuntimeError("source repo has uncommitted changes")
            return Path(f"/fake/{run_id}")
        return fn

    def _run(self, **kwargs):
        kwargs.setdefault("log_dir", self.log_dir)
        # DCC Task WF-6b (reviewer finding 3): default to this test's own tmp-backed activity log
        # path rather than leaving it unset (None), which would fall back to the real
        # %LOCALAPPDATA% activity_log.log_path() default.
        kwargs.setdefault("activity_log_path", self.tmp / "activity.jsonl")
        return req.run_requeue_once(**kwargs)

    # ------------------------------------------------------------------ C1
    def test_global_switch_off_never_starts(self):
        calls = []
        outcome = self._run(
            state=req.RequeueState(), global_config=auto.AutoModeConfig(enabled=False),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [make_item()], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, [])
        self.assertEqual(outcome.status, req.STATUS_DISABLED)

    def test_own_switch_off_never_starts(self):
        calls = []
        outcome = self._run(
            state=req.RequeueState(), global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=False), now=NOW,
            list_runs_fn=lambda: [make_item()], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, [])
        self.assertEqual(outcome.status, req.STATUS_DISABLED)

    # ------------------------------------------------------------------ C2
    def test_only_provider_quota_is_scheduled_other_reasons_are_never_started(self):
        state = req.RequeueState()
        items = [
            make_item(run_id="r-quota", code="PROVIDER_QUOTA"),
            make_item(run_id="r-reviewer", stage="needs_human", code="REVIEWER_NEEDS_HUMAN"),
            make_item(run_id="r-nochange", stage="needs_human", code="NO_CHANGES"),
            make_item(run_id="r-blocked", stage="needs_human", code="TASK_BLOCKED"),
            make_item(run_id="r-failed", stage="failed", code="PROVIDER_ERROR"),
            make_item(run_id="r-stopped", stage="stopped", code="USER_SAFETY_STOP"),
        ]
        calls = []
        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: items, active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(set(state.pending), {"r-quota"})
        self.assertEqual(state.needs_human, set())

        outcome = self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=DUE_AFTER_FALLBACK,
            list_runs_fn=lambda: items, active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, ["r-quota"])
        self.assertEqual(outcome.status, req.STATUS_STARTED)

    # ------------------------------------------------------------------ C13
    def test_missing_required_fields_goes_straight_to_needs_human(self):
        state = req.RequeueState()
        item = make_item(run_id="r-missing")
        item["record"]["criteria"] = []
        calls = []
        later = NOW.replace(hour=20)
        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=later,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, [])
        self.assertIn("r-missing", state.needs_human)
        self.assertEqual(req.run_status_label("r-missing", state), req.NEEDS_HUMAN_TEXT)

    # ------------------------------------------------------------------ C8
    def test_busy_repo_waits_and_is_retried_once_free(self):
        state = req.RequeueState()
        item = make_item(run_id="r-busy")
        calls = []
        busy = {"value": True}

        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        due = DUE_AFTER_FALLBACK
        outcome = self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: (["running"] if busy["value"] else []),
            start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, [])
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)
        self.assertIn("r-busy", state.pending)

        busy["value"] = False
        outcome2 = self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: (["running"] if busy["value"] else []),
            start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, ["r-busy"])
        self.assertEqual(outcome2.status, req.STATUS_STARTED)

    # ------------------------------------------------------------------ C7
    def test_switching_off_mid_cycle_stops_the_actual_start(self):
        requeue_config_path = self.tmp / "requeue.json"
        req.save_requeue_config(req.RequeueConfig(enabled=True), path=requeue_config_path)
        state = req.RequeueState()
        item = make_item(run_id="r-toggle")
        calls = []

        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config_path=requeue_config_path, now=NOW,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        due = DUE_AFTER_FALLBACK

        def active_runs_fn_that_disables(_repo):
            req.set_enabled(False, path=requeue_config_path)
            return []

        outcome = self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config_path=requeue_config_path, now=due,
            list_runs_fn=lambda: [item], active_runs_fn=active_runs_fn_that_disables,
            start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, [])
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)
        self.assertIn("r-toggle", state.pending)

        req.set_enabled(True, path=requeue_config_path)
        outcome2 = self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config_path=requeue_config_path, now=due,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, ["r-toggle"])
        self.assertEqual(outcome2.status, req.STATUS_STARTED)

    # ------------------------------------------------------------------ C7 (global switch)
    def test_global_switch_off_mid_cycle_also_stops_the_actual_start(self):
        """The Reviewer's own finding: the earlier version of this test only ever toggled this
        feature's *own* switch mid-cycle, never the shared global one -- even though
        run_requeue_once's guard re-reads both. This exercises the shared global switch
        (reports_auto.AutoModeConfig) specifically, via global_config_path, the same way app.py's
        real background loop always supplies it."""
        global_config_path = self.tmp / "global.json"
        auto.save_auto_mode_config(auto.AutoModeConfig(enabled=True), path=global_config_path)
        state = req.RequeueState()
        item = make_item(run_id="r-global-toggle")
        calls = []

        self._run(
            state=state, global_config_path=global_config_path,
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        due = DUE_AFTER_FALLBACK

        def active_runs_fn_that_disables(_repo):
            auto.set_enabled(False, path=global_config_path)
            return []

        outcome = self._run(
            state=state, global_config_path=global_config_path,
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [item], active_runs_fn=active_runs_fn_that_disables,
            start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, [])
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)
        self.assertIn("r-global-toggle", state.pending)

        auto.set_enabled(True, path=global_config_path)
        outcome2 = self._run(
            state=state, global_config_path=global_config_path,
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        self.assertEqual(calls, ["r-global-toggle"])
        self.assertEqual(outcome2.status, req.STATUS_STARTED)

    # ------------------------------------------------------------------ C9
    def test_rejected_start_goes_straight_to_needs_human_and_is_never_retried(self):
        state = req.RequeueState()
        item = make_item(run_id="r-reject")
        calls = []
        due = DUE_AFTER_FALLBACK

        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=self._start_fn(calls),
        )
        outcome = self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._start_fn(calls, ok=False),
        )
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)
        self.assertEqual(calls, ["r-reject"])
        self.assertIn("r-reject", state.needs_human)
        self.assertNotIn("r-reject", state.pending)
        self.assertEqual(req.run_status_label("r-reject", state), req.NEEDS_HUMAN_TEXT)

        # Never retried even on a later cycle.
        later = due + timedelta(hours=3)
        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=later,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._start_fn(calls, ok=False),
        )
        self.assertEqual(calls, ["r-reject"])

    # ------------------------------------------------------------------ C9 (start rejection, not a race)
    def test_start_rejection_is_not_consumed_as_a_guard_abort(self):
        """Distinguishes a genuine rejection (C9: terminal, consumes the lineage attempt) from a
        guard abort / race (C7/C8: never terminal, stays pending) -- both raise while a start is
        attempted, but only the guard's own ActiveRunExists must leave the candidate pending."""
        state = req.RequeueState()
        item = make_item(run_id="r-reject-2")
        due = DUE_AFTER_FALLBACK
        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [], start_requeue_fn=lambda **_: None,
        )
        self._run(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
            start_requeue_fn=lambda *, record: (_ for _ in ()).throw(RuntimeError("source repo dirty")),
        )
        self.assertIn("r-reject-2", state.needs_human)
        self.assertEqual(state.lineage_attempts.get("r-reject-2"), 1)

    # ------------------------------------------------------------------ C5
    def test_lineage_is_capped_at_two_requeues_then_needs_human(self):
        state = req.RequeueState()
        calls = []
        # Every successor's own message deliberately does not match the strict quota-reset shape,
        # so each one gets the fixed FALLBACK_DELAY_MINUTES (60) wait -- a predictable schedule.
        runs = {"run-a": make_item(run_id="run-a")["record"]}

        def list_runs_fn():
            return [{"record": record} for record in runs.values()]

        def start_fn(*, record):
            calls.append(record["run_id"])
            new_id = f"run-{len(calls)}"
            runs[new_id] = make_record(run_id=new_id, message="rate limited, try again later")
            return Path(f"/fake/{new_id}")

        due = DUE_AFTER_FALLBACK  # run-a (60min wait) is due
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [], start_requeue_fn=start_fn)
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=due,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [], start_requeue_fn=start_fn)
        self.assertEqual(calls, ["run-a"])  # 1st requeue started ("run-1")

        due2 = due + timedelta(minutes=10)  # discovers + schedules run-1 (60min wait from here)
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=due2,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [], start_requeue_fn=start_fn)
        due3 = due2 + timedelta(minutes=65)  # run-1's 60min wait has elapsed: it is now due
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=due3,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [], start_requeue_fn=start_fn)
        self.assertEqual(calls, ["run-a", "run-1"])  # 2nd requeue started ("run-2")

        due4 = due3 + timedelta(minutes=15)  # discovers run-2; the lineage already used both
        outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),       # of its allowed requeues
                            requeue_config=req.RequeueConfig(enabled=True), now=due4,
                            list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [],
                            start_requeue_fn=start_fn)
        # "run-2" (the 2nd requeue's own result) also stopped with PROVIDER_QUOTA; a 3rd requeue
        # is beyond the 2-max, so it must go straight to needs_human, never a 3rd start.
        self.assertEqual(calls, ["run-a", "run-1"])
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)
        self.assertIn("run-2", state.needs_human)

    # ------------------------------------------------------------------ C6
    def test_daily_limit_reached_blocks_further_starts_and_shows_fixed_text(self):
        state = req.RequeueState()
        items = [make_item(run_id="r-1", repo="C:/repos/one"), make_item(run_id="r-2", repo="C:/repos/two")]
        calls = []
        due = DUE_AFTER_FALLBACK

        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True, daily_limit=1), now=NOW,
                 list_runs_fn=lambda: items, active_runs_fn=lambda repo: [],
                 start_requeue_fn=self._start_fn(calls))
        outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                            requeue_config=req.RequeueConfig(enabled=True, daily_limit=1), now=due,
                            list_runs_fn=lambda: items, active_runs_fn=lambda repo: [],
                            start_requeue_fn=self._start_fn(calls))
        self.assertEqual(len(calls), 1)  # only one of the two due candidates started
        self.assertEqual(outcome.status, req.STATUS_STARTED)
        notice = req.limit_notice(auto.AutoModeConfig(enabled=True), req.RequeueConfig(enabled=True, daily_limit=1),
                                  state, NOW.strftime("%Y-%m-%d"))
        self.assertEqual(notice, req.LIMIT_REACHED_TEXT)

        # On a new day the count resets and the still-pending candidate may start.
        next_day = due + timedelta(days=1)
        outcome2 = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                             requeue_config=req.RequeueConfig(enabled=True, daily_limit=1), now=next_day,
                             list_runs_fn=lambda: items, active_runs_fn=lambda repo: [],
                             start_requeue_fn=self._start_fn(calls))
        self.assertEqual(len(calls), 2)
        self.assertEqual(outcome2.status, req.STATUS_STARTED)

    # ------------------------------------------------------------------ C11
    def test_one_repos_waiting_candidate_never_blocks_another_repos_requeue(self):
        state = req.RequeueState()
        items = [make_item(run_id="r-busy-repo", repo="C:/repos/busy"),
                 make_item(run_id="r-free-repo", repo="C:/repos/free")]
        calls = []
        due = DUE_AFTER_FALLBACK

        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                 list_runs_fn=lambda: items, active_runs_fn=lambda repo: [],
                 start_requeue_fn=self._start_fn(calls))

        def active_runs_fn(repo):
            return ["running"] if repo.endswith("busy") else []

        outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                            requeue_config=req.RequeueConfig(enabled=True), now=due,
                            list_runs_fn=lambda: items, active_runs_fn=active_runs_fn,
                            start_requeue_fn=self._start_fn(calls))
        self.assertEqual(calls, ["r-free-repo"])
        self.assertEqual(outcome.status, req.STATUS_STARTED)
        self.assertIn("r-busy-repo", state.pending)

    # ------------------------------------------------------------------ C12
    def test_log_write_failure_never_affects_the_requeue_count(self):
        broken_log_dir = self.tmp / "not-a-directory"
        broken_log_dir.write_text("x", encoding="utf-8")  # a file where a directory is expected

        state = req.RequeueState()
        calls = []
        runs = {"run-a": make_item(run_id="run-a")["record"]}

        def list_runs_fn():
            return [{"record": record} for record in runs.values()]

        def start_fn(*, record):
            calls.append(record["run_id"])
            new_id = f"run-{len(calls)}"
            runs[new_id] = make_record(run_id=new_id, message="rate limited, try again later")
            return Path(f"/fake/{new_id}")

        due = DUE_AFTER_FALLBACK
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [],
                 start_requeue_fn=start_fn, log_dir=broken_log_dir)
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=due,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [],
                 start_requeue_fn=start_fn, log_dir=broken_log_dir)
        due2 = due + timedelta(minutes=10)
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=due2,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [],
                 start_requeue_fn=start_fn, log_dir=broken_log_dir)
        due3 = due2 + timedelta(minutes=65)
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=due3,
                 list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [],
                 start_requeue_fn=start_fn, log_dir=broken_log_dir)
        self.assertEqual(calls, ["run-a", "run-1"])  # the log writes silently failed throughout

        due4 = due3 + timedelta(minutes=15)
        outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                            requeue_config=req.RequeueConfig(enabled=True), now=due4,
                            list_runs_fn=list_runs_fn, active_runs_fn=lambda repo: [],
                            start_requeue_fn=start_fn, log_dir=broken_log_dir)
        self.assertEqual(calls, ["run-a", "run-1"])  # still capped at 2, despite every log write failing
        self.assertIn("run-2", state.needs_human)
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)

    # ------------------------------------------------------------------ C12 (persisted daily count)
    def test_daily_count_save_failure_still_counts_and_keeps_the_limit_safe(self):
        """Same C12 guarantee, but for the *persisted* daily count (仕様3/再起動) rather than the
        run log: when daily_count_path's own write fails, record_daily_attempt's in-memory bump
        must still happen, so the limit is never exceeded even though nothing was saved."""
        broken_dir = self.tmp / "not-a-directory-2"
        broken_dir.write_text("x", encoding="utf-8")
        daily_count_path = broken_dir / "daily_count.json"  # every write under this fails
        state = req.RequeueState(daily_count_path=daily_count_path)
        today = NOW.strftime("%Y-%m-%d")
        state.record_daily_attempt(today)
        state.record_daily_attempt(today)
        self.assertEqual(state.daily_count(today), 2)  # counted despite every save failing

        config = req.RequeueConfig(enabled=True, daily_limit=2)
        self.assertEqual(req.limit_notice(auto.AutoModeConfig(enabled=True), config, state, today),
                         req.LIMIT_REACHED_TEXT)

    # ------------------------------------------------------------------ C10
    def test_approval_push_build_update_are_never_called(self):
        state = req.RequeueState()
        item = make_item(run_id="r-safe")
        calls = []
        due = DUE_AFTER_FALLBACK
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                 list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                 start_requeue_fn=self._start_fn(calls))
        with mock.patch("scripts.dev_control_center.candidate.approve") as approve, \
             mock.patch("scripts.dev_control_center.candidate.push") as push, \
             mock.patch("scripts.dev_control_center.candidate.run_dev") as run_dev, \
             mock.patch("scripts.dev_control_center.release_update.plan") as release_plan:
            self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                     requeue_config=req.RequeueConfig(enabled=True), now=due,
                     list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                     start_requeue_fn=self._start_fn(calls))
            approve.assert_not_called()
            push.assert_not_called()
            run_dev.assert_not_called()
            release_plan.assert_not_called()
        self.assertEqual(calls, ["r-safe"])

    # ------------------------------------------------------------------ stop event
    def test_stop_event_set_mid_cycle_never_starts(self):
        state = req.RequeueState()
        item = make_item(run_id="r-stop")
        calls = []
        stop_event = threading.Event()
        due = DUE_AFTER_FALLBACK
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                 requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                 list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                 start_requeue_fn=self._start_fn(calls), stop_event=stop_event)
        stop_event.set()
        outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                            requeue_config=req.RequeueConfig(enabled=True), now=due,
                            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                            start_requeue_fn=self._start_fn(calls), stop_event=stop_event)
        self.assertEqual(calls, [])
        self.assertEqual(outcome.status, req.STATUS_STOPPED)

    # ------------------------------------------------------------------ sanity
    def test_nothing_to_do_when_no_runs_exist(self):
        outcome = self._run(
            state=req.RequeueState(), global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [], active_runs_fn=lambda repo: [], start_requeue_fn=lambda **_: None,
        )
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)


class ActivityLogTests(unittest.TestCase):
    """DCC Task WF-6b 仕様2: 自動再実行の予約・開始・上限・対象外の記録点だけを検証する。
    実際の画面・AI・Orchestrator・外部通信は使わず、保存先は一時フォルダに限る。target_id は
    activity_log.TARGET_RUN の形式 (\\d{8}-\\d{6}-\\d{6}) に合わせる -- 形式が違うと
    activity_log.append() 自体が ActivityLogError で拒否し、_log_activity がそれを握りつぶして
    何も記録されないため、ここでの検証が意味を持つには run_id 自体をその形式にする必要がある。"""

    def setUp(self):
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.log_dir = self.tmp / "run_log"
        self.activity_path = self.tmp / "activity.jsonl"
        self.addCleanup(self._tmp_ctx.cleanup)

    def _start_fn(self, calls, *, ok=True, run_id="20260310-170000-000099"):
        def fn(*, record):
            calls.append(record["run_id"])
            if not ok:
                raise RuntimeError("source repo has uncommitted changes")
            return Path(f"/fake/{run_id}")
        return fn

    def _run(self, **kwargs):
        kwargs.setdefault("log_dir", self.log_dir)
        kwargs.setdefault("activity_log_path", self.activity_path)
        return req.run_requeue_once(**kwargs)

    def _entries(self):
        return activity_log.read_recent(path=self.activity_path)

    def test_pending_schedule_is_recorded(self):
        run_id = "20260310-165000-000001"
        item = make_item(run_id=run_id)
        self._run(state=req.RequeueState(), global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        entries = self._entries()
        waiting = [e for e in entries if e.action == activity_log.ACTION_WAITING]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0].role, activity_log.ROLE_AUTO_RETRY)
        self.assertEqual(waiting[0].target_type, activity_log.TARGET_RUN)
        self.assertEqual(waiting[0].target_id, run_id)

    def test_start_is_recorded_with_the_new_run_id(self):
        run_id = "20260310-165000-000002"
        new_run_id = "20260310-170000-000099"
        item = make_item(run_id=run_id)
        state = req.RequeueState()
        calls = []
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn(calls, run_id=new_run_id))
        outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                            requeue_config=req.RequeueConfig(enabled=True), now=DUE_AFTER_FALLBACK,
                            list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                            start_requeue_fn=self._start_fn(calls, run_id=new_run_id))
        self.assertEqual(outcome.status, req.STATUS_STARTED)
        entries = self._entries()
        starts = [e for e in entries if e.action == activity_log.ACTION_START]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0].role, activity_log.ROLE_AUTO_RETRY)
        self.assertEqual(starts[0].target_type, activity_log.TARGET_RUN)
        self.assertEqual(starts[0].target_id, new_run_id)

    def test_missing_required_fields_exclusion_is_recorded(self):
        run_id = "20260310-165000-000003"
        item = make_item(run_id=run_id)
        item["record"]["criteria"] = []
        self._run(state=req.RequeueState(), global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        entries = self._entries()
        excluded = [e for e in entries if e.action == activity_log.ACTION_EXCLUDED]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].target_type, activity_log.TARGET_RUN)
        self.assertEqual(excluded[0].target_id, run_id)

    def test_lineage_limit_exclusion_is_recorded(self):
        run_id = "20260310-165000-000004"
        item = make_item(run_id=run_id)
        state = req.RequeueState()
        state.lineage_attempts[run_id] = req.MAX_LINEAGE_ATTEMPTS
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        entries = self._entries()
        excluded = [e for e in entries if e.action == activity_log.ACTION_EXCLUDED]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].target_id, run_id)

    def test_rejected_start_exclusion_is_recorded(self):
        run_id = "20260310-165000-000005"
        item = make_item(run_id=run_id)
        state = req.RequeueState()
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=DUE_AFTER_FALLBACK,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([], ok=False))
        entries = self._entries()
        excluded = [e for e in entries if e.action == activity_log.ACTION_EXCLUDED
                    and e.target_id == run_id]
        self.assertEqual(len(excluded), 1)

    def test_daily_limit_reached_is_recorded(self):
        items = [make_item(run_id="20260310-165000-000006", repo="C:/repos/one"),
                 make_item(run_id="20260310-165000-000007", repo="C:/repos/two")]
        state = req.RequeueState()
        due = DUE_AFTER_FALLBACK
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True, daily_limit=1), now=NOW,
                  list_runs_fn=lambda: items, active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True, daily_limit=1), now=due,
                  list_runs_fn=lambda: items, active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        entries = self._entries()
        self.assertTrue(any(e.action == activity_log.ACTION_LIMIT for e in entries))

    def test_entry_has_only_fixed_words_id_and_timestamp(self):
        run_id = "20260310-165000-000008"
        item = make_item(run_id=run_id, task="Task本文の秘密", repo="C:/secret/repo")
        self._run(state=req.RequeueState(), global_config=auto.AutoModeConfig(enabled=True),
                  requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                  list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                  start_requeue_fn=self._start_fn([]))
        raw = self.activity_path.read_text(encoding="utf-8")
        for banned in ("C:/secret", "Task本文の秘密", "Traceback"):
            self.assertNotIn(banned, raw)

    def test_activity_log_write_failure_never_changes_the_outcome(self):
        run_id = "20260310-165000-000009"
        new_run_id = "20260310-170000-000098"
        item = make_item(run_id=run_id)
        state = req.RequeueState()
        calls = []

        def broken_append(**kwargs):
            raise activity_log.ActivityLogError("boom")

        with mock.patch.object(activity_log, "append", side_effect=broken_append):
            self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                      requeue_config=req.RequeueConfig(enabled=True), now=NOW,
                      list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                      start_requeue_fn=self._start_fn(calls, run_id=new_run_id))
            outcome = self._run(state=state, global_config=auto.AutoModeConfig(enabled=True),
                                requeue_config=req.RequeueConfig(enabled=True), now=DUE_AFTER_FALLBACK,
                                list_runs_fn=lambda: [item], active_runs_fn=lambda repo: [],
                                start_requeue_fn=self._start_fn(calls, run_id=new_run_id))
        self.assertEqual(outcome.status, req.STATUS_STARTED)
        self.assertEqual(calls, [run_id])
        self.assertFalse(self.activity_path.exists())


class RestartBehaviorTests(unittest.TestCase):
    """DCC Task 19b, 仕様3/仕様6, Reviewer findings 1 & 2: nothing about a stopped run or the
    day's own count may survive a DCC restart in a way that lets this process auto-requeue a run
    it never actually saw stop, or exceed the daily limit a previous session already spent."""

    def setUp(self):
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.addCleanup(self._tmp_ctx.cleanup)

    # ------------------------------------------------------------------ finding 1
    def test_runs_already_stopped_before_startup_are_excluded_forever(self):
        pre_existing = make_item(run_id="run-already-stopped-before-dcc-started")
        state = req.RequeueState()
        req.seed_startup_exclusions(state, list_runs_fn=lambda: [pre_existing])

        calls = []
        outcome = req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [pre_existing], active_runs_fn=lambda repo: [],
            start_requeue_fn=lambda *, record: Path("/fake/should-never-be-called"),
            log_dir=self.tmp / "log", activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertEqual(calls, [])
        self.assertNotIn("run-already-stopped-before-dcc-started", state.pending)
        self.assertNotIn("run-already-stopped-before-dcc-started", state.needs_human)
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)

        # Even many cycles later, still never scheduled -- not even once the switches are on and
        # the run is still sitting there unchanged.
        later = NOW + timedelta(hours=5)
        req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=later,
            list_runs_fn=lambda: [pre_existing], active_runs_fn=lambda repo: [],
            start_requeue_fn=lambda *, record: Path("/fake/should-never-be-called"),
            log_dir=self.tmp / "log", activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertNotIn("run-already-stopped-before-dcc-started", state.pending)
        self.assertNotIn("run-already-stopped-before-dcc-started", state.needs_human)

    def test_exclusion_survives_starting_with_the_switch_off_then_turning_it_on(self):
        """仕様6: seeding must not depend on either switch -- a DCC that starts with the feature
        OFF and is only turned ON later must still have excluded the pre-existing stopped run."""
        pre_existing = make_item(run_id="run-old")
        state = req.RequeueState()
        # Seeded while the feature is (implicitly) OFF -- seed_startup_exclusions itself never
        # reads either switch, matching app.py calling it unconditionally at startup.
        req.seed_startup_exclusions(state, list_runs_fn=lambda: [pre_existing])

        calls = []
        req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,  # now ON
            list_runs_fn=lambda: [pre_existing], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._never(calls), log_dir=self.tmp / "log",
            activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertEqual(calls, [])
        self.assertNotIn("run-old", state.pending)

    def test_a_newly_stopped_run_and_a_requeue_successor_are_not_excluded(self):
        """Only run_ids visible to the one seed_startup_exclusions snapshot are ever excluded: a
        run that stops *after* DCC started, and any successor a requeue itself starts, must be
        scheduled normally."""
        state = req.RequeueState()
        req.seed_startup_exclusions(state, list_runs_fn=lambda: [])  # nothing stopped yet at startup

        new_item = make_item(run_id="run-stopped-after-startup")
        calls = []
        req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=lambda: [new_item], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._never(calls), log_dir=self.tmp / "log",
            activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertIn("run-stopped-after-startup", state.pending)

        due = DUE_AFTER_FALLBACK

        def start_fn(*, record):
            calls.append(record["run_id"])
            return Path("/fake/run-successor")

        outcome = req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=due,
            list_runs_fn=lambda: [new_item], active_runs_fn=lambda repo: [],
            start_requeue_fn=start_fn, log_dir=self.tmp / "log",
            activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertEqual(calls, ["run-stopped-after-startup"])
        self.assertEqual(outcome.status, req.STATUS_STARTED)

    @staticmethod
    def _never(calls):
        def fn(*, record):
            calls.append(record["run_id"])
            return Path("/fake/should-never-start")
        return fn

    # ------------------------------------------------------------------ finding 2
    def test_daily_limit_persists_across_a_simulated_same_day_restart(self):
        daily_count_path = self.tmp / "daily_count.json"
        today = NOW.strftime("%Y-%m-%d")

        session1 = req.RequeueState(daily_count_path=daily_count_path)
        session1.record_daily_attempt(today)
        self.assertEqual(session1.daily_count(today), 1)

        # A brand-new RequeueState -- simulating a DCC process restarted later the same day --
        # must inherit the count already spent, not start back at 0.
        session2 = req.RequeueState(daily_count_path=daily_count_path)
        self.assertEqual(session2.daily_count(today), 1)

        config = req.RequeueConfig(enabled=True, daily_limit=1)
        self.assertEqual(req.limit_notice(auto.AutoModeConfig(enabled=True), config, session2, today),
                         req.LIMIT_REACHED_TEXT)

        calls = []
        outcome = req.run_requeue_once(
            state=session2, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=config, now=DUE_AFTER_FALLBACK,
            list_runs_fn=lambda: [make_item(run_id="run-after-restart")], active_runs_fn=lambda repo: [],
            start_requeue_fn=self._never(calls), log_dir=self.tmp / "log",
            activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertEqual(calls, [])  # today's single slot was already spent in session1
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)
        self.assertIn("run-after-restart", session2.pending)  # stays pending, retried once the day rolls over

    def test_daily_count_resets_on_a_new_calendar_day_even_after_a_restart(self):
        daily_count_path = self.tmp / "daily_count.json"
        session1 = req.RequeueState(daily_count_path=daily_count_path)
        session1.record_daily_attempt("2026-03-10")
        session1.record_daily_attempt("2026-03-10")

        session2 = req.RequeueState(daily_count_path=daily_count_path)
        self.assertEqual(session2.daily_count("2026-03-10"), 2)
        self.assertEqual(session2.daily_count("2026-03-11"), 0)  # a new day, never carried over

    # ------------------------------------------------------------------ Reviewer finding 1 (repair)
    def test_restart_count_plus_a_failed_save_still_blocks_a_third_requeue_today(self):
        """Reviewer finding 1: record_daily_attempt used to bump a from-this-process-only counter
        (starting at 0) instead of the day's already-persisted total, so a fresh RequeueState
        created after a same-day restart whose own first save then failed would report a count of
        1 instead of 2 -- silently letting the daily_limit=2 be exceeded. Fixed: the new total is
        always computed from daily_count(today) (memory-vs-disk max) first, so it is correct even
        when the save of that very total fails."""
        daily_count_path = self.tmp / "daily_count.json"
        today = NOW.strftime("%Y-%m-%d")
        req._write_json_atomic(daily_count_path, {"date": today, "count": 1})  # 1 already spent pre-restart

        state = req.RequeueState(daily_count_path=daily_count_path)
        with mock.patch.object(req, "_write_json_atomic", side_effect=OSError("disk full")):
            total = state.record_daily_attempt(today)
        self.assertEqual(total, 2)
        self.assertEqual(state.daily_count(today), 2)

        config = req.RequeueConfig(enabled=True, daily_limit=2)
        self.assertEqual(req.limit_notice(auto.AutoModeConfig(enabled=True), config, state, today),
                         req.LIMIT_REACHED_TEXT)

    def test_restart_count_integration_only_one_of_two_due_runs_starts_despite_every_save_failing(self):
        """Same finding, exercised through run_requeue_once: with 1 requeue already spent before
        the restart and daily_limit=2, two runs in two different (so never repo-deduped)
        repositories become due in the same post-restart session -- only one may start, even
        though every save in this session fails."""
        daily_count_path = self.tmp / "daily_count.json"
        today = NOW.strftime("%Y-%m-%d")
        req._write_json_atomic(daily_count_path, {"date": today, "count": 1})

        state = req.RequeueState(daily_count_path=daily_count_path)
        item_a = make_item(run_id="run-a-restart", repo="C:/repos/app-a")
        item_b = make_item(run_id="run-b-restart", repo="C:/repos/app-b")
        calls = []

        def start_fn(*, record):
            calls.append(record["run_id"])
            return Path(f"/fake/{record['run_id']}-new")

        with mock.patch.object(req, "_write_json_atomic", side_effect=OSError("disk full")):
            req.run_requeue_once(
                state=state, global_config=auto.AutoModeConfig(enabled=True),
                requeue_config=req.RequeueConfig(enabled=True, daily_limit=2), now=NOW,
                list_runs_fn=lambda: [item_a, item_b], active_runs_fn=lambda repo: [],
                start_requeue_fn=start_fn, log_dir=self.tmp / "log",
                activity_log_path=self.tmp / "activity.jsonl",
            )
            req.run_requeue_once(
                state=state, global_config=auto.AutoModeConfig(enabled=True),
                requeue_config=req.RequeueConfig(enabled=True, daily_limit=2), now=DUE_AFTER_FALLBACK,
                list_runs_fn=lambda: [item_a, item_b], active_runs_fn=lambda repo: [],
                start_requeue_fn=start_fn, log_dir=self.tmp / "log",
                activity_log_path=self.tmp / "activity.jsonl",
            )
        self.assertEqual(len(calls), 1)  # 1 (pre-restart) + 1 == daily_limit 2 -- the other stays pending
        self.assertEqual(state.daily_count(today), 2)

    # ------------------------------------------------------------------ Reviewer finding 2 (repair)
    def test_a_failed_startup_list_fetch_disables_discovery_until_a_later_fetch_succeeds(self):
        """Reviewer finding 2: seed_startup_exclusions's own list_runs_fn raising used to leave
        `runs = []`, so a run that was already PROVIDER_QUOTA-stopped before DCC started would
        simply never be excluded once the list call started working again -- discovery would see
        it as brand-new and schedule it. Fixed: a failed seeding leaves state.startup_seeded False,
        and run_requeue_once refuses discovery/starting every cycle until a later seeding attempt
        (made with that cycle's own list_runs_fn) actually succeeds."""
        pre_existing = make_item(run_id="run-old-quota")
        state = req.RequeueState()
        calls = {"n": 0}

        def flaky_list_runs():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient failure reading the run list")
            return [pre_existing]

        ok = req.seed_startup_exclusions(state, list_runs_fn=flaky_list_runs)  # 1st call: fails
        self.assertFalse(ok)
        self.assertFalse(state.startup_seeded)

        start_calls = []
        outcome = req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=NOW,
            list_runs_fn=flaky_list_runs, active_runs_fn=lambda repo: [],
            start_requeue_fn=self._never(start_calls), log_dir=self.tmp / "log",
            activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertTrue(state.startup_seeded)  # the retry (this cycle's 2nd call) succeeded
        self.assertEqual(start_calls, [])
        self.assertNotIn("run-old-quota", state.pending)
        self.assertNotIn("run-old-quota", state.needs_human)
        self.assertEqual(outcome.status, req.STATUS_NOTHING_TO_DO)

        # And it stays excluded on every later cycle too, same as a successful startup seeding.
        later = NOW + timedelta(hours=5)
        req.run_requeue_once(
            state=state, global_config=auto.AutoModeConfig(enabled=True),
            requeue_config=req.RequeueConfig(enabled=True), now=later,
            list_runs_fn=flaky_list_runs, active_runs_fn=lambda repo: [],
            start_requeue_fn=self._never(start_calls), log_dir=self.tmp / "log",
            activity_log_path=self.tmp / "activity.jsonl",
        )
        self.assertEqual(start_calls, [])
        self.assertNotIn("run-old-quota", state.pending)


class DisplayLabelTests(unittest.TestCase):
    def test_waiting_label_shows_computed_minutes_only(self):
        state = req.RequeueState()
        state.pending["r-1"] = req._Pending(scheduled_at=NOW.replace(hour=17, minute=5), lineage_root="r-1", attempt=1)
        label = req.run_status_label("r-1", state, now=NOW)
        self.assertEqual(label, "枠の回復待ち（再実行まで約15分）")

    def test_needs_human_label(self):
        state = req.RequeueState()
        state.needs_human.add("r-2")
        self.assertEqual(req.run_status_label("r-2", state, now=NOW), req.NEEDS_HUMAN_TEXT)

    def test_unknown_run_has_no_label(self):
        self.assertEqual(req.run_status_label("r-unknown", req.RequeueState(), now=NOW), "")

    def test_limit_notice_requires_both_switches_on(self):
        state = req.RequeueState()
        state.record_daily_attempt("2026-03-10")
        config = req.RequeueConfig(enabled=True, daily_limit=1)
        self.assertEqual(req.limit_notice(auto.AutoModeConfig(enabled=True), config, state, "2026-03-10"),
                         req.LIMIT_REACHED_TEXT)
        self.assertEqual(req.limit_notice(auto.AutoModeConfig(enabled=False), config, state, "2026-03-10"), "")
        self.assertEqual(req.limit_notice(auto.AutoModeConfig(enabled=True),
                                          req.RequeueConfig(enabled=False, daily_limit=1), state, "2026-03-10"), "")


if __name__ == "__main__":
    unittest.main()
