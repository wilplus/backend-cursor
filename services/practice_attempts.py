"""A practice try and the practice's end (POST
/v2/user/confidence-practice/<id>/attempts and PUT .../complete).

Moved out of ``routes.v2.user_sessions`` unchanged (founder 2026-10-12). The
route's auth, purpose guard and consent choices (personalised practice; the
try also needs sensitive information) run before anything here, and the
route finds the speaker's own practice first.

A try is transcribed through ``services.practice_transcription`` (the
processing-authorization path for every provider call), checked against the
passage, measured, stored, recorded, and the first passage-valid try is the
stable comparison target. Raw scores stay private (AC-9): only the route's
owner-safe payload reaches the speaker.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from services.refusal import Refusal
from utils.ids import is_uuid

logger = logging.getLogger(__name__)


def _coach_asked_own_wording(practice) -> bool:
    """The shown words are required unless the coach's shared exercise asks
    for different wording (founder 2026-09-28, 14B)."""
    shared = practice.get("coach_shared_exercise") if isinstance(
        practice, dict) else None
    return isinstance(shared, dict) and shared.get("own_wording") is True


def _passage_refused(practice, alignment) -> bool:
    """The attempt did not say the shown words, and the coach did not ask
    for different ones (founder 2026-09-28, 14B)."""
    return (not alignment.get("matches")
            and not _coach_asked_own_wording(practice))


def _attempt_comparison(database, practice, original, current_snapshot,
                        previous, metrics, baseline, baseline_kind) -> dict:
    """The versioned before/after observation (no automatic outcome), with
    both sides' delivery-cue reads beside it (Phase 3, F5) whenever the
    speaker has a baseline. Raw, versioned, never an improvement label."""
    from services.after_practice import attach_cue_reads
    comparison = {
        "contract_version": "practice-product-observation-v1",
        "baseline": original,
        "attempt": current_snapshot,
        "previous_attempt": previous,
        "no_automatic_outcome": True,
    }
    if not baseline:
        return comparison
    snippet = database.get_snippet_by_id(str(practice.get("snippet_id") or "")) or {}
    return attach_cue_reads(
        comparison, original_metrics=snippet.get("metrics"),
        attempt_metrics=metrics, baseline=baseline, baseline_kind=baseline_kind)


def _audio(upload: Any) -> tuple[bytes, str, str]:
    """(remuxed bytes, mime, extension), or 422 when too short."""
    audio_bytes = upload.read()
    if len(audio_bytes) < 1000:
        raise Refusal("AUDIO_TOO_SHORT", "That recording was too short. Try again.", 422)
    from services.webm_remux import remux_webm_for_seeking
    audio_bytes = remux_webm_for_seeking(audio_bytes, label="practice")
    mime = (upload.mimetype or "audio/webm").split(";", 1)[0]
    ext = ".webm" if "webm" in mime else ".m4a" if "mp4" in mime else ".wav"
    return audio_bytes, mime, ext


def _heard(database, practice, audio_bytes, ext) -> tuple[dict, dict]:
    """(transcription, alignment): the try transcribed and held to the
    passage shown."""
    from services.practice_transcription import transcribe_practice_attempt
    transcription = transcribe_practice_attempt(
        database, practice, audio_bytes, hint_filename=f"practice{ext}")
    if not transcription or not transcription.get("transcript"):
        raise Refusal("TRANSCRIPTION_FAILED",
                      "We couldn't hear that clearly. Try again.", 422)
    from services.confident_voice_practice import passage_alignment
    alignment = passage_alignment(
        str(practice.get("exact_passage") or ""),
        str(transcription.get("transcript") or ""))
    if _passage_refused(practice, alignment):
        raise Refusal("PASSAGE_MISMATCH",
                      "Please read the exact passage shown and try again.", 422)
    return transcription, alignment


def _duration_sec(transcription: dict, form: Any) -> float:
    duration_ms = transcription.get("transcribed_duration_ms")
    try:
        captured = max(0.0, float(form.get("duration_sec") or 0.0))
    except (TypeError, ValueError):
        captured = 0.0
    return (float(duration_ms) / 1000.0
            if isinstance(duration_ms, int) and duration_ms > 0 else captured)


def _confidence_baseline(database, practice, practice_id, metrics,
                         user_id) -> tuple[Any, str]:
    """Apply the SAME existing, self-relative acoustic confidence signal used
    by full-take snippets when a valid speaker/take baseline is available.
    Honest absence stays None; we never synthesize a score."""
    baseline, baseline_kind = None, "none"
    try:
        from services.voice_confidence import (
            read_for_piece, resolve_confidence_baseline,
        )
        take_rows = database.get_snippets_by_session(
            str(practice.get("take_session_id"))) or []
        take_metrics = [row.get("metrics") for row in take_rows
                        if isinstance(row.get("metrics"), dict)]
        baseline, baseline_kind = resolve_confidence_baseline(
            str(practice.get("owner_user_id") or user_id),
            take_metrics, database=database)
        confidence_read = read_for_piece(metrics, baseline, baseline_kind)
        if confidence_read:
            metrics["voice_confidence"] = confidence_read
    except Exception as confidence_err:
        logger.info(
            "confidence-practice attempt confidence unavailable id=%s: %s",
            practice_id, confidence_err)
    return baseline, baseline_kind


def _store_audio(key: str, audio_bytes: bytes, mime: str) -> tuple[Any, str]:
    """(bucket, audio_ref) for the stored try."""
    from services.lab_audio_storage import (
        lab_audio_public_url, put_lab_audio_bytes, target_bucket)
    bucket = put_lab_audio_bytes(key, audio_bytes, mime)
    return bucket, (lab_audio_public_url(key)
                    or f"s3://{bucket or target_bucket()}/{key}")


def add_attempt(database, *, practice: dict, practice_id: str,
                existing: list, upload: Any, form: Any,
                user_id: Any) -> list:
    """Transcribe, check, measure, store and record one try; the practice's
    attempts afterwards. Raises ``Refusal`` for a try that is turned down."""
    audio_bytes, mime, ext = _audio(upload)
    transcription, alignment = _heard(database, practice, audio_bytes, ext)
    from services.audio_metrics import analyze_audio
    from services.confident_voice_practice import (
        acoustic_snapshot, machine_confidence_decision,
    )
    duration_ms = transcription.get("transcribed_duration_ms")
    duration_sec = _duration_sec(transcription, form)
    metrics = analyze_audio(
        audio_bytes, str(transcription["transcript"]), duration_sec)
    if not metrics:
        raise Refusal("ANALYSIS_FAILED",
                      "We couldn't compare that attempt. Try again.", 422)
    baseline, baseline_kind = _confidence_baseline(
        database, practice, practice_id, metrics, user_id)
    current_snapshot = acoustic_snapshot({
        "metrics": metrics,
        "words": transcription.get("words") or [],
        "duration_ms": duration_ms or int(duration_sec * 1000),
        "audio_ref": "captured",
        "transcript": transcription["transcript"],
    })
    original = ((practice.get("acoustic_evidence") or {}).get("snapshot")
                if isinstance(practice.get("acoustic_evidence"), dict) else {}) or {}
    previous = (existing[-1].get("acoustic_metrics") if existing else None)
    # Keep raw, versioned before/after observations for later validation,
    # but do not manufacture an improvement label or choose a "best"
    # attempt before the need-specific thresholds are approved.
    comparison = _attempt_comparison(
        database, practice, original, current_snapshot, previous, metrics,
        baseline, baseline_kind)
    attempt_index = len(existing) + 1
    key = (f"confidence-practice/{user_id}/{practice_id}/"
           f"{attempt_index}-{uuid.uuid4().hex}{ext}")
    bucket, audio_ref = _store_audio(key, audio_bytes, mime)
    from services.practice_audio_objects import record_practice_attempt
    inserted = record_practice_attempt(database, {
        "practice_id": str(practice_id),
        "attempt_index": attempt_index,
        "storage_path": key,
        "audio_ref": audio_ref,
        "mime_type": mime,
        "duration_ms": int(duration_ms or max(1, duration_sec * 1000)),
        "transcript": str(transcription["transcript"]),
        "transcript_alignment": alignment,
        "acoustic_metrics": current_snapshot,
        "comparison": comparison,
        "assessment_key": "recorded_for_comparison",
        "machine_confidence_decision": machine_confidence_decision(current_snapshot),
    }, practice=practice, bucket=bucket, audio_bytes=audio_bytes)
    if not inserted:
        raise Refusal("V2_ERROR", "Could not save that attempt.", 500)
    # The first passage-valid attempt is the stable comparison target.
    # Later attempts remain visible, but cannot be cherry-picked by an
    # unvalidated score.
    strongest = min(existing + [inserted], key=lambda row: int(
        row.get("attempt_index") or 2**31 - 1
    ))
    database.set_confident_voice_practice_strongest(
        practice_id, str(strongest.get("id")))
    return database.list_confident_voice_practice_attempts(practice_id)


def _kept_attempt(database, practice_id: str, body: dict) -> tuple[str, str]:
    answer, attempt_id = body.get("user_answer"), body.get("attempt_id")
    if answer not in ("yes", "no") or not is_uuid(str(attempt_id or "")):
        raise Refusal("INVALID_INPUT", "attempt_id and user_answer are required", 400)
    attempts = database.list_confident_voice_practice_attempts(practice_id)
    comparison_attempt = next(
        (row for row in attempts if row.get("is_strongest")), None)
    if (not comparison_attempt
            or str(comparison_attempt.get("id")) != str(attempt_id)):
        raise Refusal("INVALID_INPUT", "Use the frozen first valid attempt.", 400)
    if not database.keep_confident_voice_practice_attempt(
            practice_id, str(attempt_id), str(answer)):
        raise Refusal("NOT_FOUND", "attempt not found", 404)
    return str(attempt_id), str(answer)


def complete_practice(database, *, practice: dict, practice_id: str,
                      user_id: Any, body: dict) -> dict:
    """Dismiss the practice or keep its frozen comparison try; the updated
    row. Never writes any presentation surface: no ideal-text, decision,
    style, cue, flagship or voice_album call belongs here. Professional
    review remains separate."""
    if practice.get("status") != "open":
        raise Refusal("PRACTICE_CLOSED", "This practice is already closed.", 409)
    now = datetime.now(timezone.utc).isoformat()
    if body.get("action") == "dismiss":
        updated: Optional[dict] = database.update_confident_voice_practice(
            practice_id, str(user_id), {"status": "dismissed", "closed_at": now})
        if not updated:
            raise Refusal("V2_ERROR", "Could not close this practice.", 500)
        return updated
    attempt_id, answer = _kept_attempt(database, practice_id, body)
    updated = database.update_confident_voice_practice(
        practice_id, str(user_id), {
            "status": "completed",
            "selected_attempt_id": attempt_id,
            "final_user_answer": answer,
            "closed_at": now,
        })
    if not updated:
        raise Refusal("V2_ERROR", "Could not finish this practice.", 500)
    return updated
