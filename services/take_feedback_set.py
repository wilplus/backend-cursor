"""Immutable Feedback Manager membership for one spoken Take.

The visible payload is rebuilt on each GET because playback references expire
and accepted items disappear.  Membership is not rebuilt: only stable candidate
identities are stored, so accepting item one can never reveal item four.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


MAX_FEEDBACK_PER_TAKE = 3
CONFIDENT_VOICE_FAMILY = "confident_voice"


def feedback_identity(change: Any) -> Optional[dict]:
    """Return the minimal durable identity for one visible feedback item."""
    if not isinstance(change, dict):
        return None
    item_id = str(change.get("id") or "").strip()
    kind = str(change.get("kind") or "").strip()
    source = str(change.get("source") or "").strip()
    family = str(change.get("feedback_family") or "").strip()
    if not item_id or not kind or not source or not family:
        return None
    return {
        "id": item_id,
        "kind": kind,
        "source": source,
        "feedback_family": family,
        **({"snippet_id": str(change["snippet_id"])}
           if change.get("snippet_id") else {}),
        **({"take_session_id": str(change["take_session_id"])}
           if change.get("take_session_id") else {}),
    }


def _identity_tuple(value: Any) -> Optional[tuple[str, str, str, str]]:
    if not isinstance(value, dict):
        return None
    fields = (
        str(value.get("id") or "").strip(),
        str(value.get("kind") or "").strip(),
        str(value.get("source") or "").strip(),
        str(value.get("feedback_family") or "").strip(),
    )
    return fields if all(fields) else None


def _candidate_tuple(value: Any) -> Optional[tuple[str, str, str]]:
    if not isinstance(value, dict):
        return None
    fields = (
        str(value.get("id") or "").strip(),
        str(value.get("kind") or "").strip(),
        str(value.get("source") or "").strip(),
    )
    return fields if all(fields) else None


def sanitize_selected_keys(value: Any) -> list[dict]:
    """Validate/dedupe stored keys without trusting a JSONB row's shape."""
    out: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in value if isinstance(value, list) else []:
        key = feedback_identity(raw)
        identity = _identity_tuple(key)
        if key is None or identity is None or identity in seen:
            continue
        seen.add(identity)
        out.append(key)
        if len(out) == MAX_FEEDBACK_PER_TAKE:
            break
    return out


def selected_keys(changes: Iterable[Any]) -> list[dict]:
    """Stable keys for the final Manager output, capped across every lane."""
    return sanitize_selected_keys([
        key for key in (feedback_identity(row) for row in changes)
        if key is not None
    ])


def has_confident_voice(keys: Any) -> bool:
    return any(
        isinstance(key, dict)
        and key.get("feedback_family") == CONFIDENT_VOICE_FAMILY
        for key in (keys if isinstance(keys, list) else [])
    )


def filter_to_selected(changes: Iterable[Any], keys: Any) -> list[dict]:
    """Keep current payload rows whose immutable membership key was claimed."""
    allowed = {
        identity for identity in (
            _identity_tuple(key) for key in sanitize_selected_keys(keys))
        if identity is not None
    }
    if not allowed:
        return []
    return [
        row for row in changes
        if isinstance(row, dict) and _identity_tuple(row) in allowed
    ]


def filter_candidates_to_selected(
    changes: Iterable[Any], keys: Any,
) -> list[dict]:
    """Filter the pre-Manager pool, before feedback_family is stamped."""
    allowed = {
        identity for identity in (
            _candidate_tuple(key) for key in sanitize_selected_keys(keys))
        if identity is not None
    }
    if not allowed:
        return []
    return [
        row for row in changes
        if isinstance(row, dict) and _candidate_tuple(row) in allowed
    ]


def load_feedback_set(
    database: Any, arc_id: str, take_session_id: str,
) -> Optional[dict]:
    row = database.get_ideal_text_feedback_set(
        str(arc_id), str(take_session_id))
    if not isinstance(row, dict):
        return None
    if (str(row.get("arc_id") or "") != str(arc_id)
            or str(row.get("take_session_id") or "")
            != str(take_session_id)):
        return None
    keys = sanitize_selected_keys(row.get("selected_keys"))
    if not keys or not has_confident_voice(keys):
        return None
    return {**row, "selected_keys": keys}


def claim_feedback_set(
    database: Any,
    *,
    arc_id: str,
    owner_user_id: str,
    take_session_id: str,
    take_index: int,
    review_version: int,
    changes: Iterable[Any],
) -> Optional[dict]:
    """Claim the final set once; return the database winner on a race.

    The required Confident Voice family is checked before persistence.  A
    detector/generation fault therefore cannot freeze a rewrite-only set that
    permanently violates the Take contract.
    """
    keys = selected_keys(changes)
    if not keys or not has_confident_voice(keys):
        return None
    row = database.claim_ideal_text_feedback_set(
        str(arc_id),
        str(owner_user_id),
        str(take_session_id),
        int(take_index),
        int(review_version),
        keys,
    )
    if not isinstance(row, dict):
        return None
    claimed = sanitize_selected_keys(row.get("selected_keys"))
    if not claimed or not has_confident_voice(claimed):
        return None
    return {**row, "selected_keys": claimed}
