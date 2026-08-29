"""Storage for willab Lab audio — the user's own takes.

WHY THIS MODULE EXISTS (P0 audit, founder 2026-08-03)
-----------------------------------------------------
Lab takes were being written to ``coach_feedback_videos``. That started
as a transport shortcut and turned into a data-separation problem:

  * ``coach_feedback_videos`` is the COACH's content — feedback videos
    and reference material, long-lived, curated, effectively public
    (``R2_PUBLIC_BASE_URL`` serves it).
  * Lab takes are the USER's voice. Sensitive, per-user, subject to
    deletion requests, and on a different retention clock.

Worse, the separation was already fictional in production:
``coach_video_storage.put_coach_object_bytes(bucket, ...)`` IGNORES its
``bucket`` argument whenever R2 is configured — it always writes
``r2_bucket_name()``. So passing ``"coach_feedback_videos"`` vs anything
else changed nothing: every take, every coach video, every extracted PDF
and every learning artifact landed in ONE bucket, under one access
policy, with one lifecycle rule. Real segregation needs a real second
bucket, which is what this module targets.

HOW THE CUTOVER IS SAFE
-----------------------
Flipping a storage destination on a live product is exactly the kind of
change that breaks the loop, so this one is inert until deliberately
switched on:

  WRITES go to the lab bucket ONLY when both ``R2_LAB_AUDIO_BUCKET`` and
  ``R2_LAB_AUDIO_PUBLIC_BASE_URL`` are set. Missing either one and every
  call behaves exactly as before (coach bucket, coach public base). The
  public-base half of that condition is load-bearing: writing to a new
  bucket while still minting URLs against the OLD public domain produces
  rows whose ``audio_url`` 404s on playback.

  READS never assume. ``get_lab_audio_bytes`` tries the lab bucket, then
  the coach bucket, then the interview-audio bucket. Objects written
  before the flip stay exactly where they are — there is no migration to
  run and no window where old takes are unreadable. That also makes the
  flip reversible: unset the env vars and new writes go back to the old
  bucket while everything written meanwhile still reads.

So merging this changes nothing observable. Provisioning the bucket and
setting the two vars is the actual cutover, and it is a Railway-side
action (see docs/OPS-SECRETS-AND-STAGING.md).
"""
from __future__ import annotations

import hashlib
import logging
import posixpath
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_cfg = None


def _config():
    global _cfg
    if _cfg is None:
        from config import Config

        _cfg = Config()
    return _cfg


def _reset_config_cache() -> None:
    """Test hook — drop the memoised Config so env changes take effect."""
    global _cfg
    _cfg = None


def lab_audio_bucket() -> str:
    """The dedicated lab-audio bucket name, or "" when unconfigured."""
    return (getattr(_config(), "R2_LAB_AUDIO_BUCKET", None) or "").strip()


def coach_bucket() -> str:
    """The legacy destination — where lab audio lived before the split."""
    c = _config()
    return (getattr(c, "COACH_FEEDBACK_VIDEO_BUCKET", None)
            or "coach_feedback_videos").strip()


def lab_audio_segregated() -> bool:
    """True when NEW lab audio should go to its own bucket.

    Requires the bucket AND its public base URL (see the module docstring
    on why the URL half matters), plus the shared R2 credentials — with
    no R2 the process is on the Supabase dev fallback, where
    ``put_coach_object_bytes`` does honour its bucket argument and the
    split needs no new machinery.
    """
    from services.coach_video_storage import coach_videos_use_r2

    return bool(
        lab_audio_bucket()
        and (getattr(_config(), "R2_LAB_AUDIO_PUBLIC_BASE_URL", None) or "").strip()
        and coach_videos_use_r2()
    )


def target_bucket() -> str:
    """Bucket that a write RIGHT NOW would land in.

    Persist this alongside the object key (the pipeline job payload does)
    so a later read knows where to look first.
    """
    if lab_audio_segregated():
        return lab_audio_bucket()
    from services.coach_video_storage import (
        coach_videos_use_r2, r2_bucket_name,
    )

    return r2_bucket_name() if coach_videos_use_r2() else coach_bucket()


def storage_provider() -> str:
    """Provider used by a write at this instant."""
    from services.coach_video_storage import coach_videos_use_r2

    return "r2" if coach_videos_use_r2() else "supabase"


def _client():
    """boto3 client for the lab bucket.

    Same credentials as coach media — one R2 account, several buckets —
    but its own cached client so neither subsystem's config changes can
    surprise the other.
    """
    import boto3
    from botocore.config import Config as BotoConfig

    c = _config()
    account = (getattr(c, "R2_ACCOUNT_ID", None) or "").strip()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=(getattr(c, "R2_ACCESS_KEY_ID", None) or "").strip(),
        aws_secret_access_key=(getattr(c, "R2_SECRET_ACCESS_KEY", None) or "").strip(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )


def lab_audio_public_url(key: str) -> Optional[str]:
    """Stable HTTPS URL for a lab-audio object.

    Points at the LAB public base once segregation is on, and at the
    coach base before that — matching wherever the bytes actually are.
    ``None`` when neither base is configured (dev), where callers already
    fall back to an ``s3://`` marker and signed URLs at read time.
    """
    c = _config()
    if lab_audio_segregated():
        base = (getattr(c, "R2_LAB_AUDIO_PUBLIC_BASE_URL", None) or "").strip()
    else:
        base = (getattr(c, "R2_PUBLIC_BASE_URL", None) or "").strip()
    base = base.rstrip("/")
    if not base:
        return None
    return f"{base}/{key.lstrip('/')}"


