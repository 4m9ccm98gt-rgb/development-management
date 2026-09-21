"""Tk-free coordinator tests: tokens, cancel_repo_scope (D-021), watchdog, accounting."""

from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

from scripts.dev_control_center.core import Cancelled
from scripts.dev_control_center.loader import (
    GLOBAL,
    Coordinator,
    NoticeKind,
    RequestState,
    TerminalNotice,
    WorkerResult,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def wait_for(predicate, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached in time")


class Stub:
    """A gated blocking worker function. ``aware`` stubs return when cancelled."""

    def __init__(self, value="ok", *, aware: bool = False, raise_cancelled: bool = False) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.value = value
        self.aware = aware
        self.raise_cancelled = raise_cancelled

    def __call__(self, cancel: threading.Event):
        self.started.set()
        if self.aware:
            cancel.wait(10)
            if self.raise_cancelled:
                raise Cancelled()
            return self.value
        self.release.wait(10)
        return self.value


def quick(value="ok"):
    return lambda cancel: value


class CoordinatorBase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.c = Coordinator(clock=self.clock)
        self.stubs: list[Stub] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for stub in self.stubs:
            stub.release.set()
        self.c.close()

    def stub(self, *args, **kwargs) -> Stub:
        stub = Stub(*args, **kwargs)
        self.stubs.append(stub)
        return stub

    def check_invariants(self, pool: str) -> None:
        s = self.c.stats(pool)
        self.assertLessEqual(s["active_count"], s["size"])
        self.assertLessEqual(s["total_live"], s["t_max"])

    def drain_tokens(self):
        return [(type(m).__name__, m.token) for m in self.c.drain()]


class TokenTests(CoordinatorBase):
    def test_newer_same_key_supersedes_and_older_result_is_dropped(self):
        old = self.stub("old")
        req1 = self.c.submit(("a", "local"), old, pool="LOCAL", epoch=1)
        old.started.wait(5)
        req2 = self.c.submit(("a", "local"), quick("new"), pool="LOCAL", epoch=1)
        self.assertTrue(req1.cancel.is_set())
        self.assertEqual(req1.state, RequestState.SUPERSEDED)
        wait_for(lambda: req2.state == RequestState.COMPLETED)
        old.release.set()
        wait_for(lambda: self.c.stats("LOCAL")["running"] == 0)
        messages = self.c.drain()
        self.assertEqual([m.payload for m in messages], ["new"])
        self.assertTrue(self.c.is_latest(req2.token, req2.key))
        self.assertFalse(self.c.is_latest(req1.token, req1.key))

    def test_slots_are_bounded_by_keys_and_pool_isolated(self):
        for i in range(100):
            self.c.submit((f"r{i % 5}", "local"), self.stub(aware=False), pool="LOCAL", epoch=i)
        pending, results, notices = self.c.slot_counts()
        self.assertLessEqual(pending, 5)
        self.assertLessEqual(results + notices, 10)
        self.check_invariants("LOCAL")
        github = self.c.submit(("r0", "github"), quick("gh"), pool="GITHUB", epoch=1)
        wait_for(lambda: github.state == RequestState.COMPLETED)

    def test_result_drain_is_one_per_key_highest_token(self):
        self.c.submit(("a", "local"), quick("1"), pool="LOCAL", epoch=1)
        wait_for(lambda: self.c.slot_counts()[1] == 1)
        req = self.c.submit(("a", "local"), quick("2"), pool="LOCAL", epoch=1)
        wait_for(lambda: req.state == RequestState.COMPLETED)
        self.assertEqual([m.payload for m in self.c.drain()], ["2"])
        self.assertEqual(self.c.drain(), [])


class RepoScopeCancelTests(CoordinatorBase):
    """D-021: leaving a repo frees the workers held for it."""

    def test_a_responsive_workers_free_slot_without_clock_advance(self):
        a = self.stub("late-a", aware=True, raise_cancelled=True)
        b = self.stub("late-b", aware=True)
        ra = self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        rb = self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        rc = self.c.submit(("C", "local"), quick("c"), pool="LOCAL", epoch=1)
        self.assertEqual(rc.state, RequestState.PENDING)
        self.assertEqual(self.c.cancel_repo_scope("A", "leave"), (0, 1))
        self.assertEqual(self.c.cancel_repo_scope("B", "leave"), (0, 1))
        for req in (ra, rb):
            self.assertTrue(req.cancel.is_set())
            self.assertEqual(req.state, RequestState.SUPERSEDED)
            self.assertIsNotNone(req.cancelled_at)
        wait_for(lambda: rc.state == RequestState.COMPLETED)
        self.assertEqual(self.clock.now, 0.0)
        wait_for(lambda: self.c.stats("LOCAL")["running"] == 0)
        messages = self.c.drain()
        self.assertEqual([m.payload for m in messages], ["c"])
        self.assertEqual(self.c.stats("LOCAL")["abandoned_live"], 0)

    def test_b_cancel_ignoring_workers_are_abandoned_after_grace_only(self):
        a, b = self.stub(), self.stub()
        self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        rc = self.c.submit(("C", "local"), quick("c"), pool="LOCAL", epoch=1)
        self.c.cancel_repo_scope("A", "leave")
        self.c.cancel_repo_scope("B", "leave")
        self.clock.advance(9.9)
        self.c.tick()
        self.assertEqual(rc.state, RequestState.PENDING)
        self.clock.advance(0.1)
        self.c.tick()
        wait_for(lambda: rc.state == RequestState.COMPLETED)
        stats = self.c.stats("LOCAL")
        self.assertEqual(stats["abandoned_live"], 2)
        self.assertLessEqual(stats["total_live"], stats["t_max"])
        self.assertLess(self.clock.now, 30)
        self.assertEqual([type(m) for m in self.c.drain()], [WorkerResult])  # no notice for A/B
        self.c.tick()  # once-only: no double abandonment
        self.assertEqual(self.c.stats("LOCAL")["abandoned_live"], 2)
        a.release.set()
        b.release.set()
        wait_for(lambda: self.c.stats("LOCAL")["abandoned_live"] == 0)
        self.check_invariants("LOCAL")

    def test_c_mixed_honouring_and_ignoring(self):
        a, b = self.stub(), self.stub(aware=True)
        self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        rc = self.c.submit(("C", "local"), quick("c"), pool="LOCAL", epoch=1)
        self.c.cancel_repo_scope("A", "leave")
        self.c.cancel_repo_scope("B", "leave")
        wait_for(lambda: rc.state == RequestState.COMPLETED)  # B's worker, no clock
        self.assertEqual(self.clock.now, 0.0)
        self.clock.advance(10)
        self.c.tick()
        self.assertEqual(self.c.stats("LOCAL")["abandoned_live"], 1)

    def test_d_pending_request_removed_without_touching_workers(self):
        a, b = self.stub(), self.stub()
        self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        before = self.c.stats("LOCAL")
        rc = self.c.submit(("C", "local"), quick(), pool="LOCAL", epoch=1)
        self.assertEqual(self.c.cancel_repo_scope("C", "leave"), (1, 0))
        self.assertEqual(rc.state, RequestState.SUPERSEDED)
        after = self.c.stats("LOCAL")
        for field in ("active_count", "abandoned_live", "total_live", "running"):
            self.assertEqual(before[field], after[field])
        self.assertEqual(after["pending"], 0)
        self.assertEqual(self.c.drain(), [])

    def test_e_global_requests_are_never_cancelled(self):
        g = self.stub("remote")
        rg = self.c.submit((GLOBAL, "remote_repos"), g, pool="BACKGROUND")
        g.started.wait(5)
        for repo in ("A", "B", "C"):
            self.c.cancel_repo_scope(repo, "leave")
        self.assertEqual(rg.state, RequestState.RUNNING)
        self.assertFalse(rg.cancel.is_set())
        self.clock.advance(10)
        self.c.tick()
        self.assertEqual(self.c.stats("BACKGROUND")["abandoned_live"], 0)
        g.release.set()
        wait_for(lambda: rg.state == RequestState.COMPLETED)
        messages = self.c.drain()
        self.assertEqual([m.payload for m in messages], ["remote"])
        self.assertIsNone(messages[0].repo)

    def test_g_same_key_resubmit_uses_same_routine(self):
        first = self.stub()
        r1 = self.c.submit(("A", "local"), first, pool="LOCAL", epoch=1)
        first.started.wait(5)
        self.c.submit(("A", "local"), quick(), pool="LOCAL", epoch=2)
        self.assertEqual(r1.state, RequestState.SUPERSEDED)
        self.assertIsNotNone(r1.cancelled_at)

    def test_h_stress_cancel_complete_tick_race(self):
        for i in range(150):
            barrier = threading.Barrier(3)
            req = self.c.submit(("S", "local"), quick(i), pool="LOCAL", epoch=i)

            def cancel():
                barrier.wait()
                self.c.cancel_repo_scope("S", "race")

            def tick():
                barrier.wait()
                self.clock.advance(0.001)
                self.c.tick()

            threads = [threading.Thread(target=cancel), threading.Thread(target=tick)]
            for t in threads:
                t.start()
            barrier.wait()
            for t in threads:
                t.join()
            wait_for(lambda: req.state in (RequestState.COMPLETED, RequestState.SUPERSEDED))
            wait_for(lambda: self.c.stats("LOCAL")["running"] == 0)
            self.check_invariants("LOCAL")
            outcomes = [m for m in self.c.drain() if m.token == req.token]
            self.assertLessEqual(len(outcomes), 1)
            if req.state == RequestState.SUPERSEDED:
                self.assertEqual(outcomes, [])
        self.assertEqual(self.c.stats("LOCAL")["abandoned_live"], 0)

    def test_github_pool_four_rapid_switches(self):
        stubs = [self.stub(aware=True, raise_cancelled=True) for _ in range(4)]
        reqs = []
        for i, stub in enumerate(stubs[:3]):
            reqs.append(self.c.submit((f"R{i}", "github"), stub, pool="GITHUB", epoch=1))
            stub.started.wait(5)
        last = self.c.submit(("R3", "github"), quick("last"), pool="GITHUB", epoch=1)
        for i in range(3):
            self.c.cancel_repo_scope(f"R{i}", "leave")
        wait_for(lambda: last.state == RequestState.COMPLETED)
        self.assertEqual(self.clock.now, 0.0)


class AccountingTests(CoordinatorBase):
    def _expire_running(self, pool: str, keys, *, deadline_advance: float):
        stubs = []
        for key in keys:
            stub = self.stub()
            self.c.submit(key, stub, pool=pool, epoch=1)
            stubs.append(stub)
        for stub in stubs:
            stub.started.wait(5)
        self.clock.advance(deadline_advance)
        self.c.tick()
        self.check_invariants(pool)
        return stubs

    def test_a_cap_boundary_and_b_all_wedged_recovery(self):
        wedged = self._expire_running("GITHUB", [(f"r{i}", "github") for i in range(3)],
                                      deadline_advance=61)
        s = self.c.stats("GITHUB")
        self.assertEqual((s["abandoned_live"], s["active_count"], s["total_live"]), (3, 3, 6))
        wedged += self._expire_running("GITHUB", [(f"q{i}", "github") for i in range(3)],
                                       deadline_advance=61)
        s = self.c.stats("GITHUB")
        self.assertEqual(s["total_live"], s["t_max"])          # 7, never exceeded
        self.assertGreater(s["abandoned_live"], 4)             # abandoned may exceed the room
        self.assertEqual(s["deficit"], 3 - s["active_count"])  # shortfall recorded
        # Drive the remaining active worker(s) to expiry: pool fully wedged.
        while self.c.stats("GITHUB")["active_count"]:
            wedged += self._expire_running("GITHUB", [(f"z{len(wedged)}", "github")],
                                           deadline_advance=61)
        s = self.c.stats("GITHUB")
        self.assertEqual((s["active_count"], s["total_live"]), (0, 7))
        self.c.drain()
        fail_closed = self.c.submit(("new", "github"), quick(), pool="GITHUB", epoch=1)
        self.assertEqual(fail_closed.state, RequestState.TIMED_OUT)
        notices = self.c.drain()
        self.assertEqual(len(notices), 1)
        self.assertIsInstance(notices[0], TerminalNotice)
        self.assertEqual(notices[0].kind, NoticeKind.ABANDON_CAP)
        self.assertEqual(self.c.stats("GITHUB")["total_live"], 7)
        # Release ONE wedged worker: it is rehabilitated and a healthy request completes.
        wedged[0].release.set()
        wait_for(lambda: self.c.stats("GITHUB")["active_count"] == 1)
        healthy = self.c.submit(("ok", "github"), quick("healthy"), pool="GITHUB", epoch=1)
        wait_for(lambda: healthy.state == RequestState.COMPLETED)
        for stub in wedged:
            stub.release.set()
        wait_for(lambda: self.c.stats("GITHUB")["abandoned_live"] == 0)
        s = self.c.stats("GITHUB")
        self.assertLessEqual(s["active_count"], s["size"])
        self.assertLessEqual(s["total_live"], s["t_max"])

    def test_f001_rehabilitated_worker_can_be_reclaimed_again_after_supersede(self):
        wedged = []
        while self.c.stats("GITHUB")["total_live"] < 7 or self.c.stats("GITHUB")["active_count"]:
            wedged += self._expire_running("GITHUB", [(f"z{len(wedged)}", "github")],
                                           deadline_advance=61)
        self.c.drain()
        wedged[0].release.set()  # abandoned -> rehabilitated (pool was short)
        wait_for(lambda: self.c.stats("GITHUB")["active_count"] == 1)
        # The recovered worker wedges again, on a request that is then superseded.
        again = self.stub()
        self.c.submit(("k", "github"), again, pool="GITHUB", epoch=1)
        again.started.wait(5)
        newer = self.c.submit(("k", "github"), quick("new"), pool="GITHUB", epoch=2)
        self.assertEqual(newer.state, RequestState.PENDING)
        self.clock.advance(10)  # grace
        self.c.tick()
        s = self.c.stats("GITHUB")
        self.assertEqual((s["active_count"], s["abandoned_live"]), (0, 7))
        # Once any worker returns, the slot recovers and the newer request runs.
        again.release.set()
        wait_for(lambda: newer.state == RequestState.COMPLETED)

    def test_c_refill_without_a_return(self):
        for pool in ("LOCAL", "BACKGROUND"):
            self._expire_running(pool, [(f"r{i}", "local") for i in range(2)],
                                 deadline_advance=100)
            s = self.c.stats(pool)
            self.assertEqual(s["active_count"], s["size"])  # replacements spawned

    def test_e_pending_expiry_touches_no_worker(self):
        a, b = self.stub(), self.stub()
        self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        pending = self.c.submit(("C", "local"), quick(), pool="LOCAL", epoch=1, deadline=5)
        before = self.c.stats("LOCAL")
        self.clock.advance(6)
        self.c.tick()
        self.assertEqual(pending.state, RequestState.TIMED_OUT)
        after = self.c.stats("LOCAL")
        for field in ("active_count", "abandoned_live", "total_live"):
            self.assertEqual(before[field], after[field])
        notices = self.c.drain()
        self.assertEqual([n.kind for n in notices], [NoticeKind.TIMEOUT])

    def test_g_no_capacity_versus_busy(self):
        a, b = self.stub(), self.stub()
        self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        waiting = self.c.submit(("C", "local"), quick(), pool="LOCAL", epoch=1)
        self.assertEqual(waiting.state, RequestState.PENDING)  # busy, not fail-closed
        self.clock.advance(31)
        self.c.tick()  # A/B expire (abandoned + replaced); C's own deadline also passed
        self.assertEqual(waiting.state, RequestState.TIMED_OUT)  # bound by 5a, not fail-closed


class ArbitrationTests(CoordinatorBase):
    def test_a_timeout_notice_beats_late_completion_and_applies_once(self):
        stub = self.stub("late")
        req = self.c.submit(("A", "local"), stub, pool="LOCAL", epoch=1)
        stub.started.wait(5)
        self.clock.advance(31)
        self.c.tick()
        self.assertEqual(req.state, RequestState.TIMED_OUT)
        stub.release.set()
        wait_for(lambda: self.c.stats("LOCAL")["abandoned_live"] == 0)
        messages = self.c.drain()
        self.assertEqual([type(m) for m in messages], [TerminalNotice])
        self.assertEqual(self.c.drain(), [])

    def test_b_old_late_result_after_newer_notice(self):
        old = self.stub("old")
        r1 = self.c.submit(("A", "github"), old, pool="GITHUB", epoch=1)
        old.started.wait(5)
        blocker = [self.stub(), self.stub()]
        for i, b in enumerate(blocker):  # occupy remaining GITHUB workers
            self.c.submit((f"x{i}", "github"), b, pool="GITHUB", epoch=1)
            b.started.wait(5)
        r2 = self.c.submit(("A", "github"), quick("new"), pool="GITHUB", epoch=1, deadline=5)
        self.assertEqual(r1.state, RequestState.SUPERSEDED)
        self.clock.advance(6)
        self.c.tick()
        old.release.set()
        wait_for(lambda: self.c.stats("GITHUB")["running"] == 2)
        messages = self.c.drain()
        a_messages = [m for m in messages if m.key == ("A", "github")]
        self.assertEqual(len(a_messages), 1)
        self.assertIsInstance(a_messages[0], TerminalNotice)
        self.assertEqual(a_messages[0].token, r2.token)

    def test_d_completion_wins_lock_so_watchdog_makes_no_notice(self):
        req = self.c.submit(("A", "local"), quick("done"), pool="LOCAL", epoch=1)
        wait_for(lambda: req.state == RequestState.COMPLETED)
        self.clock.advance(1000)
        self.c.tick()
        messages = self.c.drain()
        self.assertEqual([type(m) for m in messages], [WorkerResult])

    def test_e_newer_request_clears_older_notice(self):
        a, b = self.stub(), self.stub()
        self.c.submit(("A", "local"), a, pool="LOCAL", epoch=1)
        self.c.submit(("B", "local"), b, pool="LOCAL", epoch=1)
        a.started.wait(5)
        b.started.wait(5)
        self.c.submit(("C", "local"), quick(), pool="LOCAL", epoch=1, deadline=1)
        self.clock.advance(2)
        self.c.tick()
        self.assertEqual(self.c.slot_counts()[2], 1)
        self.c.submit(("C", "local"), quick(), pool="LOCAL", epoch=2)
        self.assertEqual(self.c.slot_counts()[2], 0)


class ExitGuaranteeTests(unittest.TestCase):
    def test_process_exits_with_wedged_worker_and_nothing_applies_after_close(self):
        script = (
            "import threading, time\n"
            "from scripts.dev_control_center.loader import Coordinator\n"
            "c = Coordinator()\n"
            "block = threading.Event()\n"
            "c.submit(('a','local'), lambda cancel: block.wait(), pool='LOCAL', epoch=1)\n"
            "c.submit(('b','local'), lambda cancel: 'x', pool='LOCAL', epoch=1)\n"
            "time.sleep(0.3)\n"
            "c.close()\n"
            "assert c.drain() == []\n"
        )
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLess(time.monotonic() - started, 15)


if __name__ == "__main__":
    unittest.main()
