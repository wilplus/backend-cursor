"""A coach judges an imported corpus clip end to end (founder 2026-10-06,
panel answer CO1 A, decisions log N56.4: "Tests cover the whole path:
import, spotting, queue, label, split").

THE GAP THIS CLOSES. With ``Config.TRAINING_IMPORT_ENABLED`` on, an import
was analysed, spotted, queued and split, and still could not be judged:

  * ``GET /v2/coach/sessions/<id>/confidence-queue`` presents a row only
    through the canonical blind presentation (an ``evidence_spans`` row, a
    canonical coach assignment and a learning exposure), and that path
    needs the Take's ``owner_principal_id`` and ``project_id``. An import is
    created ownerless (``v2_create_internal_session``) and never gets an
    evidence span, so its queue was always empty.
  * the corpus page played a row from ``/v2/coach/mlc3/source-playback/``,
    retired with MLC-3 (founder 2026-09-30, L8); nothing played.

WHAT AN IMPORT IS SERVED FROM. What it has: its snippets and the cohort
frozen on its ``intake_context`` (``label_queue_selection``, built from the
V3 spotting by ``confidence_labels.corpus_label_queue``). Its rows are
presented by the same allowlist the canonical rows use, minus the canonical
handles it has none of (no assignment, so no ``playback_reference_id``; no
exposure ledger, so ``learning_exposures`` is empty).

WHY NOT THE CANONICAL PATH. The label does not need it: the label PUT writes
``confidence_labels`` (lane ``coach``) and only shadows into the canonical
chain when an evidence span exists (``coach_judgement_record``,
best-effort). And reaching it would mean giving an import an owner
principal and a project, which is the wrong claim twice: the importing
coach is not the voice on the clip (L3), and an owner principal on an
import is exactly what would let the Phase-1 permit RPC authorise a third
party's audio under the coach's own acceptance (the B-2 class of
``authorization_binds_to_acquirer.sql``).

PLAYBACK. A coach-only read returns a short-lived signed URL for one QUEUED
clip of an import, with the clip's window on that audio, signed by the same
resolver the coach review packet plays every snippet through
(``services.audio_ref_resolver.resolve_playable_ref`` over the snippet's
``audio_segment_path``: the parent recording, offsets relative to it).

BLIND COACH and AC-9. Nothing here reads or returns the V3 pick, a block, a
selection reason, a policy version, a score or a transcript. The queue rows
and the playback body are allowlists.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: A signed corpus clip lives this long: enough to play one judgement, short
#: enough that a copied link dies before it travels.
PLAYBACK_TTL_SECONDS = 900

#: The pre-judgement keys an import's queue row carries, and nothing else.
_ROW_KEYS = ("snippet_id", "label", "re_review", "rating_locked",
             "rating_lock_reason")


def is_corpus_import(session: Any) -> bool:
    """True for a training import (``v2_sessions.source``)."""
    from services.training_import import IMPORT_SOURCE

    return isinstance(session, dict) and session.get("source") == IMPORT_SOURCE


def corpus_queue_open(session: Any) -> bool:
    """An import's queue is served from its own cohort only while the
    founder's switch is on; off, the queue route answers what it answered
    before (no canonical evidence, so nothing)."""
    from services.training_import import import_enabled

    return is_corpus_import(session) and import_enabled()


def corpus_presented_rows(rows: Any) -> list:
    """The import's queue rows, blind: an allowlist over the rows the queue
    route already built (cohort order, labels, routing locks), never a raw
    storage reference, clip coordinates, transcript or selection record."""
    out: list = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("snippet_id"):
            continue
        presented = {key: row.get(key) for key in _ROW_KEYS}
        presented["snippet_id"] = str(row["snippet_id"])
        presented["re_review"] = bool(row.get("re_review"))
        presented["rating_locked"] = bool(row.get("rating_locked"))
        presented["learning_exposures"] = []
        out.append(presented)
    return out


def _queued_ids(session: dict) -> set:
    from services.confidence_labels import stored_selection_records

    ctx = session.get("intake_context")
    return {record["snippet_id"]
            for record in stored_selection_records(ctx if isinstance(ctx, dict) else {})}


def queued_corpus_clip(database: Any, snippet_id: str
                       ) -> tuple[Optional[dict], Optional[dict]]:
    """``(snippet, session)`` for a clip in an import's frozen label queue,
    else ``(None, None)``: an unknown clip, a clip of an ordinary Take and a
    clip the cohort did not draw all read the same, so the route cannot be
    used to learn which clips exist or which the machine kept."""
    snippet = database.get_snippet_by_id(str(snippet_id))
    if not isinstance(snippet, dict) or not snippet.get("session_id"):
        return None, None
    session = database.v2_get_session_by_id(str(snippet["session_id"]))
    if not is_corpus_import(session):
        return None, None
    if str(snippet.get("id") or snippet_id) not in _queued_ids(session):
        return None, None
    return snippet, session


def playback_body(snippet: dict) -> Optional[dict]:
    """The signed URL and the clip's window on it, or None when nothing
    could be signed (a bare key or an ``s3://`` marker is not playable)."""
    from services.audio_ref_resolver import resolve_playable_ref

    ref = snippet.get("audio_segment_path") or snippet.get("storage_path")
    url = resolve_playable_ref(ref, expires_in=PLAYBACK_TTL_SECONDS)
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        logger.warning("corpus playback: clip %s has no signable audio",
                       snippet.get("id"))
        return None
    return {
        "snippet_id": str(snippet.get("id")),
        "url": url,
        "start_offset_ms": snippet.get("start_offset_ms"),
        "duration_ms": snippet.get("duration_ms"),
        "expires_in_s": PLAYBACK_TTL_SECONDS,
    }
