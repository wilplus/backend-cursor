"""The window of three (founder lock 2026-09-30, task 11; contract 24b/24c
as amended).

At any moment the Ideal Text holds at most three OPEN feedbacks: moments
still waiting for the speaker's judgement or practise. The Manager still
evaluates every block and freezes every selection (24b); this is the last
step before serving, and it chooses which of the open moments reach the
page NOW. It re-decides on every read, so saving helper words on one moment
frees its slot and the next candidate appears without a new Take.

THE RULE (founder, Q2 A). Slots fill from the two ends of the read: the
highest moment read above the confident threshold takes green, the lowest
moment read below it with a practise attached takes orange, and the third
slot goes to whichever side has the next candidate farthest from the
threshold. Never three of one colour. When only one side has candidates,
at most two show. A moment the machine could not read, or read weak with
nothing to practise, fills a slot only when the two ends leave one empty,
in text order.

WHAT LEAVES THE WINDOW ENTIRELY. A paragraph saved with helper words is
done (B8): its moments are not served for judgement, and its notes ride the
locked screen, not the walk. Everything already answered stays: history is
never withheld. A praise or a rewrite rides its own paragraph's open moment
and is withheld with it, so no paragraph holds a note without the judgement
that carries it (24f).

AC-9: the score orders the slots and never leaves this module; the served
row carries the tier name and nothing else.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

WINDOW = 3
PER_COLOUR = 2
CONFIDENT_VOICE = "confident_voice"


def _is_moment(row: dict) -> bool:
    return (row.get("source") == CONFIDENT_VOICE
            or row.get("feedback_family") == CONFIDENT_VOICE)


def _open(row: dict) -> bool:
    return str(row.get("status") or "") not in ("approved", "dismissed")


def _colour(row: dict) -> Optional[str]:
    """"confident", "weak" (with a practise attached), or None for a moment
    that carries no bar."""
    tier = row.get("bookmark_tier")
    if tier == "confident":
        return "confident"
    if tier == "weak" and row.get("practice_exercise"):
        return "weak"
    return None


def _sides(
    scored: list[tuple[dict, Optional[float]]],
) -> tuple[list[tuple[dict, float]], list[tuple[dict, float]]]:
    """The two ends of the read: the confident moments, highest first, and
    the weak-with-a-practise moments, lowest first. A moment with no score
    is on neither side."""
    confident = sorted(
        ((row, s) for row, s in scored
         if _colour(row) == "confident" and s is not None),
        key=lambda pair: -pair[1])
    weak = sorted(
        ((row, s) for row, s in scored
         if _colour(row) == "weak" and s is not None),
        key=lambda pair: pair[1])
    return confident, weak


class _Slots:
    """The window filling up: at most WINDOW moments, at most PER_COLOUR of
    one colour."""

    def __init__(self) -> None:
        self.chosen: list[dict] = []
        self.taken = {"confident": 0, "weak": 0}

    def full(self) -> bool:
        return len(self.chosen) >= WINDOW

    def take(self, side: str, pool: list) -> None:
        if pool and self.taken[side] < PER_COLOUR and not self.full():
            self.chosen.append(pool.pop(0)[0])
            self.taken[side] += 1

    def farthest(self, side: str, pool: list) -> Optional[float]:
        """How far this side's next candidate sits from the threshold, or
        None when the side is spent or capped."""
        if not pool or self.taken[side] >= PER_COLOUR:
            return None
        return abs(pool[0][1])


def _fill_from_the_ends(
    slots: _Slots, confident: list, weak: list,
) -> None:
    """The third slot and any left: whichever side has the next candidate
    farther from the threshold; never a third of one colour."""
    while not slots.full() and (confident or weak):
        far_c = slots.farthest("confident", confident)
        far_w = slots.farthest("weak", weak)
        if far_c is None and far_w is None:
            break
        if far_w is None or (far_c is not None and far_c >= far_w):
            slots.take("confident", confident)
        else:
            slots.take("weak", weak)


def choose_open_moments(
    moments: list[dict], score_of: Callable[[dict], Optional[float]],
) -> list[dict]:
    """The open moments that fill the window, in the order they were given.

    `moments` are the open Confident Voice rows on paragraphs not saved
    with helper words, in text order. `score_of` is the internal read, above
    zero being the confident side; a moment with no score counts as
    unreadable.
    """
    if len(moments) <= WINDOW:
        return list(moments)
    scored = [(row, score_of(row)) for row in moments]
    confident, weak = _sides(scored)
    slots = _Slots()
    slots.take("confident", confident)
    slots.take("weak", weak)
    _fill_from_the_ends(slots, confident, weak)
    # Unreadable moments, weak with nothing to practise, or a moment the
    # bundle carries no score for, in text order.
    for row, s in scored:
        if slots.full():
            break
        if row not in slots.chosen and (_colour(row) is None or s is None):
            slots.chosen.append(row)
    kept = {id(row) for row in slots.chosen}
    return [row for row in moments if id(row) in kept]


def window_rows(
    rows: Iterable[Any], *, paragraph_of: Callable[[dict], Optional[int]],
    saved_paragraphs: set[int], score_of: Callable[[dict], Optional[float]],
) -> list[dict]:
    """The served rows after the window: at most three open moments, their
    notes, everything answered, and nothing on a paragraph saved with helper
    words."""
    rows = [row for row in rows if isinstance(row, dict)]
    open_moments = [
        row for row in rows
        if _is_moment(row) and _open(row)
        and paragraph_of(row) not in saved_paragraphs]
    chosen = choose_open_moments(open_moments, score_of)
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
