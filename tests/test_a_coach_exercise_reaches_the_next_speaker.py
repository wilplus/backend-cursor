"""A coach's exercise reaches the next speaker with its pattern (founder
2026-09-30, C4: "every coach answer also lands in the library under the
pattern it treats, so the next speaker with that pattern is served from the
library first"; build plan P2-3; W6 2026-10-05).

The walk files the coach's exercise through the upload seam with the
matching criteria the frontend mirrors, which said
``requires_multiple_acoustic_signals: true``: a claim that the exercise
needs several signals on a clip, while contract 35g-1 says one detected
problem it targets is the fit. Nothing reads the flag, and nothing proved
the next speaker is served the exercise.

Pins:
  * after the coach's answer is filed and shared, the NEXT speaker's moment
    where the same pattern fired, read weak, is served the coach's exercise
    by the V3 lane, from the library, as an exact fit; one fired signal is
    enough (the legacy rush gate's "several signals" never applies there);
  * a moment where a different pattern fired is not served it;
  * the stored row says what routing does (``false``), and matching never
    reads the flag: a legacy row still claiming ``true`` matches the same.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import coach_exercise_authoring as cea
from services import confident_voice_practice as cvp
from services import exercise_coach_requests as ecr

REQUEST_ID = "5d1c9a3e-7b2f-4c6d-9e8a-1f0b2c3d4e5f"
WALK_ID = f"coach-request-{REQUEST_ID}"
LIBRARY = [{"error_id": e, "label": e, "status": "detected", "active": True}
           for e in ("rushing", "word_compression", "ending_compression")]


class _Db:
    """The library the walk files into and the V3 lane reads from."""

    def __init__(self):
        self.exercises: dict = {}
        self.versions: list = []
        self.assigned: list = []
        self.request = {
            "id": REQUEST_ID, "take_session_id": "take-1", "snippet_id": "snip-1",
            "owner_user_id": "speaker-1", "kind": "error", "resolution": None,
            "observed_tags": ["ending_compression"], "reason": "nothing_targets_it",
            "draft_surface": "exercise_script", "draft_text": "Land the last word.",
            "draft_model_version": "gpt-test-1"}

    # the catalogue
    def list_speaking_errors(self, active_only=True):
        return LIBRARY

    def get_diagnostic_exercise(self, exercise_id):
        row = self.exercises.get(exercise_id)
        return dict(row) if row else None

    def get_active_diagnostic_exercise(self, exercise_id):
        row = self.exercises.get(exercise_id)
        return dict(row) if row and row.get("active") else None

    def list_diagnostic_exercises(self):
        return [dict(r) for r in self.exercises.values()]

    def upsert_diagnostic_exercise(self, row):
        self.exercises[row["exercise_id"]] = dict(row)
        return dict(row)

    def record_exercise_version(self, payload):
        self.versions.append(dict(payload))
        return dict(payload)

    def set_exercise_version_transcript(self, **_kwargs):
        return None

    # the request (the first speaker's moment)
    def get_exercise_coach_request_by_id(self, request_id):
        return dict(self.request) if request_id == REQUEST_ID else None

    def get_exercise_coach_request(self, take_session_id, snippet_id):
        if (take_session_id, snippet_id) == ("take-1", "snip-1"):
            return dict(self.request)
        return None

    def resolve_exercise_coach_request(self, **kwargs):
        self.request.update(resolution=kwargs["resolution"],
                            resolved_exercise_id=kwargs["exercise_id"],
                            resolved_exercise_version=kwargs["exercise_version"],
                            shared_at="2026-10-05T10:00:00Z" if kwargs["share"] else None)
        return dict(self.request)

    def get_confident_voice_exercise_assignment(self, _take, _snip):
        return None

    def insert_feedback_pair(self, **fields):
        return fields

    def get_snippets_by_session(self, _take):
        return [{"id": "snip-2", "metrics": {"wpm": 150.0}, "transcript": "x"}]

    # the next speaker's Take, read by the V3 lane
    def get_confident_voice_practice_candidates(self, ids):
        return [{"id": i, "session_id": "take-2", "transcript": "the next words",
                 "audio_segment_path": "s3://b", "duration_ms": 4000,
                 "metrics": {"wpm": 150.0}} for i in ids]

    def get_confident_voice_practice_by_take(self, _take):
        return None

    def assign_confident_voice_exercise(self, **kwargs):
        self.assigned.append(kwargs)
        return {"selected_exercise_id": kwargs["candidates"][0]["exercise_id"]}

    def completed_exercise_before(self, *_args):
        return False


def _file_and_share(db):
    """The walk: Words, Video, Home; the upload seam, then the answer."""
    definition = {
        "exercise_id": WALK_ID, "title": "Land the ending",
        "instruction": "Let the final word land before you breathe.",
        "introduction_copy": "", "acoustic_problem_tags": ["ending_compression"],
        "matching_criteria": {"requires_multiple_acoustic_signals": True,
                              "max_per_take": 1,
                              "primary_problem_tag": "ending_compression"},
        "active": True}
    with patch.object(cea, "store_exercise_video",
                      lambda *_a: "https://cdn.example/journal/exercise/coach.mp4"), \
            patch("services.exercise_versions.transcribe_exercise_video",
                  lambda *_a, **_k: ("coach_authorization_missing", None, None)):
        status, _ = cea.attach_video(
            db, exercise_id=WALK_ID, coach_id="coach-1", video_bytes=b"video",
            filename="clip.mp4", content_type="video/mp4", definition=definition)
    assert status == 200, status
    status, _ = ecr.resolve_request(
        db, db.request, {"resolution": "exercise_chosen", "exercise_id": WALK_ID,
                         "share_with_user": True}, "coach-1")
    assert status == 200, status


def _next_speaker_moment(db, fired: dict):
    """One V3 bookmark of the next speaker's Take, read weak, with ONE
    signal fired: not "eligible" by the legacy rush gate (it needs two or
    three), which V3 does not apply on its own moment (35g-1)."""
    target = {"source": "confident_voice", "bookmark_tier": "exercise",
              "snippet_id": "snip-2"}
    verdict = {"eligible": False, "reason": "weak_acoustic_evidence",
               "pattern": "low_confidence_rushing_dominant", "priority": 1,
               "signals": fired, "snapshot": {}}
    with patch.object(cvp, "exercise_eligibility", lambda *_a, **_k: verdict):
        rows = cvp.attach_v3_exercise_offer(
            [target], take_session_id="take-2", owner_user_id="speaker-2",
            database=db, ground=lambda _row: {"slide_index": 0})
    return rows[0]


@patch("config.Config.EXERCISE_FALLBACK_LADDER_ENABLED", False)
class TheNextSpeakerTests(unittest.TestCase):
    def test_after_a_share_the_next_moment_with_the_pattern_is_served_the_coach_s_exercise(self):
        db = _Db()
        _file_and_share(db)
        row = _next_speaker_moment(db, {"compressed_ending": True})
        offer = row.get("practice_exercise")
        self.assertIsNotNone(offer, "the coach's exercise reached the next speaker")
        self.assertEqual(offer["exercise_id"], WALK_ID)
        self.assertNotIn("chosen_by_coach", offer)   # from the library, not a share
        draw = db.assigned[-1]
        self.assertEqual(draw["take_session_id"], "take-2")
        self.assertEqual(draw["matching_policy_version"], "exercise-fit-tier-v1:exact")

    def test_a_moment_where_another_pattern_fired_is_not_served_it(self):
        db = _Db()
        _file_and_share(db)
        row = _next_speaker_moment(db, {"insufficient_pauses": True})
        self.assertNotIn("practice_exercise", row)
        self.assertTrue(row.get("problem_recognised"))

    def test_the_filed_row_says_one_signal_is_the_fit(self):
        db = _Db()
        _file_and_share(db)
        criteria = db.exercises[WALK_ID]["matching_criteria"]
        self.assertFalse(criteria["requires_multiple_acoustic_signals"])
        self.assertEqual(criteria["primary_problem_tag"], "ending_compression")


class TheFlagIsNeverReadTests(unittest.TestCase):
    def test_a_legacy_row_still_claiming_several_signals_matches_the_same(self):
        row = {"exercise_id": "legacy", "version": 1,
               "acoustic_problem_tags": ["ending_compression"],
               "supported_confidence_patterns": ["low_confidence_rushing_dominant"],
               "matching_criteria": {"requires_multiple_acoustic_signals": True,
                                     "primary_problem_tag": "ending_compression"}}
        flipped = {**row, "matching_criteria": {**row["matching_criteria"],
                                                "requires_multiple_acoustic_signals": False}}
        for exercise in (row, flipped):
            fit, ranked = cvp.matched_exercises(
                "low_confidence_rushing_dominant", [exercise],
                observed_tags={"ending_compression"})
            self.assertEqual(fit, "exact")
            self.assertEqual(ranked[0][1]["exercise_id"], "legacy")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
