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

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

RESOLUTIONS = ("exercise_chosen", "exercise_authored", "no_safe_match",
               "line_written", "version_written", "note_written")
#: Answers in words (0402, 0403): the resolution → what the speaker's row
#: calls it. A note (an error without a video, an ambiguity) rides the
#: moment only and is never filed anywhere.
WORD_RESOLUTIONS = {"line_written": "line", "version_written": "version",
                    "note_written": "note"}
#: The surface a written answer's pair is recorded on; a note has none.
_PAIR_SURFACE = {"line_written": "praise_line",
                 "version_written": "clearer_version",
                 "exercise_authored": "exercise_script"}

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
    from services.coach_request_drafts import draft_on
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
        # Why it came (founder 2026-09-29): error, praise, rewrite, ambiguity.
        # Rows from before 0391 are errors. Since 0408 (Phase 2, F1) the
        # speaker's side once they judged, else the kind it rose under.
        "kind": (request.get("answer_kind") or request.get("kind")
                 or "error"),
        # Where it rose (0408) and what the speaker did with the bookmark:
        # coach-only, after the blind rating; never the read.
        "raised_on": request.get("raised_on") or "judgement",
        **_moment_event_fields(request, database),
        "spotted": [{"error_id": tag, "label": labels.get(tag) or tag}
                    for tag in request.get("observed_tags") or []],
        "created_at": request.get("created_at"),
        "resolution": request.get("resolution"),
        "resolved_exercise_id": request.get("resolved_exercise_id"),
        # The answer in words (0402), when the coach wrote one, and the video
        # the coach added to it (0403).
        "answer_text": request.get("answer_text"),
        "answer_video_url": answer_video_url(request),
        # The model's draft the coach may edit from; coach-only (C2).
        "draft": draft_on(request),
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


def _moment_event_fields(request: dict, database: Any) -> dict:
    """When the speaker opened and skipped this bookmark (0408); None where
    nothing was recorded or the read failed."""
    out: dict[str, Any] = {"opened_at": None, "skipped_at": None}
    reader = getattr(database, "list_moment_events_for_take", None)
    if reader is None:
        return out
    try:
        rows = reader(str(request.get("take_session_id"))) or []
    except Exception as e:  # noqa: BLE001 — the payload still serves
        logger.warning("moment events read failed take=%s: %s",
                       request.get("take_session_id"), e, exc_info=True)
        return out
    for row in rows:
        if not isinstance(row, dict) \
                or str(row.get("snippet_id")) != str(request.get("snippet_id")):
            continue
        key = f"{row.get('event')}_at"
        if key in out and out[key] is None:
            out[key] = row.get("created_at")
    return out


def _require_main_target(fields: dict) -> Optional[tuple]:
    """THE MAIN TARGET IS REQUIRED (founder 2026-09-30, C8/D5, E5; build plan
    P2-4). An exercise authored from a moment names the one pattern it is
    written for, as ``main_target`` or ``matching_criteria.primary_problem_tag``;
    the catalogue then checks it is one of the exercise's own tags. Without
    it the exercise would be the exact fit for nothing. The catalogue holds
    every coach door to the same rule (``_require_main_target`` there); this
    one refuses before anything is saved, whether the exercise is new or not."""
    from services.diagnostic_exercise_catalogue import (
        MAIN_TARGET_MESSAGE, fold_main_target,
    )
    target = fields.get("main_target")
    if not isinstance(target, str) or not target.strip():
        criteria = fields.get("matching_criteria")
        target = criteria.get("primary_problem_tag") if isinstance(criteria, dict) else None
        if not isinstance(target, str) or not target.strip():
            return _error(400, "MAIN_TARGET_REQUIRED", MAIN_TARGET_MESSAGE)
        fields["main_target"] = target
    fold_main_target(fields)
    return None


