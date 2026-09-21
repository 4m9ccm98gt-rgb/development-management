"""Selection-state tests through the real coordinator and shared apply path (Tk-free)."""

from pathlib import Path
from collections import defaultdict
import random
import re
import threading
import time
import unittest

from scripts.dev_control_center.core import (
    Cancelled,
    EntryPointChoice,
    GitHubState,
    RepoDefinition,
    RepoEntrypoints,
    RepoState,
    decide_lifecycle,
)
from scripts.dev_control_center.loader import Coordinator, NoticeKind, RequestState
from scripts.dev_control_center.selection import (
    DEV_MANAGEMENT,
    GLOBAL_REMOTE_REPOS,
    GLOBAL_SELF_UPDATE,
    CandidateProvenance,
    IntentSnapshot,
    LocalSnapshot,
    Origin,
    SelectionState,
)
from tests.test_dev_control_center_async_load import FakeClock, wait_for

ROOT = Path(__file__).resolve().parents[1]
APP_TEXT = (ROOT / "scripts" / "dev_control_center" / "app.py").read_text(encoding="utf-8")
SEL_TEXT = (ROOT / "scripts" / "dev_control_center" / "selection.py").read_text(encoding="utf-8")

X = "a" * 40
Y = "b" * 40
NAMES = ["A", "B", "C", DEV_MANAGEMENT]
DEFS = [RepoDefinition(n, "desktop", "main", owner="o") for n in NAMES]


def ready(name: str) -> EntryPointChoice:
    return EntryPointChoice("READY", Path(name))


ENTRIES = RepoEntrypoints(ready("s.cmd"), ready("r.cmd"), ready("b.cmd"), ready("u.cmd"), "UPDATE")


def snapshot(defn: RepoDefinition, head: str = X) -> LocalSnapshot:
    state = RepoState(True, True, branch=defn.branch, head=head, origin_head=head,
                      origin_repo=defn.full_name)
    return LocalSnapshot(state, ENTRIES)


def gh(sha: str = X) -> GitHubState:
    return GitHubState(branch_sha=sha, ci_sha=sha, ci_target="main", ci_state="GREEN", check_count=1)


class FakeView:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.sel = None

    def _rec(self, *a):
        self.calls.append(a)

    def names(self, name):
        return [c for c in self.calls if c[0] == name]

    def on_loading(self, repo): self._rec("loading", repo)
    def on_request_suggestion(self, repo):
        self._rec("suggest_req", repo)
        if self.sel is not None:
            self.sel.submit_suggest(repo)
    def on_suggestion(self, repo, value): self._rec("suggestion", repo, value)
    def on_local(self, repo, snap): self._rec("local", repo, snap)
    def on_local_unavailable(self, repo, text): self._rec("local_unavailable", repo, text)
    def on_github(self, repo, state): self._rec("github", repo, state)
    def on_candidate_text(self, text): self._rec("candidate", text)
    def on_lifecycle(self): self._rec("lifecycle")
    def on_log(self, text): self._rec("log", text)
    def on_post_notice(self, text): self._rec("post_notice", text)
    def on_global_result(self, kind, msg): self._rec("global_result", kind, msg.payload)
    def on_global_notice(self, kind, notice): self._rec("global_notice", kind, notice.kind)


class FakeScheduler:
    def __init__(self) -> None:
        self.queue: dict[int, object] = {}
        self._n = 0

    def after(self, ms, fn):
        self._n += 1
        self.queue[self._n] = fn
        return self._n

    def cancel(self, handle):
        self.queue.pop(handle, None)

    def run(self):
        for handle in list(self.queue):
            fn = self.queue.pop(handle, None)
            if fn:
                fn()


