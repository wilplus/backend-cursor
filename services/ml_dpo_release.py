"""Immutable release and evaluation-report helpers for the DPO loop."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.ml_surface_contracts import contract_for_surface


MANIFEST_SCHEMA_VERSION = 1
EVALUATION_SCHEMA_VERSION = 1


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_hash(payload: dict[str, Any], hash_key: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(hash_key, None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def write_release_manifest(
    path: Path,
    *,
    surface: str,
    train_path: Path,
    val_path: Path | None,
    train_examples: int,
    val_examples: int,
    train_groups: int,
    val_groups: int,
) -> dict[str, Any]:
    contract = contract_for_surface(surface)
    train_hash = file_sha256(train_path)
    val_hash = file_sha256(val_path) if val_path else None
    release_material = {
        "surface": contract.id,
        "split_policy": "user-and-project-disjoint-v1",
        "train_sha256": train_hash,
        "val_sha256": val_hash,
    }
    release_hash = hashlib.sha256(_canonical_json(release_material)).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_release_id": f"dpo-{contract.id}-{release_hash[:16]}",
        "surface": contract.id,
        "annotation_fields": list(contract.annotation_fields),
        "split_policy": "user-and-project-disjoint-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "train": {
                "name": train_path.name,
                "sha256": train_hash,
                "examples": int(train_examples),
            },
            "validation": None if not val_path else {
                "name": val_path.name,
                "sha256": val_hash,
                "examples": int(val_examples),
            },
        },
        "groups": {"train": int(train_groups), "validation": int(val_groups)},
    }
    payload["manifest_sha256"] = _payload_hash(payload, "manifest_sha256")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return payload


def load_release_manifest(path: Path, *, expected_surface: str | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported DPO manifest schema_version")
    expected_hash = _payload_hash(payload, "manifest_sha256")
    if payload.get("manifest_sha256") != expected_hash:
        raise ValueError("DPO manifest hash mismatch")
    contract = contract_for_surface(str(payload.get("surface") or ""))
    if expected_surface and contract.id != contract_for_surface(expected_surface).id:
        raise ValueError("DPO manifest surface does not match requested surface")
    if payload.get("split_policy") != "user-and-project-disjoint-v1":
        raise ValueError("DPO manifest does not use the canonical disjoint split")
    return payload


def verify_release_file(manifest: dict[str, Any], role: str, path: Path) -> None:
    record = (manifest.get("files") or {}).get(role)
    if not isinstance(record, dict):
        raise ValueError(f"DPO manifest has no {role!r} file")
    if file_sha256(path) != record.get("sha256"):
        raise ValueError(f"{role} JSONL hash does not match immutable release")


def write_evaluation_report(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    report["schema_version"] = EVALUATION_SCHEMA_VERSION
    report["evaluation_sha256"] = _payload_hash(report, "evaluation_sha256")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return report


def load_evaluation_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        raise ValueError("Unsupported DPO evaluation schema_version")
    if report.get("evaluation_sha256") != _payload_hash(report, "evaluation_sha256"):
        raise ValueError("DPO evaluation report hash mismatch")
    contract_for_surface(str(report.get("surface") or ""))
    if report.get("passed") is not True:
        raise ValueError("Candidate did not pass its surface evaluation")
    return report
