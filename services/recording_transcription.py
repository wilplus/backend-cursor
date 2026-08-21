"""The transcription stage of the recording pipeline.

This module owns exactly the behavior that turns an accepted recording into a
punctuated word-timestamp stream.  It deliberately does not cut pieces, align
slides, compute acoustics, rank feedback, or persist snippets.

Failure semantics match the former inline implementation: provider and text
normalization failures are logged and return an empty/degraded transcript.  The
canonical-piece stage remains responsible for turning missing word timestamps
into the explicit retryable processing failure.
"""
from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import logging
from typing import Optional

from services.recording_state import RecordingState


logger = logging.getLogger(__name__)


# OpenAI Whisper rejects uploads larger than 25MB; compress above this
# threshold (a touch under 25MB for multipart/header headroom).
WHISPER_MAX_BYTES = 24 * 1024 * 1024


def merge_slide_vocabulary(session_context: Optional[dict]) -> Optional[list[str]]:
    """Merge domain vocabulary and slide titles for Whisper priming."""
    context = session_context or {}
    terms = list(context.get("domain_vocabulary") or [])
    for slide in (context.get("slides") or []):
        if isinstance(slide, dict):
            title = (slide.get("title") or "").strip()
            if title:
                terms.append(title)

    seen: set[str] = set()
    merged: list[str] = []
    for term in terms:
        key = (term or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(term.strip())
        if len(merged) >= 120:
            break
    return merged or None


def _transcription_audio(
    state: RecordingState,
    *,
    log: logging.Logger,
) -> tuple[bytes, str]:
    """Return Whisper-safe bytes/name, preserving original bytes on failure."""
    whisper_bytes = state.audio_bytes
    whisper_name = state.filename or "lab.webm"
    if len(state.audio_bytes) <= WHISPER_MAX_BYTES:
        return whisper_bytes, whisper_name

    from services.audio_metrics import compress_audio_for_whisper

    compressed = compress_audio_for_whisper(state.audio_bytes)
    if compressed and len(compressed) < len(state.audio_bytes):
        log.info(
            "process_lab_recording: compressed audio for whisper "
            "sid=%s %d→%d bytes",
            state.session_id,
            len(state.audio_bytes),
            len(compressed),
        )
        return compressed, "lab.mp3"
    return whisper_bytes, whisper_name


def _language_hint(session_context: Optional[dict]) -> Optional[str]:
    if not isinstance(session_context, dict):
        return None
    language = session_context.get("language")
    return (str(language).strip() or None) if language else None


def _settle_transcription_charge(
    state: RecordingState,
    transcription: dict,
    *,
    log: logging.Logger,
) -> None:
    """Settle the idempotent post-transcription token charge, best-effort."""
    try:
        from services.token_account import charge
        from services.token_prices import band_for_seconds

        activity = (
            "reread"
            if (state.recording_kind or "spoken") == "read"
            else band_for_seconds(transcription.get("duration"))
        )
        charge(
            str(state.user_id),
            activity,
            ref_id=str(state.recording_id),
        )
    except Exception as error:
        log.warning(
            "lab: token charge failed sid=%s err=%s",
            state.session_id,
            error,
        )


def _normalize_words(
    words: list,
    segments: list,
    *,
    session_id: str,
    log: logging.Logger,
) -> list:
    """Restore deterministic punctuation/run-on boundaries, best-effort."""
    normalized = words
    if normalized and segments:
        try:
            from services.slide_word_split import restore_punctuation

            normalized = restore_punctuation(normalized, segments)
        except Exception as error:
            log.warning(
                "process_lab_recording: punctuation restore failed sid=%s: "
                "%s (raw words kept)",
                session_id,
                error,
            )

    if normalized:
        try:
            from services.slide_word_split import (
                runon_split_enabled,
                split_runon_sentences,
            )

            if runon_split_enabled():
                normalized = split_runon_sentences(normalized)
        except Exception as error:
            log.warning(
                "process_lab_recording: run-on sentence split failed "
                "sid=%s: %s (words kept as-is)",
                session_id,
                error,
            )
    return normalized


def transcribe_recording(
    state: RecordingState,
    *,
    log: logging.Logger = logger,
) -> RecordingState:
    """Return a new state containing the normalized Whisper transcript."""
    try:
        from services.openai_service import OpenAIService

        service = OpenAIService()
        if not service.client:
            return replace(state, segments=(), words_all=())

        whisper_bytes, whisper_name = _transcription_audio(state, log=log)
        transcription = service.transcribe_audio(
            BytesIO(whisper_bytes),
            whisper_name,
            vocabulary=merge_slide_vocabulary(state.session_context),
            language=_language_hint(state.session_context),
            usage_surface=f"whisper_{state.recording_kind or 'spoken'}",
            usage_user_id=state.user_id,
            usage_session_id=state.session_id,
        ) or {}
        segments = list(transcription.get("segments") or [])
        words = list(transcription.get("words") or [])
        _settle_transcription_charge(state, transcription, log=log)
    except Exception as error:
        log.warning(
            "process_lab_recording.voice_metrics_diag sid=%s "
            "status=transcription_failed err=%s (acoustics still computed)",
            state.session_id,
            error,
        )
        return replace(state, segments=(), words_all=())

    words = _normalize_words(
        words,
        segments,
        session_id=state.session_id,
        log=log,
    )
    return replace(
        state,
        segments=tuple(segments),
        words_all=tuple(words),
    )
