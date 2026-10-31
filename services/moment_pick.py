"""Which moments a Take shows, and what each one is for (founder
2026-10-30, N289: "the praise clips just get the praise ... the moments
that need to be improved, get the AI [clip]"; the read itself, founder lock
2026-10-12 section 6).

Every clip gets its willfidence, S x W, from 0 to 1:

  S  the clip's universal-v3 sound read, stretched to 0..1
     (``willfidence.stretch``): the voice.
  W  the mean of the word signals present: few fillers, few hedges, fits the
     slide (``willfidence.filler`` / ``hedging`` / ``slide_fit``), read on
     the clip's own transcript.

Three moments, one per block, each with its own job (N289):

  strongest  the Take's highest willfidence clip, a block's best clip
             standing for it; clips with enough words (``MIN_WORDS``) rank
             before short ones, and a clip that holds the helper words its
             slide had when the Take was recorded (``held``) after the
             others (N246 item 2). Always PRAISED, whatever its voice, and
             "your most confident moment" (``highest``). No AI clip.
  weakest    from a block left, the lowest willfidence clip with at least
             ``STRETCH_WORDS`` words and a sound read: room to grow the
             machine actually heard. CORRECTED with the voice (``voice``):
             the AI clip, practised.
  between    from another block, the clip whose words need help the most
             (``services.rewrite_gate``, read on the words the speaker sees,
             N121): CORRECTED with the clearer version (``clearer``). The
             policy keeps it only when a rewrite passes the gate's second
             half; else it is praised as a next best. Picked before the
             weakest, so a Take of two blocks gets the precise fix. Rushing
             is the tempo step's (N181, N289 item 6), which follows the
             moments.

A slot nothing fills gives its place to the next best block, praised as the
strongest is (``next``; N289 item 5), so a Take still shows three when it
has three blocks (N284), and never skips one. The walk's order is the
client's: strongest, weakest, the next best, then between.

On a plan (N289 item 8), this week's level takes the slot whose tool fits
it (``pick(reads, level=...)``): "Say it once" the between, "A voice that
moves" the weakest; never the strongest's block, never a fourth moment.

The Take's context counts too (N293, ``services.take_context``): a clip that
carries the key line or the call to action reads a little higher for the
strongest and a little lower for the fix slots (``RELEVANCE_LIFT``), so the
praise and the fix land where the talk needs them. Nothing known, nothing
changes.

A clip with no sound read is not dropped (founder 2026-10-17): its S is
neutral and its words order it. It can be the strongest, never the weakest.

Until 2026-10-30 the Take showed its three highest clips, each praised or
corrected by its own voice (N108, N284), and every praise was practised
with the AI clip (N122); before that, its two highest (N118) or its two
strongest voices (N108).

Internal only (AC-9): the numbers order the moments and never leave the
frame. What crosses to the client is a tier name, one flag, one routing
word and the slot's name.
"""
from __future__ import annotations

from typing import Any, Optional

from services import willfidence

#: Founder lock 2026-10-12, section 6: a start value, calibrated later so
#: that about 7 in 10 blind judges say Yes to green moments.
FLOOR = 0.6
MIN_WORDS = 5
#: Three moments a Take (N284), one per block.
SHOWN_LIMIT = 3
#: The weakest is a whole thought, never a fragment (N289 item 2).
STRETCH_WORDS = 8
#: How much a sentence that carries the key line or the call to action
#: counts for more (N293, ``services.take_context.relevance``): it lifts the
#: strongest's rank and makes the fix likelier to land on it.
RELEVANCE_LIFT = 0.25
#: The two best, which the V3 policy gives a block each (N128, N246 item 1).
PAIR = 2

EXERCISE_CLEARER = "clearer"
EXERCISE_VOICE = "voice"

#: The slots (N289), as the client reads them: a word, never a rank.
SLOT_STRONGEST = "strongest"
SLOT_WEAKEST = "weakest"
SLOT_BETWEEN = "between"
SLOT_NEXT = "next"


#: S when a clip has no sound read (founder 2026-10-17): the middle of the
#: scale, so the words alone order the clips and the Take still shows its
#: highest moments until the sound read is back. Never a number anyone
#: sees.
NEUTRAL_SOUND = 0.5


