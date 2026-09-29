"""The per-snippet Whisper request and its normalized result, pinned.

`tests/test_snippet_transcription.py` covers a missing client. These cases
pin what reaches the provider and what comes back from it, by behaviour.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import snippet_transcription


class _Transcriptions:
    def __init__(self, reply):
        self.reply = reply
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def _client(monkeypatch, reply):
    transcriptions = _Transcriptions(reply)
    monkeypatch.setattr(
        snippet_transcription.openai_service, "client",
        SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions)))
    usage: list[dict] = []
    monkeypatch.setattr("services.llm_usage.record_audio_usage",
                        lambda **kwargs: usage.append(kwargs))
    captured: list[BaseException] = []
    monkeypatch.setattr(snippet_transcription.sentry_sdk, "capture_exception",
                        captured.append)
    return transcriptions, usage, captured


_REPLY = SimpleNamespace(
    id="resp-1", text="  um, so we grow.  ", language="english",
    duration=1.2345,
    words=[
        SimpleNamespace(word=" um", start=0.1, end=0.3, probability=0.9),
        {"word": "so", "start": "0.4", "end": None},
        {"word": "bad", "start": "x", "end": 1.0},
    ],
)


def test_the_request_and_the_normalized_result(monkeypatch):
    transcriptions, usage, _ = _client(monkeypatch, _REPLY)

    result = snippet_transcription.transcribe_snippet_bytes(
        b"audio", "clip.wav", language_hint="pl")

    (request,) = transcriptions.requests
    assert request == {
        "model": "whisper-1",
        "file": ("clip.wav", b"audio", "audio/x-wav"),
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
        "prompt": snippet_transcription._DISFLUENT_PROMPT,
        "language": "pl",
    }
    assert result == {
        "provider_response_id": "resp-1",
        "transcript": "um, so we grow.",
        "language": "english",
        "words": [
            {"word": " um", "start": 0.1, "end": 0.3, "confidence": 0.9},
            {"word": "so", "start": 0.4, "end": 0.0, "confidence": None},
        ],
        "transcribed_duration_ms": 1234,
    }
    assert usage == [{"surface": "whisper_snippet", "seconds": 1.2345}]


@pytest.mark.parametrize("hint,sent", [
    ("snippet.mp3", ("snippet.mp3", "audio/mpeg")),
    ("CLIP.MP3", ("snippet.mp3", "audio/mpeg")),
    ("noext", ("snippet.mp3", "audio/mpeg")),
    ("", ("snippet.mp3", "audio/mpeg")),
])
def test_the_filename_is_fixed_up_to_its_lowercase_extension(
    monkeypatch, hint, sent,
):
    transcriptions, _, _ = _client(monkeypatch, _REPLY)

    snippet_transcription.transcribe_snippet_bytes(b"audio", hint)

    name, _, content_type = transcriptions.requests[0]["file"]
    assert (name, content_type) == sent
    assert "language" not in transcriptions.requests[0]


def test_an_empty_reply_keeps_every_field_none(monkeypatch):
    _client(monkeypatch, {"text": "", "duration": "n/a"})

    assert snippet_transcription.transcribe_snippet_bytes(b"audio") == {
        "provider_response_id": None, "transcript": None, "language": None,
        "words": None, "transcribed_duration_ms": None,
    }


def test_a_provider_failure_is_none_and_reported(monkeypatch):
    error = TimeoutError("slow")
    _, usage, captured = _client(monkeypatch, error)

    assert snippet_transcription.transcribe_snippet_bytes(b"audio") is None
    assert captured == [error]
    assert usage == []


def test_a_provider_failure_raises_when_asked_to(monkeypatch):
    error = TimeoutError("slow")
    _client(monkeypatch, error)

    with pytest.raises(
        snippet_transcription.SnippetTranscriptionProviderError,
        match="^provider_outcome_uncertain:TimeoutError$",
    ) as raised:
        snippet_transcription.transcribe_snippet_bytes(
            b"audio", raise_on_provider_error=True)
    assert raised.value.__cause__ is error


def test_no_bytes_never_reaches_the_provider(monkeypatch):
    transcriptions, _, _ = _client(monkeypatch, _REPLY)

    assert snippet_transcription.transcribe_snippet_bytes(b"") is None
    assert transcriptions.requests == []
