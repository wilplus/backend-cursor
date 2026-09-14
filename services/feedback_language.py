"""Feedback Language typed outputs (Chunk 3).

One product/service abstraction with two output kinds: comment | rephrase.
Does not merge the existing canonical learning surfaces into an undifferentiated
dataset. Model reuse across typed surfaces requires a separate training design.

See Contract Delta D3 §4 and Interface Manifest D6 §4.1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FEEDBACK_LANGUAGE_OUTPUT_VERSION = "feedback-language-output-v1"
FEEDBACK_LANGUAGE_COACH_REVISION_VERSION = "feedback-language-coach-revision-v1"

OutputKind = Literal["comment", "rephrase"]
CommentPurpose = Literal[
    "confidence_explanation",
    "actionable_observation",
    "positive_praise",
]
RevisionOrigin = Literal["machine", "coach"]

# Canonical family retained for provenance (never collapsed)
FAMILY_FOR_PURPOSE: dict[CommentPurpose, str] = {
    "confidence_explanation": "confident_voice",
    "actionable_observation": "rewrite_clarity",
    "positive_praise": "great_formulation",
}
FAMILY_FOR_REPHRASE = "rewrite_clarity"


@dataclass(frozen=True)
class FeedbackLanguageOutput:
    output_kind: OutputKind
    comment_purpose: CommentPurpose | None  # required for comment, null for rephrase
    revision_origin: RevisionOrigin
    text: str
    canonical_family: str
    candidate_output_sha256: str | None = None


def build_comment(
    purpose: CommentPurpose,
    text: str,
    *,
    origin: RevisionOrigin = "machine",
    candidate_output_sha256: str | None = None,
) -> FeedbackLanguageOutput:
    if not text or not text.strip():
        raise ValueError("comment text must be non-empty")
    return FeedbackLanguageOutput(
        output_kind="comment",
        comment_purpose=purpose,
        revision_origin=origin,
        text=text.strip(),
        canonical_family=FAMILY_FOR_PURPOSE[purpose],
        candidate_output_sha256=candidate_output_sha256,
    )


def build_rephrase(
    text: str,
    *,
    origin: RevisionOrigin = "machine",
    candidate_output_sha256: str | None = None,
) -> FeedbackLanguageOutput:
    if not text or not text.strip():
        raise ValueError("rephrase text must be non-empty")
    return FeedbackLanguageOutput(
        output_kind="rephrase",
        comment_purpose=None,
        revision_origin=origin,
        text=text.strip(),
        canonical_family=FAMILY_FOR_REPHRASE,
        candidate_output_sha256=candidate_output_sha256,
    )


def validate_output_kind_and_purpose(
    output_kind: str,
    comment_purpose: str | None,
) -> None:
    """Fail closed on illegal combinations."""
    if output_kind == "rephrase":
        if comment_purpose is not None:
            raise ValueError("rephrase must have null comment_purpose")
        return
    if output_kind == "comment":
        if comment_purpose not in (
            "confidence_explanation",
            "actionable_observation",
            "positive_praise",
        ):
            raise ValueError(f"invalid comment_purpose: {comment_purpose!r}")
        return
    raise ValueError(f"invalid output_kind: {output_kind!r}")
