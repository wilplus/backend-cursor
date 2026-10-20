"""Two kinds of coach video (founder, 2026-10-18 and 19; decisions log
N77, N78; migration 0480).

What the founder decided, pinned here through the public seams:

  * an EXERCISE VIDEO a coach makes for one speaker reaches that speaker at
    once; another speaker gets it only once the founder approves it, and
    only on an exact fit; another speaker's unapproved video never;
  * on a moment the speaker's own set comes first, then the shared library;
  * it fits only exactly (the video's main mistake heard on this clip), and
    a video whose practice ended on a Good job rests for good;
  * the speaker's own coach video always plays; the AI clip never takes its
    place;
  * a coach's praise line is read for its own speaker only, first;
  * a DIRECT MESSAGE, the coach's word for a Take, shows on that Take only.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import ai_voice_clip
from services import confident_voice_practice as cvp
from services.coach_message_read import coach_message_for
from services.feedback_catalogue import decorate
from tests.test_confident_voice_practice import MatchTraceTests
from tests.test_confident_voice_practice import _Db as _LibraryDb

RUSHING = {"insufficient_pauses": True}


class _Db(_LibraryDb):
    """The catalogue, each speaker's own set and their Good jobs."""

    def __init__(self, rows, sets, rested=()):
        super().__init__(rows)
        self._sets = sets
        self._rested = list(rested)

    def list_speaker_exercise_ids(self, owner):
        return set(self._sets.get(owner, ()))

    def speaker_exercise_history(self, *_args, **_kwargs):
        return {"pattern_takes": {}, "completed_exercises": [],
                "rested_exercises": self._rested, "earlier_takes": 1}


class WhichVideoTheAppPicks(unittest.TestCase):

    _row = MatchTraceTests._row
    _offer = MatchTraceTests._offer  # always for "owner-1"

    def _coach_video_for(self, owner, exercise_id="coach-request-a"):
        return {**self._row(exercise_id, ["rushing"], primary="rushing"),
                "owner_user_id": owner}

    def test_another_speakers_coach_video_is_never_served(self):
        theirs = self._coach_video_for("speaker-a")
        db = _Db([theirs], {"speaker-a": {"coach-request-a"},
                            # even listed in this speaker's set by mistake
                            "owner-1": {"coach-request-a"}})
        self.assertIsNone(self._offer(db, RUSHING))

    def test_the_speakers_own_coach_video_is_served(self):
        mine = self._coach_video_for("owner-1")
        db = _Db([mine], {"owner-1": {"coach-request-a"}})
        self.assertEqual(self._offer(db, RUSHING)["exercise_id"], "coach-request-a")

    def test_the_shared_library_serves_when_it_fits(self):
        library = self._row("library-rushing", ["rushing"], primary="rushing")
        db = _Db([library], {})
        self.assertEqual(self._offer(db, RUSHING)["exercise_id"], "library-rushing")

    def test_a_coach_video_reaches_others_only_once_approved(self):
        filed = self._row("coach-request-old", ["rushing"], primary="rushing")
        self.assertIsNone(self._offer(_Db([filed], {}), RUSHING))
        approved = {**filed, "review_decision": "approved"}
        self.assertEqual(self._offer(_Db([approved], {}), RUSHING)["exercise_id"],
                         "coach-request-old")

    def test_the_speakers_own_video_comes_before_the_library(self):
        # Named to sort first: only the tiers keep it out of the draw.
        library = self._row("aaa-library-rushing", ["rushing"], primary="rushing")
        mine = self._coach_video_for("owner-1")
        db = _Db([library, mine], {"owner-1": {"coach-request-a"}})
        self.assertEqual(self._offer(db, RUSHING)["exercise_id"], "coach-request-a")
        self.assertEqual([c["exercise_id"] for c in db.assigned[0]["candidates"]],
                         ["coach-request-a"])

    def test_it_fits_only_exactly(self):
        side = {**self._row("coach-request-b", ["word_compression", "rushing"],
                            primary="word_compression"),
                "owner_user_id": "owner-1"}
        db = _Db([side], {"owner-1": {"coach-request-b"}})
        self.assertIsNone(self._offer(db, RUSHING))

    def test_a_good_job_rests_the_video_for_good(self):
        mine = self._coach_video_for("owner-1")
        db = _Db([mine], {"owner-1": {"coach-request-a"}},
                 rested=["coach-request-a"])
        self.assertIsNone(self._offer(db, RUSHING))


