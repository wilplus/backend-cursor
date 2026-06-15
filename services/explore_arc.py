"""Explore-Session arc resolution (willab Prompt A §3, session-declared).

An "explore session" links the 3 (optional 4th) takes of the SAME talk under one
arc_id so the app can compare them. The arc is SESSION-DECLARED: minted at take 1,
then each record_again carries it. Standalone recordings have no arc (both None).

resolve_arc is pure (the uuid mint is the only effect) so it's unit-tested; the
route persists the result + reads take_count.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def resolve_arc(
    explore_session: Any,
    arc_id: Any,
    take_index: Any,
) -> tuple[Optional[str], Optional[int]]:
    """Decide this recording's (arc_id, take_index):

      • arc_id provided          → carry it + the FE-incremented take_index
        (a subsequent take of an existing arc).
      • explore_session, no arc  → MINT a fresh arc_id, take_index = 1
        (the first take of a new explore session).
      • neither                  → (None, None) — a standalone recording.
    """
    aid = arc_id.strip() if isinstance(arc_id, str) else (arc_id or None)
    if aid:
        try:
            ti = int(take_index)
        except (TypeError, ValueError):
            ti = 1
        return str(aid), max(1, ti)
    if _truthy(explore_session):
        return str(uuid.uuid4()), 1
    return None, None
