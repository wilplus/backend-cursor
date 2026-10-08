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
recording of their voice. The uploaded object is deleted here, before the
caller answers (Phase 4): the orphan sweep never sees this path's objects.
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

    IT READS THE PROJECT, NOT JUST THE TAKE (2026-09-16). This asked
    v2_sessions.owner_principal_id and stopped there, and on production that
    column is NULL for 348 of 367 user takes — so practice would have refused
    to save a retake for 95% of speakers, the refusal working exactly as
    designed on an answer that was never authoritative.

    projects.owner_principal_id is NOT NULL; the take's column is a
    denormalised copy that most rows never got. The recording path has always
    resolved from the project (routes/v2/lab_recording.py hands
    upload.project.principal.id to the same service), so reading the project
    here is not a fallback bolted on — it is reading the same source the rest
    of the pipeline already trusts. The take's own column is kept as the first
    look because when it IS set it is the cheapest correct answer.
    """
    from services.processing_authorization import ProcessingAuthorizationService

    row: dict = practice if isinstance(practice, dict) else {}
    take_id = str(row.get("take_session_id") or "")
    if not take_id:
        return ""
    session = database.v2_get_session_by_id(take_id) or {}
    owner = str(session.get("owner_principal_id") or "")
    if not owner:
        owner = database.get_project_owner_principal(
            str(session.get("project_id") or ""))
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

    A REFUSED SAVE LEAVES NO RECORDING (F1 Repair Plan Phase 4). The route
    uploads before it calls this, so every way this can fail -- no principal,
    a refused insert, a refused registration, an exception -- deletes the
    object it was handed before answering. Nothing else would: the orphan
    sweep only reads `processing_orphan_objects`, which this path never
    wrote, and the purge only reads registered objects.
    """
    try:
        inserted = _record(database, row, practice=practice, bucket=bucket,
                           audio_bytes=audio_bytes)
    except Exception:
        _discard_object(row, bucket, audio_bytes)
        raise
    if inserted is None:
        _discard_object(row, bucket, audio_bytes)
    return inserted


def _discard_object(row: dict, bucket: Optional[str],
                    audio_bytes: bytes) -> None:
    """Delete the uploaded recording of an attempt that was not saved.
    Verified by its bytes, best effort: a failure is logged loudly."""
    key = str((row or {}).get("storage_path") or "")
    if not key or not bucket or not audio_bytes:
        return
    try:
        from services.lab_audio_storage import delete_verified_lab_audio_object
        deleted = delete_verified_lab_audio_object(
            key, bucket=str(bucket), storage_provider=_provider_for(bucket),
            expected_sha256=hashlib.sha256(audio_bytes).hexdigest())
    except Exception as error:
        logger.error("unsaved practice recording not deleted key=%s: %s",
                     key, error, exc_info=True)
        return
    if not deleted:
        logger.error("unsaved practice recording not deleted key=%s", key)


def _record(
    database: Any,
    row: dict,
    *,
    practice: Any,
    bucket: Optional[str],
    audio_bytes: bytes,
) -> Optional[dict]:
    """The insert and the registration; `record_practice_attempt` owns the
    cleanup of the uploaded object when this returns None or raises.

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
    _shadow_verdicts(database, inserted, practice)
    # V4 B1.4: the try's fast read, timed from the request's arrival. Dark:
    # it changes nothing the speaker gets, and a failure only logs (O5).
    from services.v4_practice_read import record_for_attempt
    record_for_attempt(database, inserted)
    return inserted


def _shadow_verdicts(database: Any, attempt: dict, practice: Any) -> None:
    """6b (0411): every detector version's verdict on the attempt's saved
    snapshot, into the shadow log. Best-effort; the attempt stands."""
    try:
        from services.detector_candidates import register_candidates
        from services.detector_rollout import record_attempt
        register_candidates()
        take = str((practice or {}).get("take_session_id") or "") if isinstance(practice, dict) else ""
        if take:
            record_attempt(database, attempt, take_session_id=take)
    except Exception as e:  # noqa: BLE001 — a shadow row is never worth the attempt
        logger.info("practice attempt shadow verdicts skipped: %s", e)


def _undo(database: Any, attempt_id: str) -> None:
    """Best effort. A failure here is logged and nothing more: the caller is
    already returning an error, and `record_practice_attempt` deletes the
    stored object."""
    if not attempt_id or not hasattr(database, "delete_confident_voice_practice_attempt"):
        return
    try:
        database.delete_confident_voice_practice_attempt(attempt_id)
    except Exception as error:  # pragma: no cover - logged, never raised
        logger.error("could not roll back practice attempt %s: %s",
                     attempt_id, error)
