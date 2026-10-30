"""Which moments a Take shows, and whether each is praised or corrected
(founder 2026-10-23, N118 and N122, flow page C2 and H1: "minimum 2; best
two; highest willfidence moments of the take"; 2026-10-21, N108: "the voice
decides"; founder lock 2026-10-12 section 6 for the read itself).

Every clip gets its willfidence, S x W, from 0 to 1:

  S  the clip's universal-v3 sound read, stretched to 0..1
     (``willfidence.stretch``): the voice.
  W  the mean of the word signals present: few fillers, few hedges, fits the
     slide (``willfidence.filler`` / ``hedging`` / ``slide_fit``), read on
     the clip's own transcript.

Shown: the Take's three highest willfidence clips, however low, at most one
per block and from any slide, so they can be on one long slide (founder
2026-10-30, N284: "we need more moments at least 2"; two since N118); a
block's best clip stands for it, and clips with enough words (``MIN_WORDS``)
rank before short ones. A clip that holds the helper words its slide had
when the Take was recorded (``held``) ranks after the clips that do not, so
the next best confident moment is shown in its place (founder 2026-10-28,
N246 item 2). Fewer than three only when the Take has fewer clips, and
never fewer than two when it has two.
When the two best clips share a block, the V3 policy first moves the
boundary between them, or cuts the block itself, so each has a block of its
own (``best_two``; N128, N246 item 1). Of those shown, the stronger voice is
"your most confident moment", even when its willfidence is the lower (N122,
"S×W picks, voice names top"). On a plan, the moment where this week's level
shows most is practised as well (``pick_with_level``, N246 item 3).

The voice decides each (N108). A shown moment whose voice reaches ``FLOOR``
with at least ``MIN_WORDS`` words is PRAISED, unless its words need help
(``services.rewrite_gate``, read on the words the speaker sees, N121), when
it is CORRECTED with the clearer version; a moment whose voice is under the
floor is CORRECTED, with the clearer version when its words need help
("words first, then voice", founder 2026-10-18), otherwise the voice
exercise. So the voice exercise is only ever for a voice under the floor.
The V3 policy keeps the clearer version only when a rewrite passes the
gate's second half; a moment whose voice cleared the floor and whose rewrite
does not pass is praised (``voice_clears``), never sent to the voice
exercise.

A clip with no sound read is not dropped (founder 2026-10-17): its S is
neutral and its words order it; such a clip is below the floor by
construction, so it is corrected.

Until 2026-10-23 the Take showed its two strongest voices, at most one per
slide (N108), so a Take of one slide showed one moment and the second best
moment of a long slide was never shown. Until 2026-10-21 S x W decided both
the rank and the praise (N86). Willfidence also gives the praise's level,
the coach's read (N104) and the Take's column (N105).

Internal only (AC-9): the numbers order the moments and never leave the
frame. What crosses to the client is a tier name, one flag and one routing
word.
"""
from __future__ import annotations

from typing import Any, Optional

from services import willfidence

#: Founder lock 2026-10-12, section 6: a start value, calibrated later so
#: that about 7 in 10 blind judges say Yes to green moments.
FLOOR = 0.6
MIN_WORDS = 5
#: The Take shows its three highest moments (founder 2026-10-30, N284; two
#: since 2026-10-14, N118); each is praised or corrected by its own voice
#: (founder 2026-10-21, N108).
SHOWN_LIMIT = 3
#: The two best, which the V3 policy gives a block each (N128, N246 item 1).
PAIR = 2

EXERCISE_CLEARER = "clearer"
EXERCISE_VOICE = "voice"


#: S when a clip has no sound read (founder 2026-10-17): the middle of the
#: scale, so the words alone order the clips and the Take still shows its
#: highest moments until the sound read is back. Never a number anyone
#: sees.
NEUTRAL_SOUND = 0.5


