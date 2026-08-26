"""Post-label machine × coach comparison for the founder-only audit.

This is deliberately not a labeling payload and not a quorum calculation.
The machine proposal is not a vote.  Rows are emitted only after the
authenticated founder has committed their own blind label, so a direct call
cannot reveal a proposal for an unanswered piece.
"""
from __future__ import annotations

from typing import Any


FOUNDER_COMPARISON_EMAIL = "artur@willonski.com"
_LABEL_VALUES = (
    "yes", "in_between", "no", "not_sure", "audio_unclear", "neutral",
)
_PERCEPTUAL_VALUES = ("yes", "in_between", "no")
_MACHINE_VALUES = ("yes", "in_between", "no", "neutral")


def is_founder_comparison_email(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.strip().lower() == FOUNDER_COMPARISON_EMAIL
    )


def _latest_own_label(rows: Any, rater_id: Any) -> dict | None:
    own = [
        row for row in (rows or [])
        if isinstance(row, dict)
        and str(row.get("rater_id") or "") == str(rater_id or "")
        and (
            row.get("value") in _LABEL_VALUES
            or row.get("unrateable") is True
        )
    ]
    own.sort(key=lambda row: (
        row.get("updated_at") or row.get("created_at") or ""
    ))
    return own[-1] if own else None


def build_founder_comparison(
    snippets: Any,
    labels_by_snippet: Any,
    *,
    rater_id: Any,
) -> dict:
    """Build a qualitative, post-label comparison from immutable stamps."""
    labels = labels_by_snippet if isinstance(labels_by_snippet, dict) else {}
    rows: list[dict] = []
    for snippet in (snippets or []):
        if not isinstance(snippet, dict) or not snippet.get("id"):
            continue
        snippet_id = str(snippet["id"])
        label = _latest_own_label(labels.get(snippet_id), rater_id)
        if label is None:
            continue
        coach_value = (
            label.get("value")
            if label.get("value") in _LABEL_VALUES else None
        )
        machine_value = (
            label.get("machine_value")
            if label.get("machine_value") in _MACHINE_VALUES else None
        )
        unrateable = label.get("unrateable") is True
        comparable = (
            not unrateable
            and coach_value in _PERCEPTUAL_VALUES
            and machine_value in _MACHINE_VALUES
        )
        rows.append({
            "snippet_id": snippet_id,
            "transcript": snippet.get("transcript") or "",
            "machine_value": machine_value,
            "coach_value": coach_value,
            "coach_unrateable": unrateable,
            "agreement": (
                coach_value == machine_value if comparable else None
            ),
            "both_confident": (
                coach_value == "yes" and machine_value == "yes"
                if comparable else False
            ),
        })

    comparable_rows = [row for row in rows if row["agreement"] is not None]
    same = sum(1 for row in comparable_rows if row["agreement"] is True)
    return {
        "rows": rows,
        "summary": {
            "labelled": len(rows),
            "comparable": len(comparable_rows),
            "same": same,
            "different": len(comparable_rows) - same,
            "both_confident": sum(
                1 for row in comparable_rows if row["both_confident"]
            ),
        },
    }
