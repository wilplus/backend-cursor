"""The coach's side of a moment no exercise fitted (founder 2026-09-28).

Since D1 an exercise is offered only when a detected problem fired on the clip
and something in the library targets it. When a bookmark the speaker judged
has nothing, ``services.judgement_follow_up`` records one request per (Take,
moment) (migration 0385; founder 2026-09-29: every bookmark, at judgement). This module is what the coach does with
it, reached only through the route's blind gate: the coach has already rated
the moment themselves before any of this is revealed (contract 35f).

Three resolutions, each recorded once:

  * ``exercise_chosen``   — an active library exercise;
  * ``exercise_authored`` — one the coach files into the library now. It goes
    through the same catalogue validation as every exercise, so it must name a
    problem code can detect, and it becomes reusable for any speaker whose
    clip shows that problem — the coach's teaching, not a verdict about one
    person (L3);
  * ``no_safe_match``     — nothing suitable exists.

Sharing with the speaker is a separate tick and only an exercise can be
shared. A shared exercise then rides on that same item for the speaker.
"""
from __future__ import annotations

from typing import Any, Optional

RESOLUTIONS = ("exercise_chosen", "exercise_authored", "no_safe_match")

_REFUSALS = {
    "EXERCISE_COACH_REQUEST_ALREADY_RESOLVED": (
        409, "This moment already has your answer; it cannot be changed."),
    "EXERCISE_COACH_REQUEST_NOT_FOUND": (404, "request not found"),
    "EXERCISE_COACH_REQUEST_INPUT_INVALID": (400, "That answer is not valid."),
}


def _error(status: int, code: str, message: str) -> tuple[int, dict]:
    return status, {"code": code, "error": message}


def _labels(database: Any) -> dict:
    rows = (database.list_speaking_errors() or []
            if hasattr(database, "list_speaking_errors") else [])
    return {str(r.get("error_id")): r.get("label")
            for r in rows if isinstance(r, dict) and r.get("error_id")}


def coach_request_payload(request: dict, database: Any) -> dict:
    """What the coach sees AFTER their blind rating. Coach-only: the need
    evidence may be revealed now (35f), never to the speaker."""
    from services.confident_voice_practice import coach_exercise_order
    from services.exercise_pick_view import request_candidates
    trace = request.get("request_trace")
    signals = trace.get("signals") if isinstance(trace, dict) else None
    labels = _labels(database)
    assignment = (database.get_confident_voice_exercise_assignment(
        str(request.get("take_session_id")), str(request.get("snippet_id")))
        if hasattr(database, "get_confident_voice_exercise_assignment")
        else None)
    ordered = coach_exercise_order({
        "machine_assessment": {"pattern": request.get("pattern")},
        "acoustic_evidence": {"signals": signals},
    }, database)
    return {
        "id": str(request.get("id")),
        "take_session_id": str(request.get("take_session_id")),
        "snippet_id": str(request.get("snippet_id")),
        "reason": request.get("reason"),
        "spotted": [{"error_id": tag, "label": labels.get(tag) or tag}
                    for tag in request.get("observed_tags") or []],
        "created_at": request.get("created_at"),
        "resolution": request.get("resolution"),
        "resolved_exercise_id": request.get("resolved_exercise_id"),
        "resolved_at": request.get("resolved_at"),
        "shared_at": request.get("shared_at"),
        # The library has since gained a fitting exercise and the speaker was
        # offered it: a share from here would not reach them.
        "offered_since": isinstance(assignment, dict),
        # Why nothing fitted: every exercise and its reason (step 6).
        "candidates": request_candidates(request),
        "available_exercises": [{
            "exercise_id": row.get("exercise_id"),
            "version": row.get("version"),
            "title": row.get("title"),
            "instruction": row.get("instruction"),
            "explanation_video_ref": row.get("explanation_video_url"),
        } for row in ordered],
    }


def _exercise_for(database: Any, request: dict, body: dict,
                  resolution: str) -> tuple[Optional[dict], Optional[tuple]]:
    """(exercise, None) or (None, error) for an exercise resolution."""
    if resolution == "exercise_chosen":
        exercise = database.get_active_diagnostic_exercise(
            str(body.get("exercise_id") or ""))
        if not isinstance(exercise, dict):
            return None, _error(409, "EXERCISE_UNAVAILABLE",
                                "Select an active reviewed exercise.")
        return exercise, None
    from services.diagnostic_exercise_catalogue import (
        CatalogueRefusal,
        save_exercise,
    )
    custom = body.get("custom_exercise")
    fields = dict(custom) if isinstance(custom, dict) else {}
    fields["exercise_id"] = f"coach-request-{request.get('id')}"
    fields.setdefault("active", True)
    # What was spotted is what it treats, unless the coach names otherwise.
    if not fields.get("acoustic_problem_tags") and request.get("observed_tags"):
        fields["acoustic_problem_tags"] = list(request["observed_tags"])
    try:
        exercise = save_exercise(database, fields)
    except CatalogueRefusal as refusal:
        return None, _error(refusal.status, refusal.code, refusal.message)
    if not isinstance(exercise, dict):
        return None, _error(503, "EXERCISE_UNAVAILABLE",
                            "The exercise could not be saved.")
    return exercise, None


def resolve_request(database: Any, request: dict, body: Any,
                    coach_id: str) -> tuple[int, dict]:
    """The coach's one answer to a request, and optionally the share."""
    fields: dict = body if isinstance(body, dict) else {}
    resolution = fields.get("resolution")
    if resolution not in RESOLUTIONS:
        return _error(400, "INVALID_INPUT",
                      f"resolution must be one of {', '.join(RESOLUTIONS)}")
    share = fields.get("share_with_user") is True
    exercise = None
    if resolution != "no_safe_match":
        exercise, error = _exercise_for(database, request, fields, resolution)
        if error:
            return error
    elif share:
        return _error(400, "INVALID_INPUT",
                      "Only an exercise can be shared with the speaker.")
    try:
        resolved = database.resolve_exercise_coach_request(
            request_id=str(request.get("id")), coach_id=str(coach_id),
            resolution=resolution,
            exercise_id=(str(exercise.get("exercise_id"))
                         if exercise else None),
            exercise_version=(int(exercise.get("version") or 1)
                              if exercise else None),
            share=share)
    except Exception as e:  # the database's refusal, named
        for code, (status, message) in _REFUSALS.items():
            if code in str(e):
                return _error(status, code, message)
        raise
    if not isinstance(resolved, dict):
        return _error(500, "V2_ERROR", "Could not save your answer.")
    return 200, {"request": coach_request_payload(resolved, database)}


def review(database: Any, *, take_session_id: str, snippet_id: str,
           method: str, body: Any, coach_id: str) -> tuple[int, dict]:
    """GET: the request. PUT: resolve it. The route has already enforced the
    blind gate and the speaker's practice permission."""
    request = database.get_exercise_coach_request(
        str(take_session_id), str(snippet_id))
    if not isinstance(request, dict):
        return _error(404, "NOT_FOUND", "No exercise request for this moment.")
    if method == "GET":
        return 200, {"request": coach_request_payload(request, database)}
    return resolve_request(database, request, body, coach_id)
