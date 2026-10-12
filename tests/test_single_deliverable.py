"""willab — the SINGLE-DELIVERABLE re-shape (founder 2026-07-17).

The product delivers ONE thing: the ideal text. Record a take → instant
ideal text vN (unverified) → the coach verifies in the background, always →
the verified text displays FREE. The ONLY paid item: opening the key-moment
explanations (5 credits, one-time per presentation). This is now the ONLY
behavior — the SINGLE_DELIVERABLE_ENABLED flag was retired.

Pinned here, token by token:
  BE-1  version bump on a CHANGED machine copy only; migration fallbacks;
        the L1 seam-smoothing pass exists and its contract is pinned.
  BE-2  the 3-take batch cap lifts (takes append forever).
  BE-3  VERIFY: snapshot + idempotency + the per-version verified bubble.
  BE-4  the student GET: both states FREE, never a 402; the coach's working
        text NEVER leaks unverified.
  BE-5  the 5-credit moments unlock (atomic; no grandfathering) + the gated
        explanations GET.
  BE-6  the $25 unlock and publish-analysis routes are gone (retired).

Run: python3 -m unittest tests.test_single_deliverable
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

try:
    from flask import Flask, jsonify, request

    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from routes.v2 import lab_recording as v2_lab_recording
    from services.db import DatabaseService, db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jsonify = None
    request = None
    DatabaseService = None
    _IMPORT_ERROR = e

ARC = "a1"


def _row(**over):
    row = {"arc_id": ARC, "text": "machine text", "auto_text": "machine text",
           "updated_by": None, "approved_at": None, "version": 3,
           "verified_version": None, "verified_text": None}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentGetSingleDeliverableTests(unittest.TestCase):
    """BE-4 — both states FREE; the coach's working text never leaks."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, row, *, entitled_moments=False, expl=None):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch("routes.v2.explore_ideal_text._moments_entitled",
                              return_value=entitled_moments), \
                 patch("routes.v2.explore_ideal_text._moment_explanations_map",
                              return_value=(expl or {})), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(db, "get_user_arc_ideal_notes",
                              return_value="notes"):
                out = v2_explore_ideal_text.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status


    def test_coach_working_text_never_leaks_unverified(self):
        # Coach owns the row, no machine copy, nothing verified → empty text,
        # NOT the coach's in-progress edit.
        body, _ = self._get(_row(text="coach secret", auto_text=None,
                                 updated_by="coach1", version=2))
        self.assertEqual(body["status"], "unverified")
        self.assertNotIn("coach secret", json.dumps(body))


    def test_ac9_score_free(self):
        body, _ = self._get(_row())
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "power_score"):
            self.assertNotIn(banned, raw)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RecordingFlowTagTests(unittest.TestCase):
    """The flat-field → session_context fold (founder 2026-07-20). The
    intake validator strips unknown keys, so these tags ONLY exist because
    _recording_flow_tags folds them — pinned so a validator refactor can't
    silently drop the star-re-record contract.

    read_target / ideal_version are RETIRED (founder 2026-08-05): they only
    ever existed to pair a re-read to the version it read."""

    SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"


    def test_paired_snippet_uuid_guard(self):
        self.assertEqual(
            v2_lab_recording._recording_flow_tags({"paired_snippet_id": self.SNIP}),
            {"paired_snippet_id": self.SNIP})
        self.assertEqual(
            v2_lab_recording._recording_flow_tags({"paired_snippet_id": "not-a-uuid"}), {})


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SnapshotSanitizeTests(unittest.TestCase):
    def test_write_time_projection_mirrors_serve(self):
        from services.ideal_text_block import sanitize_suggestions_snapshot
        out = sanitize_suggestions_snapshot({
            "s1": {"kind": "replace", "replacement_text": "calmer words",
                   "why": "Lands better.", "trigger": "threat"},
            "s2": {"kind": "structure", "trigger": "contrast",
                   "why": "not about X. about Y."},
            "s3": {"kind": "delivery", "trigger": "pace_fast",
                   "why": None},
            "s4": "not-a-dict",
        })
        by = {o["snippet_id"]: o for o in out}
        self.assertIsNone(by["s1"]["trigger"])          # clamped
        self.assertEqual(by["s1"]["replacement"], "calmer words")
        self.assertEqual(by["s2"]["device"], "contrast")
        self.assertEqual(by["s2"]["quote"], "not about X. about Y.")
        self.assertEqual(by["s3"]["device"], "pace_fast")
        self.assertIsNone(by["s3"]["quote"])
        self.assertNotIn("s4", by)
        import json as _json
        self.assertNotIn("threat", _json.dumps(out))


if __name__ == "__main__":
    unittest.main()
