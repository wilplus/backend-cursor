"""Explore-Session arc resolution (willab Prompt A §3 / always-on 2026-06-17).

An "explore session" links the 3 (optional 4th) takes of the SAME talk under one
arc_id so the app can compare them. ALWAYS-ON (founder): there's no opt-in toggle
anymore — EVERY fresh Lab recording starts a 3-take arc, and the chat cadence
guides the takes. The arc is minted at take 1, then each record_again carries it.

resolve_arc is pure (the uuid mint is the only effect) so it's unit-tested; the
route persists the result + reads take_count.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional


def resolve_arc(
    explore_session: Any,
    arc_id: Any,
    take_index: Any,
) -> tuple[Optional[str], Optional[int]]:
    """Decide this recording's (arc_id, take_index):

      • arc_id provided → carry it + the FE-incremented take_index (a
        subsequent take of an existing arc).
      • no arc_id       → MINT a fresh arc_id, take_index = 1 (the first take of
        a new arc). ALWAYS — there is no standalone path anymore.

    ``explore_session`` is accepted for back-compat but no longer gates anything
    (the 3-take flow is the default; the FE removed the opt-in toggle).
    """
    aid = arc_id.strip() if isinstance(arc_id, str) else (arc_id or None)
    if aid:
        try:
            ti = int(take_index)
        except (TypeError, ValueError):
            ti = 1
        return str(aid), max(1, ti)
    # Always-on: a fresh recording is take 1 of a new arc.
    return str(uuid.uuid4()), 1
