"""Helper words belong to the Slide (contract 13-14, founder 2026-09-25).

A Take may split a Slide into a different number of Paragraphs than the Take
before it, so helper words cannot live on a Paragraph and survive that. They
live on the Slide, in the order they were picked (Q12 A).

WHEN PICKS ADD UP AND WHEN THEY REPLACE (Q14 A). Picks made while reviewing
the same Take add up on a Slide. The first pick on that Slide that is LOCKED
in a later Take replaces everything the Slide had from earlier Takes. The
replacement waits for the lock rather than the tap, because a pick the
speaker never locks must not wipe the helper words they did lock.

Tapping new words on the same Paragraph in the same Take replaces that
Paragraph's pick; it does not add a second one.

The pure functions here take and return plain row dicts, so the rule is
testable without a database. The two `record_*` functions are the only I/O,
and they are best-effort: the Paragraph-level write (`ideal_text_part`) has
already succeeded when they run, and a failure here must never turn that
success into an error for the speaker.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

Row = dict[str, Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _renumber(rows: list[Row]) -> list[Row]:
    ordered = sorted(rows, key=lambda r: int(r.get("ord") or 0))
    return [dict(r, ord=i) for i, r in enumerate(ordered)]


def pick(rows: list[Row], *, take_id: str, part_id: str,
         phrase: Optional[str], now: Optional[str] = None) -> list[Row]:
    """One Slide's rows after the speaker taps (or clears) words on a Paragraph.

    Rows from earlier Takes are kept here; `lock` is what retires them."""
    part = str(part_id).lower()
    kept = [dict(r) for r in rows
            if not (str(r.get("take_session_id") or "") == take_id
                    and str(r.get("source_part_id") or "").lower() == part)]
    if phrase:
        replaced = next(
            (r for r in rows
             if str(r.get("take_session_id") or "") == take_id
             and str(r.get("source_part_id") or "").lower() == part), None)
        kept.append({
            # A re-pick keeps its place in the order; a new pick goes last.
            "ord": (int(replaced.get("ord") or 0) if replaced
                    else max((int(r.get("ord") or 0) for r in rows),
                             default=-1) + 1),
            "phrase": phrase,
            "take_session_id": take_id,
            "source_part_id": part,
            # A re-pick on a Paragraph already locked this Take stays locked:
            # the sheet re-saves the words after a lock when the speaker
            # edited the text on the lock screen.
            "locked_at": replaced.get("locked_at") if replaced else None,
            "selected_at": now or _now(),
        })
    return _renumber(kept)


def lock(rows: list[Row], *, take_id: str, part_id: str, locked: bool,
         now: Optional[str] = None) -> list[Row]:
    """One Slide's rows after the speaker locks (or unlocks) a Paragraph."""
    part = str(part_id).lower()

    def _mine(r: Row) -> bool:
        return (str(r.get("take_session_id") or "") == take_id
                and str(r.get("source_part_id") or "").lower() == part)

    if not locked:
        # Unlock clears this Paragraph's helper words, as it clears the
        # Paragraph-level phrase. (Unlock itself goes away in PR 7.)
        return _renumber([dict(r) for r in rows
                          if str(r.get("source_part_id") or "").lower()
                          != part])
    if not any(_mine(r) for r in rows):
        # Locking with no new pick in this Take keeps what the Slide had.
        return [dict(r) for r in rows]
    stamp = now or _now()
    out = [dict(r, locked_at=r.get("locked_at") or stamp) if _mine(r)
           else dict(r)
           for r in rows
           if str(r.get("take_session_id") or "") == take_id]
    return _renumber(out)


def project(rows: Any) -> list[Row]:
    """Locked helper words as recording roots, Slide by Slide, in pick order."""
    out: list[Row] = []
    valid = [r for r in (rows or [])
             if isinstance(r, Mapping) and r.get("locked_at")
             and isinstance(r.get("phrase"), str) and r.get("phrase")
             and isinstance(r.get("slide_index"), int)
             and not isinstance(r.get("slide_index"), bool)
             and r["slide_index"] >= 0]
    for r in sorted(valid, key=lambda r: (r["slide_index"],
                                          int(r.get("ord") or 0))):
        out.append({
            "part_id": str(r.get("source_part_id") or ""),
            "slide_index": r["slide_index"],
            "text": r["phrase"],
            "type": "flagship",
        })
    return out


def merge_recording_roots(legacy: list[Row], slide_roots: list[Row]) -> list[Row]:
    """Slide-level helper words win for every Slide that has any.

    Slides without a slide-level row yet (helper words locked before this
    table existed) keep the Paragraph-level projection, so nothing already
    locked disappears on deploy."""
    covered = {r["slide_index"] for r in slide_roots}
    kept = [r for r in legacy if r.get("slide_index") not in covered]
    return sorted(kept + slide_roots,
                  key=lambda r: int(r.get("slide_index") or 0))


def slide_of_part(snapshot: Any, part_id: str) -> Optional[int]:
    """The Slide a Paragraph belongs to, from the immutable document core.

    The core pairs its `parts` with its `pieces` one to one; only that pairing
    proves the Slide. Anything missing or mismatched is None — never guessed
    from text."""
    payload = snapshot.get("payload") if isinstance(snapshot, Mapping) else None
    if not isinstance(payload, Mapping):
        return None
    parts, pieces = payload.get("parts"), payload.get("pieces")
    if (not isinstance(parts, list) or not isinstance(pieces, list)
            or len(parts) != len(pieces)):
        return None
    want = str(part_id).lower()
    for part, piece in zip(parts, pieces):
        if (isinstance(part, Mapping)
                and str(part.get("id") or "").lower() == want
                and isinstance(piece, Mapping)):
            slide = piece.get("slide_index")
            if isinstance(slide, int) and not isinstance(slide, bool) \
                    and slide >= 0:
                return slide
            return None
    return None


def _apply(database: Any, arc_id: str, user_id: str, part_id: str,
           change) -> None:
    snapshot = database.get_ideal_text_document_core(arc_id, user_id)
    slide = slide_of_part(snapshot, part_id)
    if slide is None:
        return
    rows = [r for r in (database.get_slide_helper_words(arc_id, user_id) or [])
            if r.get("slide_index") == slide]
    after = change(rows)
    if after != rows:
        database.replace_slide_helper_words(arc_id, user_id, slide, after)


def record_pick(database: Any, arc_id: str, user_id: str, part_id: str,
                take_id: str, phrase: Optional[str]) -> None:
    """Best-effort: mirror a Paragraph pick onto its Slide."""
    try:
        _apply(database, arc_id, user_id, part_id,
               lambda rows: pick(rows, take_id=take_id, part_id=part_id,
                                 phrase=phrase))
    except Exception as error:
        logger.warning("slide helper words pick failed arc=%s part=%s: %s",
                       arc_id, part_id, error)


def record_lock(database: Any, arc_id: str, user_id: str, part_id: str,
                take_id: str, locked: bool) -> None:
    """Best-effort: mirror a Paragraph lock onto its Slide."""
    try:
        _apply(database, arc_id, user_id, part_id,
               lambda rows: lock(rows, take_id=take_id, part_id=part_id,
                                 locked=locked))
    except Exception as error:
        logger.warning("slide helper words lock failed arc=%s part=%s: %s",
                       arc_id, part_id, error)


def slide_roots(database: Any, arc_id: str, user_id: str) -> list[Row]:
    """Best-effort read for the recording screen; [] on any failure."""
    try:
        return project(database.get_slide_helper_words(arc_id, user_id))
    except Exception as error:
        logger.warning("slide helper words read failed arc=%s: %s",
                       arc_id, error)
        return []
