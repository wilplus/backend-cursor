"""A pair remembers the yes (founder 2026-09-30, L1; build plan ML-8).

Door 1 is the training yes. It is open since 2026-10-01 (counsel's wording
signed, "open door 1"; its code switch was removed 2026-10-12); this
module is the machinery:

  * every pair is stamped at write with its owner's principal and the
    consent state the ledger shows for that principal at that moment;
  * the weekly refresh (refresh_feedback_pair_consent_v1, migration 0405)
    recomputes every pair from the ledger, so a yes given later makes older
    pairs releasable and a withdrawal makes them not, voiding any release
    that carried them;
  * a person whose service is ending (an account deletion not cancelled,
    or a termination) has no releasable pair whatever the ledger says
    (0422, PLF-T3): at the request, at the stamp and at every refresh.

WHICH SURFACES NEED THE YES: all of them, counsel 2026-10-01 (a coach's note
about a speaker's passage is the speaker's personal data even without the
passage attached; basis Art 6(1)(a) with Art 9(2)(a), never legitimate
interest). That covers the coach's own
two (coach_moment_line, coach_take_word) too, Privacy/Terms 3.5 signed by the
founder 2026-10-08 (decisions log N68; 22-…SIGNED, E2): the coach's words
are training data under the SPEAKER's training yes, so the speaker's yes
governs them exactly as it governs the rest (the coach agreement covers
the coach's side, and is no substitute for the speaker's yes). Since
2026-10-19 the doors are closed to both coach-word surfaces (N79); the yes
governs them again the day a door reopens to them. The constant
below changes only by a reviewed change carrying a new answer from counsel,
never by a toggle. AC-9: nothing here reaches a speaker.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.feedback_pairs import SURFACES

_log = logging.getLogger(__name__)

#: The pair surfaces whose release needs the speaker's training yes: all
#: five (counsel 2026-10-01; founder 2026-09-30, L1; the coach's own words
#: by 3.5, N68). Every surface a door knows (feedback_pairs.DOOR_SURFACES)
#: must be here; tests/test_coach_words_in_the_doors.py fails otherwise.
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
    """3.5 E4 (V4's coach sheets and the block pick):
    a coach hears a speaker's moment to answer a question that teaches the
    software (Privacy 3.5 §4a; the switch's fifth line), so a Take's
    moments go on a sheet only while its speaker holds the training yes and
    has not objected to the blind check (0454; an objection that cannot be
    read counts as one). Composes the two existing reads; no rule of its own."""
    if not take_holds_training_yes(database, take_session_id):
        return False
    from services.error_presence_audit import _objected

    return not _objected(database, str(take_session_id))


def admitted_takes(database: Any, takes: Any) -> Optional[dict]:
    """``takes_may_reach_a_coach_sheet`` for these Takes, from one read of
    each table the per-take check reads once per Take.

    None when that read cannot be done. The caller then uses the per-take
    check, so a batch that cannot run never changes who is heard.
    """
    distinct = sorted({str(t) for t in (takes or []) if t})
    if not distinct:
        return {}
    try:
        return _admitted_together(database, distinct)
    except Exception as error:  # noqa: BLE001 -- the per-take check still runs
        _log.warning("coach sheet consent batch failed: %s", error, exc_info=True)
        return None


def _admitted_together(database: Any, takes: list[str]) -> dict:
    """The per-take rule, with the Takes, projects and principals read once
    and the consent calls shared by everyone who has the same principal."""
    from services.account_deletion import learning_stopped

    sessions = _rows_by(database, "v2_sessions",
                        "id,user_id,owner_principal_id,project_id,arc_id,recording_id",
                        "id", takes)
    projects, principals = _owners_of(database, sessions)
    take_owner = {take: _take_owner(sessions.get(take) or {}, projects, principals) for take in takes}
    yes_ids = sorted({owner for owner in take_owner.values() if owner})
    yes = dict(zip(yes_ids, _side_by_side(
        [lambda owner=owner: _training_yes(database, owner, learning_stopped) for owner in yes_ids])))
    need = [take for take in takes if yes.get(take_owner[take])]
    keys = {_speaker_key(sessions.get(take) or {}, principals) for take in need}
    resolved = dict(zip(keys, _side_by_side(
        [lambda key=key: _resolve(database, key) for key in keys]))) if keys else {}
    heard: set[str] = set()
    for key in keys:
        speaker = resolved.get(key)
        if isinstance(speaker, str) and speaker:
            heard.add(speaker)
    speakers = sorted(heard)
    objected = dict(zip(speakers, _side_by_side(
        [lambda principal=principal: _objected_principal(database, principal)
         for principal in speakers]))) if speakers else {}
    out = {}
    for take in takes:
        owner = take_owner[take]
        if not yes.get(owner):
            out[take] = False
            continue
        speaker = resolved.get(_speaker_key(sessions.get(take) or {}, principals))
        out[take] = isinstance(speaker, str) and bool(speaker) and not objected.get(speaker, True)
    return out


def _training_yes(database: Any, principal: str, learning_stopped: Any) -> bool:
    """``holds_training_yes`` without importing this module into itself."""
    if consent_for_principal(database, principal).get("active") is not True:
        return False
    return not learning_stopped(database, principal)


def _rows_by(database: Any, table: str, columns: str, key: str, ids: list[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    unique = list(dict.fromkeys(ids))
    for start in range(0, len(unique), 80):
        part = unique[start:start + 80]
        rows = database.client.table(table).select(columns).in_(key, part).execute().data or []
        for row in rows:
            if isinstance(row, dict) and row.get(key):
                found[str(row[key])] = row
    return found


def _owners_of(database: Any, sessions: dict[str, dict]) -> tuple[dict[str, str], dict[str, str]]:
    projects: list[str] = []
    users: list[str] = []
    for session in sessions.values():
        if not session.get("owner_principal_id"):
            project = _uuid_text(session.get("project_id") or session.get("arc_id"))
            if project:
                projects.append(project)
        user = _uuid_text(session.get("user_id"))
        if user:
            users.append(user)
    project_rows = _rows_by(database, "projects", "id,owner_principal_id", "id", projects) if projects else {}
    user_rows = _rows_by(database, "owner_principals", "id,user_id", "user_id", users) if users else {}
    return ({pid: str(row.get("owner_principal_id") or "") for pid, row in project_rows.items()},
            {uid: str(row.get("id") or "") for uid, row in user_rows.items() if row.get("id")})


def _take_owner(session: dict, projects: dict[str, str], principals: dict[str, str]) -> str:
    """``take_principal`` from a session already read."""
    owner = str(session.get("owner_principal_id") or "")
    if not owner:
        project = str(session.get("project_id") or session.get("arc_id") or "")
        owner = projects.get(project) or ""
    if owner:
        return owner
    return principals.get(str(session.get("user_id") or "")) or ""


def _speaker_key(session: dict, principals: dict[str, str]) -> tuple:
    """The arguments ``take_speaker_principal`` resolves, without the calls."""
    user = str(session.get("user_id") or "")
    owner = principals.get(user) if user else ""
    if owner:
        return ("account", owner, user, None)
    return ("take", str(session.get("owner_principal_id") or ""), user or None,
            str(session.get("recording_id") or "") or None)


def _resolve(database: Any, key: tuple) -> Optional[str]:
    from services.processing_authorization import ProcessingAuthorizationService
    _kind, owner, user, recording = key
    try:
        principal = ProcessingAuthorizationService(database).resolve_acquisition_principal(
            owner or "", user_id=user, recording_id=recording)
    except Exception as error:  # noqa: BLE001 -- an unreadable acquirer is not heard
        _log.warning("coach sheet acquirer not read: %s", error, exc_info=True)
        return None
    return str(principal) if principal else None


def _objected_principal(database: Any, principal: str) -> bool:
    """``error_presence_audit._objected`` for a principal already resolved.
    Unreadable counts as objected, as there."""
    try:
        result = database.client.rpc("has_blind_check_objection_v1", {
            "p_acquisition_principal_id": str(principal),
        }).execute()
    except Exception as error:  # noqa: BLE001 -- unknown reads as objected
        _log.warning("blind-check objection read failed: %s", error, exc_info=True)
        return True
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        data = next(iter(data.values()), None)
    return data is not False


def _side_by_side(calls: list) -> list:
    if len(calls) <= 1:
        return [call() for call in calls]
    import contextvars
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(calls))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, call) for call in calls]
        return [future.result() for future in futures]


def _uuid_text(value: Any) -> Optional[str]:
    from uuid import UUID
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def takes_may_reach_a_coach_sheet(database: Any, takes: Any) -> dict:
    """``take_may_reach_a_coach_sheet`` for each distinct Take, keyed by
    id, the reads side by side: each check is about five database calls
    and a coach line holds up to the weekly cap of sheets (the panel's
    5-second queues, 2026-11-06). A check that fails reads as no."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor
    distinct = sorted({str(t or "") for t in (takes or [])} - {""})

    def one(take: str) -> bool:
        try:
            return bool(take_may_reach_a_coach_sheet(database, take))
        except Exception as e:  # noqa: BLE001 -- unknown reads as no
            _log.warning("coach sheet consent read failed take=%s: %s", take, e)
            return False

    if len(distinct) <= 1:
        return {t: one(t) for t in distinct}
    with ThreadPoolExecutor(max_workers=min(8, len(distinct))) as pool:
        # A copy of the request's context per check, so its database calls
        # still count in the request's timing.
        futures = {t: pool.submit(contextvars.copy_context().run, one, t) for t in distinct}
        return {t: f.result() for t, f in futures.items()}
