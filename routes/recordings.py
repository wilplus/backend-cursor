"""V2 recordings only (taskmaster homework flow)."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
import sentry_sdk
import uuid

recordings_v2_bp = Blueprint("recordings_v2", __name__)


def _is_valid_uuid(value):
    """Return True if value is a valid UUID string."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _build_transcript_preview(transcription_text, max_len=280):
    """Return first max_len chars of transcript, or empty string if None/empty."""
    if not transcription_text:
        return ""
    t = (transcription_text or "").strip()
    return t if len(t) <= max_len else (t[:max_len].rstrip() + "…")


@recordings_v2_bp.route("/<recording_id>", methods=["GET"])
@require_auth
def get_recording_v2(recording_id):
    """
    Get a recording by id (owner-only). Returns 404 for not found or not allowed.
    Includes transcription_text and optional transcript_preview.
    """
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400

        user_id = request.user_id
        recording = db.get_recording(recording_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404

        transcription_text = recording.get("transcription_text")
        transcript_preview = _build_transcript_preview(transcription_text)

        payload = {
            "id": recording.get("id"),
            "user_id": recording.get("user_id"),
            "created_at": recording.get("created_at"),
            "session_id": recording.get("session_id"),
            "session_v2_id": recording.get("session_v2_id"),
            "transcription_text": transcription_text,
            "transcript_preview": transcript_preview or None,
            "duration_seconds": recording.get("duration_seconds") or recording.get("duration"),
            "words_per_minute": recording.get("words_per_minute"),
            "filler_words_count": recording.get("filler_words_count"),
            "performance_score_v2": recording.get("performance_score_v2"),
            "performance_metrics_v2": recording.get("performance_metrics_v2"),
            "metric_labels_snapshot_v2": recording.get("metric_labels_snapshot_v2"),
        }
        return jsonify(payload), 200

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RECORDING_ERROR", "error": str(e)}), 500