def read(score: Any, text: Any, metrics: Any, shown: Any = None) -> dict:
    """S, W and their product for one clip.

    ``text`` is the clip's own transcript, which W reads; ``shown`` the
    words the speaker sees for it (the Ideal Text's, after the silent
    smoothing), which the words check reads (N121), the transcript when
    not given.

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
            "words_help": words_need_help(text if shown is None else shown, fit)}


def pick(reads: list[dict]) -> dict:
    """``reads``: one row per clip with ``block_id``, ``slide_index``,
    ``word_count``, ``candidate_id``, ``read`` (from :func:`read`, or
    None) and ``held`` (its words hold the slide's helper words; N246).

    Returns ``{"shown": [{"block_id", "candidate_id", "praise", "kind",
    "highest", "voice_clears"}, ...]}``: the three highest willfidence clips
    (N284),
    one per block, in rank order; ``praise`` True when the voice reaches
    the floor with enough words and the words need no help, else ``kind``
    "clearer" (the words need help) or "voice" (the voice is under the
    floor); ``highest`` marks the stronger voice of those shown (N122);
    ``voice_clears`` says the voice reached the floor (N108)."""
    best_per_block: dict[Any, dict] = {}
    for row in reads:
        if not row.get("read"):
            continue
        held = best_per_block.get(row["block_id"])
        if held is None or _rank(row) < _rank(held):
            best_per_block[row["block_id"]] = row
    ranked = sorted(best_per_block.values(), key=_rank)[:SHOWN_LIMIT]
    top = min(ranked, key=_voice_rank) if ranked else None
    return {"shown": [_entry(row, top) for row in ranked]}


def _entry(row: dict, top: Optional[dict]) -> dict:
    clears = _voice_clears(row)
    words_help = bool(row["read"].get("words_help"))
    praise = clears and not words_help
    return {
        "block_id": row["block_id"],
        "candidate_id": row.get("candidate_id"),
        "praise": praise,
        "kind": None if praise else (
            EXERCISE_CLEARER if words_help else EXERCISE_VOICE),
        "highest": row is top,
        "voice_clears": clears,
    }


def pick_with_level(reads: list[dict], candidate_id: Any, level: str, kind: str) -> dict:
    """A Take on a plan (founder 2026-10-28, N246 item 3, in place of N134
    item 2 and N209 item 2's best moment and the level's): the two best
    moments, as :func:`pick` reads them (three since N284), and the moment
    where this week's level shows most, ``candidate_id``, always practised
    with the level's own ``kind`` and marked ``plan_level``: on its own
    shown moment when it is one of them, else as one more, never the most
    confident. When that
    clip has no read, or another clip of its block is shown, :func:`pick`
    alone."""
    picked = pick(reads)
    shown = picked["shown"]
    marks = {"praise": False, "kind": kind, "plan_level": level}
    for at, moment in enumerate(shown):
        if moment["candidate_id"] == candidate_id:
            shown[at] = {**moment, **marks}
            return picked
    row = next((row for row in reads
                if row.get("read") and row.get("candidate_id") == candidate_id), None)
    if row is not None and all(moment["block_id"] != row["block_id"] for moment in shown):
        shown.append({**_entry(row, None), **marks})
    return picked


def best_two(reads: list[dict]) -> list[dict]:
    """The Take's two highest willfidence clips from any block, by the rank
    :func:`pick` uses (rows as it takes them). When both sit in one block,
    the V3 policy moves the block's boundary between them first, so
    :func:`pick` then shows both (founder 2026-10-24, N128)."""
    return sorted((row for row in reads if row.get("read")), key=_rank)[:PAIR]


def _rank(row: dict) -> tuple:
    """Clips with enough words first, whatever their voice (a three-word
    fragment is shown only when a Take has nothing longer), then those that
    do not hold the slide's helper words (N246 item 2), then the
    willfidence, then the voice (N118)."""
    return (not _worded(row), bool(row.get("held")), -row["read"]["value"],
            -row["read"]["s"])


def _voice_rank(row: dict) -> tuple:
    """The stronger voice: a clip with enough words first, then the voice,
    then the willfidence (N122)."""
    return not _worded(row), -row["read"]["s"], -row["read"]["value"]


def _voice_clears(row: dict) -> bool:
    """The voice reaches the floor, on a clip with enough words and a sound
    read (a clip with none stays corrected, 2026-10-17)."""
    read_ = row["read"]
    return _worded(row) and bool(read_.get("sound", True)) and read_["s"] >= FLOOR


def _worded(row: dict) -> bool:
    return (row.get("word_count") or 0) >= MIN_WORDS
