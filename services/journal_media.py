"""Journal cover media — presigned direct-to-storage uploads (2026-07-25).

Covers (image / video / audio) are uploaded by the browser STRAIGHT to
Cloudflare R2 using a presigned PUT. The bytes never transit Flask and never
transit the Next BFF — that is a requirement, not an optimization: the FE runs
on Vercel, whose ~4.5MB serverless request-body limit already 413s on audio
uploads, and Journal video is far larger.

Flow:
  1. CMS  → POST /v2/internal/journal/media/presign {password, filename,
            content_type, kind}
  2. here → {upload_url, public_url, headers, key, expires_in}
  3. CMS  → PUT the file to `upload_url` with exactly the returned `headers`
  4. CMS  → save `public_url` on the post (cover_image_url / media_url)

An author pasting an external https:// URL skips all of this.

Same boto3/R2 client shape as services.user_media_storage (shared
R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY), pointed at the
journal bucket. Kept a separate module so Journal content lands in its own
bucket with its own public-read + cache policy, without threading bucket
plumbing through the user-media helpers.

Public surface:
  JournalMediaError            — configuration/validation failure (route maps
                                 it to 503 / 400).
  journal_media_use_r2()       — True iff full creds + bucket are configured.
  allowed_content_types(kind)  — the per-kind MIME allowlist.
  max_bytes_for(kind)          — the per-kind size cap.
  build_object_key(...)        — randomized, extension-preserving object key.
  presign_put(...)             — the presigned PUT + the eventual public URL.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_s3_client = None

# Per-kind MIME allowlists. Deliberately narrow: these files are served to
# the public from our domain, so "whatever the browser sent" is not a policy.
_ALLOWED: dict[str, tuple] = {
    "image": ("image/jpeg", "image/png", "image/webp", "image/avif"),
    "audio": ("audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg",
              "audio/wav"),
    "video": ("video/mp4", "video/webm", "video/quicktime"),
}

# Per-kind size caps (MB), overridable by env so a big launch video does not
# need a deploy. Defaults from the FE spec.
_DEFAULT_MAX_MB = {"image": 10, "audio": 50, "video": 500}

# Extension per MIME, so a randomized key keeps a sane suffix for CDNs and
# players that sniff on it.
_EXT_FOR_MIME = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/avif": ".avif",
    "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/webm": ".weba",
    "audio/ogg": ".ogg", "audio/wav": ".wav",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
}

_PRESIGN_TTL_SEC = 900   # 15 min: long enough for a large upload to start.


class JournalMediaError(RuntimeError):
    """Presign could not be issued. Message is safe to show the CMS author."""


def _config():
    from config import Config
    return Config


def journal_bucket_name() -> str:
    """Bucket the covers land in.

    Falls back to the user-media bucket (and then the coach bucket) so a dev
    environment without a dedicated Journal bucket still works — same
    fallback ladder as services.user_media_storage.
    """
    c = _config()
    for attr in ("R2_JOURNAL_BUCKET", "R2_USER_MEDIA_BUCKET", "R2_BUCKET_NAME"):
        bucket = (getattr(c, attr, None) or "").strip()
        if bucket:
            return bucket
    return (getattr(c, "COACH_FEEDBACK_VIDEO_BUCKET", None) or "").strip()


def journal_public_base_url() -> str:
    """Public base URL for the journal bucket (CDN or r2.dev), no trailing
    slash. Empty when unconfigured — presign then refuses, because an upload
    we cannot produce a public URL for would silently strand the file."""
    c = _config()
    for attr in ("R2_JOURNAL_PUBLIC_BASE_URL", "R2_USER_MEDIA_PUBLIC_BASE_URL",
                 "R2_PUBLIC_BASE_URL"):
        base = (getattr(c, attr, None) or "").strip()
        if base:
            return base.rstrip("/")
    return ""


def journal_media_use_r2() -> bool:
    """True iff full R2 credentials AND a bucket are configured."""
    c = _config()
    return all([
        (getattr(c, "R2_ACCOUNT_ID", None) or "").strip(),
        (getattr(c, "R2_ACCESS_KEY_ID", None) or "").strip(),
        (getattr(c, "R2_SECRET_ACCESS_KEY", None) or "").strip(),
        journal_bucket_name(),
    ])


def allowed_content_types(kind: Any) -> tuple:
    return _ALLOWED.get((kind or "").strip().lower(), ())


def max_bytes_for(kind: Any) -> int:
    """Per-kind cap in bytes. Env override: JOURNAL_MAX_IMAGE_MB etc."""
    k = (kind or "").strip().lower()
    default = _DEFAULT_MAX_MB.get(k, 10)
    raw = os.getenv(f"JOURNAL_MAX_{k.upper()}_MB")
    try:
        mb = int(raw) if raw else default
    except (TypeError, ValueError):
        mb = default
    return max(1, mb) * 1024 * 1024


def classify_kind(content_type: Any) -> Optional[str]:
    """'image' | 'audio' | 'video' from a MIME type, else None."""
    ct = (content_type or "").strip().lower()
    for kind, allowed in _ALLOWED.items():
        if ct in allowed:
            return kind
    return None


def build_object_key(kind: str, content_type: str,
                     filename: Any = None, folder: Any = None) -> str:
    """A randomized object key, extension preserved.

    The client filename is NEVER used as the key (path traversal, collisions,
    and leaking an author's local filenames on a public URL). It only informs
    the extension when the MIME map has no entry.

    ``folder`` overrides the path segment (defaults to the kind) so generated
    covers land under journal/generated/ and stay distinguishable from
    uploads in the bucket — the two have different lifecycles.
    """
    ext = _EXT_FOR_MIME.get((content_type or "").strip().lower())
    if not ext:
        guessed = mimetypes.guess_extension(
            (content_type or "").strip().lower() or "") or ""
        if not guessed and isinstance(filename, str) and "." in filename:
            tail = filename.rsplit(".", 1)[-1]
            # Only a plausible extension, never arbitrary client text.
            guessed = f".{tail.lower()}" if re.fullmatch(
                r"[a-z0-9]{1,5}", tail.lower()) else ""
        ext = guessed
    segment = (folder or kind or "misc").strip().strip("/") or "misc"
    return f"journal/{segment}/{uuid.uuid4().hex}{ext}"


def _client():
    """Lazy boto3 S3 client pointed at the R2 account (cached per process).
    Mirrors services.user_media_storage._client."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    import boto3
    from botocore.config import Config as BotoConfig

    c = _config()
    account = (getattr(c, "R2_ACCOUNT_ID", None) or "").strip()
    _s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=(getattr(c, "R2_ACCESS_KEY_ID", None) or "").strip(),
        aws_secret_access_key=(
            getattr(c, "R2_SECRET_ACCESS_KEY", None) or "").strip(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )
    return _s3_client


def presign_put(*, kind: Any, content_type: Any,
                filename: Any = None) -> dict:
    """Mint a presigned PUT for one cover file.

    Returns {upload_url, public_url, key, headers, expires_in, max_bytes}.
    The caller PUTs the bytes to `upload_url` with exactly `headers`, then
    stores `public_url` on the post.

    Raises JournalMediaError on: R2 unconfigured, no public base URL, an
    unknown `kind`, or a content_type outside the per-kind allowlist. The
    route maps those to 503 / 400 — it never returns a half-usable presign.
    """
    k = (kind or "").strip().lower()
    if k not in _ALLOWED:
        raise JournalMediaError(
            f"kind must be one of {', '.join(sorted(_ALLOWED))}"
        )
    ct = (content_type or "").strip().lower()
    if ct not in _ALLOWED[k]:
        raise JournalMediaError(
            f"content_type for {k} must be one of {', '.join(_ALLOWED[k])}"
        )
    if not journal_media_use_r2():
        raise JournalMediaError(
            "Journal media storage is not configured (R2 credentials or "
            "bucket missing)."
        )
    base = journal_public_base_url()
    if not base:
        # Refuse rather than hand back an upload URL whose file we could
        # never reference publicly.
        raise JournalMediaError(
            "Journal media storage has no public base URL configured "
            "(set R2_JOURNAL_PUBLIC_BASE_URL)."
        )

    bucket = journal_bucket_name()
    key = build_object_key(k, ct, filename)
    try:
        upload_url = _client().generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": ct},
            ExpiresIn=_PRESIGN_TTL_SEC,
        )
    except Exception as e:
        logger.warning("journal_media: presign failed bucket=%s key=%s: %s",
                       bucket, key, e)
        raise JournalMediaError("Could not create the upload URL.") from e

    return {
        "upload_url": upload_url,
        "public_url": f"{base}/{key}",
        "key": key,
        # ContentType is part of the signature — the PUT must send it back
        # verbatim or R2 rejects the request with SignatureDoesNotMatch.
        "headers": {"Content-Type": ct},
        "expires_in": _PRESIGN_TTL_SEC,
        "max_bytes": max_bytes_for(k),
    }


