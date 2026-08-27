from datetime import datetime, timezone

import pytest

from services.dataset_releases import (
    DatasetReleaseError,
    build_dataset_release_manifest,
    manifest_json,
    speaker_split,
)


OWNER_A = "10000000-0000-0000-0000-000000000001"
OWNER_B = "10000000-0000-0000-0000-000000000002"


def _item(owner, evidence, surface="confidence_classification"):
    return {
        "owner_principal_id": owner,
        "evidence_span_id": evidence,
        "learning_surface": surface,
        "item_payload": {"audio_features": {"pace": 1.1}},
        "label_provenance": {
            "machine": {"prediction_id": "m1", "value": "yes"},
            "user_self_report": {"judgment_id": "u1", "value": "no"},
            "blind_coach": {"judgment_id": "c1", "value": "yes"},
        },
        "eligibility_decision": "eligible",
    }


def _manifest(items):
    return build_dataset_release_manifest(
        release_identifier="confidence-2026-08-26-r1",
        learning_surface="confidence_classification",
        source_cutoff_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        items=items,
        exclusions=[],
        inclusion_rules={"consent": "active"},
        exclusion_rules={"audio_unclear": True},
        taxonomy_versions={"confidence": "v1"},
        feature_versions={"acoustic": "v1"},
        extraction_code_commit="abc123",
        consent_retention_status={"policy": "v1"},
        created_by="90000000-0000-0000-0000-000000000001",
    )


def test_same_speaker_is_stable_across_projects_items_and_releases():
    assert speaker_split(OWNER_A) == speaker_split(OWNER_A)
    manifest = _manifest([
        _item(OWNER_A, "20000000-0000-0000-0000-000000000001"),
        _item(OWNER_A, "20000000-0000-0000-0000-000000000002"),
        _item(OWNER_B, "20000000-0000-0000-0000-000000000003"),
    ])
    owner_a_splits = {
        row["split"] for row in manifest["items"]
        if row["owner_principal_id"] == OWNER_A
    }
    assert len(owner_a_splits) == 1
    assert len({row["owner_principal_id"]
                for row in manifest["split_assignments"]}) == 2


def test_release_checksum_and_json_are_reproducible():
    items = [
        _item(OWNER_A, "20000000-0000-0000-0000-000000000001"),
        _item(OWNER_B, "20000000-0000-0000-0000-000000000002"),
    ]
    first = _manifest(items)
    second = _manifest(reversed(items))
    assert first == second
    assert manifest_json(first) == manifest_json(second)


def test_release_refuses_mixed_surfaces_and_collapsed_labels():
    mixed = _item(
        OWNER_A, "20000000-0000-0000-0000-000000000001",
        surface="praise_selection",
    )
    with pytest.raises(DatasetReleaseError, match="one learning surface"):
        _manifest([mixed])
    collapsed = _item(
        OWNER_A, "20000000-0000-0000-0000-000000000001")
    collapsed["label_provenance"] = {"label": "yes"}
    with pytest.raises(DatasetReleaseError, match="provenance"):
        _manifest([collapsed])


def test_release_keeps_machine_user_and_coach_provenance_separate():
    manifest = _manifest([
        _item(OWNER_A, "20000000-0000-0000-0000-000000000001")])
    provenance = manifest["items"][0]["label_provenance"]
    assert set(provenance) == {
        "machine", "user_self_report", "blind_coach",
    }
    assert "gold_label" not in provenance


@pytest.mark.parametrize("surface", [
    "confidence_classification",
    "correction_generation",
    "coach_comment_generation",
    "praise_generation",
    "praise_selection",
    "correction_selection",
])
def test_every_span_level_surface_requires_exact_evidence(surface):
    item = _item(OWNER_A, "", surface=surface)
    with pytest.raises(DatasetReleaseError, match="owner and evidence"):
        build_dataset_release_manifest(
            release_identifier=f"{surface}-r1",
            learning_surface=surface,
            source_cutoff_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
            items=[item], exclusions=[], inclusion_rules={},
            exclusion_rules={}, taxonomy_versions={}, feature_versions={},
            extraction_code_commit="abc123",
            consent_retention_status={"policy": "v1"},
            created_by="90000000-0000-0000-0000-000000000001",
        )


def test_ideal_text_release_is_take_anchored_without_fake_span_evidence():
    item = _item(OWNER_A, "", surface="ideal_text_generation")
    item["item_payload"] = {
        "take_id": "30000000-0000-0000-0000-000000000001",
        "document_hash": "a" * 64,
    }
    manifest = build_dataset_release_manifest(
        release_identifier="ideal-text-r1",
        learning_surface="ideal_text_generation",
        source_cutoff_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        items=[item], exclusions=[], inclusion_rules={}, exclusion_rules={},
        taxonomy_versions={}, feature_versions={},
        extraction_code_commit="abc123",
        consent_retention_status={"policy": "v1"},
        created_by="90000000-0000-0000-0000-000000000001",
    )
    assert manifest["items"][0]["evidence_span_id"] is None
