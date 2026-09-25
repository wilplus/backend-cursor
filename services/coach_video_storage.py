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

from services.r2_client import build_r2_client, clamp_ttl
from services.user_content_keys import is_user_content_key

logger = logging.getLogger(__name__)

_cfg = None
_s3_client = None

#: TTL for a deck/user-content ref re-signed on read. A week, which is the
#: clamp maximum — see refreshed_media_url for why it is generous rather than
#: tight. It is NOT a storage lifetime: the signature is re-minted on every
#: read, so this only has to outlast a single sitting with the document open.
_DECK_REF_TTL = 604800


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


def require_coach_video_r2() -> str:
    """Return the configured R2 bucket for service-mode coach media."""
    if not coach_videos_use_r2():
        raise RuntimeError("MLC3_R2_COACH_MEDIA_NOT_CONFIGURED")
    bucket = (getattr(_config(), "R2_BUCKET_NAME", None) or "").strip()
    if not bucket:
        raise RuntimeError("MLC3_R2_COACH_MEDIA_BUCKET_NOT_CONFIGURED")
    return bucket


def put_coach_object_r2_bytes(
    bucket: str, key: str, body: bytes, content_type: str,
) -> None:
    required_bucket = require_coach_video_r2()
    if bucket.strip() != required_bucket:
        raise RuntimeError("MLC3_R2_COACH_MEDIA_BUCKET_MISMATCH")
    _client().put_object(
        Bucket=required_bucket,
        Key=key.lstrip("/"),
        Body=body,
        ContentType=content_type,
    )


def get_coach_object_r2_bytes(bucket: str, key: str) -> bytes:
    required_bucket = require_coach_video_r2()
    if bucket.strip() != required_bucket:
        raise RuntimeError("MLC3_R2_COACH_MEDIA_BUCKET_MISMATCH")
    response = _client().get_object(
        Bucket=required_bucket,
        Key=key.lstrip("/"),
    )
    return response["Body"].read()


def presigned_get_coach_object_r2(
    bucket: str, key: str, expires_in: int = 3600,
) -> str:
    required_bucket = require_coach_video_r2()
    if bucket.strip() != required_bucket:
        raise RuntimeError("MLC3_R2_COACH_MEDIA_BUCKET_MISMATCH")
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": required_bucket, "Key": key.lstrip("/")},
        ExpiresIn=_clamp_ttl(expires_in),
    )


def r2_bucket_name() -> str:
    """R2 Bucket name (S3 API). Falls back to COACH_FEEDBACK_VIDEO_BUCKET."""
    c = _config()
    return ((getattr(c, "R2_BUCKET_NAME", None) or "").strip() or c.COACH_FEEDBACK_VIDEO_BUCKET).strip()


def coach_media_public_url(storage_key: str) -> Optional[str]:
    """Always ``None``: nothing in these buckets gets a public URL any more.

    FOUNDER 2026-09-25, decision 4: both buckets go private (DPIA RISK-11,
    M11.4). A public URL is permanent, unauthenticated and unrevocable; user
    content stopped getting one on 2026-09-17/18, and coach-authored media
    kept it only because the buckets were public anyway. With them private a
    public URL would simply fail, so no caller is handed one.

    Every caller already handles ``None`` — each falls back to a presigned GET
    or an ``s3://bucket/key`` marker — and every read re-signs from the key
    (``refreshed_media_url``, ``resolve_playable_ref``), so a stored ref never
    has to stay valid. Kept as a function so those call sites read the same.
    """
    del storage_key
    return None


