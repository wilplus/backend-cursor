"""The Voice Album — capture (founder re-lock 2026-08-13/14).

THE ENTRY RULE, verbatim from the founder: "Acoustic data indicates a
great moment -> User agrees -> Coach agrees = This moment lands in the
Voice Album." Three independent signals, one row when they align on a
snippet:

  * ACOUSTIC — the star lane generated an EMPHASIZE for the snippet
    (a `moment_suggestions` row; the machine's confident read);
  * USER     — the owner answered yes on the displayed Confident Voice card
    (an owner_voice_album_routing row, structurally outside learning);
  * COACH    — an explicit professional coach confidence label is YES and the
    session is PUBLISHED. Peer labels and owner self-reports never satisfy
    this leg. Blind until publish: an unreleased coach answer does not exist
    on the user surface.

NEVER a ranking term. The founder deleted the album-quorum bonus with
`_W_B` (2026-08-14): the album is a DESTINATION for aligned moments, not
a weight inside `power_score`. Nothing in this module feeds ranking.

CAPTURE ONLY. No user-facing surface ships from here — the read surface
needs founder-signed copy (LIVE LOOP) and lands separately. Until then
the album fills quietly and correctly.

A MIRROR, NOT A GRAVEYARD (founder ruling 2026-08-14): the album is "a
pure reflection of the current state" — when a signal withdraws (the
owner changes their answer, most commonly), the entry is REMOVED, "not
an append-only graveyard of changed minds". `refresh_voice_album` is a
full reconciliation: it inserts newly aligned moments AND removes
entries that no longer align. Still-aligned entries are untouched (the
insert is insert-if-missing, so `entered_at` survives re-refreshes).
Best-effort throughout: a refresh miss never breaks the publish flow or
the decide POST it rides behind (LIVE LOOP).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

def _professional_coach_yes(rows: Any) -> bool:
    """True only for a released professional coach's explicit Yes.

    Provenance is structural: peer lanes, bootstrap rows, unrateable labels,
    and self-reports are never upgraded into a coach judgment by agreement.
    """
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        lane = row.get("lane")
        # Rows written before the provenance migration have no lane but retain
        # ``source=coach``. That is still an explicit professional judgment;
        # bootstrap and peer/game rows remain excluded.
        professional = lane == "coach" or (
            lane is None and row.get("source") == "coach"
        )
        if not professional or row.get("self_report") is True:
            continue
        if row.get("state_id") not in (None, "confidence"):
            continue
        if row.get("unrateable") is True:
            continue
        if str(row.get("value") or "").strip().lower() == "yes":
            return True
    return False


def _owner_agreements(database, arc_id: Any) -> dict:
    """{snippet_id: routing row} for the Voice Album's USER signal.

    The Confident Voice card is an anchored response, so it lives in the
    routing-only table and never in confidence_labels/training corpora.
    Only an explicit yes satisfies the album entry rule.
    """
    out: dict = {}
    for row in database.list_owner_voice_album_routes(str(arc_id)) or []:
        if (isinstance(row, dict) and row.get("response") == "yes"
                and row.get("snippet_id")):
            out[str(row["snippet_id"])] = row
    return out


def refresh_voice_album(arc_id: Any, *, database=None) -> int:
    """Reconcile the album against the three signals: insert every newly
    aligned moment, REMOVE every entry that no longer aligns (the mirror
    ruling — a reverted approval withdraws the moment). Returns how many
    NEW entries landed (0 on any miss — best-effort, never raises into a
    caller's request path)."""
    if not arc_id:
        return 0
    try:
        if database is None:
            from services.db import db as database

        user_ok = _owner_agreements(database, arc_id)

        # ACOUSTIC — the machine's emphasize stars for this arc.
        acoustic_ok = {
            sid for sid, row in
            (database.get_moment_suggestions_by_arc(str(arc_id)) or {}
             ).items()
            if isinstance(row, dict) and row.get("kind") == "emphasize"
        }

        # COACH — explicit professional coach YES, on PUBLISHED sessions only.
        #
        # The publish gate is unchanged and load-bearing: a quorum can settle
        # while the coach is still working, and BLIND COACH means none of it
        # exists for the student until the review is released.
        coach_ok: dict = {}   # snippet_id -> take_session_id
        for sess in (database.get_arc_sessions(arc_id) or []):
            if not sess.get("results_published_at"):
                continue
            sid = str(sess.get("id") or "")
            if not sid:
                continue
            try:
                snips = database.get_snippets_by_session(sid) or []
            except Exception:
                continue
            _ids = [str(x.get("id")) for x in snips
                    if isinstance(x, dict) and x.get("id")]
            labels = database.get_confidence_labels_by_snippet_ids(_ids) or {}
            for snip_id in _ids:
                if _professional_coach_yes(labels.get(snip_id)):
                    coach_ok[str(snip_id)] = sid

        # `aligned` may legitimately be EMPTY — the mirror still has to
        # run, because an empty alignment with existing entries means
        # every one of them must go (the user changed their mind).
        aligned = set(user_ok) & acoustic_ok & set(coach_ok)

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

        removed = 0
        for snip_id in sorted(existing - aligned):
            if database.delete_voice_album_entry(
                    arc_id=str(arc_id), snippet_id=snip_id):
                removed += 1

        if new or removed:
            logger.info("voice_album: +%d/-%d entries arc=%s",
                        new, removed, arc_id)
        return new
    except Exception as e:
        logger.warning("voice_album: refresh failed arc=%s: %s", arc_id, e)
        return 0
