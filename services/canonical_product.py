"""Canonical product language for the presentation-rehearsal MVP.

Routes and services use these names even while the persistence adapter still
maps a few of them onto historical ``arc``/``session``/``snippet`` columns.
No product rule belongs in that compatibility mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class ProcessingState(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class FeedbackFamily(StrEnum):
    CONFIDENT_VOICE = "confident_voice"
    GREAT_FORMULATION = "great_formulation"
    REWRITE_FOR_CLARITY = "rewrite_for_clarity"


class FeedbackDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CoachReviewState(StrEnum):
    REVIEWED = "reviewed"
    REFINED = "refined"
    MATERIAL_CORRECTION = "material_correction"
    NOT_CONFIRMED = "not_confirmed"


@dataclass(frozen=True)
class FeedbackItem:
    """One user-facing observation or proposal with exact evidence.

    Machine generation, the user's decision and the coach's later review are
    separate facts.  A coach review may supersede the explanation or proposal,
    but it never rewrites accepted Ideal Text by itself.
    """

    id: str
    family: FeedbackFamily
    message: str
    evidence: "EvidenceLocator"
    review_state: CoachReviewState | None = None
    replacement_text: str | None = None
    application_guidance: str | None = None
    examples: tuple[str, ...] = ()
    user_decision: FeedbackDecision = FeedbackDecision.PENDING


@dataclass(frozen=True)
class OwnerPrincipal:
    id: str
    user_id: str | None
    is_guest: bool


@dataclass(frozen=True)
class Project:
    id: str
    owner_principal_id: str
    display_name: str
    setup: Mapping[str, Any]


@dataclass(frozen=True)
class EvidenceLocator:
    """Exact location shared by machine feedback and professional review."""

    project_id: str
    take_id: str
    slide_index: int
    paragraph_index: int
    evidence_span: Mapping[str, Any]
    audio_interval: Mapping[str, Any] | None = None
    piece_id: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id or not self.take_id:
            raise ValueError("project_id and take_id are required")
        if self.slide_index < 0 or self.paragraph_index < 0:
            raise ValueError("slide and paragraph indexes must be non-negative")


@dataclass(frozen=True)
class CreateTake:
    project_id: str
    owner_principal_id: str
    idempotency_key: str
    session_context: Mapping[str, Any]


@dataclass(frozen=True)
class TakeAccepted:
    project_id: str
    take_id: str
    take_index: int
    state: ProcessingState = ProcessingState.PROCESSING
