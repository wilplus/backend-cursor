"""The video a coach adds to a written answer (founder 2026-09-30, A5;
0403). Stored like an exercise video (public journal media) and kept on
the request row as `answer_video_ref`; it rides `coach_answer` once the
answer is shared. Before the answer is given it is written to the row
directly; once given, a new video is an answer change and goes through the
resolver (0446), so the history keeps the old video. The route enforces
the blind gate before this runs."""
from __future__ import annotations

import logging
import os
from typing import Any

from werkzeug.utils import secure_filename

_log = logging.getLogger(__name__)

_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v")


def store_answer_video(database: Any, *, request_row: Any, video_file: Any,
                       max_mb: int, coach_id: Any = None) -> tuple[int, dict]:
    """(status, payload): 200 {video_url}, or the refusal named. A coach
    changing their own answer (0446) may add a new video; another coach's
    resolved request is closed."""
    if not isinstance(request_row, dict) or not request_row.get("id"):
        return 404, {"code": "NOT_FOUND", "error": "No request for this moment."}
    from services.coach_request_drafts import changed_by_another_coach
    if changed_by_another_coach(request_row, coach_id):
        return 409, {"code": "ALREADY_RESOLVED",
                     "error": "This moment already has another coach's answer."}
    if video_file is None or not getattr(video_file, "filename", ""):
        return 400, {"code": "INVALID_INPUT", "error": "video_file is required"}
    ext = os.path.splitext(secure_filename(video_file.filename))[1].lower()
    if ext not in _EXTENSIONS:
        return 415, {"code": "UNSUPPORTED_TYPE",
                     "error": "Upload an .mp4, .mov, .webm or .m4v file."}
    video_bytes = video_file.read()
    if len(video_bytes) > max(1, int(max_mb)) * 1024 * 1024:
        return 413, {"code": "TOO_LARGE",
                     "error": f"Video is too large. Max allowed is {max_mb}MB."}
    from services.coach_exercise_authoring import store_exercise_video
    from services.journal_media import JournalMediaError
    try:
        url = store_exercise_video(video_bytes, video_file.filename,
                                   getattr(video_file, "content_type", None) or "video/mp4")
    except JournalMediaError as refused:
        return 503, {"code": "DISABLED", "error": str(refused)}
    except Exception as e:  # noqa: BLE001 -- storage named, never raised out
        _log.error("answer video upload failed request=%s: %s", request_row["id"], e)
        return 502, {"code": "UPLOAD_FAILED", "error": "Failed to upload video to storage."}
    answered = bool(request_row.get("resolution"))
    if answered:
        return _replace_resolved_video(database, request_row, url, coach_id)
    try:
        database.set_exercise_coach_request_video(request_id=str(request_row["id"]), video_ref=url)
    except Exception as e:  # noqa: BLE001 -- the file is stored; the row is not
        _log.error("answer video not kept request=%s: %s", request_row["id"], e, exc_info=True)
        return 500, {"code": "V2_ERROR", "error": "Could not keep the video."}
    return 200, {"video_url": url}


def _replace_resolved_video(database: Any, request_row: dict, url: str,
                            coach_id: Any) -> tuple[int, dict]:
    """A new video on an answer already given (0446, Q-B12 A) is a change
    of that answer: it goes through the resolver with the answer as it
    stands, so the old answer and its video move into the history and the
    row takes the new video in the same UPDATE. Like any change it is
    unshared until the coach shares the answer again (the share belonged to
    the answer the speaker saw)."""
    from services.exercise_coach_requests import refusal_for
    try:
        resolved = database.resolve_exercise_coach_request(
            request_id=str(request_row["id"]), coach_id=str(coach_id or ""),
            resolution=str(request_row.get("resolution")),
            exercise_id=request_row.get("resolved_exercise_id"),
            exercise_version=request_row.get("resolved_exercise_version"),
            share=False, answer_text=request_row.get("answer_text"),
            video_ref=url)
    except Exception as e:  # noqa: BLE001 -- the database's refusal, named
        refused = refusal_for(e)
        if refused is not None:
            return refused
        _log.error("answer video not kept request=%s: %s", request_row["id"], e, exc_info=True)
        return 500, {"code": "V2_ERROR", "error": "Could not keep the video."}
    if not isinstance(resolved, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not keep the video."}
    return 200, {"video_url": url}
