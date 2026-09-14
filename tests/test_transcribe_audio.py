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

def test_request_is_whisper1_verbose_json_with_segment_and_word_timestamps():
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"RIFFdata"), "take.webm")
    (call,) = client.calls
    assert call["model"] == "whisper-1"
    assert call["response_format"] == "verbose_json"
    assert call["timestamp_granularities"] == ["segment", "word"]
    assert call["file"] == ("take.webm", b"RIFFdata", "audio/webm")


def test_transcription_runs_on_the_larger_transcribe_timeout():
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), "take.webm")
    assert client.options == [{"timeout": osvc.config.OPENAI_TRANSCRIBE_TIMEOUT_SECONDS}]


@pytest.mark.parametrize("filename, content_type, expected", [
    ("take.webm", "audio/x-custom", "audio/x-custom"),   # explicit wins
    ("take.m4a", None, "audio/mp4"),                      # module table
    ("take.opus", "  ", "audio/opus"),                    # blank explicit → table
    ("take.xyz", None, "application/octet-stream"),       # unknown → octet-stream
    ("", None, "application/octet-stream"),               # no name at all
])
def test_content_type_never_silently_defaults_to_webm(filename, content_type, expected):
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), filename, content_type=content_type)
    name, _bytes, ct = client.calls[0]["file"]
    assert ct == expected
    assert name == (filename or "audio.bin")


def test_mimetypes_answer_is_preferred_over_the_module_table(monkeypatch):
    monkeypatch.setattr(osvc.mimetypes, "guess_type", lambda *_a, **_k: ("audio/from-mimetypes", None))
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), "take.webm")
    assert client.calls[0]["file"][2] == "audio/from-mimetypes"


# ── the language rule (2026-07-29) ───────────────────────────────────────────

def test_unknown_language_keeps_the_disfluency_prompt_and_no_language_hint():
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), "take.webm")
    call = client.calls[0]
    assert "language" not in call
    assert call["prompt"].startswith("Umm, let me think")


def test_english_keeps_the_prompt_and_passes_the_normalised_code():
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), "take.webm", language=" EN-us ")
    call = client.calls[0]
    assert call["language"] == "en-us"
    assert call["prompt"].startswith("Umm, let me think")


def test_non_english_language_drops_the_english_prompt_and_keeps_vocabulary():
    client = _FakeClient()
    _service(client).transcribe_audio(
        BytesIO(b"x"), "take.webm", language="pl", vocabulary=["Kraków", " OKR ", ""],
    )
    call = client.calls[0]
    assert call["language"] == "pl"
    assert call["prompt"] == "Kraków, OKR."


def test_non_english_language_without_vocabulary_sends_no_prompt_at_all():
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), "take.webm", language="de")
    call = client.calls[0]
    assert call["language"] == "de"
    assert "prompt" not in call


def test_vocabulary_is_appended_to_the_prompt_and_capped_at_forty_terms():
    terms = [f"term{i}" for i in range(50)]
    client = _FakeClient()
    _service(client).transcribe_audio(BytesIO(b"x"), "take.webm", vocabulary=terms + ["  "])
    prompt = client.calls[0]["prompt"]
    assert prompt.startswith("Umm, let me think")
    assert prompt.endswith("term39.")
    assert "term40" not in prompt


# ── the response contract ────────────────────────────────────────────────────

def test_result_carries_text_duration_language_segments_and_words():
    out = _service(_FakeClient()).transcribe_audio(BytesIO(b"x"), "take.webm")
    assert out["text"] == "hello there"
    assert out["language"] == "en"
    assert out["duration"] == 3.25                       # last segment's end
    assert out["segments"] == [
        {"start": 0.0, "end": 1.5, "text": "hello"},     # stripped
        {"start": 1.5, "end": 3.25, "text": "there"},
    ]
    assert out["words"] == [
        {"word": "hello", "start": 0.0, "end": 0.9},
        {"word": "there", "start": 1.6, "end": 3.25},
    ]


