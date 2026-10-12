"""Open or resume the speaker's one optional same-passage practice for a
moment (POST /v2/user/snippets/<snippet_id>/confidence-practice).

Moved out of ``routes.v2.user_sessions`` unchanged (founder 2026-10-12). The
route's auth, purpose guard and personalised-practice consent run before
anything here. The one write is the practice row, and only after the
ownership check, the answer gate, the kind, the exercise gate, the exact
evidence and the passage have all passed.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

from services.practice_adoption import ANSWERS as _PRACTICE_ANSWERS
from services.practice_adoption import route_matches as _route_matches
from services.refusal import Refusal
from services.snippet_values import resolve_all

#: start_exercise_check refusal → (code, message). The codes and messages
#: are the ones this route already returned; only the owner moved.
_START_REFUSALS = {
    "NOT_ELIGIBLE": ("NOT_ELIGIBLE", "This moment does not match the exercise."),
    "NOT_MATCHABLE": ("NOT_ELIGIBLE", "This exercise cannot be matched safely."),
    "EXERCISE_OFFER_STALE": ("EXERCISE_OFFER_STALE",
                             "A better matching exercise is now available."),
}


def original_answer(body: dict) -> Any:
    """The speaker's answer about the original, one of the five; or None
    under Phase 2 (founder 2026-10-01, F1), where the judgement comes after
    the practice and the start carries no answer."""
    answer = body.get("original_user_answer")
    if answer is not None and answer not in _PRACTICE_ANSWERS:
        raise Refusal("INVALID_INPUT", "original_user_answer is not valid", 400)
    return answer


def _answer_matches_route(owner_route: dict, answer: str) -> bool:
    """The first answer as the owner route stored it (founder 2026-09-25).

    The sheet sends one of the five answers since PR 5; before it, "no"
    stood for every answer but Yes (wilplus/backend-cursor#673). Both are
    accepted; `route_matches` reads the stored answer and the four legacy
    values."""
    yes_or_no = "yes" if owner_route.get("response") == "yes" else "no"
    return (_route_matches(str(owner_route.get("response") or ""), answer)
            or yes_or_no == answer)


def _answer_gate(database, *, session: dict, snippet_id: str, user_id: str,
                 answer: Any) -> None:
    """ANSWER FIRST, until Phase 2: the practice starts only once the
    Confident Voice question was answered, as the owner route records it.
    Under F1 a start with no answer passes; a start that carries one is
    still checked, so the old sheet and the new run side by side."""
    if answer is None:
        return
    owner_route = next((
        row for row in database.list_owner_voice_album_routes(
            str(session.get("arc_id")))
        if str(row.get("snippet_id")) == str(snippet_id)
        and str(row.get("owner_user_id")) == str(user_id)
    ), None)
    if not owner_route or not _answer_matches_route(owner_route, answer):
        raise Refusal("ANSWER_REQUIRED",
                      "Answer the Confident Voice question first.", 409)


def _start_kind(database, body: dict) -> tuple[str, Optional[str], Any]:
    """(kind, exercise_id, exercise). THREE KINDS OF PASSAGE (founder lock
    2026-09-30, D1): the library exercise matched to the clip, the Manager's
    rewrite as the words to say, or the plain moment said again. Only the
    first needs an exercise row and the exercise gate."""
    from services.practice_adoption import KINDS

    kind = str(body.get("kind") or "exercise")
    if kind not in KINDS:
        raise Refusal("INVALID_INPUT", "kind is not valid", 400)
    if kind != "exercise":
        return kind, None, None
    exercise_id = str(body.get("exercise_id") or "hear-every-word-v1")
    exercise = database.get_active_diagnostic_exercise(exercise_id)
    if not exercise:
        raise Refusal("EXERCISE_UNAVAILABLE", "This exercise is not available.", 409)
    return kind, exercise_id, exercise


def _median_wpm(database, take_id: str) -> Optional[float]:
    wpms = []
    for row in database.get_snippets_by_session(take_id) or []:
        wpm = resolve_all(row).get("wpm")
        if isinstance(wpm, (int, float)) and not isinstance(wpm, bool):
            wpms.append(float(wpm))
    return statistics.median(wpms) if wpms else None


def _start_gate(database, kind, snip, take_id, snippet_id, exercise_id,
                median_wpm, user_id) -> tuple[Any, Optional[dict]]:
    """(verdict, matching). The offer froze its choice (80/20, founder
    2026-09-26); the tapped exercise must be that one. A rewrite or the
    plain moment has no exercise to gate, and the clip's read is still
    recorded with the practice, as evidence, never as a verdict shown."""
    from services.confident_voice_practice import (
        exercise_eligibility, start_exercise_check,
    )
    if kind != "exercise":
        return exercise_eligibility(snip, session_median_wpm=median_wpm), None
    refusal, verdict, matching = start_exercise_check(
        snippet=snip, take_session_id=take_id, snippet_id=snippet_id,
        exercise_id=str(exercise_id), database=database,
        owner_user_id=user_id, session_median_wpm=median_wpm)
    if refusal:
        code, message = _START_REFUSALS[refusal]
        raise Refusal(code, message, 409)
    return verdict, matching


def _evidence(body: dict, session: dict, take_id: str) -> tuple[dict, int, int]:
    """(span, slide_index, paragraph_index) of the exact feedback evidence."""
    evidence: Any = body.get("evidence") if isinstance(body.get("evidence"), dict) else {}
    span: Any = evidence.get("span") if isinstance(evidence.get("span"), dict) else {}
    slide_index = evidence.get("slide_index")
    paragraph_index = evidence.get("paragraph_index")
    if str(evidence.get("project_id") or "") != str(session.get("arc_id")) \
            or str(evidence.get("take_session_id") or "") != take_id \
            or not isinstance(slide_index, int) or slide_index < 0 \
            or not isinstance(paragraph_index, int) or paragraph_index < 0 \
            or not isinstance(span.get("start"), int) \
            or not isinstance(span.get("end"), int) \
            or span["end"] <= span["start"]:
        raise Refusal("INVALID_INPUT", "exact feedback evidence is required", 400)
    return span, slide_index, paragraph_index


def _snapshot(kind, exercise_id, exercise, body) -> dict:
    """What the practice froze: the library exercise as served, or the
    kind of passage with the feedback item it came from."""
    if exercise:
        return {
            "exercise_id": exercise_id,
            "version": int(exercise.get("version") or 1),
            "title": exercise.get("title"),
            "instruction": exercise.get("instruction"),
            "explanation_video_url": exercise.get("explanation_video_url"),
            "source": "diagnostic_library",
        }
    return {
        "exercise_id": None, "version": 0, "title": None,
        "instruction": None, "explanation_video_url": None,
        "source": kind,
        "feedback_id": str(body.get("feedback_id") or "") or None,
    }


def _owned_moment(database, snippet_id: str, user_id: Any) -> tuple[dict, dict]:
    snip = database.get_snippet_by_id(snippet_id)
    session = database.v2_get_session_by_id(
        str((snip or {}).get("session_id") or ""))
    if (not snip or not session
            or str(session.get("user_id")) != str(user_id)
            or not session.get("arc_id")):
        raise Refusal("NOT_FOUND", "snippet not found", 404)
    return snip, session


def _practice_row(*, user_id, session, take_id, snippet_id, kind, exercise_id,
                  snapshot, span, slide_index, paragraph_index, passage, snip,
                  verdict, matching, answer) -> dict:
    audio_ref = snip.get("audio_segment_path") or snip.get("audio_ref")
    return {
        "owner_user_id": str(user_id),
        "project_id": str(session["arc_id"]),
        "take_session_id": take_id,
        "snippet_id": str(snippet_id),
        "exercise_id": exercise_id,
        "exercise_version": int(snapshot["version"]),
        "exercise_snapshot": snapshot,
        "kind": kind,
        "slide_index": slide_index,
        "paragraph_index": paragraph_index,
        "evidence_span": span,
        "exact_passage": passage,
        "original_audio_ref": str(audio_ref),
        "original_start_offset_ms": int(snip.get("start_offset_ms") or 0),
        "original_duration_ms": int(snip.get("duration_ms") or 0),
        "machine_assessment": {
            "pattern": verdict.get("pattern"),
            "priority": verdict.get("priority"),
            **(matching or {}),
        },
        "acoustic_evidence": {
            "signals": verdict.get("signals"),
            "snapshot": verdict.get("snapshot"),
            "pace_high": verdict.get("pace_high"),
        },
        "original_user_answer": answer,
    }


def start_practice(database, *, snippet_id: str, body: dict, user_id: Any,
                   answer: Any) -> tuple[dict, bool]:
    """(practice row, created). This moment's own row resumes (ONE PRACTICE
    PER MOMENT, founder 2026-09-29); otherwise a new one is written.
    Raises ``Refusal`` for every refused start."""
    snip, session = _owned_moment(database, snippet_id, user_id)
    _answer_gate(database, session=session, snippet_id=str(snippet_id),
                 user_id=str(user_id), answer=answer)
    kind, exercise_id, exercise = _start_kind(database, body)
    take_id = str(session.get("id"))
    existing = database.get_confident_voice_practice_by_moment(
        take_id, str(snippet_id), str(user_id))
    if existing:
        return existing, False
    verdict, matching = _start_gate(
        database, kind, snip, take_id, str(snippet_id), exercise_id,
        _median_wpm(database, take_id), user_id)
    span, slide_index, paragraph_index = _evidence(body, session, take_id)
    from services.practice_adoption import passage_for
    passage = passage_for(
        kind, (snip.get("transcript") or "").strip(), body.get("passage"))
    if not passage:
        raise Refusal("INVALID_INPUT", "the words to practise are required", 400)
    snapshot = _snapshot(kind, exercise_id, exercise, body)
    created = database.create_confident_voice_practice(_practice_row(
        user_id=user_id, session=session, take_id=take_id,
        snippet_id=snippet_id, kind=kind, exercise_id=exercise_id,
        snapshot=snapshot, span=span, slide_index=slide_index,
        paragraph_index=paragraph_index, passage=passage, snip=snip,
        verdict=verdict, matching=matching, answer=answer))
    if not created:
        raise Refusal("V2_ERROR", "Could not start this practice.", 500)
    return created, True
