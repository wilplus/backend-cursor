"""A practice attempt and its stored recording land together, or not at all.

WHY THIS FUNCTION EXISTS RATHER THAN TWO CALLS AT THE ROUTE.

Until 2026-09-16 the practice route uploaded a speaker's recording to R2 and
then inserted the attempt row, and nothing anywhere recorded that the FILE
existed. services/data_purge.py deletes storage only for objects it can find
in processing_audio_objects, processing_orphan_objects and (now)
processing_practice_objects — so a speaker who asked to be deleted had their
practice rows removed and their recordings left in the bucket.

That gap was possible because "insert the attempt" and "register the object"
were two independent things a caller could do one of. Here they are one
function, so the only way to add an attempt is to register its audio with it.
A future second caller gets the invariant for free rather than having to know
about it.

WHAT HAPPENS WHEN REGISTRATION FAILS. The attempt is rolled back and the
caller is told. That is deliberately the harsh choice: an attempt whose audio
cannot be accounted for is exactly the state this module exists to prevent,
and a speaker losing one retake is a far smaller harm than an unreachable
recording of their voice. The uploaded object is left for
orphan_audio_cleanup, which is what that sweep is for.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Mirrors the CHECK on processing_practice_objects.storage_provider.
_PROVIDERS = ("r2", "supabase")


def _provider_for(bucket: Any) -> str:
    """R2 is the only object store the practice path writes to today.

    Kept as a function rather than a constant so that the day a second
    provider appears, the answer is wrong in ONE place instead of silently
    mislabelling every row.
    """
    return "r2"


def resolve_practice_principal(database: Any, practice: Any) -> str:
    """The acquisition principal that owns a practice, in either mode.

    One resolver, because the registry's FK and the provider permit must name
    the SAME principal — two resolutions that drift would register a recording
    against one identity and permit it against another, and the purge would
    then miss it for the owner who actually asked.
    """
    from services.processing_authorization import ProcessingAuthorizationService

    row: dict = practice if isinstance(practice, dict) else {}
    take_id = str(row.get("take_session_id") or "")
    if not take_id:
        return ""
    session = database.v2_get_session_by_id(take_id) or {}
    owner = str(session.get("owner_principal_id") or "")
    authorization = ProcessingAuthorizationService(database)
    if not authorization.enforced:
        return owner
    return authorization.resolve_acquisition_principal(
        owner, user_id=str(row.get("owner_user_id") or "") or None)


def record_practice_attempt(
    database: Any,
    row: dict,
    *,
    practice: Any,
    bucket: Optional[str],
    audio_bytes: bytes,
) -> Optional[dict]:
    """Insert one attempt and register its recording. Returns the attempt.

    Returns None when either half fails; the attempt is removed if the
    registration does not land, so no attempt exists whose audio the purge
    cannot see.

    The object key and content type are READ FROM `row`, never passed
    alongside it. They were both parameters until a caller could have handed
    `storage_path="a"` in the row and `object_key="b"` beside it — the purge
    would then have deleted b while the attempt pointed at a, which is the
    same unreachable-recording bug in a new shape. One source, so the two
    halves cannot describe different objects.
    """
    object_key = str(row.get("storage_path") or "")
    content_type = str(row.get("mime_type") or "") or "application/octet-stream"
    acquisition_principal_id = resolve_practice_principal(database, practice)
    if not acquisition_principal_id:
        # No principal means no FK, which means no registry row, which means a
        # recording the purge cannot reach. Refuse before anything is written.
        logger.error(
            "practice attempt refused: no acquisition principal for take %s",
            practice.get("take_session_id") if isinstance(practice, dict)
            else None)
        return None

    inserted = database.insert_confident_voice_practice_attempt(row)
    if not inserted:
        return None

    attempt_id = str(inserted.get("id") or "")
    provider = _provider_for(bucket)
    if not attempt_id or not object_key or not bucket \
            or provider not in _PROVIDERS or not audio_bytes:
        logger.error(
            "practice attempt %s cannot be registered (bucket=%s key=%s "
            "bytes=%s) — rolling it back rather than leaving audio the purge "
            "cannot reach", attempt_id, bucket, object_key, len(audio_bytes or b""))
        _undo(database, attempt_id)
        return None

    registered = database.insert_practice_audio_object({
        "acquisition_principal_id": acquisition_principal_id,
        "practice_attempt_id": attempt_id,
        "storage_provider": provider,
        "bucket": str(bucket),
        "object_key": str(object_key),
        "byte_size": len(audio_bytes),
        "content_type": content_type,
        "exact_bytes_sha256": hashlib.sha256(audio_bytes).hexdigest(),
    })
    if not registered:
        logger.error(
            "practice audio registration failed for attempt %s — rolling the "
            "attempt back", attempt_id)
        _undo(database, attempt_id)
        return None
    return inserted


def _undo(database: Any, attempt_id: str) -> None:
    """Best effort. A failure here is logged and nothing more: the caller is
    already returning an error, and the stored object is picked up by
    orphan_audio_cleanup, which exists for exactly this."""
    if not attempt_id or not hasattr(database, "delete_confident_voice_practice_attempt"):
        return
    try:
        database.delete_confident_voice_practice_attempt(attempt_id)
    except Exception as error:  # pragma: no cover - logged, never raised
        logger.error("could not roll back practice attempt %s: %s",
                     attempt_id, error)
