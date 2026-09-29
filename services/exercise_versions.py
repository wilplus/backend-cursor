"""An exercise keeps its versions (founder 2026-09-29, decision 4; 0399).

The live library ``diagnostic_exercise`` is upserted in place, so a save
that changes what an exercise IS (its texts, its targets, its patterns, its
video) bumps the row's version and writes one immutable version row beside
it: the definition as saved, the AI script draft if the coach asked for one,
the coach's final text, the video's lineage and the transcript of the video.
An outcome points at the exact version shown (0372, 0387 store it), and from
here on that version can be read back.

THE TRANSCRIPT IS MADE AT UPLOAD, UNDER THE COACH'S OWN AUTHORIZATION. The
coach's video is the coach's data. It goes through the same authorized
provider path the speaker's practice audio uses (one boundary, PLF1), with
the coach's own principal. When the boundary is enforced and the coach has
no current authorization, the upload still succeeds and the version row
says ``coach_authorization_missing``; nothing waits on a transcript and the
exercise serves on its video and instruction as it does today.

Nothing learns from any of this yet: no learning surface is registered for
scripts, and the three texts are kept for a decision that has not been made.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: What makes a version: a change to any of these bumps the live row.
DEFINITION_FIELDS = (
    "title", "instruction", "introduction_copy", "confident_introduction_copy",
    "acoustic_problem_tags", "supported_confidence_patterns",
    "matching_criteria", "explanation_video_url",
)

SOURCES = ("cms", "coach_panel", "coach_request", "coach_review")

TRANSCRIPT_DONE = "done"
TRANSCRIPT_PENDING = "pending"
TRANSCRIPT_FAILED = "failed"
TRANSCRIPT_NO_AUTHORIZATION = "coach_authorization_missing"
TRANSCRIPT_NOT_REQUESTED = "not_requested"


def _norm(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return sorted(str(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in sorted(value.items())}
    if value is None:
        return ""
    return str(value)


def definition_changed(before: Any, after: dict) -> bool:
    """Whether ``after`` says something different about the exercise."""
    if not isinstance(before, dict):
        return True
    return any(_norm(before.get(field)) != _norm(after.get(field))
               for field in DEFINITION_FIELDS if field in after)


def next_version(before: Any, after: dict) -> int:
    """The version the live row carries after this save (never lower)."""
    if not isinstance(before, dict):
        requested = after.get("version")
        return requested if isinstance(requested, int) and requested >= 1 else 1
    current = int(before.get("version") or 1)
    return current + 1 if definition_changed(before, after) else current


def video_sha256(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def record_version(
    database: Any, row: dict, *, source: str, created_by: str = "",
    ai_draft_text: Optional[str] = None,
    ai_draft_model_version: Optional[str] = None,
    video_sha256_hex: Optional[str] = None, video_bytes: Optional[int] = None,
    transcript_status: str = TRANSCRIPT_NOT_REQUESTED,
) -> Optional[dict]:
    """Write the version row for a saved live row, insert-once (0399).

    Best effort and never in the save's way: a version that cannot be
    written is logged, the live row stands, and the next save tries again.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown exercise version source: {source!r}")
    writer = getattr(database, "record_exercise_version", None)
    if writer is None or not isinstance(row, dict):
        return None
    payload = {
        "exercise_id": str(row.get("exercise_id") or ""),
        "version": int(row.get("version") or 1),
        **{field: row.get(field) for field in DEFINITION_FIELDS},
        "ai_draft_text": ai_draft_text or None,
        "ai_draft_model_version": ai_draft_model_version or None,
        "video_sha256": video_sha256_hex or None,
        "video_bytes": video_bytes,
        "transcript_status": transcript_status,
        "source": source,
        "created_by": str(created_by or ""),
    }
    try:
        stored = writer(payload)
    except Exception as e:  # noqa: BLE001 — the live row stands
        _log.warning("exercise version not recorded id=%s v=%s: %s",
                     payload["exercise_id"], payload["version"], e)
        return None
    return stored if isinstance(stored, dict) else None


def transcribe_exercise_video(
    database: Any, *, coach_user_id: str, video_bytes: bytes, filename: str,
) -> tuple[str, Optional[dict], Optional[str]]:
    """The coach's video, transcribed through the authorized provider path.

    Returns ``(status, transcript, language)`` with status one of done,
    failed, coach_authorization_missing. The transcript is the snippet
    transcription contract as returned (text, words, duration), so it can
    later be read the way a practice attempt's is.
    """
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates,
    )
    from services.processing_authorization import (
        ProcessingAuthorizationError, ProcessingAuthorizationService,
    )
    authorization = ProcessingAuthorizationService(database)
    principal = database.get_owner_principal_for_user(str(coach_user_id)) \
        if hasattr(database, "get_owner_principal_for_user") else None
    principal_id = str((principal or {}).get("id") or "")
    if authorization.enforced and not principal_id:
        return TRANSCRIPT_NO_AUTHORIZATION, None, None
    adapter = AuthorizedProviderAdapter(
        database, ProviderCoordinates(principal_id, None, None),
        authorization=authorization,
    )
    try:
        result = adapter.transcribe_snippet(video_bytes, filename)
    except ProcessingAuthorizationError:
        return TRANSCRIPT_NO_AUTHORIZATION, None, None
    except Exception as e:  # noqa: BLE001 — named, never raised into the upload
        _log.warning("exercise video transcription failed: %s", e)
        return TRANSCRIPT_FAILED, None, None
    if not isinstance(result, dict) or not str(result.get("transcript") or "").strip():
        return TRANSCRIPT_FAILED, None, None
    language = result.get("language")
    return TRANSCRIPT_DONE, result, str(language) if language else None


def settle_transcript(
    database: Any, *, exercise_id: str, version: int, status: str,
    transcript: Optional[dict], language: Optional[str],
) -> Optional[dict]:
    """Record the transcript's one arrival on a pending version row."""
    setter = getattr(database, "set_exercise_version_transcript", None)
    if setter is None:
        return None
    try:
        stored = setter(exercise_id=str(exercise_id), version=int(version),
                        status=status, transcript=transcript,
                        language=language)
    except Exception as e:  # noqa: BLE001 — the upload stands
        _log.warning("exercise transcript not recorded id=%s v=%s: %s",
                     exercise_id, version, e)
        return None
    return stored if isinstance(stored, dict) else None
