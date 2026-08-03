"""The Reflection Game (F2 handoff §1, 2026-08-03).

The shadow detector's "possibly confident" moments go to the USER as a
question, never a claim ("How did this moment land for you?"). The user
votes → the coach verifies BLIND → only a coach-verified moment lands in
the cross-project Confident Voices library. By-product: the three-way
agreement matrix (machine flag × user vote × coach verdict) on identical
audio — the F2 label stream.

Founder-locked fences engineered here and in the routes:
  * NO DECOY LEAK — decoy identity (machine_flagged) lives on the row,
    server-side only; the user payload is an explicit allowlist that can
    never carry it, nor any model confidence.
  * BLIND COACH — the coach payload is audio + transcript ONLY: no
    machine flag, no user vote, until after the verdict is stored.
  * AC-9 — no counts, streaks, or scores in any user/coach payload of
    the game or library. A list is a list.
  * CADENCE — hard cap 2 freshly-served clips per user per UTC day
    (the server-side authority for "per session"; the FE also respects
    its own session cap on top).

Sources: shadow-flagged (predicted 'challenge') snippets from the user's
takes — spoken AND read (recording_kind rides the row; read-derived
moments are delivery material). Decoys: 1 in 4 clips are UNFLAGGED
segments from the same user, duration-matched and measured (not silence,
not a giveaway). Snippets a coach already labeled are excluded from both
pools — game material stays blind end to end.

PROVENANCE — not the peer-review lane. services/confidence_reviews.py
captures a NON-BLIND judgement: the reviewer is shown the AI's
confidence choice and grades it. A game vote is the opposite by
construction — the user is never told whether the machine flagged the
clip (that is the no-decoy-leak fence), so these are BLIND user labels,
a third provenance beside non-blind peer review and blind coach truth.
The two must never be blended indistinguishably downstream (the
confirmation-loop risk that lane's SELECTION_SOURCE split exists to
prevent). Today nothing here writes a corpus row at all — the matrix is
the log line below — so any future trainer that consumes it must carry
its own provenance tag in."""
from __future__ import annotations

import logging
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)

# Every 4th clip (0-indexed position % 4 == 3) is a decoy.
_DECOY_EVERY = 4
# Keep this many unvoted clips banked per user.
_POOL_TARGET = 4
# A clip must be a real utterance: at least this many words / this long.
_MIN_WORDS = 3
_MIN_DURATION_MS = 1500
# Decoys are duration-matched to the flagged pool within this band.
_DECOY_DURATION_BAND = (0.5, 1.8)
# Server-enforced cadence: freshly served clips per user per UTC day.
SERVE_CAP_PER_DAY = 2


def _word_count(text: Any) -> int:
    return len(str(text or "").split())


def _snip_ok(snip: dict) -> bool:
    if _word_count(snip.get("transcript")) < _MIN_WORDS:
        return False
    dur = snip.get("duration_ms")
    return isinstance(dur, (int, float)) and not isinstance(dur, bool) \
        and dur >= _MIN_DURATION_MS


def _measured(snip: dict) -> bool:
    """Ordinary measured speech — the decoy bar (not silence, not an
    unanalyzed fragment; a giveaway decoy defeats the design)."""
    _m = snip.get("metrics")
    m = _m if isinstance(_m, dict) else {}
    score = m.get("overall_score")
    return score is not None and not isinstance(score, bool)


def _clip_fields(snip: dict, session: dict, flagged: bool) -> dict:
    _ctx = session.get("intake_context")
    ctx = _ctx if isinstance(_ctx, dict) else {}
    _m = snip.get("metrics")
    m = _m if isinstance(_m, dict) else {}
    return {
        "snippet_id": str(snip.get("id")),
        "take_session_id": str(session.get("id")),
        "arc_id": (str(session.get("arc_id"))
                   if session.get("arc_id") else None),
        "machine_flagged": bool(flagged),      # server-side only, always
        "recording_kind": (m.get("recording_kind")
                           or session.get("recording_kind") or "spoken"),
        "named_emotion": ctx.get("named_emotion"),
        "topic": ctx.get("topic"),
        "start_offset_ms": snip.get("start_offset_ms"),
        "duration_ms": snip.get("duration_ms"),
        "transcript": (snip.get("transcript")
                       or snip.get("transcription_text") or ""),
    }


