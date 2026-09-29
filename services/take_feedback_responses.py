"""Validation for immutable user responses to the frozen Take feedback set."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from services.canonical_product import OWNER_RESPONSES


# One vocabulary for every module (audit D2): see OWNER_RESPONSES.
RESPONSES = OWNER_RESPONSES


def album_routing_for(response: str) -> str:
    """The Voice Album routing value for a Confident Voice answer: the answer.

    F-4 (audit 2026-09-22). The Take-review route used to derive the stored
    routing inline and fold in_between and not_sure into ``neutral`` and
    audio_unclear into ``unrateable`` on the way to
    ``owner_voice_album_routing``, so two different things a speaker said
    became one record, on every Confident Voice answer, after the table's
    CHECK had already been widened to the five states (0341). The one
    derivation now lives here and keeps the five apart. Only ``yes`` ever
    satisfies the Album's USER leg, so nothing downstream changes meaning.
    """
    if response not in RESPONSES["confident_voice"]:
        raise ValueError(f"not a Confident Voice answer: {response!r}")
    return response


def parse_feedback_response(
    body: Any,
) -> tuple[Optional[dict], Optional[str]]:
    """Validate the typed answer without making a membership decision.

    Membership belongs to the database transaction that appends the immutable
    report. Keeping this parser independent prevents the HTTP route from doing
    a stale read followed by a separate write.
    """
    if not isinstance(body, dict):
        return None, "body must be an object"
    feedback_id = body.get("feedback_id")
    family = body.get("feedback_family")
    response = body.get("response")
    if (not isinstance(feedback_id, str) or not feedback_id.strip()
            or not isinstance(family, str) or not family.strip()
            or not isinstance(response, str) or not response.strip()):
        return None, "feedback_id, feedback_family and response are required"
    feedback_id, family, response = (
        feedback_id.strip(), family.strip(), response.strip()
    )
    if family not in RESPONSES or response not in RESPONSES[family]:
        return None, "response is not valid for this feedback family"
    supplied_snippet = body.get("snippet_id")
    if supplied_snippet is not None:
        supplied_snippet = str(supplied_snippet).strip() or None
    exact_identity = {
        "candidate_id": body.get("candidate_id"),
        "feedback_membership_id": body.get("feedback_membership_id"),
        "feedback_exposure_id": body.get("feedback_exposure_id"),
    }
    supplied_identity_count = sum(
        value is not None for value in exact_identity.values()
    )
    if supplied_identity_count not in (0, len(exact_identity)):
        return None, "complete canonical feedback identity is required"
    if supplied_identity_count:
        try:
            exact_identity = {
                key: str(uuid.UUID(str(value)))
                for key, value in exact_identity.items()
            }
        except (TypeError, ValueError):
            return None, "canonical feedback identity must contain UUIDs"
    else:
        exact_identity = {}
    return {
        "feedback_id": feedback_id,
        "feedback_family": family,
        "response": response,
        "snippet_id": supplied_snippet,
        **exact_identity,
    }, None