def put_bytes(*, data: Any, content_type: str, folder: str = "generated",
              kind: str = "image") -> dict:
    """Upload bytes we already hold, server-side. Returns {public_url, key}.

    The presign flow above exists because a browser upload must not transit
    Flask. This one is the opposite case: a GENERATED cover arrives as base64
    in our own process (services/journal_image.py), so it is already here and
    a presign would mean handing it back to the browser to re-upload.

    Same bucket, same public base, same content-type allowlist. Raises
    JournalMediaError on unconfigured storage, a disallowed type, an empty
    body, or a file over the per-kind cap — the route maps those to 503 / 400.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise JournalMediaError("No image data to store.")
    ct = (content_type or "").strip().lower()
    if ct not in _ALLOWED.get(kind, ()):
        raise JournalMediaError(
            f"content_type for {kind} must be one of "
            f"{', '.join(_ALLOWED.get(kind, ()))}"
        )
    cap = max_bytes_for(kind)
    if len(data) > cap:
        raise JournalMediaError(
            f"The image is larger than the {cap // (1024 * 1024)}MB limit.")
    if not journal_media_use_r2():
        raise JournalMediaError(
            "Journal media storage is not configured (R2 credentials or "
            "bucket missing)."
        )
    base = journal_public_base_url()
    if not base:
        raise JournalMediaError(
            "Journal media storage has no public base URL configured "
            "(set R2_JOURNAL_PUBLIC_BASE_URL)."
        )

    bucket = journal_bucket_name()
    key = build_object_key(kind, ct, folder=folder)
    try:
        _client().put_object(
            Bucket=bucket, Key=key, Body=bytes(data), ContentType=ct,
            # Keys are random and content never changes under one, so the
            # object is immutable by construction.
            CacheControl="public, max-age=31536000, immutable",
        )
    except Exception as e:
        logger.warning("journal_media: put_bytes failed bucket=%s key=%s: %s",
                       bucket, key, e)
        raise JournalMediaError("Could not store the image.") from e

    return {"public_url": f"{base}/{key}", "key": key}
