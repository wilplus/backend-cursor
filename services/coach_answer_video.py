"""The video a coach adds to a written answer (founder 2026-09-30, A5;
0403). Stored like an exercise video (public journal media) and kept on
the request row as `answer_video_ref`; it rides `coach_answer` once the
answer is shared. The route enforces the blind gate before this runs."""
from __future__ import annotations

import logging
import os
from typing import Any

from werkzeug.utils import secure_filename

_log = logging.getLogger(__name__)

_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v")


def store_answer_video(database: Any, *, request_row: Any, video_file: Any,
                       max_mb: int) -> tuple[int, dict]:
    """(status, payload): 200 {video_url}, or the refusal named."""
    if not isinstance(request_row, dict) or not request_row.get("id"):
        return 404, {"code": "NOT_FOUND", "error": "No request for this moment."}
    if request_row.get("resolution"):
        return 409, {"code": "ALREADY_RESOLVED",
                     "error": "This moment already has your answer."}
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
    try:
        database.set_exercise_coach_request_video(request_id=str(request_row["id"]), video_ref=url)
    except Exception as e:  # noqa: BLE001 -- the file is stored; the row is not
        _log.error("answer video not kept request=%s: %s", request_row["id"], e, exc_info=True)
        return 500, {"code": "V2_ERROR", "error": "Could not keep the video."}
    return 200, {"video_url": url}
