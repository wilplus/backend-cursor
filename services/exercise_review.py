"""The founder's review of a coach's exercise video (founder 2026-10-19,
decisions log N78; migration 0477).

Two kinds of coach video. A DIRECT MESSAGE (the answer on a moment, the
word for a Take) belongs to one speaker and is never shared. An EXERCISE
VIDEO a coach makes for one speaker's moment reaches that speaker at once,
and every other speaker whose own recording shows that mistake exactly once
the founder approves it here.

* ``waiting`` lists the coach exercise videos with no review yet: the ones
  made for one speaker since 0477, and those filed into the shared library
  before it, which reach nobody new until reviewed.
* ``review`` records the founder's decision. ``approved`` copies the video
  out of the speaker's private storage into the library (so it stays when
  that speaker leaves) and clears the owner in the same write; ``kept``
  leaves it with its speaker and takes it off the list.

Founder only; the routes enforce it. Nothing here reaches a speaker's screen.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

DECISIONS = ("approved", "kept")


def _coach_made(exercise: Any) -> bool:
    from services.confident_voice_practice import _COACH_MADE
    return isinstance(exercise, dict) and str(
        exercise.get("exercise_id") or "").startswith(_COACH_MADE)


def _view(exercise: dict) -> dict:
    """What the founder reviews: the video, its words and what it treats."""
    from services.coach_answer_video import exercise_video_url
    from services.confident_voice_practice import exercise_targets
    main, secondary = exercise_targets(exercise)
    return {
        "exercise_id": exercise.get("exercise_id"),
        "version": exercise.get("version"),
        "title": exercise.get("title"),
        "instruction": exercise.get("instruction"),
        "treats": sorted(main),
        "also_treats": sorted(secondary),
        "video_url": exercise_video_url(exercise.get("explanation_video_url")),
        "made_for_one_speaker": bool(exercise.get("owner_user_id")),
        "updated_at": exercise.get("updated_at"),
    }


def waiting(database: Any) -> list[dict]:
    """Every live coach exercise video still waiting for the founder."""
    rows = [row for row in (database.list_diagnostic_exercises() or [])
            if _coach_made(row) and not row.get("review_decision")
            and row.get("active") and row.get("explanation_video_url")]
    return [_view(row) for row in rows]


def _library_copy(ref: Any) -> str:
    """The video where the shared library keeps it. A private ref (a coach
    video made for one speaker since 0477) is copied to the library's
    store; a public one (filed before 0477) already is there. Raises on
    failure: approving never leaves a shared row on a file that goes when
    its speaker leaves."""
    ref = str(ref or "")
    if not ref.startswith("s3://"):
        return ref
    from services.coach_exercise_authoring import store_exercise_video
    from services.coach_video_storage import (
        get_coach_object_bytes, guess_video_content_type,
    )
    bucket, _, key = ref[len("s3://"):].partition("/")
    data = get_coach_object_bytes(bucket, key)
    name = os.path.basename(key) or "exercise.mp4"
    return store_exercise_video(data, name, guess_video_content_type(name))


def review(database: Any, exercise_id: str, body: Any,
           founder_id: str) -> tuple[int, dict]:
    """PUT /admin/exercises/<id>/review {decision, version}: (status,
    payload). ``version`` is the one the founder watched."""
    decision = (body or {}).get("decision") if isinstance(body, dict) else None
    if decision not in DECISIONS:
        return 400, {"code": "INVALID_INPUT",
                     "error": "decision must be approved or kept"}
    exercise = database.get_diagnostic_exercise(str(exercise_id))
    if not isinstance(exercise, dict):
        return 404, {"code": "NOT_FOUND", "error": "exercise not found"}
    if not _coach_made(exercise):
        return 409, {"code": "NOT_A_COACH_VIDEO",
                     "error": "Only a coach's exercise video is reviewed."}
    if exercise.get("review_decision") == "approved":
        return 409, {"code": "ALREADY_APPROVED",
                     "error": "Already shared; retire it to take it back."}
    # The version the founder watched: a video saved since is not approved
    # unseen.
    version = int(exercise.get("version") or 1)
    if str((body or {}).get("version")) != str(version):
        return 409, {"code": "VERSION_CHANGED",
                     "error": "This video changed since it was opened."}
    video_url = None
    if decision == "approved":
        try:
            video_url = _library_copy(exercise.get("explanation_video_url"))
        except Exception as e:  # noqa: BLE001 -- storage named, never raised out
            _log.error("exercise video copy failed id=%s: %s", exercise_id, e)
            return 502, {"code": "UPLOAD_FAILED",
                         "error": "Failed to copy the video to the library."}
    saved = database.review_diagnostic_exercise(
        exercise_id=str(exercise_id), decision=decision,
        reviewed_by=str(founder_id), version=version, video_url=video_url)
    if not isinstance(saved, dict):
        return 409, {"code": "VERSION_CHANGED",
                     "error": "This video changed since it was opened."}
    if decision == "approved":
        _record_approved_version(database, saved, exercise_id, founder_id)
    return 200, {"exercise": _view(saved), "decision": decision}


def _record_approved_version(database: Any, saved: dict, exercise_id: str,
                             founder_id: str) -> None:
    """The approved row as its own version (0399): the library's copy of the
    video, with no owner, so it outlives the speaker's earlier versions."""
    from services.exercise_versions import record_version
    lister = getattr(database, "list_exercise_versions", None)
    latest = ((lister(str(exercise_id)) or [None])[0]
              if lister is not None else None) or {}
    record_version(database, saved, source="cms", created_by=str(founder_id),
                   video_sha256_hex=latest.get("video_sha256"),
                   video_bytes=latest.get("video_bytes"))
