"""Validation for immutable user responses to the frozen Take feedback set."""
from __future__ import annotations

from typing import Any, Optional


RESPONSES = {
    "confident_voice": {
        "yes", "in_between", "no", "not_sure", "audio_unclear",
    },
    "rewrite_clarity": {
        "apply_suggestion", "edit_myself", "keep_wording",
    },
    "great_formulation": {"useful", "not_useful", "not_sure"},
}


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
    return {
        "feedback_id": feedback_id,
        "feedback_family": family,
        "response": response,
        "snippet_id": supplied_snippet,
    }, None


def validate_feedback_response(
    body: Any, selected_keys: Any,
) -> tuple[Optional[dict], Optional[str]]:
    """Compatibility validator for callers/tests holding a frozen snapshot."""
    parsed, err = parse_feedback_response(body)
    if err or parsed is None:
        return None, err
    feedback_id = parsed["feedback_id"]
    family = parsed["feedback_family"]
    member = next((
        key for key in (selected_keys or [])
        if isinstance(key, dict)
        and str(key.get("id") or "") == feedback_id
        and str(key.get("feedback_family") or "") == family
    ), None)
    if member is None:
        return None, "feedback item is not in this Take's frozen set"
    supplied_snippet = parsed.get("snippet_id")
    member_snippet = str(member.get("snippet_id") or "") or None
    if supplied_snippet is not None:
        if supplied_snippet != member_snippet:
            return None, "snippet provenance does not match the feedback item"
    return {
        "feedback_id": feedback_id,
        "feedback_family": family,
        "response": parsed["response"],
        "snippet_id": member_snippet,
    }, None
