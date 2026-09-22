"""Immutable Feedback Manager membership for one spoken Take.

The visible payload is rebuilt on each GET because playback references expire
and accepted items disappear.  Membership is not rebuilt: only stable candidate
identities are stored, so accepting item one can never reveal item four.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


#: V2's budget: exactly one item from each of three families. Retained as
#: superseded history (24h) — it still describes every set frozen before the
#: 2026-09-18 cutover, and `snippet_ids_by_family` still reads those. It is no
#: longer what a new set must satisfy.
MAX_FEEDBACK_PER_TAKE = 3
CONFIDENT_VOICE_FAMILY = "confident_voice"
REQUIRED_FAMILIES = {
    "confident_voice", "rewrite_clarity", "great_formulation",
}

#: THE STORAGE CEILING, NOT A PRODUCT BUDGET (0347). The Manager owns how many
#: items a Take carries (L2); this bound exists so a fault cannot write an
#: unbounded array into a row every reader loads. Far above any real deck's
#: block count, far below anything that would hurt. It must stay equal to the
#: bound in the migration and in `claim_ideal_text_feedback_set_v1` — three
#: copies of one number is how V2's budget came to be enforced in four places
#: that then had to be changed together.
MAX_SELECTED_KEYS = 64


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
        if len(out) == MAX_SELECTED_KEYS:
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


def has_required_families(keys: Any) -> bool:
    """V2's budget: exactly three items, one from each family.

    Superseded history (24h). Kept because it still describes every set
    frozen before the 2026-09-18 cutover, and because naming V2's rule
    explicitly is what stops it being mistaken for the current one again.
    `is_claimable_set` is what a new set must satisfy.
    """
    sanitized = sanitize_selected_keys(keys)
    return (
        len(sanitized) == MAX_FEEDBACK_PER_TAKE
        and {str(key.get("feedback_family")) for key in sanitized}
        == REQUIRED_FAMILIES
    )


def is_claimable_set(keys: Any) -> bool:
    """May this selection be frozen as what the speaker was shown?

    THE ONE REQUIREMENT THAT SURVIVED V2 (0347). A set must carry at least
    one Confident Voice item. That is the evaluation this product exists to
    make; it must never be silently replaced by a third rewrite, which is the
    reason the old three-family rule existed. 24b guarantees V3 produces one
    per valid block, so it costs V3 nothing and keeps the guarantee V2 had.

    What is NOT required any more is "exactly three, one per family". That is
    V2's versioned budget, and V3's differs by design — one relative-best
    Confident Voice item per valid 75-word block, plus at most two Praise,
    one exercise and one rewrite (24f). A fixed three cannot describe it, and
    demanding it is why every V3 Take froze V2's selection instead of the one
    actually on screen.

    This is deliberately NOT a budget check. The Manager owns the budget
    (L2); this asks only whether a selection is a coherent record of what
    was served. A budget re-litigated here would be a second arbiter.
    """
    sanitized = sanitize_selected_keys(keys)
    return bool(sanitized) and has_confident_voice(sanitized)


def snippet_ids_by_family(keys: Any) -> dict[str, str]:
    """Return the exact clip identities already frozen for each family."""
    return {
        str(key["feedback_family"]): str(key["snippet_id"])
        for key in sanitize_selected_keys(keys)
        if key.get("feedback_family") in REQUIRED_FAMILIES
        and key.get("snippet_id")
    }


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


def frozen_set_addresses(changes: Iterable[Any], keys: Any) -> bool:
    """True when a frozen set names at least one of the rows being served.

    R-4 (audit 2026-09-22). A set that addresses NONE of the served rows
    cannot be the set that froze them — it predates them. Every document
    opened before the 2026-09-18 cutover carries V2's three keys, and V3's
    rows share no identity with them, so filtering blanks the surface and
    the insert-once claim can never correct it.

    It asks with `_identity_tuple`, the same rule `filter_to_selected` uses,
    and that is the whole point of it living here: a caller that decided
    "addresses" on ids alone would pass rows the filter then dropped for a
    differing `kind` or `source`, which is the original defect wearing a
    new predicate.
    """
    allowed = {
        identity for identity in (
            _identity_tuple(key) for key in sanitize_selected_keys(keys))
        if identity is not None
    }
    if not allowed:
        return False
    return any(
        _identity_tuple(row) in allowed
        for row in changes if isinstance(row, dict)
    )


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
    if not is_claimable_set(keys):
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

    All three required families are checked before persistence. A detector or
    generation fault therefore cannot freeze a partial set as success.
    """
    keys = selected_keys(changes)
    if not is_claimable_set(keys):
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
    if not is_claimable_set(claimed):
        return None
    return {**row, "selected_keys": claimed}
