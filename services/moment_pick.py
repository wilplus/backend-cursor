"""Which moments a Take shows, and whether each is praised or corrected
(founder 2026-10-20, flow page C2, C4 and H1: "the score decides each";
founder lock 2026-10-12 section 6 for the read itself).

Each block's selected clip gets one number, its willfidence, S x W, from 0
to 1:

  S  the clip's universal-v3 sound read, stretched to 0..1
     (``willfidence.stretch``).
  W  the mean of the word signals present: few fillers, few hedges, fits the
     slide (``willfidence.filler`` / ``hedging`` / ``slide_fit``).

Shown: the Take's two highest moments, at most one per slide (each slide's
best clip, one with at least ``MIN_WORDS`` words when the slide has one),
ranked by willfidence, clips with enough words before short ones. Each shown moment is PRAISED when it reaches
``FLOOR`` with at least ``MIN_WORDS`` words and CORRECTED when it does not:
both strong, two praises and no practise; both weak, two corrections, each
with its own tries and clips. The highest of the two is marked, so the walk
can say "This was your most confident moment." A clip with no sound read is
not dropped (founder 2026-10-17): its S is neutral and its words order it;
such a clip is below the floor by construction, so it is corrected.

A correction's kind (founder 2026-10-18, "words first, then voice";
``services.rewrite_gate``): the clearer version when its words need help
(fillers, hedges, undermining words, off the slide, a broken sentence),
otherwise the voice exercise. The V3 policy then keeps the clearer version
only when a rewrite passes the gate's second half.

Until 2026-10-20 the roles were fixed: the best moment was praised (with the
softer line under the floor) and the second best was always corrected.

Internal only (AC-9): the numbers order the moments and never leave the
frame. What crosses to the client is a tier name, one flag and one routing
word.
"""
from __future__ import annotations

from typing import Any

from services import willfidence

#: Founder lock 2026-10-12, section 6: a start value, calibrated later so
#: that about 7 in 10 blind judges say Yes to green moments.
FLOOR = 0.6
MIN_WORDS = 5
#: The Take shows its two highest moments (founder 2026-10-14, 2026-10-17);
#: each is praised or corrected by its own score (founder 2026-10-20).
SHOWN_LIMIT = 2

EXERCISE_CLEARER = "clearer"
EXERCISE_VOICE = "voice"


#: S when a clip has no sound read (founder 2026-10-17): the middle of the
#: scale, so the words alone order the clips and the Take still shows its
#: two highest moments until the sound read is back. Never a number anyone
#: sees.
NEUTRAL_SOUND = 0.5


def read(score: Any, text: Any, metrics: Any) -> dict:
    """S, W and their product for one clip.

    With no sound read (the clip was never stamped: no baseline yet, the
    measure off, or it failed) S is ``NEUTRAL_SOUND`` and ``sound`` is
    False (founder 2026-10-17: the highest and the second-highest
    willfidence moments are always shown); below the floor by construction,
    so such a moment is corrected."""
    s = willfidence.stretch(score)
    sound = s is not None
    if s is None:
        s = NEUTRAL_SOUND
    from services.rewrite_gate import words_need_help
    fit = willfidence.slide_fit([metrics])
    w = willfidence.partial_w(willfidence.filler(text), willfidence.hedging(text), fit)
    w = 1.0 if w is None else w
    return {"s": s, "w": w, "value": s * w, "sound": sound,
            "words_help": words_need_help(text, fit)}


def pick(reads: list[dict]) -> dict:
    """``reads``: one row per block with ``block_id``, ``slide_index``,
    ``word_count`` and ``read`` (from :func:`read`, or None).

    Returns ``{"shown": [{"block_id", "praise", "kind", "highest"}, ...]}``:
    the two highest moments in rank order, ``praise`` True when the moment
    reaches the floor with enough words, else ``kind`` "clearer" or
    "voice"; ``highest`` marks the first."""
    scored = [row for row in reads if row.get("read")]
    best_per_slide: dict[Any, dict] = {}
    for row in scored:
        held = best_per_slide.get(row["slide_index"])
        if held is None or _ahead(row, held):
            best_per_slide[row["slide_index"]] = row
    # Clips with enough words rank before short ones, whatever their score:
    # a three-word fragment is shown only when a Take has nothing longer.
    ranked = sorted(best_per_slide.values(),
                    key=lambda r: (not _worded(r), -r["read"]["value"]))
    shown = []
    for position, row in enumerate(ranked[:SHOWN_LIMIT]):
        praise = _worded(row) and row["read"]["value"] >= FLOOR
        shown.append({
            "block_id": row["block_id"],
            "praise": praise,
            "kind": None if praise else (
                EXERCISE_CLEARER if row["read"].get("words_help") else EXERCISE_VOICE),
            "highest": position == 0,
        })
    return {"shown": shown}


def _worded(row: dict) -> bool:
    return (row.get("word_count") or 0) >= MIN_WORDS


def _ahead(row: dict, held: dict) -> bool:
    """A slide's best clip: one with enough words before one without, then
    the higher willfidence."""
    if _worded(row) != _worded(held):
        return _worded(row)
    return row["read"]["value"] > held["read"]["value"]
