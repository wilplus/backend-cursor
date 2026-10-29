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
         now: Optional[str] = None,
         live_parts: Optional[set] = None) -> list[Row]:
    """One Slide's rows after the speaker locks (or unlocks) a Paragraph.

    `live_parts`: the ids of the Slide's Paragraphs now (lower case). A lock
    also retires earlier-Take rows of a Paragraph the Slide no longer has
    (audit 2026-10-04: a later Take with fewer or fresh Paragraphs left its
    words on the recording screen, out of reach of any lock or unlock)."""
    part = str(part_id).lower()

    def _orphan(r: Row) -> bool:
        source = str(r.get("source_part_id") or "").lower()
        return live_parts is not None and source not in live_parts

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
           or (str(r.get("source_part_id") or "").lower() != part
               and not _orphan(r))]
    return _renumber(out)


# THE EIGHT-WORD CAP ON THE SERVER (founder lock 2026-09-30, B3; F1 Repair
# Plan Phase 5; six 2026-10-12; eight 2026-10-15). The client stops a ninth
# tap; before the cap every save route took any length. Words saved before
# the cap are read as they are. The frontend's HELPER_WORDS_MAX
# (src/lib/willab/phraseTokens.ts) must match.
HELPER_WORDS_MAX = 8

# ANY WORDS OF THE PARAGRAPH (founder 2026-10-15). The words need not sit
# next to each other: each run of neighbouring words is one piece, and the
# pieces are joined with this, in the order they were said.
PIECE_SEP = " · "


def pieces(phrase: Any) -> list[str]:
    """The runs of words one helper-words pick holds."""
    return [p.strip() for p in str(phrase or "").split(PIECE_SEP.strip())
            if p.strip()]


def within_cap(phrase: Any) -> bool:
    """One to eight words."""
    count = sum(len(p.split()) for p in pieces(phrase))
    return 0 < count <= HELPER_WORDS_MAX


def _flat(text: Any) -> str:
    import re
    return re.sub(r"\s+", " ", str(text or "")).strip()


def phrase_in_version(phrase: Any, paragraphs: Any) -> Optional[str]:
    """The helper words, when they are exact words of one Take's version of
    the Slide (founder lock 2026-09-30, B4, D5, Q3: one Take, one pick).

    `paragraphs` is that version's list of Paragraph texts for the Slide;
    every piece must sit inside ONE of them, in the order said, whitespace
    folded, no marker syntax. None otherwise."""
    import re
    parts = [_flat(p) for p in pieces(phrase)]
    if not parts or any(re.search(r"[*_~`{}]", p) for p in parts):
        return None
    for text in paragraphs or []:
        hay, at = _flat(text), 0
        for part in parts:
            at = hay.find(part, at)
            if at < 0:
                break
            at += len(part)
        else:
            return PIECE_SEP.join(parts)
    return None


def holds(text: Any, phrases: Any) -> bool:
    """Do these words hold one of the helper-word picks in ``phrases``,
    every piece of it in the order picked? Case, spacing and punctuation
    aside (founder 2026-10-28, N246 item 2: the sentence that already has
    its helper words gives its place to the next confident moment)."""
    said = _tokens(text)
    for phrase in phrases or []:
        parts = [part for part in (_tokens(piece) for piece in pieces(phrase)) if part]
        if parts and _in_order(said, parts):
            return True
    return False


def _tokens(text: Any) -> list[str]:
    import re
    return re.findall(r"[\w']+", str(text or "").replace("’", "'").lower())


def _in_order(said: list[str], parts: list[list[str]]) -> bool:
    at = 0
    for part in parts:
        size = len(part)
        found = next((i for i in range(at, len(said) - size + 1)
                      if said[i:i + size] == part), None)
        if found is None:
            return False
        at = found + size
    return True


def held_at_take(database: Any, arc_id: Any, user_id: Any, take: Any,
                 slides: Any) -> dict[int, list[str]]:
    """``{slide_index: [phrase, ...]}``: the locked helper words each of
    ``slides`` had when ``take`` was recorded, the last set the log holds
    from before it began (N246 item 2). Read from the log, not the live rows,
    so words picked in this Take's own walk never move its moments, and an
    older Take reads the same on every opening. {} on anything unreadable,
    logged: the moments are then picked as before."""
    from services.rewrite_declines import instant
    started = instant(take.get("created_at")) if isinstance(take, Mapping) else None
    wanted = sorted({s for s in slides or () if isinstance(s, int)
                     and not isinstance(s, bool) and s >= 0})
    if started is None or not arc_id or not user_id or not wanted:
        return {}
    try:
        logs = database.list_slide_helper_words_log_for_slides(
            str(arc_id), str(user_id), wanted)
    except Exception as error:  # noqa: BLE001 -- the moments as before
        logger.warning("slide helper words at the take unreadable arc=%s: %s",
                       arc_id, error)
        return {}
    held: dict[int, list[str]] = {}
    for slide, rows in (logs or {}).items():
        before = [row for row in rows or [] if isinstance(row, Mapping)
                  and (instant(row.get("created_at")) or started) < started]
        phrases = [str(p) for p in (before[-1].get("phrases") or []) if p] if before else []
        if phrases:
            held[slide] = phrases
    return held


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


