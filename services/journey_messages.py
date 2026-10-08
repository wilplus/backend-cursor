"""Durable three-take journey messages and their idempotency keys.

The Lounge's bubble after each of the first three Takes. Its actions are
the doors the bubble offers (the frontend labels them from the signed copy):

- ``prepare_take_2`` / ``prepare_take_3``: the next Take (J4).
- ``export``: export the notes (Take 3).
- ``keep_practising`` ("Practise again", N48.3 Q8 A): after Takes 1, 2
  and 3 (founder 2026-10-06, QA9 A, N51.5; ledger A019a), not Take 3 alone.

``presentation_mode`` is no longer emitted (J5, N37.4): the ⋯ menu is
Presentation Mode's only door. The Take 3 copy lost its last sentence
("You can present, export your notes, or keep practising.") per Q-B15 A
(N62); every other word is as signed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional


_NAMESPACE = uuid.UUID("c0af92c8-758e-4c31-9c6e-f6d36bd52395")

_COPY = {
    1: (
        "We have successfully registered your first take 🎉\n\n"
        "You have recorded some of the helper words and recognized your "
        "confident moments.\n\n"
        "Use the helper words and record the second take of your presentation ⬇️"
    ),
    2: (
        "Your presentation is stronger now.\n\n"
        "We’ve seen your message become clearer. Now let’s focus on making the "
        "delivery feel natural and confident.\n\n"
        "Use the orange-marked text as your anchors - not a script - and try "
        "to speak as to a friend."
    ),
    3: (
        "Your presentation is ready.\n\n"
        "We’ve seen your message become much more clear and your delivery grow "
        "more natural across three takes.\n\n"
        "Use the orange-marked text as your anchors - not a script - and try "
        "to speak as to a friend."
    ),
}

_ACTIONS = {
    1: ["prepare_take_2", "keep_practising"],
    2: ["prepare_take_3", "keep_practising"],
    3: ["export", "keep_practising"],
}


def journey_client_id(user_id: Any, arc_id: Any, take_index: Any) -> str:
    return str(uuid.uuid5(
        _NAMESPACE, f"{user_id}:{arc_id}:take:{int(take_index)}:next-steps"
    ))


def journey_message(user_id: Any, arc_id: Any, take_index: Any) -> Optional[dict]:
    try:
        take = int(take_index)
    except (TypeError, ValueError):
        return None
    if take not in _COPY:
        return None
    return {
        "client_id": journey_client_id(user_id, arc_id, take),
        "role": "bot",
        "kind": "cadence",
        "body": _COPY[take],
        "metadata": {
            "journey": True,
            "arc_id": str(arc_id),
            "take_index": take,
            "actions": list(_ACTIONS[take]),
        },
        "client_created_at": datetime.now(timezone.utc).isoformat(),
    }


def journey_seen(database, user_id: Any, arc_id: Any, take_index: Any) -> bool:
    try:
        if int(take_index) not in _COPY:
            return True
        client_id = journey_client_id(user_id, arc_id, take_index)
        return bool(database.get_lounge_message_by_client_id(
            str(user_id), client_id
        ))
    except Exception:
        return False
