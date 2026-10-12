"""The coach's decision on a speaker's Confident Voice practice (PUT on
``/v2/coach/sessions/<sid>/snippets/<snip>/confidence-practice``).

Moved out of ``routes.v2.coach`` unchanged (founder 2026-10-12: "move logic
out of the backend routes"). The route keeps its blind gate, the speaker's
practice choice (E3) and the practice lookup, in that order, and calls
``save_coach_decision`` only after all three pass; nothing here runs before
the coach's own blind rating is saved.

Writes, in order: the coach's custom exercise filed into the library (when
one is sent), the share's coach assignment, the selected attempt's judgement
and its more-confident record, the practice row, the Album reconciliation,
the library teaching ("Attach = both") and the share notification.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from services.coach_moment_errors import teach_on_attach, with_moment_errors
from services.practice_adoption import ANSWERS as _FIVE_ANSWERS
from services.practice_more_confident import record_after_coach_decision


class PracticeRefusal(Exception):
    """A refused decision: the route answers ``body`` with ``status``."""

    def __init__(self, code: str, error: str, status: int) -> None:
        super().__init__(code)
        self.status = status
        self.body = {"code": code, "error": error}


def requested_video_url(body: dict) -> tuple[Any, Any]:
    """The coach's explanation video address, or the reason it is refused.

    Returns ``(url_or_None, None)`` or ``(None, message)``.
    """
    requested = body.get("explanation_video_url")
    if requested is None:
        return None, None
    if not isinstance(requested, str):
        return None, "explanation_video_url must be a URL."
    requested = requested.strip()
    if requested and not re.match(r"^https?://[^\s]+$", requested,
                                  re.IGNORECASE):
        return None, "explanation_video_url must use http or https."
    return requested, None


def shared_exercise_snapshot(database, exercise, final_video_url, body,
                             practice=None) -> dict:
    """What the speaker is shown. `own_wording` when the coach asks for
    different words than the ones said (founder 2026-09-28, 14B): the
    speaker's practice is then not held to the exact passage. Recorded on the
    shared exercise itself, so the rule travels with what they were asked.

    With `practice` (the share path), the coach's pick counts (0398): it is
    frozen as a coach assignment so the practice joins the jar, and the
    snapshot carries the id the readiness count joins on. Best effort, after
    nothing and in the way of nothing."""
    snapshot = {
        "exercise_id": exercise.get("exercise_id"),
        "version": int(exercise.get("version") or 1),
        "title": exercise.get("title"),
        "instruction": exercise.get("instruction"),
        "explanation_video_url": final_video_url,
        "source": exercise.get("source") or "diagnostic_library",
    }
    if body.get("own_wording") is True:
        snapshot["own_wording"] = True
    if practice is not None:
        from services.confident_voice_practice import record_coach_review_share
        coach_assignment = record_coach_review_share(database, practice, exercise)
        if coach_assignment:
            snapshot["exercise_assignment_id"] = str(
                coach_assignment.get("id") or "")
    return snapshot


def _decision_inputs(practice: dict, body: dict) -> tuple[str, str, Any]:
    decision = body.get("professional_coach_decision")
    if decision not in ("yes", "no", "refine"):
        raise PracticeRefusal("INVALID_INPUT",
                              "professional_coach_decision is required", 400)
    selected_attempt_id = str(practice.get("selected_attempt_id") or "")
    selected_attempt_decision = body.get("selected_attempt_coach_decision")
    if selected_attempt_id and selected_attempt_decision not in _FIVE_ANSWERS:
        raise PracticeRefusal(
            "INVALID_INPUT", "Judge the selected practice recording itself.", 400)
    return decision, selected_attempt_id, selected_attempt_decision


def _file_custom_exercise(database, practice: dict, custom_body) -> dict:
    """FILED INTO THE LIBRARY, not minted here (founder 2026-09-25). It has
    to name the error it treats, or it can never reach anyone: routing
    matches an exercise's errors against the errors a detector actually
    found on a clip. Filing it also keeps a coach's judgement about one
    recording from riding along onto that speaker's later practice (L3)."""
    from services.diagnostic_exercise_catalogue import (
        CatalogueRefusal,
        file_coach_exercise,
    )
    custom_body = with_moment_errors(custom_body, practice, database)
    try:
        exercise = file_coach_exercise(
            database, practice_id=practice.get("id"), fields=custom_body)
    except CatalogueRefusal as refusal:
        raise PracticeRefusal(refusal.code, refusal.message,
                              refusal.status) from refusal
    if not exercise:
        raise PracticeRefusal("EXERCISE_UNAVAILABLE",
                              "The exercise could not be saved.", 503)
    return exercise


