"""Which open moments reach the page (founder lock 2026-10-12,
``docs/FOUNDER-LOCK-moment-feedback-chat-2026-10-12.md``; replaces the window
of three of 2026-09-30).

The Manager already chose them (`services.moment_pick`): up to three green
moments, at most one per slide, and one exercise. Every open Confident Voice
moment that is green (`bookmark_tier == "confident"`) or is the exercise
(`practice_prompt`) shows; other open moments do not. On a Take where the
machine could read nothing, at most two open moments show, in text order,
so the speaker still has something to open.

WHAT LEAVES ENTIRELY. A paragraph saved with helper words is done: its open
moments are not served, and its notes ride the locked screen. Everything
already answered stays: history is never withheld. A praise or a rewrite
rides its own paragraph's open moment and is withheld with it.

AC-9: no score or band is read or served here.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

#: On a Take with no green moment and no exercise, at most this many open
#: moments show, in text order.
UNREAD = 2
CONFIDENT_VOICE = "confident_voice"


def _is_moment(row: dict) -> bool:
    return (row.get("source") == CONFIDENT_VOICE
            or row.get("feedback_family") == CONFIDENT_VOICE)


def _open(row: dict) -> bool:
    return str(row.get("status") or "") not in ("approved", "dismissed")


def _picked(row: dict) -> bool:
    return row.get("bookmark_tier") == "confident" or bool(row.get("practice_prompt"))


def choose_open_moments(moments: list[dict]) -> list[dict]:
    """The open moments to show, in the order they were given."""
    picked = [row for row in moments if _picked(row)]
    return picked if picked else moments[:UNREAD]


def window_rows(
    rows: Iterable[Any], *, paragraph_of: Callable[[dict], Optional[int]],
    saved_paragraphs: set[int],
) -> list[dict]:
    """The served rows: the picked open moments, their notes, everything
    answered, and nothing on a paragraph saved with helper words."""
    rows = [row for row in rows if isinstance(row, dict)]
    open_moments = [
        row for row in rows
        if _is_moment(row) and _open(row)
        and paragraph_of(row) not in saved_paragraphs]
    chosen = choose_open_moments(open_moments)
    chosen_ids = {id(row) for row in chosen}
    withheld_paragraphs = {
        paragraph_of(row) for row in open_moments if id(row) not in chosen_ids}
    kept_paragraphs = {paragraph_of(row) for row in chosen}
    out: list[dict] = []
    for row in rows:
        paragraph = paragraph_of(row)
        if paragraph in saved_paragraphs and _open(row):
            continue
        if _is_moment(row):
            if _open(row) and id(row) not in chosen_ids:
                continue
        elif (_open(row) and paragraph in withheld_paragraphs
              and paragraph not in kept_paragraphs):
            continue
        out.append(row)
    return out
