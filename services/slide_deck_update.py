"""Updating a project's deck, inside the project (founder 2026-10-29, N257).

A speaker adds a deck to a project that has none, or replaces its deck, in
the same project: the Take count, the coach's history and the plan carry on.
Until N257 a changed deck was refused (409 PRESENTATION_LOCKED) and had to
start a new project (contract clause 4, N48.2 Q4 A); that refusal is gone.

How it works, end to end:

1. ``PUT /v2/projects/<id>/deck`` stores the next deck in
   ``projects.setup["next_deck"]`` (``store_next_deck``). No Take changes.
2. The setup read (``GET /v2/explore/arc/<id>/setup``) hands that deck to
   the recording screen (``setup_deck``), so the next Take is said on it.
3. When that Take is persisted, ``next_deck`` is cleared
   (``clear_next_deck_after_take``).
4. Its rebuild writes the WHOLE Ideal Text fresh from the Take, never a
   merge by slide index (``deck_changed_for_take``, used by
   ``services/take_rebuild.py``); the previous text stays in
   ``ideal_text_versions``. Helper words move to a new slide with the same
   title (``move_helper_words_by_title``); the others stay only in the
   helper-words history.

The deck of a Take is the one in its own ``v2_sessions.intake_context``
(slides and presentation_ref); the current deck is ``next_deck`` when set,
else the latest spoken Take's.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

NEXT_DECK = "next_deck"


class DeckUpdateError(Exception):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


def _context(session: Any) -> Mapping[str, Any]:
    ctx = session.get("intake_context") if isinstance(session, Mapping) else None
    return ctx if isinstance(ctx, Mapping) else {}


def _spoken(sessions: Any) -> list[dict]:
    """Spoken Takes in take order; a read never counts."""
    rows = [s for s in (sessions or [])
            if isinstance(s, dict) and s.get("recording_kind") != "read"
            and not s.get("paired_session_id")]
    rows.sort(key=lambda s: (int(s.get("take_index") or 0),
                             str(s.get("created_at") or "")))
    return rows


def has_deck(context: Any) -> bool:
    """Whether a Take's context (or a stored deck) carries slides or a PDF."""
    return isinstance(context, Mapping) and bool(
        context.get("slides") or context.get("presentation_ref"))


def deck_fingerprint(context: Any) -> tuple:
    """Exact deck identity: the PDF and the slides' titles and bodies.

    THE PDF, NOT ITS ADDRESS (founder 2026-10-10: Take 2 refused on the
    same slides). The setup read hands the app a freshly signed URL for
    the deck on every read (refreshed_media_url), and the app records the
    next Take with it, so the raw string never equals what was stored.
    Our refs compare by their object key: the same PDF in any of its four
    written shapes is the same deck. A foreign URL has no key and compares
    as written."""
    if not isinstance(context, Mapping):
        return (None, ())
    ref = context.get("presentation_ref")
    ref = ref.strip() if isinstance(ref, str) and ref.strip() else None
    if ref is not None:
        from services.coach_video_storage import media_key_from_ref

        ref = media_key_from_ref(ref) or ref
    rows = []
    slides = context.get("slides")
    if isinstance(slides, list):
        for slide in slides:
            if not isinstance(slide, Mapping):
                rows.append(("", ""))
                continue
            rows.append((str(slide.get("title") or "").strip(),
                         str(slide.get("body") or "").strip()))
    return (ref, tuple(rows))


def slide_titles(context: Any) -> list[str]:
    slides = context.get("slides") if isinstance(context, Mapping) else None
    if not isinstance(slides, list):
        return []
    return [str(s.get("title") or "").strip() if isinstance(s, Mapping) else ""
            for s in slides]


# ── The next deck, stored on the project ────────────────────────────────

def validate_deck(body: Any) -> dict:
    """``{"slides", "presentation_ref"}`` cleaned with the same rules as a
    Take's intake context (60 slides, title 200, body 2000, ref 2000).
    Raises ``IntakeContextError`` with a speaker-safe message. A body with
    neither slides nor a PDF is not a deck."""
    from services.intake_context import (
        IntakeContextError,
        _norm_presentation_ref,
        _norm_slides,
    )
    if not isinstance(body, dict):
        raise IntakeContextError("Body must be a JSON object")
    deck = {
        "slides": _norm_slides(body.get("slides")),
        "presentation_ref": _norm_presentation_ref(body.get("presentation_ref")),
    }
    if not has_deck(deck):
        raise IntakeContextError("slides or presentation_ref is required")
    return deck


