"""DCC Task 19a: a single button chains PUSH -> BUILD -> UPDATE-DRY-RUN for an approved candidate,
stopping on the first failure and never reaching RELEASE.

Everything here is a fake: no real Tk window, no real App initialisation, no real git/push, no
real BUILD, no real distribution, no network. The app under test is built with `App.__new__`
(skipping `__init__`, so no Tk widget is ever created) and given only the plain-Python stand-ins
(FakeVar / FakeLog / FakeButton / FakeSelection) that the methods under test actually touch.
`_apply_lifecycle_state` and `_reload_after` are stubbed out: they belong to unrelated, already
covered screen state and are not part of this task.
"""

from __future__ import annotations

from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts.dev_control_center import app as dcc
from scripts.dev_control_center.core import RepoDefinition, RepoState


def fake_candidate(sha="a" * 40, run_id="20260101-000000-000001"):
    return SimpleNamespace(sha=sha, run_id=run_id, branch=f"ai-candidate/{run_id}-x")


class FakeVar:
    """Stand-in for tk.StringVar: just the get/set surface the app code touches."""

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class FakeLog:
    """Stand-in for the tk.Text log widget: just the subset `_log` / `_log_process` touch."""

    def __init__(self) -> None:
        self._text = ""

    def configure(self, **_kwargs) -> None:
        pass

    def insert(self, _index: str, text: str) -> None:
        self._text += text

    def index(self, _spec: str) -> str:
        return f"{self._text.count(chr(10)) + 1}.0"

    def delete(self, _start: str, _end: str) -> None:
        pass

    def see(self, _index: str) -> None:
        pass

    def get(self, _start: str, _end: str) -> str:
        return self._text


class FakeButton:
    """Stand-in for a ttk.Button: only the state()/configure() calls `_set_button_states` makes."""

    def __init__(self) -> None:
        self._flags: set[str] = set()

    def state(self, spec=None):
        if spec is None:
            return tuple(self._flags)
        for flag in spec:
            if flag.startswith("!"):
                self._flags.discard(flag[1:])
            else:
                self._flags.add(flag)
        return tuple(self._flags)

    def configure(self, **_kwargs) -> None:
        pass


class FakeSelection:
    """Stand-in for SelectionState: only `.current` and the two methods the drain path calls."""

    def __init__(self, definition: RepoDefinition) -> None:
        self.current = definition
        self.post_action_notice: dict[str, str] = {}

    def process_boundary(self, _repo_name: str, _event: str) -> bool:
        return False