def read(score: Any, text: Any, metrics: Any, shown: Any = None,
         relevance: float = 0.0) -> dict:
    """S, W and their product for one clip.

    ``text`` is the clip's own transcript, which W reads; ``shown`` the
    words the speaker sees for it (the Ideal Text's, after the silent
    smoothing), which the words check reads (N121), the transcript when
    not given; ``relevance`` how much it serves the talk, 0 to 1, from the
    Take's context (N293), 0 when nothing is known.

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
            "words_help": words_need_help(text if shown is None else shown, fit),
            "relevance": max(0.0, min(1.0, float(relevance or 0.0)))}


def pick(reads: list[dict], level: Optional[dict] = None) -> dict:
    """``reads``: one row per clip with ``block_id``, ``slide_index``,
    ``word_count``, ``candidate_id``, ``read`` (from :func:`read`, or
    None) and ``held`` (its words hold the slide's helper words; N246).

    ``level``, on a plan (N289 item 8): ``{"candidate_id", "slot", "kind",
    "plan_level"}``, the clip where this week's level shows most and the
    slot it takes; ignored when that clip has no read or sits in the
    strongest's block.

    Returns ``{"shown": [{"block_id", "candidate_id", "praise", "kind",
    "highest", "voice_clears", "slot"}, ...]}``, at most one per block:
    the strongest (praised, ``highest``), the weakest (``kind`` "voice"),
    the between (``kind`` "clearer"), each slot nothing fills taken by the
    next best block (``slot`` "next", praised); ``plan_level`` on the
    level's moment. ``voice_clears`` says the voice reached the floor
    (N113)."""
    readable = [row for row in reads if row.get("read")]
    best_per_block: dict[Any, dict] = {}
    for row in readable:
        held = best_per_block.get(row["block_id"])
        if held is None or _rank(row) < _rank(held):
            best_per_block[row["block_id"]] = row
    ranked = sorted(best_per_block.values(), key=_rank)
    if not ranked:
        return {"shown": []}
    strongest = ranked[0]
    used = {strongest["block_id"]}
    forced = _level_row(readable, level, strongest)
    shown = [_entry(strongest, SLOT_STRONGEST, praise=True, highest=True)]
    # The precise fix first: on a Take of two blocks, words that need help
    # get their clearer version before the AI clip gets the weakest.
    for slot, find, kind in ((SLOT_BETWEEN, _between, EXERCISE_CLEARER),
                             (SLOT_WEAKEST, _weakest, EXERCISE_VOICE)):
        if forced and forced[1]["slot"] == slot:
            found: Optional[dict] = forced[0]
            marks = {"kind": forced[1]["kind"], "plan_level": forced[1]["plan_level"]}
        else:
            found = find([r for r in readable if r["block_id"] not in used
                          and not (forced and r["block_id"] == forced[0]["block_id"])])
            marks = {"kind": kind}
        if found is not None:
            used.add(found["block_id"])
            shown.append({**_entry(found, slot, kind=marks.pop("kind")), **marks})
    for row in ranked[1:]:
        if len(shown) >= SHOWN_LIMIT:
            break
        if row["block_id"] not in used:
            used.add(row["block_id"])
            shown.append(_entry(row, SLOT_NEXT, praise=True))
    return {"shown": shown}


def _entry(row: dict, slot: str, *, praise: bool = False, highest: bool = False,
           kind: Optional[str] = None) -> dict:
    return {
        "block_id": row["block_id"],
        "candidate_id": row.get("candidate_id"),
        "praise": praise,
        "kind": None if praise else kind,
        "highest": highest,
        "voice_clears": _voice_clears(row),
        "slot": slot,
    }


def _weakest(rows: list[dict]) -> Optional[dict]:
    """The lowest willfidence clip with a whole thought and a sound read;
    never one that already holds its slide's helper words (N246 item 2:
    it was worked on), which comes back only as a next best."""
    heard = [row for row in rows if (row.get("word_count") or 0) >= STRETCH_WORDS
             and row["read"].get("sound", True) and not row.get("held")]
    return min(heard, key=lambda row: (row["read"]["value"] * _damp(row), row["read"]["s"]),
               default=None)


def _between(rows: list[dict]) -> Optional[dict]:
    """The clip whose words need help the most: the lowest W, then the
    lowest willfidence; never one that holds its slide's helper words."""
    worded = [row for row in rows if _worded(row) and row["read"].get("words_help")
              and not row.get("held")]
    return min(worded, key=lambda row: (row["read"]["w"] * _damp(row), row["read"]["value"]),
               default=None)


def _level_row(rows: list[dict], level: Optional[dict],
               strongest: dict) -> Optional[tuple[dict, dict]]:
    if not level or level.get("slot") not in (SLOT_WEAKEST, SLOT_BETWEEN):
        return None
    row = next((r for r in rows if r.get("candidate_id") == level.get("candidate_id")), None)
    if row is None or row["block_id"] == strongest["block_id"]:
        return None
    return row, level


def best_two(reads: list[dict]) -> list[dict]:
    """The Take's two highest willfidence clips from any block, by the rank
    :func:`pick` uses (rows as it takes them). When both sit in one block,
    the V3 policy moves the block's boundary between them first, so the
    Take has more blocks to show its moments from (founder 2026-10-24,
    N128)."""
    return sorted((row for row in reads if row.get("read")), key=_rank)[:PAIR]


def _rank(row: dict) -> tuple:
    """The strongest's rank: clips with enough words first, whatever their
    voice (a three-word fragment is shown only when a Take has nothing
    longer), then those that do not hold the slide's helper words (N246
    item 2), then the willfidence, lifted by relevance (N293), then the
    voice (N118)."""
    return (not _worded(row), bool(row.get("held")),
            -row["read"]["value"] * (1 + RELEVANCE_LIFT * _relevance(row)), -row["read"]["s"])


def _relevance(row: dict) -> float:
    return float(row["read"].get("relevance") or 0.0)


def _damp(row: dict) -> float:
    """A relevant sentence reads a little lower for the fix slots, so the
    fix lands where it matters most to the talk (N293)."""
    return 1 - RELEVANCE_LIFT * _relevance(row)


def _voice_clears(row: dict) -> bool:
    """The voice reaches the floor, on a clip with enough words and a sound
    read (a clip with none stays corrected, 2026-10-17)."""
    read_ = row["read"]
    return _worded(row) and bool(read_.get("sound", True)) and read_["s"] >= FLOOR


def _worded(row: dict) -> bool:
    return (row.get("word_count") or 0) >= MIN_WORDS
