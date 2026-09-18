"""Owner response to a Confident Voice moment — routing only."""
from __future__ import annotations

from typing import Any, Optional


RESPONSES = ("yes", "no", "neutral", "unrateable")

# The five states the instrument asks for (contract §29). Stored whole: an
# in-between, a not-sure and an audio-unclear are three different self-reports,
# and folding any of them into `no` or into each other would destroy exactly
# the distinction the question exists to capture.
#
# Only `yes` ever satisfies the Voice Album's USER leg — the other four are
# answers, not weaker yeses.
FIVE_STATES = ("yes", "in_between", "no", "not_sure", "audio_unclear")


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


def five_state_response(payload: Any) -> tuple[Optional[str], Optional[str]]:
    """Validate a standalone Confident Voice answer ("Practice new").

    No coercion and no aliasing: the answer is stored as given, or rejected.
    The legacy `neutral` / `unrateable` values are audit-only and are NOT
    accepted here, so a new write can never land on a retired vocabulary.
    """
    if not isinstance(payload, dict):
        return None, "body: must be an object"
    value = payload.get("response")
    if value not in FIVE_STATES:
        return None, "response: must be one of " + ", ".join(FIVE_STATES)
    return value, None