class ACoachsVideoIsMadeForOneSpeaker(unittest.TestCase):

    def test_a_share_opens_on_a_moment_drawn_before(self):
        """A draw from before N77 names a library video the speaker no
        longer gets; the coach's own video shared for the moment opens."""
        mine = {**MatchTraceTests._row(
            None, "coach-request-a", ["rushing"], primary="rushing"),
            "owner_user_id": "owner-1"}

        class Db(_Db):
            def get_confident_voice_exercise_assignment(self, *_a):
                return {"id": "asg-old", "selected_exercise_id": "library-x",
                        "matching_policy_version": cvp.MATCHING_POLICY_VERSION}

            def get_exercise_coach_request(self, *_a):
                return {"id": "req-1", "owner_user_id": "owner-1",
                        "shared_at": "now", "resolved_exercise_id": "coach-request-a",
                        "resolved_exercise_version": 1}

        weak = {"eligible": True, "pattern": "low_confidence_rushing_dominant",
                "signals": RUSHING}
        with patch.object(cvp, "exercise_eligibility", lambda *_a, **_k: weak):
            refused, _verdict, matching = cvp.start_exercise_check(
                snippet={"id": "snippet-a"}, take_session_id="take-1",
                snippet_id="snippet-a", exercise_id="coach-request-a",
                session_median_wpm=None, database=Db([mine], {}),
                owner_user_id="owner-1")
        self.assertIsNone(refused)
        self.assertEqual(matching["matching_policy_version"],
                         cvp.COACH_REQUEST_POLICY_VERSION)

    def test_a_row_filed_before_is_not_claimed(self):
        """A coach video for this speaker never takes over a row that was in
        the shared library: other speakers may practise on it."""
        from services.diagnostic_exercise_catalogue import (
            CatalogueRefusal, save_exercise,
        )

        class Db:
            def get_diagnostic_exercise(self, _id):
                return {"exercise_id": "coach-request-a", "owner_user_id": None}

            def list_speaking_errors(self, *_a, **_k):
                return [{"error_id": "rushing", "status": "detected"}]

        body = {**MatchTraceTests._row(
            None, "coach-request-a", ["rushing"], primary="rushing"),
            "active": True}
        with self.assertRaises(CatalogueRefusal) as refused:
            save_exercise(Db(), body, source="coach_request",
                          owner_user_id="owner-1")
        self.assertEqual(refused.exception.code, "EXERCISE_UNAVAILABLE")


