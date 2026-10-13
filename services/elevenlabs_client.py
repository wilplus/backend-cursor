"""The ElevenLabs HTTP calls the AI voice needs, and nothing else.

Only ``services.authorized_voice_provider`` calls this module: every call
there takes a processing permit first (CLAUDE.md, "every provider call goes
through the processing-authorization path"). Nothing here logs the key, the
audio, the text sent, or the provider's voice id.

Endpoints (official Python SDK 2.71, 2026-10-05; docs/AI-VOICE-PRACTICE.md):

  POST   /v1/voices/add                    Instant Voice Clone (multipart)
  DELETE /v1/voices/{voice_id}             delete a clone
  GET    /v1/voices/{voice_id}             does the clone still exist
  POST   /v1/text-to-speech/{voice_id}     generate (JSON body, audio back)
  GET    /v1/user/subscription             credits used and the plan's limit
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from config import Config


class VoiceProviderError(Exception):
    """One ElevenLabs failure, by kind, never with user content.

    ``kind``: ``missing_key`` · ``invalid_key`` · ``rate_limited`` ·
    ``quota_exceeded`` · ``not_found`` · ``rejected`` (4xx we sent badly) ·
    ``outage`` (5xx, timeout, network). ``transient`` says whether one
    bounded retry may help.
    """

    def __init__(self, kind: str, status: Optional[int] = None,
                 code: Optional[str] = None):
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.code = code

    @property
    def transient(self) -> bool:
        return self.kind in ("rate_limited", "outage")


@dataclass(frozen=True)
class Speech:
    audio: bytes
    content_type: str
    request_id: Optional[str]
    #: The provider's own count when it sends one (header ``character-cost``
    #: or ``x-character-count``); None otherwise.
    character_cost: Optional[int]


_QUOTA_CODES = ("quota_exceeded", "insufficient_credits", "credits_exhausted")
#: ElevenLabs answers a voice that isn't there with a 400 and one of these
#: codes, not a 404; a delete must read it as "already gone".
_MISSING_CODES = ("voice_not_found", "voice_does_not_exist", "not_found")


def _error(response: httpx.Response) -> VoiceProviderError:
    status = response.status_code
    code = None
    try:
        detail = (response.json() or {}).get("detail")
        if isinstance(detail, dict):
            code = str(detail.get("status") or detail.get("code") or "") or None
    except Exception:  # noqa: BLE001 — a body that isn't JSON still has a status
        code = None
    if code in _QUOTA_CODES:
        return VoiceProviderError("quota_exceeded", status, code)
    if status == 401:
        return VoiceProviderError("invalid_key", status, code)
    if status == 404 or code in _MISSING_CODES:
        return VoiceProviderError("not_found", status, code)
    if status == 429:
        return VoiceProviderError("rate_limited", status, code)
    if status >= 500:
        return VoiceProviderError("outage", status, code)
    return VoiceProviderError("rejected", status, code)


def _int_header(response: httpx.Response, *names: str) -> Optional[int]:
    for name in names:
        raw = response.headers.get(name)
        if raw and raw.strip().isdigit():
            return int(raw.strip())
    return None


class ElevenLabsClient:
    def __init__(self, api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: Optional[float] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self._key = (api_key if api_key is not None
                     else Config.ELEVENLABS_API_KEY).strip()
        self._base = (base_url or Config.ELEVENLABS_API_BASE).rstrip("/")
        self._timeout = float(timeout or Config.ELEVENLABS_TIMEOUT_SECONDS)
        self._transport = transport

    def _client(self) -> httpx.Client:
        if not self._key:
            raise VoiceProviderError("missing_key")
        return httpx.Client(
            base_url=self._base, timeout=self._timeout,
            headers={"xi-api-key": self._key}, transport=self._transport)

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with self._client() as client:
                response = client.request(method, path, **kwargs)
        except VoiceProviderError:
            raise
        except httpx.HTTPError:
            raise VoiceProviderError("outage") from None
        if response.status_code >= 400:
            raise _error(response)
        return response

    def create_voice(self, *, name: str, sample: bytes, filename: str,
                     content_type: str) -> str:
        """One Instant Voice Clone from one sample; its provider voice id."""
        response = self._send(
            "POST", "/v1/voices/add",
            data={"name": name, "remove_background_noise": "false",
                  "description": "WillpowerLab practice voice"},
            files=[("files", (filename, sample, content_type))])
        voice_id = str((response.json() or {}).get("voice_id") or "")
        if not voice_id:
            raise VoiceProviderError("rejected", response.status_code,
                                     "NO_VOICE_ID")
        return voice_id

    def delete_voice(self, voice_id: str) -> None:
        """Delete one clone. A clone that is already gone counts as deleted."""
        try:
            self._send("DELETE", f"/v1/voices/{voice_id}")
        except VoiceProviderError as error:
            if error.kind != "not_found":
                raise

    def voice_exists(self, voice_id: str) -> bool:
        try:
            self._send("GET", f"/v1/voices/{voice_id}")
            return True
        except VoiceProviderError as error:
            if error.kind == "not_found":
                return False
            raise

    def speak(self, *, voice_id: str, body: dict,
              output_format: str = "mp3_44100_128") -> Speech:
        response = self._send(
            "POST", f"/v1/text-to-speech/{voice_id}",
            params={"output_format": output_format}, json=body,
            headers={"Accept": "audio/mpeg"})
        return Speech(
            audio=response.content,
            content_type=response.headers.get("content-type", "audio/mpeg"),
            request_id=response.headers.get("request-id"),
            character_cost=_int_header(
                response, "character-cost", "x-character-count"))

    def subscription(self) -> dict:
        """The plan's credits: ``used``, ``limit``, ``resets_unix``, ``tier``."""
        data = self._send("GET", "/v1/user/subscription").json() or {}
        return {
            "tier": data.get("tier"),
            "used": data.get("character_count"),
            "limit": data.get("character_limit"),
            "resets_unix": data.get("next_character_count_reset_unix"),
            "voice_slots_used": data.get("voice_slots_used"),
            "voice_limit": data.get("voice_limit"),
        }