class CombinedRunCase(unittest.TestCase):
    def setUp(self):
        dcc.ACTIVE_OPERATIONS.clear()
        self.addCleanup(dcc.ACTIVE_OPERATIONS.clear)
        self.definition = RepoDefinition("combined-run-app", "desktop", "ai-candidate/x")
        self.ui = dcc.App.__new__(dcc.App)
        self.ui.selection = FakeSelection(self.definition)
        self.ui.flow = {}
        self.ui.lifecycle_events = queue.Queue()
        self.ui.lifecycle_jobs = {}
        self.ui.lifecycle_cancellations = {}
        self.ui.lifecycle_after = {}
        self.ui.combined_run_tokens = {}
        self.ui.active_process = None
        self.ui._stream_key = None
        self.ui._stream_open = False
        self.ui.banner_var = FakeVar("")
        self.ui.log = FakeLog()
        self.ui.master = SimpleNamespace()
        # Unrelated, already-covered screen state: not part of this task, stubbed to a no-op.
        self.ui._apply_lifecycle_state = lambda: None
        self.ui._reload_after = lambda repo_name: None

        engine = patch.object(dcc.release_update, "engine_repo", return_value=True)
        engine.start()
        self.addCleanup(engine.stop)
        profiles = patch.object(dcc.provenance, "PROFILES", {})
        profiles.start()
        self.addCleanup(profiles.stop)

    def approved_flow(self) -> dict:
        return {"can_push": True, "active": True, "candidate": fake_candidate()}

    def finish(self, action: str, rc: int) -> None:
        self.ui.lifecycle_events.put(("finished", object(), self.definition.name, action, rc))

    def log_text(self) -> str:
        return self.ui.log.get("1.0", "end")

    def pump_until(self, condition, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.ui._drain_lifecycle_events()
            time.sleep(0.01)
        self.assertTrue(condition())


class ButtonStateTests(CombinedRunCase):
    def setUp(self):
        super().setUp()
        self.ui.approve_button = FakeButton()
        self.ui.push_button = FakeButton()
        self.ui.discard_button = FakeButton()
        self.ui.combined_button = FakeButton()

    def test_disabled_without_an_approved_sha(self):
        self.ui.flow[self.definition.name] = {"can_push": False, "active": True, "candidate": None}
        self.ui._set_button_states()
        self.assertIn("disabled", self.ui.combined_button.state())

    def test_enabled_once_approved_on_a_common_engine_repo(self):
        self.ui.flow[self.definition.name] = self.approved_flow()
        self.ui._set_button_states()
        self.assertNotIn("disabled", self.ui.combined_button.state())

    def test_disabled_when_the_repo_does_not_use_the_common_engine(self):
        self.ui.flow[self.definition.name] = self.approved_flow()
        with patch.object(dcc.release_update, "engine_repo", return_value=False):
            self.ui._set_button_states()
        self.assertIn("disabled", self.ui.combined_button.state())


class CancelTests(CombinedRunCase):
    def test_cancelling_the_confirmation_runs_nothing(self):
        self.ui.flow[self.definition.name] = self.approved_flow()
        with patch.object(dcc.messagebox, "askyesno", return_value=False) as ask, \
             patch.object(self.ui, "_start_lifecycle") as start:
            self.ui.push_build_dry_run()
        ask.assert_called_once()
        start.assert_not_called()
        self.assertEqual(dcc.ACTIVE_OPERATIONS, {})
        self.assertNotIn(self.definition.name, self.ui.lifecycle_after)


class ChainTests(CombinedRunCase):
    """Drives the real chain: only `_start_lifecycle`, the confirmation dialog, the BUILD folder
    pick and the BUILD inspection inputs are faked; everything else is the app's own code."""

    def start_chain(self, start_mock):
        self.ui.flow[self.definition.name] = self.approved_flow()
        self.ui.push_build_dry_run()
        self.pump_until(lambda: start_mock.call_count == 1)

    def build_patches(self):
        state = RepoState(True, True, head="a" * 40, origin_repo=self.definition.full_name)
        entries = MagicMock(build=MagicMock(ready=True, path=Path("entry.py")))
        return (
            patch.object(dcc, "inspect_repo", return_value=state),
            patch("scripts.dev_control_center.core.discover_entrypoints", return_value=entries),
            patch.object(dcc.machine_entries, "supported", return_value=True),
            patch.object(dcc.candidate_flow, "build_gate", return_value=None),
            patch.object(dcc.filedialog, "askdirectory", return_value="C:/combined-run-out"),
        )

    def test_push_build_and_dry_run_each_run_once_in_order(self):
        patches = self.build_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.assertEqual(start.call_args_list[0].args[1:], (self.definition.name, "push"))
            self.finish("push", 0)

            self.pump_until(lambda: start.call_count == 2)
            self.assertEqual(start.call_args_list[1].args[1:], (self.definition.name, "build"))
            self.finish("build", 0)

            self.pump_until(lambda: start.call_count == 3)
            self.assertEqual(start.call_args_list[2].args[1:], (self.definition.name, "update-dry-run"))
            self.finish("update-dry-run", 0)

            self.pump_until(lambda: "RELEASEの準備ができました" in self.log_text())
        self.assertEqual(start.call_count, 3)
        self.assertNotIn("release", [c.args[2] for c in start.call_args_list])
        self.assertEqual(dcc.ACTIVE_OPERATIONS, {})  # reservation released once the run is done

    def test_a_push_failure_stops_before_build_and_shows_the_fixed_reason(self):
        with patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 1)
            self.pump_until(lambda: self.definition.name not in self.ui.lifecycle_after)
        self.assertEqual(start.call_count, 1)
        self.assertIn(f"{self.definition.name}: PUSH 失敗 rc=1", self.log_text())
        self.assertNotIn("RELEASEの準備ができました", self.ui.banner_var.get())
        self.assertEqual(dcc.ACTIVE_OPERATIONS, {})  # reservation released: a retry can start

    def test_a_build_failure_stops_before_dry_run_and_shows_the_fixed_reason(self):
        patches = self.build_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: start.call_count == 2)
            self.finish("build", 1)
            self.pump_until(lambda: self.definition.name not in self.ui.lifecycle_after)
        self.assertEqual(start.call_count, 2)
        self.assertEqual([c.args[2] for c in start.call_args_list], ["push", "build"])
        self.assertIn(f"{self.definition.name}: BUILD 失敗 rc=1", self.log_text())
        self.assertNotIn("RELEASEの準備ができました", self.ui.banner_var.get())
        self.assertEqual(dcc.ACTIVE_OPERATIONS, {})

    def test_a_dry_run_failure_shows_the_fixed_reason_and_no_release_ready_text(self):
        patches = self.build_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: start.call_count == 2)
            self.finish("build", 0)
            self.pump_until(lambda: start.call_count == 3)
            self.finish("update-dry-run", 1)
            self.pump_until(lambda: self.definition.name not in self.ui.lifecycle_after)
        self.assertEqual(start.call_count, 3)
        self.assertEqual([c.args[2] for c in start.call_args_list], ["push", "build", "update-dry-run"])
        self.assertIn(f"{self.definition.name}: UPDATE-DRY-RUN 失敗 rc=1", self.log_text())
        self.assertNotIn("RELEASEの準備ができました", self.ui.banner_var.get())
        self.assertEqual(dcc.ACTIVE_OPERATIONS, {})

    def test_release_is_never_called_and_only_one_confirmation_is_shown(self):
        patches = self.build_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch.object(dcc.messagebox, "askyesno", return_value=True) as ask, \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: start.call_count == 2)
            self.finish("build", 0)
            self.pump_until(lambda: start.call_count == 3)
            self.finish("update-dry-run", 0)
            self.pump_until(lambda: "RELEASEの準備ができました" in self.log_text())
        self.assertNotIn("release", [c.args[2] for c in start.call_args_list])
        ask.assert_called_once()  # only the initial "run these 3 stages?" confirmation

    def test_folder_picks_between_stages_block_other_operations(self):
        """DCC Task 19a review finding: the reservation must survive both modal folder picks that
        happen while the combined run is between subprocess stages -- BUILD's own artifact-folder
        pick (no PROFILES entry for this fake repo) and this run's own distribution-folder pick
        before UPDATE-DRY-RUN. While either is open, another combined run or an individual
        operation on the same repo must be refused; once it closes, the run continues."""
        state = RepoState(True, True, head="a" * 40, origin_repo=self.definition.full_name)
        entries = MagicMock(build=MagicMock(ready=True, path=Path("entry.py")))
        observed: list[bool] = []

        def pick_folder(*_args, **_kwargs):
            observed.append(self.ui._repo_busy())
            with patch.object(self.ui, "_start_lifecycle") as blocked:
                self.ui.push_build_dry_run()
                self.ui.push_candidate()
            observed.append(blocked.called)
            return "C:/combined-run-out"

        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints", return_value=entries), \
             patch.object(dcc.machine_entries, "supported", return_value=True), \
             patch.object(dcc.candidate_flow, "build_gate", return_value=None), \
             patch.object(dcc.filedialog, "askdirectory", side_effect=pick_folder), \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: start.call_count == 2)   # BUILD started; its own folder pick ran
            self.finish("build", 0)
            self.pump_until(lambda: start.call_count == 3)   # this run's own folder pick ran too
            self.finish("update-dry-run", 0)
            self.pump_until(lambda: "RELEASEの準備ができました" in self.log_text())

        # Both folder picks (BUILD's own, and this run's) saw the repo busy and refused the
        # competing operation attempted from inside them.
        self.assertEqual(observed, [True, False, True, False])
        self.assertEqual(dcc.ACTIVE_OPERATIONS, {})


