"""Arc-domain helpers: deck identity, arc continuation, arc entitlement.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 1). The
arc ROUTES still live in ``routes/v2_routes.py`` -- only the helpers the Lab
upload path needs are here, so that module can import them without a cycle.
They land in the module the arc routes will move into next.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

from routes.admin import is_admin, is_coach
from services.db import db

logger = logging.getLogger(__name__)


def _presentation_id_from_slides(slides) -> str:
    """Stable content hash of a deck's slides, independent of the served PDF
    URL (which changes on every re-upload). Same deck text → same id → same
    presentation group. Uses normalized title+body so cosmetic re-uploads
    don't split the take history."""
    import hashlib
    if not slides:
        return ""
    parts = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        t = (s.get("title") or "").strip()
        b = (s.get("body") or "").strip()
        parts.append(f"{t}\n{b}")
    canonical = "\n---\n".join(parts)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def _continue_deck_arc(user_id, slides, fresh_arc_id, fresh_take_index):
    """Continue-one-arc (single-deliverable, founder 2026-07-17): every take of
    the SAME deck (same user) joins that deck's most-developed arc — takes
    append forever (the old 3-take batch cap is retired).

    Matches by the stable deck-hash across the user's lab sessions and continues
    the deck's MOST-developed arc (consistent with the /strengths group arc,
    #132). Returns (arc_id, take_index). Falls back to the freshly-minted arc
    for a NEW deck / deckless / guest / a full batch / any error — never raises
    into the record path. The current session is skipped because its arc_id
    isn't set yet.
    """
    if not user_id or not slides:
        return fresh_arc_id, fresh_take_index
    try:
        pid = _presentation_id_from_slides(slides)
        if not pid:
            return fresh_arc_id, fresh_take_index
        counts: dict = {}
        for s in (db.v2_list_user_lab_sessions(user_id) or []):
            ctx = s.get("intake_context") if isinstance(
                s.get("intake_context"), dict) else {}
            s_slides = (ctx or {}).get("slides") or []
            aid = s.get("arc_id")
            if not s_slides or not aid:
                continue
            if _presentation_id_from_slides(s_slides) == pid:
                counts[aid] = counts.get(aid, 0) + 1
        # Batch cap (founder re-lock 2026-07-11): only arcs with an OPEN
        # batch are joinable — the most-developed open one wins (so take 5
        # fills batch 2 instead of minting a third arc). All full → the
        # fresh arc starts the next batch, counter back to take 1.
        # SINGLE DELIVERABLE (founder re-shape 2026-07-17, cap lock
        # overturned): takes append to the presentation FOREVER — one deck =
        # one presentation; only a new deck/topic mints a new one.
        open_arcs = dict(counts)
        if not open_arcs:
            return fresh_arc_id, fresh_take_index
        best_arc = max(open_arcs.items(), key=lambda kv: kv[1])[0]
        return best_arc, open_arcs[best_arc] + 1
    except Exception as e:
        logger.warning("continue_deck_arc failed user=%s: %s", user_id, e)
        return fresh_arc_id, fresh_take_index


def _continue_topic_arc(user_id, topic, fresh_arc_id, fresh_take_index):
    """Continue-one-arc for DECKLESS takes (founder bug #4/#6, 2026-07-06):
    the conversational practice flow has no deck, so the deck-hash continue
    never matched and every take minted a FRESH arc — splitting one training
    across arcs (wrong counter, cadence mismatch, coach saw one take per arc).

    Same doctrine as _continue_deck_arc, keyed on the NORMALIZED TOPIC (the
    "same talk"): re-recording the same-titled talk joins its most-developed
    existing arc — takes append forever (the old 3-take batch cap is retired).
    New topic / guest / no topic / any error → the fresh arc.
    Never raises into the record path."""
    if not user_id or not isinstance(topic, str) or not topic.strip():
        return fresh_arc_id, fresh_take_index
    try:
        norm = " ".join(topic.strip().lower().split())
        counts: dict = {}
        for s in (db.v2_list_user_lab_sessions(user_id) or []):
            ctx = s.get("intake_context") if isinstance(
                s.get("intake_context"), dict) else {}
            s_topic = (ctx or {}).get("topic")
            aid = s.get("arc_id")
            if not aid or not isinstance(s_topic, str):
                continue
            # DECKLESS candidates only (review): a deckless take must not join
            # a DECK arc that happens to share the topic — mixing alignment-
            # less takes into a per-slide best-presentation arc.
            if (ctx or {}).get("slides"):
                continue
            if " ".join(s_topic.strip().lower().split()) == norm:
                counts[aid] = counts.get(aid, 0) + 1
        # Batch cap — same open-batch rule as _continue_deck_arc; lifted
        # entirely under the single deliverable (takes append forever).
        open_arcs = dict(counts)
        if not open_arcs:
            return fresh_arc_id, fresh_take_index
        best_arc = max(open_arcs.items(), key=lambda kv: kv[1])[0]
        return best_arc, open_arcs[best_arc] + 1
    except Exception as e:
        logger.warning("continue_topic_arc failed user=%s: %s", user_id, e)
        return fresh_arc_id, fresh_take_index


def _arc_audit_paid(arc_id, user_id):
    """Phase-1 per-arc paid flag (the FE's ``audit_paid``). True when the scope
    should be FULL: a non-arc / standalone session (no paywall concept), an
    admin/coach (always sees everything), or an entitled arc. False only for an
    unpaid arc — the free-take teaser scope."""
    from services.arc_entitlement import is_arc_entitled
    if not arc_id:
        return True
    if user_id and (is_admin(user_id) or is_coach(user_id)):
        return True
    return is_arc_entitled(db, arc_id, user_id)


def _spoken_takes_and_reads(sessions):
    """Split an arc's sessions into spoken takes (ordered by take_index) and
    a {spoken_session_id: [read_session, ...]} map — a take can carry SEVERAL
    mid-take re-reads and ALL of them fold into it (founder 2026-07-16),
    oldest first. Rows without recording_kind (pre-migration / legacy) read
    as spoken."""
    spoken, reads = [], {}
    for s in sessions:
        if (s.get("recording_kind") == "read") or s.get("paired_session_id"):
            if s.get("paired_session_id"):
                reads.setdefault(str(s.get("paired_session_id")), []).append(s)
        else:
            spoken.append(s)
    spoken.sort(key=lambda x: (x.get("take_index") or 0))
    for _lst in reads.values():
        _lst.sort(key=lambda x: (x.get("created_at") or ""))
    return spoken, reads
