"""A coach's training-corpus upload (POST /v2/coach/training-imports), from a
validated request to its 202 receipt.

Moved out of ``routes.v2.coach`` unchanged (founder 2026-10-12). The import's
work is ``services.training_import``; this is the request's order around it:
prepare (the content gate), the idempotent duplicate, the corpus registration
the processing-authorization path requires before any provider call (N58,
0435), then the analysis on a background thread.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: prepare_training_import reasons that are the audio's fault: a 422.
_GATE_REASONS = ("no_audio", "too_short", "silence", "gate", "gate_error",
                 "no_topic")


def _int_or(raw, default: int) -> int:
    """Form int with a fallback — a typo in an optional knob must not 400 an
    upload that already cost the coach a file read."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _stripped(form: Any, name: str) -> Optional[str]:
    return (form.get(name) or "").strip() or None


def _register_corpus_import(database, prepared: dict) -> Optional[tuple[dict, int]]:
    """Record that THIS route created the import, under the founder's corpus
    basis (N58, 0435): an import's provider calls are permitted only for a
    session registered here. None when recorded (or the gate is off, where
    nothing is permitted anyway); else the refusal, with the import marked
    failed, because under enforce nothing could analyse it."""
    from services.processing_authorization import (
        ProcessingAuthorizationError, register_corpus_import,
    )
    try:
        register_corpus_import(database, session_id=prepared["session_id"],
                               recording_id=prepared.get("recording_id"))
        return None
    except ProcessingAuthorizationError as refusal:
        logger.warning("training import not registered sid=%s code=%s",
                       prepared.get("session_id"), refusal.code)
        try:
            database.takes.set_session_analysis_state(
                prepared["session_id"], "failed", error=refusal.code)
        except Exception:
            logger.warning("could not mark the unregistered import failed",
                           exc_info=True)
        return ({"code": refusal.code,
                 "error": "the import could not be registered"}, refusal.status)


def _not_prepared(prepared: dict) -> tuple[dict, int]:
    reason = prepared.get("reason") or "failed"
    if reason in _GATE_REASONS:
        return {
            "code": "AUDIO_REJECTED", "reason": reason,
            "error": prepared.get("detail")
                     or "the audio did not pass the content gate",
        }, 422
    return {"code": "SERVER_ERROR", "reason": reason,
            "error": prepared.get("detail") or "import failed"}, 500


def _start_analysis(prepared: dict, audio_bytes: bytes, filename: str,
                    queue_per_band: int) -> None:
    """Whisper + the cutting pass is MINUTES on a long talk, and the FE's
    proxy caps far below that. Returning the request before the work
    removes the dangerous shape entirely: a gateway timeout on a request
    whose BE work then succeeded, which the coach reads as "failed" and
    retries into a duplicate. The FE polls
    GET /v2/coach/training-imports/<session_id> for the outcome; the
    session's analysis_state carries it (the same processing → ready |
    failed lane the live async path already uses)."""
    import threading

    from services.training_import import run_training_import_analysis
    thread = threading.Thread(
        target=run_training_import_analysis,
        kwargs={"prepared": prepared, "audio_bytes": audio_bytes,
                "filename": filename, "queue_per_band": queue_per_band},
        daemon=True,
    )
    thread.start()


def start_training_import(database, audio_file: Any, form: Any, *,
                          uploader_id: Any, topic: str,
                          language: str) -> tuple[dict, int]:
    """(payload, status) for one validated upload: 202 with the receipt, 200
    for a duplicate, 422 for audio the content gate refused, the
    registration's refusal, or 500."""
    audio_bytes = audio_file.read()
    from services.training_import import prepare_training_import
    filename = audio_file.filename or "import.webm"
    queue_per_band = _int_or(form.get("queue_per_band"), 5)
    prepared = prepare_training_import(
        audio_bytes=audio_bytes,
        filename=filename,
        content_type=audio_file.mimetype,
        user_id=(form.get("user_id") or uploader_id),
        topic=topic,
        speaker_label=_stripped(form, "speaker_label"),
        source_note=_stripped(form, "note"),
        stages=(form.get("stages") or None),
        # BOTH spellings (fix 2026-07-29): the FE ships `idempotency_key`,
        # the coach-video lane's name is `upload_idempotency_key`.
        idempotency_key=((form.get("idempotency_key")
                          or form.get("upload_idempotency_key")
                          or "").strip() or None),
        language=language,
    )
    if not prepared.get("ok"):
        return _not_prepared(prepared)
    # The idempotency key already produced this import — return the
    # original rather than minting a second (a talk imported twice is
    # labelled twice and trains twice, invisibly).
    if prepared.get("duplicate"):
        return {**prepared, "status": "duplicate"}, 200
    if (unregistered := _register_corpus_import(database, prepared)) is not None:
        return unregistered
    _start_analysis(prepared, audio_bytes, filename, queue_per_band)
    # THE 202 IS A RECEIPT, NOT A RESULT — and it must be impossible to
    # read as one (FE §6.4). It carries NO count field: a consumer whose
    # rule is "ok:true with a count present = finished" would otherwise
    # see a bare ok:true, default the missing counts to 0, and announce a
    # zero-piece failure that never happened. `status: "processing"` says
    # the same thing positively. Both properties are pinned by test —
    # adding snippet_count/queue_count here would break a real consumer.
    return {
        "ok": True, "status": "processing",
        "session_id": prepared["session_id"],
        "arc_id": prepared["arc_id"],
        "stages": prepared["stages"],
        "duration_sec": prepared.get("duration_sec"),
        "speaker_label": prepared.get("speaker_label"),
        "language": prepared.get("language"),
        "filename": filename,
    }, 202
