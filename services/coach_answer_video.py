"""The video a coach adds to a written answer (founder 2026-09-30, A5;
0403). Stored PRIVATELY in the coach-media bucket (founder 2026-10-15, fix
5: "keep the coach videos", but no public link; Privacy 3.6 §7) and kept on
the request row as `answer_video_ref`, an ``s3://bucket/key`` marker that
every read re-signs (``exercise_coach_requests.answer_video_url``); it rides `coach_answer` once the
answer is shared. Before the answer is given it is written to the row
directly; once given, a new video is an answer change and goes through the
resolver (0446), so the history keeps the old video. The route enforces
the blind gate before this runs."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from werkzeug.utils import secure_filename

_log = logging.getLogger(__name__)

_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v")
_CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime",
                  ".webm": "video/webm", ".m4v": "video/x-m4v"}

#: Where an answer video lives in the coach-media bucket.
KEY_PREFIX = "coach-answers"


def _speaker_of(database: Any, request_row: dict) -> str:
    """The speaker the answer is for: their videos live under their id, so
    closing their account finds every one (``erase_for_user``)."""
    take = request_row.get("take_session_id")
    session = database.v2_get_session_by_id(str(take)) if take else None
    return str((session or {}).get("user_id") or "unknown")


def store_private_video(video_bytes: bytes, *, speaker_id: str, request_id: str,
                        ext: str) -> str:
    """The video in the private coach-media bucket, under the speaker's id;
    returns its ``s3://bucket/key`` ref. Raises on failure."""
    from services.coach_video_storage import default_media_bucket, put_coach_object_bytes
    bucket = default_media_bucket()
    key = f"{KEY_PREFIX}/{speaker_id}/{request_id}/{uuid.uuid4().hex}{ext}"
    put_coach_object_bytes(bucket, key, video_bytes, _CONTENT_TYPES.get(ext, "video/mp4"))
    return f"s3://{bucket}/{key}"


def playable(ref: str) -> str:
    """A short-lived link for the coach's own preview of what they stored."""
    from services.coach_video_storage import refreshed_media_url
    return refreshed_media_url(ref) or ref


def exercise_video_url(ref: Any) -> Any:
    """An exercise video as a player can open it. A coach's video for one
    speaker is a private ``s3://`` ref (0477, N77), signed afresh on every
    read; a library video is a public link and passes unchanged. A private
    ref that cannot be signed is None: the bucket key names the speaker."""
    if isinstance(ref, str) and ref.startswith("s3://"):
        from services.coach_video_storage import refreshed_media_url
        return refreshed_media_url(ref) or None
    return ref


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
    try:
        url = store_private_video(video_bytes, speaker_id=_speaker_of(database, request_row),
                                  request_id=str(request_row["id"]), ext=ext)
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
    return 200, {"video_url": playable(url)}


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
    return 200, {"video_url": playable(url)}


def erase_for_user(user_id: Any) -> int:
    """Closing an account: every coach answer video kept for this speaker
    goes (Privacy 3.6 §7: kept while the account is open, including after a
    Take is deleted). Called with the AI voice's erase, at the termination
    request. Returns how many objects were deleted; never raises."""
    if not user_id:
        return 0
    from services import coach_video_storage as storage
    if not storage.coach_videos_use_r2():
        _log.warning("coach answer videos: R2 off, nothing erased user=%s", user_id)
        return 0
    deleted = 0
    try:
        client = storage._client()
        bucket = storage.default_media_bucket()
        prefix = f"{KEY_PREFIX}/{user_id}/"
        token = None
        while True:
            page = client.list_objects_v2(Bucket=bucket, Prefix=prefix,
                                          **({"ContinuationToken": token} if token else {}))
            keys = [{"Key": o["Key"]} for o in page.get("Contents") or []]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
                deleted += len(keys)
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
    except Exception as error:  # noqa: BLE001 -- never blocks the deletion request
        _log.warning("coach answer videos: erase failed user=%s: %s", user_id,
                     type(error).__name__, exc_info=True)
    return deleted

