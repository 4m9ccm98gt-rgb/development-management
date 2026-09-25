"""Real Tk hover regression with DCC's 50ms heartbeat running."""
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, PropertyMock, patch
from scripts.dev_control_center import app as dcc
from scripts.dev_control_center.app_setup import App


class HoverTests(unittest.TestCase):
    def setUp(self):
        for target, name in ((dcc.App, 'scan_remote_repos'), (dcc.App, 'check_self_update'),
                             (dcc.SelectionState, '_fire')):
            p = patch.object(target, name); p.start(); self.addCleanup(p.stop)
        self.decision = SimpleNamespace(sync_enabled=False, run_enabled=True, build_enabled=True,
            release_enabled=True, candidate_sha='', candidate_source='-', banner='test')
        for p in (patch.object(dcc.App, 'repo_state', new_callable=PropertyMock, return_value=MagicMock()),
                  patch.object(dcc.App, 'entrypoints', new_callable=PropertyMock, return_value=MagicMock()),
                  patch.object(dcc, 'decide_lifecycle', return_value=self.decision)):
            p.start(); self.addCleanup(p.stop)
        self.root = tk.Tk()
        self.ui = App(self.root)
        self.root.geometry('1080x720')
        self.root.update()
        self.ui._set_button_states()
        self.addCleanup(self.ui._on_close)
        self.style = ttk.Style(self.root)

    def color(self, button):
        return self.style.lookup('TButton', 'background', button.state())

    def test_four_buttons_hold_hover_over_five_seconds_of_heartbeat(self):
        for name in ('run_button', 'build_button', 'release_button', 'orchestrator_button'):
            with self.subTest(button=name):
                b = getattr(self.ui, name)
                identity = str(b)
                b.event_generate('<Enter>')
                deadline = time.monotonic() + 5.1
                while time.monotonic() < deadline:
                    self.root.update()
                    self.assertTrue(b.instate(['active', '!disabled']))
                    self.assertEqual(self.color(b), dcc.DARK_ACCENT)
                    time.sleep(.01)
                self.assertEqual(str(getattr(self.ui, name)), identity)
                b.event_generate('<Leave>'); self.root.update()
                self.assertFalse(b.instate(['active']))
                self.assertEqual(self.color(b), dcc.DARK_FIELD)

    def test_pressed_disabled_and_click_dispatch_survive_refresh(self):
        for name, action, field in (('run_button', 'run', 'run_enabled'),
                                   ('build_button', 'build', 'build_enabled'),
                                   ('release_button', 'release', 'release_enabled')):
            with self.subTest(button=name), patch.object(self.ui, 'launch') as launch:
                b = getattr(self.ui, name)
                b.event_generate('<Enter>'); b.event_generate('<ButtonPress-1>', x=5, y=5)
                self.ui._set_button_states()
                self.assertTrue(b.instate(['pressed', 'active']))
                self.assertEqual(self.color(b), dcc.DARK_SELECTION)
                b.event_generate('<ButtonRelease-1>', x=5, y=5)
                launch.assert_called_once_with(action)
                setattr(self.decision, field, False)
                self.ui._set_button_states()
                self.assertTrue(b.instate(['disabled']))
                self.assertEqual(self.color(b), dcc.DARK_DISABLED_BG)
                launch.reset_mock(); b.invoke(); launch.assert_not_called()
                setattr(self.decision, field, True)
                self.ui._set_button_states()
                self.assertTrue(b.instate(['!disabled', 'active']))
                b.event_generate('<Leave>')
        self.assertTrue(self.ui.orchestrator_button.instate(['!disabled']))


if __name__ == '__main__':
    unittest.main()