def next_deck_of(project: Any) -> Optional[dict]:
    """The deck stored for the next Take, or None."""
    setup = project.get("setup") if isinstance(project, Mapping) else None
    deck = setup.get(NEXT_DECK) if isinstance(setup, Mapping) else None
    return dict(deck) if isinstance(deck, Mapping) and has_deck(deck) else None


def next_take_number(sessions: Any) -> int:
    """The number the next spoken Take will get."""
    return max((int(s.get("take_index") or 0) for s in _spoken(sessions)),
               default=0) + 1


def store_next_deck(database: Any, project_id: str, principal_id: str,
                    body: Any) -> dict:
    """Store the next deck on an owned project; no Take is touched.
    ``{"project_id", "next_take"}``, or ``DeckUpdateError`` /
    ``IntakeContextError``."""
    from services.project_repository import (
        ProjectOwnershipError,
        ProjectRepository,
    )
    deck = validate_deck(body)
    repository = ProjectRepository(database)
    try:
        project = repository.require_owned_project(project_id, principal_id)
    except ProjectOwnershipError as error:
        raise DeckUpdateError("PROJECT_NOT_FOUND", 404,
                              "Project not found") from error
    setup = dict(project.get("setup") or {}) \
        if isinstance(project.get("setup"), Mapping) else {}
    setup[NEXT_DECK] = {**deck,
                        "set_at": datetime.now(timezone.utc).isoformat()}
    if not database.update_project_setup(project_id, principal_id, setup):
        raise DeckUpdateError("PROJECT_NOT_FOUND", 404, "Project not found")
    return {"project_id": str(project_id),
            "next_take": next_take_number(repository.project_takes(project_id))}


def clear_next_deck_after_take(database: Any, project: Any,
                               principal_id: str, take_context: Any,
                               take_index: int) -> bool:
    """After a spoken Take is persisted: the stored next deck is spent when
    this Take was said on it, or on any deck other than the previous
    Take's (the first Take on new slides). A Take on the previous deck
    leaves it waiting. ``project`` is the row the upload already read, so a
    project with no next deck costs no read. Best-effort: never fails the
    Take (LIVE LOOP)."""
    stored = next_deck_of(project)
    if not stored:
        return False
    project_id = str(project.get("id") or "")
    try:
        mine = deck_fingerprint(take_context)
        if mine != deck_fingerprint(stored):
            earlier = [s for s in _spoken(database.takes.get_arc_sessions(
                project_id)) if int(s.get("take_index") or 0)
                < int(take_index)]
            if not earlier or mine == deck_fingerprint(
                    _context(earlier[-1])):
                return False
        setup = {k: v for k, v in (project.get("setup") or {}).items()
                 if k != NEXT_DECK}
        return bool(database.update_project_setup(
            project_id, str(principal_id), setup))
    except Exception as error:
        logger.warning("next deck not cleared project=%s take=%s: %s",
                       project_id, take_index, error, exc_info=True)
        return False


# ── Reads: the setup screen and the Ideal Text page ─────────────────────

def setup_deck(project: Any, spoken: list) -> tuple[Mapping[str, Any], bool,
                                                     Optional[int]]:
    """``(deck, deck_changed, deck_since_take)`` for the setup read.

    The stored next deck when there is one (the next Take is the first on
    it); else the deck of the latest spoken Take that carried one, with the
    Take it was first used on. ``spoken`` is in take order."""
    stored = next_deck_of(project)
    if stored:
        return stored, True, None
    anchor = next((i for i in range(len(spoken) - 1, -1, -1)
                   if has_deck(_context(spoken[i]))), len(spoken) - 1)
    if anchor < 0:
        return {}, False, None
    deck = _context(spoken[anchor])
    mark = deck_fingerprint(deck)
    first = anchor
    while first > 0 and deck_fingerprint(_context(spoken[first - 1])) == mark:
        first -= 1
    since = spoken[first].get("take_index")
    return deck, False, since if isinstance(since, int) else None


def latest_deck(spoken: list) -> tuple[Any, list[str]]:
    """``(presentation_ref, slide_titles)`` of the latest spoken Take that
    carried a deck; ``(None, [])`` when none did."""
    for session in reversed(spoken):
        context = _context(session)
        if has_deck(context):
            return context.get("presentation_ref") or None, slide_titles(context)
    return None, []


