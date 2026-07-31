"""Per-snippet Whisper transcription.

Wraps OpenAI Whisper for short MP3 snippet bytes, returning text + detected language
+ word-level timestamps in a single normalized dict. Failures return None — callers
should treat transcription as best-effort and never block snippet creation on it.

Cost: Whisper-1 is ~$0.006/min. 8 snippets x 3s ~= $0.0024 per recording. Negligible.
Latency: ~1s per snippet, sequential by default. Caller may parallelize if needed.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from io import BytesIO
from typing import Any, Optional

import sentry_sdk

from services.openai_service import openai_service

logger = logging.getLogger(__name__)

# Disfluent prompt mirrors openai_service.transcribe_audio so Whisper preserves
# filler words ("um", "uh", "i mean") rather than auto-cleaning them. Critical
# because filler density is what the candidate generator reads downstream.
_DISFLUENT_PROMPT = "Umm, let me think like, hmm... Okay, so, uh, yeah. I mean, you know, it's like, um, well..."


def transcribe_snippet_bytes(
    mp3_bytes: bytes,
    hint_filename: str = "snippet.mp3",
    *,
    language_hint: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Run Whisper on a single snippet's MP3 bytes.

    Returns {transcript, language, words, transcribed_duration_ms} or None on failure.
    `words` is a list of {word, start, end} per Whisper's verbose_json word granularity.

    `language_hint` (ISO 639-1, e.g. 'en', 'pl') is optional. Pass it when the parent
    recording's language is known to anchor detection on short clips where auto-detect
    can flip on accents/noise.
    """
    if not mp3_bytes:
        return None
    client = getattr(openai_service, "client", None)
    if client is None:
        logger.warning("snippet_transcription: OpenAI client not initialized; skipping")
        return None

    ct = mimetypes.guess_type(hint_filename or "")[0] or "audio/mpeg"
    ext = os.path.splitext(hint_filename or "")[1].lower() or ".mp3"
    if not (hint_filename or "").endswith(ext):
        hint_filename = f"snippet{ext}"

    kwargs: dict[str, Any] = {
        "model": "whisper-1",
        "file": (hint_filename, mp3_bytes, ct),
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
        "prompt": _DISFLUENT_PROMPT,
    }
    if language_hint:
        kwargs["language"] = language_hint

    try:
        resp = client.audio.transcriptions.create(**kwargs)
    except Exception as e:
        logger.warning(
            "snippet_transcription: Whisper call failed size=%d hint_lang=%s err=%s",
            len(mp3_bytes), language_hint, type(e).__name__,
        )
        sentry_sdk.capture_exception(e)
        return None

    # Normalize response: openai SDK returns an object with attributes; older versions
    # may return dicts. Handle both.
    def _attr(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    text = (_attr(resp, "text", "") or "").strip()
    language = (_attr(resp, "language", None) or None)
    duration_seconds = _attr(resp, "duration", None)
    words_raw = _attr(resp, "words", None) or []

    words: list[dict[str, Any]] = []
    for w in words_raw:
        try:
            words.append({
                "word": str(_attr(w, "word", "")),
                "start": float(_attr(w, "start", 0.0) or 0.0),
                "end": float(_attr(w, "end", 0.0) or 0.0),
            })
        except (TypeError, ValueError):
            continue

    transcribed_duration_ms: Optional[int] = None
    try:
        if duration_seconds is not None:
            transcribed_duration_ms = int(round(float(duration_seconds) * 1000.0))
    except (TypeError, ValueError):
        transcribed_duration_ms = None

    # Cost ledger (token-pricing Phase 0). Re-Whispering a single piece is the
    # cost of a COACH/ADMIN boundary edit, not of a take — kept on its own
    # surface so it can never be mistaken for per-take transcription spend.
    try:
        from services.llm_usage import record_audio_usage
        record_audio_usage(surface="whisper_snippet", seconds=duration_seconds)
    except Exception:
        pass

    return {
        "transcript": text or None,
        "language": (language or None),
        "words": words or None,
        "transcribed_duration_ms": transcribed_duration_ms,
    }


def transcribe_snippet_from_bytesio(bio: BytesIO, hint_filename: str = "snippet.mp3", **kw) -> Optional[dict[str, Any]]:
    """Convenience wrapper for callers holding a BytesIO buffer."""
    try:
        bio.seek(0)
        data = bio.read()
        bio.seek(0)
    except Exception as e:
        logger.warning("snippet_transcription: BytesIO read failed: %s", type(e).__name__)
        sentry_sdk.capture_exception(e)
        return None
    return transcribe_snippet_bytes(data, hint_filename=hint_filename, **kw)
