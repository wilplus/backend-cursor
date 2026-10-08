"""Which signed line to say next (build plan D-FW-3; founder lock
2026-10-06, the Feedback walk, "Line bank"; docs/SIGNED-line-bank-2026-10-06.md
"Rotation").

The signed file's rule, in three parts, all kept here:

  * within one bank the same line is never shown twice in a row, for one
    speaker, across reloads, Takes and devices: the memory is
    ``line_bank_memory`` (0438), and ``pick_line_bank_line_v1`` decides
    and records the next index in one call under the row's lock;
  * a "later" line shows only from Take 2 on, with the real Take number,
    and only when it is true: the cue its bank names was measurably weaker
    on the earlier Take (``later_is_true``);
  * nothing is invented: the line is an index into the signed bank
    (``services.line_bank``), and the only number a line can carry is the
    Take number (AC-9).

WHAT "MEASURABLY WEAKER THEN" MEANS is after_practice's bar, unchanged: the
cue moved toward confident by at least ``CUE_GAIN_MIN`` within-speaker z
between the earlier Take's read and this Take's (``after_practice.cue_gains``
over two ``cue_reads`` dicts against one baseline). A bank that names one
cue (B02 to B08) needs that cue; B01 (sounded surer, no single cue) and B09
(the gentle line) need at least one cue that moved that far. No read on
either side is never true.

The caller supplies the two reads and the two Take numbers (D-FW-4 wires
the Manager rows); this module only decides and remembers. A choice is
``{"bank", "index"}`` or ``{"bank", "later_take"}``: keys, never free text.
``say`` renders one from the signed bank.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.line_bank import BANKS, LATER, bank_for_cue, later_line, line

_log = logging.getLogger(__name__)

#: The index the memory records for a bank's later line.
LATER_INDEX = -1


def _take(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def later_is_true(bank: str, *, take_index: Any, earlier_take_index: Any,
                  reads_now: Any, reads_then: Any) -> bool:
    """True only when the bank has a later line, this is Take 2 or later,
    the earlier Take is a real earlier one, and the bank's cue was
    measurably weaker on it. Pure."""
    from services.after_practice import cue_gains

    now, then = _take(take_index), _take(earlier_take_index)
    if bank not in LATER or now is None or then is None:
        return False
    if now < 2 or not 1 <= then < now:
        return False
    moved = {key for key, _gain in cue_gains(reads_then, reads_now)}
    if not moved:
        return False
    if bank in ("B01", "B09"):
        return True
    return any(bank_for_cue(key) == bank for key in moved)


def pick(database: Any, *, user_id: str, bank: str, take_index: Any = None,
         earlier_take_index: Any = None, reads_now: Any = None,
         reads_then: Any = None) -> Optional[dict]:
    """The next line of ``bank`` for this speaker, recorded as shown.

    ``{"bank", "index"}`` for an ordinary line, never the index shown just
    before in this bank; ``{"bank", "later_take"}`` for the later line,
    when ``later_is_true`` and the line shown just before was not that
    same later line. None when the bank is unknown or the memory cannot
    answer: without it the rule cannot be kept, and the caller says no
    bank line rather than one that might repeat."""
    if bank not in BANKS or not str(user_id or ""):
        return None
    later = later_is_true(bank, take_index=take_index,
                          earlier_take_index=earlier_take_index,
                          reads_now=reads_now, reads_then=reads_then)
    try:
        index = database.pick_line_bank_line(
            user_id=str(user_id), bank=bank, size=len(BANKS[bank]),
            later_true=later)
    except Exception as error:  # noqa: BLE001 -- logged; no line rather than a repeat
        _log.warning("line bank pick failed bank=%s: %s", bank, type(error).__name__)
        return None
    if index == LATER_INDEX and later:
        return {"bank": bank, "later_take": _take(earlier_take_index)}
    if isinstance(index, int) and 0 <= index < len(BANKS[bank]):
        return {"bank": bank, "index": index}
    _log.warning("line bank pick out of range bank=%s", bank)
    return None


def say(choice: Any) -> Optional[str]:
    """The signed words of a choice, or None for anything else."""
    if not isinstance(choice, dict) or choice.get("bank") not in BANKS:
        return None
    bank = str(choice["bank"])
    if "later_take" in choice:
        take = _take(choice.get("later_take"))
        if bank not in LATER or take is None or take < 1:
            return None
        return later_line(bank, take)
    index = _take(choice.get("index"))
    if index is None or not 0 <= index < len(BANKS[bank]):
        return None
    return line(bank, index)


# --- The walk's screens (D-FW-3 wired, 2026-10-08) -------------------------
#
# The Feedback walk draws its bank lines on the speaker's screen, where a
# screen must not wait on a call (walk lock: nothing blinks). So the walk
# reads, once as it opens, the index each bank would say next (``upcoming``:
# exactly what ``pick`` would answer with no later line, without recording
# it), shows that line, and records it as shown when its screen comes on
# (``shown``, through ``pick``, under the row's lock). The two agree unless
# another device said a line of the same bank in between, and then the next
# read follows the memory again. The walk never claims a later line: it has
# no reads to prove one true, so ``shown`` passes none.


def upcoming(database: Any, *, user_id: str) -> dict[str, int]:
    """{bank: index of the ordinary line it says next} for every signed
    bank, for this speaker; {} when the memory cannot be read (the walk then
    keeps its own turn). Indexes only (AC-9). Records nothing."""
    if not str(user_id or ""):
        return {}
    try:
        rows = database.read_line_bank_memory(user_id=str(user_id))
    except Exception as error:  # noqa: BLE001 -- logged; the walk keeps its own turn
        _log.warning("line bank memory read failed: %s", type(error).__name__)
        return {}
    last: dict[str, Optional[int]] = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("bank") in BANKS:
            last[str(row["bank"])] = _take(row.get("last_plain_index"))
    out: dict[str, int] = {}
    for bank, lines in BANKS.items():
        plain = last.get(bank)
        out[bank] = 0 if plain is None or not 0 <= plain < len(lines) else (plain + 1) % len(lines)
    return out


def shown(database: Any, *, user_id: str, body: Any) -> tuple[int, dict]:
    """The walk showed a line of ``body["bank"]``: record it as the line
    said (``pick`` with no later line). Returns (status, body):
    200 {"bank", "index"} with the index recorded; 400 INVALID_INPUT for an
    unknown bank; 503 when the memory cannot record it."""
    bank = body.get("bank") if isinstance(body, dict) else None
    if not isinstance(bank, str) or bank not in BANKS:
        return 400, {"code": "INVALID_INPUT", "error": "bank must be a signed bank"}
    choice = pick(database, user_id=user_id, bank=bank)
    if choice is None or "index" not in choice:
        return 503, {"code": "V2_ERROR", "error": "Could not save."}
    return 200, {"bank": bank, "index": choice["index"]}
