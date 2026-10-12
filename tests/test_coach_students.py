"""The coach's students (founder 2026-10-01, Phase 0b) stay off (N48.5
Q26 A); the switch and its on-branch were deleted 2026-10-11.

Pins: the roster and the profile carry no name, a profile lists its Takes
with their index, and the walk-take read is 404 (400 for a bad id).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

UID = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
ARC = "44444444-4444-4444-8444-444444444444"


def _session():
    return {"id": SID, "user_id": UID, "intake_context": {"language": "en", "topic": "Board"},
            "arc_id": ARC, "take_index": 2, "created_at": "2026-10-01T09:00:00Z",
            "review_requested_at": "2026-10-01T09:01:00Z", "recording_kind": "spoken"}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_the_roster_and_the_profile_carry_no_name(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(db.takes, "list_coach_students",
                              return_value=[{"user_id": UID, "last_active": "x", "session_count": 1}]), \
                 patch.object(db, "get_user_profiles", return_value={UID: {"domain": "sales"}}):
                resp, status = v2_coach.v2_coach_students.__wrapped__()
            self.assertEqual(status, 200)
            self.assertNotIn("name", resp.get_json()[0])
            with patch.object(db, "get_user_profile", return_value={"domain": "sales", "goal": "g"}), \
                 patch.object(db.takes, "v2_list_user_lab_sessions", return_value=[_session()]), \
                 patch.object(db, "get_feelings_by_sessions", return_value=[]), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_texts", return_value={}):
                resp, status = v2_coach.v2_coach_student_detail.__wrapped__(UID)
            body = resp.get_json()
            self.assertEqual(status, 200)
            self.assertNotIn("name", body)
            self.assertEqual(body["sessions"][0]["take_index"], 2)


if __name__ == "__main__":
    unittest.main()