def _exercise_for(database: Any, request: dict, body: dict, resolution: str,
                  coach_id: str = "") -> tuple[Optional[dict], Optional[tuple]]:
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
    error = _require_main_target(fields)
    if error:
        return None, error
    # The model's draft beside the final is the one kept on this request,
    # never a client's text (FL-L3).
    draft = (str(request.get("draft_text") or "").strip() or None
             if str(request.get("draft_surface") or "exercise_script") == "exercise_script"
             else None)
    try:
        exercise = save_exercise(
            database, fields, source="coach_request", created_by=str(coach_id or ""),
            ai_draft_text=draft,
            ai_draft_model_version=(str(request.get("draft_model_version") or "").strip()
                                    or None) if draft else None)
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
    answer = None
    if resolution in WORD_RESOLUTIONS:
        answer = " ".join(str(fields.get("answer_text") or "").split())
        if not answer:
            return _error(400, "INVALID_INPUT", "answer_text is required.")
    elif resolution != "no_safe_match":
        exercise, error = _exercise_for(database, request, fields, resolution,
                                        coach_id=str(coach_id))
        if error:
            return error
    elif share:
        return _error(400, "INVALID_INPUT",
                      "Only an answer can be shared with the speaker.")
    kwargs = {} if answer is None else {"answer_text": answer}
    try:
        resolved = database.resolve_exercise_coach_request(
            request_id=str(request.get("id")), coach_id=str(coach_id),
            resolution=resolution,
            exercise_id=(str(exercise.get("exercise_id"))
                         if exercise else None),
            exercise_version=(int(exercise.get("version") or 1)
                              if exercise else None),
            share=share, **kwargs)
    except Exception as e:  # the database's refusal, named
        for code, (status, message) in _REFUSALS.items():
            if code in str(e):
                return _error(status, code, message)
        raise
    if not isinstance(resolved, dict):
        return _error(500, "V2_ERROR", "Could not save your answer.")
    _file_answer(database, request, resolved, fields, exercise, coach_id)
    return 200, {"request": coach_request_payload(resolved, database)}


def _authored_for_this_moment(request: dict, resolution: str,
                              exercise: Optional[dict]) -> bool:
    """The walk's exercise answer: the coach saved a NEW exercise for this
    moment through the upload seam (``coach-request-<request id>``) and the
    request resolves to it as ``exercise_chosen``. Choosing any other
    library exercise is not the coach's final for this draft."""
    if resolution != "exercise_chosen" or not isinstance(exercise, dict):
        return False
    from services.coach_exercise_authoring import exercise_id_for_request
    return str(exercise.get("exercise_id") or "") == \
        exercise_id_for_request(request.get("id"))


def _pair_surface(request: dict, resolution: str,
                  exercise: Optional[dict]) -> Optional[str]:
    if _authored_for_this_moment(request, resolution, exercise):
        return "exercise_script"
    return _PAIR_SURFACE.get(resolution)


def _version_transcript(database: Any, exercise: Optional[dict]) -> Optional[str]:
    """The video's transcript on the exercise version the request resolved
    to (0399), the walk pair's second final; None while it is not there."""
    reader = getattr(database, "get_exercise_version_transcript", None)
    if reader is None or not isinstance(exercise, dict):
        return None
    try:
        row = reader(str(exercise.get("exercise_id") or ""),
                     int(exercise.get("version") or 1))
    except Exception as e:  # noqa: BLE001 -- the answer stands
        logger.info("exercise transcript read failed id=%s: %s",
                    exercise.get("exercise_id"), e)
        return None
    if not isinstance(row, dict) or row.get("transcript_status") != "done":
        return None
    body = row.get("transcript")
    text = body.get("transcript") if isinstance(body, dict) else None
    return " ".join(str(text).split()) if text else None


def _record_pairs(database: Any, request: dict, resolved: dict, fields: dict,
                  exercise: Optional[dict], coach_id: str) -> None:
    """THE PAIR (founder C2, C5; build plan P2-1): when the model's draft was
    shown (it is kept on this request row, by the server) and the coach's
    final differs. Every pair is stamped with the request, the moment, the
    owner and the model version, so the export contract can release it
    (W6; W7 L5, L6). The walk's exercise answer (``_authored_for_this_moment``)
    records the saved instruction and, where it arrived, the video's
    transcript as a second final. The transcript pair carries the exercise
    version and the moment but not the request: one pair per request and
    surface is the table's own key (0402)."""
    from services.feedback_pairs import record_pair
    resolution = str(resolved.get("resolution") or "")
    surface = _pair_surface(request, resolution, exercise)
    draft = request.get("draft_text")
    if not surface or not draft or str(request.get("draft_surface") or surface) != surface:
        return
    authored = surface == "exercise_script" and isinstance(exercise, dict)
    criteria = (exercise or {}).get("matching_criteria")
    main_target = (criteria.get("primary_problem_tag")
                   if authored and isinstance(criteria, dict) else None)
    common = dict(
        surface=surface, draft=draft, coach_id=coach_id,
        model_version=request.get("draft_model_version"),
        pattern_key=main_target or _pattern_key(request, resolution, fields.get("pattern_key")),
        owner_user_id=request.get("owner_user_id"),
        take_session_id=request.get("take_session_id"),
        snippet_id=request.get("snippet_id"),
        exercise_id=(exercise or {}).get("exercise_id") if exercise else None,
        exercise_version=(int(exercise.get("version") or 1) if exercise else None))
    final = (resolved.get("answer_text") if resolution in WORD_RESOLUTIONS
             else (exercise or {}).get("instruction"))
    record_pair(database, final=final, request_id=str(request.get("id")), **common)
    if authored:
        transcript = _version_transcript(database, exercise)
        if transcript:
            record_pair(database, final=transcript, final_kind="transcript", **common)


