"""The catalogue of signed lines (founder 2026-09-30, E3 and C4; P1-4).

One signed sentence per pattern, read by the Manager before its fallback:

  * a PRAISE row (family great_formulation) gets `praise_line`: the line
    for its device first (an exact-quote structural device, or the
    impeccable read), else the first of its delivery cues that has a line,
    else the line for the confident read itself;
  * a REWRITE row (family rewrite_clarity) gets `rewrite_move`: the line
    for its why_key ("clarity", "clarity_tentative", ...).

A row with no matching line is left as it is: the sheet keeps its constant
and the fallback stays honest (contract 24f). Nothing here invents a line,
scores anything, or reads a recording (AC-9, L3). Pure except `decorate`'s
one catalogue read, which the caller passes in.

THE PROPOSED FLOOR (founder 2026-10-05, decisions log N48.6, Q29 A). Nine
praise lines and three rewrite moves, drafted for the founder's signature
and held below behind ``PROPOSED_LINES_SIGNED``, which is OFF: until he
signs docs/SIGN-praise-lines-and-rewrite-moves-2026-10.md and a reviewed
change flips it, nothing in this module behaves differently from before.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# The Manager's own leading-filler rule, so a move is named by the rule that
# made the rewrite rather than by a second opinion about it.
from services.take_feedback_manager import _LEADING_FILLER_RE

LANES = ("praise", "rewrite")
PATTERN_KINDS = {
    "praise": ("read", "cue", "device"),
    "rewrite": ("move",),
}
#: The read a praise line falls back to when neither device nor cue has one.
CONFIDENT_READ = "confident_read"
MAX_TEXT = 400
_KEY_MAX = 64

#: The device the Manager's tentative praise fallback carries
#: (take_feedback_manager._fallback_praise): the shortest complete sentence,
#: praised in tentative words because that is all the evidence allows.
TENTATIVE_FORMULATION = "tentative_formulation"

#: The three rewrite moves, under the names the coach panel's Home screen
#: already files them by (frontend src/lib/willab/coachWalkCopy.ts,
#: homeMoves). Keys, never copy.
DROP_THE_FILLER = "drop_the_filler"
SPLIT_THE_CLAUSE = "split_the_clause"
REPAIR_THE_STRUCTURE = "repair_the_structure"
REWRITE_MOVES = (DROP_THE_FILLER, SPLIT_THE_CLAUSE, REPAIR_THE_STRUCTURE)

# ── THE PROPOSED LINES (founder 2026-10-05, decisions log N48.6, Q29 A) ────
#
# "The nine praise lines and three rewrite moves are drafted by the session
# for the founder's signature." Drafted from contract 24f, 24j, 25, 29b and
# 35f and from the founder's own wording: the praise lead "It was your
# confident moment." and the tentative praise (2026-09-24), the cue sentences
# on the Good job screen (frontend trackedChangeWhy.ts PRAISE_CUE_COPY) and
# the signed after-practice sentences (services/after_practice.py, N22).
# Each line, its trigger and the reason for its words are on the signing
# sheet, docs/SIGN-praise-lines-and-rewrite-moves-2026-10.md.
#
# PROPOSED, NOT SIGNED. Every line is copy a speaker would read, so none
# reaches a speaker until the founder signs the sheet and a reviewed change
# sets PROPOSED_LINES_SIGNED. A "B" answer on the sheet replaces a text here
# with the founder's own words before that change; a struck line is removed.
#
# Off, nothing changes: `floor_rows()` is empty, `decorate` reads only the
# database catalogue, and a rewrite's move is looked up by its why_key alone,
# exactly as before. On, these lines are the catalogue's FLOOR (E3): version
# 0, beneath every line a founder or coach writes into `feedback_catalogue`
# (version 1 and up), so a signed line in the table always wins for its
# pattern; and a rewrite row is also looked up by the move its own words
# made (`move_of`), most specific first, like praise.
#
# Every line describes how the delivery or the words SOUND, never how the
# speaker felt (N23 Q7); compares the speaker only with their own norm,
# never with anyone else; carries no number (AC-9) and no retired construct
# word; and is tentative where the evidence is (the fallback praise and the
# two fallback moves).
PROPOSED_LINES_SIGNED = False

PROPOSED_LINES: tuple[tuple[str, str, str, str], ...] = (
    # (lane, pattern_kind, pattern_key, text)
    ("praise", "read", CONFIDENT_READ,
     "It was your confident moment: your voice sounded more assured here "
     "than it usually does."),
    ("praise", "cue", "wide_range",
     "Your voice rose and fell more than it usually does, so the words did "
     "not sit on one note."),
    ("praise", "cue", "full_volume",
     "You let your volume move, so the words had shape rather than one flat "
     "level."),
    ("praise", "cue", "no_hesitation",
     "You went straight through it, with fewer and shorter pauses than you "
     "usually take."),
    ("praise", "cue", "settled_pitch",
     "Your voice sat lower than it usually does, so it sounded settled."),
    ("praise", "cue", "kept_moving",
     "You kept the pace up here instead of letting it drop."),
    ("praise", "cue", "landed_ending",
     "You brought the end down and landed it, instead of letting it drift "
     "up."),
    ("praise", "cue", "opened_strong",
     "You opened with energy and eased off after, instead of building up "
     "to it."),
    ("praise", "device", TENTATIVE_FORMULATION,
     "On this take, this was one of your more assured moments — and there "
     "is still room to improve."),
    ("rewrite", "move", DROP_THE_FILLER,
     "Try starting straight on your point, without the filler word in "
     "front of it."),
    ("rewrite", "move", SPLIT_THE_CLAUSE,
     "Try it as two shorter sentences, with a short pause where the first "
     "one ends."),
    ("rewrite", "move", REPAIR_THE_STRUCTURE,
     "Say it as one sentence, so the thought does not stop before it is "
     "finished."),
)

_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)
_STOP_RE = re.compile(r"[.!?]+")


def proposed_lines_signed() -> bool:
    """Read at call time, so a reviewed flip (or a test) is seen at once."""
    return bool(PROPOSED_LINES_SIGNED)


def floor_rows() -> list[dict]:
    """The proposed lines as catalogue rows of version 0, beneath every
    version in the table, or [] while they are unsigned."""
    if not proposed_lines_signed():
        return []
    return [{"lane": lane, "pattern_kind": kind, "pattern_key": key,
             "text": text, "version": 0, "active": True}
            for lane, kind, key, text in PROPOSED_LINES]


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD_RE.findall(text)]


def move_of(row: Any) -> Optional[str]:
    """Which of the three moves a rewrite row's own words made, or None.

    Read from the row alone, its quote against its clearer words, by the
    rules that wrote them (take_feedback_manager): the quote without its
    opening filler is ``drop_the_filler``; the same words in more sentences
    is ``split_the_clause``; the same words in fewer sentences is
    ``repair_the_structure``. A rewrite that changes the words (a model's
    stronger formulation) made none of the three. Pure; a key, never copy.
    """
    if not isinstance(row, dict) or not is_rewrite(row):
        return None
    quote, proposed = row.get("quote"), row.get("proposed_text")
    if not isinstance(quote, str) or not isinstance(proposed, str):
        return None
    quote, proposed = quote.strip(), proposed.strip()
    if not quote or not proposed or quote == proposed:
        return None
    stripped = _LEADING_FILLER_RE.sub("", quote, count=1)
    if stripped and stripped != quote \
            and stripped[0].upper() + stripped[1:] == proposed:
        return DROP_THE_FILLER
    if _words(quote) != _words(proposed):
        return None
    before = len(_STOP_RE.findall(quote))
    after = len(_STOP_RE.findall(proposed))
    if after > before:
        return SPLIT_THE_CLAUSE
    if after < before:
        return REPAIR_THE_STRUCTURE
    return None


class CatalogueRefusal(Exception):
    def __init__(self, message: str, *, code: str = "INVALID_INPUT",
                 status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _clean(value: Any, limit: int) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return text if 0 < len(text) <= limit else ""


def validate_line(body: Any) -> dict:
    """The one row an author may write, or a CatalogueRefusal naming why.

    `signed_by` is taken by the ROUTE from the authenticated caller, never
    from the body (L3)."""
    if not isinstance(body, dict):
        raise CatalogueRefusal("body must be an object")
    lane = _clean(body.get("lane"), _KEY_MAX)
    if lane not in LANES:
        raise CatalogueRefusal("lane must be praise or rewrite")
    kind = _clean(body.get("pattern_kind"), _KEY_MAX)
    if kind not in PATTERN_KINDS[lane]:
        raise CatalogueRefusal(
            f"pattern_kind for {lane} must be one of "
            f"{', '.join(PATTERN_KINDS[lane])}")
    key = _clean(body.get("pattern_key"), _KEY_MAX)
    if not key or any(ch.isspace() for ch in key):
        raise CatalogueRefusal("pattern_key is required and carries no spaces")
    text = _clean(body.get("text"), MAX_TEXT)
    if not text:
        raise CatalogueRefusal(f"text is required, at most {MAX_TEXT} characters")
    if any(ch.isdigit() for ch in text) and "%" in text:
        # A percentage in a user-facing line is a number about the speaker
        # (AC-9). Digits alone are allowed: "the last four words" is words.
        raise CatalogueRefusal("a line may not carry a percentage")
    return {"lane": lane, "pattern_kind": kind, "pattern_key": key,
            "text": text}


def newest_lines(rows: Any) -> dict[tuple[str, str, str], str]:
    """The newest ACTIVE line per (lane, kind, key). Rows in any order."""
    best: dict[tuple[str, str, str], tuple[int, str]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        key = (str(row.get("lane") or ""), str(row.get("pattern_kind") or ""),
               str(row.get("pattern_key") or ""))
        text = row.get("text")
        version = row.get("version")
        if not all(key) or not isinstance(text, str) or not text.strip():
            continue
        if isinstance(version, bool) or not isinstance(version, int):
            version = 1
        if key not in best or version > best[key][0]:
            best[key] = (version, text.strip())
    return {key: text for key, (_, text) in best.items()}


def praise_line_for(row: Any, lines: dict) -> Optional[str]:
    """The signed line behind a praise row, by its evidence."""
    if not isinstance(row, dict) or not lines:
        return None
    device = row.get("device")
    if isinstance(device, str) and device:
        line = lines.get(("praise", "device", device))
        if line:
            return line
    for cue in row.get("cue_keys") or []:
        if isinstance(cue, str):
            line = lines.get(("praise", "cue", cue))
            if line:
                return line
    return lines.get(("praise", "read", CONFIDENT_READ))


def rewrite_move_for(row: Any, lines: dict) -> Optional[str]:
    """The signed move behind a rewrite row, by its why_key; once the
    proposed lines are signed, by the move its own words made first."""
    if not isinstance(row, dict) or not lines:
        return None
    if proposed_lines_signed():
        move = move_of(row)
        line = lines.get(("rewrite", "move", move)) if move else None
        if line:
            return line
    why = row.get("why_key")
    if not isinstance(why, str) or not why:
        return None
    return lines.get(("rewrite", "move", why))


def decorate(changes: Any, catalogue_rows: Any) -> list:
    """The served rows with `praise_line` / `rewrite_move` where the
    catalogue has one. Rows are copied; nothing else on them changes. The
    signed proposed lines are the floor beneath the table's own versions."""
    lines = newest_lines([*floor_rows(), *(catalogue_rows or [])])
    out: list = []
    for row in changes or []:
        if not isinstance(row, dict) or not lines:
            out.append(row)
            continue
        if is_praise(row):
            line = praise_line_for(row, lines)
            out.append({**row, "praise_line": line} if line else row)
        elif is_rewrite(row):
            move = rewrite_move_for(row, lines)
            out.append({**row, "rewrite_move": move} if move else row)
        else:
            out.append(row)
    return out


def is_praise(row: dict) -> bool:
    """The sheet's own rule (chunkSteps.isPraiseFeedback): the praise family,
    or the impeccable read."""
    return (row.get("feedback_family") == "great_formulation"
            or row.get("device") == "impeccable")


def is_rewrite(row: dict) -> bool:
    """The sheet's own rule (paragraphOverlay.rewriteOf): the rewrite family,
    or any replace with words to propose (a legacy-lane row carries no
    family)."""
    proposed = row.get("proposed_text")
    return (row.get("feedback_family") == "rewrite_clarity"
            or (row.get("kind") == "replace"
                and isinstance(proposed, str) and bool(proposed.strip())))