def put_lab_audio_bytes(key: str, body: bytes, content_type: str) -> str:
    """Store lab audio. Returns the bucket it actually landed in.

    The return value is the point: callers persist it (recording rows,
    queue payloads) so reads don't have to guess, and so objects written
    either side of the cutover stay individually addressable.
    """
    key = key.lstrip("/")
    if lab_audio_segregated():
        bucket = lab_audio_bucket()
        _client().put_object(Bucket=bucket, Key=key, Body=body,
                             ContentType=content_type)
        return bucket
    # Pre-cutover (or no R2): unchanged behaviour, unchanged destination.
    from services.coach_video_storage import put_coach_object_bytes

    bucket = target_bucket()
    put_coach_object_bytes(bucket, key, body, content_type)
    return bucket


def _candidate_buckets(bucket_hint: Optional[str]) -> list:
    """Buckets to try, in order, with duplicates dropped.

    Hint first (what the row says), then the lab bucket, then the coach
    bucket, then the interview-audio bucket — the last one because some
    lab-derived snippet clips were written through
    ``services.audio_storage`` during the R2 migration.
    """
    from services.audio_storage import audio_bucket_name

    ordered = [
        (bucket_hint or "").strip(),
        lab_audio_bucket(),
        coach_bucket(),
        (audio_bucket_name() or "").strip(),
    ]
    seen: set = set()
    out = []
    for b in ordered:
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


def get_lab_audio_bytes(key: str, *, bucket_hint: Optional[str] = None) -> bytes:
    """Fetch lab audio, trying every bucket it could plausibly be in.

    A miss in one bucket is NOT an error — it's the expected outcome for
    an object written on the other side of the cutover. Only exhausting
    every candidate raises, and the raised error names the key and the
    buckets tried (no credentials, no URLs) so the log line is actionable.
    """
    key = key.lstrip("/")
    if not key:
        raise ValueError("key is required")

    from services.coach_video_storage import (
        coach_videos_use_r2, get_coach_object_bytes,
    )

    tried: list[Tuple[str, str]] = []
    for bucket in _candidate_buckets(bucket_hint):
        try:
            if coach_videos_use_r2():
                r = _client().get_object(Bucket=bucket, Key=key)
                data = r["Body"].read()
            else:
                # Supabase dev fallback honours the bucket argument.
                data = get_coach_object_bytes(bucket, key)
            if data:
                return data
            tried.append((bucket, "empty"))
        except Exception as exc:
            tried.append((bucket, type(exc).__name__))
            continue

    detail = ", ".join(f"{b}({why})" for b, why in tried) or "no buckets configured"
    raise FileNotFoundError(f"lab audio {key!r} not found — tried: {detail}")


def get_exact_storage_object_bytes(
    key: str, *, bucket: str, storage_provider: str,
) -> bytes:
    """Read exactly one provider/bucket/key without compatibility fallback."""
    key = key.lstrip("/")
    bucket = (bucket or "").strip()
    if not key or not bucket:
        raise ValueError("exact bucket and object key are required")
    provider = (storage_provider or "").strip().lower()
    if provider == "r2":
        return _client().get_object(Bucket=bucket, Key=key)["Body"].read()
    if provider == "supabase":
        from services.db import db

        return db.client.storage.from_(bucket).download(key)
    raise ValueError("unsupported storage provider")


def delete_verified_lab_audio_object(
    key: str, *, bucket: str, storage_provider: str,
    expected_sha256: str,
) -> bool:
    """Delete one exact object only after byte-hash verification.

    No fallback bucket search is allowed here. A purge inventory identifies
    one provider/bucket/key, and the expected SHA-256 must match the bytes at
    those coordinates immediately before deletion. Authentication or network
    errors fail closed and are never treated as proof of absence.
    """
    key = key.lstrip("/")
    bucket = (bucket or "").strip()
    expected_sha256 = (expected_sha256 or "").strip().lower()
    if (not key or not bucket or len(expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha256)):
        raise ValueError("exact object coordinates and SHA-256 are required")
    provider = (storage_provider or "").strip().lower()
    if provider == "r2":
        client = _client()
        before = get_exact_storage_object_bytes(
            key, bucket=bucket, storage_provider=provider,
        )
        if hashlib.sha256(before).hexdigest() != expected_sha256:
            raise ValueError("object checksum does not match purge inventory")
        client.delete_object(Bucket=bucket, Key=key)
        try:
            client.head_object(Bucket=bucket, Key=key)
        except Exception as error:
            response = getattr(error, "response", {}) or {}
            status = (response.get("ResponseMetadata") or {}).get(
                "HTTPStatusCode"
            )
            code = str((response.get("Error") or {}).get("Code") or "")
            if status == 404 and code in ("404", "NoSuchKey", "NotFound"):
                return True
            raise
        return False
    if provider == "supabase":
        from services.db import db

        storage = db.client.storage.from_(bucket)
        before = get_exact_storage_object_bytes(
            key, bucket=bucket, storage_provider=provider,
        )
        if hashlib.sha256(before).hexdigest() != expected_sha256:
            raise ValueError("object checksum does not match purge inventory")
        removed = storage.remove([key])
        if removed is None:
            raise RuntimeError("storage provider did not acknowledge deletion")
        folder, name = posixpath.split(key)
        listing = storage.list(folder, {"search": name, "limit": 100})
        names = {
            str(item.get("name") or "")
            for item in (listing or []) if isinstance(item, dict)
        }
        return name not in names
    raise ValueError("unsupported storage provider")
