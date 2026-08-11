"""One storage ref → something an <audio src> can play (founder
2026-08-10: master playback dead on the user surfaces).

PR #378 fixed exactly one call site — the coach confidence queue. The
snippet writer's ``s3://bucket/key`` FALLBACK refs — written whenever a
service is missing its public-URL env (per-service config, the
CONFIG-FIRST class) — were signed against the wrong bucket, 404ed, and
the player rendered dead. Every OTHER surface kept handing the raw
column through: the slide-take viewer, the library, the readouts, the
game rounds. This module is that one bucket-authoritative branch,
hoisted, so every consumer resolves the same way and the next surface
cannot re-introduce the bug by forgetting it.

The CONFIG root cause stays open and is not this module's to fix: set
the public-URL base vars on EVERY Railway service (worker included) and
verify from each service's boot log. This resolver is the belt that
keeps already-written rows — and the next env miss — playable.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRES = 6 * 3600


def _public_base_buckets() -> list:
    """[(public_base, bucket)] for every base this codebase mints URLs on.

    The pairing is the writers' own: lab_audio_public_url mints on
    R2_LAB_AUDIO_PUBLIC_BASE_URL (lab bucket) when segregation is on and on
    R2_PUBLIC_BASE_URL (the coach bucket, R2_BUCKET_NAME override honoured)
    otherwise; audio_storage mints on R2_AUDIO_PUBLIC_BASE_URL for
    R2_AUDIO_BUCKET_NAME. Empty config halves drop out. Best-effort — an
    unreadable config just means no re-signing, today's behavior."""
    try:
        from config import Config
        coach_bucket = str(
            (getattr(Config, "R2_BUCKET_NAME", "") or "").strip()
            or getattr(Config, "COACH_FEEDBACK_VIDEO_BUCKET", "")
            or "coach_feedback_videos")
        pairs = [
            (getattr(Config, "R2_LAB_AUDIO_PUBLIC_BASE_URL", "") or "",
             getattr(Config, "R2_LAB_AUDIO_BUCKET", "") or ""),
            (getattr(Config, "R2_PUBLIC_BASE_URL", "") or "", coach_bucket),
            (getattr(Config, "R2_AUDIO_PUBLIC_BASE_URL", "") or "",
             getattr(Config, "R2_AUDIO_BUCKET_NAME", "") or ""),
        ]
        return [(b.strip().rstrip("/"), k.strip())
                for b, k in pairs if b.strip() and k.strip()]
    except Exception:
        return []


def _sign(bucket: str, key: str, expires_in: int):
    try:
        from services.coach_video_storage import presigned_get_coach_object
        return presigned_get_coach_object(bucket, key,
                                          expires_in=expires_in)
    except Exception as e:
        logger.warning("resolve_playable_ref: could not sign %s/%s: %s",
                       bucket, key, e)
        return None


def resolve_playable_ref(ref: Any, *, expires_in: int = _DEFAULT_EXPIRES,
                         default_bucket: Optional[str] = None
                         ) -> Optional[str]:
    """Resolve one ref. http(s) passes through untouched; ``s3://bucket/
    key`` is signed against ITS OWN bucket (the ref is authoritative —
    assuming a bucket is how #378's bug happened); a bare key signs
    against ``default_bucket`` (the coach video bucket when unset). On
    any signing failure the INPUT comes back unchanged — a visible dead
    ref is debuggable, a silently nulled one is not. None/'' → None."""
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith("http://") or ref.startswith("https://"):
        # OUR OWN public bases are not trusted blindly (founder 2026-08-11:
        # every Feedbacks-review player dead while the env was set all
        # along). A writer with the base configured mints
        # `{base}/{key}` URLs whether or not the bucket actually SERVES
        # that base — R2 only answers on a public base once the bucket's
        # dev URL is enabled or a custom domain is attached, so a healthy-
        # looking row can 403 on every play. A ref sitting on a base we
        # minted is re-signed against that base's own bucket; signing works
        # on any bucket in the account regardless of public access. A
        # foreign https URL (imports store external ones) passes through
        # untouched, and an already-signed URL lives on the S3 endpoint
        # domain, which is not a configured base, so it never re-signs.
        for base, base_bucket in _public_base_buckets():
            if ref.startswith(base + "/"):
                key = ref[len(base) + 1:].split("?", 1)[0]
                signed = _sign(base_bucket, key, expires_in)
                return signed or ref
        return ref
    try:
        from config import Config
        from services.coach_video_storage import presigned_get_coach_object
        bucket = str(
            default_bucket
            or getattr(Config, "COACH_FEEDBACK_VIDEO_BUCKET", "")
            or "coach_feedback_videos")
    except Exception:
        return ref
    if "://" in ref:
        rest = ref.split("://", 1)[-1]
        ref_bucket, _, ref_key = rest.partition("/")
        use_bucket, key = ((ref_bucket, ref_key) if ref_key
                           else (bucket, rest))
    else:
        use_bucket, key = bucket, ref
        if key.startswith(f"{bucket}/"):
            key = key[len(bucket) + 1:]
    try:
        signed = presigned_get_coach_object(use_bucket, key,
                                            expires_in=expires_in)
        return signed or ref
    except Exception as e:
        logger.warning("resolve_playable_ref: could not sign %s: %s",
                       ref, e)
        return ref
