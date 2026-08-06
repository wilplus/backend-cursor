"""The acoustic-targets surface stays dark until founder sign-off.

WHY. Restoring the session globals (2026-08-06) repopulates `global_wpm`,
`global_fillers` and `global_dynamic_db`, which had been NULL on every session
since 2026-06-01. Those three feed `compute_acoustic_targets`, whose output
STEP 8 renders with the instruction to "keep the NUMBERS verbatim (WPM, dB,
filler counts)" plus `triggers=['show_acoustic_targets_card']`.

So a fix aimed at telemetry would have silently switched a user-facing surface
back on, with copy nobody reviewed. That is the shape the decision filter's
STEP 2 exists to catch — a fence breach arriving as a side effect of something
that is genuinely an F1-surface fix.

THE TEST IS NOT "no digits". SpeechDataPanel shows wpm/Hz/dB to users on
purpose. Its header states the operative rule: those figures are "reference
DATA, never a verdict. No best/worst flag, no direction guess, no
characterization." A prescriptive numeric TARGET is a direction, and "you were
at 132" against a goal of 145 is a shortfall verdict.

Run: python3 -m unittest test_acoustic_targets_held
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent


class TestTheSurfaceIsHeld(unittest.TestCase):

    def test_the_route_does_not_pass_globals_into_the_targets(self):
        """The gate itself. If a future edit drops the conditional, the
        numbers reach STEP 8 on the next recording."""
        source = (ROOT / "routes" / "v2" / "coaching.py").read_text()
        self.assertIn("_ACOUSTIC_TARGETS_SIGNED_OFF = False", source,
                      "the acoustic-targets hold has been removed or renamed")

    def test_no_globals_yields_no_targets(self):
        """Behaviour-preserving: this is exactly what every session has done
        since 2026-06-01, and must keep doing until the copy is signed off."""
        from services.coaching_state_machine import compute_acoustic_targets
        out = compute_acoustic_targets(
            global_wpm=None, global_fillers=None,
            global_dynamic_db=None, session_duration_ms=None)
        for key in ("target_wpm", "target_dynamic_db", "target_fillers_total"):
            self.assertIsNone(out[key], f"{key} materialised from nothing")

    def test_the_fallback_line_carries_no_number(self):
        """What users actually get while the surface is held — the
        qualitative seed. It must stay free of digits."""
        from services.coaching_state_machine import (
            _format_acoustic_targets_for_prompt,
        )
        line = _format_acoustic_targets_for_prompt(
            target_wpm=None, target_db=None, target_fillers_total=None,
            target_fillers_per_min=None, current_wpm=None,
            current_fillers=None)
        self.assertFalse(any(ch.isdigit() for ch in line),
                         f"the qualitative fallback grew a number: {line!r}")

    def test_populated_targets_would_emit_numbers(self):
        """Pins WHY the hold exists rather than asserting it in a comment. If
        this ever stops producing digits the surface has been made compliant
        and the hold can be reconsidered — this failing is good news."""
        from services.coaching_state_machine import (
            _format_acoustic_targets_for_prompt,
        )
        line = _format_acoustic_targets_for_prompt(
            target_wpm=145, target_db=18.5, target_fillers_total=12,
            target_fillers_per_min=1.0, current_wpm=132.0, current_fillers=19)
        self.assertTrue(any(ch.isdigit() for ch in line))
        self.assertIn("145", line)
        self.assertIn("132", line)      # the implicit shortfall verdict


class TestBenchmarksOutsideTheRegistry(unittest.TestCase):
    """D31 — the registry is the single source for thresholds, and
    "hardcoding any of these values elsewhere is a bug, whatever it looks
    like". These three predate the registry and are recorded, not fixed:
    moving them is a behaviour change on a live surface and belongs with the
    sign-off, not smuggled in beside a telemetry fix."""

    def test_the_known_hardcoded_thresholds_are_still_only_these_three(self):
        source = (ROOT / "services" / "coaching_state_machine.py").read_text()
        tree = ast.parse(source)
        hardcoded = {
            node.targets[0].id
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, (int, float))
            and not isinstance(node.value.value, bool)
            and ("WPM" in node.targets[0].id or "FILLER" in node.targets[0].id)
        }
        self.assertEqual(
            hardcoded, {"_IDEAL_WPM_MIN", "_IDEAL_WPM_MAX",
                        "_TARGET_FILLERS_PER_MIN"},
            "a benchmark constant was added or removed outside the dimension "
            "registry (D31) — the registry is the single source for "
            "thresholds and these three are a known, recorded exception")


if __name__ == "__main__":
    unittest.main()
