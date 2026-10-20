"""
STORY    As a speaker, I want my coach's Take-word video transcribed only
         under my processing permit, and only when I said yes to training,
         so that my coach's recording about my talk is processed with my
         consent and never slows the coach's save.
OUTCOME
  O1  Enforce + my authority: my principal, the Take and recording None are
      on the permit (openai, transcription); the permit comes before the
      provider and the terminal event after it; the transcript is saved.
  O2  Enforce + refusal: no provider call, no transcript, a warning logged
      with exc_info; the coach's word and video are still saved.
  O3  Mode off: no principal lookup, no permit, the call runs plainly.
  O4  Without my training yes nothing reaches the transcriber (N79).
  O5  A coach who edits only the words keeps the video, and it is not sent
      again; a null video removes it; a failed read stops the save.
PROVES   O1 -> test_enforced_with_authority_permit_precedes_provider_and_saves
         O2 -> test_enforced_permit_refused_no_transcript_and_logged
               test_refusal_still_saves_the_coach_s_word_and_video
         O3 -> test_mode_off_runs_plainly
               test_the_link_the_upload_handed_back_is_kept_and_transcribed
         O4 -> test_without_the_training_yes_nothing_reaches_the_transcriber
         O5 -> test_editing_only_the_words_keeps_the_video
               test_editing_only_the_words_never_sends_the_video_again
               test_a_null_video_removes_it
               test_a_word_only_edit_leaves_the_video_out_of_the_write
               test_a_failed_read_stops_the_save
WHY      PLF1 (founder 2026-10-05, N48.1): the video went to Whisper with no
         permit; N79 (founder 2026-10-19): only for the training yes.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import coach_take_word as ctw
from services import coach_word_pairs as cwp
from services.coach_video_storage import default_media_bucket
from services.processing_authorization import ProcessingAuthorizationError

TAKE = "22222222-2222-4222-8222-222222222222"
COACH = "33333333-3333-4333-8333-333333333333"
BUCKET = default_media_bucket()
# The marker the upload writes (coach-feedback/<take>/ in the upload bucket).
ROW = {"id": "word-1", "take_session_id": TAKE, "coach_id": COACH,
       "video_ref": f"s3://{BUCKET}/coach-feedback/{TAKE}/take.webm", "draft_text": None}
# What the upload hands the panel, and the panel sends back on save.
SIGNED_LINK = (f"https://account.r2.cloudflarestorage.com/{BUCKET}/coach-feedback/{TAKE}/"
               "take.webm?X-Amz-Expires=3600&X-Amz-Signature=abc")


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
        return {"transcript": kwargs["transcript"]}

    def upsert_coach_take_word(self, *, take_session_id, coach_id, text, video_ref, share,
                               keep_video=False):
        if keep_video:  # the saved video stays, as the payload leaves it out
            video_ref = (self.words.get((take_session_id, coach_id)) or {}).get("video_ref")
        row = {"id": "word-1", "take_session_id": take_session_id, "coach_id": coach_id,
               "text": text, "video_ref": video_ref, "updated_at": "t2"}
        self.words[(take_session_id, coach_id)] = row
        return row


class _Now:
    """The background thread, run in place so the test sees its result."""

    def __init__(self, target, args=(), kwargs=None, **_ignored):
        self._run = lambda: target(*args, **(kwargs or {}))

    def start(self):
        self._run()


def _provider(calls: list, order: list):
    class _OpenAI:
        client = object()

        def transcribe_audio(self, audio, filename, **kwargs):
            order.append("provider")
            calls.append((audio.read(), filename, kwargs))
            return {"text": "  Slow down on the second slide.  "}
    return _OpenAI


class TranscribeTakeWordVideoTests(unittest.TestCase):
    def _run(self, auth, *, db=None, call=None, training_yes=True):
        db = db or _Db()
        calls: list = []
        patches = [
            mock.patch("services.pair_consent.take_holds_training_yes",
                       return_value=training_yes),
            mock.patch("services.coach_video_storage.refreshed_media_url",
                       return_value="https://media/take.webm"),
            mock.patch("services.coach_word_pairs.threading.Thread", _Now),
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

    def test_enforced_with_authority_permit_precedes_provider_and_saves(self):
        auth = _Auth()
        result, db, calls = self._run(auth)
        self.assertEqual(result, "Slow down on the second slide.")
        self.assertEqual(auth.order, ["permit", "started", "provider", "completed"])
        self.assertEqual(auth.resolved, [("owner-principal", "speaker-user")])
        self.assertEqual(auth.current, [("principal-speaker", "coach_draft")])
        permit = auth.permits[0]
        self.assertEqual(
            (permit["acquisition_principal_id"], permit["take_id"], permit["recording_id"],
             permit["provider"], permit["operation_kind"]),
            ("principal-speaker", TAKE, None, "openai", "transcription"))
        self.assertEqual(calls[0][0], b"audio-bytes")
        self.assertEqual([t["transcript"] for t in db.transcripts],
                         ["Slow down on the second slide."])

    def test_mode_off_runs_plainly(self):
        auth = _Auth(enforced=False)
        result, db, calls = self._run(auth)
        self.assertEqual(result, "Slow down on the second slide.")
        self.assertEqual((auth.resolved, auth.current, auth.permits), ([], [], []))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(db.transcripts), 1)

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


class ATakeWordVideoIsTurnedIntoWords(unittest.TestCase):
    """N79 (founder 2026-10-19): what the coach says in a Take-word video is
    written down, for speakers who said yes to training only."""

    _run = TranscribeTakeWordVideoTests._run

    def _save(self, *, training_yes):
        db = _Db()
        _, db, calls = self._run(
            _Auth(enforced=False), db=db, training_yes=training_yes,
            call=lambda: ctw.save_take_word(
                db, take_session_id=TAKE, coach_id=COACH,
                body={"text": "Well done.", "video_ref": SIGNED_LINK}))
        return db, calls

    def test_the_link_the_upload_handed_back_is_kept_and_transcribed(self):
        db, calls = self._save(training_yes=True)
        self.assertEqual(db.words[(TAKE, COACH)]["video_ref"], ROW["video_ref"])
        self.assertEqual(len(calls), 1)
        self.assertEqual([t["transcript"] for t in db.transcripts],
                         ["Slow down on the second slide."])

    def test_without_the_training_yes_nothing_reaches_the_transcriber(self):
        db, calls = self._save(training_yes=False)
        self.assertEqual(db.words[(TAKE, COACH)]["video_ref"], ROW["video_ref"])
        self.assertEqual((calls, db.transcripts), ([], []))


class ATakeWordKeepsItsVideo(unittest.TestCase):
    """Founder 2026-10-19: a coach who edits only the words keeps their video."""

    _run = TranscribeTakeWordVideoTests._run

    def _saves(self, *bodies):
        db = _Db()

        def go():
            for body in bodies:
                ctw.save_take_word(db, take_session_id=TAKE, coach_id=COACH, body=body)
        self._run(_Auth(enforced=False), db=db, call=go)
        return db.words[(TAKE, COACH)]

    def test_editing_only_the_words_keeps_the_video(self):
        word = self._saves({"text": "Well done.", "video_ref": SIGNED_LINK},
                           {"text": "Well done, and slow the opening."})
        self.assertEqual((word["text"], word["video_ref"]),
                         ("Well done, and slow the opening.", ROW["video_ref"]))

    def test_editing_only_the_words_never_sends_the_video_again(self):
        db = _Db()
        _, db, calls = self._run(_Auth(enforced=False), db=db, call=lambda: [
            ctw.save_take_word(db, take_session_id=TAKE, coach_id=COACH, body=body)
            for body in ({"text": "Well done.", "video_ref": SIGNED_LINK},
                         {"text": "Well done, and slow the opening."})])
        self.assertEqual(len(calls), 1)

    def test_a_null_video_removes_it(self):
        word = self._saves({"text": "Well done.", "video_ref": SIGNED_LINK},
                           {"text": "Well done.", "video_ref": None})
        self.assertIsNone(word["video_ref"])


class TheDatabaseKeepsTheVideoAndTheShare(unittest.TestCase):
    """The write itself (services.db): a word-only edit leaves the video and
    its words untouched, and a failed read never passes for "no word yet"
    (which would stamp the share again and tell the speaker twice)."""

    def _upsert(self, rows, client=None, **kwargs):
        from services.db import db as real
        from tests.fakes import FakeSupabaseClient, swap_attr
        client = client or FakeSupabaseClient({"coach_take_words": rows})
        with swap_attr(real, "client", client):
            real.upsert_coach_take_word(take_session_id=TAKE, coach_id=COACH,
                                        text="Edited.", share=True, **kwargs)
        return client.tables["coach_take_words"]

    def test_a_word_only_edit_leaves_the_video_out_of_the_write(self):
        saved = [{"video_ref": ROW["video_ref"], "transcript": "Slow down.",
                  "shared_at": "t0"}]
        query = self._upsert(saved, video_ref=None, keep_video=True)
        self.assertEqual(sorted(query.payload),
                         ["coach_id", "take_session_id", "text", "updated_at"])

    def test_a_failed_read_stops_the_save(self):
        from tests.fakes import FakeSupabaseClient

        def rows(query):  # only the read fails; a write would succeed
            if query.calls[-1][0] == "upsert":
                return [query.payload]
            raise ConnectionError("read failed")
        client = FakeSupabaseClient({"coach_take_words": rows})
        with self.assertRaises(ConnectionError):
            self._upsert(None, client=client, video_ref=None, keep_video=True)
        self.assertNotIn("upsert", [c[0] for c in client.tables["coach_take_words"].calls])


if __name__ == "__main__":
    unittest.main()
