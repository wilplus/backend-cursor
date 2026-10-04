"""The Voice Album — capture (founder re-lock 2026-08-13/14).

THE ENTRY RULE, verbatim from the founder: "Acoustic data indicates a
great moment -> User agrees -> Coach agrees = This moment lands in the
Voice Album." Three independent signals, one row when they align on a
snippet:

  * ACOUSTIC — the star lane generated an EMPHASIZE for the snippet
    (a `moment_suggestions` row; the machine's confident read);
  * USER     — the owner answered yes on the displayed Confident Voice card
    (an owner_voice_album_routing row, structurally outside learning);
  * COACH    — an explicit professional coach confidence label is YES on a
    Take of this project. Peer labels and owner self-reports never satisfy
    this leg. The coach's judgement on the walk is final when written
    (35g-5), so the write is the release; the arc-level publish that once
    released it is retired (founder 2026-09-30, B3; contract 65).

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
Best-effort throughout: a refresh miss never breaks the rating write or
the decide POST it rides behind (LIVE LOOP).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MACHINE_CONFIDENT_TRIGGERS = {"confident"}


def _machine_confident(row: Any) -> bool:
    """A neutral confidence-review nomination is not a machine Yes."""
    return bool(
        isinstance(row, dict)
        and row.get("kind") == "emphasize"
        and row.get("trigger") in _MACHINE_CONFIDENT_TRIGGERS
    )

def _professional_coach_yes(rows: Any) -> bool:
    """True only when the latest professional judgment is explicit Yes."""
    from services.professional_confidence import latest_professional_value
    return latest_professional_value(rows) == "yes"


def _owner_agreements(database, arc_id: Any, complete: Any = None) -> dict:
    """{snippet_id: routing row} for the Voice Album's USER signal.

    The Confident Voice card is an anchored response, so it lives in the
    routing-only table and never in confidence_labels/training corpora.
    Only an explicit yes satisfies the album entry rule.
    """
    out: dict = {}
    # New immutable exact-clip self-reports are the authoritative USER leg.
    # Machine, user and coach provenance remain separate tables. The legacy
    # routing mirror below keeps older clips readable during migration.
    reader = getattr(database, "list_confident_voice_self_reports", None)
    try:
        for row in (reader(str(arc_id)) if reader else None) or []:
            if (isinstance(row, dict) and row.get("response") == "yes"
                    and row.get("snippet_id")):
                out[str(row["snippet_id"])] = row
    except Exception:
        logger.warning("voice_album: self-reports unreadable arc=%s", arc_id,
                       exc_info=True)
        if complete is not None:
            complete[0] = False
    for row in database.list_owner_voice_album_routes(str(arc_id)) or []:
        if (isinstance(row, dict) and row.get("response") == "yes"
                and row.get("snippet_id")
                and str(row["snippet_id"]) not in out):
            out[str(row["snippet_id"])] = row
    return out


def _slide_or_none(slide: Any) -> Any:
    """An integer slide index, or None (a bool is not a slide)."""
    return slide if isinstance(slide, int) and not isinstance(slide, bool) else None


def _reconcile_practice_attempt(
    database: Any, *, arc: str, target: str, attempt: Any,
) -> bool:
    """A practice attempt of this project: an explicit coach No removes it;
    it enters only when coach, machine and user all say yes AND it is the
    practice's selected attempt."""
    practice = database.get_confident_voice_practice(
        str(attempt.get("practice_id") or ""))
    if not practice or str(practice.get("project_id") or "") != arc:
        return False
    coach = attempt.get("coach_confidence_decision")
    # Any coach answer but Yes keeps it out (five answers since 0390).
    if coach is not None and coach != "yes":
        return bool(database.delete_voice_album_practice_entry(
            arc_id=arc, practice_attempt_id=target,
        ))
    aligned = (
        coach == "yes"
        and attempt.get("machine_confidence_decision") == "yes"
        and attempt.get("user_answer") == "yes"
        and str(practice.get("selected_attempt_id") or "") == target
    )
    if not aligned:
        return False
    return bool(database.insert_voice_album_practice_entry(
        arc_id=arc,
        practice_attempt_id=target,
        take_session_id=str(practice.get("take_session_id") or "") or None,
        slide_index=practice.get("slide_index"),
    ))


