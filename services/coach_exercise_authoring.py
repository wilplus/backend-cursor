"""Exercise authoring for the coach panel (founder 2026-09-29, decision 4).

The same catalogue service and the same live library as the CMS
(services/diagnostic_exercise_catalogue); the same refusals, word for word.
What this module adds is the coach's door: the library as an author reads
it, the save that keeps its version and the AI draft beside the final
(0399), the video that is stored and transcribed at upload under the coach's
own authorization, and a first script drafted from the library's own past
finals and shown to the coach only.

THE DRAFT IS A CANDIDATE. It is returned to the coach, who edits it; what is
saved as the exercise is the coach's final. The draft is stored beside that
final on the version row and served nowhere. An exercise's text is copy the
coach signs; nothing generated reaches a speaker (LIVE LOOP).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

LLM_SURFACE = "exercise_script_draft"

_DRAFT_SYSTEM = (
    "You write short practice exercises for a public-speaking coach. The "
    "coach will record a video following the script and will edit every "
    "word before anyone sees it. Write in the second person, plainly, for a "
    "speaker who rehearses one passage of their own talk. Name the one "
    "delivery pattern the exercise addresses, say what to do differently "
    "on the next attempt, and keep it under 150 words. No scores, no "
    "judgements about the speaker, no promises."
)


def library_for_authoring(database: Any) -> dict:
    """Every exercise with its latest version row, and the error library."""
    exercises = database.list_diagnostic_exercises() or []
    lister = getattr(database, "list_exercise_versions", None)
    rows = []
    for exercise in exercises:
        if not isinstance(exercise, dict):
            continue
        versions = lister(str(exercise.get("exercise_id") or "")) \
            if lister is not None else []
        rows.append({**exercise, "latest_version": (versions or [None])[0]})
    errors = database.list_speaking_errors(active_only=False) \
        if hasattr(database, "list_speaking_errors") else []
    return {"exercises": rows, "speaking_errors": errors or []}


def save_from_coach_panel(database: Any, body: Any, *,
                          coach_id: str) -> Optional[dict]:
    """One save through the catalogue, source coach_panel, the AI draft (if
    the coach asked for one) kept beside the final. Raises CatalogueRefusal
    as the CMS does."""
    from services.diagnostic_exercise_catalogue import save_exercise
    fields = dict(body) if isinstance(body, dict) else {}
    draft = str(fields.pop("ai_draft_text", "") or "").strip() or None
    draft_model = str(fields.pop("ai_draft_model_version", "") or "").strip() \
        or None
    saved = save_exercise(
        database, fields, source="coach_panel", created_by=str(coach_id),
        ai_draft_text=draft, ai_draft_model_version=draft_model)
    if not saved:
        return None
    return {"exercise": saved, "version": int(saved.get("version") or 1)}


def store_exercise_video(video_bytes: bytes, filename: str,
                         content_type: str) -> str:
    """The video, in the journal bucket under its public base; the URL the
    live row will carry. Raises JournalMediaError when storage is off."""
    from services import journal_media
    ct = (content_type or "").strip().lower()
    if ct not in journal_media.allowed_content_types("video"):
        ct = "video/mp4"
    stored = journal_media.put_object_bytes(
        kind="video", content_type=ct, data=video_bytes, filename=filename,
        folder="exercise")
    return str(stored["public_url"])


#: Stands in for the video's address while a definition is checked before
#: the video is stored; never written.
_URL_TO_COME = "https://video.pending.invalid/exercise"


def _definition_for_video(database: Any, exercise_id: str,
                          definition: Any) -> tuple[Optional[dict], dict]:
    """What the video attaches to: the live row, the coach's definition, or
    both merged (an edit and a new video in one save). ``(base, extras)``
    with the AI draft fields split off; base None when nothing exists."""
    existing = database.get_diagnostic_exercise(str(exercise_id))
    fields = dict(definition) if isinstance(definition, dict) else {}
    extras = {
        "ai_draft_text": str(fields.pop("ai_draft_text", "") or "").strip()
        or None,
        "ai_draft_model_version": str(
            fields.pop("ai_draft_model_version", "") or "").strip() or None,
    }
    if not isinstance(existing, dict) and not fields:
        return None, extras
    base = {**(existing if isinstance(existing, dict) else {}), **fields,
            "exercise_id": str(exercise_id)}
    return base, extras


def attach_video(database: Any, *, exercise_id: str, coach_id: str,
                 video_bytes: bytes, filename: str, content_type: str,
                 definition: Any = None) -> tuple[int, dict]:
    """Store, hash, save as a new version, transcribe; ``(status, payload)``.

    A NEW EXERCISE ARRIVES WITH ITS VIDEO. The library refuses an exercise
    without a video and the video needs an exercise to attach to, so the
    coach's first save is one call: the definition rides in ``definition``
    and the video in the body. For an existing exercise ``definition`` is an
    optional edit merged over the live row. Either way the definition is
    checked BEFORE the video is stored, so a refusal leaves nothing behind.

    The transcript never blocks the exercise: a missing coach authorization
    or a failed provider call is recorded on the version row and the video
    serves as it does today.
    """
    from services.diagnostic_exercise_catalogue import (
        CatalogueRefusal, save_exercise, validate_exercise,
    )
    from services.exercise_versions import (
        TRANSCRIPT_PENDING, settle_transcript, transcribe_exercise_video,
        video_sha256,
    )
    from services.journal_media import JournalMediaError
    base, extras = _definition_for_video(database, exercise_id, definition)
    if base is None:
        return 404, {"code": "NOT_FOUND", "error": "exercise not found"}
    try:
        validate_exercise(database, {**base, "explanation_video_url": _URL_TO_COME})
    except CatalogueRefusal as refusal:
        return refusal.status, {"code": refusal.code, "error": refusal.message}
    try:
        url = store_exercise_video(video_bytes, filename, content_type)
    except JournalMediaError as refused:
        return 503, {"code": "DISABLED", "error": str(refused)}
    except Exception as e:  # noqa: BLE001 — storage named, never raised out
        _log.error("exercise video upload failed id=%s: %s", exercise_id, e)
        return 502, {"code": "UPLOAD_FAILED",
                     "error": "Failed to upload video to storage."}
    try:
        saved = save_exercise(
            database, {**base, "explanation_video_url": url},
            source="coach_panel", created_by=str(coach_id),
            video_sha256=video_sha256(video_bytes),
            video_bytes=len(video_bytes),
            transcript_status=TRANSCRIPT_PENDING, **extras)
    except CatalogueRefusal as refusal:
        return refusal.status, {"code": refusal.code, "error": refusal.message}
    if not saved:
        return 500, {"code": "V2_ERROR",
                     "error": "The exercise could not be saved."}
    version = int(saved.get("version") or 1)
    status, transcript, language = transcribe_exercise_video(
        database, coach_user_id=str(coach_id), video_bytes=video_bytes,
        filename=filename)
    settle_transcript(database, exercise_id=str(exercise_id), version=version,
                      status=status, transcript=transcript, language=language)
    return 200, {"exercise": saved, "version": version,
                 "transcript_status": status}


def _examples(database: Any, error_ids: list[str]) -> list[str]:
    """The library's own finals for these errors: what a draft learns from."""
    wanted = set(error_ids)
    out = []
    for exercise in database.list_diagnostic_exercises() or []:
        if not isinstance(exercise, dict):
            continue
        tags = {str(t) for t in exercise.get("acoustic_problem_tags") or []}
        text = str(exercise.get("instruction") or "").strip()
        if tags & wanted and text:
            out.append(f"- {exercise.get('title') or exercise.get('exercise_id')}: {text}")
    return out[:6]


