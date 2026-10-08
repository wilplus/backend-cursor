"""The arc's spoken Takes and the Take-count progress reader
(services/slide_selection.py).

The Best Presentation builder that used to live here is removed (founder
2026-10-05, N48.3 Q13 A; contract 52): the Ideal Text is the transcript of
the Take it is built from, never a best-of pick across Takes (L1).

Run: python3 -m pytest tests/test_slide_selection.py
"""
from __future__ import annotations

import pathlib
import unittest

import services.slide_selection as bp

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ProgressTests(unittest.TestCase):
    def test_counts_and_ready_threshold(self):
        self.assertEqual(bp.presentation_progress(0), {
            "takes_done": 0, "takes_target": 3, "takes_remaining": 3,
            "ready": False,
        })
        self.assertTrue(bp.presentation_progress(3)["ready"])
        self.assertTrue(bp.presentation_progress(4)["ready"])
        self.assertFalse(bp.presentation_progress(2)["ready"])
        self.assertEqual(bp.presentation_progress(-5)["takes_done"], 0)

    def test_takes_remaining_drives_the_two_more_message(self):
        self.assertEqual(bp.presentation_progress(1)["takes_remaining"], 2)
        self.assertEqual(bp.presentation_progress(3)["takes_remaining"], 0)
        self.assertEqual(bp.presentation_progress(5)["takes_remaining"], 0)


class SpokenSessionsTests(unittest.TestCase):
    def test_reads_and_paired_takes_are_excluded(self):
        sessions = [
            {"id": "a", "recording_kind": "spoken"},
            {"id": "b", "recording_kind": "read"},
            {"id": "c", "paired_session_id": "a"},
            {"id": "d"},
            None,
        ]
        self.assertEqual([s["id"] for s in bp.spoken_arc_sessions(sessions)],
                         ["a", "d"])


class BuilderRemovedTests(unittest.TestCase):
    """N48.3 Q13 A: the best-of builder is gone, not kept degraded."""

    def test_the_builder_and_best_of_selection_are_gone(self):
        for name in ("build_best_presentation", "_finalize_best_presentation",
                     "select_best_per_slide", "select_best_deckless",
                     "compose_presentation", "_bp_signature"):
            self.assertFalse(hasattr(bp, name), name)

    def test_nothing_in_production_names_the_builder(self):
        offenders = []
        for folder in ("routes", "services", "utils"):
            for path in (ROOT / folder).rglob("*.py"):
                src = path.read_text(encoding="utf-8")
                if "build_best_presentation(" in src \
                        or "assemble_ideal_text_block(" in src:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_the_report_module_is_gone(self):
        self.assertFalse((ROOT / "services" / "ideal_text_report.py").exists())


if __name__ == "__main__":
    unittest.main()
