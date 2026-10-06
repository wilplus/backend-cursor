"""The machine checks each practise try (founder lock 2026-10-06, the
Feedback walk; decisions log N52.3), dark behind
``Config.MACHINE_PRACTICE_CHECK_ENABLED``.

The founder: "don't ask me right away does my last take sound confident to
me, you need to check it yourself". After each try the machine decides one
of two things, never a number (AC-9):

  - ``praise``: the try is measurably better. The loop ends on this try,
    the helper words are tapped from its words, then the walk goes on.
  - ``again``: not yet. The encouragement and another try, until praise
    or Skip. There is no cap (lock D2; CM3 is still open).

WHAT "MEASURABLY BETTER" MEANS is after_practice's rule, unchanged, read
on the try just made (its lanes 1 to 3 against the original clip): the
targeted problem cleared, a delivery cue moved toward confident by at least
``CUE_GAIN_MIN`` within-speaker z, or the machine leg reads higher. Lane 4
("nothing") is ``again``.

A REWRITE PRACTICE (29b) says new words, so the original clip is never its
yardstick (founder 2026-10-01). Saying the accepted words is the practise:
its first try is ``praise``. A later try is ``praise`` too, named by the
cue that moved since the previous try when one did.

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

RULE_VERSION = "practice-check-v1"
#: The two outcomes. Nothing else is ever decided.
NEXT = ("praise", "again")
#: The after_practice lanes that count as measurably better.
_BETTER_LANES = frozenset({"cleared", "cue", "machine_leg"})


def machine_practice_check_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "MACHINE_PRACTICE_CHECK_ENABLED", False))


def _index(row: Mapping) -> int:
    return int(row.get("attempt_index") or 0)


def decide(practice: Any, attempts: Iterable[Any], attempt_id: Any) -> dict:
    """The decision for one try. Pure.

    {"next", "key", "lane", "attempt_id", "attempt_index", "rule_version",
     "decided_by"}; ``key`` names the praise line on ``praise`` and the
    encouragement ("step" or "effort") on ``again``."""
    from services.after_practice import (
        _original_praise, _rewrite_praise, encouragement,
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
    step = encouragement(upto)
    return {**base, "next": "again", "key": step["key"], "lane": "none"}


def checkable_attempt(attempts: list) -> Optional[dict]:
    """The latest try, the only one the machine may decide."""
    if not attempts:
        return None
    return max(attempts, key=_index)


def check_attempt(database: Any, practice: Mapping, attempt_id: str,
                  owner_user_id: str) -> tuple[int, dict]:
    """Decide the latest try and, on praise, close the practice on it.

    Returns (status, body) like ``practice_adoption.judge_attempt``:
    ``outcome`` is "done" on praise and "again" otherwise, so the walk
    reads it the same way; ``check`` is the decision the walk shows."""
    from services.practice_adoption import practice_words

    if practice.get("status") != "open":
        return 409, {"code": "PRACTICE_CLOSED",
                     "error": "This practice is already closed."}
    attempts = database.list_confident_voice_practice_attempts(
        str(practice.get("id")))
    target = checkable_attempt(attempts)
    if target is None or str(target.get("id")) != str(attempt_id):
        return 409, {"code": "NOT_CHECKABLE",
                     "error": "Check your latest attempt."}
    check = decide(practice, attempts, attempt_id)
    result: dict = {"outcome": "done" if check["next"] == "praise" else "again",
                    "check": public_check(check), "attempt_transcript": None,
                    "practice_row": practice}
    fields: dict = {"after_practice": check}
    if check["next"] == "praise":
        fields.update({
            "status": "completed",
            "selected_attempt_id": str(attempt_id),
            # Where the speaker landed, for reading only (F7); the
            # scorekeeper still reads the first valid attempt.
            "landed_attempt_index": target.get("attempt_index"),
            "closed_at": datetime.now(timezone.utc).isoformat(),
        })
    updated = database.update_confident_voice_practice(
        str(practice.get("id")), owner_user_id, fields)
    if updated is None:
        return 500, {"code": "V2_ERROR", "error": "Could not save."}
    result["practice_row"] = updated
    if check["next"] == "praise":
        result["attempt_transcript"] = practice_words(target.get("transcript"))
        # Phase 5: the closed practice's pair for the delayed measure (off,
        # nothing). The endpoint is the first valid attempt, not this one.
        from services.delayed_measure import enrol
        enrol(database, updated)
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