def draft_script(database: Any, body: Any, *,
                 coach_id: str) -> tuple[int, dict]:
    """A first script for the named errors, to the coach only."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_EXERCISE_SCRIPT_DRAFT
    fields = body if isinstance(body, dict) else {}
    error_ids = [str(e).strip() for e in (fields.get("error_ids") or [])
                 if str(e or "").strip()]
    if not error_ids:
        return 400, {"code": "INVALID_INPUT", "error": "error_ids is required"}
    library = {str(row.get("error_id")): row
               for row in database.list_speaking_errors(active_only=False) or []
               if isinstance(row, dict)}
    unknown = [e for e in error_ids if e not in library]
    if unknown:
        return 400, {"code": "INVALID_INPUT",
                     "error": f"Unknown speaking errors: {', '.join(unknown)}"}
    named = "; ".join(
        f"{library[e].get('label') or e}: {library[e].get('definition') or ''}".strip(": ")
        for e in error_ids)
    examples = _examples(database, error_ids)
    notes = str(fields.get("notes") or "").strip()
    title = str(fields.get("title") or "").strip()
    user = (
        f"Delivery pattern(s) this exercise addresses: {named}\n"
        + (f"Working title: {title}\n" if title else "")
        + (f"Coach's notes: {notes}\n" if notes else "")
        + ("Existing exercises in the library for these patterns, for tone "
           "and length:\n" + "\n".join(examples) + "\n" if examples else "")
        + "Write the script."
    )
    result = chat_complete(
        spec=SPEC_EXERCISE_SCRIPT_DRAFT, system=_DRAFT_SYSTEM, user=user,
        surface=LLM_SURFACE, user_id=str(coach_id))
    if result is None or not str(result.text or "").strip():
        return 503, {"code": "DRAFT_UNAVAILABLE",
                     "error": "A draft could not be written right now."}
    return 200, {"draft": result.text.strip(), "model_version": result.model}
