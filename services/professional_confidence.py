"""Professional-coach confidence judgments used by the product loop.

Blind peer ratings remain valuable internal training and evaluation data, but
they are not product authority. This module is the single boundary that reads
the shared ratings table for live coaching behavior: only an explicit,
rateable confidence judgment from a professional coach may pass.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


def is_professional_coach_rating(row: Any) -> bool:
    """Whether ``row`` is an explicit professional confidence judgment."""
    if not isinstance(row, dict) or row.get("self_report") is True:
        return False
    lane = row.get("lane")
    professional = lane == "coach" or (
        lane is None and row.get("source") == "coach"
    )
    return bool(
        professional
        and row.get("state_id") in (None, "confidence")
        and row.get("unrateable") is not True
        and row.get("value") in ("yes", "no")
    )


def latest_professional_value(rows: Any) -> Optional[str]:
    """Latest professional Yes/No from a collection of rating rows."""
    professional = [row for row in (rows or [])
                    if is_professional_coach_rating(row)]
    professional.sort(
        key=lambda row: row.get("updated_at") or row.get("created_at") or ""
    )
    return professional[-1].get("value") if professional else None


def professional_verdicts(database, snippet_ids: Iterable[Any]) -> dict:
    """Return ``{snippet_id: yes|no}`` using professional rows only.

    The read is batched and best-effort. Missing, peer-only, owner, bootstrap,
    neutral, and unrateable rows are absent rather than promoted to product
    decisions.
    """
    ids = [str(value) for value in (snippet_ids or []) if value]
    if not ids:
        return {}
    try:
        rows_by_snippet = (
            database.get_confidence_labels_by_snippet_ids(ids) or {}
        )
    except Exception as error:
        logger.warning(
            "professional confidence read failed (%d ids): %s",
            len(ids),
            error,
        )
        return {}
    out: dict = {}
    for snippet_id in ids:
        value = latest_professional_value(rows_by_snippet.get(snippet_id))
        if value is not None:
            out[snippet_id] = value
    return out


def professional_yes_ids(database, snippet_ids: Iterable[Any]) -> set:
    """Subset carrying a latest explicit professional Yes."""
    return {
        snippet_id for snippet_id, value
        in professional_verdicts(database, snippet_ids).items()
        if value == "yes"
    }
