"""The owner's answer to one frozen feedback item on their Take (POST
/v2/user/takes/<take_session_id>/feedback-response).

Moved out of ``routes.v2.user_sessions`` unchanged (founder 2026-10-12). The
route keeps the ownership gate (the Take is the caller's own, on a project)
and the 500 boundary. The answer is a self-report with its own provenance: it
never overwrites a coach judgment, never becomes a gold label, and can only
name an item in this exact Take's frozen set (L3).

Writes, in order, for a first answer: the self-report, the Take's rebake
request, the canonical dual write, the budget row, then for Confident Voice
the Voice Album route and its refresh, and the follow-up. A changed
Confident Voice judgement (QA1 A, D-FW-9) is kept BESIDE the first and only
moves the Album and the coach routing.
"""
from __future__ import annotations

from typing import Any, Callable

from services.ideal_text_feedback_bake import request_rebake_for_take
from services.refusal import Refusal
from services.take_feedback_responses import album_routing_for

_REVISED = ("revised", "revised_replay")
_IDENTITY_KEYS = ("candidate_id", "feedback_membership_id", "feedback_exposure_id")


def route_owner_voice_album(database, *, row: dict, arc_id: str,
                            owner_user_id: str) -> bool:
    """Write the owner's Confident Voice answer as the Voice Album route.

    The answer routes as itself (F-4): the five states are stored whole,
    never folded into the legacy neutral/unrateable pair. Routing only; it
    is never a label."""
    snip = database.get_snippet_by_id(row["snippet_id"]) or {}
    piece = ((snip.get("metrics") or {}).get("piece")
             if isinstance(snip.get("metrics"), dict) else {})
    return bool(database.upsert_owner_voice_album_route(
        snippet_id=row["snippet_id"],
        owner_user_id=owner_user_id,
        arc_id=arc_id,
        response=album_routing_for(row["response"]),
        slide_index=(piece.get("slide_index")
                     if isinstance(piece, dict) else None),
    ))


def _changed_judgement(database, row: dict, outcome: str, result: dict,
                       take_session_id: str, owner_user_id: str) -> tuple[str, dict]:
    """A changed Confident Voice judgement is kept BESIDE the first (founder
    QA1 A, D-FW-9): the first answer's row is never touched; the latest is a
    revision every reader overlays. Only a Confident Voice judgement reopens:
    a rewrite's answer wrote the Paragraph (L1). Returns (outcome, result):
    "revised" or "revised_replay" with the revision's result,
    "revision_failed" when a change could not be saved, else what the first
    writer said."""
    if (outcome not in ("conflict", "replayed")
            or row["feedback_family"] != "confident_voice"):
        return outcome, result
    change = database.revise_take_feedback_self_report(
        take_session_id=take_session_id, owner_user_id=owner_user_id,
        feedback_id=row["feedback_id"], response=row["response"]) or {}
    revision = str(change.get("outcome") or "")
    try:
        changed_before = int((change.get("row") or {}).get("revision") or 0) > 0
    except (TypeError, ValueError):
        changed_before = False
    if revision == "revised":
        return "revised", change
    if revision == "replayed" and (outcome == "conflict" or changed_before):
        return "revised_replay", change
    if not revision:
        # GPT-0440: if the revision cannot be saved the latest answer is
        # stale, so the speaker is told it did not save.
        return "revision_failed", result
    return outcome, result


def _album_and_follow_up(database, row, arc_id, take_session_id,
                         owner_user_id, follow_up_for) -> str:
    """The Album route and refresh, then the follow-up (founder 2026-09-29:
    a judgement is always answered)."""
    if not row.get("snippet_id"):
        return "none"
    route_owner_voice_album(database, row=row, arc_id=arc_id,
                            owner_user_id=owner_user_id)
    from services.voice_album import refresh_voice_album
    refresh_voice_album(arc_id, database=database)
    return follow_up_for(
        database, take_session_id=take_session_id,
        snippet_id=str(row["snippet_id"]), owner_user_id=owner_user_id,
        answer=row["response"])


