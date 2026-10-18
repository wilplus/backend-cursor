"""A coach's video belongs to the speaker it was made for (founder,
2026-10-18; decisions log N77; migration 0476).

What the founder decided, pinned here through the public seams:

  * the app picks a video by itself only from the speaker's OWN set, never
    another speaker's coach video and never a library one no coach chose
    for them;
  * it fits only exactly (the video's main mistake heard on this clip), and
    a video whose practice ended on a Good job rests for good;
  * the speaker's own coach video always plays; the AI clip never takes its
    place;
  * a coach's praise line is read for its own speaker only, first;
  * the coach's word for a Take shows on that Take only.
"""
from __future__ import annotations

import unittest

from services import ai_voice_clip
from services import confident_voice_practice as cvp
from services.coach_message_read import coach_message_for
from services.feedback_catalogue import decorate
from tests.test_confident_voice_practice import V3ExerciseFitTests

RUSHING = {"insufficient_pauses": True}


class _Db(V3ExerciseFitTests._Db):
    """The catalogue, each speaker's own set and their Good jobs."""

    def __init__(self, rows, sets, rested=()):
        super().__init__(rows, {})
        self._sets = sets
        self._rested = list(rested)

    def list_speaker_exercise_ids(self, owner):
        return set(self._sets.get(owner, ()))

    def speaker_exercise_history(self, *_args, **_kwargs):
        return {"pattern_takes": {}, "completed_exercises": [],
                "rested_exercises": self._rested, "earlier_takes": 1}


class TheAppPicksOnlyFromTheSpeakersOwnSet(unittest.TestCase):

    _row = V3ExerciseFitTests._row
    _offer = V3ExerciseFitTests._offer  # always for "owner-1"

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

    def test_a_library_video_no_coach_chose_is_not_served(self):
        library = self._row("library-rushing", ["rushing"], primary="rushing")
        db = _Db([library], {})
        self.assertIsNone(self._offer(db, RUSHING))
        # Once a coach picked it for this speaker, it is theirs to get.
        db = _Db([library], {"owner-1": {"library-rushing"}})
        self.assertEqual(self._offer(db, RUSHING)["exercise_id"], "library-rushing")

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