def refreshed_media_url(ref: Optional[str]) -> Optional[str]:
    """Re-sign a STORED media ref from its key, fresh, on every read.

    Four shapes reach this (see ``media_key_from_ref``): a presigned GET, a
    URL on one of our public bases, an ``s3://`` marker, a bare key. Each is
    ours, so each comes back as a new presigned GET for the same object in
    the same bucket. Anything else — a Supabase signed URL, a foreign URL, a
    malformed value — is returned untouched. Never a guess.

    HISTORY. Written 2026-09-16 for the deck blackout (a 7-day presigned URL
    written once and read forever went dark), when it re-pointed presigned
    refs at the permanent public URL. User content moved to signing on
    2026-09-17/18 (DPIA RISK-11). Founder 2026-09-25, decision 4: both
    buckets go private, so coach-authored media signs too and no public URL
    is produced at all.

    Pure apart from reading config. Repairs on READ, so no backfill runs
    against rows nobody is looking at.
    """
    if not ref or not isinstance(ref, str):
        return ref
    raw = ref.strip()
    try:
        key = media_key_from_ref(raw)
        # EVERY OBJECT OF OURS SIGNS (founder 2026-09-25, decision 4). Until
        # the buckets went private only user content did, and coach-authored
        # media kept its permanent public URL — which stops working the moment
        # the bucket is private. A bare value signs only when it is a
        # user-content key, as before: anything else bare may not be a key at
        # all. A foreign ref has no key and passes through.
        explicit = raw.startswith("s3://") or raw.lower().startswith(("http://", "https://"))
        if key and (explicit or is_user_content_key(key)):
            # USER CONTENT SIGNS, AND SIGNS FRESH (DPIA RISK-11, decks added
            # 2026-09-18). A new signature is minted from the KEY on every
            # read, so nothing depends on a stored URL staying valid — which
            # is the actual root cause of the September deck blackout, not
            # the TTL that got blamed for it.
            #
            # DECK_REF_TTL rather than the resolver's six hours: PDF.js
            # streams a document with lazy range requests, so it can ask for
            # bytes long after the page loaded, and the FE's "Retry loading
            # slides" button re-fetches the SAME url instead of asking the
            # API for a fresh ref — so an expired signature is a dead end
            # until the user reloads the route. A week of headroom on a URL
            # that is re-minted every read costs nothing and removes that
            # whole class of report.
            #
            # THE BUCKET COMES FROM THE REF, NOT THE DEFAULT (2026-09-18).
            # Passing "" here signed every ref against the coach bucket, so a
            # ref minted on any of the four other public bases became a valid
            # signature over a key that bucket does not hold — a 404 in place
            # of a URL that had been working. `media_ref_bucket` returns None
            # when it cannot place the ref, and "" keeps today's default.
            return presigned_get_coach_object(
                media_ref_bucket(raw) or "", key, expires_in=_DECK_REF_TTL,
            ) or ref
        # Not ours to re-address: a Supabase signed URL, a foreign URL, junk.
        return ref
    except Exception:  # pragma: no cover - a malformed ref stays as it was
        return ref


def _strip_leading_bucket(path: str) -> str:
    """R2's S3 endpoint is path-style: ``/<bucket>/<key>``. Strip the bucket
    only when it really is the leading segment — a key that merely starts with
    the same letters must not lose them."""
    bucket = r2_bucket_name()
    if bucket and path.startswith(bucket + "/"):
        return path[len(bucket) + 1:]
    return path


def media_key_from_ref(ref: Any) -> Optional[str]:
    """The object key behind a stored media ref, whatever shape it was written
    in. ``None`` when the ref is not ours to re-address.

    Four shapes reach this, and they were written by different code in
    different months:

    ``https://<s3-endpoint>/<bucket>/<key>?X-Amz-Signature=…``  a presigned GET
    ``https://<public base>/<key>``                             a public URL
    ``s3://<bucket>/<key>``                                     the CONFIG-FIRST marker
    ``<key>``                                                   a bare key

    A FOREIGN https URL returns ``None`` — imports store other people's URLs,
    and re-addressing one against our bucket breaks it. That is the whole
    reason this returns ``None`` rather than guessing a key out of any path it
    is handed.
    """
    if not isinstance(ref, str):
        return None
    raw = ref.strip()
    if not raw:
        return None
    if raw.startswith("s3://"):
        rest = raw[len("s3://"):]
        _, _, key = rest.partition("/")
        return key or None
    if not raw.lower().startswith(("http://", "https://")):
        return raw.lstrip("/") or None
    from urllib.parse import urlsplit

    parts = urlsplit(raw)
    path = (parts.path or "").lstrip("/")
    if not path:
        return None
    if "x-amz-signature=" in (parts.query or "").lower():
        return _strip_leading_bucket(path) or None
    # A public URL, but only on a base WE mint on. Anything else is foreign.
    host = f"{parts.scheme}://{parts.netloc}"
    for base in _our_public_bases():
        if raw.startswith(base + "/"):
            return raw[len(base) + 1:].split("?", 1)[0] or None
        if base == host:
            return path or None
    return None


