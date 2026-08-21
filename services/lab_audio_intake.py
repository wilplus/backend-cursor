"""Bounded file intake for the Lab recording upload endpoint."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from services.context_document import extract_context_text
from services.lab_recording_intake import RecordingIntakeError
from services.upload_guard import (
    Deadline,
    UploadTooLarge,
    deadline_for,
    read_capped,
)


@dataclass(frozen=True)
class RecordingUpload:
    """Validated upload data safe to carry into storage and analysis."""

    audio_file: Any
    audio_bytes: bytes
    context_document: dict[str, Any] | None
    deadline: Deadline


def _parse_context_document(upload: Any, max_bytes: int) -> dict[str, Any]:
    """Read and extract a context document before any audio is stored."""
    try:
        data = read_capped(upload, max_bytes)
    except UploadTooLarge as exc:
        raise RecordingIntakeError(
            "FILE_TOO_LARGE",
            "the context document is too large",
            413,
        ) from exc

    if not data:
        raise RecordingIntakeError(
            "INVALID_INPUT",
            "the context document is empty",
            400,
        )

    parsed = extract_context_text(
        data,
        content_type=getattr(upload, "content_type", None),
        filename=getattr(upload, "filename", None),
    )
    if not parsed.get("text"):
        raise RecordingIntakeError(
            "NO_TEXT",
            "no readable text found in the context document",
            400,
        )
    parsed["filename"] = getattr(upload, "filename", None)
    return parsed


def read_recording_upload(
    files: Mapping[str, Any],
    *,
    content_length: int | None,
    max_audio_mb: int,
    context_max_mb: int,
    video_extensions: set[str] | frozenset[str] | tuple[str, ...],
) -> RecordingUpload:
    """Validate and read the multipart files with hard memory ceilings."""
    if "audio_file" not in files:
        raise RecordingIntakeError(
            "AUDIO_FILE_REQUIRED",
            "audio_file is required",
            400,
        )

    audio_file = files.get("audio_file")
    max_audio_bytes = max_audio_mb * 1024 * 1024
    max_context_bytes = max(1, int(context_max_mb or 25)) * 1024 * 1024
    request_max_bytes = max_audio_bytes + 1024 * 1024
    context_upload = files.get("context_document")
    if context_upload is not None:
        request_max_bytes += max_context_bytes
    if (content_length or 0) > request_max_bytes:
        raise RecordingIntakeError(
            "FILE_TOO_LARGE",
            "the recording or context document is too large",
            413,
        )

    deadline = deadline_for("lab-upload")
    try:
        audio_bytes = read_capped(audio_file, max_audio_bytes)
    except UploadTooLarge as exc:
        raise RecordingIntakeError(
            "FILE_TOO_LARGE",
            f"audio_file exceeds {max_audio_mb}MB",
            413,
        ) from exc
    if not audio_bytes:
        raise RecordingIntakeError(
            "INVALID_INPUT",
            "audio_file is empty",
            400,
        )

    content_type = str(getattr(audio_file, "mimetype", None) or "").strip().lower()
    extension = os.path.splitext(
        str(getattr(audio_file, "filename", None) or "")
    )[1].lower().lstrip(".")
    if content_type.startswith("video/") or extension in video_extensions:
        raise RecordingIntakeError(
            "AUDIO_ONLY",
            "Upload an audio file — video isn't supported.",
            415,
        )

    context_document = (
        _parse_context_document(context_upload, max_context_bytes)
        if context_upload is not None
        else None
    )
    return RecordingUpload(
        audio_file=audio_file,
        audio_bytes=audio_bytes,
        context_document=context_document,
        deadline=deadline,
    )
