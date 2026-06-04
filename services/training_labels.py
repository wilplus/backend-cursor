"""willab beta — training-label validation (design §14, contract §3.9b).

The private classifier-training lane. The coach assigns each snippet a
direction appraisal (threat|ambiguous|challenge); at publish the labels
are captured here. The publish gate (§3.10/§14) requires EVERY snippet
labeled.

PRIVATE (split-sink §2 / AC-9): these never reach the user, never enter
insights_payload, and the strong/to-work-on tag is never derived from
them. This module only validates + normalises; persistence is db.upsert_
training_labels; the publish route enforces the "every snippet" gate.

Schema is direction-v1 (FE-locked); written versioned so the future
28→12-16 scenario protocol augments rather than replaces it.
"""
from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "direction-v1"
VALID_VALUES = ("threat", "ambiguous", "challenge")


class TrainingLabelError(ValueError):
    """Validation error with an FE-renderable message. The publish
    route catches and 422s with the message verbatim."""


def validate_publish_labels(
    labels: Any,
    required_snippet_ids: set,
) -> list[dict]:
    """Validate the publish body's labels against the session's snippets.

    Enforces the §14 publish gate: EVERY snippet in
    ``required_snippet_ids`` must have a valid label, with no labels for
    snippets outside the session.

    Each label entry: {snippet_id, value ∈ VALID_VALUES,
    was_pre_filled?, was_overridden?}. Returns cleaned rows ready for
    db.upsert_training_labels (schema_version stamped here).

    Raises TrainingLabelError on: not a list, bad entry, bad value,
    non-bool flags, a label for an unknown snippet, a duplicate, or any
    session snippet left unlabeled.
    """
    if not isinstance(labels, list):
        raise TrainingLabelError("labels: must be an array")

    cleaned: list[dict] = []
    seen: set = set()
    for i, entry in enumerate(labels):
        if not isinstance(entry, dict):
            raise TrainingLabelError(f"labels[{i}]: must be an object")

        sid = entry.get("snippet_id")
        if not isinstance(sid, str) or not sid.strip():
            raise TrainingLabelError(f"labels[{i}].snippet_id: required")
        sid = sid.strip()
        if sid in seen:
            raise TrainingLabelError(f"labels[{i}].snippet_id: duplicate ({sid})")
        if sid not in required_snippet_ids:
            raise TrainingLabelError(
                f"labels[{i}].snippet_id: not a snippet of this session ({sid})"
            )
        seen.add(sid)

        value = entry.get("value")
        if value not in VALID_VALUES:
            raise TrainingLabelError(
                f"labels[{i}].value: must be one of {', '.join(VALID_VALUES)}"
            )

        was_pre_filled = entry.get("was_pre_filled", False)
        was_overridden = entry.get("was_overridden", False)
        if not isinstance(was_pre_filled, bool):
            raise TrainingLabelError(f"labels[{i}].was_pre_filled: must be a boolean")
        if not isinstance(was_overridden, bool):
            raise TrainingLabelError(f"labels[{i}].was_overridden: must be a boolean")

        cleaned.append({
            "snippet_id": sid,
            "schema_version": SCHEMA_VERSION,
            "value": value,
            "was_pre_filled": was_pre_filled,
            "was_overridden": was_overridden,
        })

    # The §14 gate: every snippet must be labeled.
    missing = required_snippet_ids - seen
    if missing:
        raise TrainingLabelError(
            f"labels: every snippet must be labeled — {len(missing)} "
            f"unlabeled (e.g. {sorted(missing)[0]})"
        )

    return cleaned
