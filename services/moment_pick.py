"""Which moments a Take shows: green moments and one exercise
(founder lock 2026-10-12, ``docs/FOUNDER-LOCK-moment-feedback-chat-2026-10-12.md``
section 6).

Each block's selected clip gets one number, its willfidence, S x W, from 0
to 1:

  S  the clip's universal-v3 sound read, stretched to 0..1
     (``willfidence.stretch``).
  W  the mean of the word signals present: few fillers, few hedges, fits the
     slide (``willfidence.filler`` / ``hedging`` / ``slide_fit``).

Green: on each slide the best clip, if it reaches ``FLOOR`` and has at least
``MIN_WORDS`` words; the Take shows the best ``GREEN_LIMIT`` of those. When
none reaches the floor, the single best clip is shown with the softer signed
line (``soft``).

The exercise: the lowest clip that is not green. Its kind follows the lower
half: words (W < S) gives the clearer version, otherwise the voice exercise.

Internal only (AC-9): the numbers order the moments and never leave the
frame. What crosses to the client is a tier name and one routing word.
"""
from __future__ import annotations

from typing import Any, Optional

from services import willfidence

#: Founder lock 2026-10-12, section 6: a start value, calibrated later so
#: that about 7 in 10 blind judges say Yes to green moments.
FLOOR = 0.6
MIN_WORDS = 5
GREEN_LIMIT = 3

EXERCISE_CLEARER = "clearer"
EXERCISE_VOICE = "voice"


def read(score: Any, text: Any, metrics: Any) -> Optional[dict]:
    """S, W and their product for one clip; None when there is no sound read."""
    s = willfidence.stretch(score)
    if s is None:
        return None
    w = willfidence.partial_w(
        willfidence.filler(text), willfidence.hedging(text),
        willfidence.slide_fit([metrics]))
    w = 1.0 if w is None else w
    return {"s": s, "w": w, "value": s * w}


def pick(reads: list[dict]) -> dict:
    """``reads``: one row per block with ``block_id``, ``slide_index``,
    ``word_count`` and ``read`` (from :func:`read`, or None).

    Returns ``{"green": [block_id...], "soft": bool, "exercise": block_id or
    None, "exercise_kind": "clearer" | "voice" | None}``."""
    scored = [row for row in reads if row.get("read")]
    best_per_slide: dict[Any, dict] = {}
    for row in scored:
        if row["read"]["value"] < FLOOR or (row.get("word_count") or 0) < MIN_WORDS:
            continue
        held = best_per_slide.get(row["slide_index"])
        if held is None or row["read"]["value"] > held["read"]["value"]:
            best_per_slide[row["slide_index"]] = row
    ranked = sorted(best_per_slide.values(), key=lambda r: -r["read"]["value"])
    green = ranked[:GREEN_LIMIT]
    soft = False
    if not green and scored:
        green = [max(scored, key=lambda r: r["read"]["value"])]
        soft = True
    green_ids = [row["block_id"] for row in green]
    rest = [row for row in scored if row["block_id"] not in green_ids]
    lowest = min(rest, key=lambda r: r["read"]["value"]) if rest else None
    kind = None
    if lowest is not None:
        kind = (EXERCISE_CLEARER if lowest["read"]["w"] < lowest["read"]["s"]
                else EXERCISE_VOICE)
    return {
        "green": green_ids,
        "soft": soft,
        "exercise": lowest["block_id"] if lowest else None,
        "exercise_kind": kind,
    }