def _reconcile_original_clip(
    database: Any, *, arc: str, target: str, take_session_id: Any,
) -> bool:
    """An original clip: an explicit professional No on its Take removes
    it; it enters only when the user's yes, the machine's confident star and
    the professional Yes on that Take all align. The Take has to be this
    project's; nothing else gates it since the publish was retired."""
    user_row = _owner_agreements(database, arc).get(target)
    suggestion = (
        database.get_moment_suggestions_by_arc(arc) or {}
    ).get(target)
    labels = database.get_confidence_labels_by_snippet_ids([target]) or {}
    from services.professional_confidence import latest_professional_value
    coach_value = latest_professional_value(labels.get(target))
    session = database.v2_get_session_by_id(str(take_session_id or "")) or {}
    session_matches = bool(
        session
        and str(session.get("project_id") or session.get("arc_id") or "") == arc
    )
    if coach_value == "no" and session_matches:
        return bool(database.delete_voice_album_entry(
            arc_id=arc, snippet_id=target,
        ))
    aligned = bool(
        coach_value == "yes"
        and user_row
        and _machine_confident(suggestion)
        and session_matches
    )
    if not aligned or not isinstance(user_row, dict):
        return False
    return bool(database.insert_voice_album_entry(
        arc_id=arc,
        snippet_id=target,
        take_session_id=str(take_session_id or "") or None,
        slide_index=_slide_or_none(user_row.get("slide_index")),
    ))


def reconcile_voice_album_clip(
    arc_id: Any, clip_id: Any, *, take_session_id: Any = None, database=None,
) -> bool:
    """Reconcile only the clip explicitly judged in this revision.

    Missing evidence is a no-op.  An existing entry is removed only after an
    explicit professional No on this exact clip; incomplete reads can never
    withdraw a user's saved moment.
    """
    if not arc_id or not clip_id:
        return False
    try:
        if database is None:
            from services.db import db as database
        arc = str(arc_id)
        target = str(clip_id)

        attempt = database.get_confident_voice_practice_attempt(target)
        if attempt:
            return _reconcile_practice_attempt(
                database, arc=arc, target=target, attempt=attempt,
            )
        return _reconcile_original_clip(
            database, arc=arc, target=target, take_session_id=take_session_id,
        )
    except Exception as error:
        logger.warning(
            "voice_album: exact clip reconciliation failed arc=%s clip=%s: %s",
            arc_id,
            clip_id,
            error,
        )
        return False


def _acoustic_yes_ids(database: Any, arc_id: Any) -> set:
    """ACOUSTIC — the machine's emphasize stars for this arc."""
    return {
        sid for sid, row in
        (database.get_moment_suggestions_by_arc(str(arc_id)) or {}
         ).items()
        if _machine_confident(row)
    }


def _coach_yes_sessions(database: Any, arc_id: Any, complete: Any = None) -> dict:
    """COACH — {snippet_id: take_session_id} for every explicit professional
    coach YES on a Take of this project.

    The publish gate that once stood here is retired with the arc-level
    delivery (founder 2026-09-30, B3; contract 65): on the walk a judgement
    is answered blind and is final when written (35g-5), so there is no
    draft to hold back. The album still has no read surface (capture only).
    """
    coach_ok: dict = {}   # snippet_id -> take_session_id
    for sess in (database.takes.get_arc_sessions(arc_id) or []):
        sid = str(sess.get("id") or "")
        if not sid:
            continue
        try:
            snips = database.get_snippets_by_session(sid) or []
        except Exception:
            logger.warning("voice_album: snippets unreadable take=%s", sid,
                           exc_info=True)
            if complete is not None:
                complete[0] = False
            continue
        _ids = [str(x.get("id")) for x in snips
                if isinstance(x, dict) and x.get("id")]
        labels = database.get_confidence_labels_by_snippet_ids(_ids) or {}
        for snip_id in _ids:
            if _professional_coach_yes(labels.get(snip_id)):
                coach_ok[str(snip_id)] = sid
    return coach_ok


def _existing_clip_entries(database: Any, arc_id: Any) -> set:
    """Snippet ids of the album's original-clip entries (not practice)."""
    return {str(e.get("snippet_id"))
            for e in (database.list_voice_album(str(arc_id)) or [])
            if isinstance(e, dict)
            and e.get("source_kind") != "practice_attempt"
            and e.get("snippet_id")}


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

        # FAIL CLOSED (F1 Repair Plan Phase 5; audit 2026-10-03): a read
        # that failed is not "nobody agreed". Inserts still land; removals
        # wait for a refresh whose every read completed.
        complete = [True]
        user_ok = _owner_agreements(database, arc_id, complete)
        acoustic_ok = _acoustic_yes_ids(database, arc_id)
        coach_ok = _coach_yes_sessions(database, arc_id, complete)

        # `aligned` may legitimately be EMPTY — the mirror still has to
        # run, because an empty alignment with existing entries means
        # every one of them must go (the user changed their mind).
        aligned = set(user_ok) & acoustic_ok & set(coach_ok)

        existing = _existing_clip_entries(database, arc_id)

        new = 0
        for snip_id in sorted(aligned - existing):
            ok = database.insert_voice_album_entry(
                arc_id=str(arc_id), snippet_id=snip_id,
                take_session_id=coach_ok.get(snip_id),
                slide_index=_slide_or_none(
                    user_ok[snip_id].get("slide_index")))
            if ok:
                new += 1

        removed = 0
        for snip_id in sorted(existing - aligned if complete[0] else set()):
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
