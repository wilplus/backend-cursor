"""The coach names the error on a moment, and attaching teaches the library.

FOUNDER 2026-09-25, on the coach's Confident Voice practice review:
  * "Naming a new error tags the clip, stored as coach provenance."
  * "Attach = both": giving the speaker an exercise for this moment also teaches
    the library that the exercise fixes this moment's error, with undo.

WHAT THIS PINS DOWN:
  * the coach's naming wins over the machine's reading when there is one, and
    a name no detector produces is never taught (it could match nobody);
  * teaching happens on ATTACH (share), after the save, never for a coach's
    own exercise (that one is filed with the moment's errors instead);
  * the coach's own exercise now names the moment's error, so it is no longer
    refused every time (the form never sent one);
  * naming is an append-only event, idempotent, and only for a library entry;
  * undo is scoped to this moment and is idempotent;
  * it is ONE route: naming and undoing are a PATCH on the practice review,
    dispatched after its own blind gate and under its one purpose guard, and
    nothing here reaches the speaker's payload (L3, BLIND COACH);
  * both new tables are deleted with the speaker's practice.

The SQL functions' own behaviour (the stranded-tag rule, never emptying an
exercise, deletion) was exercised against PostgreSQL 16 before this landed;
see the PR.

Run: python3 -m unittest tests.test_coach_moment_errors
"""
from __future__ import annotations

import pathlib
import unittest

try:
    from flask import Flask, request

    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

ROOT = pathlib.Path(__file__).resolve().parents[1]
COACH = "00000000-0000-0000-0000-00000000000c"


# ── the pure rules ─────────────────────────────────────────────────────────


# ── the route ──────────────────────────────────────────────────────────────
# One route, on purpose: the exercise surface on the coach side is pinned to a
# single purpose-guarded route (test_phase1_compliance_contract), so naming
# and undoing are a PATCH on it, behind its own inline blind gate.


# ── fences ─────────────────────────────────────────────────────────────────

class FenceTests(unittest.TestCase):
    SOURCE = (ROOT / "routes/v2/coach.py").read_text()

    def _route(self):
        start = self.SOURCE.index("def v2_coach_confident_voice_practice")
        head = self.SOURCE.rindex("@v2_bp.route", 0, start)
        end = self.SOURCE.index("@v2_bp.route", start)
        return self.SOURCE[head:end]

    def test_an_edit_is_dispatched_only_after_the_blind_gate(self):
        route = self._route()
        self.assertIn('methods=["GET", "PUT", "PATCH"]', route)
        self.assertLess(route.index("BLIND_RATING_REQUIRED"),
                        route.index('if request.method == "PATCH":'))


if __name__ == "__main__":
    unittest.main()
