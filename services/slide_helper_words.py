"""Helper words belong to the Slide (contract 13-14, founder 2026-09-25).

A Take may split a Slide into a different number of Paragraphs than the Take
before it, so helper words cannot live on a Paragraph and survive that. They
live on the Slide, in the order they were picked (Q12 A).

WHEN PICKS ADD UP AND WHEN THEY REPLACE (Q14 A, as narrowed by the F1
Repair Plan Phase 5). Picks made while reviewing the same Take add up on a
Slide. A pick LOCKED in a later Take replaces what THAT Paragraph had from
earlier Takes; another Paragraph's words on the same Slide stay until that
Paragraph is locked anew (locked helper words persist until the user picks
new ones, contract 14; the audit of 2026-10-03 found the whole Slide wiped).
The replacement waits for the lock rather than the tap, because a pick the
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
           if str(r.get("take_session_id") or "") == take_id
           or str(r.get("source_part_id") or "").lower() != part]
    return _renumber(out)


# THE FOUR-WORD CAP ON THE SERVER (founder lock 2026-09-30, B3; F1 Repair
# Plan Phase 5). The client stops a fifth tap; until now every save route took
# any length. Words saved before the cap are read as they are.
HELPER_WORDS_MAX = 4


def within_cap(phrase: Any) -> bool:
    """One to four words."""
    return 0 < len(str(phrase or "").split()) <= HELPER_WORDS_MAX


def _flat(text: Any) -> str:
    import re
    return re.sub(r"\s+", " ", str(text or "")).strip()


def phrase_in_version(phrase: Any, paragraphs: Any) -> Optional[str]:
    """The helper words, when they are exact words of one Take's version of
    the Slide (founder lock 2026-09-30, B4, D5, Q3: one Take, one phrase).

    `paragraphs` is that version's list of Paragraph texts for the Slide;
    the phrase must sit inside ONE of them, whitespace folded, no marker
    syntax. None otherwise."""
    import re
    want = _flat(phrase)
    if not want or re.search(r"[*_~`{}]", want):
        return None
    for text in paragraphs or []:
        if want in _flat(text):
            return want
    return None


def version_of_take(history: Mapping, take_index: Any) -> Optional[dict]:
    """The Slide's version spoken in one Take, by its Take number — the
    number the history labels each version with and the overlay's chips
    show."""
    if not isinstance(take_index, int) or isinstance(take_index, bool):
        return None
    for row in history.get("versions") or []:
        if isinstance(row, Mapping) and row.get("take_index") == take_index:
            return dict(row)
    return None


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
    """Slide-level helper words win for every Paragraph that has any.

    A Paragraph without a slide-level row yet (helper words locked before
    this table existed) keeps its Paragraph-level projection, so nothing
    already locked disappears on deploy -- including a sibling Paragraph on a
    Slide where another Paragraph has a slide-level row (Phase 5). A legacy
    row that names no Paragraph is covered by its Slide, as before."""
    covered_parts = {(r["slide_index"], str(r.get("part_id") or "").lower())
                     for r in slide_roots if r.get("part_id")}
    covered_slides = {r["slide_index"] for r in slide_roots}

    def _covered(r: Row) -> bool:
        part = str(r.get("part_id") or "").lower()
        if part:
            return (r.get("slide_index"), part) in covered_parts
        return r.get("slide_index") in covered_slides

    kept = [r for r in legacy if not _covered(r)]
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
