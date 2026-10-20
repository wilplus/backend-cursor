"""
STORY    As a speaker, I want a coach exercise made about my moment to be used
         for training only with my training yes, so that my consent decides.
OUTCOME
  O1  The walk's pair is stamped with the request, the moment, the owner and
      the model version; the draft is the server's (never the client's
      text); the video's transcript is a second pair without the request.
      With the owner's training yes it is releasable.
  O2  Without the owner's yes the pair is stored but not releasable.
  O3  A Library save and a pick of another library exercise make no pair,
      while the request still resolves.
PROVES   O1 -> test_the_pair_is_stamped_and_releasable_with_the_owner_s_yes
         O2 -> test_without_the_owner_s_yes_it_is_recorded_but_not_releasable
         O3 -> test_a_library_save_and_a_library_pick_make_no_pair
WHY      Founder 2026-10-05 (W6): an unstamped pair had no owner, so no consent
         could ever reach it.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import coach_exercise_authoring as cea
from services import exercise_coach_requests as ecr

REQUEST_ID = "0b6a8c1e-2f3d-4a5b-8c7d-9e0f1a2b3c4d"
WALK_ID = f"coach-request-{REQUEST_ID}"
LIBRARY = [{"error_id": e, "label": e, "status": "detected", "active": True}
           for e in ("rushing", "word_compression", "ending_compression")]


class _WalkDb:
    """The catalogue, the request, the pairs and the consent ledger, in
    memory: just enough of services.db for the walk's two calls."""

    def __init__(self, *, request=None, consent=True):
        self.exercises: dict = {}
        self.versions: list = []
        self.request = request
        self.resolved: list = []
        self.pairs: list = []
        self.consent = consent

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

    def set_exercise_version_transcript(self, *, exercise_id, version, status,
                                        transcript, language):
        for row in self.versions:
            if row["exercise_id"] == exercise_id and row["version"] == version:
                row["transcript_status"] = status
                row["transcript"] = transcript
        return {"transcript_status": status}

    def get_exercise_version_transcript(self, exercise_id, version):
        return next((dict(r) for r in self.versions
                     if r["exercise_id"] == exercise_id and r["version"] == version), None)

    # the request
    def get_exercise_coach_request_by_id(self, request_id):
        if self.request and str(self.request["id"]) == str(request_id):
            return dict(self.request)
        return None

    def get_confident_voice_exercise_assignment(self, _take, _snip):
        return None

    def resolve_exercise_coach_request(self, **kwargs):
        self.resolved.append(kwargs)
        return {**self.request, "resolution": kwargs["resolution"],
                "resolved_exercise_id": kwargs.get("exercise_id"),
                "shared_at": "now" if kwargs["share"] else None}

    # the passage the pair remembers
    def get_snippets_by_session(self, take_session_id):
        return [{"id": "snip-1", "session_id": take_session_id,
                 "transcript": "and that   is why the number matters"}]

    # the pairs and the consent ledger
    def insert_feedback_pair(self, **fields):
        row = {"id": f"pair-{len(self.pairs) + 1}", **fields}
        self.pairs.append(row)
        return row

    def create_admin_annotation_event(self, **_fields):
        return None

    def get_owner_principal_for_user(self, user_id):
        return {"id": f"principal-{user_id}"}

    def get_mlc2_training_consent_status(self, principal_id):
        if not self.consent:
            return {"active": False}
        return {"active": True, "grant_event_id": "grant-1",
                "consent_policy_version": "phase1-2026-10-02"}


def _request(**over):
    return {"id": REQUEST_ID, "take_session_id": "take-1", "snippet_id": "snip-1",
            "owner_user_id": "speaker-1", "kind": "error", "reason": "nothing_targets_it",
            "observed_tags": ["ending_compression"], "resolution": None,
            "draft_surface": "exercise_script", "draft_text": "Say the last word fully, then stop.",
            "draft_model_version": "gpt-test-1", **over}


