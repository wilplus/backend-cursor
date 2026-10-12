"""One Apply / ✓-prefer tap on a suggestion row (POST
/v2/user/snippets/<snippet_id>/suggestion-feedback, founder 2026-07-14).

Moved out of ``routes.v2.user_sessions`` unchanged (founder 2026-10-12). A
SECOND-ORDER preference signal (below coach truth); capture only, never
echoed back as any score (AC-9). The route keeps the ownership check (the
authenticated owner or the matching signed Guest ID; a bare session UUID is
never authorization) and calls ``record_suggestion_feedback`` only after it.

Writes, in order: the feedback row, the Take's rebake request, then — for a
star decision — the decision ledger, the Voice Album refresh, the Take's
budget, the dismissed suggestion's removal and the document's reassembly.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from services.ideal_text_feedback_bake import request_rebake_for_take
from services.refusal import Refusal

logger = logging.getLogger(__name__)

SUGGESTION_TARGETS = ("upgrade", "rewrite_your_voice", "rewrite_polished",
                      "comment", "comment_video",
                      # Star suggestions (2026-07-18): per-star Approve /
                      # Revert on the SD ideal text (no apply_all surfaced).
                      "moment_emphasize", "moment_replace",
                      # LIVING TRANSCRIPT (FE contract 2026-07-21): a
                      # span-anchored tracked change on the document.
                      # Founder bug 2026-07-22: the FE shipped these and
                      # this allowlist rejected them with 400 — every
                      # Accept/Keep on the document failed ("Couldn't
                      # save that just now"). The #221 bug class: new
                      # vocabulary on one side, an unwidened guard on
                      # the other.
                      "document_replace", "document_bold",
                      # Structural stars are delivery prompts (no Approve);
                      # this target is accepted forward-compatibly for
                      # engagement feedback but changes NO serve behavior
                      # (never in the applied-map / fold).
                      "moment_structure")
# "reverted" (2026-07-15): Approve is a reversible toggle on the FE — the
# undo reports here so applied→reverted pairs keep the preference signal
# honest (second-order lane, below coach truth, as ever).
# "dismissed" (2026-07-20, gradual refinement rule 2): an explicit
# rejection of a star — recorded on the decision ledger so the same
# suggestion is never generated again for that phrase.
SUGGESTION_ACTIONS = ("applied", "preferred", "apply_all", "reverted",
                      "dismissed")

_LEDGER_TARGETS = ("moment_replace", "moment_emphasize",
                   "document_replace", "document_bold")
_LEDGER_ACTIONS = ("applied", "dismissed", "reverted")
_EMPHASIS_TARGETS = ("moment_emphasize", "document_bold")


def validated_tap(body: dict) -> tuple[Any, Any, Any]:
    """(target, action, upgrade_index), or a 400 ``Refusal``."""
    target = body.get("target")
    if target not in SUGGESTION_TARGETS:
        raise Refusal("INVALID_INPUT",
                      f"target: must be one of {', '.join(SUGGESTION_TARGETS)}", 400)
    action = body.get("action")
    if action not in SUGGESTION_ACTIONS:
        raise Refusal("INVALID_INPUT",
                      f"action: must be one of {', '.join(SUGGESTION_ACTIONS)}", 400)
    upgrade_index = body.get("upgrade_index")
    if upgrade_index is not None and (
        not isinstance(upgrade_index, int)
        or isinstance(upgrade_index, bool) or upgrade_index < 0
    ):
        raise Refusal("INVALID_INPUT",
                      "upgrade_index: must be a non-negative integer", 400)
    return target, action, upgrade_index


def _text_or_none(value: Any) -> Optional[str]:
    return str(value) if isinstance(value, str) and value.strip() else None


def _arc_version(database, arc: str) -> Any:
    try:
        return (database.ideal_text.get_coach_arc_ideal_text(arc)
                or {}).get("version")
    except Exception:
        return None


def _slide_index(snip: dict) -> Any:
    """§12.3 — the intent key's location: the cutter's own slide bucket for
    this snippet (the one cross-take key). Missing/legacy metrics → None;
    the row then carries the phrase key only, exactly as before."""
    piece = (snip.get("metrics") or {}).get("piece") \
        if isinstance(snip.get("metrics"), dict) else None
    return piece.get("slide_index") if isinstance(piece, dict) else None


def _decision_subject(body: dict, suggestion: Any, decision_text: Any) -> tuple[Any, Any]:
    """A coach revision is a new proposal against the text the user
    currently has. Store its visible before/after pair so accepting it never
    mutates an earlier machine decision in place."""
    if body.get("source") != "coach_revision":
        return suggestion, decision_text
    quote, proposed = body.get("quote"), body.get("proposed_text")
    if (isinstance(quote, str) and quote.strip()
            and isinstance(proposed, str) and proposed.strip()):
        return ({**(suggestion or {}), "replacement_text": proposed.strip()},
                quote.strip())
    return suggestion, decision_text


def _refresh_album(database, arc: str, target: str, action: str) -> None:
    """THE VOICE ALBUM (founder 2026-08-14, mirror ruling): an APPLIED
    emphasize is the USER signal of the entry rule; a REVERT withdraws it,
    and the same refresh REMOVES the entry. Best-effort: never breaks the
    decide POST."""
    if action not in ("applied", "reverted") or target not in _EMPHASIS_TARGETS:
        return
    try:
        from services.voice_album import refresh_voice_album
        refresh_voice_album(arc, database=database)
    except Exception as va_err:
        logger.warning("voice_album: decide hook failed arc=%s: %s", arc, va_err)


def _spend_budget(database, arc: str, snippet_id: str, target: str,
                  action: str, body: dict) -> None:
    """THE TAKE'S BUDGET (founder 2026-08-10): a decided star keeps its slot
    — applied and dismissed alike; a revert returns it (undecided again,
    SPEC R4). THE STYLE LANE (slice 2, founder 2026-08-11): a post-lock bold
    decision rides OUTSIDE the ≤3 with lane:style. PROPOSAL HISTORY: the
    texts ride when the client sends them."""
    from services.intervention_spend import spend, unspend
    star_key = f"star:{target}:{snippet_id}"
    arc_sessions = database.takes.get_arc_sessions(arc) or []
    if action == "reverted":
        unspend(database, arc, arc_sessions, change_key=star_key)
        return
    style = bool(body.get("style_lane")) and target == "document_bold"
    spend(database, arc, arc_sessions,
          change_key=star_key,
          decision=("approved" if action == "applied" else "disregarded"),
          lane=("lane:style" if style else None),
          intervention_type=("EMPHASISE" if target in _EMPHASIS_TARGETS
                             else "REWRITE"),
          quote=_text_or_none(body.get("quote")),
          proposed_text=_text_or_none(body.get("proposed_text")),
          why_key=_text_or_none(body.get("why_key")))


def _record_star_decision(database, *, session: dict, snip: dict,
                          snippet_id: str, target: str, action: str,
                          body: dict, phrase_for: Callable,
                          reassemble: Callable) -> None:
    """DECISION LEDGER (founder 2026-07-20, gradual refinement): a star tap
    is also a durable per-PHRASE decision — applied bakes into every future
    version, dismissed is never re-offered, reverted wipes the slate."""
    arc = session.get("arc_id")
    if not arc:
        return
    from services.ideal_decision_ledger import record_star_decision
    suggestion = (database.get_moment_suggestions_by_arc(arc)
                  or {}).get(str(snippet_id))
    version = _arc_version(database, arc)
    # The ledger is keyed on the phrase AS IT APPEARS IN THE DOCUMENT — not
    # the raw snippet transcript (founder bug 2026-07-22: the document is
    # smoothed, so a raw-keyed row could never be found by the bake).
    decision_text = phrase_for(
        arc, snippet_id,
        fallback=(snip.get("transcript") or snip.get("transcription_text")))
    suggestion, decision_text = _decision_subject(body, suggestion, decision_text)
    record_star_decision(
        database, arc, suggestion=suggestion, target=target, action=action,
        target_text=decision_text, snippet_id=snippet_id, version=version,
        slide_index=_slide_index(snip))
    _refresh_album(database, arc, target, action)
    _spend_budget(database, arc, snippet_id, target, action, body)
    # A dismissed star also stops being OFFERED right now: the row removal
    # kills the anchor/star on every future serve.
    if action == "dismissed":
        database.delete_moment_suggestion(str(snippet_id))
    if action in ("applied", "reverted"):
        # Living Transcript: an approved change must appear in the document
        # NOW, and an Undo must restore the original NOW.
        reassemble(arc)


def record_suggestion_feedback(database, *, session: dict, snip: dict,
                               snippet_id: str, session_id: str, user_id: Any,
                               target: str, action: str, upgrade_index: Any,
                               body: dict, phrase_for: Callable,
                               reassemble: Callable) -> bool:
    """Record the tap; whether the feedback row was written. The ledger
    work is best-effort and never breaks the POST."""
    ok = database.insert_user_suggestion_feedback(
        snippet_id=snippet_id,
        session_id=session_id,
        user_id=user_id,
        target=target,
        action=action,
        upgrade_index=upgrade_index,
        suggestion_version=(
            str(body.get("suggestion_version"))
            if body.get("suggestion_version") is not None else None
        ),
    )
    request_rebake_for_take(session, written=bool(ok))  # F3
    if target in _LEDGER_TARGETS and action in _LEDGER_ACTIONS:
        try:
            _record_star_decision(
                database, session=session, snip=snip, snippet_id=snippet_id,
                target=target, action=action, body=body,
                phrase_for=phrase_for, reassemble=reassemble)
        except Exception as led_err:
            logger.warning(
                "suggestion-feedback: ledger write failed snip=%s: %s",
                snippet_id, led_err)
    return bool(ok)
