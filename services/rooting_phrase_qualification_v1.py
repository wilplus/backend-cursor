"""Disabled RPQ-V1 service contract.

The SQL layer owns provenance and state transitions.  This module only maps a
typed routing state to the founder-approved qualitative controls.  It exposes
no score and contains no runtime-enabling configuration path in this slice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RPQ_V1_RUNTIME_ENABLED = False

RoutingState = Literal[
    "eligible_direct",
    "eligible_after_rerecord",
    "pending_recording",
    "pending_owner_alignment_confirmation",
    "blocked_semantic_mismatch",
    "blocked_semantic_unavailable",
    "blocked_confidence_response",
    "blocked_audio_or_transcript",
    "blocked_existing_block_root",
    "stale_text_revision",
    "invalidated",
]


@dataclass(frozen=True)
class RootingPhraseControls:
    primary_action: str | None
    secondary_action: str | None
    coverage_state: Literal["ready", "pending"]


def controls_for_state(state: RoutingState) -> RootingPhraseControls:
    """Return qualitative RPQ controls without surfacing machine internals."""
    if state == "eligible_direct":
        return RootingPhraseControls(
            "lock_and_make_rooting_phrase", "lock_only", "ready"
        )
    if state == "eligible_after_rerecord":
        return RootingPhraseControls("make_rooting_phrase", "not_now", "ready")
    if state == "pending_recording":
        return RootingPhraseControls("practice_this_phrase", None, "pending")
    if state == "pending_owner_alignment_confirmation":
        return RootingPhraseControls(
            "confirm_phrase_anchors_point", "reject_for_slide", "pending"
        )
    return RootingPhraseControls(None, None, "pending")


def runtime_is_enabled() -> bool:
    """Structural kill switch for the local synthetic implementation."""
    return RPQ_V1_RUNTIME_ENABLED

