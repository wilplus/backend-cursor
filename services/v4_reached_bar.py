"""The "reached" bar, calibrated from blind coach answers (V4 Phase 1,
B1.4b; build plan D-ML-15; founder O4, V8 A, V9 A, QB8 A).

WHAT THE BAR IS. A level of the machine's S x partial W (willfidence-v1-
machine, B1.3). In Phase 2 a practise try "reached" when its fast read is at
or above it (B1.4); the "Which sounds surer" queue splits passages above and
below it (QB8 A). Internal only: the bar and every value compared with it
stay inside the machine (AC-9).

HOW IT IS SET (O4). The level where blind coaches say "Yes, confident"
about 7 times in 10: the LOWEST level such that, among all answered moments
read at or above it, the coaches' Yes share is at least ``TARGET_SHARE``.
Any single blind coach answer counts (V8 A); In-between counts half (V9 A:
Yes 1, In-between 0.5, No 0); Not sure and Audio unclear are not answers
about the clip and are left out. A moment's level is its block's S x W, and
an answer about one of the block's clips is an answer about that moment.

UNTIL THERE ARE ENOUGH ANSWERS the bar is the placeholder ``PLACEHOLDER``
(0.6, dark only), and the report says so. ``MIN_ANSWERS`` is a starting
value. A calibrated bar is a new ``BAR_VERSION`` written here by hand, after
the report lands in the decisions log; older reads keep the version they
used.

Pure apart from ``gather`` (a read), and nothing here writes.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

#: The bar in force. A calibration replaces both lines in one reviewed change.
BAR = 0.6
BAR_VERSION = "reached-bar-v0-placeholder"
PLACEHOLDER = 0.6
#: O4: "where the blind coach says Yes about 7 in 10".
TARGET_SHARE = 0.7
#: Fewer answered moments than this and the placeholder stands.
MIN_ANSWERS = 40

#: V9 A (and Q1): Yes 1, In-between 1/2, No 0.
ANSWER_VALUES = {"yes": 1.0, "in_between": 0.5, "no": 0.0}


def answer_value(row: Any) -> Optional[float]:
    """One blind coach answer as a value, or None when it is not one: not
    the coach lane, a self-report, an abstention, not blind (0411), no rater,
    another question, or Not sure (V8 A: any single blind coach answer)."""
    if not isinstance(row, dict):
        return None
    if (row.get("state_id") or "confidence") != "confidence":
        return None
    if row.get("lane") != "coach" or row.get("self_report") or row.get("unrateable"):
        return None
    if row.get("blind") is False or not row.get("rater_id"):
        return None
    return ANSWER_VALUES.get(str(row.get("value") or ""))


def calibrate(pairs: Iterable[tuple[float, float]]) -> dict:
    """The bar from (level, answer value) pairs. Pure.

    Walks the answered moments from the highest level down, keeping the
    running Yes share of everything at or above; the bar is the lowest level
    at which that share still meets TARGET_SHARE. With fewer than MIN_ANSWERS
    pairs, or none meeting the target, the placeholder stands."""
    clean = sorted(
        ((float(level), float(value)) for level, value in pairs
         if level is not None and value is not None and 0.0 <= float(level) <= 1.0),
        key=lambda pair: -pair[0])
    report = {"answers": len(clean), "target_share": TARGET_SHARE,
              "min_answers": MIN_ANSWERS, "placeholder": PLACEHOLDER}
    if len(clean) < MIN_ANSWERS:
        return {**report, "bar": PLACEHOLDER, "status": "placeholder",
                "reason": "not_enough_answers", "share_at_or_above": None}
    total = 0.0
    bar: Optional[float] = None
    share_at_bar: Optional[float] = None
    for index, (level, value) in enumerate(clean, start=1):
        total += value
        last_of_level = index == len(clean) or clean[index][0] < level
        if last_of_level and total / index >= TARGET_SHARE:
            bar, share_at_bar = level, total / index
    if bar is None:
        return {**report, "bar": PLACEHOLDER, "status": "placeholder",
                "reason": "target_never_met", "share_at_or_above": None}
    return {**report, "bar": round(bar, 4), "status": "calibrated",
            "reason": None, "share_at_or_above": round(share_at_bar or 0.0, 4)}


def pairs_from(reads: Iterable[dict], frames: dict[str, dict],
               labels: Iterable[dict]) -> list[tuple[float, float]]:
    """Each blind coach answer paired with its moment's S x W. Pure.

    ``reads``: v4_willfidence_reads rows; ``frames``: {take id: frame};
    ``labels``: confidence_labels rows."""
    level_by_clip: dict[str, float] = {}
    for read in reads:
        if read.get("s") is None or read.get("w") is None:
            continue
        frame = frames.get(str(read.get("take_session_id"))) or {}
        block = next((b for b in frame.get("blocks") or []
                      if b.get("block_id") == read.get("block_id")), None)
        for clip in (block or {}).get("snippet_ids") or []:
            level_by_clip[str(clip)] = float(read["s"]) * float(read["w"])
    out: list[tuple[float, float]] = []
    for label in labels:
        value = answer_value(label)
        level = level_by_clip.get(str(label.get("snippet_id")))
        if value is not None and level is not None:
            out.append((level, value))
    return out


def gather(database: Any, limit: int = 5000) -> dict:
    """Read what the report needs and calibrate. Read-only."""
    client = database.client
    reads = (client.table("v4_willfidence_reads")
             .select("take_session_id,block_id,s,w")
             .eq("read_version", "willfidence-v1-machine")
             .limit(int(limit)).execute().data) or []
    takes = sorted({str(r["take_session_id"]) for r in reads})
    frames: dict[str, dict] = {}
    for take in takes:
        frame = database.get_v4_dark_frame(take)
        if isinstance(frame, dict):
            frames[take] = frame
    clips = sorted({str(c) for f in frames.values() for b in f.get("blocks") or []
                    for c in b.get("snippet_ids") or []})
    labels: list[dict] = []
    for start in range(0, len(clips), 200):
        labels.extend((client.table("confidence_labels")
                       .select("snippet_id,state_id,lane,self_report,unrateable,"
                               "blind,rater_id,value")
                       .in_("snippet_id", clips[start:start + 200])
                       .execute().data) or [])
    return {**calibrate(pairs_from(reads, frames, labels)),
            "bar_in_force": BAR, "bar_version": BAR_VERSION}
