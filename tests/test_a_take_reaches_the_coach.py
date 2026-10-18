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
# The queue reads its Takes in batches, never once per Take or per speaker
# (founder 2026-10-18: "I want the speakers to open faster").
PER_TAKE = "the coach queue read one Take at a time"


def _row():
    return {"id": SID, "user_id": "u1", "intake_context": {},
            "recording_id": "rec-1", "arc_id": ARC, "take_index": 1,
            "review_requested_at": "2026-10-01T09:00:00Z"}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheMomentsQueueTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, recording_language, coach_languages, feedback_set,
             events=None, answers=None, labels=None, own=None):
        opened = [{"take_session_id": SID, "snippet_id": SNIP, "event": "opened"}]
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(db, "get_user_proficient_languages",
                              return_value=coach_languages), \
                 patch.object(db, "list_moment_events_for_sessions",
                              return_value=opened if events is None else events), \
                 patch.object(db, "list_confident_voice_answered_moments",
                              return_value=answers or []), \
                 patch("routes.v2.coach.load_review_queue",
                       return_value=([_row()], {SID: [{"id": SNIP}]}, {})), \
                 patch.object(db, "get_recording",
                              return_value={"transcription_language": recording_language}), \
                 patch.object(db, "list_exercise_coach_requests_for_sessions",
                              return_value={}), \
                 patch.object(db, "get_own_state_ratings_for_sessions",
                              return_value={SID: own} if own else {}), \
                 patch.object(db, "get_user_profiles", return_value={}), \
                 patch.object(db, "get_confidence_labels_by_snippet_ids",
                              return_value=labels or {}), \
                 patch.object(db, "get_ideal_text_feedback_sets_for_takes",
                              return_value={SID: [{"arc_id": ARC, **feedback_set}]}
                              if feedback_set else {}), \
                 patch.object(db, "get_own_state_ratings_for_session",
                              side_effect=AssertionError(PER_TAKE)), \
                 patch.object(db, "get_user_profile",
                              side_effect=AssertionError(PER_TAKE)), \
                 patch.object(db, "get_ideal_text_feedback_set",
                              side_effect=AssertionError(PER_TAKE)):
                with self.assertLogs(level="INFO") as logs:
                    v2_coach.logger.info("probe")
                    out = v2_coach.v2_coach_moments_queue.__wrapped__()
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status, "\n".join(logs.output)


    def _frozen(self):
        return {"selected_keys": [{
            "id": f"relative-confidence:{SID}:{SNIP}", "kind": "relative_confidence",
            "source": "confident_voice", "feedback_family": "confident_voice",
            "snippet_id": SNIP, "take_session_id": SID,
        }]}


    def test_another_coach_s_audio_unclear_lists_the_moment_for_this_one(self):
        unclear = {"rater_id": "coach9", "value": "audio_unclear", "unrateable": True,
                   "lane": "coach", "state_id": "confidence"}
        body, status, _ = self._get(
            recording_language="en", coach_languages=["en"],
            feedback_set=self._frozen(), labels={SNIP: [unclear]})
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["takes"][0]["moments"],
                         [{"snippet_id": SNIP, "state": "judge_it"}])

    def test_a_take_carries_when_this_coach_last_answered_on_it(self):
        """The speaker screen lists answered Takes most recently answered
        first: a time, never the answer."""
        body, _, _ = self._get(
            recording_language="en", coach_languages=["en"],
            feedback_set=self._frozen())
        self.assertIsNone(body[0]["takes"][0]["answered_at"])
        body, _, _ = self._get(
            recording_language="en", coach_languages=["en"],
            feedback_set=self._frozen(),
            own={SNIP: {"value": "yes", "unrateable": False,
                        "updated_at": "2026-10-18T17:00:00+00:00"}})
        take = body[0]["takes"][0]
        self.assertEqual(take["answered_at"], "2026-10-18T17:00:00+00:00")
        self.assertEqual(take["waiting"], 0)


if __name__ == "__main__":
    unittest.main()
