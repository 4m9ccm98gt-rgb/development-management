"""DCC checkbox/radiobutton dark-theme contrast (bug: hover/pressed turned the background
white, matching the already-light text color and making the label unreadable).

Uses a fake ttk.Style that records configure()/map() calls instead of a real Tk
interpreter, so this never opens an actual window; all style data lives in memory only.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.dev_control_center import app as dcc

ROOT = Path(__file__).resolve().parents[1]

WHITE_LIKE = {"#ffffff", "#fff", "white"}


class _FakeMaster:
    def configure(self, **_kwargs):
        pass


class _RecordingStyle:
    """Stand-in for ttk.Style: records every configure()/map() call per style name
    instead of touching a real Tcl interpreter."""

    def __init__(self, _master=None):
        self.configured: dict[str, dict] = {}
        self.mapped: dict[str, dict] = {}

    def theme_use(self, _name):
        pass

    def configure(self, style_name, **kwargs):
        self.configured.setdefault(style_name, {}).update(kwargs)

    def map(self, style_name, **kwargs):
        self.mapped.setdefault(style_name, {}).update(kwargs)

    def state_value(self, option, style_name, state_name):
        """Resolve the value ttk.Style.lookup would pick for a single named state:
        first entry in the map list whose statespec contains state_name, else the
        plain configure() default."""
        for statespec, value in self.mapped.get(style_name, {}).get(option, []):
            if state_name in statespec:
                return value
        return self.configured.get(style_name, {}).get(option)


class CheckbuttonRadiobuttonThemeTests(unittest.TestCase):
    def setUp(self):
        self.style_instances: list[_RecordingStyle] = []

        def _style_factory(master=None):
            style = _RecordingStyle(master)
            self.style_instances.append(style)
            return style

        patcher = patch.object(dcc.ttk, "Style", side_effect=_style_factory)
        patcher.start()
        self.addCleanup(patcher.stop)
        dcc.configure_dark_theme(_FakeMaster())
        self.style = self.style_instances[-1]

    def test_both_styles_are_configured_from_dark_palette(self):
        for style_name in ("TCheckbutton", "TRadiobutton"):
            base = self.style.configured.get(style_name)
            self.assertIsNotNone(base, f"{style_name} was not configured")
            self.assertEqual(base.get("background"), dcc.DARK_BG)
            self.assertEqual(base.get("foreground"), dcc.DARK_FG)

            state_map = self.style.mapped.get(style_name)
            self.assertIsNotNone(state_map, f"{style_name} has no style.map()")
            for state in ("active", "pressed", "selected", "disabled"):
                fg = self.style.state_value("foreground", style_name, state)
                bg = self.style.state_value("background", style_name, state)
                self.assertIsNotNone(fg, f"{style_name}/{state} has no foreground")
                self.assertIsNotNone(bg, f"{style_name}/{state} has no background")

    def test_hover_and_pressed_keep_foreground_background_distinct_and_not_white_on_white(self):
        for style_name in ("TCheckbutton", "TRadiobutton"):
            for state in ("active", "pressed"):
                fg = self.style.state_value("foreground", style_name, state)
                bg = self.style.state_value("background", style_name, state)
                self.assertNotEqual(
                    fg.lower(), bg.lower(),
                    f"{style_name}/{state}: foreground equals background ({fg})",
                )
                self.assertFalse(
                    fg.lower() in WHITE_LIKE and bg.lower() in WHITE_LIKE,
                    f"{style_name}/{state}: both foreground and background are white-like",
                )

    def test_dark_theme_colors_feed_the_states_directly(self):
        # Every color used across the two styles must trace back to a DARK_* constant
        # defined in app.py, not an ad-hoc literal unrelated to the dark palette.
        dark_values = {
            getattr(dcc, name) for name in dir(dcc)
            if name.startswith("DARK_") and isinstance(getattr(dcc, name), str)
        }
        dark_values |= WHITE_LIKE
        for style_name in ("TCheckbutton", "TRadiobutton"):
            for option in ("foreground", "background"):
                for _statespec, value in self.style.mapped[style_name][option]:
                    self.assertIn(value.lower(), {v.lower() for v in dark_values})


class CheckbuttonUsesSharedStyleTests(unittest.TestCase):
    def test_reports_inbox_checkbuttons_use_the_default_checkbutton_style(self):
        text = (ROOT / "scripts" / "dev_control_center" / "reports_inbox_view.py").read_text(encoding="utf-8")
        checkbutton_calls = [line for line in text.splitlines() if "ttk.Checkbutton(" in line]
        self.assertEqual(len(checkbutton_calls), 4, checkbutton_calls)
        for line in checkbutton_calls:
            self.assertNotIn("style=", line)


if __name__ == "__main__":
    unittest.main()
