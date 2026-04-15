"""
Resolve a playable tutor video URL for GET /v2/homework/session/status.

Supports:
- http(s) URLs (pass-through)
- storage://bucket/path (signed URL via service-role client)
- explicit bucket + storage path columns when URL is empty or non-playable
"""
from __future__ import annotations

import os
from typing import Any, Optional, Tuple

from config import Config

config = Config()


def _trim(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    t = v.strip()
    return t or None


def parse_storage_uri(uri: str) -> Optional[Tuple[str, str]]:
    text = (uri or "").strip()
    prefix = "storage://"
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix) :]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return None
    bucket = parts[0].strip()
    path = parts[1].strip()
    if not bucket or not path:
        return None
    return bucket, path


def _storage_base_url() -> Optional[str]:
    base = _trim(config.SUPABASE_URL)
    if not base:
        return None
    return base.rstrip("/") + "/storage/v1/object"


def _public_object_url(bucket: str, storage_path: str) -> Optional[str]:
    base = _storage_base_url()
    if not base:
        return None
    path = storage_path.lstrip("/")
    return f"{base}/public/{bucket}/{path}"


def resolve_tutor_video_playable_url(
    *,
    db: Any,
    explicit_video_url: Any = None,
    video_bucket: Any = None,
    video_storage_path: Any = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (playable_url, resolved_bucket, resolved_path).

    `db` must provide create_signed_url(bucket, path, expires_in) like DatabaseService.
    """
    direct = _trim(explicit_video_url)
    b_meta = _trim(video_bucket)
    p_meta = _trim(video_storage_path)

    if direct and (direct.startswith("http://") or direct.startswith("https://")):
        return direct, b_meta, p_meta

    if direct and direct.startswith("storage://"):
        parsed = parse_storage_uri(direct)
        if parsed:
            bucket, path = parsed
            try:
                ttl = int(os.getenv("TUTOR_VIDEO_SIGNED_URL_TTL_SEC", "86400"))
            except (TypeError, ValueError):
                ttl = 86400
            ttl = max(60, min(604800, ttl))
            try:
                signed = db.create_signed_url(bucket, path, ttl)
                return signed, bucket, path
            except Exception:
                return None, bucket, path
        return None, b_meta, p_meta

    bucket = b_meta or _trim(os.getenv("HOMEWORK_VIDEO_BUCKET")) or _trim(config.COACH_FEEDBACK_VIDEO_BUCKET)
    path = p_meta
    if not bucket or not path:
        if direct:
            return direct, b_meta, p_meta
        return None, bucket, path

    is_public = os.getenv("HOMEWORK_VIDEO_BUCKET_PUBLIC", "false").strip().lower() == "true"
    if is_public:
        return _public_object_url(bucket, path), bucket, path

    try:
        ttl = int(os.getenv("TUTOR_VIDEO_SIGNED_URL_TTL_SEC", "86400"))
    except (TypeError, ValueError):
        ttl = 86400
    ttl = max(60, min(604800, ttl))
    try:
        signed = db.create_signed_url(bucket, path.lstrip("/"), ttl)
        return signed, bucket, path.lstrip("/")
    except Exception:
        return None, bucket, path.lstrip("/")
