"""The jar's evaluation reaches the founder's pace panel (founder 2026-09-30,
B8, C9; E9: "the bar (300 attempts, 30 per exercise) stays; a descriptive
weekly view instead"; W6 2026-10-05).

The per-exercise counts and the "two piles" evaluation lost their only page
with /cms/jar. The founder-only ledger route now carries both: the counts
in ``ledger.exercise_jar`` (readiness, unchanged) and the evaluation in a
top-level ``jar_evaluation``, which is ``evaluate_jar`` gated on that same
count, unchanged: sealed and why below the bar, both piles above it.

Pins: the key is served beside ``gaps``; it is exactly ``evaluate_jar``
with the ledger's own count as the gate (no second read); a sealed answer
says sealed; a failing evaluation is None, never unsealed; the route stays
founder-only.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

from services.exercise_evaluation import evaluate_jar as REAL_EVALUATE_JAR

try:
    from flask import Flask
    from routes.v2 import learning_admin
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    _IMPORT_ERROR = e

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAR = {"counted": 12, "ready": False, "why_not": "12 of 300 first-exposure attempts with a valid endpoint",
       "exercises": [{"exercise_id": "land-it", "exposures": 20, "cohort": 14, "counted": 12, "needed": 30}],
       "bar": {"min_counted": 300, "min_per_exercise": 30}}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheLedgerRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, evaluate=None):
        calls = []

        def evaluate_jar(database, gate=None):
            calls.append(gate)
            if evaluate is not None:
                return evaluate(database, gate)
            return REAL_EVALUATE_JAR(database, gate=gate)

        raw = learning_admin.v2_admin_learning_ledger.__wrapped__
        with self.app.test_request_context(), \
                patch("services.learning_ledger.ledger",
                      return_value={"exercise_jar": JAR, "pairs": {}, "shadow_cues": {}}), \
                patch("services.exercise_gaps.gap_view", return_value={"rows": []}), \
                patch.object(learning_admin.db, "list_ledger_snapshots", return_value=[]), \
                patch("services.exercise_evaluation.evaluate_jar", side_effect=evaluate_jar):
            out = raw()
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status, calls

    def test_the_evaluation_rides_beside_the_gaps_gated_on_the_ledger_s_own_count(self):
        body, status, calls = self._get()
        self.assertEqual(status, 200)
        self.assertIn("gaps", body)
        self.assertEqual(calls, [JAR], "the ledger's own count is the gate")
        evaluation = body["jar_evaluation"]
        self.assertTrue(evaluation["sealed"])
        self.assertEqual(evaluation["why_not"], JAR["why_not"])
        self.assertEqual(evaluation["bar"], {"min_counted": 300, "min_per_exercise": 30})
        self.assertTrue(evaluation["requires_founder_approval"])
        self.assertFalse(evaluation["promotes"])
        self.assertNotIn("machine_only", evaluation)
        # The per-exercise counts ride the ledger's jar, unchanged.
        self.assertEqual(body["ledger"]["exercise_jar"]["exercises"][0]["needed"], 30)

    def test_it_is_evaluate_jar_unchanged(self):
        stand_in = {"sealed": False, "machine_only": {"scoreboard": {}}, "anything": 1}
        body, _status, _calls = self._get(evaluate=lambda _db, _gate: stand_in)
        self.assertEqual(body["jar_evaluation"], stand_in)

    def test_a_failing_evaluation_is_none_never_unsealed(self):
        def broken(_db, _gate):
            raise RuntimeError("down")
        body, status, _calls = self._get(evaluate=broken)
        self.assertEqual(status, 200)
        self.assertIsNone(body["jar_evaluation"])

    def test_the_route_is_founder_only(self):
        source = (ROOT / "routes" / "v2" / "learning_admin.py").read_text()
        head = source[:source.index("def v2_admin_learning_ledger(")].rsplit("@v2_bp.route", 1)[1]
        self.assertIn("@require_founder", head)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
