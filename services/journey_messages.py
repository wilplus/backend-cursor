"""Durable three-take journey messages and their idempotency keys."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional


_NAMESPACE = uuid.UUID("c0af92c8-758e-4c31-9c6e-f6d36bd52395")

_COPY = {
    1: (
        "Your first talk track is ready.\n\n"
        "We’ve seen what already works and where the message needs more clarity. "
        "Now let’s focus on how it sounds and lands.\n\n"
        "Use the orange-marked text as your anchors - not a script - and try "
        "to speak as to a friend."
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
        "to speak as to a friend.\n\n"
        "You can present, export your notes, or keep practising."
    ),
}

_ACTIONS = {
    1: ["prepare_take_2"],
    2: ["prepare_take_3"],
    3: ["presentation_mode", "export", "keep_practising"],
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
