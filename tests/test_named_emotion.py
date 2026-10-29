"""
STORY    As a coach, I want to see the emotion the speaker named before
         recording, as their own word, so that I coach from what they felt
         and not from a machine bucket.
OUTCOME
  O1  The upload stores the named emotion on intake_context as a key from
      the closed vocabulary (case and padding tolerated).
  O2  An unknown word is dropped and never blocks the recording.
  O3  Once the coach's blind labels are in, the coach view shows the stored
      key unchanged, and nothing else is attached to it.
PROVES   O1 -> test_the_upload_stores_the_key_and_the_coach_sees_it
         O2 -> test_an_unknown_word_is_dropped_and_the_take_still_lands
         O3 -> test_the_upload_stores_the_key_and_the_coach_sees_it
WHY      F2 handoff section 2, 2026-08-03: the answer used to evaporate.
"""
from __future__ import annotations

import io
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from flask import Flask, request

    import services.lab_recording as lab
    from routes.v2 import coach as v2_coach
    from routes.v2 import lab_recording as route
    from services.lab_analysis_dispatch import PendingAnalysis
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e

SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _upload(named_emotion):
    """POST /lab/recordings with only the outside world faked (database,
    storage, audio gate, project lookup, analysis queue). Returns the status
    and the intake_context the route stored."""
    from werkzeug.datastructures import FileStorage
    data = {"audio_file": FileStorage(
        stream=io.BytesIO(b"x" * 32), filename="take.webm",
        content_type="audio/webm"), "topic": "t",
        "named_emotion": named_emotion}
    project = SimpleNamespace(
        project_id="project-1", idempotency_key="upload-1",
        duplicate_take=None, principal=SimpleNamespace(id="owner-1"))
    auth = MagicMock(enforced=False)
    auth.resolve_acquisition_principal.return_value = "owner-1"
    fake_db = MagicMock()
    with ExitStack() as stack, Flask(__name__).test_request_context(
            method="POST", data=data, content_type="multipart/form-data"):
        for target, kw in (
            ("routes.v2.lab_recording.db", {"new": fake_db}),
            ("routes.v2.lab_recording.resolve_take_project",
             {"return_value": project}),
            ("routes.v2.lab_recording.ProcessingAuthorizationService",
             {"return_value": auth}),
            ("services.processing_authorization."
             "ProcessingAuthorizationService", {"return_value": auth}),
            ("routes.v2.lab_recording._is_data_foundation_canary_owner",
             {"return_value": False}),
            ("routes.v2.lab_recording.require_analyzable_recording",
             {"return_value": {"ok": True, "duration_sec": 30}}),
            ("services.lab_audio_storage.put_lab_audio_bytes",
             {"return_value": "lab-bucket"}),
            ("services.lab_audio_storage.storage_provider",
             {"return_value": "r2"}),
            ("services.create_take.reserve_take", {"return_value": 1}),
            ("routes.v2.lab_recording.dispatch_recording_analysis",
             {"return_value": PendingAnalysis({"state": "processing"})}),
        ):
            stack.enter_context(patch(target, **kw))
        _, status = route.v2_lab_create_recording.__wrapped__()
    stored = fake_db.takes.set_session_intake_context.call_args.args[1]
    return status, stored


def _coach_view(intake_context):
    """GET /coach/sessions/<id> for a coach who has answered every moment
    blind, on a Take whose intake_context is the one given."""
    session = {"id": SID, "user_id": "speaker-1",
               "intake_context": {"language": "en", **intake_context},
               "status": "pending_admin_review"}
    snippet = {"id": "a", "index": 1, "transcript": "hi",
               "audio_ref": "p/a.wav", "start_offset_ms": 0,
               "duration_ms": 8000}
    db = v2_coach.db
    with ExitStack() as stack, Flask(__name__).test_request_context():
        request.user_id = "coach-1"
        for attr, value in (
            ("v2_get_session_by_id", lambda sid: session),
            ("get_user_proficient_languages", lambda user_id: ["en"]),
            ("get_snippets_by_session", lambda sid: []),
            ("get_recording", lambda rid: {"transcription_language": "en"}),
            ("claim_coach_review", lambda session_id, actor_user_id, **kw: {
                "assigned_to": actor_user_id, "claimed": True}),
            ("get_coach_snippet_drafts_by_sessions", lambda ids: {}),
            ("get_own_state_ratings_for_sessions", lambda ids, rater_id: {SID: {
                "a": {"value": "yes", "unrateable": False}}}),
            ("get_ai_draft_coach_notes_by_session", lambda sid: {}),
        ):
            stack.enter_context(patch.object(db, attr, value, create=True))
        stack.enter_context(patch.object(
            db.takes, "get_read_sessions_for", lambda sid: [], create=True))
        stack.enter_context(patch.object(
            lab, "build_readout_from_session",
            lambda sid, **kw: {"snippets": [dict(snippet)]}))
        resp, status = v2_coach.v2_coach_get_session.__wrapped__(SID)
        return status, resp.get_json()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class NamedEmotionTests(unittest.TestCase):

    def test_the_upload_stores_the_key_and_the_coach_sees_it(self):
        status, stored = _upload(" Excited ")
        self.assertEqual(status, 202)
        self.assertEqual(stored["named_emotion"], "excited")
        status, view = _coach_view(stored)
        self.assertEqual(status, 200)
        self.assertTrue(view["context_unlocked"])
        self.assertEqual(view["named_emotion"], "excited")
        self.assertEqual(
            [k for k in view if "emotion" in k], ["named_emotion"])

    def test_an_unknown_word_is_dropped_and_the_take_still_lands(self):
        status, stored = _upload("ecstatic-ish")
        self.assertEqual(status, 202)
        self.assertNotIn("named_emotion", stored)


if __name__ == "__main__":
    unittest.main()
