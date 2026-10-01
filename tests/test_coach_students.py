"""The coach's students (founder 2026-10-01, Phase 0b), dark behind
COACH_STUDENTS_ENABLED.

Pins: off, the roster and the profile carry no name and the walk-take read
is 404; on, the real name rides where the student has one, a profile lists
its Takes with their index, and one Take comes back in the walk's shape
with the name beside it, behind the queue's language gate.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from config import Config
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

UID = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
SNIP = "33333333-3333-4333-8333-333333333333"
ARC = "44444444-4444-4444-8444-444444444444"


def _session():
    return {"id": SID, "user_id": UID, "intake_context": {"language": "en", "topic": "Board"},
            "arc_id": ARC, "take_index": 2, "created_at": "2026-10-01T09:00:00Z",
            "review_requested_at": "2026-10-01T09:01:00Z", "recording_kind": "spoken"}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SwitchOffTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.assertFalse(Config.COACH_STUDENTS_ENABLED)

    def test_the_roster_and_the_profile_carry_no_name(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(db.takes, "list_coach_students",
                              return_value=[{"user_id": UID, "last_active": "x", "session_count": 1}]), \
                 patch.object(db, "get_user_profiles", return_value={UID: {"domain": "sales"}}), \
                 patch.object(db, "get_student_names", side_effect=AssertionError("never read while off")):
                resp, status = v2_coach.v2_coach_students.__wrapped__()
            self.assertEqual(status, 200)
            self.assertNotIn("name", resp.get_json()[0])
            with patch.object(db, "get_user_profile", return_value={"domain": "sales", "goal": "g"}), \
                 patch.object(db.takes, "v2_list_user_lab_sessions", return_value=[_session()]), \
                 patch.object(db, "get_feelings_by_sessions", return_value=[]), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_texts", return_value={}), \
                 patch.object(db, "get_student_names", side_effect=AssertionError("never read while off")):
                resp, status = v2_coach.v2_coach_student_detail.__wrapped__(UID)
            body = resp.get_json()
            self.assertEqual(status, 200)
            self.assertNotIn("name", body)
            self.assertEqual(body["sessions"][0]["take_index"], 2)

    def test_the_walk_take_read_is_404(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(db, "v2_get_session_by_id", side_effect=AssertionError("never read while off")):
                resp, status = v2_coach.v2_coach_walk_take.__wrapped__(SID)
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SwitchOnTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._on = patch.object(Config, "COACH_STUDENTS_ENABLED", True)
        self._on.start()
        self.addCleanup(self._on.stop)

    def test_the_real_name_rides_where_the_student_has_one(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(db.takes, "list_coach_students",
                              return_value=[{"user_id": UID, "last_active": "x", "session_count": 1},
                                            {"user_id": "u-2", "last_active": "y", "session_count": 0}]), \
                 patch.object(db, "get_user_profiles", return_value={}), \
                 patch.object(db, "get_student_names", return_value={UID: "Anna"}) as names:
                resp, status = v2_coach.v2_coach_students.__wrapped__()
        self.assertEqual(status, 200)
        rows = resp.get_json()
        self.assertEqual(rows[0]["name"], "Anna")
        self.assertNotIn("name", rows[1])
        self.assertTrue(rows[1]["pseudonym"])
        names.assert_called_once_with([UID, "u-2"])

    def _walk(self, *, coach_languages, feedback_set):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(db, "v2_get_session_by_id", return_value=_session()), \
                 patch.object(db, "get_snippets_by_session", return_value=[{"id": SNIP}]), \
                 patch.object(db, "get_own_state_ratings_for_session", return_value={}), \
                 patch.object(db, "list_exercise_coach_requests_for_sessions", return_value={}), \
                 patch.object(db, "get_user_proficient_languages", return_value=coach_languages), \
                 patch.object(db, "get_student_names", return_value={UID: "Anna"}), \
                 patch.object(db, "get_ideal_text_feedback_set", return_value=feedback_set):
                out = v2_coach.v2_coach_walk_take.__wrapped__(SID)
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status

    def test_one_take_comes_back_in_the_walks_shape_with_the_name(self):
        frozen = {"selected_keys": [{
            "id": f"relative-confidence:{SID}:{SNIP}", "kind": "relative_confidence",
            "source": "confident_voice", "feedback_family": "confident_voice",
            "snippet_id": SNIP, "take_session_id": SID,
        }]}
        body, status = self._walk(coach_languages=["en"], feedback_set=frozen)
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "Anna")
        take = body["speaker"]["takes"][0]
        self.assertEqual(take["session_id"], SID)
        self.assertEqual(take["take_index"], 2)
        self.assertEqual(take["moments"], [{"snippet_id": SNIP, "state": "judge_it"}])
        self.assertFalse(take["waiting_for_text"])
        # The pseudonym stays the shape's label; the name rides beside it.
        self.assertTrue(body["speaker"]["pseudonym"])
        self.assertNotIn("user_id", body["speaker"])

    def test_an_unfrozen_take_waits_for_the_text(self):
        body, status = self._walk(coach_languages=["en"], feedback_set=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["speaker"]["takes"][0]["waiting_for_text"])

    def test_the_queues_language_gate_applies(self):
        body, status = self._walk(coach_languages=["pl"], feedback_set=None)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "RATER_LANGUAGE_MISMATCH")
        body, status = self._walk(coach_languages=[], feedback_set=None)
        self.assertEqual(status, 428)

    def test_a_missing_take_is_404(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(db, "v2_get_session_by_id", return_value=None):
                resp, status = v2_coach.v2_coach_walk_take.__wrapped__(SID)
            self.assertEqual(status, 404)
            self.assertEqual(v2_coach.v2_coach_walk_take.__wrapped__("nope")[1], 400)


if __name__ == "__main__":
    unittest.main()