def ensure_clip_pool(user_id: Any, database=None) -> int:
    """Top the user's unvoted clip bank up to the pool target, keeping
    the 1-in-4 decoy cadence over the user's ALL-TIME clip sequence (so
    a devtools reader can't infer decoy position from within one batch).
    Returns the number of clips created. Best-effort; never raises."""
    if database is None:
        from services.db import db as database
    try:
        uid = str(user_id)
        existing = database.list_reflection_clips(uid) or []
        pending = [c for c in existing if not c.get("user_vote")]
        need = _POOL_TARGET - len(pending)
        if need <= 0:
            return 0
        used_snippets = {str(c.get("snippet_id")) for c in existing}

        sessions = database.list_user_arc_sessions(uid) or []
        by_id = {str(s.get("id")): s for s in sessions}
        sids = list(by_id.keys())
        if not sids:
            return 0
        snips_by_sid = database.get_snippets_by_sessions(sids) or {}
        labels_by_sid = database.get_training_labels_by_sessions(sids) or {}
        coach_labeled = {
            str(r.get("snippet_id"))
            for rows in labels_by_sid.values() for r in (rows or [])
            if r.get("snippet_id")
        }

        all_snips: list = []
        for sid, rows in snips_by_sid.items():
            for s in (rows or []):
                if str(s.get("id")) in used_snippets \
                        or str(s.get("id")) in coach_labeled \
                        or not _snip_ok(s):
                    continue
                all_snips.append((sid, s))
        if not all_snips:
            return 0

        flagged_ids = database.get_shadow_challenge_snippet_ids(
            [str(s.get("id")) for _, s in all_snips]) or set()
        flagged_pool = [(sid, s) for sid, s in all_snips
                        if str(s.get("id")) in flagged_ids]
        if not flagged_pool:
            return 0            # the game only exists where the shadow saw something

        durs = [s.get("duration_ms") for _, s in flagged_pool]
        med = median(durs)
        lo, hi = med * _DECOY_DURATION_BAND[0], med * _DECOY_DURATION_BAND[1]
        decoy_pool = [
            (sid, s) for sid, s in all_snips
            if str(s.get("id")) not in flagged_ids and _measured(s)
            and lo <= (s.get("duration_ms") or 0) <= hi
        ]

        created = 0
        position = len(existing)
        while created < need and (flagged_pool or decoy_pool):
            want_decoy = (position % _DECOY_EVERY) == (_DECOY_EVERY - 1)
            if want_decoy and decoy_pool:
                sid, snip = decoy_pool.pop(0)
                flagged = False
            elif flagged_pool:
                sid, snip = flagged_pool.pop(0)
                flagged = True
            else:
                break           # never pad a missing flagged slot with decoys
            if database.insert_reflection_clip(
                    uid, _clip_fields(snip, by_id.get(sid) or {}, flagged)):
                created += 1
                position += 1
        return created
    except Exception as e:
        logger.warning("reflection: pool build failed user=%s: %s",
                       user_id, e)
        return 0


def serve_clips(user_id: Any, database=None) -> list:
    """The clips to hand the user right now, cadence-enforced: at most
    SERVE_CAP_PER_DAY clips get their FIRST serve per UTC day; an
    already-served, still-unvoted clip re-serves freely (a reload never
    burns allowance). Returns internal rows — the ROUTE builds the wire
    payload from an explicit allowlist (no-decoy-leak lives there)."""
    if database is None:
        from services.db import db as database
    try:
        uid = str(user_id)
        ensure_clip_pool(uid, database)
        pending = [c for c in (database.list_reflection_clips(uid) or [])
                   if not c.get("user_vote")]
        already = [c for c in pending if c.get("served_at")]
        fresh = [c for c in pending if not c.get("served_at")]
        out = already[:SERVE_CAP_PER_DAY]
        allowance = max(
            0, SERVE_CAP_PER_DAY
            - int(database.count_reflection_clips_served_today(uid) or 0)
            - len(out))
        if allowance and fresh:
            newly = fresh[:allowance]
            database.mark_reflection_clips_served(
                [c.get("id") for c in newly])
            out.extend(newly)
        return out[:SERVE_CAP_PER_DAY]
    except Exception as e:
        logger.warning("reflection: serve failed user=%s: %s", user_id, e)
        return []


def log_matrix_row(clip: dict) -> None:
    """§1f — the internal agreement-matrix stream, one line per verdict:
    machine flag × user vote × coach verdict on identical audio, with
    the source take's kind and named emotion. NEVER surfaced to user or
    coach; this log is the F2 label stream."""
    try:
        logger.info(
            "reflection.matrix clip=%s user=%s machine_flagged=%s "
            "user_vote=%s coach_verdict=%s recording_kind=%s "
            "named_emotion=%s",
            clip.get("id"), clip.get("user_id"),
            bool(clip.get("machine_flagged")), clip.get("user_vote"),
            clip.get("coach_verdict"), clip.get("recording_kind"),
            clip.get("named_emotion"))
    except Exception:
        pass