class TerminationLeakRegressionTests(ChainTests):
    """DCC Task 19a review findings (round 2): the combined run's whole-run reservation must be
    released on termination paths that don't go through a stage's own success/failure `after`
    callback -- a cancelled BUILD folder pick, a failed BUILD precondition check, and an explicit
    stop. Inherits `build_patches`/`start_chain` from ChainTests; each test below overrides just
    the one fake that triggers its termination path."""

    def test_build_folder_pick_cancel_releases_the_reservation(self):
        state = RepoState(True, True, head="a" * 40, origin_repo=self.definition.full_name)
        entries = MagicMock(build=MagicMock(ready=True, path=Path("entry.py")))
        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints", return_value=entries), \
             patch.object(dcc.machine_entries, "supported", return_value=True), \
             patch.object(dcc.candidate_flow, "build_gate", return_value=None), \
             patch.object(dcc.filedialog, "askdirectory", return_value=""), \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: dcc.ACTIVE_OPERATIONS == {})
        self.assertEqual(start.call_count, 1)  # BUILD's own subprocess never started
        self.assertEqual(self.ui.combined_run_tokens, {})
        self.assertNotIn("RELEASEの準備ができました", self.ui.banner_var.get())

    def test_build_precondition_failure_releases_the_reservation(self):
        state = RepoState(True, True, head="a" * 40, origin_repo=self.definition.full_name)
        entries = MagicMock(build=MagicMock(ready=True, path=Path("entry.py")))
        with patch.object(dcc, "inspect_repo", return_value=state), \
             patch("scripts.dev_control_center.core.discover_entrypoints", return_value=entries), \
             patch.object(dcc.machine_entries, "supported", return_value=True), \
             patch.object(dcc.candidate_flow, "build_gate", side_effect=ValueError("build_gate: precondition failed")), \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: dcc.ACTIVE_OPERATIONS == {})
        self.assertEqual(start.call_count, 1)  # BUILD's own subprocess never started
        self.assertEqual(self.ui.combined_run_tokens, {})
        self.assertIn("BUILD停止", self.ui.banner_var.get())
        self.assertNotIn("RELEASEの準備ができました", self.ui.banner_var.get())

    def test_explicit_stop_mid_run_releases_the_reservation_and_stops_the_chain(self):
        patches = self.build_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.start_chain(start)
            self.finish("push", 0)
            self.pump_until(lambda: start.call_count == 2)  # BUILD's own subprocess "started"

            # Simulate BUILD's subprocess actually running, then an explicit stop through the
            # existing stop button's own handler (confirmation + cancel.set()).
            self.ui.lifecycle_jobs[self.definition.name] = object()
            self.ui.lifecycle_cancellations[self.definition.name] = threading.Event()
            self.ui.stop_lifecycle()
            self.assertTrue(self.ui.lifecycle_cancellations[self.definition.name].is_set())
            self.finish("build", 1)
            self.pump_until(lambda: dcc.ACTIVE_OPERATIONS == {})
        self.assertEqual(start.call_count, 2)  # UPDATE-DRY-RUN never started
        self.assertIn(f"{self.definition.name}: BUILD 停止 rc=1", self.log_text())
        self.assertNotIn("RELEASEの準備ができました", self.ui.banner_var.get())
        self.assertEqual(self.ui.combined_run_tokens, {})

        # The reservation being gone means the repo can be retried (here: a fresh combined run;
        # the same ACTIVE_OPERATIONS check also guards every individual PUSH/BUILD/UPDATE button).
        with patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as retry:
            self.ui.push_build_dry_run()
        retry.assert_called_once()


