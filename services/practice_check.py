"""The machine checks each practise try (founder lock 2026-10-06, the
Feedback walk; decisions log N52.3). On; the switch was deleted 2026-10-11.

The founder: "don't ask me right away does my last take sound confident to
me, you need to check it yourself". After each try the machine decides one
of three things, never a number (AC-9):

  - ``praise``: the try is measurably better. The loop ends on this try,
    the helper words are tapped from its words, then the walk goes on.
  - ``again``: not yet. The encouragement and another try, until praise,
    Skip, or the third try.
  - ``moved_on``: the third try that is not praise (CM3a A: up to three
    tries; CM3b A, decisions log N55). The loop stops: the practice closes
    with no try selected, so no helper words are tapped from it and its
    bar clears, and the walk moves on to "Judgement time!" with a CM3b
    line. Praise on the third try still wins.

WHAT "MEASURABLY BETTER" MEANS is after_practice's rule, unchanged, read
on the try just made (its lanes 1 to 3 against the original clip): the
targeted problem cleared, a delivery cue moved toward confident by at least
``CUE_GAIN_MIN`` within-speaker z, or the machine leg reads higher. Lane 4
("nothing") is ``again``.

A REWRITE PRACTICE (29b) says new words, so the original clip is never its
yardstick (founder 2026-10-01). Saying the accepted words is the practise:
its first try is ``praise``. A later try is ``praise`` too, named by the
cue that moved since the previous try when one did.

A "NOT YET" NAMES WHAT WENT THE WRONG WAY (founder 2026-10-13, option A):
the cue that moved furthest away from confident against the original clip,
read on the same within-speaker baseline as the praise, past the same
``CUE_GAIN_MIN``; when none did, the general line. The reads are made when
the try uploads, so the check waits on nothing new.

PROVENANCE (L3). This is a machine decision about one try. It is never
written as the speaker's answer (``user_answer``, ``final_user_answer``),
never a label, and never reaches the coach as the speaker's side. The
speaker's own Voice Album answer is asked later, at "Judgement time!".

What leaves the server is ``next`` and the key of the line to say (the
words come from the signed line bank); no score, cue value or lane number.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

RULE_VERSION = "practice-check-v3"
#: The three outcomes. Nothing else is ever decided.
NEXT = ("praise", "again", "moved_on")
#: CM3a A: the loop stops after the third try that is not praise. Since
#: 2026-10-16 (founder, the Exercise screen as one thread) a praise no longer
#: ends the loop either: the speaker may try until three tries in all,
#: whatever the answers; the praise stands (see ``takes_more_tries``).
TRY_CAP = 3
#: The signed bank said when it does (CM3b A, N55; services/line_bank.py).
MOVED_ON_KEY = "CM3b"
#: The after_practice lanes that count as measurably better.
_BETTER_LANES = frozenset({"cleared", "cue", "machine_leg"})


def _index(row: Mapping) -> int:
    return int(row.get("attempt_index") or 0)


def decide(practice: Any, attempts: Iterable[Any], attempt_id: Any) -> dict:
    """The decision for one try. Pure.

    {"next", "key", "lane", "attempt_id", "attempt_index", "rule_version",
    "decided_by"}; ``key`` names the praise line on ``praise``, the reading
    that went the wrong way on ``again`` (``miss:<cue key>``, else
    ``effort``), and the signed CM3b line on ``moved_on``."""
    from services.after_practice import (
        _original_praise, _reads, _rewrite_praise, cue_drops,
    )
    rows = [r for r in attempts if isinstance(r, Mapping)]
    tried = next((r for r in rows if str(r.get("id")) == str(attempt_id)), None)
    base = {"rule_version": RULE_VERSION, "decided_by": "machine",
            "attempt_id": str(attempt_id),
            "attempt_index": _index(tried) if tried else None}
    if tried is None:
        return {**base, "next": "again", "key": "effort", "lane": "none"}
    if str((practice or {}).get("kind") or "exercise") == "rewrite":
        said = _rewrite_praise(rows, dict(tried), "yes", {})
        return {**base, "next": "praise", "key": said["key"], "lane": said["lane"]}
    said = _original_praise(practice, dict(tried), "yes", {})
    if said.get("lane") in _BETTER_LANES:
        return {**base, "next": "praise", "key": said["key"], "lane": said["lane"]}
    upto = [r for r in rows if _index(r) <= _index(tried)]
    if len(upto) >= TRY_CAP:
        return {**base, "next": "moved_on", "key": MOVED_ON_KEY, "lane": "none"}
    # Option A (founder 2026-10-13): name the reading that went furthest the
    # wrong way against the original clip; none clearly moved: the general.
    drops = cue_drops(_reads(tried, "original"), _reads(tried, "attempt"))
    key = f"miss:{drops[0][0]}" if drops else "effort"
    return {**base, "next": "again", "key": key, "lane": "none"}


def checkable_attempt(attempts: list) -> Optional[dict]:
    """The latest try, the only one the machine may decide."""
    if not attempts:
        return None
    return max(attempts, key=_index)


def takes_more_tries(practice: Mapping, tries_made: int) -> bool:
    """Whether one more try may be recorded and checked after ``tries_made``
    (founder 2026-10-16, the Exercise screen as one thread): while the
    practice is open, and after the machine closed it on a praise until
    three tries in all. A practice the speaker closed, or that moved on,
    takes none."""
    if practice.get("status") == "open":
        return True
    return machine_closed(practice) and tries_made < TRY_CAP


def check_attempt(database: Any, practice: Mapping, attempt_id: str,
                  owner_user_id: str) -> tuple[int, dict]:
    """Decide the latest try; on praise close the practice on it, on
    moved_on close it with no try selected.

    Returns (status, body) like ``practice_adoption.judge_attempt``:
    ``outcome`` is "done" on praise, "moved_on" when the loop stopped at the
    third try, and "again" otherwise; ``check`` is the decision the walk
    shows. A moved-on practice keeps no ``selected_attempt_id`` and no
    answer, so ``machine_closed`` stays False (no helper words), the
    moment settles like a Skip and its bar clears.

    After a praise the speaker may still try, up to three tries in all
    (founder 2026-10-16). A later praise is the try the practice lands on;
    a later "not yet" or third try changes nothing stored: the earlier
    praise stands, so the helper words tapped from it stay."""
    from services.practice_adoption import practice_words

    attempts = database.list_confident_voice_practice_attempts(
        str(practice.get("id")))
    if not takes_more_tries(practice, len(attempts) - 1):
        return 409, {"code": "PRACTICE_CLOSED",
                     "error": "This practice is already closed."}
    target = checkable_attempt(attempts)
    if target is None or str(target.get("id")) != str(attempt_id):
        return 409, {"code": "NOT_CHECKABLE",
                     "error": "Check your latest attempt."}
    check = decide(practice, attempts, attempt_id)
    outcome = {"praise": "done", "moved_on": "moved_on"}.get(check["next"], "again")
    result: dict = {"outcome": outcome,
                    "check": public_check(check), "attempt_transcript": None,
                    "practice_row": practice}
    praised_before = machine_closed(practice)
    fields: dict = {} if praised_before else {"after_practice": check}
    if check["next"] == "moved_on" and not praised_before:
        fields.update({
            "status": "completed",
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })
    if check["next"] == "praise":
        fields.update({
            "after_practice": check,
            "status": "completed",
            "selected_attempt_id": str(attempt_id),
            # Where the speaker landed, for reading only (F7); the
            # scorekeeper still reads the first valid attempt.
            "landed_attempt_index": target.get("attempt_index"),
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })
    updated = database.update_confident_voice_practice(
        str(practice.get("id")), owner_user_id, fields) if fields else dict(practice)
    if updated is None:
        return 500, {"code": "V2_ERROR", "error": "Could not save."}
    result["practice_row"] = updated
    if check["next"] == "praise":
        result["attempt_transcript"] = practice_words(target.get("transcript"))
    return 200, result


def public_check(check: Mapping) -> dict:
    """What the speaker's screen may see: the outcome and the line's key.
    No lane, no cue value, no index of anything measured (AC-9)."""
    return {"next": check.get("next"), "key": check.get("key")}


def machine_closed(practice: Mapping) -> bool:
    """A practice the machine closed on a praised try (the helper words may
    be tapped from it, like a Yes or In-between one)."""
    said = practice.get("after_practice")
    return (practice.get("status") == "completed"
            and isinstance(said, Mapping)
            and said.get("decided_by") == "machine"
            and said.get("next") == "praise")