def test_dict_shaped_words_are_read_and_malformed_words_are_dropped():
    words = [
        {"word": "one", "start": 0.0, "end": 0.4},
        {"word": "two", "start": 0.5},                 # no end → end = start
        {"word": "three", "start": "later"},           # non-numeric start → dropped
        {"start": 1.0, "end": 1.2},                    # no word → dropped
    ]
    out = _service(_FakeClient([_response(words=words)])).transcribe_audio(BytesIO(b"x"), "t.webm")
    assert out["words"] == [
        {"word": "one", "start": 0.0, "end": 0.4},
        {"word": "two", "start": 0.5, "end": 0.5},
    ]


def test_no_segments_means_zero_duration_and_empty_lists():
    out = _service(_FakeClient([_response(segments=[], words=None)])).transcribe_audio(
        BytesIO(b"x"), "t.webm",
    )
    assert out["duration"] == 0.0
    assert out["segments"] == []
    # words=None in the fixture means "use the default words"; the response
    # still carries them and they are independent of segments.
    assert [w["word"] for w in out["words"]] == ["hello", "there"]


def test_audio_stream_is_rewound_after_the_bytes_are_read():
    audio = BytesIO(b"abcdef")
    _service(_FakeClient()).transcribe_audio(audio, "take.webm")
    assert audio.tell() == 0


# ── fallbacks and failure ────────────────────────────────────────────────────

def test_word_granularity_rejected_by_the_provider_falls_back_to_segments_only():
    client = _FakeClient([RuntimeError("unknown parameter timestamp_granularities"),
                          _response(words=[])])
    out = _service(client).transcribe_audio(BytesIO(b"x"), "take.webm", language="pl")
    assert len(client.calls) == 2
    assert "timestamp_granularities" in client.calls[0]
    assert "timestamp_granularities" not in client.calls[1]
    # everything else about the request is preserved on the retry
    assert client.calls[1]["language"] == "pl"
    assert client.calls[1]["model"] == "whisper-1"
    assert out["text"] == "hello there"
    assert out["words"] == []


def test_audio_usage_is_recorded_on_billable_seconds_with_attribution():
    seen = {}
    with patch("services.llm_usage.record_audio_usage", lambda **kw: seen.update(kw)):
        _service(_FakeClient()).transcribe_audio(
            BytesIO(b"x"), "take.webm",
            usage_surface="whisper_read", usage_user_id="u1",
            usage_session_id="s1", usage_arc_id="a1",
        )
    assert seen == {"surface": "whisper_read", "seconds": 3.25,
                    "user_id": "u1", "session_id": "s1", "arc_id": "a1"}


def test_usage_ledger_failure_never_touches_the_transcript():
    def _boom(**_kw):
        raise RuntimeError("ledger down")
    with patch("services.llm_usage.record_audio_usage", _boom):
        out = _service(_FakeClient()).transcribe_audio(BytesIO(b"x"), "take.webm")
    assert out["text"] == "hello there"


def test_provider_failure_is_wrapped_and_reported_to_sentry():
    captured = []
    with patch.object(osvc.sentry_sdk, "capture_exception", captured.append):
        with pytest.raises(Exception, match=r"^Transcription failed: .*whisper down"):
            _service(_FakeClient([RuntimeError("whisper down"), RuntimeError("whisper down")])) \
                .transcribe_audio(BytesIO(b"x"), "take.webm")
    assert len(captured) == 1 and str(captured[0]) == "whisper down"


def test_missing_client_refuses_before_touching_the_audio():
    class _Untouchable:
        def seek(self, *_a):
            raise AssertionError("audio must not be read without a client")
        read = seek

    with pytest.raises(Exception, match="OpenAI client not initialized"):
        _service(None).transcribe_audio(_Untouchable(), "take.webm")
