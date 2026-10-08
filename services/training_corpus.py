"""The training-corpus copy job (SPEC-training-corpus-and-project-purge §4, P3).

After a Take is processed, and only while its owner holds an active training
yes (`get_mlc2_training_consent_status_v2`, migration 0373), copy two kinds
of thing into `training_corpus_items` (0375) — separate copies, never pointers:

* the TRANSCRIPT SPAN of each Confident Voice item the speaker was shown, the
  words of that moment;
* a professional COACH LABEL on it, if one exists when the job runs: the
  coach's blind judgement as the confidence chain recorded it (``ml_judgments``,
  0430), never the mixed-purpose ``confidence_labels`` (DA-PROHIBIT).

TEXT AND MEASUREMENTS ONLY, NEVER AUDIO (3.5 pack, file 22 decision D1, signed
by the founder 2026-10-08; Privacy 3.5 §4a: "no recording of your voice, and no
clip of one, is ever copied or sent for training"). The audio branch this job
once had (``_copy_audio``: cut each shown moment's clip and store it under
`training-corpus/`) is removed, not switched off: nothing here reads a Take's
audio object, downloads bytes or writes to storage. Copying audio would need its
own consent, retention row and consent-screen design, none of which exists.
The erasure below still deletes any stored object a row names, so a row
written before D1 (there are none: the switch never opened) is still erased.

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
    # A deletion or termination stops every copy (0422, PLF-T2); the
    # database refuses one too, this only spares the upload.
    from services.account_deletion import learning_stopped

    if learning_stopped(database, principal):
        return {"status": "learning_stopped"}
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
    if _copy_coach_label(database, base, snippet_id):
        copied += 1
    return copied


#: The chain's blind coach decisions this copy keeps, as the value it
#: stores: the professional Yes and No the copy always kept (0430).
_COACH_DECISIONS = {"rating_yes": "yes", "rating_no": "no"}


def _copy_coach_label(database: Any, base: dict, snippet_id: str) -> bool:
    """The coach's blind judgement on this moment, from the confidence
    chain's own record (``ml_judgments`` through
    ``get_mlc2_blind_coach_ratings_v1``, 0430; DA-PROHIBIT). Never from
    ``confidence_labels``: that table is product state shared with owner,
    peer and machine answers, and canonical training code must not read it.
    So a label is copied only for a moment the walk judged blind on a Take
    the chain admitted (the training yes is the same authority for both)."""
    reader = getattr(database, "get_mlc2_blind_coach_ratings", None)
    if reader is None:
        return False
    decision = (reader(base["source_take_id"], [snippet_id]) or {}).get(
        str(snippet_id))
    value = _COACH_DECISIONS.get(str(decision or ""))
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


# ── Erasure (SPEC §6.3, P4) ────────────────────────────────────────────────

PURGE_TASK_PATH = "services.training_corpus.purge_due_copies"


def enqueue_corpus_purge(acquisition_principal_id: Any) -> bool:
    """Ask for the erasure of a person's due copies. Never raises.

    Not behind the copy switch: erasure must run whenever copies are due,
    including after the copying itself has been switched off again.
    """
    if not acquisition_principal_id:
        return False
    try:
        from services.job_queue import enqueue

        return bool(enqueue(
            PURGE_TASK_PATH, str(acquisition_principal_id),
            rq_job_id=f"training-corpus-purge:{acquisition_principal_id}"))
    except Exception as error:  # noqa: BLE001
        logger.warning("training corpus purge not enqueued principal=%s: %s",
                       acquisition_principal_id, error)
        return False


def purge_due_copies(acquisition_principal_id: str, *,
                     database: Any = None) -> dict:
    """Erase every copy of this person that a withdrawal marked due.

    For audio: delete the object at its exact coordinates after re-checking
    its hash, and require it verified absent; only then erase the row. A copy
    whose object cannot be proven gone stays due, and the next run tries
    again. Rows the account purge already marked `purged` (object gone) are
    erased directly.
    """
    if database is None:
        from services.db import db as database
    due = database.list_due_training_corpus_items(str(acquisition_principal_id))
    erased = failed = 0
    for item in due or []:
        if item.get("storage_key") and item.get("state") != "purged" \
                and not _object_gone(item):
            failed += 1
            continue
        if database.erase_training_corpus_item(str(item["id"])):
            erased += 1
        else:
            failed += 1
    return {"erased": erased, "failed": failed}


def _object_gone(item: dict) -> bool:
    try:
        from services.lab_audio_storage import delete_verified_lab_audio_object

        return bool(delete_verified_lab_audio_object(
            str(item["storage_key"]), bucket=str(item.get("bucket") or ""),
            storage_provider=str(item.get("storage_provider") or ""),
            expected_sha256=str(item.get("object_sha256") or "")))
    except Exception as error:  # noqa: BLE001 — never proof of absence
        logger.warning("training corpus object not erased item=%s: %s",
                       item.get("id"), error)
        return False


def sweep_due_training_copies(*, database: Any = None, limit: int = 20) -> dict:
    """Finish every erasure a lost queue message left undone.

    Turning training off queues `purge_due_copies` once. If that message is
    lost, or storage refuses a delete, the copies stay `purge_pending` and
    "your training copies will be deleted" stops being true. The worker's
    sweep calls this, so an erasure never depends on one message. Not behind
    the copy switch: erasure runs whenever copies are due.
    """
    if database is None:
        from services.db import db as database
    people = erased = failed = 0
    for principal in database.list_principals_with_due_training_copies(limit):
        result = purge_due_copies(principal, database=database)
        people += 1
        erased += int(result.get("erased") or 0)
        failed += int(result.get("failed") or 0)
    return {"people": people, "erased": erased, "failed": failed}


def _snippet_of(source_ref: str) -> str:
    parts = str(source_ref or "").split(":")
    return parts[1] if len(parts) >= 3 and parts[0] == "snippet" else ""


def sweep_late_coach_labels(*, database: Any = None, limit: int = 100) -> dict:
    """Copy a coach's label that arrived after the moment was copied.

    The copy job copies a coach label only if one exists when it runs, and a
    coach usually rates days later. This finds copied moments (their words)
    with no copied label yet and copies the coach's label if there is one
    now. The database re-checks the same training yes the moment was copied
    under, so nothing is copied after a withdrawal. DARK with the copy job.
    """
    if not copy_enabled():
        return {"status": "disabled"}
    if database is None:
        from services.db import db as database
    rows = database.list_training_moments(limit)
    labelled = {(row["training_grant_event_id"], _snippet_of(row["source_ref"]))
                for row in rows if row.get("item_kind") == "coach_label"}
    copied = 0
    for row in rows:
        snippet_id = _snippet_of(row.get("source_ref") or "")
        if (row.get("item_kind") != "transcript_span" or not snippet_id
                or (row["training_grant_event_id"], snippet_id) in labelled):
            continue
        base = {key: str(row[key]) for key in (
            "acquisition_principal_id", "training_grant_event_id",
            "source_project_id", "source_take_id")}
        if _copy_coach_label(database, base, snippet_id):
            copied += 1
    return {"status": "swept", "labels": copied}
