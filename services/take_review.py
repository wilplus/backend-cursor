"""Durable review finalization for spoken Takes after Take 1.

Take 1 owns document creation.  A later Take owns a new review identity and a
new immutable feedback set, but it must never rebuild or silently overwrite the
canonical words.  This service is the one boundary between those two facts.

Success is intentionally proven twice: the atomic RPC returns a receipt, then
fresh reads confirm both the current row and the requested historical snapshot.
An in-memory return value is not durable state and cannot release processing.
"""
from __future__ import annotations

from typing import Any

from services.ideal_text_confirmation import confirmed_ideal_text


class TakeReviewFinalizationError(RuntimeError):
    """A later Take could not establish its durable Ideal Text review state."""

    def __init__(self, take_session_id: str, reason: str):
        super().__init__(f"Take review was not finalized: {reason}")
        self.take_session_id = str(take_session_id)
        self.reason = str(reason)


def _take_number(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def finalize_later_take_review(
    database: Any,
    *,
    arc_id: str,
    owner_user_id: str,
    take_session_id: str,
    take_index: int,
) -> dict:
    """Advance one later spoken Take and return its confirmed version receipt.

    The Take/session/owner/Project tuple is checked here and again inside the
    transaction.  A stale browser marker or retry can therefore never advance
    a different Project merely because it knows an arc id.
    """
    index = _take_number(take_index)
    if index is None or index < 2:
        raise TakeReviewFinalizationError(
            take_session_id, "later Take index is invalid")
    if not arc_id or not owner_user_id or not take_session_id:
        raise TakeReviewFinalizationError(
            take_session_id, "Project, owner, and Take identities are required")

    session = database.v2_get_session_by_id(str(take_session_id)) or {}
    if str(session.get("id") or "") != str(take_session_id):
        raise TakeReviewFinalizationError(take_session_id, "Take is missing")
    if str(session.get("arc_id") or "") != str(arc_id):
        raise TakeReviewFinalizationError(
            take_session_id, "Take belongs to a different Project")
    if str(session.get("user_id") or "") != str(owner_user_id):
        raise TakeReviewFinalizationError(
            take_session_id, "Take belongs to a different owner")
    if _take_number(session.get("take_index")) != index:
        raise TakeReviewFinalizationError(
            take_session_id, "Take index does not match its stored session")
    if session.get("recording_kind") == "read" \
            or session.get("paired_session_id"):
        raise TakeReviewFinalizationError(
            take_session_id, "only a spoken Take has a review version")

    before = confirmed_ideal_text(
        database.get_coach_arc_ideal_text(str(arc_id)))
    if before is None:
        raise TakeReviewFinalizationError(
            take_session_id, "canonical Ideal Text is missing")
    old_version = _take_number(before.get("version")) or 1
    owner_edit_before = database.get_user_ideal_edit(
        str(arc_id), str(owner_user_id))

    # The snapshot's reasoning remains sanitized at write time, matching the
    # Take 1 assembler.  It is history/provenance, not the Manager's visible
    # feedback set (which has its own immutable table).
    try:
        from services.ideal_text_block import sanitize_suggestions_snapshot

        suggestions = database.get_moment_suggestions_by_arc(str(arc_id)) or {}
        moments = sanitize_suggestions_snapshot(suggestions)
    except Exception:
        moments = []

    try:
        receipt = database.finalize_ideal_text_take(
            str(arc_id),
            str(owner_user_id),
            str(take_session_id),
            index,
            moments,
        )
    except Exception as exc:
        raise TakeReviewFinalizationError(
            take_session_id, "atomic database finalizer failed") from exc
    if not isinstance(receipt, dict) \
            or _take_number(receipt.get("version")) != index \
            or str(receipt.get("arc_id") or "") != str(arc_id) \
            or str(receipt.get("take_session_id") or "") \
            != str(take_session_id) \
            or _take_number(receipt.get("take_index")) != index \
            or receipt.get("text_confirmed") is not True:
        raise TakeReviewFinalizationError(
            take_session_id, "database finalizer returned no confirmation")

    after = confirmed_ideal_text(
        database.get_coach_arc_ideal_text(str(arc_id)))
    current_version = _take_number((after or {}).get("version"))
    if after is None or current_version is None or current_version < index:
        raise TakeReviewFinalizationError(
            take_session_id, "current review version was not observable")
    snapshot = database.get_ideal_text_version(str(arc_id), index) or {}
    if not str(snapshot.get("text") or "").strip():
        raise TakeReviewFinalizationError(
            take_session_id, "historical review snapshot was not observable")

    # When this operation actually advances the current version, a current
    # owner edit must remain byte-for-byte current.  That is the mechanical L1
    # proof that "new review" did not mean "discard the user's words".
    if (index > old_version and isinstance(owner_edit_before, dict)
            and owner_edit_before.get("version") == old_version
            and str(owner_edit_before.get("text") or "").strip()):
        owner_edit_after = database.get_user_ideal_edit(
            str(arc_id), str(owner_user_id)) or {}
        if (owner_edit_after.get("version") != index
                or owner_edit_after.get("text") != owner_edit_before.get("text")):
            raise TakeReviewFinalizationError(
                take_session_id, "owner edit was not preserved")

    # Publish the exact later-Take review state before returning. The
    # canonical words remain untouched; only their immutable cold-open read
    # model advances. The GET path never repairs a missing snapshot.
    from services.ideal_text_core_snapshot import publish_for_arc
    publish_for_arc(database, str(arc_id), str(owner_user_id))

    return {
        **after,
        "version": index,
        "current_version": current_version,
        "take_session_id": str(take_session_id),
        "take_index": index,
        "review_finalized": True,
    }