def _chosen_exercise(database, practice: dict,
                     body: dict) -> tuple[dict, Optional[dict], str]:
    """(exercise, custom exercise or None, exercise id)."""
    custom_body = body.get("custom_exercise")
    if custom_body is not None:
        exercise = _file_custom_exercise(database, practice, custom_body)
        return exercise, exercise, str(exercise.get("exercise_id") or "")
    exercise_id = str(body.get("exercise_id") or practice.get("exercise_id"))
    exercise = database.get_active_diagnostic_exercise(exercise_id)
    if not exercise:
        raise PracticeRefusal("EXERCISE_UNAVAILABLE",
                              "Select an active reviewed exercise.", 409)
    return exercise, None, exercise_id


def _final_video_url(body: dict, exercise: dict, share: bool):
    requested, invalid_video = requested_video_url(body)
    if invalid_video:
        raise PracticeRefusal("INVALID_INPUT", invalid_video, 400)
    final_video_url = (
        requested
        or exercise.get("explanation_video_url")
        or exercise.get("explanation_video_ref")
    )
    if share and not final_video_url:
        raise PracticeRefusal("INVALID_INPUT",
                              "Add an explanation video before sharing.", 400)
    return final_video_url


def _save_selected_attempt(database, practice: dict, attempt_id: str,
                           answer: Any, coach_id: str) -> None:
    selected_attempt = database.set_confident_voice_practice_attempt_coach_decision(
        str(practice.get("id")), attempt_id, str(answer), coach_id)
    if not selected_attempt:
        raise PracticeRefusal(
            "V2_ERROR", "Could not save the selected recording judgment.", 500)
    record_after_coach_decision(database, str(practice.get("id")), attempt_id)


def _reconcile_album(database, practice: dict, updated: dict) -> None:
    from services.confident_voice_practice import (
        reconcile_practice_voice_album,
    )
    admitted = reconcile_practice_voice_album(updated, database=database)
    if admitted:
        from services.arc_notifications import fire_voice_album_ready
        fire_voice_album_ready(
            database, practice.get("owner_user_id"), practice.get("project_id"))


def _notify_share(database, practice: dict) -> None:
    from services.arc_notifications import fire_confidence_practice_shared
    emitted = fire_confidence_practice_shared(
        database, practice.get("owner_user_id"), practice.get("project_id"),
        practice.get("id"))
    if emitted:
        database.update_confident_voice_practice(
            str(practice.get("id")), None,
            {"chat_emitted_at": datetime.now(timezone.utc).isoformat()})


def save_coach_decision(database, practice: dict, body: dict,
                        coach_id: str) -> dict:
    """Save the coach's decision on ``practice``; the updated row.

    Raises ``PracticeRefusal`` for every refused request."""
    decision, attempt_id, attempt_answer = _decision_inputs(practice, body)
    exercise, custom_exercise, exercise_id = _chosen_exercise(
        database, practice, body)
    share = body.get("share_with_user") is True
    final_video_url = _final_video_url(body, exercise, share)
    exercise_snapshot = shared_exercise_snapshot(
        database, exercise, final_video_url, body, practice if share else None)
    patch = {
        "professional_coach_decision": decision,
        "coach_selected_exercise_id": exercise_id,
        "coach_custom_exercise": custom_exercise,
        "coach_explanation_video_url": final_video_url,
    }
    if share:
        patch.update({
            "coach_shared_exercise": exercise_snapshot,
            "coach_shared_by": coach_id,
            "coach_shared_at": datetime.now(timezone.utc).isoformat(),
        })
    if attempt_id:
        _save_selected_attempt(database, practice, attempt_id, attempt_answer,
                               coach_id)
    updated = database.update_confident_voice_practice(
        str(practice.get("id")), None, patch)
    if not updated:
        raise PracticeRefusal("V2_ERROR", "Could not save the coach decision.", 500)
    if attempt_id:
        _reconcile_album(database, practice, updated)
    if share and custom_exercise is None:  # "Attach = both" (founder 09-25)
        teach_on_attach(database, practice, exercise_id, coach_id)
    if share:
        _notify_share(database, practice)
    return updated