class ExclusivityTests(CombinedRunCase):
    def test_a_busy_repo_refuses_to_start_the_combined_run(self):
        self.ui.flow[self.definition.name] = self.approved_flow()
        token = object()
        dcc.ACTIVE_OPERATIONS[id(token)] = (self.definition.name, "build")
        try:
            with patch.object(dcc.messagebox, "askyesno") as ask, \
                 patch.object(self.ui, "_start_lifecycle") as start:
                self.ui.push_build_dry_run()
            ask.assert_not_called()
            start.assert_not_called()
        finally:
            dcc.ACTIVE_OPERATIONS.pop(id(token), None)

    def test_a_second_combined_run_is_refused_while_the_first_is_active(self):
        self.ui.flow[self.definition.name] = self.approved_flow()
        with patch.object(dcc.messagebox, "askyesno", return_value=True) as ask, \
             patch.object(self.ui, "_start_lifecycle", return_value=True) as start:
            self.ui.push_build_dry_run()  # first run: reserves the repo, starts PUSH
            self.assertEqual(start.call_count, 1)
            self.ui.push_build_dry_run()  # second attempt while the first is still active
            ask.assert_called_once()      # the second call never even reaches its own confirmation
            self.assertEqual(start.call_count, 1)

    def test_an_individual_push_is_refused_while_the_combined_run_is_active(self):
        self.ui.flow[self.definition.name] = self.approved_flow()
        with patch.object(dcc.messagebox, "askyesno", return_value=True), \
             patch.object(self.ui, "_start_lifecycle", return_value=True):
            self.ui.push_build_dry_run()
        with patch.object(self.ui, "_start_lifecycle") as individual_start:
            self.ui.push_candidate()
        individual_start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