def _file_answer(database: Any, request: dict, resolved: dict, fields: dict,
                 exercise: Optional[dict], coach_id: str) -> None:
    """What an answer leaves behind besides the resolution, all best-effort
    and never in the answer's way:

    * the (draft, final) pair, when a draft was shown and the final differs
      (``_record_pairs``; services.feedback_pairs; founder C5);
    * a praise line lands in the catalogue of signed lines as the newest
      version for the moment's pattern (35f; P2-3) unless the coach says
      ``file_in_catalogue: false``. A clearer version never does: it is one
      speaker's passage, not a move for every rewrite.
    """
    resolution = str(resolved.get("resolution") or "")
    if resolution == "note_written":
        # 7 (C5-a, 0411): the personal line is a pair surface of its own.
        from services.coach_word_pairs import record_moment_line_pair
        record_moment_line_pair(database, request_row=request, coach_id=coach_id,
                                final_text=resolved.get("answer_text"))
    _record_pairs(database, request, resolved, fields, exercise, coach_id)
    if resolution == "line_written" and fields.get("file_in_catalogue") is not False:
        _file_praise_line(database, request, resolved, coach_id,
                          fields.get("pattern_key"))


def answer_video_url(request: Any) -> Optional[str]:
    """The playable address of the video a coach added to a written answer
    (0403), or None. Exercise videos are public journal media; a private
    ref is re-signed on every read."""
    ref = (request or {}).get("answer_video_ref") if isinstance(request, dict) else None
    if not ref:
        return None
    try:
        from services.coach_video_storage import refreshed_media_url
        return refreshed_media_url(str(ref)) or str(ref)
    except Exception:  # noqa: BLE001 -- the address still serves
        return str(ref)


def _pattern_key(request: dict, resolution: str, chosen: Any = None) -> Optional[str]:
    """The pattern an answer is filed under: the coach's own choice when they
    named one on the Home screen (a cue, the read, a move), else the first
    thing spotted, else the rewrite's why."""
    if isinstance(chosen, str) and chosen.strip() and not any(c.isspace() for c in chosen.strip()):
        return chosen.strip()
    tags = [t for t in (request.get("observed_tags") or []) if isinstance(t, str)]
    if resolution == "version_written":
        trace = request.get("request_trace")
        why = trace.get("why_key") if isinstance(trace, dict) else None
        return str(why) if why else "clarity"
    return tags[0] if tags else None


def _file_praise_line(database: Any, request: dict, resolved: dict,
                      coach_id: str, chosen: Any = None) -> None:
    from services.feedback_catalogue import (
        CONFIDENT_READ, CatalogueRefusal, validate_line,
    )
    writer = getattr(database, "insert_feedback_catalogue_line", None)
    if writer is None:
        return
    key = _pattern_key(request, "line_written", chosen)
    if key == CONFIDENT_READ:
        key = None
    body = {"lane": "praise", "pattern_kind": "cue" if key else "read",
            "pattern_key": key or CONFIDENT_READ,
            "text": resolved.get("answer_text")}
    try:
        line = validate_line(body)
        writer(**line, signed_by=str(coach_id))
    except CatalogueRefusal as refusal:
        logger.info("praise line not filed request=%s: %s",
                    request.get("id"), refusal)
    except Exception as e:  # noqa: BLE001 -- the answer stands
        logger.warning("praise line not filed request=%s: %s",
                       request.get("id"), e, exc_info=True)


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
