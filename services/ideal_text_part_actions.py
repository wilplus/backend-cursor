"""A speaker's action on one Paragraph of the Ideal Text: lock or unlock it
(PUT /explore/arc/<arc_id>/parts/<part_id>/lock) and pick or skip its
helper words (PUT .../root).

Moved out of ``routes.v2.explore_ideal_text`` unchanged (founder 2026-10-12).
The route keeps the ownership gate, the body's own checks, the read of the
document's parts against the words the speaker saw (`text_echo`), and the
cold-open publication after the save. Both actions only ever touch the
Paragraph the speaker acted on, and the helper words change only on the
speaker's own pick (L1).

Writes, in order — lock: the lock, its Slide mirror, the canonical decision;
root: the helper words, their Slide mirror, the canonical pick or skip.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.intervention_spend import latest_spoken_take_sid
from services.refusal import Refusal
from services.slide_helper_words import record_lock, record_pick

logger = logging.getLogger(__name__)


def seed_parts_for_lock(database, arc_id, user_id, echo, raw_parts) -> list:
    """Adopt the CLIENT's parts list so a lock can land on a document with no
    stored identity. Returns the seeded parts in `_locked_parts` shape, or [].

    SEED-ON-LOCK (SPEC-lockin-loop-and-coach-panel §2, the founder's DoD): the
    founder's loop locks a paragraph the student never EDITED, and an
    unedited document has stored no parts. The client MINTS ids, the server
    VALIDATES (real UUIDs, joins back to the echoed document byte for byte)
    and stores. Two refusals on top:

      * ANY stored part carrying a lock → no seed (compose_locked owns that
        reconciliation on the next GET).
      * `locked` flags inside the seed are IGNORED — every seeded part lands
        open; the lock this request asks for is the only one.
    """
    try:
        from services.ideal_text_parts import (
            InvalidParts, agrees_with_text, validate,
        )
        if not isinstance(raw_parts, list) or not raw_parts:
            return []
        existing = database.get_ideal_text_parts(arc_id, user_id, with_lock=True)
        if any(r.get("locked_at") for r in (existing or [])
               if isinstance(r, dict)):
            return []
        try:
            parts = validate(raw_parts)
        except InvalidParts:
            return []
        if not parts or not agrees_with_text(parts, echo):
            return []
        rows = [{"id": p["id"], "ord": p["ord"], "text": p["text"],
                 "locked_at": None} for p in parts]
        if not database.replace_ideal_text_parts(arc_id, user_id, rows):
            return []
        return [dict(r, locked=False) for r in rows]
    except Exception as e:
        logger.warning("seed parts for lock failed arc=%s: %s", arc_id, e)
        return []


def _lock_reason(body: dict, locked: bool) -> Any:
    reason = body.get("reason")
    if reason not in (None, "keep_evolving"):
        raise Refusal("INVALID_INPUT", "reason is not valid", 400)
    if reason == "keep_evolving" and locked:
        raise Refusal("INVALID_INPUT", "keep_evolving requires unlocked", 400)
    return reason


def _part_state(database, arc_id, user_id, part_id, take_id):
    """(the Take's session, the part's stored row, its latest revision)."""
    session = database.v2_get_session_by_id(take_id) or {} if take_id else {}
    rows = database.get_ideal_text_parts(arc_id, user_id, with_lock=True) or []
    row = next((r for r in rows
                if str(r.get("id") or "") == str(part_id).lower()), {})
    revision = database.get_latest_ideal_text_part_revision(
        arc_id=arc_id, user_id=user_id, part_id=str(part_id)) or {}
    return session, row, revision


def _record_lock_decision(database, *, arc_id, user_id, part_id, target,
                          locked, reason, sessions) -> None:
    """Canonical paragraph versioning is an immutable decision chain; the
    legacy part row remains the live read during parity. A missing exposure
    snapshot is observable and retriable, never a reason to undo the
    speaker's successful lock."""
    try:
        from services.feedback_data_contract import (
            canonical_paragraph_decision, content_hash,
        )
        take_id = latest_spoken_take_sid(sessions)
        session, row, revision = _part_state(
            database, arc_id, user_id, part_id, take_id)
        value = ("lock_for_next_take" if locked
                 else "keep_evolving" if reason == "keep_evolving"
                 else "reopen_for_edit")
        coordinate = content_hash({
            "part_id": str(part_id).lower(), "value": value,
            "legacy_revision_id": revision.get("id"),
            "legacy_revision_action": revision.get("action"),
            "iteration": row.get("iteration"), "locked_at": row.get("locked_at"),
            "text": target.get("text"),
        })
        decision = canonical_paragraph_decision(
            take_id=str(take_id or ""),
            project_id=str(session.get("project_id") or ""),
            rater_id=user_id, source_ideal_part_id=str(part_id).lower(),
            exact_text=str(target.get("text") or ""), value=value,
            revision_coordinate=coordinate)
        if decision is not None:
            database.record_canonical_paragraph_decision(decision)
    except Exception as error:
        logger.warning(
            "canonical paragraph decision dual-write failed "
            "arc=%s part=%s: %s", arc_id, part_id, error)


def lock_part(database, *, arc_id: str, user_id: str, part_id: str,
              parts: list, locked: bool, body: dict,
              sessions: list) -> Optional[dict]:
    """Lock or unlock ``part_id`` among the document's current ``parts``;
    the helper-words proposal for a lock (None otherwise). Raises
    ``Refusal`` (404 part not found, 400 reason, 500 not saved)."""
    target = next((p for p in parts if p["id"] == str(part_id).lower()), None)
    if target is None:
        raise Refusal("NOT_FOUND", "part not found", 404)
    reason = _lock_reason(body, locked)
    if not database.set_ideal_text_part_lock(
            arc_id, user_id, str(part_id), locked,
            revision_action=("keep_evolving" if reason == "keep_evolving" else None)):
        raise Refusal("V2_ERROR", "Could not save", 500)
    record_lock(database, arc_id, user_id, str(part_id),
                latest_spoken_take_sid(sessions), locked)
    _record_lock_decision(
        database, arc_id=arc_id, user_id=user_id, part_id=part_id,
        target=target, locked=locked, reason=reason, sessions=sessions)
    if not locked:
        return None
    from services.rooting_phrase import propose_rooting_phrase
    return propose_rooting_phrase(target.get("text"))


def _valid_root(target: dict, body: dict) -> Optional[dict]:
    """The exact span picked, or None for a skip. Raises a 400 ``Refusal``."""
    phrase = body.get("phrase")
    start, end = body.get("start"), body.get("end")
    if phrase is None:
        if start is not None or end is not None:
            raise Refusal("INVALID_INPUT", "skip must not include a span", 400)
        return None
    from services.rooting_phrase import validate_rooting_phrase
    valid = validate_rooting_phrase(target.get("text"), phrase, start, end)
    if valid is None:
        # "locked" dropped 2026-09-25, founder sign-off.
        raise Refusal("INVALID_ROOT_PHRASE",
                      "Choose exact words from this paragraph.", 400)
    return valid


def _record_root_decision(database, *, arc_id, user_id, part_id, valid,
                          take_id) -> None:
    """The canonical pick or skip, bound to this exact paragraph. Best-effort."""
    try:
        from services.feedback_data_contract import (
            canonical_root_phrase, canonical_root_phrase_skip, content_hash,
        )
        session, row, revision = _part_state(
            database, arc_id, user_id, part_id, take_id)
        picked = valid or {}
        coordinate = content_hash({
            "part_id": str(part_id).lower(),
            "legacy_revision_id": revision.get("id"),
            "legacy_revision_action": revision.get("action"),
            "root_selected_at": row.get("root_selected_at"),
            "phrase": picked.get("text"), "start": picked.get("start"),
            "end": picked.get("end"),
            "action": "select" if valid is not None else "skip",
        })
        common = {
            "take_id": str(take_id or ""),
            "project_id": str(session.get("project_id") or ""),
            "rater_id": user_id, "source_ideal_part_id": str(part_id).lower(),
            "revision_coordinate": coordinate,
        }
        if valid is not None:
            root = canonical_root_phrase(
                exact_text=valid["text"], start=valid["start"],
                end=valid["end"], **common)
            if root is not None:
                database.record_canonical_root_phrase(root)
        else:
            skip = canonical_root_phrase_skip(**common)
            if skip is not None:
                database.record_canonical_root_phrase_skip(skip)
    except Exception as error:
        logger.warning(
            "canonical root phrase dual-write failed "
            "arc=%s part=%s: %s", arc_id, part_id, error)


def root_part(database, *, arc_id: str, user_id: str, part_id: str,
              target: dict, body: dict, sessions: list) -> dict:
    """Save the helper words picked on ``target`` (or the skip); the
    response body. No lock precondition — why, in
    db.set_ideal_text_part_root. Raises ``Refusal``."""
    valid = _valid_root(target, body)
    picked = valid or {}
    if not database.set_ideal_text_part_root(
            arc_id=arc_id, user_id=user_id, part_id=str(part_id),
            phrase=picked.get("text"), start=picked.get("start"),
            end=picked.get("end")):
        raise Refusal("V2_ERROR", "Could not save the rooting phrase", 500)
    take_id = latest_spoken_take_sid(sessions)
    record_pick(database, arc_id, user_id, str(part_id), take_id,
                picked.get("text"))
    _record_root_decision(database, arc_id=arc_id, user_id=user_id,
                          part_id=part_id, valid=valid, take_id=take_id)
    return {
        "saved": True,
        "part_id": str(part_id),
        "root_phrase": picked.get("text"),
        "root_start": picked.get("start"),
        "root_end": picked.get("end"),
    }