def _revised(database, row, arc_id, take_session_id, owner_user_id) -> dict:
    """A changed judgement: the Album and coach routing follow the latest
    answer; the canonical ledger and the spend keep the first resolution."""
    from services.judgement_follow_up import follow_up_for_revision
    follow_up = _album_and_follow_up(database, row, arc_id, take_session_id,
                                     owner_user_id, follow_up_for_revision)
    return {
        "saved": True, "revised": True,
        "feedback_id": row["feedback_id"],
        "feedback_family": row["feedback_family"],
        "response": row["response"], "follow_up": follow_up,
    }


def _first_answer_outcome(database, *, row, arc_id, take_session_id,
                          owner_user_id) -> tuple[str, dict]:
    result = database.insert_take_feedback_self_report(
        arc_id=arc_id, take_session_id=take_session_id,
        owner_user_id=owner_user_id, **row)
    if result is None:
        raise Refusal("V2_ERROR", "Could not save this response.", 500)
    outcome = str(result.get("outcome") or "")
    if outcome == "not_member":
        raise Refusal("INVALID_INPUT",
                      "feedback item is not in this Take's frozen set", 400)
    if outcome == "provenance_mismatch":
        raise Refusal("INVALID_INPUT",
                      "snippet provenance does not match the feedback item", 400)
    outcome, result = _changed_judgement(database, row, outcome, result,
                                         take_session_id, owner_user_id)
    if outcome == "conflict":
        raise Refusal("RESPONSE_ALREADY_FINAL", "This response is already final.", 409)
    if outcome not in ("saved", "replayed", *_REVISED) \
            or not isinstance(result.get("row"), dict):
        raise Refusal("V2_ERROR", "Could not save this response.", 500)
    return outcome, result


def _spend(database, arc_id, row) -> None:
    """The budget row records that the item was explicitly resolved; its key
    includes the frozen feedback identity, so families sharing one snippet
    cannot overwrite each other."""
    from services.intervention_spend import spend
    family = row["feedback_family"]
    spend(
        database, arc_id, database.takes.get_arc_sessions(arc_id) or [],
        change_key=f"feedback:{family}:{row['feedback_id']}",
        decision=("approved" if row["response"] in (
            "yes", "apply_suggestion", "useful") else "disregarded"),
        lane=f"feedback:{family}",
        intervention_type=("NOTICE" if family == "confident_voice"
                           else "REWRITE" if family == "rewrite_clarity"
                           else "EMPHASISE"),
    )


def save_feedback_answer(database, *, session: dict, take_session_id: str,
                         owner_user_id: str, body: dict,
                         text_update: Callable[..., dict]) -> dict:
    """Record the owner's answer; the response body. ``text_update`` is the
    accepted rewrite's Paragraph read (29b P1-1). Raises ``Refusal``."""
    arc_id = str(session["arc_id"])
    from services.take_feedback_responses import parse_feedback_response
    row: Any
    row, err = parse_feedback_response(body)
    if err:
        raise Refusal("INVALID_INPUT", err, 400)
    canonical_identity = {key: row.pop(key, None) for key in _IDENTITY_KEYS}
    outcome, result = _first_answer_outcome(
        database, row=row, arc_id=arc_id, take_session_id=take_session_id,
        owner_user_id=owner_user_id)
    request_rebake_for_take(session)  # F3: the answer retired the bake
    # Downstream writes use the database-derived snippet provenance, never
    # the request echo.
    row = {**row, "snippet_id": result["row"].get("snippet_id")}
    if outcome in _REVISED:
        return _revised(database, row, arc_id, take_session_id, owner_user_id)
    from services.take_feedback_responses import canonical_dual_write
    canonical_dual_write(database, session, take_session_id, owner_user_id,
                         row, canonical_identity,
                         {"selected_keys": result.get("selected_keys") or []})
    _spend(database, arc_id, row)
    follow_up = "none"
    if row["feedback_family"] == "confident_voice":
        from services.judgement_follow_up import follow_up_for_judgement
        follow_up = _album_and_follow_up(database, row, arc_id, take_session_id,
                                         owner_user_id, follow_up_for_judgement)
    return {
        "saved": True,
        "feedback_id": row["feedback_id"],
        "feedback_family": row["feedback_family"],
        "response": row["response"],
        "follow_up": follow_up,
        **text_update(database, row, arc_id, owner_user_id, take_session_id),
    }
