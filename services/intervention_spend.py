"""The take's intervention budget ledger (founder 2026-08-10).

"each feedback needs to be there; full and end to end and waiting; not
that it appears once the other is accepted."

The manager engine's ≤3 budget (H.1, §R1: "max 3 interventions per take,
total, across both layers") was per ARBITRATION: a decided change left the
pool on the next serve, freed its slot, and a fresh candidate appeared —
the trickle the founder rejected. This module makes the budget per TAKE:

  * every explicit decision on a served intervention SPENDS one slot
    (`spend`) — approved and disregarded alike; deciding is what costs,
    not agreeing;
  * a reverted decision UN-SPENDS it (`unspend`) — the offer is undecided
    again (SPEC R4: absence of a row means undecided) and the slot
    returns;
  * the serve reads `spent_count` and passes it to the gate, which
    subtracts it from the budget (`arbitrate(budget_spent=...)`), so the
    set on screen is chosen once, waits whole, and only shrinks.

The rows double as SPEC §3.3/§6's `intervention_decision` ground truth —
we proposed this and the person it was for said no — which is why `spend`
takes the lane and the C.2 type: they are the join to `intervention_arms`
that turns PPV_FLOOR from an assumption into a measurement.

WHAT MUST NEVER WRITE HERE: any bulk or implicit path (save-time auto-
keeps, lock sweeps). SPEC R4: fabricated refusals corrupt the one direct
precision measurement this product will ever collect, and they cannot be
cleaned afterwards. Only a tap the student actually made spends.

Pure helpers + best-effort db calls; a ledger miss must never break a
decision POST, and a count miss degrades to the per-arbitration budget,
never to silence.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def latest_spoken_take_sid(sessions: Any) -> str:
    """The arc's latest SPOKEN take — the take a decision spends against.

    Same filter the ideal-text GET's crucial-bubble block applies: read
    rows and paired rows are not takes. Empty string when the arc has no
    spoken take yet (the counter still works — it just keys the pre-take
    epoch)."""
    rows = [s for s in (sessions or [])
            if isinstance(s, dict)
            and s.get("recording_kind") != "read"
            and not s.get("paired_session_id")]
    rows.sort(key=lambda s: (s.get("take_index") or 0))
    return str(rows[-1].get("id") or "") if rows else ""


def spend(database, arc_id: Any, sessions: Any, *, change_key: str,
          decision: str, lane: Optional[str] = None,
          intervention_type: Optional[str] = None,
          quote: Optional[str] = None,
          proposed_text: Optional[str] = None,
          why_key: Optional[str] = None) -> bool:
    """Record one explicit decision. decision: approved | disregarded.

    quote / proposed_text / why_key ride along when the caller has them
    (slice 2, founder 2026-08-11): the ledger doubles as the PROPOSAL
    HISTORY the deck's editor lists per chunk, and without the text a
    dismissed proposal is unrecoverable (its suggestion row is deleted).

    LANE NOTE — "lane:style" marks a post-lock style decision. Style rides
    OUTSIDE the ≤3 budget (ruling 4), so spent_count excludes that lane;
    the row still lands here because the learning loop wants every
    explicit decision, budgeted or not."""
    if not arc_id or not change_key:
        return False
    try:
        return bool(database.record_intervention_decision(
            arc_id=str(arc_id),
            take_session_id=latest_spoken_take_sid(sessions),
            change_key=str(change_key),
            decision=decision,
            lane=lane,
            intervention_type=intervention_type,
            quote=quote,
            proposed_text=proposed_text,
            why_key=why_key))
    except Exception as e:
        logger.warning("intervention_spend: spend failed arc=%s: %s",
                       arc_id, e)
        return False


def unspend(database, arc_id: Any, sessions: Any, *,
            change_key: str) -> bool:
    """A revert deletes the row — undecided again, the slot returns."""
    if not arc_id or not change_key:
        return False
    try:
        return bool(database.delete_intervention_decision(
            arc_id=str(arc_id),
            take_session_id=latest_spoken_take_sid(sessions),
            change_key=str(change_key)))
    except Exception as e:
        logger.warning("intervention_spend: unspend failed arc=%s: %s",
                       arc_id, e)
        return False


def spent_count(database, arc_id: Any, take_session_id: Any) -> int:
    """Slots already spent on this take. 0 on any failure — the serve
    degrades to the per-arbitration budget rather than going dark."""
    if not arc_id:
        return 0
    try:
        return int(database.count_intervention_decisions(
            str(arc_id), str(take_session_id or "")) or 0)
    except Exception as e:
        logger.warning("intervention_spend: count failed arc=%s: %s",
                       arc_id, e)
        return 0


def paragraph_index_at(served_text: Any, offset: Any) -> int:
    """Which "\\n\\n" paragraph of the served text `offset` falls in.

    THE PARAGRAPH IS THE UNIT the budget is counted in (founder 2026-08-11:
    "do it per slide up to 2"). It is not an approximation of the slide — the
    document is built with one paragraph per slide, so they are the same
    thing — and it is also exactly the CHUNK the student decides on, which is
    the reason to count here rather than per take. 0 for anything unreadable:
    a document with no paragraph breaks is one group, which is the old flat
    cap."""
    if not isinstance(served_text, str) or not served_text:
        return 0
    try:
        at = int(offset)
    except Exception:
        return 0
    if at <= 0:
        return 0
    return served_text.count("\n\n", 0, at)


def spent_by_paragraph(database, arc_id: Any, take_session_id: Any,
                       served_text: Any) -> dict:
    """{paragraph index: slots spent there} for this take.

    Placed by the decision row's own QUOTE — the words the slot was spent on
    — which needs no schema change and survives the document being restruc-
    tured, because it is matched by content rather than by an offset that
    every reassembly invalidates. A quote no longer in the document (baked,
    corrected, retyped) counts against nothing: the same drop-never-guess
    rule the anchors follow, and it errs toward offering feedback rather than
    withholding it. {} on any failure — the serve then degrades to a fresh
    per-paragraph budget rather than going dark.

    KNOWN LIMIT: `find` takes the FIRST occurrence, so a phrase the speaker
    used on two slides charges the earlier one. Bounded — one slide
    under-serves by one and its twin over-serves by one, both still inside the
    cap — and the alternative is a schema change plus a backfill of history
    that was never recorded. If that stops being acceptable the fix is a
    `slide_index` column written at decide time, NOT a cleverer matcher: a
    matcher that picks between two identical phrases is guessing."""
    if not arc_id or not isinstance(served_text, str) or not served_text:
        return {}
    try:
        rows = database.list_spent_intervention_decisions(
            str(arc_id), str(take_session_id or "")) or []
    except Exception as e:
        logger.warning("intervention_spend: per-paragraph read failed "
                       "arc=%s: %s", arc_id, e)
        return {}
    out: dict = {}
    for r in rows:
        quote = ((r or {}).get("quote") or "").strip()
        if not quote:
            continue
        at = served_text.find(quote)
        if at < 0:
            continue
        para = paragraph_index_at(served_text, at)
        out[para] = out.get(para, 0) + 1
    return out


def style_spend(database, arc_id: Any, take_session_id: Any,
                served_text: Any) -> dict:
    """The take's spent STYLE slots: ``{"count": int, "by_paragraph": {}}``.

    The style lane got its own ≤3-per-take / ≤2-per-slide budget on
    2026-08-12, and a budget needs a ledger or it resets on every poll:
    accepting an accent would summon a replacement, which is the trickle the
    main take budget was built to kill.

    A SEPARATE LEDGER OF THE SAME ROWS. `spend` has always written style
    decisions here tagged ``lane:style``, and `spent_count` /
    `spent_by_paragraph` have always excluded them because style rides
    outside the ≤3. Nothing about that changes — this reads the rows those
    two throw away, so the two budgets stay genuinely separate rather than
    one quietly charging the other.

    ONE READ FOR BOTH NUMBERS on purpose. This lands on the ideal-text GET,
    which the deck polls; counting the take and placing the slides from one
    row set costs one round trip instead of two, and the pair can never
    disagree about which rows they saw.

    Placement is the same quote match `spent_by_paragraph` documents, with
    the same known limit (`find` takes the first occurrence) and the same
    safe direction: a quote no longer in the document counts against no
    slide, so the error runs toward offering feedback rather than
    withholding it. Zeroes on any failure — a ledger miss must degrade to
    the per-serve cap, never to silence.
    """
    empty = {"count": 0, "by_paragraph": {}}
    if not arc_id:
        return empty
    try:
        rows = database.list_style_intervention_decisions(
            str(arc_id), str(take_session_id or "")) or []
    except Exception as e:
        logger.warning("intervention_spend: style read failed arc=%s: %s",
                       arc_id, e)
        return empty
    by_para: dict = {}
    doc = served_text if isinstance(served_text, str) else ""
    for r in rows:
        if not doc:
            continue
        quote = ((r or {}).get("quote") or "").strip()
        if not quote:
            continue
        at = doc.find(quote)
        if at < 0:
            continue
        para = paragraph_index_at(doc, at)
        by_para[para] = by_para.get(para, 0) + 1
    # The COUNT is every style decision, placed or not: a slot spent on words
    # that have since been baked away is still spent against the take.
    return {"count": len(rows), "by_paragraph": by_para}