class StubLoaders:
    """Local/GitHub loaders that can honour or ignore cancel and be gated."""

    def __init__(self) -> None:
        self.mode: dict[tuple[str, str], str] = {}     # "block" (ignore), "aware", default fast
        self.gates: dict[tuple[str, str], threading.Event] = defaultdict(threading.Event)
        self.started: dict[tuple[str, str], threading.Event] = defaultdict(threading.Event)
        self.calls: list[tuple[str, str]] = []
        self.github_sha = X

    def _run(self, kind: str, defn: RepoDefinition, cancel, result):
        key = (defn.name, kind)
        self.calls.append(key)
        self.started[key].set()
        mode = self.mode.get(key, "fast")
        if mode == "aware":
            cancel.wait(10)
            raise Cancelled()
        if mode == "block":
            self.gates[key].wait(10)
        return result

    def local(self, defn, cancel):
        return self._run("local", defn, cancel, snapshot(defn))

    def github(self, defn, cancel):
        return self._run("github", defn, cancel, gh(self.github_sha))

    def suggest(self, defn, cancel):
        return "python -m unittest"

    def release_all(self):
        for gate in self.gates.values():
            gate.set()


class SelectionBase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.coordinator = Coordinator(clock=self.clock)
        self.view = FakeView()
        self.loaders = StubLoaders()
        self.sched = FakeScheduler()
        self.sel = SelectionState(self.coordinator, DEFS, self.view, self.loaders,
                                  scheduler=self.sched)
        self.view.sel = self.sel
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.loaders.release_all()
        self.sel.close()

    def select(self, name: str, fire: bool = True):
        self.sel.select(name)
        if fire:
            self.sched.run()

    def pump_until(self, predicate, timeout: float = 5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.sel.pump()
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError("condition not reached")

    def shown(self, name: str, repo: str) -> list:
        return [c for c in self.view.names(name) if c[1] == repo]

    def load_fully(self, name: str):
        self.select(name)
        self.pump_until(lambda: self.sel.authoritative_github(name) is not None
                        and self.sel.authoritative_local(name) is not None)

    def decision(self, name: str):
        snap = self.sel.authoritative_local(name)
        defn = next(d for d in DEFS if d.name == name)
        return decide_lifecycle(defn, snap.repo_state, snap.entrypoints,
                                self.sel.authoritative_github(name),
                                self.sel.provenance.text(name))


class RepoSwitchTests(SelectionBase):
    def test_debounce_skipped_repo_submits_nothing_and_last_repo_loads(self):
        self.select("A", fire=False)
        self.select("B", fire=False)
        self.select("C")
        self.pump_until(lambda: self.sel.authoritative_local("C") is not None)
        self.assertEqual({repo for repo, _ in self.loaders.calls}, {"C"})

    def test_a_b_c_cancel_aware_workers_free_c_without_clock_advance(self):
        for repo in ("A", "B"):
            self.loaders.mode[(repo, "local")] = "aware"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        self.select("B")
        self.loaders.started[("B", "local")].wait(5)
        self.select("C")
        self.pump_until(lambda: self.sel.authoritative_local("C") is not None)
        self.assertEqual(self.clock.now, 0.0)
        self.assertEqual(self.coordinator.stats("LOCAL")["abandoned_live"], 0)
        self.assertEqual([c[1] for c in self.view.names("local")], ["C"])

    def test_a_b_c_cancel_ignoring_workers_wait_for_grace(self):
        for repo in ("A", "B"):
            self.loaders.mode[(repo, "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        self.select("B")
        self.loaders.started[("B", "local")].wait(5)
        self.select("C")
        time.sleep(0.1)
        self.sel.pump()
        self.assertIsNone(self.sel.authoritative_local("C"))
        self.clock.advance(10)
        self.pump_until(lambda: self.sel.authoritative_local("C") is not None)
        self.assertEqual(self.coordinator.stats("LOCAL")["abandoned_live"], 2)
        self.assertEqual(self.view.names("local_unavailable"), [])  # no notice for A/B

    def test_returning_to_a_reloads_and_stale_a_result_is_discarded(self):
        self.loaders.mode[("A", "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        first_epoch = self.sel.lifecycle_epoch["A"]
        self.select("B")
        self.pump_until(lambda: self.sel.authoritative_local("B") is not None)
        self.loaders.mode[("A", "local")] = "fast"
        self.select("A")
        self.assertGreater(self.sel.lifecycle_epoch["A"], first_epoch)
        self.loaders.release_all()  # the stale A worker returns late
        self.pump_until(lambda: self.sel.authoritative_local("A") is not None)
        stamp = self.sel._local["A"]
        self.assertEqual(stamp.epoch, self.sel.lifecycle_epoch["A"])

    def test_result_with_old_epoch_is_dropped_at_apply(self):
        self.select("A")
        wait_for(lambda: self.coordinator.slot_counts()[1] >= 1)
        self.sel.new_epoch("A", "manual")  # completed result now carries a stale epoch
        self.sel.pump()
        self.assertIsNone(self.sel.authoritative_local("A"))
        self.assertEqual(self.view.names("local"), [])

    def test_result_for_other_repo_is_dropped(self):
        self.loaders.mode[("A", "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        self.select("B", fire=False)  # B selected; A's late result must not show
        self.loaders.release_all()
        time.sleep(0.1)
        self.sel.pump()
        self.assertEqual(self.shown("local", "A"), [])

    def test_process_boundary_cancels_running_loads_with_grace_clock(self):
        self.loaders.mode[("A", "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        token = self.coordinator.latest_token(("A", "local"))
        self.assertEqual(self.coordinator.request_state(token), RequestState.RUNNING)
        self.sel.process_boundary("A", "process-start")
        self.assertEqual(self.coordinator.request_state(token), RequestState.SUPERSEDED)
        self.assertIsNone(self.sel.authoritative_local("A"))

    def test_suggestion_is_requested_and_applied_through_view(self):
        self.select("A")
        self.pump_until(lambda: self.view.names("suggestion"))
        self.assertEqual(self.view.names("suggest_req"), [("suggest_req", "A")])


class ReselectionTests(SelectionBase):
    """D-015 / D-013 / D-019: only the new epoch's authoritative data may drive decisions."""

    def _auto_reflected_a(self):
        self.load_fully("A")
        self.assertEqual(self.sel.provenance.text("A"), X)
        self.assertEqual(self.sel.provenance.origin("A"), Origin.AUTO)

    def _assert_no_stale_decision(self):
        self.assertEqual(self.sel.provenance.text("A"), "")
        self.assertEqual(self.sel.provenance.origin("A"), Origin.NONE)
        self.assertIsNone(self.sel.authoritative_github("A"))
        decision = self.decision("A")
        self.assertEqual(decision.candidate_sha, "")
        self.assertFalse(any((decision.run_enabled, decision.build_enabled,
                              decision.release_enabled, decision.sync_enabled)))

    def test_a_b_a_only_local_delivered(self):
        self._auto_reflected_a()
        self.load_fully("B")
        self.loaders.mode[("A", "github")] = "block"
        self.select("A")
        self.pump_until(lambda: self.sel.authoritative_local("A") is not None)
        self._assert_no_stale_decision()
        self.assertTrue(self.sel.github_loading)

    def test_direct_reselect_and_manual_refresh_only_local_delivered(self):
        for action in ("reselect", "manual"):
            with self.subTest(action):
                self.setUp()
                self._auto_reflected_a()
                self.loaders.mode[("A", "github")] = "block"
                if action == "reselect":
                    self.select("A")
                else:
                    self.sel.new_epoch("A", "manual")
                    self.sel.reload_local("A")
                self.pump_until(lambda: self.sel.authoritative_local("A") is not None)
                self._assert_no_stale_decision()
                self.assertEqual(self.sel.display_cache["A"].branch_sha, X)
                self.loaders.release_all()
                self.pump_until(lambda: self.sel.authoritative_github("A") is not None
                                if action == "reselect" else True)

    def test_failed_github_leaves_candidate_empty(self):
        self._auto_reflected_a()
        self.loaders.github = lambda d, c: GitHubState(error="offline")
        self.select("A")
        self.pump_until(lambda: self.sel.authoritative_github("A") is not None)
        self.assertEqual(self.sel.provenance.text("A"), "")
        self.assertFalse(self.decision("A").run_enabled)

    def test_user_and_ai_candidates_survive_switching(self):
        self.load_fully("A")
        self.sel.provenance.user_edit("A", X)         # typed value equal to the old auto SHA
        self.sel.provenance.ai_result("B", Y)
        self.select("B")
        self.select("A")
        self.assertEqual(self.sel.provenance.text("A"), X)
        self.assertEqual(self.sel.provenance.origin("A"), Origin.USER)
        self.assertEqual(self.sel.provenance.origin("B"), Origin.AI)

    def test_fresh_github_result_auto_reflects_again(self):
        self._auto_reflected_a()
        self.select("B")
        self.select("A")
        self.pump_until(lambda: self.sel.provenance.text("A") == X)
        self.assertEqual(self.sel.provenance.origin("A"), Origin.AUTO)


class ProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = gh(X)
        self.auth = {"A": self.record}
        self.p = CandidateProvenance(lambda repo: self.auth.get(repo))

    def test_clear_then_refresh_refills_as_auto_never_none_with_text(self):
        self.assertTrue(self.p.auto_reflect("A", X, self.record))
        self.p.user_edit("A", Y)
        self.assertEqual(self.p.origin("A"), Origin.USER)
        self.p.user_edit("A", "")
        self.assertEqual(self.p.origin("A"), Origin.NONE)
        self.assertTrue(self.p.auto_reflect("A", X, self.auth["A"]))
        self.assertEqual((self.p.text("A"), self.p.origin("A")), (X, Origin.AUTO))

    def test_invariant_none_iff_empty_under_random_operations(self):
        rng = random.Random(7)
        for _ in range(3000):
            op = rng.choice(["user", "user_empty", "ai", "auto", "norm", "clear", "drop_auth"])
            text = rng.choice([X, Y, X.upper(), "", "abc", " " + Y + " "])
            if op == "user":
                self.p.user_edit("A", text)
            elif op == "user_empty":
                self.p.user_edit("A", "")
            elif op == "ai":
                self.p.ai_result("A", text)
            elif op == "auto":
                self.p.auto_reflect("A", text, self.auth.get("A"))
            elif op == "norm":
                self.p.normalize("A", text)
            elif op == "clear":
                self.p.clear_auto("A")
            else:
                self.auth["A"] = self.record if rng.random() < 0.5 else None
            self.assertEqual(self.p.origin("A") is Origin.NONE, self.p.text("A") == "")

    def test_normalize_rules_and_origin_preserved(self):
        for origin_setter in (lambda: self.p.user_edit("A", X.upper()),
                              lambda: self.p.ai_result("A", X.upper())):
            self.p.user_edit("A", "")
            origin_setter()
            if self.p.origin("A") is Origin.AI:
                self.p.candidate_by_repo["A"] = X.upper()   # AI results are lower-cased on entry
            before = self.p.origin("A")
            self.assertTrue(self.p.normalize("A", X))
            self.assertEqual((self.p.text("A"), self.p.origin("A")), (X, before))
        self.assertFalse(self.p.normalize("A", Y))            # differs by more than case
        self.p.user_edit("A", "")
        self.assertFalse(self.p.normalize("A", X))            # empty text is never filled
        self.assertEqual(self.p.origin("A"), Origin.NONE)

    def test_auto_reflect_rejected_cases(self):
        self.assertFalse(self.p.auto_reflect("A", Y, self.record))                 # sha != branch
        self.assertFalse(self.p.auto_reflect("A", X, gh(X)))                       # not the authoritative record
        self.assertFalse(self.p.auto_reflect("A", X, None))
        self.auth["A"] = GitHubState(error="x")
        self.assertFalse(self.p.auto_reflect("A", X, self.auth["A"]))              # error record
        self.auth["A"] = self.record
        self.p.user_edit("A", "abc")
        self.assertFalse(self.p.auto_reflect("A", X, self.record))                 # text present
        self.p.user_edit("A", "")
        self.auth["A"] = None                                                       # stale / expired
        self.assertFalse(self.p.auto_reflect("A", X, self.record))

    def test_clear_auto_only_acts_on_auto(self):
        self.p.user_edit("A", X)
        self.assertFalse(self.p.clear_auto("A"))
        self.p.ai_result("B", X)
        self.assertFalse(self.p.clear_auto("B"))
        self.assertEqual(self.p.text("B"), X)

    def test_case_normalization_survives_refresh_and_switch_for_user_and_ai(self):
        for name, setter in (("A", self.p.user_edit), ("B", self.p.ai_result)):
            self.auth[name] = gh(X)
            setter(name, X)
            self.p.normalize(name, X)
            self.p.clear_auto(name)      # what invalidate/leave do
            self.assertEqual(self.p.text(name), X)


class TimeoutAndModalTests(SelectionBase):
    def test_local_timeout_applies_once_and_fails_closed(self):
        self.loaders.mode[("A", "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        self.clock.advance(31)
        self.pump_until(lambda: self.view.names("local_unavailable"))
        self.sel.pump()
        self.sel.pump()
        self.assertEqual(len(self.view.names("local_unavailable")), 1)
        self.assertIn("タイムアウト", self.view.names("local_unavailable")[0][2])
        self.assertIsNone(self.sel.authoritative_local("A"))

    def test_github_timeout_gives_error_state_that_enables_nothing(self):
        self.loaders.mode[("A", "github")] = "block"
        self.select("A")
        self.loaders.started[("A", "github")].wait(5)
        self.pump_until(lambda: self.sel.authoritative_local("A") is not None)
        self.clock.advance(61)
        self.pump_until(lambda: self.sel.authoritative_github("A") is not None)
        self.assertTrue(self.sel.authoritative_github("A").error)
        self.assertEqual(self.sel.provenance.text("A"), "")
        self.assertFalse(self.decision("A").run_enabled)

    def test_notice_is_held_during_dialog_and_delivered_once_after(self):
        self.loaders.mode[("A", "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        self.sel.guard.begin(IntentSnapshot("release", {"x": 1}))
        self.clock.advance(31)
        self.sel.pump()                     # watchdog fires while the dialog is open
        self.loaders.release_all()          # a late worker result must not displace the notice
        time.sleep(0.1)
        self.sel.pump()
        self.assertEqual(self.view.names("local_unavailable"), [])
        self.assertTrue(self.sel.guard.finish(lambda: {"x": 1}))
        self.sel.pump()
        self.sel.pump()
        self.assertEqual(len(self.view.names("local_unavailable")), 1)

    def test_held_notice_dropped_if_repo_changed_during_dialog(self):
        self.loaders.mode[("A", "local")] = "block"
        self.select("A")
        self.loaders.started[("A", "local")].wait(5)
        self.sel.guard.begin(IntentSnapshot("release", {}))
        self.clock.advance(31)
        self.sel.pump()
        self.sel.select("B")
        self.sel.guard.end()
        self.sel.pump()
        self.assertEqual(self.shown("local_unavailable", "A"), [])

    def test_guard_finish_detects_changed_world(self):
        self.sel.guard.begin(IntentSnapshot("k", {"a": 1}))
        self.assertFalse(self.sel.guard.finish(lambda: {"a": 2}))
        self.assertFalse(self.sel.guard.active)

    def test_wedged_local_pool_stays_bounded(self):
        self.loaders.mode = {(n, "local"): "block" for n in NAMES}
        # wedge LOCAL completely: tmax = 2 + 4
        for i in range(8):
            self.select(NAMES[i % 4])
            time.sleep(0.02)
            self.clock.advance(31)
            self.coordinator.tick()
        self.assertLessEqual(self.coordinator.stats("LOCAL")["total_live"], 6)


class GlobalScopeTests(SelectionBase):
    def test_global_results_survive_switching_and_apply_once(self):
        gate = threading.Event()
        self.sel.submit_global(GLOBAL_REMOTE_REPOS, lambda cancel: gate.wait(5) and ["r"])
        self.select("A")
        self.select("B")
        self.select("C")
        gate.set()
        self.pump_until(lambda: self.view.names("global_result"))
        self.sel.pump()
        self.assertEqual(self.view.names("global_result"), [("global_result", GLOBAL_REMOTE_REPOS, ["r"])])

    def test_global_result_deferred_by_guard_then_applied(self):
        self.sel.guard.begin(IntentSnapshot("setup", {}))
        self.sel.submit_global(GLOBAL_REMOTE_REPOS, lambda cancel: ["r"])
        time.sleep(0.15)
        self.sel.pump()
        self.assertEqual(self.view.names("global_result"), [])
        self.sel.guard.end()
        self.pump_until(lambda: self.view.names("global_result"))

    def test_global_timeout_is_a_notice(self):
        gate = threading.Event()
        self.sel.submit_global(GLOBAL_REMOTE_REPOS, lambda cancel: gate.wait(10))
        time.sleep(0.1)
        self.clock.advance(91)
        self.pump_until(lambda: self.view.names("global_notice"))
        self.assertEqual(self.view.names("global_notice")[0][2], NoticeKind.TIMEOUT)
        gate.set()

    def test_self_update_result_dropped_after_dev_management_process(self):
        gate = threading.Event()
        self.sel.submit_global(GLOBAL_SELF_UPDATE, lambda cancel: gate.wait(5) and ("l", "g"))
        time.sleep(0.05)
        self.sel.process_boundary("A", "process-start")          # another repo: not invalidated
        self.assertEqual(self.sel.self_update_epoch, 0)
        self.assertTrue(self.sel.process_boundary(DEV_MANAGEMENT, "process-start"))
        self.assertEqual(self.sel.self_update_epoch, 1)
        gate.set()
        time.sleep(0.15)
        self.sel.pump()
        self.assertEqual(self.view.names("global_result"), [])

    def test_after_close_nothing_applies(self):
        self.sel.submit_global(GLOBAL_REMOTE_REPOS, lambda cancel: ["r"])
        time.sleep(0.1)
        self.sel.close()
        self.sel.pump()
        self.assertEqual(self.view.names("global_result"), [])


class NonBlockingTests(SelectionBase):
    def test_select_and_submit_return_quickly_while_loaders_block(self):
        for kind in ("local", "github"):
            self.loaders.mode[("A", kind)] = "block"
        started = time.perf_counter()
        self.select("A")
        self.assertLess(time.perf_counter() - started, 0.25)


class SourceContractTests(unittest.TestCase):
    def test_candidate_writes_only_inside_provenance_class(self):
        start = SEL_TEXT.index("class CandidateProvenance")
        end = SEL_TEXT.index("@dataclass(frozen=True)\nclass Stamped")
        outside = SEL_TEXT[:start] + SEL_TEXT[end:]
        for text in (outside, APP_TEXT):
            self.assertNotRegex(text, r"candidate_by_repo\[[^\]]+\]\s*=")
            self.assertNotRegex(text, r"candidate_origin\[[^\]]+\]\s*=")
        self.assertNotIn("auto_candidate_by_repo", APP_TEXT + SEL_TEXT)
        self.assertNotIn("candidate_source", re.sub(r"candidate_source_var", "", SEL_TEXT))

    def test_app_reads_state_only_through_accessors(self):
        self.assertNotIn("github_states", APP_TEXT)
        self.assertNotRegex(APP_TEXT, r"self\.repo_state\s*=[^=]")
        self.assertNotRegex(APP_TEXT, r"self\.entrypoints\s*=[^=]")
        self.assertIn("authoritative_github(", APP_TEXT)
        self.assertIn("authoritative_local(", APP_TEXT)

    def test_active_process_is_set_only_by_begin_and_end_process(self):
        assignments = re.findall(r"self\.active_process = (.+)", APP_TEXT)
        self.assertEqual(sorted(assignments), sorted(["None", "(process, repo_name, action)", "None"]))
        begin = APP_TEXT.index("    def _begin_process")
        end_ = APP_TEXT.index("    def _end_process")
        self.assertIn("self.active_process = (process, repo_name, action)", APP_TEXT[begin:end_])
        for launcher in ("def launch_ai_orchestrator", "def _launch_cmd"):
            start = APP_TEXT.index(launcher)
            body = APP_TEXT[start:APP_TEXT.index("\n    def ", start + 10)]
            self.assertIn("self._begin_process(", body)

    def test_blocking_calls_are_off_the_ui_thread_paths(self):
        for name in ("_select_repo", "refresh", "refresh_github", "refresh_all", "on_loading"):
            start = APP_TEXT.index(f"    def {name}(")
            body = APP_TEXT[start:APP_TEXT.index("\n    def ", start + 10)]
            for banned in ("inspect_repo(", "discover_entrypoints(", "fetch_github_state(",
                           "suggest_test_command(", "list_github_repositories("):
                self.assertNotIn(banned, body, f"{name} calls {banned} on the UI thread")


if __name__ == "__main__":
    unittest.main()