def _definition(**over):
    base = {"exercise_id": WALK_ID, "title": "Land the ending",
            "instruction": "Let the final word land before you breathe.",
            "introduction_copy": "", "acoustic_problem_tags": ["ending_compression"],
            # What the walk's frontend sends: the old default mirrored.
            "matching_criteria": {"requires_multiple_acoustic_signals": True,
                                  "max_per_take": 1,
                                  "primary_problem_tag": "ending_compression"},
            "active": True,
            # The frontend sends the text it showed; the server does not take it.
            "ai_draft_text": "A text the client calls a draft.",
            "ai_draft_model_version": ""}
    base.update(over)
    return base


def _upload(db, *, definition=None, exercise_id=WALK_ID, transcript="Let the final word land.",
            coach_id="coach-1"):
    status = "done" if transcript else "coach_authorization_missing"
    body = {"transcript": transcript, "language": "en"} if transcript else None
    # The walk's video belongs to the moment's speaker: stored privately
    # under their id (N77; 0477), never in the public library bucket.
    with patch.object(cea, "_store_speaker_video",
                      lambda *_a, **_k: "s3://coach-media/coach-answers/speaker-1/x.mp4"), \
            patch("services.exercise_versions.transcribe_exercise_video",
                  lambda *_a, **_k: (status, body, "en" if transcript else None)):
        return cea.attach_video(
            db, exercise_id=exercise_id, coach_id=coach_id, video_bytes=b"video",
            filename="clip.mp4", content_type="video/mp4",
            definition=definition if definition is not None else _definition())


def _resolve(db, *, exercise_id=WALK_ID, coach_id="coach-1", share=True):
    return ecr.resolve_request(
        db, db.request, {"resolution": "exercise_chosen", "exercise_id": exercise_id,
                         "share_with_user": share}, coach_id)


class TheWalkPairTests(unittest.TestCase):

    def test_the_pair_is_stamped_and_releasable_with_the_owner_s_yes(self):
        db = _WalkDb(request=_request(), consent=True)
        _upload(db)
        _resolve(db)
        by_kind = {p["final_kind"]: p for p in db.pairs}
        self.assertEqual(set(by_kind), {"final", "transcript"})
        final, transcript = by_kind["final"], by_kind["transcript"]
        for pair in (final, transcript):
            self.assertEqual(pair["take_session_id"], "take-1")
            self.assertEqual(pair["snippet_id"], "snip-1")
            self.assertEqual(pair["owner_user_id"], "speaker-1")
            self.assertEqual(pair["draft_model_version"], "gpt-test-1")
            # The server's draft, kept on the request; never the client's text.
            self.assertEqual(pair["draft_text"], "Say the last word fully, then stop.")
            self.assertEqual(pair["consent_state"], "yes")
            self.assertTrue(pair["releasable"])
        self.assertEqual(final["request_id"], REQUEST_ID)
        self.assertEqual(final["final_text"], "Let the final word land before you breathe.")
        self.assertIsNone(transcript["request_id"])
        self.assertEqual(transcript["final_text"], "Let the final word land.")

    def test_without_the_owner_s_yes_it_is_recorded_but_not_releasable(self):
        db = _WalkDb(request=_request(), consent=False)
        _upload(db)
        _resolve(db)
        self.assertTrue(db.pairs)
        self.assertTrue(all(p["consent_state"] == "no" and not p["releasable"]
                            for p in db.pairs))

    def test_a_library_save_and_a_library_pick_make_no_pair(self):
        db = _WalkDb(request=_request(), consent=True)
        _upload(db, exercise_id="lib-ex", definition=_definition(exercise_id="lib-ex"))
        self.assertEqual(db.pairs, [])
        status, _body = _resolve(db, exercise_id="lib-ex")
        self.assertEqual(status, 200)
        self.assertEqual(db.resolved[-1]["exercise_id"], "lib-ex")
        self.assertEqual(db.pairs, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
