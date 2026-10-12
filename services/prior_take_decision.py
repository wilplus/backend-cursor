"""The speaker's decision on a cross-take change (POST
/explore/arc/<arc_id>/prior-take/decide, founder 2026-07-20 #4).

Moved out of ``routes.v2.explore_ideal_text`` unchanged (founder 2026-10-12).
The route keeps the Living Transcript flag and the ownership gate.

  accept → the PREVIOUS take's wording replaces the current one and BAKES
           FORWARD: an approved ledger row keyed on the current phrase.
  keep   → the current wording stands; the offer is remembered as dismissed.

Writes, in order: the decision ledger, the Take's budget, the rebake request,
then (accept only) the document's reassembly. Nothing is written into the
Paragraph without the speaker's accept (L1).
"""
from __future__ import annotations

from typing import Any, Callable

from services.ideal_text_feedback_bake import request_rebake_after_answer
from services.refusal import Refusal


def _decision_inputs(body: dict) -> tuple[str, str, str, str]:
    action = body.get("action")
    if action not in ("accept", "keep"):
        raise Refusal("INVALID_INPUT", "action must be accept or keep", 400)
    quote = (body.get("quote") or "").strip()
    snippet_id = (body.get("snippet_id") or "").strip()
    proposed = (body.get("proposed_text") or "").strip()
    if not quote or not snippet_id:
        raise Refusal("INVALID_INPUT", "quote and snippet_id are required", 400)
    if action == "accept" and not proposed:
        raise Refusal("INVALID_INPUT", "proposed_text is required", 400)
    return action, quote, snippet_id, proposed


def _document_version(database, arc_id: str) -> Any:
    try:
        return (database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}).get("version")
    except Exception:
        return None


def _why_key(body: dict) -> Any:
    why = body.get("why_key")
    return str(why) if isinstance(why, str) and why.strip() else None


def decide_prior_take(database, *, arc_id: str, sessions: list, body: dict,
                      user_id: Any, reassemble: Callable) -> bool:
    """Record the decision; whether the ledger row was written. Raises a
    400 ``Refusal`` for an invalid body."""
    action, quote, snippet_id, proposed = _decision_inputs(body)
    from services.ideal_decision_ledger import normalize_phrase
    version = _document_version(database, arc_id)
    ok = database.upsert_ideal_decision(
        arc_id=str(arc_id), kind="replace",
        target_phrase=normalize_phrase(quote), display_phrase=quote,
        replacement_text=(proposed if action == "accept" else None),
        decision=("approved" if action == "accept" else "dismissed"),
        source="prior_take", snippet_id=snippet_id,
        version=(version if isinstance(version, int) else None))
    if ok:
        # THE TAKE'S BUDGET (founder 2026-08-10): a decided offer keeps its
        # slot — approved and kept alike; deciding is what spends. Also SPEC
        # §6's ground-truth row. PROPOSAL HISTORY (slice 2): the quote always
        # rides; the replacement rides on accepts.
        from services.intervention_spend import spend
        spend(database, arc_id, sessions,
              change_key="prior_take:" + normalize_phrase(quote),
              decision=("approved" if action == "accept" else "disregarded"),
              lane="lane:prior_take", intervention_type="REWRITE",
              quote=quote, proposed_text=(proposed or None),
              why_key=_why_key(body))
        request_rebake_after_answer(arc_id, str(user_id))  # F3
    if ok and action == "accept":
        reassemble(arc_id)
    return bool(ok)
