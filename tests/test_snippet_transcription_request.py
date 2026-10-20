"""
STORY    As a speaker, I want each short clip sent to transcription in a
         format the provider accepts and the result cleaned up, so that my
         practice and feedback get accurate words.
OUTCOME
  O1  The file name is fixed up to its lowercase extension and its type
      sent; no language is forced without a hint.
  O2  The returned text is trimmed, malformed word times are dropped, the
      duration is in ms, and the clip's seconds are recorded as usage.
PROVES   O1 -> test_the_filename_is_fixed_up_to_its_lowercase_extension
         O2 -> test_the_result_is_cleaned_and_its_usage_recorded
WHY      tests/test_snippet_transcription.py covers a missing client.
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


def test_the_result_is_cleaned_and_its_usage_recorded(monkeypatch):
    _, usage, _ = _client(monkeypatch, _REPLY)

    out = snippet_transcription.transcribe_snippet_bytes(b"audio", "snippet.mp3")

    assert out == {
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
