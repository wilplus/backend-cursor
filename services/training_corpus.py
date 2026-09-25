"""The training-corpus copy job (SPEC-training-corpus-and-project-purge §4, P3).

After a Take is processed, and only while its owner holds an active training
yes (`get_mlc2_training_consent_status_v2`, migration 0373), copy three kinds
of thing into `training_corpus_items` (0375) — separate copies, never pointers:

* the AUDIO SEGMENT of each Confident Voice item the speaker was shown, cut
  from the Take's own recording and stored under `training-corpus/`;
* its TRANSCRIPT SPAN, the words of that segment;
* a professional COACH LABEL on it, if one exists when the job runs.

Which items were shown is read from the frozen feedback set, which the bake or
the first open writes a little after processing ends. If it is not there yet,
the job waits and asks again, a bounded number of times.

DARK. `Config.MLC2_TRAINING_CORPUS_COPY_ENABLED` is a code constant, False
until P5; both the enqueue and the job return at once while it is. Behind it
the database refuses every copy anyway: nobody can hold a training yes, and the
`training_corpus` retention rule does not exist.

Provenance (L3): each item carries one kind. The coach label is copied as the
coach's judgment and nothing else; owner answers, peer ratings and machine
reads are never copied as labels. Nothing here trains anything.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

COPY_TASK_PATH = "services.training_corpus.run_corpus_copy"
#: The frozen set usually lands within a minute of processing. Six waits of
#: five minutes cover a slow bake and a first open the next morning does not.
MAX_WAITS = 6
WAIT_SECONDS = 300


def copy_enabled() -> bool:
    from config import Config

    return Config.MLC2_TRAINING_CORPUS_COPY_ENABLED is True


def enqueue_corpus_copy(take_session_id: Any, arc_id: Any, user_id: Any,
                        attempt: int = 0) -> bool:
    """Ask for one copy run, off the critical path. Never raises.

    Called unbranched at the end of the analysis run, so every condition
    lives here. While the switch is off this is a constant False.
    """
    if not copy_enabled() or not take_session_id or not arc_id:
        return False
    try:
        from services.job_queue import enqueue

        return bool(enqueue(
            COPY_TASK_PATH, str(take_session_id), str(arc_id),
            str(user_id or ""), int(attempt),
            delay_seconds=WAIT_SECONDS if attempt else 0,
            rq_job_id=f"training-corpus-copy:{take_session_id}:{attempt}",
        ))
    except Exception as error:  # noqa: BLE001 — never touch the live loop
        logger.warning("training corpus copy not enqueued take=%s: %s",
                       take_session_id, error)
        return False


def _principal(database: Any, take_session_id: str, arc_id: str) -> str:
    session = database.v2_get_session_by_id(str(take_session_id)) or {}
    owner = str(session.get("owner_principal_id") or "")
    if owner:
        return owner
    # Most Takes carry no owner_principal_id; the project always does.
    return str(database.get_project_owner_principal(str(arc_id)) or "")


def _shown_confident_voice(frozen: dict) -> list[str]:
    out = []
    for key in frozen.get("selected_keys") or []:
        if (isinstance(key, dict)
                and key.get("feedback_family") == "confident_voice"
                and key.get("snippet_id")
                and str(key["snippet_id"]) not in out):
            out.append(str(key["snippet_id"]))
    return out


def run_corpus_copy(take_session_id: str, arc_id: str, user_id: str = "",
                    attempt: int = 0, *, database: Any = None) -> dict:
    """The RQ entrypoint. Returns what it did, for the log and the tests."""
    if not copy_enabled():
        return {"status": "disabled"}
    if database is None:
        from services.db import db as database
    principal = _principal(database, take_session_id, arc_id)
    consent = (database.get_mlc2_training_consent_status(principal)
               if principal else None) or {}
    if consent.get("active") is not True:
        return {"status": "no_training_yes"}
    from services.take_feedback_set import load_feedback_set

    frozen = load_feedback_set(database, arc_id, take_session_id)
    if frozen is None:
        if attempt + 1 < MAX_WAITS:
            enqueue_corpus_copy(take_session_id, arc_id, user_id, attempt + 1)
            return {"status": "waiting_for_frozen_set"}
        return {"status": "no_frozen_set"}
    copied = 0
    for snippet_id in _shown_confident_voice(frozen):
        copied += _copy_moment(database, principal, str(consent["grant_event_id"]),
                               arc_id, take_session_id, snippet_id)
    return {"status": "copied", "items": copied}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _copy_moment(database: Any, principal: str, grant_event_id: str,
                 arc_id: str, take_session_id: str, snippet_id: str) -> int:
    snippet = database.get_snippet_by_id(snippet_id) or {}
    if str(snippet.get("session_id") or "") != str(take_session_id):
        return 0
    base = {
        "acquisition_principal_id": principal,
        "training_grant_event_id": grant_event_id,
        "source_project_id": str(arc_id),
        "source_take_id": str(take_session_id),
    }
    copied = 0
    text = (snippet.get("transcript") or "").strip()
    if text and _record(database, {
            **base, "source_ref": f"snippet:{snippet_id}:transcript",
            "source_sha256": _sha(text.encode("utf-8")),
            "item_kind": "transcript_span", "content": {"text": text}}):
        copied += 1
    if _copy_audio(database, base, snippet, snippet_id):
        copied += 1
    if _copy_coach_label(database, base, snippet_id):
        copied += 1
    return copied


def _copy_audio(database: Any, base: dict, snippet: dict,
                snippet_id: str) -> bool:
    source = database.get_take_audio_object(base["source_take_id"])
    if not isinstance(source, dict):
        return False
    try:
        from services.blind_review_media import render_blind_clip_wav
        from services.lab_audio_storage import (
            get_exact_storage_object_bytes, put_lab_audio_bytes,
            storage_provider,
        )

        whole = get_exact_storage_object_bytes(
            str(source["object_key"]), bucket=str(source["bucket"]),
            storage_provider=str(source.get("storage_provider") or "r2"))
        if _sha(whole) != str(source.get("exact_bytes_sha256") or ""):
            logger.warning("training corpus: source bytes changed snip=%s",
                           snippet_id)
            return False
        clip = render_blind_clip_wav(
            whole, start_offset_ms=int(snippet.get("start_offset_ms") or 0),
            duration_ms=int(snippet.get("duration_ms") or 0))
        key = (f"training-corpus/{base['acquisition_principal_id']}/"
               f"{base['training_grant_event_id']}/{snippet_id}.wav")
        bucket = put_lab_audio_bytes(key, clip, "audio/wav")
        provider = storage_provider()
    except Exception as error:  # noqa: BLE001 — a missed copy is not a fault
        logger.warning("training corpus audio copy failed snip=%s: %s",
                       snippet_id, error)
        return False
    if _record(database, {
            **base, "source_ref": f"snippet:{snippet_id}:audio",
            "source_sha256": _sha(clip), "item_kind": "audio_segment",
            "storage_provider": provider, "bucket": bucket,
            "storage_key": key, "object_sha256": _sha(clip)}):
        return True
    # Refused (a withdrawal won the race): the bytes must not stay behind.
    _discard(key, bucket, provider, _sha(clip))
    return False


def _copy_coach_label(database: Any, base: dict, snippet_id: str) -> bool:
    from services.professional_confidence import professional_verdicts

    value = professional_verdicts(database, [snippet_id]).get(snippet_id)
    if value is None:
        return False
    return _record(database, {
        **base, "source_ref": f"snippet:{snippet_id}:coach_label:{value}",
        "source_sha256": _sha(f"{snippet_id}:{value}".encode()),
        "item_kind": "coach_label", "label_provenance": "coach",
        "content": {"value": value, "rater_role": "coach"}}) is not None


def _record(database: Any, item: dict) -> Optional[dict]:
    try:
        return database.record_training_corpus_item(item)
    except Exception as error:  # noqa: BLE001 — refusals are expected
        logger.info("training corpus item refused %s: %s",
                    item.get("source_ref"), error)
        return None


def _discard(key: str, bucket: str, provider: str, sha256: str) -> None:
    try:
        from services.lab_audio_storage import delete_verified_lab_audio_object

        delete_verified_lab_audio_object(
            key, bucket=bucket, storage_provider=provider,
            expected_sha256=sha256)
    except Exception as error:  # noqa: BLE001
        logger.warning("training corpus orphan left key=%s: %s", key, error)
