"""The coach's Take-word video reaches Whisper only through the speaker's permit.

PLF1 (founder 2026-10-05, N48.1; Wave 1 step 6). ``transcribe_take_word_video``
called ``openai_service.transcribe_audio`` directly: no permit, no provider
event, and no regard for ``PLF1_PROCESSING_AUTHORIZATION_MODE``. It now goes
through ``AuthorizedProviderAdapter.transcribe_audio`` bound to the SPEAKER's
authority, as ``speaker_provider_route`` binds the coach's text drafts.

WHAT THIS PINS DOWN:
  * enforce + current authority: the speaker's principal, the Take, and
    ``recording_id=None`` are on the permit; operation ``transcription``,
    provider ``openai``; the permit comes before the provider and the
    terminal event after it; the transcript is saved as the second final;
  * enforce + refusal (authority, permit or principal): no provider call, no
    transcript, a warning logged with exc_info, and the coach's word and
    video are still saved;
  * mode off: one code path, no principal lookup, no permit, the call runs;
  * the module no longer names the bare ``openai_service`` client.

Run: python3 -m unittest tests.test_coach_take_word_permit
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import coach_take_word as ctw
from services import coach_word_pairs as cwp
from services.processing_authorization import ProcessingAuthorizationError

TAKE = "22222222-2222-4222-8222-222222222222"
COACH = "33333333-3333-4333-8333-333333333333"
ROW = {"id": "word-1", "take_session_id": TAKE, "coach_id": COACH,
       "video_ref": "s3://coach-bucket/words/take.mp4", "draft_text": None}


class _Auth:
    """Stands in for ProcessingAuthorizationService."""

    def __init__(self, *, enforced=True, refuse_current=False, refuse_permit=False,
                 principal="principal-speaker"):
        self.enforced = enforced
        self.refuse_current = refuse_current
        self.refuse_permit = refuse_permit
        self.principal = principal
        self.resolved: list[tuple] = []
        self.current: list[tuple] = []
        self.permits: list[dict] = []
        self.events: list[tuple] = []
        self.order: list[str] = []

    def resolve_acquisition_principal(self, owner, *, user_id=None, recording_id=None):
        self.resolved.append((owner, user_id))
        return self.principal

    def require_current(self, principal_id, *, operation):
        self.current.append((principal_id, operation))
        if self.refuse_current:
            raise ProcessingAuthorizationError(
                "PROCESSING_AUTHORIZATION_REQUIRED", "Current authorization is required.", 403)

    def issue_provider_permit(self, **kwargs):
        if not self.enforced:
            return None
        if self.refuse_permit:
            raise ProcessingAuthorizationError(
                "PROVIDER_PERMIT_DENIED", "Provider processing is not authorized.", 403)
        self.order.append("permit")
        self.permits.append(kwargs)
        return {"permit_id": "permit-1"}

    def record_provider_event(self, permit_id, event_kind, **kwargs):
        if not self.enforced or not permit_id:
            return
        self.order.append(event_kind)
        self.events.append((permit_id, event_kind))


class _Db:
    def __init__(self):
        self.client = object()
        self.sessions_read: list[str] = []
        self.transcripts: list[dict] = []
        self.words: dict = {}

    def v2_get_session_by_id(self, session_id):
        self.sessions_read.append(session_id)
        return {"id": session_id, "owner_principal_id": "owner-principal",
                "user_id": "speaker-user"}

    def set_coach_take_word_transcript(self, **kwargs):
        self.transcripts.append(kwargs)

    def upsert_coach_take_word(self, *, take_session_id, coach_id, text, video_ref, share):
        row = {"id": "word-1", "take_session_id": take_session_id, "coach_id": coach_id,
               "text": text, "video_ref": video_ref, "updated_at": "t2"}
        self.words[(take_session_id, coach_id)] = row
        return row


def _provider(calls: list, order: list):
    class _OpenAI:
        client = object()

        def transcribe_audio(self, audio, filename, **kwargs):
            order.append("provider")
            calls.append((audio.read(), filename, kwargs))
            return {"text": "  Slow down on the second slide.  "}
    return _OpenAI


class TranscribeTakeWordVideoTests(unittest.TestCase):
    def _run(self, auth, *, db=None, call=None):
        db = db or _Db()
        calls: list = []
        patches = [
            mock.patch("services.processing_authorization.ProcessingAuthorizationService",
                       return_value=auth),
            mock.patch("services.openai_service.OpenAIService", _provider(calls, auth.order)),
            mock.patch("services.coach_video_storage.get_coach_object_bytes",
                       return_value=b"video-bytes"),
            mock.patch("services.ffmpeg_audio_extract.extract_audio_mp3_for_whisper",
                       return_value=b"audio-bytes"),
        ]
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        result = (call or (lambda: cwp.transcribe_take_word_video(
            db, word_row=dict(ROW), coach_id=COACH)))()
        return result, db, calls


    def _assert_refused(self, auth):
        with self.assertLogs("services.coach_word_pairs", level="WARNING") as logs:
            result, db, calls = self._run(auth)
        self.assertIsNone(result)
        self.assertEqual(calls, [], "the provider was reached without a permit")
        self.assertEqual(db.transcripts, [])
        self.assertEqual(auth.events, [])
        refused = [r for r in logs.records if "refused" in r.getMessage()]
        self.assertEqual(len(refused), 1)
        self.assertIsNotNone(refused[0].exc_info)
        return refused[0]


    def test_enforced_permit_refused_no_transcript_and_logged(self):
        record = self._assert_refused(_Auth(refuse_permit=True))
        self.assertIn("PROVIDER_PERMIT_DENIED", record.getMessage())


    def test_refusal_still_saves_the_coach_s_word_and_video(self):
        auth = _Auth(refuse_current=True)
        db = _Db()
        with mock.patch("services.coach_video_storage.refreshed_media_url",
                        return_value="https://media/take.mp4"), \
                self.assertLogs("services.coach_word_pairs", level="WARNING"):
            payload, db, calls = self._run(auth, db=db, call=lambda: ctw.save_take_word(
                db, take_session_id=TAKE, coach_id=COACH,
                body={"text": "Well done.", "video_ref": ROW["video_ref"]}))
        self.assertEqual(payload["video_ref"], ROW["video_ref"])
        self.assertEqual(payload["text"], "Well done.")
        self.assertIn((TAKE, COACH), db.words)
        self.assertEqual(calls, [])
        self.assertEqual(db.transcripts, [])


if __name__ == "__main__":
    unittest.main()
