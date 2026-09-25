"""Provider adapters (parsing, error classes) and usage adapters (account vs context, last known)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.ai_orchestrator import providers as p
from tools.ai_orchestrator import usage as u
from tools.ai_orchestrator.common import CommandResult

SESSION = "cca665c9-155d-485d-8d47-9f73d026860a"


def jl(*items) -> str:
    return "\n".join(json.dumps(i) for i in items) + "\n"


def claude_stream(*, result="OK", is_error=False, subtype="success", rate=True, terminal="completed"):
    items = [
        {"type": "system", "subtype": "init", "model": "claude-sonnet-5", "session_id": SESSION},
        {"type": "assistant", "parent_tool_use_id": None, "message": {
            "model": "claude-sonnet-5", "content": [{"type": "text", "text": "OK"}],
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 5989, "cache_read_input_tokens": 3397,
                      "output_tokens": 4}}},
    ]
    if rate:
        items.append({"type": "rate_limit_event", "rate_limit_info": {
            "status": "allowed", "resetsAt": 1790326800, "rateLimitType": "five_hour",
            "unifiedWindows": {"five_hour": {"utilization": 0.06, "resetsAt": 1790326800},
                               "seven_day": {"utilization": 0.01, "resetsAt": 1790866800}}}})
    items.append({"type": "result", "subtype": subtype, "is_error": is_error, "result": result,
                  "session_id": SESSION, "terminal_reason": terminal,
                  "modelUsage": {"claude-sonnet-5": {"contextWindow": 1000000}}})
    return jl(*items)


CODEX_OK = jl(
    {"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "done"}},
    {"type": "turn.completed", "usage": {"input_tokens": 15921, "cached_input_tokens": 7680, "output_tokens": 5}},
)

CODEX_RATE_RESPONSE = {  # shape recorded from `codex app-server` account/rateLimits/read
    "ordinaryUsageAllowed": True,
    "rateLimits": {"limitId": "codex", "primary": {"usedPercent": 73, "windowDurationMins": 300, "resetsAt": 1790323318},
                   "secondary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": 1790809811},
                   "credits": {"hasCredits": False, "unlimited": False, "balance": "0"}, "planType": "plus"},
}


class ClaudeParseTests(unittest.TestCase):
    def parse(self, stdout, rc=0, stderr=""):
        return p.ClaudeProvider.parse("main", CommandResult(("claude",), rc, stdout, stderr))

    def test_success_extracts_text_session_rate_limit_and_context(self):
        r = self.parse(claude_stream())
        self.assertTrue(r.ok)
        self.assertEqual((r.text, r.session_id), ("OK", SESSION))
        self.assertEqual(r.rate_limit["unifiedWindows"]["five_hour"]["utilization"], 0.06)
        self.assertEqual(r.context, {"used_tokens": 2 + 5989 + 3397 + 4, "window_tokens": 1000000, "model": "claude-sonnet-5"})

    def test_oauth_refresh_race_is_transient_not_auth(self):
        r = self.parse(claude_stream(is_error=True, rate=False, terminal="api_error", result=
                       "Failed to refresh OAuth token: another Claude Code process is refreshing it or exited mid-refresh."), rc=1)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, p.ERR_TRANSIENT)

    def test_quota_variants(self):
        for text in ("You've hit your limit · resets 3pm", "Credit balance is too low", "usage limit reached",
                     "out of extra usage"):
            r = self.parse(claude_stream(is_error=True, rate=False, result=text), rc=1)
            self.assertEqual(r.error_kind, p.ERR_QUOTA, text)

    def test_max_turns_is_flagged(self):
        r = self.parse(claude_stream(is_error=True, subtype="error_max_turns", result=""), rc=1)
        self.assertTrue(r.max_turns)

    def test_no_result_event_is_a_protocol_error(self):
        r = self.parse("garbage\n", rc=0)
        self.assertEqual((r.ok, r.error_kind), (False, p.ERR_PROTOCOL))

    def test_success_prose_mentioning_limits_is_not_an_error(self):
        r = self.parse(claude_stream(result="I handled the rate limit and usage limit cases in the code."))
        self.assertTrue(r.ok)

    def test_review_command_is_read_only(self):
        command = p.ClaudeProvider()._review_command()
        self.assertIn("Read,Glob,Grep", command)
        self.assertNotIn("acceptEdits", command)
        self.assertNotIn("Bash", " ".join(command))

    def test_main_command_never_allows_git_writes(self):
        allowed = " ".join(p.CLAUDE_ALLOWED_BASH_TOOLS)
        for word in ("git commit", "git push", "git add", "git reset", "git checkout"):
            self.assertNotIn(word, allowed)


class CodexParseTests(unittest.TestCase):
    def parse(self, stdout, rc=0, stderr=""):
        return p.CodexProvider.parse("review", CommandResult(("codex",), rc, stdout, stderr))

    def test_success(self):
        r = self.parse(CODEX_OK)
        self.assertTrue(r.ok)
        self.assertEqual(r.text, "done")
        self.assertEqual(r.context["used_tokens"], 15926)

    def test_reconnect_error_events_do_not_fail_a_completed_turn(self):
        r = self.parse(jl({"type": "error", "message": "Reconnecting... 1/5"}) + CODEX_OK)
        self.assertTrue(r.ok)

    def test_quota_failure(self):
        out = jl({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again later."}})
        r = self.parse(out, rc=1)
        self.assertEqual(r.error_kind, p.ERR_QUOTA)

    def test_nonzero_exit_without_events_is_a_protocol_error(self):
        r = self.parse("", rc=1, stderr="boom")
        self.assertFalse(r.ok)

    def test_write_capable_only_for_main(self):
        provider = p.CodexProvider()
        main = provider._command(Path("w"), "workspace-write")
        review = provider._command(Path("w"), "read-only")
        self.assertIn("workspace-write", main)
        self.assertIn("read-only", review)


class RoleTests(unittest.TestCase):
    def test_defaults_are_claude_main_codex_reviewer(self):
        self.assertEqual((p.DEFAULT_MAIN_AGENT, p.DEFAULT_REVIEW_AGENT), ("claude", "codex"))

    def test_both_directions_are_valid_and_same_provider_is_refused(self):
        p.validate_roles("claude", "codex")
        p.validate_roles("codex", "claude")
        with self.assertRaises(Exception) as ctx:
            p.validate_roles("claude", "claude")
        self.assertEqual(ctx.exception.code, "SAME_PROVIDER_ROLES")
        p.validate_roles("claude", "claude", allow_same=True)

    def test_unknown_provider_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            p.validate_roles("claude", "gemini")
        self.assertEqual(ctx.exception.code, "UNKNOWN_PROVIDER")


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class UsageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.clock = Clock()

    def make(self, name):
        return u.make_usage_provider(name, directory=self.dir, clock=self.clock)

    def rows(self, provider):
        return dict(u.describe(provider.load(), now=self.clock()))

    def test_claude_usage_is_shown_from_the_providers_own_report(self):
        provider = self.make("claude")
        provider.ingest(p.ClaudeProvider.parse("main", CommandResult(("c",), 0, claude_stream(), "")))
        rows = self.rows(provider)
        self.assertEqual(rows["Usage 5時間枠"], "94% remaining")
        self.assertEqual(rows["Usage 週間枠"], "99% remaining")
        self.assertIn("Reset 5時間枠", rows)
        self.assertEqual(rows["Credits"], u.UNAVAILABLE)   # Claude offers no credit balance: not invented
        self.assertIn("% remaining", rows["Context"])

    def test_codex_usage_is_shown(self):
        provider = self.make("codex")
        provider.record_account(u.CodexUsageProvider.account_from_response(CODEX_RATE_RESPONSE))
        rows = self.rows(provider)
        self.assertEqual(rows["Usage 5時間枠"], "27% remaining")
        self.assertEqual(rows["Usage 7日枠"], "60% remaining")
        self.assertEqual(rows["Credits"], "0")
        self.assertEqual(rows["Plan"], "plus")

    def test_nothing_known_is_unavailable_never_a_guess(self):
        for name in ("claude", "codex"):
            rows = self.rows(self.make(name))
            self.assertTrue(rows["Usage"].startswith(u.UNAVAILABLE), rows)
            self.assertTrue(rows["Context"].startswith(u.UNAVAILABLE), rows)
            self.assertNotIn("%", rows["Usage"] + rows["Context"])

    def test_claude_without_rate_limit_event_shows_no_account_usage(self):
        provider = self.make("claude")
        provider.ingest(p.ClaudeProvider.parse("main", CommandResult(("c",), 0, claude_stream(rate=False), "")))
        rows = self.rows(provider)
        self.assertTrue(rows["Usage"].startswith(u.UNAVAILABLE))
        self.assertIn("remaining", rows["Context"])

    def test_context_and_account_are_never_mixed(self):
        provider = self.make("codex")
        provider.record_context({"used_tokens": 50_000, "window_tokens": 250_000, "model": "m"})
        data = provider.load()
        self.assertIsNone(data["account"])
        rows = dict(u.describe(data, now=self.clock()))
        self.assertEqual(rows["Context"].split(" ")[0], "80%")
        self.assertTrue(rows["Usage"].startswith(u.UNAVAILABLE))  # context does not fill the account rows
        provider.record_account(u.CodexUsageProvider.account_from_response(CODEX_RATE_RESPONSE))
        data = provider.load()
        self.assertEqual(data["context"]["used_tokens"], 50_000)
        self.assertNotIn("used_tokens", data["account"])

    def test_old_values_are_marked_last_known(self):
        provider = self.make("codex")
        provider.record_account(u.CodexUsageProvider.account_from_response(CODEX_RATE_RESPONSE))
        self.assertNotIn("last known", self.rows(provider)["Usage 5時間枠"])
        self.clock.now += 3600
        self.assertIn("last known", self.rows(provider)["Usage 5時間枠"])

    def test_refresh_failure_keeps_last_known_and_never_raises(self):
        provider = self.make("codex")
        provider.record_account(u.CodexUsageProvider.account_from_response(CODEX_RATE_RESPONSE))
        self.clock.now += 3600

        def broken():
            raise RuntimeError("app-server unavailable")

        provider._probe = broken
        data = provider.refresh(force=True)
        rows = dict(u.describe(data, now=self.clock()))
        self.assertIn("last known", rows["Usage 5時間枠"])
        self.assertIn("失敗", rows["Usage更新"])

    def test_probing_is_throttled(self):
        provider = self.make("claude")
        calls = []
        provider._probe = lambda: calls.append(1)
        provider.refresh(force=True)
        provider.refresh(force=True)      # debounced
        provider.refresh()                # inside the minimum interval
        self.assertEqual(len(calls), 1)
        self.clock.now += u.MIN_PROBE_INTERVAL["claude"] + 1
        provider.refresh()
        self.assertEqual(len(calls), 2)

    def test_low_remaining_warning_only_from_reported_values(self):
        provider = self.make("codex")
        self.assertEqual(u.warnings(provider.load(), "Main AI"), [])
        provider.record_account(u.CodexUsageProvider.account_from_response(CODEX_RATE_RESPONSE))
        self.assertEqual(u.warnings(provider.load(), "Main AI"), [])
        low = json.loads(json.dumps(CODEX_RATE_RESPONSE))
        low["rateLimits"]["primary"]["usedPercent"] = 92
        provider.record_account(u.CodexUsageProvider.account_from_response(low))
        text = u.warnings(provider.load(), "Main AI")[0]
        self.assertIn("長時間Taskを完走できない可能性", text)

    def test_cache_holds_no_secrets(self):
        provider = self.make("codex")
        provider.record_account(u.CodexUsageProvider.account_from_response(
            {**CODEX_RATE_RESPONSE, "accountId": "acct-secret", "rateLimitResetCredits": {"credits": [{"id": "tok"}]}}))
        text = provider.path.read_text(encoding="utf-8")
        self.assertNotIn("acct-secret", text)
        self.assertNotIn('"tok"', text)


if __name__ == "__main__":
    unittest.main()
