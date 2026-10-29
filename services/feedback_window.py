"""Which open moments reach the page (founder lock 2026-10-12,
``https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-moment-feedback-chat-2026-10-12.md``; replaces the window
of three of 2026-09-30).

The Manager already chose them (`services.moment_pick`): the Take's two
highest moments, at most one per slide, each praised or corrected by its
own willfidence (founder 2026-10-20). Every open Confident Voice moment that
is praised (`bookmark_tier == "confident"`) or corrected (`practice_prompt`)
shows; other open moments do not. On a Take where the
machine could read nothing, at most two open moments show, in text order,
so the speaker still has something to open. A Take whose picked moments are
all answered is not one: no other moment takes their place (founder
2026-10-21, "the black lines on the ideal text are still there even though I
walked through them").

WHAT LEAVES ENTIRELY. A paragraph saved with helper words is done: its open
moments are not served, and its notes ride the locked screen; except a
moment the Manager picked, which stays with its notes until it is answered
(founder 2026-10-28, N246 item 5: the two best moments may share a slide's
paragraph, and the helper words saved at the first took the second away).
Everything already answered stays: history is never withheld. A praise or a
rewrite rides its own paragraph's open moment and is withheld with it.

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


def choose_open_moments(moments: list[dict], *,
                        read: bool = False) -> list[dict]:
    """The open moments to show, in the order they were given. ``read``: the
    Take has picked moments, open or answered."""
    picked = [row for row in moments if _picked(row)]
    return picked if picked or read else moments[:UNREAD]


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
        and (_picked(row) or paragraph_of(row) not in saved_paragraphs)]
    read = any(_is_moment(row) and _picked(row) for row in rows)
    chosen = choose_open_moments(open_moments, read=read)
    chosen_ids = {id(row) for row in chosen}
    withheld_paragraphs = {
        paragraph_of(row) for row in open_moments if id(row) not in chosen_ids}
    kept_paragraphs = {paragraph_of(row) for row in chosen}
    out: list[dict] = []
    for row in rows:
        paragraph = paragraph_of(row)
        if paragraph in saved_paragraphs and _open(row) and paragraph not in kept_paragraphs:
            continue
        if _is_moment(row):
            if _open(row) and id(row) not in chosen_ids:
                continue
        elif (_open(row) and paragraph in withheld_paragraphs
              and paragraph not in kept_paragraphs):
            continue
        out.append(row)
    return out
