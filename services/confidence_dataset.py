"""Leakage-safe dataset partitions for the Confident Voice model.

The unit of independence is the SPEAKER, never the clip, take, session, or
project.  Every recording from one speaker belongs to exactly one of train,
validation, or test.  This prevents a model from looking accurate merely
because it heard the same voice during training.

The split is represented by a small, versioned manifest.  Creating a manifest
is an explicit dataset-release operation; applying it is pure and strict.
After release, :func:`extend_manifest` may admit new speakers to train or
validation, but never to the frozen test set.  Refreshing test data therefore
requires a new manifest/version rather than silently changing the benchmark.

Speaker identity is allowed to come from an immutable speaker/owner id.  The
training-import lane currently records a human-entered ``speaker_label``;
equal normalized labels are conservatively treated as the same speaker.  That
can merge two people with the same label (losing some usable data), but it
cannot leak one known speaker across partitions.  Rows with no stable identity
are rejected rather than guessed from session, project, filename, or audio.

Internal only.  No split, score, balance, or model information is user-facing.
Pure: no DB, filesystem, or network access.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional


PARTITIONS = ("train", "validation", "test")
POLICY_VERSION = "speaker-disjoint-v1"
SCHEMA_VERSION = 1
DEFAULT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}


class DatasetSplitError(ValueError):
    """The requested split would make its leakage guarantees unverifiable."""


def _clean_identity(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalized_label(value: Any) -> Optional[str]:
    cleaned = _clean_identity(value)
    if not cleaned:
        return None
    return re.sub(r"\s+", " ", cleaned).casefold()


def _nested(row: dict, container: str, field: str) -> Any:
    value = row.get(container)
    return value.get(field) if isinstance(value, dict) else None


def speaker_key(row: Any) -> Optional[str]:
    """Return one conservative grouping key, or ``None`` when unknowable.

    Explicit immutable ids win.  Authenticated and canonical guest owners are
    both owners; account claim is responsible for atomically replacing the
    guest owner id in historical entities.  A training-import label is the
    last acceptable fallback.  Session/project ids are deliberately absent:
    using either would put two recordings of the same voice in different
    partitions.
    """
    if not isinstance(row, dict):
        return None

    for field in ("speaker_key", "speaker_id"):
        value = _clean_identity(row.get(field))
        if value:
            return f"speaker:{value}"
    for container in ("source_metadata", "intake_context"):
        value = _clean_identity(_nested(row, container, "speaker_id"))
        if value:
            return f"speaker:{value}"

    for field in ("owner_id", "user_id", "guest_owner_id", "guest_id"):
        value = _clean_identity(row.get(field))
        if value:
            return f"owner:{value}"

    label = _normalized_label(row.get("speaker_label"))
    if not label:
        for container in ("source_metadata", "intake_context"):
            label = _normalized_label(_nested(row, container, "speaker_label"))
            if label:
                break
    return f"import-label:{label}" if label else None


def _unit_interval(seed: str, key: str) -> float:
    digest = hashlib.sha256(f"{seed}:{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _validated_ratios(ratios: Any, *, allow_test: bool = True) -> dict[str, float]:
    source = ratios if isinstance(ratios, dict) else DEFAULT_RATIOS
    out: dict[str, float] = {}
    for partition in PARTITIONS:
        raw = source.get(partition, 0.0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise DatasetSplitError(f"{partition} ratio must be numeric")
        value = float(raw)
        if value < 0:
            raise DatasetSplitError(f"{partition} ratio must not be negative")
        out[partition] = value
    if not allow_test and out["test"]:
        raise DatasetSplitError("a frozen manifest cannot admit new test speakers")
    total = sum(out.values())
    if total <= 0:
        raise DatasetSplitError("at least one partition ratio must be positive")
    return {key: value / total for key, value in out.items()}


def _partition_for(key: str, *, seed: str, ratios: dict[str, float]) -> str:
    position = _unit_interval(seed, key)
    train_edge = ratios["train"]
    validation_edge = train_edge + ratios["validation"]
    if position < train_edge:
        return "train"
    if position < validation_edge:
        return "validation"
    return "test"


def _speaker_keys(rows: Any) -> list[str]:
    keys: set[str] = set()
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        key = speaker_key(row)
        if not key:
            raise DatasetSplitError(
                f"row {index} has no stable speaker identity; exclude or label it"
            )
        keys.add(key)
    return sorted(keys)


def create_manifest(rows: Any, *, seed: str,
                    ratios: Any = None, release_id: str) -> dict:
    """Create one explicit dataset-release manifest.

    ``release_id`` is required so a frozen test set has a human-visible
    version.  The same rows, seed, and ratios always produce the same result.
    """
    release = _clean_identity(release_id)
    if not release:
        raise DatasetSplitError("release_id is required")
    split = _validated_ratios(ratios)
    assignments = {
        key: _partition_for(key, seed=str(seed), ratios=split)
        for key in _speaker_keys(rows)
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "release_id": release,
        "seed": str(seed),
        "ratios": split,
        "assignments": assignments,
        "frozen_test_speakers": sorted(
            key for key, partition in assignments.items()
            if partition == "test"
        ),
    }


def _validated_manifest(manifest: Any) -> dict:
    if not isinstance(manifest, dict):
        raise DatasetSplitError("manifest must be an object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise DatasetSplitError("unsupported manifest schema_version")
    if manifest.get("policy_version") != POLICY_VERSION:
        raise DatasetSplitError("unsupported manifest policy_version")
    assignments = manifest.get("assignments")
    if not isinstance(assignments, dict):
        raise DatasetSplitError("manifest assignments must be an object")
    for key, partition in assignments.items():
        if not _clean_identity(key) or partition not in PARTITIONS:
            raise DatasetSplitError("manifest contains an invalid assignment")
    frozen = manifest.get("frozen_test_speakers")
    if not isinstance(frozen, list):
        raise DatasetSplitError("manifest frozen_test_speakers must be a list")
    expected = sorted(
        key for key, partition in assignments.items() if partition == "test"
    )
    if sorted(frozen) != expected:
        raise DatasetSplitError("manifest test assignments do not match its freeze")
    return manifest


def extend_manifest(manifest: Any, rows: Any) -> dict:
    """Add new speakers without changing any assignment or frozen test data.

    New speakers are deterministically split between train and validation.
    A benchmark refresh is a new :func:`create_manifest` call with a new
    ``release_id``; it is never smuggled into an extension.
    """
    current = _validated_manifest(manifest)
    assignments = dict(current["assignments"])
    existing_test = tuple(current["frozen_test_speakers"])
    ratios = _validated_ratios({
        "train": current.get("ratios", {}).get("train", 0.70),
        "validation": current.get("ratios", {}).get("validation", 0.15),
        "test": 0.0,
    }, allow_test=False)
    for key in _speaker_keys(rows):
        if key not in assignments:
            assignments[key] = _partition_for(
                key, seed=str(current.get("seed") or ""), ratios=ratios,
            )
    out = dict(current)
    out["assignments"] = assignments
    out["frozen_test_speakers"] = list(existing_test)
    return out


def partition_rows(rows: Any, manifest: Any) -> dict[str, list[dict]]:
    """Apply a manifest strictly and assert clip/speaker disjointness."""
    current = _validated_manifest(manifest)
    assignments = current["assignments"]
    out: dict[str, list[dict]] = {partition: [] for partition in PARTITIONS}
    seen_snippets: set[str] = set()
    speaker_partitions: dict[str, str] = {}
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            raise DatasetSplitError(f"row {index} must be an object")
        key = speaker_key(row)
        if not key:
            raise DatasetSplitError(f"row {index} has no stable speaker identity")
        partition = assignments.get(key)
        if partition not in PARTITIONS:
            raise DatasetSplitError(
                f"speaker {key!r} is absent from release {current.get('release_id')!r}"
            )
        previous = speaker_partitions.setdefault(key, partition)
        if previous != partition:
            raise DatasetSplitError(f"speaker {key!r} crosses partitions")
        snippet_id = _clean_identity(row.get("snippet_id") or row.get("id"))
        if not snippet_id:
            raise DatasetSplitError(f"row {index} has no snippet_id")
        if snippet_id in seen_snippets:
            raise DatasetSplitError(f"duplicate snippet {snippet_id!r}")
        seen_snippets.add(snippet_id)
        out[partition].append(dict(row))
    return out


def split_audit(partitions: Any) -> dict:
    """Internal balance report; observation only, never an auto-reshuffler."""
    source = partitions if isinstance(partitions, dict) else {}
    dimensions = ("language", "device", "source", "sex", "acoustic_region")
    out: dict[str, Any] = {"partitions": {}, "speaker_overlap": []}
    speaker_sets: dict[str, set[str]] = {}
    for partition in PARTITIONS:
        rows = source.get(partition)
        rows = rows if isinstance(rows, list) else []
        speakers: set[str] = set()
        for row in rows:
            key = speaker_key(row)
            if key:
                speakers.add(key)
        speaker_sets[partition] = speakers
        by_dimension: dict[str, dict[str, int]] = {}
        for dimension in dimensions:
            counts: dict[str, int] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = row.get(dimension)
                if value is None and dimension == "acoustic_region":
                    value = _nested(row, "voice_confidence", "band")
                    if value is None:
                        metrics = row.get("metrics")
                        read = metrics.get("voice_confidence") if isinstance(metrics, dict) else None
                        value = read.get("band") if isinstance(read, dict) else None
                label = str(value or "unknown")
                counts[label] = counts.get(label, 0) + 1
            by_dimension[dimension] = counts
        out["partitions"][partition] = {
            "rows": len(rows),
            "speakers": len(speakers),
            "by_dimension": by_dimension,
        }
    for index, left in enumerate(PARTITIONS):
        for right in PARTITIONS[index + 1:]:
            for key in sorted(speaker_sets[left] & speaker_sets[right]):
                out["speaker_overlap"].append({
                    "speaker_key": key, "partitions": [left, right],
                })
    out["leakage_free"] = not out["speaker_overlap"]
    return out
