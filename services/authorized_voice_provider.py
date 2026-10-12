"""ElevenLabs behind the processing permit (CLAUDE.md: every provider call
goes through the processing-authorization path; no direct provider clients).

Each call issues one typed permit for the speaker's acquisition principal,
records ``started``, makes the call, and records ``completed`` or ``failed``
with an error code only. The permit's provider is ``elevenlabs``.

OPERATION KIND. The permit function knows five kinds, and changing it is a
migration of the whole permit function. Until counsel's review sets a
dedicated purpose for the AI voice (docs/FOUNDER-LOCK-ai-voice-practice-
2026-10-12.md section 7), both calls run as ``feedback_generation``, the kind
that already covers producing feedback from the speaker's recording, with a
manifest that names exactly what is sent. The feature is on for the
founder's account only until then.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from services.authorized_provider import ProviderCoordinates
from services.elevenlabs_client import ElevenLabsClient, Speech
from services.processing_authorization import ProcessingAuthorizationService

PROVIDER = "elevenlabs"
OPERATION = "feedback_generation"
PURPOSE = "practice_examples"


class AuthorizedVoiceProvider:
    def __init__(self, database: Any, coordinates: ProviderCoordinates, *,
                 client: Optional[ElevenLabsClient] = None,
                 authorization: Optional[ProcessingAuthorizationService] = None):
        self.coordinates = coordinates
        self.client = client or ElevenLabsClient()
        self.authorization = authorization or ProcessingAuthorizationService(database)

    def _permit(self, surface: str, content: list[str], key: str) -> Optional[str]:
        permit = self.authorization.issue_provider_permit(
            acquisition_principal_id=self.coordinates.acquisition_principal_id,
            take_id=self.coordinates.take_id,
            recording_id=self.coordinates.recording_id,
            provider=PROVIDER,
            operation_kind=OPERATION,
            minimum_data_manifest={"content": content, "purpose": PURPOSE,
                                   "surface": surface},
            idempotency_key=f"{PROVIDER}:{surface}:{key}:{uuid.uuid4().hex[:12]}",
        )
        permit_id = str((permit or {}).get("permit_id") or "") or None
        self.authorization.record_provider_event(permit_id, "started")
        return permit_id

    def _call(self, surface: str, content: list[str], key: str, call):
        permit_id = self._permit(surface, content, key)
        try:
            result = call()
        except Exception as error:
            self.authorization.record_provider_event(
                permit_id, "failed",
                error_code=str(getattr(error, "kind", "") or type(error).__name__))
            raise
        self.authorization.record_provider_event(
            permit_id, "completed", metadata={"result_kind": surface})
        return result

    def create_voice(self, *, owner_key: str, sample: bytes, filename: str,
                     content_type: str) -> str:
        return self._call(
            "voice_clone", ["voice_sample_audio"], owner_key,
            lambda: self.client.create_voice(
                name=f"willab-{owner_key[:12]}", sample=sample,
                filename=filename, content_type=content_type))

    def speak(self, *, owner_key: str, voice_id: str, body: dict) -> Speech:
        return self._call(
            "practice_example", ["bounded_transcript_sentence"], owner_key,
            lambda: self.client.speak(voice_id=voice_id, body=body))

    def delete_voice(self, *, owner_key: str, voice_id: str) -> None:
        # Deleting sends nothing of the speaker; it still leaves a trace.
        self._call("voice_delete", ["provider_voice_reference"], owner_key,
                   lambda: self.client.delete_voice(voice_id))
