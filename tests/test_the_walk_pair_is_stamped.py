"""The walk's exercise pair carries its request, moment, owner and model
version (founder 2026-10-05, W6: C2, C5, P2-1, FL-L3; W7 L5, L6 depend on it).

The walk answers an error moment through the exercise upload seam: the
coach's exercise is saved as ``coach-request-<request id>``, then the
request resolves to it as ``exercise_chosen``. Until now its pair was
written at the upload, with no request, moment, owner or model version, so
no consent could reach it (no owner), no golden set could judge it (no
passage) and the export contract could never release it.

Pins:
  * the pair rides the resolution, behind the blind gate: the saved
    instruction against the model's draft KEPT ON THE REQUEST, stamped with
    the request, the moment, the owner, the model version, the pattern (the
    exercise's main target) and the exercise version, and its passage;
  * the video's transcript is the second final, stamped the same but for
    the request (one pair per request and surface is the table's key);
  * a stamped pair takes the owner's training yes, so it is releasable;
  * the draft is the server's: a client's text is never recorded as the
    model's draft, and the Library (no request) records no pair at all;
  * choosing another library exercise is no pair; a coach answering a
    moment of their own Take is the owner answering, never a pair;
  * a pair is recorded only when a draft was shown and the final differs.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import coach_exercise_authoring as cea
from services import exercise_coach_requests as ecr
from services import feedback_pairs as fp

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
    with patch.object(cea, "store_exercise_video",
                      lambda *_a: "https://cdn.example/journal/exercise/x.mp4"), \
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
    def test_the_upload_records_no_pair_and_the_resolution_records_it_stamped(self):
        db = _WalkDb(request=_request())
        status, _ = _upload(db)
        self.assertEqual(status, 200)
        self.assertEqual(db.pairs, [], "the pair waits for the resolution")
        status, _ = _resolve(db)
        self.assertEqual(status, 200)
        final = next(p for p in db.pairs if p["final_kind"] == "final")
        self.assertEqual(final["surface"], "exercise_script")
        self.assertEqual(final["request_id"], REQUEST_ID)
        self.assertEqual((final["take_session_id"], final["snippet_id"]), ("take-1", "snip-1"))
        self.assertEqual(final["owner_user_id"], "speaker-1")
        self.assertEqual(final["draft_model_version"], "gpt-test-1")
        self.assertEqual(final["pattern_key"], "ending_compression")
        self.assertEqual((final["exercise_id"], final["exercise_version"]), (WALK_ID, 1))
        self.assertEqual(final["coach_id"], "coach-1")
        # The draft is the request's, never the client's text.
        self.assertEqual(final["draft_text"], "Say the last word fully, then stop.")
        self.assertEqual(final["final_text"], "Let the final word land before you breathe.")
        # The passage it was drafted from, so a golden set and a run can use it.
        self.assertEqual(final["passage_text"], "and that is why the number matters")
        self.assertEqual(final["prompt_context"]["kind"], "error")

    def test_the_transcript_is_the_second_final_stamped_but_for_the_request(self):
        db = _WalkDb(request=_request())
        _upload(db)
        _resolve(db)
        transcript = next(p for p in db.pairs if p["final_kind"] == "transcript")
        self.assertIsNone(transcript["request_id"])
        self.assertEqual(transcript["final_text"], "Let the final word land.")
        for field in ("take_session_id", "snippet_id", "owner_user_id",
                      "draft_model_version", "pattern_key", "exercise_id",
                      "exercise_version", "passage_text"):
            self.assertTrue(transcript[field], field)
        self.assertEqual(len(db.pairs), 2)

    def test_a_stamped_walk_pair_takes_the_owner_s_yes_and_is_releasable(self):
        db = _WalkDb(request=_request())
        _upload(db)
        _resolve(db)
        for pair in db.pairs:
            self.assertEqual(pair["owner_principal_id"], "principal-speaker-1")
            self.assertEqual(pair["consent_state"], "yes")
            self.assertTrue(pair["releasable"])

    def test_without_the_owner_s_yes_it_is_recorded_but_not_releasable(self):
        db = _WalkDb(request=_request(), consent=False)
        _upload(db)
        _resolve(db)
        self.assertTrue(db.pairs)
        self.assertTrue(all(p["consent_state"] == "no" and not p["releasable"]
                            for p in db.pairs))

    def test_the_version_row_keeps_the_request_s_draft_and_model(self):
        db = _WalkDb(request=_request())
        _upload(db)
        row = db.versions[0]
        self.assertEqual(row["ai_draft_text"], "Say the last word fully, then stop.")
        self.assertEqual(row["ai_draft_model_version"], "gpt-test-1")

    def test_choosing_another_library_exercise_is_no_pair(self):
        db = _WalkDb(request=_request())
        _upload(db, definition=_definition(exercise_id="land-it"), exercise_id="land-it")
        status, _ = _resolve(db, exercise_id="land-it")
        self.assertEqual(status, 200)
        self.assertEqual(db.pairs, [])

    def test_a_coach_answering_their_own_moment_is_the_owner_never_a_pair(self):
        db = _WalkDb(request=_request(owner_user_id="coach-1"))
        _upload(db)
        _resolve(db)
        self.assertEqual(db.pairs, [])

    def test_no_draft_shown_is_no_pair(self):
        db = _WalkDb(request=_request(draft_text=None, draft_surface=None))
        _upload(db)
        _resolve(db)
        self.assertEqual(db.pairs, [])
        self.assertIsNone(db.versions[0]["ai_draft_text"])

    def test_an_unchanged_script_still_pairs_its_differing_transcript(self):
        db = _WalkDb(request=_request(draft_text="Let the final word land before you breathe."))
        _upload(db)
        _resolve(db)
        self.assertEqual([p["final_kind"] for p in db.pairs], ["transcript"])

    def test_no_transcript_yet_is_the_one_pair(self):
        db = _WalkDb(request=_request())
        _upload(db, transcript=None)
        _resolve(db)
        self.assertEqual([p["final_kind"] for p in db.pairs], ["final"])


class TheLibraryTests(unittest.TestCase):
    """FL-L3: the Library's starting text is a past final (a coach's or the
    founder's words), never the model's draft."""

    def test_a_library_exercise_records_no_pair_and_keeps_no_draft(self):
        db = _WalkDb()
        definition = _definition(exercise_id="land-it",
                                 ai_draft_text="Another coach's final for this pattern.",
                                 ai_draft_model_version="gpt-test-1")
        status, _ = _upload(db, definition=definition, exercise_id="land-it")
        self.assertEqual(status, 200)
        self.assertEqual(db.pairs, [])
        self.assertIsNone(db.versions[0]["ai_draft_text"])
        self.assertIsNone(db.versions[0]["ai_draft_model_version"])

    def test_a_request_id_shaped_like_nothing_is_not_a_request(self):
        self.assertIsNone(cea.request_id_for_exercise("coach-request-req-1"))
        self.assertIsNone(cea.request_id_for_exercise("land-it"))
        self.assertEqual(cea.request_id_for_exercise(WALK_ID), REQUEST_ID)

    def test_a_request_whose_draft_is_another_surface_lends_none(self):
        db = _WalkDb(request=_request(draft_surface="praise_line"))
        self.assertEqual(cea.server_draft(db, WALK_ID), (None, None))


class TheOwnerRuleTests(unittest.TestCase):
    def test_record_pair_refuses_when_the_coach_is_the_owner(self):
        class _Db:
            rows: list = []

            def insert_feedback_pair(self, **fields):
                self.rows.append(fields)
                return fields
        db = _Db()
        self.assertIsNone(fp.record_pair(
            db, surface="praise_line", draft="a", final="b", coach_id="same-1",
            owner_user_id="same-1", request_id="req-1"))
        self.assertEqual(db.rows, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
