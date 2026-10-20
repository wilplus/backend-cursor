"""
STORY    As a speaker, I want my answer to a feedback item stored against that
         item's family, so that my yes on confident voice is never read as a
         yes on another kind of feedback.
OUTCOME
  O1  A projection whose owner decision names the item's own family is accepted.
  O2  A projection whose owner decision names a different family is refused.
PROVES   O1 -> test_owner_decision_on_the_items_family_is_accepted
         O2 -> test_owner_decision_on_another_family_is_refused
"""
from __future__ import annotations

import hashlib
from typing import Any

import pytest

from services.confident_moment_bundle import (
    BUNDLE_CORE_SUMMARY_VERSION,
    BUNDLE_PROJECTION_VERSION,
    ConfidentMomentProjectionInvalid,
    validate_projection_envelope,
)

def _projection_envelope() -> dict[str, Any]:
    def identifier(number: int) -> str:
        return f"00000000-0000-0000-0000-{number:012d}"

    def coach(number: int) -> dict[str, Any]:
        return {
        "current_revision_id": identifier(number),
        "revision_sha256": "a" * 64,
        "revision_delivery_id": identifier(number + 10),
        "delivery_subject_sha256": "b" * 64,
        "presentation_id": identifier(number + 20),
        "rendered_exposure_id": None,
        "unread": True,
        }
    bundles = [{
        "bundle_id": identifier(1),
        "bundle_subject_kind": "confidence_anchor",
        "slide_index": 0,
        "block_key": 0,
        "paragraph_id": identifier(2),
        "subject": {
            "candidate_id": identifier(1),
            "evidence_span_id": identifier(3),
            "canonical_feedback_presentation_id": identifier(4),
        },
        "confidence_anchor": {
            "candidate_id": identifier(1),
            "evidence_span_id": identifier(3),
            "playback_reference_id": "opaque-playback-reference",
        },
        "exercise": None,
        "root": {
            "active_root_action_id": None,
            "interaction_state_revision": "1",
            "is_orange": False,
            "is_locked": False,
            "can_restore_previous": False,
            "restore_product_action_id": None,
        },
        "state_revision": 1,
        "feedback_language_items": [
            {
                "bundle_attachment_id": identifier(5),
                "attached_candidate_id": identifier(1),
                "feedback_family": "confident_voice",
                "canonical_feedback_exposure_id": identifier(4),
                "canonical_position": 1,
                "source_passage": {
                    "evidence_span_id": identifier(3),
                    "text": "Exact passage one.",
                    "text_sha256": hashlib.sha256(b"Exact passage one.").hexdigest(),
                },
                "update_text_available": False,
                "coach_authoring_exclusion_reason": None,
                "resolution_state": "coach_revision",
                "exclusion_reason": None,
                "output": {
                    "output_kind": "comment",
                    "comment_purpose": "confidence_explanation",
                    "text": "Exact coach comment.",
                    "origin": "coach",
                },
                "coach_update": coach(30),
                "owner_decision": None,
            },
            {
                "bundle_attachment_id": identifier(7),
                "attached_candidate_id": identifier(8),
                "feedback_family": "rewrite_clarity",
                "canonical_feedback_exposure_id": identifier(14),
                "canonical_position": 2,
                "source_passage": {
                    "evidence_span_id": identifier(9),
                    "text": "Exact passage two.",
                    "text_sha256": hashlib.sha256(b"Exact passage two.").hexdigest(),
                },
                "update_text_available": True,
                "coach_authoring_exclusion_reason": None,
                "resolution_state": "coach_revision",
                "exclusion_reason": None,
                "output": {
                    "output_kind": "rephrase",
                    "comment_purpose": None,
                    "text": "Exact coach rephrase.",
                    "origin": "coach",
                },
                "coach_update": coach(31),
                "owner_decision": None,
            },
        ],
    }]
    return {
        "bundle_projection": {
            "contract_version": BUNDLE_PROJECTION_VERSION,
            "feedback_language_shape_version": "feedback-language-items-v2",
            "project_id": identifier(100),
            "take_id": identifier(101),
            "document_snapshot_id": identifier(102),
            "feedback_membership_id": identifier(103),
            "bundles": bundles,
            "coverage": {
                "target_slide_count": 1,
                "achieved_slide_count": 0,
                "target_met": False,
            },
            "response_sha256": "c" * 64,
        },
        "confident_moment_summary": {
            "contract_version": BUNDLE_CORE_SUMMARY_VERSION,
            "document_snapshot_id": identifier(102),
            "items": [{
                "bundle_id": identifier(1),
                "paragraph_id": identifier(2),
                "slide_index": 0,
                "block_key": 0,
                "marker_present": True,
                "is_orange": False,
                "is_locked": False,
                "has_coach_update": True,
                "has_unread_coach_update": True,
                "state_revision": 1,
            }],
            "summary_sha256": "d" * 64,
        },
    }


def _envelope_with_owner_decision(family: str) -> dict[str, Any]:
    envelope = _projection_envelope()
    item = envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ][0]
    assert item["feedback_family"] == "confident_voice"
    item["owner_decision"] = {
        "feedback_family": family,
        "response": "yes",
        "decision_id": "00000000-0000-0000-0000-000000000070",
        "owner_response_id": "00000000-0000-0000-0000-000000000071",
        "response_binding_id": "00000000-0000-0000-0000-000000000072",
    }
    return envelope


def test_owner_decision_on_the_items_family_is_accepted():
    envelope = _envelope_with_owner_decision("confident_voice")
    assert validate_projection_envelope(envelope) is envelope


def test_owner_decision_on_another_family_is_refused():
    envelope = _envelope_with_owner_decision("great_formulation")
    with pytest.raises(ConfidentMomentProjectionInvalid, match="family"):
        validate_projection_envelope(envelope)
