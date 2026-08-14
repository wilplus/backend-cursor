"""The Voice Album — capture (founder re-lock 2026-08-13/14).

THE ENTRY RULE, verbatim from the founder: "Acoustic data indicates a
great moment -> User agrees -> Coach agrees = This moment lands in the
Voice Album." Three independent signals, one row when they align on a
snippet:

  * ACOUSTIC — the star lane generated an EMPHASIZE for the snippet
    (a `moment_suggestions` row; the machine's confident read);
  * USER     — the student APPLIED it (an `ideal_decision_ledger` row,
    kind 'emphasize', decision 'approved', snippet-keyed);
  * COACH    — the coach tagged the snippet 'strong' AND the session is
    PUBLISHED. Blind until publish: an entry may never reveal a label
    the coach has not released (BLIND COACH), so the coach signal simply
    does not exist here before `results_published_at`.

NEVER a ranking term. The founder deleted the album-quorum bonus with
`_W_B` (2026-08-14): the album is a DESTINATION for aligned moments, not
a weight inside `power_score`. Nothing in this module feeds ranking.

CAPTURE ONLY. No user-facing surface ships from here — the read surface
needs founder-signed copy (LIVE LOOP) and lands separately. Until then
the album fills quietly and correctly.

Append-only + idempotent: `refresh_voice_album` joins the three stores
and inserts what is missing; it never deletes. (What a later REVERT of
the user's approval should do to an existing entry is a product
decision, deliberately not guessed here — logged as an open question in
the shipping PR.) Best-effort throughout: a refresh miss never breaks
the publish flow or the decide POST it rides behind (LIVE LOOP).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_STRONG_TAG = "strong"


def _approved_emphasizes(database, arc_id: Any) -> dict:
    """{snippet_id: ledger row} for the USER signal — approved emphasizes
    that know their snippet. A row without a snippet id cannot enter the
    album (the entry is a moment, not a phrase)."""
    from services.ideal_decision_ledger import load_ledger
    out: dict = {}
    for r in load_ledger(database, arc_id):
        if r.get("kind") == "emphasize" \
                and r.get("decision") == "approved" \
                and r.get("snippet_id"):
            out[str(r.get("snippet_id"))] = r
    return out


def refresh_voice_album(arc_id: Any, *, database=None) -> int:
    """Join the three signals and insert every aligned moment not already
    in the album. Returns how many NEW entries landed (0 on any miss —
    best-effort, never raises into a caller's request path)."""
    if not arc_id:
        return 0
    try:
        if database is None:
            from services.db import db as database

        user_ok = _approved_emphasizes(database, arc_id)
        if not user_ok:
            return 0

        # ACOUSTIC — the machine's emphasize stars for this arc.
        acoustic_ok = {
            sid for sid, row in
            (database.get_moment_suggestions_by_arc(str(arc_id)) or {}
             ).items()
            if isinstance(row, dict) and row.get("kind") == "emphasize"
        }
        if not acoustic_ok:
            return 0

        # COACH — 'strong' tags on PUBLISHED sessions only.
        coach_ok: dict = {}   # snippet_id -> take_session_id
        for sess in (database.get_arc_sessions(arc_id) or []):
            if not sess.get("results_published_at"):
                continue
            sid = str(sess.get("id") or "")
            if not sid:
                continue
            try:
                drafts = database.get_coach_snippet_drafts(sid) or []
            except Exception:
                continue
            for d in drafts:
                if isinstance(d, dict) and d.get("tag") == _STRONG_TAG \
                        and d.get("snippet_id"):
                    coach_ok[str(d.get("snippet_id"))] = sid
        if not coach_ok:
            return 0

        aligned = set(user_ok) & acoustic_ok & set(coach_ok)
        if not aligned:
            return 0

        existing = {str(e.get("snippet_id"))
                    for e in (database.list_voice_album(str(arc_id)) or [])
                    if isinstance(e, dict)}
        new = 0
        for snip_id in sorted(aligned - existing):
            row = user_ok[snip_id]
            _si = row.get("slide_index")
            ok = database.insert_voice_album_entry(
                arc_id=str(arc_id), snippet_id=snip_id,
                take_session_id=coach_ok.get(snip_id),
                slide_index=(_si if isinstance(_si, int)
                             and not isinstance(_si, bool) else None))
            if ok:
                new += 1
        if new:
            logger.info("voice_album: %d new entr%s arc=%s",
                        new, "y" if new == 1 else "ies", arc_id)
        return new
    except Exception as e:
        logger.warning("voice_album: refresh failed arc=%s: %s", arc_id, e)
        return 0
