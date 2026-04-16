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
from urllib.parse import unquote, urlparse

from config import Config

from services.coach_video_storage import (
    coach_media_public_url,
    coach_videos_use_r2,
    presigned_get_coach_object,
)

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


def parse_r2_uri(uri: str) -> Optional[Tuple[str, str]]:
    text = (uri or "").strip()
    prefix = "r2://"
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


def _try_storage_bucket_path_from_http_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Supabase Storage links copied from the dashboard are often not playable in <video src>:
    /object/authenticated/... needs Authorization; public URLs may 403 if the bucket is private.
    Extract (bucket, object_path) so we can create a service-role signed URL.
    If the URL already looks like a signed link (token query), return None and use as-is.
    """
    text = _trim(url)
    if not text or not (text.startswith("http://") or text.startswith("https://")):
        return None
    try:
        parsed = urlparse(text)
    except Exception:
        return None
    path = parsed.path or ""
    q = (parsed.query or "").strip()
    if "/storage/v1/object/sign/" in path and "token=" in q:
        return None
    for prefix in (
        "/storage/v1/object/public/",
        "/storage/v1/object/authenticated/",
    ):
        if path.startswith(prefix):
            rest = path[len(prefix) :]
            if "/" not in rest:
                return None
            bucket, obj = rest.split("/", 1)
            bucket = unquote(bucket.strip())
            obj = unquote(obj.lstrip("/"))
            if bucket and obj:
                return bucket, obj
    if path.startswith("/storage/v1/object/sign/"):
        rest = path[len("/storage/v1/object/sign/") :]
        if "/" not in rest:
            return None
        bucket, obj = rest.split("/", 1)
        bucket = unquote(bucket.strip())
        obj = unquote(obj.lstrip("/"))
        if bucket and obj and not q:
            return bucket, obj
    return None


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
        ref = _try_storage_bucket_path_from_http_url(direct)
        if ref:
            bucket, path = ref
            try:
                ttl = int(os.getenv("TUTOR_VIDEO_SIGNED_URL_TTL_SEC", "86400"))
            except (TypeError, ValueError):
                ttl = 86400
            ttl = max(60, min(604800, ttl))
            try:
                signed = presigned_get_coach_object(bucket, path, ttl, supabase_db=db)
                if signed:
                    return signed, bucket, path
            except Exception:
                pass
        return direct, b_meta, p_meta

    if direct and direct.startswith("r2://"):
        parsed = parse_r2_uri(direct)
        if parsed:
            bucket, path = parsed
            try:
                ttl = int(os.getenv("TUTOR_VIDEO_SIGNED_URL_TTL_SEC", "86400"))
            except (TypeError, ValueError):
                ttl = 86400
            ttl = max(60, min(604800, ttl))
            try:
                if coach_videos_use_r2():
                    signed = presigned_get_coach_object(bucket, path, ttl, supabase_db=db)
                else:
                    signed = None
                if signed:
                    return signed, bucket, path
            except Exception:
                return None, bucket, path
        return None, b_meta, p_meta

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
                signed = presigned_get_coach_object(bucket, path, ttl, supabase_db=db)
                if signed:
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
        if coach_videos_use_r2():
            pub = coach_media_public_url(path)
            if pub:
                return pub, bucket, path
        else:
            supa_pub = _public_object_url(bucket, path)
            if supa_pub:
                return supa_pub, bucket, path

    try:
        ttl = int(os.getenv("TUTOR_VIDEO_SIGNED_URL_TTL_SEC", "86400"))
    except (TypeError, ValueError):
        ttl = 86400
    ttl = max(60, min(604800, ttl))
    try:
        signed = presigned_get_coach_object(bucket, path.lstrip("/"), ttl, supabase_db=db)
        if signed:
            return signed, bucket, path.lstrip("/")
    except Exception:
        pass
    return None, bucket, path.lstrip("/")