class TheFounderReviewsACoachsExerciseVideo(unittest.TestCase):

    class Db:
        def __init__(self, row):
            self.row = dict(row)
            self.versions = []

        def get_diagnostic_exercise(self, _id):
            return dict(self.row)

        def review_diagnostic_exercise(self, *, exercise_id, decision,
                                       reviewed_by, version, video_url=None):
            if self.row["version"] != version:
                return None
            self.row.update(review_decision=decision, reviewed_by=reviewed_by)
            if decision == "approved":
                self.row.update(owner_user_id=None, explanation_video_url=video_url,
                                version=version + 1)
            return dict(self.row)

        def record_exercise_version(self, payload):
            self.versions.append(payload)
            return payload

        def get_exercise_version_transcript(self, _id, version):
            # What the coach's version holds: the words said in the video.
            return {"version": version, "transcript_status": "done",
                    "transcript": {"text": "Pause before the number."},
                    "transcript_language": "en",
                    "ai_draft_text": "Slow down.", "ai_draft_model_version": "m1"}

    ROW = {"exercise_id": "coach-request-a", "owner_user_id": "owner-1",
           "version": 1,
           "explanation_video_url": "s3://coach-media/coach-answers/owner-1/r/v.mp4"}

    def _review(self, db, body):
        from services import exercise_review
        with patch.object(exercise_review, "_library_copy",
                          lambda ref: "https://library.example/exercise/v.mp4"):
            return exercise_review.review(db, "coach-request-a", body, "founder")

    def test_approving_shares_it_from_the_library_s_own_copy(self):
        db = self.Db(self.ROW)
        status, _ = self._review(db, {"decision": "approved", "version": 1})
        self.assertEqual(status, 200)
        self.assertIsNone(db.row["owner_user_id"])
        self.assertEqual(db.row["explanation_video_url"],
                         "https://library.example/exercise/v.mp4")
        self.assertTrue(cvp.shared_for_everyone(db.row))
        # Kept as its own version, with the coach's words from the video, so
        # the speaker's earlier versions can go.
        self.assertEqual([(v["version"], v["explanation_video_url"],
                           v["transcript"]["text"], v["ai_draft_text"])
                          for v in db.versions],
                         [(2, "https://library.example/exercise/v.mp4",
                           "Pause before the number.", "Slow down.")])

    def test_only_the_version_the_founder_watched_is_approved(self):
        db = self.Db({**self.ROW, "version": 2})
        status, payload = self._review(db, {"decision": "approved", "version": 1})
        self.assertEqual((status, payload["code"]), (409, "VERSION_CHANGED"))
        self.assertEqual(db.row["owner_user_id"], "owner-1")

    def test_keeping_it_leaves_it_with_its_speaker(self):
        db = self.Db(self.ROW)
        status, _ = self._review(db, {"decision": "kept", "version": 1})
        self.assertEqual((status, db.row["owner_user_id"]), (200, "owner-1"))
        self.assertFalse(cvp.shared_for_everyone(db.row))


class TheSpeakersOwnVideoAlwaysPlays(unittest.TestCase):

    def test_the_ai_clip_never_takes_its_place(self):
        practice = {"kind": "exercise", "exercise_id": "coach-request-a",
                    "exercise_snapshot": {"explanation_video_url": "s3://b/k.mp4"},
                    "machine_assessment": {"matching_policy_version":
                                           cvp.MATCHING_POLICY_VERSION,
                                           "exercise_fit": "exact",
                                           "speaker_set": True}}
        stress = {"exercise": "stress"}  # a problem no video treats
        self.assertEqual(ai_voice_clip.demo_for(None, practice, stress), "video")
        waiting = {"status": "pending", "demo": "ai_voice"}
        self.assertEqual(ai_voice_clip.state(None, practice, waiting)["demo"], "video")


class ACoachsPraiseLineIsItsSpeakers(unittest.TestCase):

    ROW = {"feedback_family": "great_formulation", "cue_keys": ["pause"]}

    def _line(self, version, text, owner=None):
        return {"lane": "praise", "pattern_kind": "cue", "pattern_key": "pause",
                "text": text, "version": version, "active": True,
                "owner_user_id": owner}

    def test_own_first_shared_otherwise_never_another_speakers(self):
        rows = [self._line(1, "Shared."), self._line(2, "For you.", "speaker-a"),
                self._line(3, "For someone else.", "speaker-b")]
        mine = decorate([self.ROW], rows, "speaker-a")[0]
        self.assertEqual(mine["praise_line"], "For you.")
        anyone = decorate([self.ROW], rows, "speaker-c")[0]
        self.assertEqual(anyone["praise_line"], "Shared.")


class TheTakeWordStaysOnItsTake(unittest.TestCase):

    class _Db:
        def list_shared_coach_take_words(self, take_ids):
            return [{"take_session_id": "take-1", "text": "Slow the opening.",
                     "shared_at": "2026-10-18T10:00:00Z"}
                    for take in take_ids if take == "take-1"]

    SESSIONS = [{"id": "take-1", "take_index": 1}, {"id": "take-2", "take_index": 2}]

    def test_a_later_take_starts_without_it(self):
        self.assertIsNone(coach_message_for(self._Db(), self.SESSIONS, "take-2"))
        shown = coach_message_for(self._Db(), self.SESSIONS, "take-1")
        self.assertEqual((shown["text"], shown["take_session_id"]),
                         ("Slow the opening.", "take-1"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