#: Each public base and the bucket it actually serves. A public development
#: domain belongs to ONE bucket, so the base a stored ref was minted on is what
#: names the bucket its key lives in. "" means the coach default, which
#: `r2_bucket_name()` resolves (R2_BUCKET_NAME, else COACH_FEEDBACK_VIDEO_BUCKET).
_PUBLIC_BASE_BUCKETS: tuple = (
    ("R2_PUBLIC_BASE_URL", ""),
    ("R2_AUDIO_PUBLIC_BASE_URL", "R2_AUDIO_BUCKET_NAME"),
    ("R2_LAB_AUDIO_PUBLIC_BASE_URL", "R2_LAB_AUDIO_BUCKET"),
    ("R2_JOURNAL_PUBLIC_BASE_URL", "R2_JOURNAL_BUCKET"),
    ("R2_USER_MEDIA_PUBLIC_BASE_URL", "R2_USER_MEDIA_BUCKET"),
)


def _our_public_bases() -> list:
    c = _config()
    bases = []
    for attr, _bucket_attr in _PUBLIC_BASE_BUCKETS:
        value = (getattr(c, attr, None) or "").strip().rstrip("/")
        if value:
            bases.append(value)
    return bases


def media_ref_bucket(ref: Any) -> Optional[str]:
    """The bucket a stored ref's key lives in, or ``None`` for the default.

    SIGN AGAINST THE RIGHT BUCKET (2026-09-18). `refreshed_media_url` re-signs
    user content from its KEY, and it was signing every one of them against the
    coach bucket — because `media_key_from_ref` returns a key and throws the
    bucket away. A ref minted on the lab-audio, journal or user-media public
    base names a key that does not exist in the coach bucket, so the refreshed
    URL is a well-formed signature over nothing and R2 answers 404.

    Five public bases exist and each belongs to exactly one bucket, so the base
    a ref was written on IS the answer. Path-style presigned refs carry the
    bucket in the first path segment and are read from there. Anything this
    cannot place returns ``None``, and the caller keeps the default rather than
    guessing a bucket.
    """
    if not isinstance(ref, str):
        return None
    raw = ref.strip()
    if not raw:
        return None
    if raw.startswith("s3://"):
        bucket, _, _key = raw[len("s3://"):].partition("/")
        return bucket.strip() or None
    if not raw.lower().startswith(("http://", "https://")):
        return None
    from urllib.parse import urlsplit

    parts = urlsplit(raw)
    if "x-amz-signature=" in (parts.query or "").lower():
        # Path-style: /<bucket>/<key>. Only claimed when a key follows, so a
        # bucket-only URL cannot be mistaken for one.
        head, sep, _rest = (parts.path or "").lstrip("/").partition("/")
        return head if sep and head else None
    c = _config()
    host = f"{parts.scheme}://{parts.netloc}"
    for attr, bucket_attr in _PUBLIC_BASE_BUCKETS:
        base = (getattr(c, attr, None) or "").strip().rstrip("/")
        if not base or not (raw.startswith(base + "/") or base == host):
            continue
        if not bucket_attr:
            return None     # the coach default; r2_bucket_name() owns it
        return (getattr(c, bucket_attr, None) or "").strip() or None
    return None


def _client():
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    _s3_client = build_r2_client(_config())
    return _s3_client


def _clamp_ttl(expires_in: int) -> int:
    return clamp_ttl(expires_in)


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
        b = (bucket or "").strip() or r2_bucket_name()
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
        b = (bucket or "").strip() or r2_bucket_name()
        _client().put_object(Bucket=b, Key=key, Body=body, ContentType=content_type)
        return
    from services.db import db

    db.upload_audio((bucket or "").strip() or r2_bucket_name(), key, body, content_type)


def get_coach_object_bytes(bucket: str, key: str) -> bytes:
    key = key.lstrip("/")
    if coach_videos_use_r2():
        b = (bucket or "").strip() or r2_bucket_name()
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
