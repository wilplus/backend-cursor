"""The coach card's consumer of the canonical confidence chain (Q2).

The chain's producer half (promotion → outbox → frame → candidates) is
built and rehearsed; its consumer half (blind packet → render receipt →
judgment → reveal) had no application caller. This module is that caller,
for the legacy coach card: the queue coaches use today.

It writes only through the three 0393 wrappers, reads no legacy learning
store, and does nothing at all unless the writer state is ``founder_canary``
(``consumer_enabled``). In ``dark`` every function here is a no-op, so the
coach queue and the label route are byte-identical to before.

Three provenances stay apart (L3): the packet the coach sees is audio
identity only; the judgment is ``blind_coach``; the speaker's answer and the
machine's read are never in the packet and never in the handle sent to the
browser.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from uuid import UUID

from services.mlc2_confidence_cutover import configured_confidence_cutover


logger = logging.getLogger(__name__)

DELIVERY_MODE = "canary"
CLIENT_VERSION = "coach-card-blind-v1"
HANDLE_KEY = "mlc2_blind_review"
DECISION_OF = {
    "yes": "rating_yes",
    "in_between": "rating_in_between",
    "no": "rating_no",
    "not_sure": "rating_not_sure",
    "audio_unclear": "rating_audio_unclear",
}
HANDLE_FIELDS = (
    "review_assignment_id", "presentation_id",
    "acknowledgement_token", "visible_payload_sha256",
)


class ConfidenceChainConsumerError(ValueError):
    """The handle or the answer cannot be turned into a canonical write."""


def consumer_enabled() -> bool:
    """The card consumes the chain only while the chain writes."""
    return configured_confidence_cutover().canonical_writes_enabled


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ConfidenceChainConsumerError(f"{field} is not a UUID") from error


def _row(data: Any) -> Optional[dict]:
    if isinstance(data, Mapping):
        return dict(data)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return dict(data[0])
    return None


class ConfidenceChainConsumerStore:
    """Service-role RPC seam for the three 0393 wrappers."""

    def __init__(self, client: Any):
        self.client = client

    def prepare_coach_packet(
        self, *, take_id: str, snippet_id: str, reviewer_principal_id: str,
        delivery_mode: str = DELIVERY_MODE,
    ) -> Optional[dict]:
        result = self.client.rpc("prepare_mlc2_confidence_coach_packet_v1", {
            "p_take_id": _uuid(take_id, "take_id"),
            "p_snippet_id": _uuid(snippet_id, "snippet_id"),
            "p_reviewer_principal_id": _uuid(
                reviewer_principal_id, "reviewer_principal_id"),
            "p_delivery_mode": str(delivery_mode),
        }).execute()
        return _row(getattr(result, "data", None))

    def ack_render(
        self, *, review_assignment_id: str, presentation_id: str,
        acknowledgement_token: str, reviewer_principal_id: str,
        render_instance_id: str, client_rendered_at: str,
        visible_payload_sha256: str, idempotency_key: str,
        client_version: str = CLIENT_VERSION,
    ) -> Optional[dict]:
        result = self.client.rpc("ack_mlc2_confidence_coach_render_v1", {
            "p_review_assignment_id": _uuid(
                review_assignment_id, "review_assignment_id"),
            "p_presentation_id": _uuid(presentation_id, "presentation_id"),
            "p_acknowledgement_token": _uuid(
                acknowledgement_token, "acknowledgement_token"),
            "p_reviewer_principal_id": _uuid(
                reviewer_principal_id, "reviewer_principal_id"),
            "p_render_instance_id": _uuid(
                render_instance_id, "render_instance_id"),
            "p_client_rendered_at": str(client_rendered_at),
            "p_client_version": str(client_version)[:120],
            "p_visible_payload_sha256": str(visible_payload_sha256),
            "p_idempotency_key": str(idempotency_key),
        }).execute()
        return _row(getattr(result, "data", None))

    def submit_judgment(
        self, *, review_assignment_id: str, reviewer_principal_id: str,
        exposure_id: str, value: str, idempotency_key: str,
        decided_at: Optional[str] = None,
    ) -> Optional[dict]:
        decision = DECISION_OF.get(str(value))
        if decision is None:
            raise ConfidenceChainConsumerError(
                "the answer is not one of the five states")
        result = self.client.rpc("submit_mlc2_confidence_coach_judgment_v1", {
            "p_review_assignment_id": _uuid(
                review_assignment_id, "review_assignment_id"),
            "p_reviewer_principal_id": _uuid(
                reviewer_principal_id, "reviewer_principal_id"),
            "p_exposure_id": _uuid(exposure_id, "exposure_id"),
            "p_decision": decision,
            "p_decided_at": str(
                decided_at or datetime.now(timezone.utc).isoformat()),
            "p_idempotency_key": str(idempotency_key),
        }).execute()
        return _row(getattr(result, "data", None))


def coach_packet_handle(packet: Mapping[str, Any]) -> dict:
    """The four identifiers the browser needs, and nothing of the packet.

    The visible packet itself (audio object identity and span) stays on the
    server: the card already has its own playback reference, and the handle
    must never become a second channel for anything about the moment.
    """
    return {field: str(packet[field]) for field in HANDLE_FIELDS}


def attach_coach_packet(
    row: dict, *, store: ConfidenceChainConsumerStore, take_id: str,
    snippet_id: str, reviewer_principal_id: Optional[str],
) -> dict:
    """Add the chain's handle to one unlabelled queue row, when there is one.

    No-op in ``dark``, for an answered row (history, not a new exposure), for
    a reviewer without a principal, and for a snippet the chain has no
    selected candidate for (most snippets: one is selected per Take).
    """
    if not consumer_enabled() or row.get("label") is not None:
        return row
    if not reviewer_principal_id:
        return row
    try:
        packet = store.prepare_coach_packet(
            take_id=take_id, snippet_id=snippet_id,
            reviewer_principal_id=reviewer_principal_id,
        )
    except Exception as error:  # noqa: BLE001 - the queue must still serve
        logger.warning(
            "confidence chain packet not prepared take=%s snippet=%s: %s",
            take_id, snippet_id, error,
        )
        return row
    if packet and all(packet.get(field) for field in HANDLE_FIELDS):
        row[HANDLE_KEY] = coach_packet_handle(packet)
    return row


def record_coach_judgment(
    *, store: ConfidenceChainConsumerStore, handle: Any,
    reviewer_principal_id: str, value: str, idempotency_key: str,
) -> Optional[dict]:
    """Write the coach's answer as the chain's immutable judgment and reveal.

    ``handle`` is what the browser echoes back from the queue row plus the
    exposure id its render receipt returned. Returns ``None`` when the
    consumer is off; raises on a malformed handle so the caller can log it.
    """
    if not consumer_enabled():
        return None
    if not isinstance(handle, Mapping):
        raise ConfidenceChainConsumerError("mlc2 handle must be an object")
    result = store.submit_judgment(
        review_assignment_id=_uuid(
            handle.get("review_assignment_id"), "review_assignment_id"),
        reviewer_principal_id=reviewer_principal_id,
        exposure_id=_uuid(handle.get("exposure_id"), "exposure_id"),
        value=value,
        idempotency_key=idempotency_key,
    )
    if not result:
        return None
    return {
        "judgment_id": str(result.get("judgment_id") or ""),
        "review_assignment_id": str(result.get("review_assignment_id") or ""),
        "revealed": bool(result.get("revealed")),
        "replayed": bool(result.get("replayed")),
    }
