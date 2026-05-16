"""Cloudflare R2 storage for user-uploaded media (audio + video).

A focused parallel to ``services.coach_video_storage`` — same boto3
client setup, but routes to ``R2_USER_MEDIA_BUCKET`` instead of the
coach-feedback bucket. Kept separate so user uploads land in their
own R2 bucket with their own retention + access policy without us
having to thread bucket-name plumbing through three layers of
helpers.

When R2 isn't configured (dev / staging without R2 envs), the
``put_user_media_bytes`` helper falls through to ``services.db``'s
Supabase upload path so local development still works against
Supabase Storage. The read path (``user_media_public_url`` /
``presigned_get_user_media``) mirrors that fallback.

Public surface:
  - ``user_media_use_r2()`` — True iff full R2 creds + bucket name
    are configured. Routes branch on this.
  - ``put_user_media_bytes(key, body, content_type)`` — uploads
    bytes; idempotent on key reuse (last writer wins, same as S3).
  - ``user_media_public_url(key)`` — stable HTTPS URL when
    ``R2_USER_MEDIA_PUBLIC_BASE_URL`` is set; ``None`` otherwise.
  - ``presigned_get_user_media(key, expires_in)`` — signed GET
    URL for admin playback when the bucket is private. Falls back
    to Supabase signed URLs when R2 isn't configured.
  - ``guess_media_content_type(filename)`` — mimetypes wrapper
    with audio/video fallbacks.
  - ``classify_media_kind(content_type)`` — returns 'audio' /
    'video' / None based on the MIME prefix; the upload route
    rejects None so the user_uploaded_files.file_type check
    constraint stays satisfied.
"""
from __future__ import annotations

import logging
import mimetypes
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Module-level boto3 client, lazy-init'd. Same pattern + same
# credentials as services.coach_video_storage (R2_ACCOUNT_ID /
# R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY). We re-init here rather
# than importing from coach_video_storage so this module stays
# self-contained — the coach module is the wrong abstraction layer
# to reach into for user content.
_s3_client = None


def _config():
    from config import Config
    return Config


def user_media_bucket_name() -> str:
    """Bucket the uploads land in. Falls back to the coach bucket
    when R2_USER_MEDIA_BUCKET is unset so dev environments without
    a dedicated bucket still function — but the route logs a
    warning at startup if it sees the fallback, so we notice."""
    c = _config()
    bucket = (getattr(c, "R2_USER_MEDIA_BUCKET", None) or "").strip()
    if bucket:
        return bucket
    return (
        (getattr(c, "R2_BUCKET_NAME", None) or "").strip()
        or c.COACH_FEEDBACK_VIDEO_BUCKET
    )


def user_media_use_r2() -> bool:
    """True iff full R2 credentials + a real user-media bucket are
    configured. When False, callers fall through to Supabase
    Storage so dev environments still upload/download cleanly."""
    c = _config()
    return all([
        (c.R2_ACCOUNT_ID or "").strip(),
        (c.R2_ACCESS_KEY_ID or "").strip(),
        (c.R2_SECRET_ACCESS_KEY or "").strip(),
        (getattr(c, "R2_USER_MEDIA_BUCKET", None) or "").strip(),
    ])


def user_media_public_url(storage_key: str) -> Optional[str]:
    """Stable HTTPS URL when R2_USER_MEDIA_PUBLIC_BASE_URL is set
    (public bucket / custom domain). ``None`` means the read path
    must mint a signed URL."""
    base = (
        getattr(_config(), "R2_USER_MEDIA_PUBLIC_BASE_URL", None) or ""
    ).strip().rstrip("/")
    if not base:
        return None
    return f"{base}/{storage_key.lstrip('/')}"


def _client():
    """Lazy boto3 S3 client pointed at the R2 account. Reused
    across calls in this process."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    import boto3
    from botocore.config import Config as BotoConfig

    c = _config()
    account = (c.R2_ACCOUNT_ID or "").strip()
    _s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=(c.R2_ACCESS_KEY_ID or "").strip(),
        aws_secret_access_key=(c.R2_SECRET_ACCESS_KEY or "").strip(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )
    return _s3_client


def _clamp_ttl(expires_in: int) -> int:
    return max(60, min(int(expires_in), 604800))


def put_user_media_bytes(
    key: str,
    body: bytes,
    content_type: str,
) -> str:
    """Upload bytes to the user-media bucket. Returns the bucket
    name actually written to (so the caller can persist the same
    value into user_uploaded_files.r2_bucket without re-deriving
    it). Raises on failure — the route handler maps to 502.
    """
    key = key.lstrip("/")
    bucket = user_media_bucket_name()
    if user_media_use_r2():
        _client().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType=content_type,
        )
        return bucket
    # Supabase Storage fallback for dev environments. Mirrors the
    # coach_video_storage fallback so the upload path stays uniform.
    from services.db import db
    db.upload_audio(bucket, key, body, content_type)
    return bucket


def presigned_get_user_media(
    key: str,
    expires_in: int = 3600,
    *,
    supabase_db: Any = None,
) -> Optional[str]:
    """Mint a signed GET URL for ``key`` so the admin can play the
    asset without us proxying the bytes. Returns ``None`` only if
    both R2 is unconfigured AND the Supabase fallback fails (so
    the admin UI can decide whether to retry or render a placeholder).
    """
    key = key.lstrip("/")
    if user_media_use_r2():
        bucket = user_media_bucket_name()
        try:
            return _client().generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=_clamp_ttl(expires_in),
            )
        except Exception as e:
            logger.warning(
                "user_media: presigned GET failed bucket=%s key=%s err=%s",
                bucket, key, e,
            )
            return None
    if supabase_db is None:
        from services.db import db as supabase_db
    try:
        return supabase_db.create_signed_url(
            user_media_bucket_name(), key, expires_in,
        )
    except Exception as e:
        logger.warning(
            "user_media: supabase signed URL failed key=%s err=%s",
            key, e,
        )
        return None


def guess_media_content_type(filename: str) -> str:
    """Best-guess MIME from the filename. Falls back to a small
    audio/video map so we don't ship application/octet-stream
    just because mimetypes didn't ship the extension by default."""
    ct = mimetypes.guess_type(filename or "")[0]
    if ct:
        return ct
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "m4v": "video/x-m4v",
        "mkv": "video/x-matroska",
        "avi": "video/x-msvideo",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }.get(ext, "application/octet-stream")


def classify_media_kind(content_type: str) -> Optional[str]:
    """Map a MIME type to the file_type CHECK constraint values
    on user_uploaded_files. Returns 'audio' / 'video' / None.
    None means the upload should be rejected — anything that
    isn't audio or video has no path to render in the admin
    Files tab today."""
    ct = (content_type or "").strip().lower()
    if ct.startswith("audio/"):
        return "audio"
    if ct.startswith("video/"):
        return "video"
    return None