def deck_flags(database: Any, project_id: str, latest_ref: Any) -> dict:
    """``{"has_deck", "project_archived"}`` for the Ideal Text page: whether
    the current deck (the next deck if stored, else the latest Take's) has
    a PDF, and whether the project is archived (N14, N254). On a failed
    read: the latest Take's deck, not archived."""
    project = None
    try:
        project = database.get_project_row(str(project_id))
    except Exception as error:
        logger.warning("deck flags: project unreadable %s: %s",
                       project_id, error, exc_info=True)
    stored = next_deck_of(project)
    ref = stored.get("presentation_ref") if stored else latest_ref
    return {"has_deck": bool(ref),
            "project_archived": bool((project or {}).get("archived_at"))}


# ── The first Take on new slides ────────────────────────────────────────

def deck_changed_for_take(database: Any, arc_id: str, take_session_id: str,
                          old_doc: Any) -> Optional[tuple[list[str], list[str]]]:
    """``(old titles, new titles)`` when this Take was said on a different
    deck from the Take that wrote the current document; None when the deck
    is the same or cannot be read (then the Take rebuilds as before).

    The current document's Slide indexes belong to the deck of the Take
    that wrote it (``old_doc["take_session_id"]``); when that is unknown,
    the latest earlier spoken Take's deck stands in."""
    sessions = _spoken(database.takes.get_arc_sessions(str(arc_id)))
    by_id = {str(s.get("id")): s for s in sessions}
    take = by_id.get(str(take_session_id))
    if take is None:
        return None
    writer = None
    if isinstance(old_doc, Mapping) and old_doc.get("take_session_id"):
        writer = by_id.get(str(old_doc["take_session_id"]))
    if writer is None:
        index = int(take.get("take_index") or 0)
        earlier = [s for s in sessions if int(s.get("take_index") or 0) < index]
        writer = earlier[-1] if earlier else None
    if writer is None or str(writer.get("id")) == str(take_session_id):
        return None
    old, new = _context(writer), _context(take)
    if deck_fingerprint(old) == deck_fingerprint(new):
        return None
    return slide_titles(old), slide_titles(new)


def _title_key(title: Any) -> str:
    return str(title or "").strip().casefold()


def title_moves(old_titles: list[str], new_titles: list[str]) -> dict[int, int]:
    """Old slide index -> new slide index, where the titles are the same
    (trimmed, case-insensitive). A blank title matches nothing; repeated
    titles pair up in order."""
    free: dict[str, list[int]] = {}
    for index, title in enumerate(new_titles):
        if _title_key(title):
            free.setdefault(_title_key(title), []).append(index)
    moves = {}
    for index, title in enumerate(old_titles):
        slots = free.get(_title_key(title)) if _title_key(title) else None
        if slots:
            moves[index] = slots.pop(0)
    return moves


def move_helper_words_by_title(database: Any, arc_id: str, user_id: str,
                               old_titles: list[str],
                               new_titles: list[str]) -> None:
    """Helper words follow their slide's title onto the new deck (N257).

    Words on a slide whose title is not on the new deck leave the page;
    every replace is logged, so they stay in the helper-words history.
    Best-effort: the rewritten text is already durable."""
    try:
        rows = database.get_slide_helper_words(arc_id, user_id) or []
        by_slide: dict[int, list] = {}
        for row in rows:
            if isinstance(row.get("slide_index"), int):
                by_slide.setdefault(row["slide_index"], []).append(dict(row))
        if not by_slide:
            return
        moves = title_moves(old_titles, new_titles)
        landed = {moves[old]: words for old, words in by_slide.items()
                  if old in moves}
        for slide in sorted(set(by_slide) - set(landed)):
            database.replace_slide_helper_words(arc_id, user_id, slide, [])
        for slide, words in sorted(landed.items()):
            database.replace_slide_helper_words(arc_id, user_id, slide, words)
        logger.info("helper words moved to the new deck arc=%s moved=%d "
                    "left=%d", arc_id, len(landed),
                    len(by_slide) - len(landed))
    except Exception as error:
        logger.warning("helper words not moved to the new deck arc=%s: %s",
                       arc_id, error, exc_info=True)
