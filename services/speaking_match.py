"""Matching by how you speak: each person's own switch (founder, 4 and 9
November 2026, N463 item 2, N465, N559 items 4 and 6).

Matching weighs how people speak (``services/take_match_signals.py``) only
once ``TAKE_MATCH_SKILLS`` is set, after the Terms and Privacy carry it
(N481 item 4), and then only for a person who has it on. It is opt-in, off
by default (N463 item 2): nobody's employer or team owner can turn it on for
them. The Settings card is signed (N465 item 1): "Matching by how you
speak", with "Turn off"; this module is what it calls, built before the
speaking part is switched on (N559 item 6).

  * ``status``   GET  /v2/me/speaking-match  {"on": bool, "available": bool}.
                 ``available`` says whether matching by how people speak is
                 switched on at all; the card shows only then.
  * ``turn``     POST /v2/me/speaking-match  {"on": bool}. Turning it off
                 deletes what Will learned from how they speak: the
                 speaking reads kept beside every suggestion they were in,
                 either side (``take_matches.signals``: skill, progress and
                 their gaps). Their chats stay, and so do their Takes and
                 their feedback, which are not matching's to delete.

The switch lives in the account's own ``app_metadata`` (as the waitlist flag,
``services/membership.py``), so it goes with the account and needs no table.
A lookup that fails reads as off: nobody is weighed by how they speak
unless we know they said yes. No provider call, no recording.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: The account's ``app_metadata`` key.
KEY = "speaking_match_on"
#: What matching kept of how someone speaks, beside each suggestion.
LEARNED = ("skill", "pace", "skill_gap", "pace_gap", "spans", "profile_distance",
           "other_arm_differs")


def _admin() -> Any:
    from services.db import new_client
    return new_client().auth.admin


def is_on(user_id: Any) -> bool:
    """Has this person turned matching by how they speak on? A failure is
    off."""
    if not user_id:
        return False
    try:
        user = _admin().get_user_by_id(str(user_id)).user
        return bool((getattr(user, "app_metadata", None) or {}).get(KEY))
    except Exception:  # noqa: BLE001 -- unknown is off
        logger.warning("speaking_match: no answer for %s; reading it as off", user_id, exc_info=True)
        return False


def allowed(user_ids: Iterable[str]) -> set[str]:
    """Those of ``user_ids`` who have it on."""
    return {str(u) for u in user_ids if is_on(u)}


def status(user_id: Any) -> dict:
    from services import take_match_signals as signals
    return {"on": is_on(user_id), "available": signals.is_on()}


def forget(database: Any, user_id: str) -> int:
    """Delete what matching learned from how this person speaks: the
    speaking reads kept beside each suggestion they were in. Returns how
    many suggestions were cleaned."""
    from services.chats import _rows, _table
    from services.take_match import MATCHES, MAX_ROWS
    cleaned = 0
    for side in ("speaker_id", "candidate_id"):
        for row in _rows(_table(database, MATCHES).select("id,signals")
                         .eq(side, user_id).limit(MAX_ROWS)):
            kept = dict(row.get("signals") or {})
            if not set(kept) & set(LEARNED):
                continue
            _table(database, MATCHES).update(
                {"signals": {k: v for k, v in kept.items() if k not in LEARNED}}) \
                .eq("id", str(row["id"])).execute()
            cleaned += 1
    return cleaned


def turn(database: Any, user_id: Any, on: Any) -> dict:
    """Turn it on or off for the caller; off deletes what was learned."""
    from services.chats import ChatsError
    if not isinstance(on, bool):
        raise ChatsError("BAD_REQUEST", "Say on or off.", 400)
    who = str(user_id)
    try:
        user = _admin().get_user_by_id(who).user
        meta = dict(getattr(user, "app_metadata", None) or {})
        meta[KEY] = on
        meta[f"{KEY}_at"] = datetime.now(timezone.utc).isoformat()
        _admin().update_user_by_id(who, {"app_metadata": meta})
    except Exception as e:  # noqa: BLE001 -- the card says it did not work
        logger.error("speaking_match: could not turn %s %s", who, "on" if on else "off",
                     exc_info=True)
        raise ChatsError("UNAVAILABLE", "Please try again.", 503) from e
    if not on:
        forget(database, who)
    return status(who)
