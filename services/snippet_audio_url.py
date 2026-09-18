"""One playable audio URL for a snippet row, signed rather than public.

MOVED OUT OF routes/v2/common.py 2026-09-17, when the route fence caught it at
88 lines. The fence is right: this is resolution logic with a storage decision
in it, not request handling, and two route modules need it. Leaving a second
copy in routes/v2/admin.py is how the two drift, and a drift here means a
recording served public on one surface and signed on the other — which is the
same as not signing it.

THE STORAGE DECISION (DPIA RISK-11). Everything these prefixes hold is a
recording of someone speaking. The buckets are served through Cloudflare public
development URLs, so a public URL for one is permanent, unauthenticated and
unrevocable once it leaves us. This module signs instead, and re-signs stored
public URLs on read so the rows already written are covered without a backfill.
See services/user_content_keys.py.

THE FOUR ROW SHAPES are carried over verbatim from the original docstring
because they are the reason this function is not a one-liner. They do not share
a code path, and a change verified against one of them is a change verified
against a quarter of the rows.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: storage_path values under this prefix live in Supabase Storage, not R2.
#: Student uploads went there; signing them against R2 404s every one.
_SUPABASE_ONLY_PREFIX = "charisma_snippets/"


def signed_r2_audio_url(ref: str) -> Optional[str]:
    """Sign one R2 ref — a bare key, an ``s3://bucket/key`` marker, or a URL
    on one of our own public bases — against the bucket it belongs to.

    ``None`` when it could not be signed. The underlying resolver returns its
    INPUT unchanged in that case, which is deliberate there (a visible dead ref
    is debuggable) and useless to a caller that has to put the result in an
    ``<audio src>``: a bare key is not playable. Collapsing "unchanged" to
    ``None`` is what lets callers fall through to the Supabase path instead of
    handing the browser something that cannot load.
    """
    try:
        from services.audio_ref_resolver import resolve_playable_ref
        from services.audio_storage import audio_bucket_name

        out = resolve_playable_ref(
            ref, default_bucket=audio_bucket_name() or None,
        )
    except Exception as exc:
        logger.warning("snippet audio URL: signing failed for %s: %s", ref, exc)
        return None
    if not out or out == ref:
        return None
    return out


def resolve_snippet_audio_url(snippet: Any, database: Any = None,
                              app_config: Any = None) -> Optional[str]:
    """Pick a playable audio URL from whichever column the writer used.

    The four snippet states we have to play through one <audio> element:
      - Path A pre-finalize: audio_segment_path = R2 URL for the per-turn
        .webm, storage_path NULL.
      - Path A post-finalize: storage_path = bucket-relative key of the
        concat'd session full.webm. audio_segment_path is left intact
        (historical record + idempotent re-finalize), but storage_path is what
        start_offset_ms / duration_ms are RELATIVE TO, so it must win.
      - Path B (extract_recording_snippets): audio_segment_path = full URL,
        storage_path NULL.
      - Path C (the ML snippet generator, DELETED 2026-08-10) and student
        uploads: storage_path set, audio_segment_path NULL. Path C rows
        already in the table still read through here, which is why this
        branch stays.

    Precedence is therefore: storage_path → audio_segment_path → None.
    Returning None means there's truly nothing playable. Keeping
    audio_segment_path as the fallback (rather than the primary) is what makes
    the per-turn → canonical-recording migration safe — the moment
    finalize_session_recording populates storage_path, the snippet flips from
    playing its per-turn file to playing a slice of the concat'd session
    audio, no DB cleanup required.
    """
    if database is None:
        from services.db import db as database
    if app_config is None:
        from config import Config

        app_config = Config()
    if not isinstance(snippet, dict):
        return None

    storage = (snippet.get("storage_path") or "").strip()
    if storage:
        if not storage.startswith(_SUPABASE_ONLY_PREFIX):
            signed = signed_r2_audio_url(storage)
            if signed:
                return signed
            # No R2 audio bucket configured (local dev) — fall through to the
            # Supabase signed-URL path so dev still works.
        try:
            return database.create_signed_url(
                app_config.AUDIO_BUCKET_NAME, storage,
                app_config.SIGNED_URL_EXPIRY_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "snippet audio URL: signed url failed for %s: %s — falling back",
                storage, exc,
            )
            # fall through to audio_segment_path

    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        # A lab writer missing its public-URL env leaves ``s3://bucket/key``
        # here (per-service config, the CONFIG-FIRST class). Handing that to
        # an <audio src> is the dead master/snippet player the founder hit
        # (2026-08-10) — resolve it the same bucket-authoritative way #378
        # fixed the coach queue.
        #
        # A ref on one of OUR public bases is re-signed rather than passed
        # through: that is what covers the rows written before RISK-11 was
        # found. A foreign https URL (imports store external ones) is left
        # alone, because re-signing someone else's URL against our bucket
        # breaks it.
        from services.audio_ref_resolver import resolve_playable_ref

        return resolve_playable_ref(seg) or seg
    return None


def resolve_turn_audio_url(snippet: Any) -> Optional[str]:
    """The admin surface's precedence, which is the OTHER way round.

    Turn rows are read for review, where audio_segment_path is the per-turn
    file set at upload and never NULL'd by finalize; storage_path is the
    legacy / cold-start fallback. Kept as a separate function rather than a
    flag on the one above, because the precedence difference is a real
    product difference and a boolean argument would hide it.
    """
    if not isinstance(snippet, dict):
        return None
    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        from services.audio_ref_resolver import resolve_playable_ref

        return resolve_playable_ref(seg) or seg

    storage = (snippet.get("storage_path") or "").strip()
    if storage and not storage.startswith(_SUPABASE_ONLY_PREFIX):
        signed = signed_r2_audio_url(storage)
        if signed:
            return signed
    if storage:
        from config import Config
        from services.db import db

        try:
            return db.create_signed_url(
                Config().AUDIO_BUCKET_NAME, storage,
                Config().SIGNED_URL_EXPIRY_SECONDS,
            )
        except Exception:
            return None
    return None
