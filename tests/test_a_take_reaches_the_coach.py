"""A student's Take reaches the coach (founder 2026-10-01, 0a).

The coach queue can lose a Take at four filters: the review-queue select,
the language match, the frozen bookmarks and the front end. This file runs a
Take through the three on the backend and pins what each one must do now:

  * the queue select carries `recording_id`, so a Take with no declared
    language rides on the recording's detected language (the defect: the
    fallback never ran, because the id was not selected);
  * a Take withheld by language is logged with the filter's name, never
    silently absent;
  * a Take whose bookmarks are not frozen yet is listed as waiting for the
    text, with no moments, and counted on the speaker;
  * a refused coach hand-off (the first filter) is logged with its name.
"""
from __future__ import annotations

import inspect
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

SID = "11111111-1111-4111-8111-111111111111"
SNIP = "22222222-2222-4222-8222-222222222222"
ARC = "33333333-3333-4333-8333-333333333333"


def _row():
    return {"id": SID, "user_id": "u1", "intake_context": {},
            "recording_id": "rec-1", "arc_id": ARC, "take_index": 1,
            "review_requested_at": "2026-10-01T09:00:00Z"}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheQueueSelectTests(unittest.TestCase):
    def test_the_review_queue_select_carries_the_recording_id(self):
        source = inspect.getsource(type(db).list_review_queue)
        full = source[source.index("_full_cols = ("):source.index("_base_cols = (")]
        base = source[source.index("_base_cols = ("):source.index("try:")]
        self.assertIn("recording_id", full)
        self.assertIn("recording_id", base)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheMomentsQueueTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, recording_language, coach_languages, feedback_set):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(db, "get_user_proficient_languages",
                              return_value=coach_languages), \
                 patch("routes.v2.coach.load_review_queue",
                       return_value=([_row()], {SID: [{"id": SNIP}]}, {})), \
                 patch.object(db, "get_recording",
                              return_value={"transcription_language": recording_language}), \
                 patch.object(db, "list_exercise_coach_requests_for_sessions",
                              return_value={}), \
                 patch.object(db, "get_own_state_ratings_for_session",
                              return_value={}), \
                 patch.object(db, "get_ideal_text_feedback_set",
                              return_value=feedback_set):
                with self.assertLogs("routes.v2.coach", level="INFO") as logs:
                    v2_coach.logger.info("probe")
                    out = v2_coach.v2_coach_moments_queue.__wrapped__()
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status, "\n".join(logs.output)

    def test_a_take_with_no_declared_language_rides_on_the_recordings_detected_language(self):
        body, status, _ = self._get(recording_language="en", coach_languages=["en"],
                                    feedback_set=None)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)
        take = body[0]["takes"][0]
        self.assertEqual(take["session_id"], SID)
        # Not frozen yet: listed, waiting for the text, nothing to judge yet.
        self.assertTrue(take["waiting_for_text"])
        self.assertEqual(take["moments"], [])
        self.assertEqual(body[0]["waiting_for_text"], 1)

    def test_a_frozen_take_lists_its_bookmarks(self):
        frozen = {"selected_keys": [{
            "id": f"relative-confidence:{SID}:{SNIP}", "kind": "relative_confidence",
            "source": "confident_voice", "feedback_family": "confident_voice",
            "snippet_id": SNIP, "take_session_id": SID,
        }]}
        body, status, _ = self._get(recording_language="en", coach_languages=["en"],
                                    feedback_set=frozen)
        self.assertEqual(status, 200)
        take = body[0]["takes"][0]
        self.assertFalse(take["waiting_for_text"])
        self.assertEqual([m["snippet_id"] for m in take["moments"]], [SNIP])
        self.assertEqual(take["waiting"], 1)

    def test_a_take_withheld_by_language_is_logged_with_its_filter(self):
        body, status, logged = self._get(recording_language="pl", coach_languages=["en"],
                                         feedback_set=None)
        self.assertEqual(status, 200)
        self.assertEqual(body, [])
        self.assertIn("filter=language", logged)
        self.assertIn("outcome=mismatch", logged)
        self.assertIn(SID, logged)

    def test_a_take_with_no_language_anywhere_is_logged_as_unknown(self):
        body, status, logged = self._get(recording_language=None, coach_languages=["en"],
                                         feedback_set=None)
        self.assertEqual(body, [])
        self.assertIn("filter=language", logged)
        self.assertIn("outcome=language_unknown", logged)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheHandOffTests(unittest.TestCase):
    def test_a_refused_hand_off_is_logged_with_its_filter(self):
        from services import lab_send
        from services.processing_authorization import ProcessingAuthorizationError

        def refuse(*_a, **_k):
            raise ProcessingAuthorizationError(
                code="POLICY_NOT_ACCEPTED", message="accept the policy first")

        with patch.object(db, "v2_get_session_by_id",
                          return_value={"id": SID, "user_id": "u1", "status": "ready"}), \
             patch.object(lab_send, "_authorize_coach_delivery", side_effect=refuse), \
             self.assertLogs("services.lab_send", level="INFO") as logs:
            result = lab_send.send_lab_recording_to_coach(SID, "u1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "processing_authorization_required")
        self.assertIn("filter=coach_delivery_authorization", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
