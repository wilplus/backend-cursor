"""The Life Panel day card's edits (PATCH /v2/life/day/<day_id>): checkbox
ticks and the editable content of the card.

Moved out of ``routes.life_routes`` unchanged (founder 2026-10-12). The
route keeps the auth/consent gate. The FRAME is fixed: ``one_thing`` can be
changed but never removed — blanking it is how the card quietly becomes
optional.
"""
from __future__ import annotations

from typing import Any, Optional

from services import life_engine as engine
from services import life_store as store
from services.refusal import Refusal

_EDITABLE = ("morning_checks", "one_thing", "focus_blocks",
             "distraction_flagged", "evening_habits_ran",
             "evening_one_thing", "evening_distraction", "evening_line",
             "evening_measure", "edit_why")


def _not_found() -> Refusal:
    return Refusal("NOT_FOUND", "Not found", 404)


def _invalid(error: str) -> Refusal:
    return Refusal("INVALID_INPUT", error, 400)


def _requested(body: dict) -> tuple[dict, Any]:
    fields = {k: body[k] for k in _EDITABLE if k in body}
    swap_to = body.get("one_thing_goal_id")
    if swap_to is not None and not isinstance(swap_to, str):
        raise _invalid("one_thing_goal_id: must be a goal id string")
    if not fields and not swap_to:
        raise _invalid("no fields to update")
    if "one_thing" in fields and not str(fields["one_thing"] or "").strip():
        raise _invalid("one_thing: cannot be blank — change it, don't remove it")
    return fields, swap_to


def _swapped(user_id, current, swap_to, fields) -> dict:
    """Priority is GATED, never learned: the swap names the displaced ranked
    goal for the Sunday-review counter and nothing else. An explicit text
    edit in the same call wins over the swap's default text."""
    if current is None:
        raise _not_found()
    swap_fields = engine.swap_one_thing(user_id, current, swap_to)
    if swap_fields is None:
        raise _invalid("one_thing_goal_id: not one of your active goals")
    swap_fields.update(fields)
    return swap_fields


def _record_accepted_draft(fields: dict, current: Optional[dict]) -> None:
    """Extraction/formulation are LEARNED silently: the accepted text is the
    output side of the (drafted → accepted) pair, recorded only when the
    morning actually drafted a slot."""
    if "one_thing" not in fields or current is None:
        return
    meta = dict(fields.get("draft_meta") or current.get("draft_meta") or {})
    slot = meta.get("one_thing")
    if isinstance(slot, dict):
        slot["accepted"] = str(fields["one_thing"]).strip()[:500]
        fields["draft_meta"] = meta


def _write(user_id, day_id, fields) -> Optional[dict]:
    """An unrun migration costs the record, never the edit: a write refused
    with `evening_measure` (add_life_metric_readback.sql) or `draft_meta`
    (add_life_days_draft_meta.sql) is retried without it."""
    row = store.update_day(user_id, day_id, fields)
    if row is None and "evening_measure" in fields:
        fields.pop("evening_measure")
        row = store.update_day(user_id, day_id, fields)
    if row is None and "draft_meta" in fields:
        fields.pop("draft_meta")
        row = store.update_day(user_id, day_id, fields)
    return row


def update_day_card(user_id: str, day_id: str, body: dict) -> dict:
    """Apply the edit; the updated day row. Raises ``Refusal``."""
    fields, swap_to = _requested(body)
    # Both learning-contract records need the CURRENT row: draft_meta is a
    # merge into what the morning wrote, never a blind overwrite.
    current = (store.day_by_id(user_id, day_id)
               if (swap_to or "one_thing" in fields) else None)
    if swap_to:
        fields = _swapped(user_id, current, swap_to, fields)
    _record_accepted_draft(fields, current)
    if "evening_measure" in fields:
        # Free text, capped, stored verbatim; never computed against.
        fields["evening_measure"] = (str(fields["evening_measure"]
                                         or "").strip()[:2000] or None)
    row = _write(user_id, day_id, fields)
    if not row:
        raise _not_found()
    return row