def anchor_to_snapshot(slide_roots: list[Row], snapshot: Any) -> list[Row]:
    """Each Slide's helper words on a Paragraph the document still has.

    The words belong to the Slide (contract 13-14) and stay until the
    speaker picks new ones (rule 5), but each row remembers the Paragraph
    they were picked on. A later Take can give the Slide a fresh Paragraph,
    and the page draws words only on a Paragraph it has, so they vanished
    (founder 2026-10-13, project "S": slide 3's words named a Paragraph two
    Takes old). A row whose Paragraph is gone moves to the Slide's Paragraph
    that says the words, else the Slide's first. A Slide the snapshot cannot
    place keeps its rows unchanged. Pure."""
    payload = snapshot.get("payload") if isinstance(snapshot, Mapping) else None
    parts = payload.get("parts") if isinstance(payload, Mapping) else None
    pieces = payload.get("pieces") if isinstance(payload, Mapping) else None
    if (not isinstance(parts, list) or not isinstance(pieces, list)
            or len(parts) != len(pieces)):
        return slide_roots
    on_slide: dict[int, list[tuple[str, str]]] = {}
    for part, piece in zip(parts, pieces):
        if not isinstance(part, Mapping) or not isinstance(piece, Mapping):
            continue
        slide = piece.get("slide_index")
        if isinstance(slide, int) and not isinstance(slide, bool) and part.get("id"):
            on_slide.setdefault(slide, []).append(
                (str(part["id"]), _flat(part.get("text")).lower()))
    out: list[Row] = []
    for root in slide_roots:
        here = on_slide.get(root.get("slide_index"))  # type: ignore[arg-type]
        part = str(root.get("part_id") or "").lower()
        if not here or any(pid.lower() == part for pid, _ in here):
            out.append(root)
            continue
        words = _flat(root.get("text")).lower()
        home = next((pid for pid, text in here if words and words in text),
                    here[0][0])
        out.append(dict(root, part_id=home))
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


def parts_on_slide(snapshot: Any, slide: int) -> Optional[set]:
    """The lower-case ids of the Paragraphs on `slide` in the core snapshot,
    or None when the snapshot cannot say."""
    payload = snapshot.get("payload") if isinstance(snapshot, Mapping) else None
    if not isinstance(payload, Mapping):
        return None
    parts, pieces = payload.get("parts"), payload.get("pieces")
    if (not isinstance(parts, list) or not isinstance(pieces, list)
            or len(parts) != len(pieces)):
        return None
    return {str(part.get("id") or "").lower()
            for part, piece in zip(parts, pieces)
            if isinstance(part, Mapping) and isinstance(piece, Mapping)
            and piece.get("slide_index") == slide and part.get("id")}


def _apply(database: Any, arc_id: str, user_id: str, part_id: str,
           change) -> None:
    snapshot = database.get_ideal_text_document_core(arc_id, user_id)
    slide = slide_of_part(snapshot, part_id)
    if slide is None:
        return
    rows = [r for r in (database.get_slide_helper_words(arc_id, user_id) or [])
            if r.get("slide_index") == slide]
    after = change(rows, parts_on_slide(snapshot, slide))
    if after != rows:
        database.replace_slide_helper_words(arc_id, user_id, slide, after)


def record_pick(database: Any, arc_id: str, user_id: str, part_id: str,
                take_id: str, phrase: Optional[str]) -> None:
    """Best-effort: mirror a Paragraph pick onto its Slide."""
    try:
        _apply(database, arc_id, user_id, part_id,
               lambda rows, _live: pick(rows, take_id=take_id,
                                        part_id=part_id, phrase=phrase))
    except Exception as error:
        logger.warning("slide helper words pick failed arc=%s part=%s: %s",
                       arc_id, part_id, error)


def record_lock(database: Any, arc_id: str, user_id: str, part_id: str,
                take_id: str, locked: bool) -> None:
    """Best-effort: mirror a Paragraph lock onto its Slide."""
    try:
        _apply(database, arc_id, user_id, part_id,
               lambda rows, live: lock(rows, take_id=take_id,
                                       part_id=part_id, locked=locked,
                                       live_parts=live))
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


def page_roots(database: Any, arc_id: str, user_id: str,
               snapshot: Any) -> list[Row]:
    """The helper words the page draws over this immutable document.

    The Paragraphs' own locked words, joined to the snapshot's exact Slide
    lineage; then the Slides' words on a Paragraph the document still has.
    When the live Paragraphs are mid-change (a new Take publishes in two
    steps), the snapshot's own words stand in: refusing dropped every helper
    word on the project for that read (founder 2026-10-13, project "S")."""
    from services.recording_roots import (
        RecordingRootsStale,
        frozen_recording_roots,
        project_recording_roots,
    )
    try:
        roots = project_recording_roots(
            snapshot,
            database.get_ideal_text_parts(arc_id, user_id, with_lock=True),
        )
    except RecordingRootsStale as error:
        logger.info("recording roots from the snapshot arc=%s: %s",
                    arc_id, error)
        roots = frozen_recording_roots(snapshot)
    return merge_recording_roots(
        roots, anchor_to_snapshot(slide_roots(database, arc_id, user_id), snapshot))
