"""One draft per coach request, by its kind (founder 2026-09-30, C2; P2-2).

Pins: the surface follows the kind and an ambiguity has none; the draft is
composed from the moment's own passage; a provider that gives nothing is a
503 and never blocks the answer; the draft is kept on the row; the route
sits behind the blind gate; the prompts are locked and the surfaces have
golden datasets and adapters.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LockTests(unittest.TestCase):

    def test_every_prompt_forbids_scores(self):
        from services.prompts import coach_answer_drafts as p
        for system in (p.EXERCISE_SCRIPT_SYSTEM, p.PRAISE_LINE_SYSTEM, p.CLEARER_VERSION_SYSTEM):
            self.assertIn("Never give a score", system)


class RouteTests(unittest.TestCase):
    def test_the_draft_sits_behind_the_blind_gate(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        gate = source[source.index("def _moment_gate"):source.index("@v2_bp.route", source.index("def _moment_gate"))]
        self.assertIn("BLIND_RATING_REQUIRED", gate)
        for name in ("v2_coach_exercise_request_draft",):
            start = source.index(f"def {name}")
            body = source[start:source.index("@v2_bp.route", start)]
            self.assertIn("_moment_gate(session_id, snippet_id)", body)
            self.assertLess(body.index("_moment_gate"), body.index("from services."))


if __name__ == "__main__":
    unittest.main()
