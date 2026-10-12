"""Behaviour of ``OpenAIService.transcribe_audio`` — F1 piece (a), the
per-slide transcription's provider call (audit Q-A4, Phase 3).

Until this file existed the only tests around transcription mocked
``transcribe_audio`` itself (``test_recording_transcription.py`` pins what
happens around it). Nothing pinned what the function sends to Whisper or
what it hands back, and the module sat at 17.6% coverage. These tests use
a fake client that records the request and replies with a shaped response;
no network, no credentials, no prompt text is asserted verbatim (the prompt
registry's ``legacy_openai.whisper_priming`` entry owns the prompt).

What is pinned here, because the live loop depends on it:

* the request shape: whisper-1, verbose_json, segment AND word timestamps,
  the file tuple with a content type that never silently defaults to webm;
* the language rule from 2026-07-29: an English disfluency prompt on
  non-English audio is worse than none, so a declared non-English language
  drops the prompt and keeps only the domain vocabulary;
* the response contract read by ``services/recording_transcription.py``:
  text, duration, language, segments, words — all present, words absolute
  seconds, a dict-shaped word tolerated, a malformed one dropped;
* the fallbacks: word granularity unavailable → segments-only retry; usage
  ledger failure never touches the transcript; a provider failure is wrapped
  and reported; no client → refuse before touching the audio.
"""
from __future__ import annotations

import types
from io import BytesIO
from unittest.mock import patch

import pytest

import services.openai_service as osvc

# ── a fake OpenAI client with the two surfaces transcribe_audio touches ──────

class _Seg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class _Word:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


def _response(*, text="hello there", language="en", segments=None, words=None):
    return types.SimpleNamespace(
        text=text, language=language,
        segments=[_Seg(0.0, 1.5, " hello "), _Seg(1.5, 3.25, "there")] if segments is None else segments,
        words=[_Word("hello", 0.0, 0.9), _Word("there", 1.6, 3.25)] if words is None else words,
    )


class _FakeClient:
    """Records every ``audio.transcriptions.create`` call; ``replies`` is a
    list consumed in order — an Exception instance is raised instead."""

    def __init__(self, replies=None):
        self.calls: list[dict] = []
        self.options: list[dict] = []
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
        self.options.append(kwargs)
        return self


def _service(client):
    svc = osvc.OpenAIService.__new__(osvc.OpenAIService)
    svc.client = client
    return svc


@pytest.fixture(autouse=True)
def _quiet_side_channels(monkeypatch):
    """The ledger and Sentry are best-effort side channels; keep them out of
    the way unless a test patches them on purpose."""
    monkeypatch.setattr("services.llm_usage.record_audio_usage", lambda **kw: None)
    monkeypatch.setattr(osvc.sentry_sdk, "capture_exception", lambda *a, **k: None)
    # mimetypes tables differ per platform; the fallback table under test is
    # the module's own. Tests that want mimetypes' answer patch it back.
    monkeypatch.setattr(osvc.mimetypes, "guess_type", lambda *_a, **_k: (None, None))


# ── the request ──────────────────────────────────────────────────────────────


# ── the language rule (2026-07-29) ───────────────────────────────────────────


def test_non_english_language_drops_the_english_prompt_and_keeps_vocabulary():
    client = _FakeClient()
    _service(client).transcribe_audio(
        BytesIO(b"x"), "take.webm", language="pl", vocabulary=["Kraków", " OKR ", ""],
    )
    call = client.calls[0]
    assert call["language"] == "pl"
    assert call["prompt"] == "Kraków, OKR."


# ── the response contract ────────────────────────────────────────────────────


# ── fallbacks and failure ────────────────────────────────────────────────────


def test_provider_failure_is_wrapped_and_reported_to_sentry():
    captured = []
    with patch.object(osvc.sentry_sdk, "capture_exception", captured.append):
        with pytest.raises(Exception, match=r"^Transcription failed: .*whisper down"):
            _service(_FakeClient([RuntimeError("whisper down"), RuntimeError("whisper down")])) \
                .transcribe_audio(BytesIO(b"x"), "take.webm")
    assert len(captured) == 1 and str(captured[0]) == "whisper down"
