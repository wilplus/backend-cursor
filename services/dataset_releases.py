"""Immutable, speaker-disjoint dataset release manifests.

This module does not query live production tables. A caller must supply an
already-reviewed collection of canonical items and exclusions. The result is a
single-surface manifest suitable for the atomic `create_dataset_release_v1`
RPC and later manual approval.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Iterable

from services.feedback_data_contract import content_hash


SPLIT_STRATEGY_VERSION = "speaker-sha256-80-10-10-v1"
LEARNING_SURFACES = {
    "confidence_classification",
    "praise_generation",
    "praise_selection",
    "correction_generation",
    "correction_selection",
    "coach_comment_generation",
    "ideal_text_generation",
}
PROVENANCE_KEYS = {
    "machine", "user_self_report", "blind_coach", "blind_peer",
    "derived_product_state",
}
_NAMESPACE = uuid.UUID("b6b53f18-d7be-41db-a96c-eb8ba33c1ab7")


class DatasetReleaseError(ValueError):
    pass


def _stable_uuid(*parts: Any) -> str:
    return str(uuid.uuid5(
        _NAMESPACE, "\0".join(str(part) for part in parts),
    ))


def speaker_split(
    owner_principal_id: str,
    *, strategy_version: str = SPLIT_STRATEGY_VERSION,
) -> tuple[str, str]:
    """Return a stable owner-level split and its auditable assignment hash."""
    if not owner_principal_id:
        raise DatasetReleaseError("owner_principal_id is required")
    digest = hashlib.sha256(
        f"{strategy_version}\0{owner_principal_id}".encode("utf-8")
    ).hexdigest()
    bucket = int(digest[:8], 16) % 100
    split = "train" if bucket < 80 else "validation" if bucket < 90 else "test"
    return split, digest


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise DatasetReleaseError("source_cutoff_at must be ISO-8601") from error
    else:
        raise DatasetReleaseError("source_cutoff_at is required")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _validated_item(raw: Any, *, learning_surface: str) -> dict:
    if not isinstance(raw, dict):
        raise DatasetReleaseError("dataset item must be an object")
    owner_id = str(raw.get("owner_principal_id") or "")
    evidence_id = str(raw.get("evidence_span_id") or "")
    surface = str(raw.get("learning_surface") or "")
    provenance = raw.get("label_provenance")
    payload = raw.get("item_payload")
    eligibility = str(raw.get("eligibility_decision") or "")
    if not owner_id or (not evidence_id and surface != "ideal_text_generation"):
        raise DatasetReleaseError("dataset item needs owner and evidence IDs")
    if surface != learning_surface:
        raise DatasetReleaseError("one release may contain one learning surface")
    if not isinstance(payload, dict) or not isinstance(provenance, dict):
        raise DatasetReleaseError("dataset item payload/provenance must be objects")
    if surface == "ideal_text_generation" and not payload.get("take_id"):
        raise DatasetReleaseError("ideal text dataset item needs a Take ID")
    if not provenance or not set(provenance).issubset(PROVENANCE_KEYS):
        raise DatasetReleaseError("label provenance is missing or collapsed")
    if "label" in provenance or "feedback_quality" in payload:
        raise DatasetReleaseError("undifferentiated labels are prohibited")
    if eligibility not in ("eligible", "research_only"):
        raise DatasetReleaseError("eligibility decision must be explicit")
    split, assignment_hash = speaker_split(owner_id)
    checksum_payload = {
        "owner_principal_id": owner_id,
        "evidence_span_id": evidence_id or None,
        "learning_surface": surface,
        "item_payload": payload,
        "label_provenance": provenance,
        "eligibility_decision": eligibility,
    }
    item_checksum = content_hash(checksum_payload)
    return {
        "id": _stable_uuid("dataset-item", item_checksum),
        **checksum_payload,
        "split": split,
        "assignment_hash": assignment_hash,
        "item_checksum": item_checksum,
    }


def build_dataset_release_manifest(
    *, release_identifier: str, learning_surface: str,
    source_cutoff_at: Any, items: Iterable[Any], exclusions: Iterable[Any],
    inclusion_rules: dict, exclusion_rules: dict,
    taxonomy_versions: dict, feature_versions: dict,
    extraction_code_commit: str, consent_retention_status: dict,
    created_by: str,
) -> dict:
    """Freeze one manually reviewable, single-surface release manifest."""
    release_identifier = str(release_identifier or "").strip()
    if not release_identifier:
        raise DatasetReleaseError("release_identifier is required")
    if learning_surface not in LEARNING_SURFACES:
        raise DatasetReleaseError("unknown learning surface")
    if not extraction_code_commit or not created_by:
        raise DatasetReleaseError("code commit and creator are required")
    if not all(isinstance(value, dict) for value in (
            inclusion_rules, exclusion_rules, taxonomy_versions,
            feature_versions, consent_retention_status)):
        raise DatasetReleaseError("release policies and versions must be objects")

    frozen_items = sorted(
        (_validated_item(raw, learning_surface=learning_surface)
         for raw in items or []),
        key=lambda row: row["item_checksum"],
    )
    if not frozen_items:
        raise DatasetReleaseError("an empty dataset release is not valid")
    if len({row["item_checksum"] for row in frozen_items}) != len(frozen_items):
        raise DatasetReleaseError("duplicate dataset items are not allowed")

    owners: dict[str, dict] = {}
    for item in frozen_items:
        owner_id = item["owner_principal_id"]
        owners.setdefault(owner_id, {
            "id": _stable_uuid("split", owner_id, SPLIT_STRATEGY_VERSION),
            "owner_principal_id": owner_id,
            "split": item["split"],
            "strategy_version": SPLIT_STRATEGY_VERSION,
            "assignment_hash": item["assignment_hash"],
        })
        if owners[owner_id]["split"] != item["split"]:
            raise DatasetReleaseError("one speaker crossed dataset splits")

    frozen_exclusions: list[dict] = []
    for raw in exclusions or []:
        if not isinstance(raw, dict) or not raw.get("owner_principal_id") \
                or not raw.get("reason_code"):
            raise DatasetReleaseError("dataset exclusion is incomplete")
        owner_id = str(raw["owner_principal_id"])
        evidence_id = str(raw.get("evidence_span_id") or "") or None
        exclusion_material = {
            "owner_principal_id": owner_id,
            "evidence_span_id": evidence_id,
            "reason_code": str(raw["reason_code"]),
            "reason_detail": raw.get("reason_detail") or {},
            "consent_retention_status": (
                raw.get("consent_retention_status")
                or consent_retention_status
            ),
        }
        frozen_exclusions.append({
            "id": _stable_uuid("dataset-exclusion", content_hash(
                exclusion_material)),
            **exclusion_material,
        })
    frozen_exclusions.sort(key=lambda row: row["id"])

    split_counts = Counter(row["split"] for row in frozen_items)
    eligibility_counts = Counter(
        row["eligibility_decision"] for row in frozen_items
    )
    item_counts = {
        "total": len(frozen_items),
        "by_split": dict(sorted(split_counts.items())),
        "by_eligibility": dict(sorted(eligibility_counts.items())),
        "excluded": len(frozen_exclusions),
    }
    manifest_material = {
        "release_identifier": release_identifier,
        "learning_surface": learning_surface,
        "source_cutoff_at": _iso(source_cutoff_at),
        "inclusion_rules": inclusion_rules,
        "exclusion_rules": exclusion_rules,
        "taxonomy_versions": taxonomy_versions,
        "feature_versions": feature_versions,
        "extraction_code_commit": extraction_code_commit,
        "item_counts": item_counts,
        "consent_retention_status": consent_retention_status,
        "split_strategy_version": SPLIT_STRATEGY_VERSION,
        "split_assignments": sorted(owners.values(), key=lambda row: row["id"]),
        "items": frozen_items,
        "exclusions": frozen_exclusions,
        "created_by": str(created_by),
    }
    checksum = content_hash(manifest_material)
    return {
        "id": _stable_uuid("dataset-release", release_identifier, checksum),
        **manifest_material,
        "manifest_checksum": checksum,
    }


def manifest_json(manifest: dict) -> str:
    """Stable bytes for manual inspection and external checksum verification."""
    return json.dumps(
        manifest, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
