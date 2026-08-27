"""Fail-closed Confidence Classification cutover state.

The state is code-reviewed rather than environment-controlled.  In particular,
an incident rollback changes ``founder_canary`` to ``killed``—never back to
``dark``—so old learning supervision cannot silently resume.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DARK = "dark"
FOUNDER_CANARY = "founder_canary"
KILLED = "killed"
VALID_MODES = frozenset({DARK, FOUNDER_CANARY, KILLED})


@dataclass(frozen=True)
class ConfidenceCutoverState:
    mode: str
    canonical_writes_enabled: bool
    prior_learning_writes_enabled: bool
    valid_configuration: bool


def resolve_confidence_cutover(value: Any) -> ConfidenceCutoverState:
    """Resolve one atomic writer decision; malformed input fails fully shut."""
    configured = str(value or "").strip().lower()
    valid = configured in VALID_MODES
    mode = configured if valid else KILLED
    return ConfidenceCutoverState(
        mode=mode,
        canonical_writes_enabled=mode == FOUNDER_CANARY,
        prior_learning_writes_enabled=mode == DARK,
        valid_configuration=valid,
    )


def configured_confidence_cutover() -> ConfidenceCutoverState:
    from config import Config

    return resolve_confidence_cutover(Config.MLC2_CONFIDENCE_CUTOVER_MODE)
