"""Focused unit tests for Confident Moment Bundle application logic (Chunk 3).

No PostgreSQL, no browser, no live DB. Pure projection and policy tests plus
mocked-RPC repository tests.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from services.confident_moment_bundle import (
    BUNDLE_CORE_SUMMARY_VERSION,
    BUNDLE_PROJECTION_VERSION,
    ConfidentMomentProjectionInvalid,
    runtime_is_enabled,
    validate_family_response,
    validate_projection_envelope,
    validate_bundle_item_render_receipt,
    validate_coach_update_render_receipt,
)
from services.confident_moment_bundle_repository import (
    ConfidentMomentBundleDisabled,
    ConfidentMomentBundleRepository,
)
from services.feedback_language import (
    build_comment,
    build_rephrase,
    validate_output_kind_and_purpose,
)
from services.rooting_coverage import (
    AnchorCandidate,
    coverage_target_for_take,
    extract_exact_clauses,
    lexicographic_coverage_order,
    one_root_per_block_ok,
)

# ── Gate ────────────────────────────────────────────────────────────────────


def test_runtime_gate_is_disabled_by_default():
    assert runtime_is_enabled() is False


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


def test_d12_two_coach_items_are_passed_through_without_fold():
    envelope = _projection_envelope()
    assert validate_projection_envelope(envelope) is envelope
    items = envelope["bundle_projection"]["bundles"][0]["feedback_language_items"]
    assert [item["coach_update"]["current_revision_id"] for item in items] == [
        "00000000-0000-0000-0000-000000000030",
        "00000000-0000-0000-0000-000000000031",
    ]


def test_projection_rejects_cross_item_currentness_and_forbidden_fields():
    envelope = _projection_envelope()
    envelope["bundle_projection"]["bundles"][0]["feedback_language_items"][1][
        "coach_update"
    ]["unread"] = False
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_projection_envelope(envelope)


def test_d49_owner_decision_is_exact_and_family_bound():
    envelope = _projection_envelope()
    item = envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ][0]
    item["owner_decision"] = {
        "feedback_family": "confident_voice",
        "response": "yes",
        "decision_id": "00000000-0000-0000-0000-000000000070",
        "owner_response_id": "00000000-0000-0000-0000-000000000071",
        "response_binding_id": "00000000-0000-0000-0000-000000000072",
    }
    assert validate_projection_envelope(envelope) is envelope

    item["owner_decision"]["feedback_family"] = "great_formulation"
    with pytest.raises(ConfidentMomentProjectionInvalid, match="family"):
        validate_projection_envelope(envelope)


def test_d49_rejects_old_or_mixed_feedback_language_item_shape():
    envelope = _projection_envelope()
    envelope["bundle_projection"]["feedback_language_shape_version"] = (
        "feedback-language-items-v1"
    )
    with pytest.raises(ConfidentMomentProjectionInvalid, match="shape"):
        validate_projection_envelope(envelope)

    envelope = _projection_envelope()
    del envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ][0]["owner_decision"]
    with pytest.raises(ConfidentMomentProjectionInvalid, match="keys"):
        validate_projection_envelope(envelope)


@pytest.mark.parametrize(
    ("family", "response", "has_confidence_binding"),
    [
        ("confident_voice", "yes", True),
        ("confident_voice", "in_between", True),
        ("confident_voice", "no", True),
        ("confident_voice", "not_sure", True),
        ("confident_voice", "audio_unclear", True),
        ("rewrite_clarity", "apply_suggestion", False),
        ("rewrite_clarity", "keep_wording", False),
        ("great_formulation", "useful", False),
        ("great_formulation", "not_useful", False),
        ("great_formulation", "not_sure", False),
    ],
)
def test_d49_family_response_vocabulary_is_closed(
    family: str, response: str, has_confidence_binding: bool,
):
    result = {
        "family_response_contract_version": "confident-moment-family-response-v1",
        "bundle_id": "00000000-0000-0000-0000-000000000001",
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000005",
        "feedback_family": family,
        "response": response,
        "decision_id": "00000000-0000-0000-0000-000000000070",
        "owner_response_id": (
            "00000000-0000-0000-0000-000000000071"
            if has_confidence_binding else None
        ),
        "response_binding_id": (
            "00000000-0000-0000-0000-000000000072"
            if has_confidence_binding else None
        ),
        "dataset_eligible": False,
    }
    assert validate_family_response(
        result, bundle_id=result["bundle_id"],
        attachment_id=result["bundle_attachment_id"],
    ) is result


def test_d49_rewrite_not_sure_is_not_a_bundle_owner_response():
    result = {
        "family_response_contract_version": "confident-moment-family-response-v1",
        "bundle_id": "00000000-0000-0000-0000-000000000001",
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000005",
        "feedback_family": "rewrite_clarity",
        "response": "rewrite_not_sure",
        "decision_id": "00000000-0000-0000-0000-000000000070",
        "owner_response_id": None,
        "response_binding_id": None,
        "dataset_eligible": False,
    }
    with pytest.raises(ConfidentMomentProjectionInvalid, match="value"):
        validate_family_response(
            result, bundle_id=result["bundle_id"],
            attachment_id=result["bundle_attachment_id"],
        )


@pytest.mark.parametrize(
    ("path", "extra_key"),
    [
        (("bundle_projection",), "internal"),
        (("bundle_projection", "bundles", 0), "coach_update"),
        (("bundle_projection", "bundles", 0, "feedback_language_items", 0), "model"),
        (("bundle_projection", "bundles", 0, "feedback_language_items", 0, "output"), "tone"),
        (("bundle_projection", "bundles", 0, "feedback_language_items", 0, "coach_update"), "reviewer"),
        (("confident_moment_summary",), "revision_id"),
        (("confident_moment_summary", "items", 0), "rank"),
    ],
)
def test_projection_schema_is_recursively_closed(path, extra_key):
    envelope = _projection_envelope()
    target = envelope
    for key in path:
        target = target[key]
    target[extra_key] = "must-not-pass"
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_projection_envelope(envelope)


def test_projection_rejects_cross_item_and_summary_state_leakage():
    envelope = _projection_envelope()
    items = envelope["bundle_projection"]["bundles"][0]["feedback_language_items"]
    items[1]["coach_update"]["revision_delivery_id"] = items[0]["coach_update"][
        "revision_delivery_id"
    ]
    with pytest.raises(ConfidentMomentProjectionInvalid, match="identity reused"):
        validate_projection_envelope(envelope)


def test_projection_rejects_old_item_alias_duplicate_exposure_and_family_swap():
    envelope = _projection_envelope()
    item = envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ][0]
    item["canonical_feedback_presentation_id"] = item.pop(
        "canonical_feedback_exposure_id"
    )
    with pytest.raises(ConfidentMomentProjectionInvalid, match="keys"):
        validate_projection_envelope(envelope)

    envelope = _projection_envelope()
    items = envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ]
    items[1]["canonical_feedback_exposure_id"] = items[0][
        "canonical_feedback_exposure_id"
    ]
    with pytest.raises(ConfidentMomentProjectionInvalid, match="exposure"):
        validate_projection_envelope(envelope)

    envelope = _projection_envelope()
    items = envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ]
    items[0]["feedback_family"], items[1]["feedback_family"] = (
        items[1]["feedback_family"],
        items[0]["feedback_family"],
    )
    with pytest.raises(ConfidentMomentProjectionInvalid, match="family"):
        validate_projection_envelope(envelope)


def test_projection_rejects_subject_attachment_exposure_sibling_swap():
    envelope = _projection_envelope()
    items = envelope["bundle_projection"]["bundles"][0][
        "feedback_language_items"
    ]
    items[0]["canonical_feedback_exposure_id"], items[1][
        "canonical_feedback_exposure_id"
    ] = (
        items[1]["canonical_feedback_exposure_id"],
        items[0]["canonical_feedback_exposure_id"],
    )
    with pytest.raises(ConfidentMomentProjectionInvalid, match="subject attachment"):
        validate_projection_envelope(envelope)

    envelope = _projection_envelope()
    envelope["confident_moment_summary"]["items"][0][
        "has_unread_coach_update"
    ] = False
    with pytest.raises(ConfidentMomentProjectionInvalid, match="unread"):
        validate_projection_envelope(envelope)


def test_projection_rejects_unknown_shape_without_mutating_input():
    envelope = _projection_envelope()
    original = copy.deepcopy(envelope)
    validate_projection_envelope(envelope)
    assert envelope == original
    envelope = _projection_envelope()
    envelope["bundle_projection"]["score"] = 0.9
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_projection_envelope(envelope)


def test_projection_allows_achieved_coverage_above_target():
    envelope = _projection_envelope()
    envelope["bundle_projection"]["coverage"] = {
        "target_slide_count": 1,
        "achieved_slide_count": 3,
        "target_met": True,
    }
    assert validate_projection_envelope(envelope) is envelope


def test_projection_requires_anchor_and_subject_evidence_to_match():
    envelope = _projection_envelope()
    envelope["bundle_projection"]["bundles"][0]["confidence_anchor"][
        "evidence_span_id"
    ] = "00000000-0000-0000-0000-000000000099"
    with pytest.raises(ConfidentMomentProjectionInvalid, match="evidence"):
        validate_projection_envelope(envelope)


def test_projection_requires_canonical_bundle_uuid_byte_order():
    envelope = _projection_envelope()
    second = {
        "bundle_id": "00000000-0000-0000-0000-000000000009",
        "bundle_subject_kind": "no_anchor_paragraph_trigger",
        "slide_index": 1,
        "block_key": 0,
        "paragraph_id": "00000000-0000-0000-0000-000000000010",
        "subject": {
            "candidate_id": "00000000-0000-0000-0000-000000000009",
            "evidence_span_id": "00000000-0000-0000-0000-000000000011",
            "canonical_feedback_presentation_id": (
                "00000000-0000-0000-0000-000000000012"
            ),
        },
        "confidence_anchor": None,
        "feedback_language_items": [{
            "bundle_attachment_id": (
                "00000000-0000-0000-0000-000000000015"
            ),
            "attached_candidate_id": (
                "00000000-0000-0000-0000-000000000009"
            ),
            "feedback_family": "rewrite_clarity",
            "canonical_feedback_exposure_id": (
                "00000000-0000-0000-0000-000000000012"
            ),
            "canonical_position": 1,
            "source_passage": {
                "evidence_span_id": (
                    "00000000-0000-0000-0000-000000000011"
                ),
                "text": "Exact passage.",
                "text_sha256": hashlib.sha256(b"Exact passage.").hexdigest(),
            },
            "update_text_available": False,
            "coach_authoring_exclusion_reason": None,
            "resolution_state": "excluded",
            "exclusion_reason": "machine_output_invalid",
            "output": None,
            "coach_update": None,
            "owner_decision": None,
        }],
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
    }
    summary = {
        "bundle_id": second["bundle_id"],
        "paragraph_id": second["paragraph_id"],
        "slide_index": 1,
        "block_key": 0,
        "marker_present": True,
        "is_orange": False,
        "is_locked": False,
        "has_coach_update": False,
        "has_unread_coach_update": False,
        "state_revision": 1,
    }
    envelope["bundle_projection"]["bundles"].append(second)
    envelope["confident_moment_summary"]["items"].append(summary)
    assert validate_projection_envelope(envelope) is envelope
    envelope["bundle_projection"]["bundles"].reverse()
    envelope["confident_moment_summary"]["items"].reverse()
    with pytest.raises(ConfidentMomentProjectionInvalid, match="order"):
        validate_projection_envelope(envelope)


def test_repository_exact_d11_rpc_registry_and_execute_boundary():
    source = Path("services/confident_moment_bundle_repository.py").read_text()
    tree = ast.parse(source)
    expected = {
        "project_take_bundles": "project_confident_moment_bundles_v1",
        "prepare_bundle": "prepare_confident_moment_bundle_v1",
        "ack_item_render": "ack_confident_moment_bundle_item_render_v3",
        "ack_revision_render": "ack_feedback_language_revision_render_v3",
        "freeze_coverage_frame": "freeze_root_phrase_coverage_frame_v1",
        "record_family_response": "record_confident_moment_bundle_family_response_v1",
        "record_root_action": "record_confident_moment_bundle_root_action_v1",
        "update_text": "apply_confident_moment_bundle_text_update_v1",
        "project_coach_authoring_context": "project_confident_moment_coach_authoring_context_v2",
        "publish_coach_feedback_language": "publish_confident_moment_coach_feedback_language_v1",
    }
    actual: dict[str, str] = {}
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "rpc":
                continue
            assert isinstance(call.args[0], ast.Constant)
            actual[function.name] = call.args[0].value
            parent = next(
                node for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
                and call in ast.walk(node.func.value)
            )
            assert parent is not None
    assert actual == expected
    assert ".table(" not in source


# ── Subject kind derivation ─────────────────────────────────────────────────


# ── Nearest same-slide attachment ───────────────────────────────────────────


# ── Feedback Language ───────────────────────────────────────────────────────


def test_build_comment_and_rephrase():
    c = build_comment("positive_praise", "Great clarity on the close.")
    assert c.output_kind == "comment"
    assert c.canonical_family == "great_formulation"
    assert c.comment_purpose == "positive_praise"

    r = build_rephrase("We will deliver the report by Friday.")
    assert r.output_kind == "rephrase"
    assert r.comment_purpose is None
    assert r.canonical_family == "rewrite_clarity"


def test_validate_output_kind_and_purpose():
    validate_output_kind_and_purpose("comment", "actionable_observation")
    validate_output_kind_and_purpose("rephrase", None)
    with pytest.raises(ValueError):
        validate_output_kind_and_purpose("rephrase", "positive_praise")
    with pytest.raises(ValueError):
        validate_output_kind_and_purpose("comment", None)


# ── Clause extraction ───────────────────────────────────────────────────────


def test_extract_prefers_5_to_20_word_clauses():
    text = (
        "Welcome everyone. "
        "Today we will review the quarterly results and the outlook for next year. "
        "Questions later."
    )
    clauses = extract_exact_clauses(text)
    assert clauses
    assert any(5 <= c.normalized_word_count <= 20 for c in clauses)


def test_extract_falls_back_to_shortest_when_no_preferred():
    text = "Yes."
    clauses = extract_exact_clauses(text)
    assert len(clauses) == 1
    assert clauses[0].normalized_word_count >= 1


def test_extract_empty_transcript():
    assert extract_exact_clauses("") == []
    assert extract_exact_clauses("   ") == []


def test_extract_clause_preserves_exact_utf8_substring_and_hash():
    transcript = "  Héllo,\n  this   is a precise clause!  Next."
    clauses = extract_exact_clauses(transcript)
    assert len(clauses) == 1
    expected = "Héllo,\n  this   is a precise clause!"
    assert clauses[0].text == expected
    assert clauses[0].span_sha256 == hashlib.sha256(
        expected.encode("utf-8")
    ).hexdigest()


# ── Coverage targets ────────────────────────────────────────────────────────


def test_coverage_targets_30_80_100():
    t1 = coverage_target_for_take(1, 10)
    assert t1.target_count == 3
    t2 = coverage_target_for_take(2, 10)
    assert t2.target_count == 8
    t3 = coverage_target_for_take(3, 10)
    assert t3.target_count == 10
    t4 = coverage_target_for_take(4, 10)
    assert t4.target_count == 10


def test_coverage_target_mandatory_at_least_one():
    t1 = coverage_target_for_take(1, 1)
    assert t1.target_count == 1
    t1b = coverage_target_for_take(1, 2)
    assert t1b.target_count == 1


def test_one_root_per_block():
    existing = [(0, 0), (0, 1), (1, 0)]
    assert one_root_per_block_ok(existing, 0, 2) is True
    assert one_root_per_block_ok(existing, 0, 0) is False


# ── Lexicographic routing ───────────────────────────────────────────────────


def _anchor(
    slide: int,
    block: int,
    cid: str,
    *,
    aligned: bool = True,
    yes: bool = True,
    has_root: bool = False,
    locked: bool = False,
    order: int = 0,
) -> AnchorCandidate:
    candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, cid))
    return AnchorCandidate(
        slide_index=slide,
        block_key=block,
        candidate_id=candidate_id,
        membership_item_order=order,
        has_aligned_semantics=aligned,
        owner_response_confident_yes=yes,
        has_playable_audio=True,
        has_exact_transcript=True,
        already_has_root=has_root,
        is_owner_locked=locked,
    )


def test_lexicographic_orders_slide1_and_uncovered_first():
    anchors = [
        _anchor(2, 0, "c-late", has_root=False),
        _anchor(0, 0, "c-slide1", has_root=False),
        _anchor(1, 0, "c-covered", has_root=True),
        _anchor(1, 1, "c-uncovered", has_root=False),
    ]
    ordered = lexicographic_coverage_order(anchors)
    ids = [a.candidate_id for a in ordered]
    expected = {
        label: str(uuid.uuid5(uuid.NAMESPACE_URL, label))
        for label in ("c-slide1", "c-uncovered", "c-covered")
    }
    assert ids[0] == expected["c-slide1"]
    assert expected["c-uncovered"] in ids
    assert ids.index(expected["c-uncovered"]) < ids.index(expected["c-covered"])


def test_lexicographic_excludes_misaligned_and_non_yes():
    anchors = [
        _anchor(0, 0, "good"),
        _anchor(0, 1, "misaligned", aligned=False),
        _anchor(0, 2, "not-yes", yes=False),
        _anchor(0, 3, "locked", locked=True),
    ]
    ordered = lexicographic_coverage_order(anchors)
    ids = [a.candidate_id for a in ordered]
    assert ids == [str(uuid.uuid5(uuid.NAMESPACE_URL, "good"))]


def test_lexicographic_final_tie_uses_uuid_bytes():
    high = _anchor(1, 1, "high", order=1)
    low = _anchor(1, 1, "low", order=1)
    high = AnchorCandidate(**{**high.__dict__, "candidate_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"})
    low = AnchorCandidate(**{**low.__dict__, "candidate_id": "00000000-0000-0000-0000-000000000001"})
    assert [row.candidate_id for row in lexicographic_coverage_order([high, low])] == [
        low.candidate_id, high.candidate_id
    ]


# ── Repository: disabled gate ───────────────────────────────────────────────


def test_repository_prepare_fails_closed_when_disabled():
    client = MagicMock()
    repo = ConfidentMomentBundleRepository(client_provider=lambda: client)
    with pytest.raises(ConfidentMomentBundleDisabled):
        repo.prepare_bundle(
            acquisition_principal_id="p1",
            project_id="proj",
            take_id="take",
            feedback_membership_id="mem",
            bundle_subject_candidate_id="cand",
            idempotency_key="k1",
        )
    client.rpc.assert_not_called()


def test_repository_ack_fails_closed_when_disabled():
    client = MagicMock()
    repo = ConfidentMomentBundleRepository(client_provider=lambda: client)
    with pytest.raises(ConfidentMomentBundleDisabled):
        repo.ack_item_render(
            acquisition_principal_id="p1",
            bundle_id="bundle",
            bundle_attachment_id="att",
            feedback_exposure_id="exposure",
            render_instance_id="ri",
            idempotency_key="k1",
        )
    client.rpc.assert_not_called()


def test_repository_coverage_fails_closed_when_disabled():
    client = MagicMock()
    repo = ConfidentMomentBundleRepository(client_provider=lambda: client)
    with pytest.raises(ConfidentMomentBundleDisabled):
        repo.freeze_coverage_frame(
            acquisition_principal_id="p1",
            project_id="proj",
            take_id="take",
            feedback_membership_id="mem",
            document_snapshot_id="snap",
            policy_version="rooting-coverage-30-80-100-v1",
            idempotency_key="k1",
        )
    client.rpc.assert_not_called()


def test_repository_rejects_list_and_multirow_rpc_shapes():
    class DictDouble(dict):
        pass

    for value in (
        [],
        [{"id": "one"}],
        [{"id": "one"}, {"id": "two"}],
        None,
        "object",
        1,
        (),
        MagicMock(),
        DictDouble(id="one"),
    ):
        with pytest.raises(TypeError, match="scalar JSON object"):
            ConfidentMomentBundleRepository._rpc_payload(value)


# ── Repository: enabled-path with mocked RPC ────────────────────────────────


def test_repository_prepare_calls_exact_rpc_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "services.confident_moment_bundle_repository.runtime_is_enabled",
        lambda: True,
    )
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(
        data={
            "bundle_id": "cand-1",
            "bundle_subject_kind": "confidence_anchor",
            "attachments": [],
            "serves_user": False,
            "dataset_eligible": False,
        }
    )
    repo = ConfidentMomentBundleRepository(client_provider=lambda: client)
    out = repo.prepare_bundle(
        acquisition_principal_id="p1",
        project_id="proj",
        take_id="take",
        feedback_membership_id="mem",
        bundle_subject_candidate_id="cand-1",
        idempotency_key="k1",
    )
    client.rpc.assert_called_once()
    name, params = client.rpc.call_args[0]
    assert name == "prepare_confident_moment_bundle_v1"
    assert params["p_bundle_subject_candidate_id"] == "cand-1"
    assert out["dataset_eligible"] is False
    assert out["serves_user"] is False


def test_repository_ack_calls_exact_rpc_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "services.confident_moment_bundle_repository.runtime_is_enabled",
        lambda: True,
    )
    client = MagicMock()
    bundle_id = "00000000-0000-0000-0000-000000000001"
    attachment_id = "00000000-0000-0000-0000-000000000002"
    feedback_exposure_id = "00000000-0000-0000-0000-000000000003"
    render_instance_id = "00000000-0000-0000-0000-000000000004"
    client.rpc.return_value.execute.return_value = MagicMock(
        data={
            "render_contract_version": "confident-moment-bundle-item-render-v3",
            "bundle_id": bundle_id,
            "bundle_attachment_id": attachment_id,
            "feedback_exposure_id": feedback_exposure_id,
            "render_instance_id": render_instance_id,
            "render_receipt_id": "00000000-0000-0000-0000-000000000005",
            "dataset_eligible": False,
        }
    )
    repo = ConfidentMomentBundleRepository(client_provider=lambda: client)
    out = repo.ack_item_render(
        acquisition_principal_id="p1",
        bundle_id=bundle_id,
        bundle_attachment_id=attachment_id,
        feedback_exposure_id=feedback_exposure_id,
        render_instance_id=render_instance_id,
        idempotency_key="k1",
    )
    name, params = client.rpc.call_args[0]
    assert name == "ack_confident_moment_bundle_item_render_v3"
    assert params["p_bundle_id"] == bundle_id
    assert params["p_feedback_exposure_id"] == feedback_exposure_id
    assert out["dataset_eligible"] is False
    # denylist: no score/rank/qualification keys
    assert "score" not in out
    assert "qualification_state" not in out


def test_repository_coach_ack_calls_exact_d13_rpc_and_returns_same_object(monkeypatch):
    monkeypatch.setattr(
        "services.confident_moment_bundle_repository.runtime_is_enabled",
        lambda: True,
    )
    ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 8)]
    receipt = {
        "render_contract_version": "feedback-language-revision-render-v3",
        "bundle_id": ids[0],
        "bundle_attachment_id": ids[1],
        "current_revision_id": ids[2],
        "revision_delivery_id": ids[3],
        "presentation_id": ids[4],
        "render_instance_id": ids[5],
        "rendered_exposure_id": ids[6],
        "dataset_eligible": False,
    }
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=receipt)
    repo = ConfidentMomentBundleRepository(client_provider=lambda: client)
    result = repo.ack_revision_render(
        recipient_principal_id="principal",
        bundle_id=ids[0],
        bundle_attachment_id=ids[1],
        revision_id=ids[2],
        revision_delivery_id=ids[3],
        presentation_id=ids[4],
        render_instance_id=ids[5],
        idempotency_key="coach-render-1",
    )
    name, params = client.rpc.call_args[0]
    assert name == "ack_feedback_language_revision_render_v3"
    assert params["p_bundle_id"] == ids[0]
    assert result is receipt


def test_d13_receipts_reject_extra_wrong_echo_and_duplicate_identities():
    ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 8)]
    item = {
        "render_contract_version": "confident-moment-bundle-item-render-v3",
        "bundle_id": ids[0],
        "bundle_attachment_id": ids[1],
        "feedback_exposure_id": ids[2],
        "render_instance_id": ids[3],
        "render_receipt_id": ids[4],
        "dataset_eligible": False,
    }
    kwargs = {
        "bundle_id": ids[0],
        "bundle_attachment_id": ids[1],
        "feedback_exposure_id": ids[2],
        "render_instance_id": ids[3],
    }
    assert validate_bundle_item_render_receipt(item, **kwargs) is item
    alias_item = {**item, "render_instance_id": item["bundle_id"]}
    assert validate_bundle_item_render_receipt(
        alias_item, **{**kwargs, "render_instance_id": item["bundle_id"]}
    ) is alias_item
    for mutation in (
        {**item, "extra": "no"},
        {**item, "bundle_id": ids[6]},
        {**item, "render_receipt_id": ids[2]},
        {**item, "dataset_eligible": True},
    ):
        with pytest.raises(ConfidentMomentProjectionInvalid):
            validate_bundle_item_render_receipt(mutation, **kwargs)

    coach = {
        "render_contract_version": "feedback-language-revision-render-v3",
        "bundle_id": ids[0],
        "bundle_attachment_id": ids[1],
        "current_revision_id": ids[2],
        "revision_delivery_id": ids[3],
        "presentation_id": ids[4],
        "render_instance_id": ids[5],
        "rendered_exposure_id": ids[6],
        "dataset_eligible": False,
    }
    coach_kwargs = {
        "bundle_id": ids[0],
        "bundle_attachment_id": ids[1],
        "revision_id": ids[2],
        "revision_delivery_id": ids[3],
        "presentation_id": ids[4],
        "render_instance_id": ids[5],
    }
    assert validate_coach_update_render_receipt(coach, **coach_kwargs) is coach
    alias_coach = {**coach, "render_instance_id": coach["bundle_id"]}
    assert validate_coach_update_render_receipt(
        alias_coach,
        **{**coach_kwargs, "render_instance_id": coach["bundle_id"]},
    ) is alias_coach
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_coach_update_render_receipt(
            {**coach, "rendered_exposure_id": coach["presentation_id"]},
            **coach_kwargs,
        )
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_coach_update_render_receipt(
            {**coach, "current_revision_id": ids[6]}, **coach_kwargs
        )


def test_core_summary_version_constant():
    assert BUNDLE_CORE_SUMMARY_VERSION == "confident-moment-core-summary-v1"
