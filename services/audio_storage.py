"""Cloudflare R2 storage for user-recorded interview audio.

This module is the single source of truth for where interview-turn
audio bytes and concat'd session recordings live. It is intentionally
separate from services.coach_video_storage because audio and video are
different content types with different access policies, retention
needs, and access patterns:

    coach_videos (R2 bucket: coach_feedback_videos)
        - Coach-authored feedback videos
        - Long-lived, manually curated
        - Public marketing/coaching content

    user-interview-audio (R2 bucket: user-interview-audio)
        - User-recorded interview turn audio + concat'd full sessions
        - Auto-generated per session, high write rate
        - Sensitive (user voice) — eligible for stricter access controls

Before this module existed the codebase had been routing audio through
``coach_video_storage`` as a temporary measure during the R2 migration,
which coupled two unrelated subsystems. Every reader that still pointed
at Supabase Storage surfaced as a separate StorageException cascade
when the upload destination flipped to R2. Centralising the audio
backend here removes the cascade for good — there's exactly one helper
module for audio, and audio call sites that use it can't drift out of
sync.

Production config (Railway env vars):
    R2_ACCOUNT_ID           — same R2 account as coach videos
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_AUDIO_BUCKET_NAME    — e.g. "user-interview-audio"
    R2_AUDIO_PUBLIC_BASE_URL — e.g. "https://pub-<hash>.r2.dev"

Dev fallback (R2_AUDIO_BUCKET_NAME unset): falls back to Supabase Storage
at ``config.AUDIO_BUCKET_NAME`` ("audio_recordings"), matching the
codebase's pre-migration default so local development keeps working
without R2 credentials.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_cfg = None
_s3_client = None


def _config():
    global _cfg
    if _cfg is None:
        from config import Config

        _cfg = Config()
    return _cfg


def audio_storage_use_r2() -> bool:
    """True when R2 is fully configured for audio (production path).

    All four env vars must be present for us to consider R2 enabled —
    missing any one means we fall back to Supabase Storage so devs
    without R2 credentials can still run interviews locally.
    """
    c = _config()
    return bool(
        (getattr(c, "R2_ACCOUNT_ID", None) or "").strip()
        and (getattr(c, "R2_ACCESS_KEY_ID", None) or "").strip()
        and (getattr(c, "R2_SECRET_ACCESS_KEY", None) or "").strip()
        and (getattr(c, "R2_AUDIO_BUCKET_NAME", None) or "").strip()
    )


def audio_bucket_name() -> str:
    """R2 bucket name for audio. Empty string when R2 isn't configured."""
    return (getattr(_config(), "R2_AUDIO_BUCKET_NAME", None) or "").strip()


def _client():
    """Cached boto3 S3 client targeting Cloudflare R2.

    The client itself is bucket-agnostic — same credentials work for
    every bucket on the same R2 account. We keep our own cached
    instance (rather than importing services.coach_video_storage's)
    so the two storage subsystems stay independently testable and
    so a future refactor of either doesn't risk breaking the other.
    """
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


def audio_public_url(key: str) -> Optional[str]:
    """Build a stable HTTPS URL for the audio object at ``key``.

    Used to populate snippet rows' ``audio_segment_path`` with a value
    the browser can stream directly. Returns ``None`` if
    ``R2_AUDIO_PUBLIC_BASE_URL`` isn't configured (dev) — callers fall
    back to the bucket-relative key in that case, and signed-URL
    generation kicks in at read time.
    """
    base = (getattr(_config(), "R2_AUDIO_PUBLIC_BASE_URL", None) or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/{key.lstrip('/')}"


def put_audio_bytes(key: str, body: bytes, content_type: str) -> None:
    """Upload audio bytes to the configured backend.

    Production: R2 audio bucket via boto3.
    Dev fallback: Supabase Storage at ``AUDIO_BUCKET_NAME``.

    The bucket is implicit (audio always goes to the audio bucket).
    Callers should not pass it explicitly — that's exactly the coupling
    we removed by extracting this module.
    """
    key = key.lstrip("/")
    if audio_storage_use_r2():
        _client().put_object(
            Bucket=audio_bucket_name(),
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return
    # Dev fallback
    from services.db import db

    db.upload_audio(_config().AUDIO_BUCKET_NAME, key, body, content_type)


def get_audio_bytes(key: str) -> bytes:
    """Download audio bytes from the configured backend.

    Mirror of ``put_audio_bytes``: production reads R2, dev reads
    Supabase Storage. Callers don't choose the backend; they just hand
    over the bucket-relative key and trust the helper.
    """
    key = key.lstrip("/")
    if audio_storage_use_r2():
        r = _client().get_object(Bucket=audio_bucket_name(), Key=key)
        return r["Body"].read()
    from services.db import db

    return db.download_audio(_config().AUDIO_BUCKET_NAME, key)
