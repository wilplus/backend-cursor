"""The coach's confidence judgement on one clip (PUT
/v2/coach/snippets/<snippet_id>/confidence-label): the body's translation,
who may answer, the write of record, and the response released after it.

Moved out of ``routes.v2.coach`` unchanged (founder 2026-10-12). The route
keeps the order: look-ups, the rating's validation, the language gate, then
``admit_rater``, ``record_rating``, the canonical writes, and only then
``rating_response`` — the one read that releases the owner's answer and the
machine's proposal, after the blind judgement is durably written (BLIND
COACH; AC-9: nothing here is ever serialized toward a student).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.refusal import Refusal

logger = logging.getLogger(__name__)


def rating_body(body: dict) -> tuple[dict, Any]:
    """(five-state body, legacy intensity or None).

    LEGACY body ``{confident: bool, intensity?, note?}`` is validated on the
    OLD validator so its strictness is unchanged, then translated
    (true->yes, false->no) — the translation stays visible here in one
    place rather than buried in a validator that would then appear to accept
    two instruments."""
    if "confident" not in body:
        return body, None
    from services.confidence_labels import validate_confidence_label
    legacy: Any
    legacy, err = validate_confidence_label(body)
    if err:
        raise Refusal("INVALID_INPUT", err, 400)
    return {
        "state_id": "confidence",
        "value": "yes" if legacy["confident"] else "no",
        "note": legacy.get("note"),
    }, legacy.get("intensity")


_CLOSED = {
    "fresh_rater_required": "This clip is waiting for another eligible rater.",
    "audio_quarantined": "Independent raters reported that this audio cannot be judged.",
}


def admit_rater(database, sess: dict, snippet_id: str, rater_id: Any,
                is_rereview: bool) -> tuple[bool, bool]:
    """(self_report, reconsidering) for a rater allowed to answer.

    RULE 2 (founder 2026-08-11) — the owner is not a peer, and that is about
    WHOSE CLIP it is, not which surface rated it: ownership is compared
    explicitly rather than read off the lane; a corpus import is not its
    importer's voice (CO3 A, N58). THE ORIGINAL JUDGMENT STANDS (LOCKIN §5c;
    contract 34): a coach who already judged this clip reconsiders."""
    from services.label_quorum import rater_submission_access, rating_is_self_report
    self_report = rating_is_self_report(sess, rater_id)
    existing_by_snippet = database.get_confidence_labels_by_snippet_ids(
        [snippet_id]) or {}
    existing_labels = existing_by_snippet.get(str(snippet_id), [])
    access = rater_submission_access(existing_labels, rater_id)
    if not access["allowed"]:
        outcome = access["outcome"]
        if outcome in _CLOSED:
            raise Refusal(outcome.upper(), _CLOSED[outcome], 409)
        if not is_rereview:
            raise Refusal(
                "RATING_CLOSED",
                "This clip no longer needs another blind rating.", 409)
    return self_report, access["outcome"] == "update"


def _first_coach_rating(database, **rating: Any) -> None:
    """The coach's original judgment on a clip: confidence_labels (and its
    label_revision shadow)."""
    if database.upsert_state_rating(**rating):
        # V4 brief 1.7 (0442): the clip's soft-label counts follow the
        # judgment of record. A side write, never in the rating's way; the
        # function counts only the quorum's human lanes (Q3).
        from services.clip_answer_counts import refresh
        refresh(database, rating["snippet_id"])
        return
    raise Refusal(
        "SERVER_ERROR",
        "could not save the rating (run migrations/add_state_generic_ratings.sql)",
        500)


def _reconsider_coach_rating(database, **rating: Any) -> None:
    """LOCKIN §5c, contract 34 (W6 2026-10-05): "The original coach judgment
    is never editable; reconsideration is a separately timestamped,
    provenance-bearing revision." Appended to label_revision; the original
    row stays as it was. A revision that was not kept is never reported as
    saved."""
    snippet_id, rater_id = rating["snippet_id"], rating["rater_id"]
    try:
        kept = database.append_label_reconsideration(
            **{**rating, "rater_id": str(rater_id)})
    except Exception as e:  # noqa: BLE001 -- named below
        logger.warning("coach reconsideration not kept snip=%s: %s",
                       snippet_id, e, exc_info=True)
        kept = None
    if isinstance(kept, dict):
        # LISTEN AGAIN (0444): a new blind answer closes this coach's open
        # ask on the moment, if one was there. Best-effort; the revision is
        # kept either way.
        from services.coach_listen_again import mark_heard
        mark_heard(database, snippet_id=snippet_id, coach_id=rater_id)
        return
    raise Refusal("SERVER_ERROR", "could not save the rating", 500)


def record_rating(database, reconsidering: bool, *, snippet_id, row, rater_id,
                  session_id, lane, intensity, self_report, machine_value,
                  selection) -> None:
    """Write the judgment of record, or append the reconsideration.
    Raises ``Refusal`` when it was not kept."""
    write = _reconsider_coach_rating if reconsidering else _first_coach_rating
    write(database, snippet_id=snippet_id, row=row, rater_id=rater_id,
          session_id=session_id, lane=lane, intensity=intensity,
          self_report=self_report, machine_value=machine_value,
          selection=selection)


def _owner_self_report(database, snippet_id: str) -> Optional[dict]:
    reports = database.list_take_feedback_self_reports_by_snippet(str(snippet_id))
    report = next((
        r for r in reversed(reports)
        if isinstance(r, dict) and r.get("feedback_family") == "confident_voice"
    ), None)
    if not report:
        return None
    return {"value": report.get("response"),
            "created_at": report.get("created_at"),
            "provenance": "user_self_report"}


def rating_response(database, snip: dict, snippet_id: str, row: dict, lane: str,
                    legacy_intensity: Any, canonical_judgment: Any) -> dict:
    """BLINDNESS RELEASE. Called only after the independent judgment was
    durably written; queue/read payloads never call it, so the coach cannot
    see the owner label or machine proposal before committing."""
    from services.label_quorum import machine_proposal
    owner_report = _owner_self_report(database, snippet_id)
    value = row["value"]
    return {
        "saved": True, "snippet_id": snippet_id,
        "state_id": row["state_id"], "value": value,
        "unrateable": row["unrateable"], "lane": lane,
        # Legacy fields, derived — the current FE reads these.
        "confident": (True if value == "yes"
                      else False if value == "no" else None),
        "intensity": legacy_intensity,
        # Exact words are released only by this successful write. Blind
        # queue reads redact them until the same rater has a saved row.
        "transcript": (snip.get("transcript")
                       or snip.get("transcript_excerpt") or ""),
        "owner_self_report": owner_report,
        "machine_value": machine_proposal(snip),
        "mlc2": canonical_judgment,
    }
