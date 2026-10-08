"""A pair remembers the yes (founder 2026-09-30, L1; build plan ML-8).

Door 1 is the training yes. Its switch (MLC2_TRAINING_SWITCH_ENABLED) is
open since 2026-10-01 (counsel's wording signed, "open door 1"); this
module is the machinery, and it works whether the switch is open or not:

  * every pair is stamped at write with its owner's principal and the
    consent state the ledger shows for that principal at that moment;
  * the weekly refresh (refresh_feedback_pair_consent_v1, migration 0405)
    recomputes every pair from the ledger, so a yes given later makes older
    pairs releasable and a withdrawal makes them not, voiding any release
    that carried them;
  * a person whose service is ending (an account deletion not cancelled,
    or a termination) has no releasable pair whatever the ledger says
    (0422, PLF-T3): at the request, at the stamp and at every refresh.

WHICH SURFACES NEED THE YES: all three, counsel 2026-10-01 (a coach's note
about a speaker's passage is the speaker's personal data even without the
passage attached; basis Art 6(1)(a) with Art 9(2)(a), never legitimate
interest). The constant below changes only by a reviewed change carrying a
new answer from counsel, never by a toggle. AC-9: nothing here reaches a
speaker.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.feedback_pairs import SURFACES

_log = logging.getLogger(__name__)

#: The pair surfaces whose release needs the speaker's training yes. All
#: three (counsel 2026-10-01; founder 2026-09-30, L1).
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
        # The yes stands, but a person whose service is ending adds nothing
        # to any release (0422, PLF-T3); the weekly refresh keeps it so.
        from services.account_deletion import learning_stopped

        return {"owner_principal_id": principal, "consent_state": "yes",
                "consent_grant_event_id": status.get("grant_event_id"),
                "consent_policy_version": status.get("consent_policy_version"),
                "releasable": not learning_stopped(database, principal)}
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


# ── The training yes for the other learning lanes (3.5 pack, E4 and E5) ──
#
# Privacy 3.5 §4a (signed 2026-10-08): anything that learns across people
# uses a speaker's data only while that speaker holds the training yes. These
# readers are the pairs' own rule, reused so every lane reads the same one:
# the ledger's status (``get_mlc2_training_consent_status_v2``, which counts a
# yes only under a training policy that is not retired and reads a withdrawal
# as no; the database refuses the yes itself to anyone not on the processing
# policy that introduced training, as door 1 does), and a
# person whose service is ending has none (0422). They add no rule of their
# own. Every doubt answers no: a missing principal, an unreadable ledger, a
# database fault. A lane skips that speaker; it never waits or guesses.


def holds_training_yes(database: Any, principal_id: Optional[str]) -> bool:
    """True only while this principal holds an active training yes and
    their service is not ending. Fails closed."""
    if not principal_id:
        return False
    if consent_for_principal(database, principal_id).get("active") is not True:
        return False
    from services.account_deletion import learning_stopped

    return not learning_stopped(database, principal_id)


def user_holds_training_yes(database: Any, owner_user_id: Any) -> bool:
    """``holds_training_yes`` for the principal behind a user id."""
    return holds_training_yes(database, principal_for_user(database, owner_user_id))


def take_principal(database: Any, take_session_id: Any) -> Optional[str]:
    """The owner principal behind a Take, as the corpus copy resolves it:
    the Take's own column, else its project's owner (always set), else the
    principal of its user. None when none can be read."""
    if not take_session_id:
        return None
    try:
        session = database.v2_get_session_by_id(str(take_session_id)) or {}
    except Exception as e:  # noqa: BLE001 -- unknown reads as no yes
        _log.info("take owner read failed: %s", e, exc_info=True)
        return None
    if not isinstance(session, dict):
        return None
    owner = str(session.get("owner_principal_id") or "")
    project = str(session.get("project_id") or session.get("arc_id") or "")
    reader = getattr(database, "get_project_owner_principal", None)
    if not owner and project and reader is not None:
        try:
            owner = str(reader(project) or "")
        except Exception as e:  # noqa: BLE001
            _log.info("project owner read failed: %s", e, exc_info=True)
    return owner or principal_for_user(database, session.get("user_id"))


def take_holds_training_yes(database: Any, take_session_id: Any) -> bool:
    """``holds_training_yes`` for the speaker of a Take."""
    return holds_training_yes(database, take_principal(database, take_session_id))


def erase_withdrawn_sheets(database: Any, principal_id: Any) -> dict:
    """3.5 E4, on a training withdrawal: DELETE (not hide) every V4 coach
    sheet (``v4_moment_pick_sheets``, ``v4_surer_sheets``) and blind block
    pick (``coach_block_pick``) about this person's Takes. Other speakers'
    rows are never touched: the Takes are this person's own, as the
    governed purge resolves them. Skipped while the person holds the yes
    (they turned it back on before this ran); a failed consent read counts
    as no yes, so a doubt erases. Never raises: the turn-off calls it and the
    queued erasure job runs it again."""
    if not principal_id:
        return {"skipped": "no principal"}
    if holds_training_yes(database, str(principal_id)):
        return {"skipped": "holds the training yes"}
    reader = getattr(database, "take_ids_for_principal", None)
    eraser = getattr(database, "delete_learning_sheets_for_takes", None)
    if reader is None or eraser is None:
        return {"unavailable": "no sheet erasure on this database"}
    try:
        takes = reader(str(principal_id))
        deleted = eraser(takes) if takes else {}
    except Exception as e:  # noqa: BLE001 -- named; the queued job retries
        _log.warning("withdrawn sheet erasure failed: %s", e, exc_info=True)
        return {"unavailable": str(e)[:200]}
    return {"takes": len(takes), "deleted": dict(deleted or {})}


def take_may_reach_a_coach_sheet(database: Any, take_session_id: Any) -> bool:
    """3.5 E4 (``V4_COACH_SHEETS_ENABLED``, ``COACH_BLOCK_PICK_ENABLED``):
    a coach hears a speaker's moment to answer a question that teaches the
    software (Privacy 3.5 §4a; the switch's fifth line), so a Take's
    moments go on a sheet only while its speaker holds the training yes and
    has not objected to the blind check (0454; an objection that cannot be
    read counts as one). Composes the two existing reads; no rule of its own."""
    if not take_holds_training_yes(database, take_session_id):
        return False
    from services.error_presence_audit import _objected

    return not _objected(database, str(take_session_id))
