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
