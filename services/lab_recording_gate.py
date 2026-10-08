"""Minimum-content gate and rejected-take observability for Lab uploads."""
from __future__ import annotations

from typing import Any


class RecordingRejected(Exception):
    """The audio cannot enter analysis because no speech was detected.

    ``gate`` is read-only.

    Not a frozen dataclass, on purpose: Python writes to an exception after
    raising it (``__traceback__`` through a ``@contextmanager``,
    ``__context__`` in ``ExitStack``, ``__notes__`` from ``add_note``), and a
    frozen instance would answer with ``FrozenInstanceError`` in its place.
    """

    def __init__(self, gate: dict[str, Any]) -> None:
        super().__init__(gate)
        self._gate = gate

    @property
    def gate(self) -> dict[str, Any]:
        return self._gate


def require_analyzable_recording(
    audio_bytes: bytes,
    *,
    database: Any,
    project_id: str,
    owner_principal_id: str,
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
            project_id=project_id,
            owner_principal_id=owner_principal_id,
            user_id=user_id,
        )
    except Exception as exc:
        log.warning(
            "lab: rejected-take capture failed: %s (non-fatal)",
            exc,
        )
    raise RecordingRejected(gate)
