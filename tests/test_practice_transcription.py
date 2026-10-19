"""
STORY    As a speaker, I want my Confident Voice practice recording sent to
         the transcription provider only under a permit, so that nothing I
         say leaves the app without a record.
OUTCOME
  O1  A permit for this Take (recording_id None: a practice try is new
      audio) is taken BEFORE the provider is called, and the call is logged
      started then completed (Never-3: every provider call goes through the
      processing-authorization path).
  O2  On a provider failure the call is logged started then failed and the
      error propagates.
  O3  Each word's recognition ``confidence`` reaches the result unchanged
      (the practice comparison reads it).
  O4  With authorization not enforced it is the same code path: the provider
      is called once and the result is the same, with no permit.
PROVES   O1 -> test_a_permit_is_taken_before_the_provider_is_reached
         O2 -> test_the_outcome_is_recorded_on_failure_and_the_error_propagates
         O3 -> test_a_permit_is_taken_before_the_provider_is_reached
         O4 -> test_mode_off_is_the_same_path_without_a_permit
WHY      Founder 2026-09-16: the practice call moved behind the authorization
         boundary before the Phase-2 gate could be lifted.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import practice_transcription as pt

PRACTICE = {
    "id": "11111111-1111-4111-8111-111111111111",
    "take_session_id": "22222222-2222-4222-8222-222222222222",
    "snippet_id": "33333333-3333-4333-8333-333333333333",
    "owner_user_id": "44444444-4444-4444-8444-444444444444",
}

TRANSCRIPTION = {
    "transcript": "give every word enough space",
    "language": "en",
    "words": [
        {"word": "give", "start": 0.0, "end": 0.3, "confidence": 0.91},
        {"word": "every", "start": 0.35, "end": 0.7, "confidence": 0.88},
    ],
    "transcribed_duration_ms": 2400,
}


class _Auth:
    """Stands in for ProcessingAuthorizationService; writes to a shared trail."""

    def __init__(self, trail: list, enforced: bool = True):
        self.enforced = enforced
        self.trail = trail
        self.permits: list[dict] = []
        self.events: list[tuple] = []

    def resolve_acquisition_principal(self, owner, *, user_id=None,
                                      recording_id=None):
        return "principal-1"

    def issue_provider_permit(self, **kwargs):
        if not self.enforced:
            return None
        self.permits.append(kwargs)
        self.trail.append("permit")
        return {"permit_id": "permit-1"}

    def record_provider_event(self, permit_id, event_kind, **kwargs):
        if not self.enforced or not permit_id:
            return
        self.events.append((permit_id, event_kind, kwargs.get("error_code")))
        self.trail.append(event_kind)


class _Db:
    def __init__(self):
        self.client = object()

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "owner_principal_id": "owner-principal"}


class PracticeTranscriptionTests(unittest.TestCase):
    def _run(self, *, enforced=True, boom=False):
        trail: list = []
        auth = _Auth(trail, enforced=enforced)

        def fake_transcribe(audio, filename, *, language_hint=None):
            trail.append("provider")
            if boom:
                raise RuntimeError("provider exploded")
            return TRANSCRIPTION

        with patch(
            "services.processing_authorization.ProcessingAuthorizationService",
            return_value=auth,
        ), patch(
            "services.snippet_transcription.transcribe_snippet_bytes",
            fake_transcribe,
        ):
            try:
                result = pt.transcribe_practice_attempt(
                    _Db(), PRACTICE, b"audio-bytes", hint_filename="practice.webm")
            except RuntimeError as error:
                result = error
        return result, auth, trail

    def test_a_permit_is_taken_before_the_provider_is_reached(self):
        result, auth, trail = self._run()
        self.assertEqual(trail, ["permit", "started", "provider", "completed"])
        permit = auth.permits[0]
        self.assertEqual(permit["provider"], "openai")
        self.assertEqual(permit["operation_kind"], "transcription")
        self.assertEqual(permit["acquisition_principal_id"], "principal-1")
        self.assertEqual(permit["take_id"], PRACTICE["take_session_id"])
        self.assertIsNone(permit["recording_id"])
        self.assertEqual([w["confidence"] for w in result["words"]], [0.91, 0.88])
        self.assertEqual(result["transcript"], TRANSCRIPTION["transcript"])

    def test_the_outcome_is_recorded_on_failure_and_the_error_propagates(self):
        # A provider call that vanishes from the ledger when it fails is the
        # half of the record that matters most.
        result, auth, trail = self._run(boom=True)
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(trail, ["permit", "started", "provider", "failed"])
        self.assertEqual(auth.events[-1][2], "RuntimeError")

    def test_mode_off_is_the_same_path_without_a_permit(self):
        result, auth, trail = self._run(enforced=False)
        self.assertEqual(trail, ["provider"])
        self.assertEqual(auth.permits, [])
        self.assertEqual(result, TRANSCRIPTION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
