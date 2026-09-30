"""A pair remembers the yes (founder 2026-09-30, L1; build plan ML-8).

Door 1 is the training yes. Its switch (MLC2_TRAINING_SWITCH_ENABLED) is
closed in code until counsel's wording lands; this module is the machinery
that works either way:

  * every pair is stamped at write with its owner's principal and the
    consent state the ledger shows for that principal at that moment;
  * the weekly refresh (refresh_feedback_pair_consent_v1, migration 0405)
    recomputes every pair from the ledger, so a yes given later makes older
    pairs releasable and a withdrawal makes them not, voiding any release
    that carried them.

WHICH SURFACES NEED THE YES is counsel's question (L1). Until the answer
lands, every surface does: a coach's words about a speaker's passage carry
the passage. The constant below changes by a reviewed change with counsel's
answer, never by a toggle. AC-9: nothing here reaches a speaker.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.feedback_pairs import SURFACES

_log = logging.getLogger(__name__)

#: The pair surfaces whose release needs the speaker's training yes. All
#: three until counsel says otherwise (founder 2026-09-30, L1).
CONSENT_REQUIRED_SURFACES: frozenset = frozenset(SURFACES)

STATES = ("yes", "no", "not_needed", "unknown")


def principal_for_user(database: Any, owner_user_id: Any) -> Optional[str]:
    """The owner principal behind a user id, or None (a guest, a missing
    row, a database fault). Never creates one: a pair is not the moment
    to give a person an identity."""
    if not owner_user_id:
        return None
    reader = getattr(database, "get_owner_principal_for_user", None)
    if reader is None:
        return None
    try:
        row = reader(str(owner_user_id))
    except Exception as e:  # noqa: BLE001 -- the stamp is best effort, the refresh is the record
        _log.info("owner principal lookup failed: %s", e, exc_info=True)
        return None
    return str(row["id"]) if isinstance(row, dict) and row.get("id") else None


def consent_for_principal(database: Any, principal_id: Optional[str]) -> dict:
    """The ledger's answer for a principal, as the status RPC reads it:
    {active, grant_event_id, consent_policy_version}. Absent is a no."""
    if not principal_id:
        return {"active": False}
    reader = getattr(database, "get_mlc2_training_consent_status", None)
    if reader is None:
        return {"active": False}
    try:
        status = reader(principal_id) or {}
    except Exception as e:  # noqa: BLE001 -- the refresh is the record
        _log.info("training consent status read failed: %s", e, exc_info=True)
        return {"active": False}
    return status if isinstance(status, dict) else {"active": False}


def stamp(database: Any, *, surface: str, owner_user_id: Any) -> dict:
    """The consent columns for a new pair: principal, state, grant, policy,
    releasable. A surface outside CONSENT_REQUIRED_SURFACES is releasable
    without a yes ('not_needed'); a pair with no principal is 'unknown' and
    not releasable."""
    principal = principal_for_user(database, owner_user_id)
    if surface not in CONSENT_REQUIRED_SURFACES:
        return {"owner_principal_id": principal, "consent_state": "not_needed",
                "consent_grant_event_id": None, "consent_policy_version": None,
                "releasable": True}
    if not principal:
        return {"owner_principal_id": None, "consent_state": "unknown",
                "consent_grant_event_id": None, "consent_policy_version": None,
                "releasable": False}
    status = consent_for_principal(database, principal)
    if status.get("active") is True:
        return {"owner_principal_id": principal, "consent_state": "yes",
                "consent_grant_event_id": status.get("grant_event_id"),
                "consent_policy_version": status.get("consent_policy_version"),
                "releasable": True}
    return {"owner_principal_id": principal, "consent_state": "no",
            "consent_grant_event_id": None, "consent_policy_version": None,
            "releasable": False}


def refresh(database: Any) -> dict:
    """The weekly refresh. Counts about the system, or {unavailable: why}."""
    runner = getattr(database, "refresh_feedback_pair_consent", None)
    if runner is None:
        return {"unavailable": "no refresh on this database"}
    try:
        out = runner(sorted(CONSENT_REQUIRED_SURFACES))
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("pair consent refresh failed: %s", e, exc_info=True)
        return {"unavailable": str(e)[:200]}
    return dict(out) if isinstance(out, dict) else {}
