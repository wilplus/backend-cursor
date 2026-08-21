"""Minimum-content gate and rejected-take observability for Lab uploads."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RecordingRejected(Exception):
    """The audio cannot enter analysis because no speech was detected."""

    gate: dict[str, Any]


def require_analyzable_recording(
    audio_bytes: bytes,
    *,
    database: Any,
    form: Mapping[str, Any],
    user_id: str | None,
    log: Any,
) -> dict[str, Any]:
    """Return gate metrics or record the rejection and stop processing."""
    from services.min_content_gate import evaluate_min_content_bytes

    gate = evaluate_min_content_bytes(audio_bytes)
    if gate["ok"]:
        return gate

    # Gate-failed takes have no stored audio. Retain metrics only so model
    # monitoring sees rejected examples without adding voice-data cost/risk.
    try:
        database.insert_rejected_take(
            reason=gate.get("reason"),
            duration_sec=gate.get("duration_sec"),
            voiced_sec=gate.get("voiced_sec"),
            thresholds=gate.get("thresholds"),
            user_id=user_id,
            guest_session_id=(form.get("guest_session_id") or None),
            arc_id=(form.get("arc_id") or None),
            take_index=form.get("take_index"),
        )
    except Exception as exc:
        log.warning(
            "lab: rejected-take capture failed: %s (non-fatal)",
            exc,
        )
    raise RecordingRejected(gate)
