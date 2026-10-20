"""
STORY    As a speaker, I want my Ideal Text free in both states, never the
         coach's unfinished edit, with the only paid item being key-moment
         explanations, so that I get my text without a paywall and pay only
         for extras.
OUTCOME
  O1  The Ideal Text GET never shows the coach's in-progress edit.
  O2  Never-1: the Ideal Text GET carries the text and no scores or
      internal reads; the stored suggestions snapshot drops internal
      triggers but keeps the speaker-facing words.
  O3  Payments: unlocking key-moment explanations charges once per
      presentation (keyed on it), grants the unlock, and a second tap is
      free; too few tokens answer 402 and grant nothing - the explanations
      stay locked.
PROVES   O1 -> test_coach_working_text_never_leaks_unverified
         O2 -> test_ac9_score_free, test_write_time_projection_mirrors_serve
         O3 -> test_unlock_charges_once_and_grants_the_explanations
               test_unlock_without_tokens_grants_nothing
WHY      Single-deliverable re-shape, founder 2026-07-17.
"""
from __future__ import annotations

import json
import types
import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import arcs as v2_arcs
    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
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
        body, status = self._get(_row(overall_score=91, power_score=7,
                                      acoustic_read={"potentiometer": 0.4}))
        self.assertEqual(status, 200)  # free: never a 402
        self.assertEqual(body["text"], "machine text")
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "power_score", "91"):
            self.assertNotIn(banned, raw)


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
        self.assertNotIn("threat", json.dumps(out))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MomentsUnlockTests(unittest.TestCase):
    """The one paid item: key-moment explanations, charged per presentation."""

    USER = "u1"

    def setUp(self):
        self.app = Flask(__name__)
        self.unlocks: list = []
        self.charges: list = []

    def _charge(self, ok, balance):
        def charge(user, action, ref_id=None):
            self.charges.append((user, action, ref_id))
            return types.SimpleNamespace(ok=ok, charged=2500 if ok else 0,
                                         balance=balance,
                                         reason=None if ok else "short")
        return charge

    def _call(self, view, *args, ok=True, balance=7500):
        def insert(arc, user, credits):
            self.unlocks.append((arc, user, credits))
            return {"id": len(self.unlocks)}

        sessions = [{"id": "t1", "user_id": self.USER, "arc_id": ARC}]
        with self.app.test_request_context(method="POST"):
            request.user_id = self.USER
            with patch.object(db.takes, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(db, "get_moment_unlock",
                              side_effect=lambda _a: (self.unlocks[0]
                                                      if self.unlocks else None)), \
                 patch.object(db, "insert_moment_unlock", side_effect=insert), \
                 patch("services.token_account.charge",
                       self._charge(ok, balance)):
                out = view.__wrapped__(*args)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_unlock_charges_once_and_grants_the_explanations(self):
        body, status = self._call(v2_arcs.v2_unlock_moments, ARC)
        self.assertEqual(status, 200)
        self.assertTrue(body["unlocked"])
        self.assertEqual(self.charges,
                         [(self.USER, "moment_explanation", ARC)])
        self.assertEqual(len(self.unlocks), 1)

        body, status = self._call(v2_arcs.v2_unlock_moments, ARC)
        self.assertEqual((status, body.get("already_entitled")), (200, True))
        self.assertEqual(len(self.charges), 1)  # the second tap is free
        self.assertEqual(len(self.unlocks), 1)

    def test_unlock_without_tokens_grants_nothing(self):
        body, status = self._call(v2_arcs.v2_unlock_moments, ARC,
                                  ok=False, balance=100)
        self.assertEqual(status, 402)
        self.assertEqual(body["code"], "INSUFFICIENT_TOKENS")
        self.assertEqual(self.unlocks, [])
        body, status = self._call(v2_arcs.v2_get_moment_explanation, ARC, "m1")
        self.assertEqual((status, body["code"]), (402, "MOMENTS_LOCKED"))


if __name__ == "__main__":
    unittest.main()
