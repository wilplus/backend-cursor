"""
Coach / reference / feedback videos: Supabase Storage OR Cloudflare R2 (S3 API).

When R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY are set, all new
coach-video bytes use R2. Otherwise behavior matches legacy Supabase Storage.

Presigned PUT: send raw file bytes as the request body (Content-Type must match
the value used when minting the URL). Do not use multipart/form-data.
"""
from __future__ import annotations

import logging
import mimetypes
from typing import Any, Optional

logger = logging.getLogger(__name__)

_cfg = None
_s3_client = None


def _config():
    global _cfg
    if _cfg is None:
        from config import Config

        _cfg = Config()
    return _cfg


def coach_videos_use_r2() -> bool:
    c = _config()
    return bool(
        (getattr(c, "R2_ACCOUNT_ID", None) or "").strip()
        and (getattr(c, "R2_ACCESS_KEY_ID", None) or "").strip()
        and (getattr(c, "R2_SECRET_ACCESS_KEY", None) or "").strip()
    )


def r2_bucket_name() -> str:
    """R2 Bucket name (S3 API). Falls back to COACH_FEEDBACK_VIDEO_BUCKET."""
    c = _config()
    return ((getattr(c, "R2_BUCKET_NAME", None) or "").strip() or c.COACH_FEEDBACK_VIDEO_BUCKET).strip()


def coach_media_public_url(storage_key: str) -> Optional[str]:
    """Stable HTTPS URL if R2_PUBLIC_BASE_URL (custom or public dev domain) is set."""
    base = (getattr(_config(), "R2_PUBLIC_BASE_URL", None) or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/{storage_key.lstrip('/')}"


def _client():
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


def presigned_put_coach_object(bucket: str, key: str, content_type: str, expires_in: int = 3600) -> str:
    if not coach_videos_use_r2():
        raise RuntimeError("R2 credentials not configured; use Supabase signed upload instead.")
    b = (bucket or "").strip() or r2_bucket_name()
    key = key.lstrip("/")
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": b, "Key": key, "ContentType": content_type},
        ExpiresIn=_clamp_ttl(expires_in),
    )


def presigned_get_coach_object(
    bucket: str,
    key: str,
    expires_in: int = 3600,
    *,
    supabase_db: Any = None,
) -> Optional[str]:
    key = key.lstrip("/")
    if coach_videos_use_r2():
        b = r2_bucket_name()
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": b, "Key": key},
            ExpiresIn=_clamp_ttl(expires_in),
        )
    if supabase_db is None:
        from services.db import db as supabase_db
    return supabase_db.create_signed_url(bucket, key, expires_in)


def put_coach_object_bytes(bucket: str, key: str, body: bytes, content_type: str) -> None:
    key = key.lstrip("/")
    if coach_videos_use_r2():
        b = r2_bucket_name()
        _client().put_object(Bucket=b, Key=key, Body=body, ContentType=content_type)
        return
    from services.db import db

    db.upload_audio((bucket or "").strip() or r2_bucket_name(), key, body, content_type)


def get_coach_object_bytes(bucket: str, key: str) -> bytes:
    key = key.lstrip("/")
    if coach_videos_use_r2():
        b = r2_bucket_name()
        r = _client().get_object(Bucket=b, Key=key)
        return r["Body"].read()
    from services.db import db

    return db.download_audio((bucket or "").strip() or _config().COACH_FEEDBACK_VIDEO_BUCKET, key)


def guess_video_content_type(filename: str) -> str:
    ct = mimetypes.guess_type(filename)[0]
    if ct:
        return ct
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "m4v": "video/x-m4v",
        "avi": "video/x-msvideo",
        "mkv": "video/x-matroska",
    }.get(ext, "application/octet-stream")
