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


PROJECT_INTENTS = frozenset({"new", "continue"})


def validate_project_intent(
    project_intent: Any,
    arc_id: Any,
    continue_arc_id: Any,
) -> tuple[Optional[str], Optional[str]]:
    """Validate the explicit project-identity contract on a recording.

    Older clients omit ``project_intent`` and retain the legacy resolver.  New
    clients must say exactly what the user did:

      * ``new`` carries no project id; :func:`resolve_arc` mints one.
      * ``continue`` carries the user-selected ``continue_arc_id``.

    Presentation bytes, slide text, topic text, and their hashes are content;
    none of them are accepted as project identity by this contract.
    """
    raw = project_intent.strip().lower() \
        if isinstance(project_intent, str) else ""
    if not raw:
        return None, None
    if raw not in PROJECT_INTENTS:
        return None, "project_intent must be 'new' or 'continue'"

    carried = arc_id.strip() if isinstance(arc_id, str) else (arc_id or None)
    selected = (continue_arc_id.strip()
                if isinstance(continue_arc_id, str)
                else (continue_arc_id or None))

    if raw == "new":
        if carried or selected:
            return None, "A new project cannot carry an existing project id"
        return raw, None

    if not selected:
        return None, "A continued project requires continue_arc_id"
    if carried and str(carried) != str(selected):
        return None, "arc_id and continue_arc_id must identify the same project"
    return raw, None


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
