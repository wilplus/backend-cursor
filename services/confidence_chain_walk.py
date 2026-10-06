"""The coach walk's adapter onto the confidence chain (N48.5 Q27 A).

Founder 2026-10-05: "the coach walk's blind labels as its judgements". The
walk's Judge screen asks, when it paints a moment, whether the chain holds a
selected candidate for that moment
(``POST /coach/snippets/<id>/mlc2-packet``, routes/v2/confidence_chain_coach.py).
If so, the blind packet is prepared for THIS coach through the 0393 wrapper
(``attach_coach_packet``, services/confidence_chain_consumer.py) and the four
identifiers come back; the screen acknowledges the paint and echoes them on
its label PUT, which writes the immutable blind_coach judgement.

Who gets no packet (the route then answers null):

  * everyone while the chain is not writing (``consumer_enabled``);
  * a moment with no Take, or none the chain selected;
  * a coach who has seen the moment's non-blind side (35g-11,
    ``services.coach_exposure.rating_is_blind``);
  * a coach who already judged the moment: their first answer is the
    judgement of record (0427: a later one is a reconsideration), and a
    second listen is never a blind judgement;
  * any failure: the walk is never refused over the chain.

Nothing about the moment leaves the server: the handle is four identifiers
(BLIND COACH). The read of this coach's own rating is routing, never a label
the chain stores (L3).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.confidence_chain_consumer import (
    HANDLE_KEY,
    ConfidenceChainConsumerStore,
    attach_coach_packet,
    consumer_enabled,
)

_log = logging.getLogger(__name__)


def already_rated(database: Any, coach_id: str, snippet_id: str) -> bool:
    """Whether THIS coach has a saved rating on the moment. Unknown reads as
    rated: no packet is the safe side."""
    try:
        rows = (database.get_confidence_labels_by_snippet_ids([snippet_id]) or {}).get(
            snippet_id) or []
    except Exception as error:  # noqa: BLE001 - named; no packet is the safe side
        _log.warning("walk rating read failed snip=%s: %s", snippet_id, error,
                     exc_info=True)
        return True
    return any(isinstance(row, dict) and str(row.get("rater_id") or "") == str(coach_id)
               for row in rows)


def walk_packet(database: Any, *, coach_id: str, snippet_id: str) -> Optional[dict]:
    """The four-id handle for this coach on this moment, or None."""
    if not coach_id or not consumer_enabled():
        return None
    try:
        row = database.get_snippet_by_id(snippet_id) or {}
        take_id = str(row.get("session_id") or "")
        from services.coach_exposure import rating_is_blind
        if (not take_id
                or not rating_is_blind(database, coach_id=coach_id, snippet_id=snippet_id)
                or already_rated(database, coach_id, snippet_id)):
            return None
        principal = database.get_owner_principal_for_user(coach_id) or {}
        handled = attach_coach_packet(
            {"label": None}, store=ConfidenceChainConsumerStore(database.client),
            take_id=take_id, snippet_id=snippet_id,
            reviewer_principal_id=str(principal.get("id") or "") or None,
        )
    except Exception as error:  # noqa: BLE001 - named; the walk is never refused
        _log.warning("walk packet not prepared snip=%s: %s", snippet_id, error,
                     exc_info=True)
        return None
    return handled.get(HANDLE_KEY)
