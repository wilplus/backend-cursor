"""
STORY    As a speaker, I want my recording sent to transcription correctly, so
         that my transcript is accurate in my language.
         (Critical path: record -> process, the transcript seam.)
OUTCOME
  O1  The request asks whisper-1 for verbose JSON with segment AND word
      timestamps, and the answer comes back as text, duration, language,
      segments and words (absolute seconds; a malformed word dropped).
  O2  Where word timestamps are refused, a segments-only call still returns
      the transcript.
  O3  Non-English audio drops the English prompt and keeps only my words.
  O4  A provider failure is wrapped and reported, never returned as text.
  O5  What the transcriber wrote that nobody said (a stretch it calls
      silence, a video's "Thanks for watching") is not in my transcript,
      its segments or its words; my own "Thank you." stays (N276).
PROVES   O1 -> test_the_request_and_the_transcript_it_returns
         O2 -> test_without_word_timestamps_the_transcript_still_arrives
         O3 -> test_non_english_language_drops_the_english_prompt_and_keeps_vocabulary
         O4 -> test_provider_failure_is_wrapped_and_reported_to_sentry
         O5 -> test_what_nobody_said_is_not_in_the_transcript
WHY      2026-07-29: an English prompt on Polish audio gave an empty transcript.

A fake client records the request; no network, no prompt text asserted
verbatim (the prompt registry owns it).
"""
from __future__ import annotations

import types
from io import BytesIO
from unittest.mock import patch

import pytest

import services.openai_service as osvc


class _Seg:
    def __init__(self, start, end, text, no_speech_prob=None, avg_logprob=None):
        self.start, self.end, self.text = start, end, text
        self.no_speech_prob, self.avg_logprob = no_speech_prob, avg_logprob


class _Word:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


def _response(*, words=None):
    return types.SimpleNamespace(
        text="hello there", language="en",
        segments=[_Seg(0.0, 1.5, " hello "), _Seg(1.5, 3.25, "there")],
        words=[_Word("hello", 0.0, 0.9), _Word("there", 1.6, 3.25)] if words is None else words,
    )


class _FakeClient:
    """Records every ``audio.transcriptions.create`` call; ``replies`` is a
    list consumed in order — an Exception instance is raised instead."""

    def __init__(self, replies=None):
        self.calls: list[dict] = []
        self.replies = list(replies) if replies is not None else [_response()]
        client = self

        class _Transcriptions:
            def create(self_inner, **kwargs):
                client.calls.append(kwargs)
                reply = client.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return reply

        self.audio = types.SimpleNamespace(transcriptions=_Transcriptions())

    def with_options(self, **kwargs):
        return self


def _service(client):
    svc = osvc.OpenAIService.__new__(osvc.OpenAIService)
    svc.client = client
    return svc


@pytest.fixture(autouse=True)
def _quiet_side_channels(monkeypatch):
    """The ledger and Sentry are best-effort side channels."""
    monkeypatch.setattr("services.llm_usage.record_audio_usage", lambda **kw: None)
    monkeypatch.setattr(osvc.sentry_sdk, "capture_exception", lambda *a, **k: None)


def test_the_request_and_the_transcript_it_returns():
    client = _FakeClient([_response(words=[
        _Word("hello", 0.0, 0.9),
        {"word": "there", "start": 1.6, "end": None},   # dict-shaped, no end
        _Word("lost", None, 2.0),                       # no start: dropped
    ])])
    out = _service(client).transcribe_audio(BytesIO(b"audio"), "take.webm")
    (call,) = client.calls
    assert call["model"] == "whisper-1"
    assert call["response_format"] == "verbose_json"
    assert call["timestamp_granularities"] == ["segment", "word"]
    assert call["file"][:2] == ("take.webm", b"audio")
    assert out == {
        "text": "hello there", "duration": 3.25, "language": "en",
        "segments": [{"start": 0.0, "end": 1.5, "text": "hello"},
                     {"start": 1.5, "end": 3.25, "text": "there"}],
        "words": [{"word": "hello", "start": 0.0, "end": 0.9},
                  {"word": "there", "start": 1.6, "end": 1.6}],
    }


def test_without_word_timestamps_the_transcript_still_arrives():
    client = _FakeClient([TypeError("timestamp_granularities"), _response(words=[])])
    out = _service(client).transcribe_audio(BytesIO(b"audio"), "take.webm")
    assert "timestamp_granularities" not in client.calls[1]
    assert out["text"] == "hello there"
    assert [s["text"] for s in out["segments"]] == ["hello", "there"]
    assert out["words"] == []


def test_non_english_language_drops_the_english_prompt_and_keeps_vocabulary():
    client = _FakeClient()
    _service(client).transcribe_audio(
        BytesIO(b"x"), "take.webm", language="pl", vocabulary=["Kraków", " OKR ", ""],
    )
    call = client.calls[0]
    assert call["language"] == "pl"
    assert call["prompt"] == "Kraków, OKR."


def test_provider_failure_is_wrapped_and_reported_to_sentry():
    captured = []
    with patch.object(osvc.sentry_sdk, "capture_exception", captured.append):
        with pytest.raises(Exception, match=r"^Transcription failed: .*whisper down"):
            _service(_FakeClient([RuntimeError("whisper down"), RuntimeError("whisper down")])) \
                .transcribe_audio(BytesIO(b"x"), "take.webm")
    assert len(captured) == 1 and str(captured[0]) == "whisper down"


def test_what_nobody_said_is_not_in_the_transcript():
    reply = types.SimpleNamespace(
        text="Thank you. Thanks for watching! Subscribe.", language="en",
        segments=[_Seg(0.0, 2.0, " Thank you.", 0.05, -0.2),            # said
                  _Seg(2.0, 6.0, " Thanks for watching!", 0.4, -0.5),   # a video's line
                  _Seg(6.0, 9.0, " Subscribe.", 0.9, -1.4)],            # silence, by Whisper's rule
        words=[_Word("Thank", 0.0, 0.5), _Word("you", 0.5, 1.0),
               _Word("Thanks", 2.1, 2.6), _Word("Subscribe", 6.2, 7.0)],
    )
    out = _service(_FakeClient([reply])).transcribe_audio(BytesIO(b"audio"), "take.webm")
    assert out["text"] == "Thank you."
    assert [s["text"] for s in out["segments"]] == ["Thank you."]
    assert [w["word"] for w in out["words"]] == ["Thank", "you"]
    assert out["duration"] == 9.0  # the recording's length, for the cost ledger
