"""Owner response to a Confident Voice moment — routing only."""
from __future__ import annotations

from typing import Any, Optional


RESPONSES = ("yes", "no", "neutral", "unrateable")


def validate_owner_voice_album_route(
    payload: Any,
) -> tuple[Optional[dict], Optional[str]]:
    """Validate the legacy ``{ai_correct: bool, model_version?: str}`` wire."""
    if not isinstance(payload, dict):
        return None, "body: must be an object"
    ai_correct = payload.get("ai_correct")
    if not isinstance(ai_correct, bool):
        return None, "ai_correct: required, must be true or false"
    version = payload.get("model_version")
    if version is not None and not isinstance(version, str):
        return None, "model_version: must be a string when present"
    version = version.strip() if isinstance(version, str) else None
    return {
        "response": "yes" if ai_correct else "no",
        "ai_correct": ai_correct,
        "model_version": version or None,
    }, None


def routing_response_from_rating(payload: Any) -> tuple[Optional[str], Optional[str]]:
    """Validate the current ternary UI without creating a rating row.

    ``unrateable`` is an abstention and therefore a routing state of its own;
    it is never coerced into disagreement.
    """
    if not isinstance(payload, dict):
        return None, "body: must be an object"
    if payload.get("unrateable") is True:
        if payload.get("value") not in (None, ""):
            return None, "value and unrateable are mutually exclusive"
        return "unrateable", None
    value = payload.get("value")
    if value not in ("yes", "no", "neutral"):
        return None, "value: must be yes, no, or neutral"
    return value, None
