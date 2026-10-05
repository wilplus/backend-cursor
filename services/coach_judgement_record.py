"""The coach's judgment, recorded once in the canonical store too (the
append-only shadow the rating route dual-writes; moved here from the route
when W6, 2026-10-05, made the route's original judgment stand: LOCKIN §5c,
contract 34).

The legacy current-answer row (confidence_labels) remains the live read
during parity; the canonical row preserves the original blind judgment and
any later reconsideration as a superseding revision. The lookup reads
evidence only, never owner, machine or peer answers. Never in the rating's
way: a failure is logged and the rating stands.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def canonical_dual_write(database: Any, *, session_id: Any, snippet_id: Any,
                        rater_id: Any, value: Any,
                        request_idempotency_key: Any) -> None:
    """Append-only canonical shadow. The legacy current-answer row remains
    the live read during parity; this row preserves the original blind
    judgment and any later reconsideration as a superseding revision. The
    lookup reads evidence only—never owner/machine/peer answers. Never in
    the rating's way."""
    try:
        from services.feedback_data_contract import (
            TAXONOMY_VERSION,
            blind_packet_hash,
            content_hash,
        )

        canonical_evidence = database.ideal_text.get_canonical_confidence_evidence(
            take_id=str(session_id), snippet_id=str(snippet_id),
        )
        if canonical_evidence is None:
            return
        packet_hash = blind_packet_hash(canonical_evidence)
        supplied_key = request_idempotency_key
        canonical_key = (
            supplied_key.strip()
            if isinstance(supplied_key, str) and supplied_key.strip()
            else "coach-confidence:" + content_hash({
                "request_id": str(uuid.uuid4()),
                "take_id": str(session_id),
                "snippet_id": str(snippet_id),
                "coach_id": str(rater_id),
                "value": value,
            })
        )
        canonical_assignment = (
            database.assign_canonical_coach_confidence_evidence(
                take_id=str(session_id),
                evidence_span_id=str(canonical_evidence["evidence_span_id"]),
                coach_id=str(rater_id),
                blind_packet_hash=str(packet_hash),
                assignment_reason="blind_confidence_queue",
                idempotency_key=("coach-assignment:" + canonical_key),
            ) if packet_hash else None
        )
        canonical_label = (
            database.record_canonical_coach_confidence_judgment(
                evidence_span_id=str(canonical_evidence["evidence_span_id"]),
                coach_id=str(rater_id),
                value=value,
                taxonomy_version=TAXONOMY_VERSION,
                blind_packet_hash=str(packet_hash),
                idempotency_key=canonical_key,
            ) if canonical_assignment is not None else None
        )
        if canonical_label is None:
            logger.warning("canonical coach label dual-write missing take=%s snippet=%s",
                           session_id, snippet_id)
    except Exception as canonical_error:
        logger.warning(
            "canonical coach label dual-write failed take=%s "
            "snippet=%s: %s", session_id, snippet_id, canonical_error,
            exc_info=True,
        )
