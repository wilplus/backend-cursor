"""The coach's diagnosis of an error moment comes first (founder 2026-10-06,
coach panel redesign lock flow 6, N56.1; the words CP2 A; Q-B7 A and Q-B12 A,
N62; build plan D-CP-4; migration 0445).

THE SCREEN (lock flow 6). "What kind of error is it?" The errors the machine
heard come first, marked "The machine heard this"; then the other active
library errors; then "Something else · Name a new error" and "I don't hear
an error". The panel owns the words (signed, CP2 A); this module hands it
the list in that order, each entry with its label and whether the machine
heard it, and the coach's current diagnosis.

THE RULE (Q-B7 A). An error a coach names in one field is stored as "named
by a coach" (``coach_named_errors``) until the founder writes its definition
and question in admin and links it to the library; the coach's list shows
every active library error plus the coach-named ones. Naming is a signal
for the founder only: nothing here feeds a detector's readiness, which still
comes from blind "Do you hear it?" answers (services/error_presence_audit).
A diagnosis is coach provenance about one recording (L3): never a training
label, never a quorum vote, never shown to the speaker (AC-9: the speaker's
payload carries no diagnosis). Q-B12 A: a changed diagnosis replaces the
current one; the old one stays in history (the database function versions
it).

THE GATE. The route runs behind ``_moment_gate`` (BLIND COACH): a coach
diagnoses a moment only after their own blind rating of it.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

KINDS = ("error", "named_error", "no_error")
NAME_MAX = 120

_REFUSALS = {
    "COACH_DIAGNOSIS_INPUT_INVALID": (400, "INVALID_INPUT", "That diagnosis is not valid."),
    "COACH_DIAGNOSIS_ERROR_NOT_IN_LIBRARY": (
        404, "ERROR_NOT_IN_LIBRARY", "That error is not in the library."),
}


def _error(status: int, code: str, message: str) -> tuple[int, dict]:
    return status, {"code": code, "error": message}


def machine_heard_error_ids(request: Any) -> list[str]:
    """The library errors the detectors named on this moment, in the order
    the request stored them (exercise_coach_requests.observed_tags). Words
    only: ids the panel labels, never a number."""
    if not isinstance(request, dict):
        return []
    out: list[str] = []
    for tag in request.get("observed_tags") or []:
        if isinstance(tag, str) and tag and tag not in out:
            out.append(tag)
    return out


def error_choices(library: Any, named: Any, heard: Any) -> list[dict]:
    """The list the screen shows, in the lock's order: the machine-heard
    library errors first (flagged), then the other active library errors,
    then the coach-named ones (not yet linked). Pure."""
    heard_ids = [str(h) for h in (heard or []) if h]
    rows = [r for r in (library or []) if isinstance(r, dict) and r.get("error_id")
            and r.get("active") is not False]
    by_id = {str(r["error_id"]): r for r in rows}
    out: list[dict] = []
    for error_id in heard_ids:
        row = by_id.get(error_id)
        if row is not None:
            out.append({"kind": "error", "error_id": error_id,
                        "label": str(row.get("label") or error_id), "machine_heard": True})
    for row in rows:
        error_id = str(row["error_id"])
        if error_id in heard_ids:
            continue
        out.append({"kind": "error", "error_id": error_id,
                    "label": str(row.get("label") or error_id), "machine_heard": False})
    for row in named or []:
        if not isinstance(row, dict) or not row.get("id") or row.get("speaking_error_id"):
            continue
        out.append({"kind": "named_error", "named_error_id": str(row["id"]),
                    "label": str(row.get("name") or ""), "machine_heard": False,
                    "named_by_a_coach": True})
    return out


def diagnosis_payload(row: Any) -> Optional[dict]:
    """The coach's current diagnosis as the panel reads it; None when the
    coach has not diagnosed the moment. Never a number."""
    if not isinstance(row, dict) or row.get("kind") not in KINDS:
        return None
    # The version is history bookkeeping for audit, not a count for anyone:
    # the panel does not show it, so it does not ride.
    out: dict = {"kind": str(row["kind"])}
    if row.get("kind") == "error":
        out["error_id"] = str(row.get("error_id") or "")
    elif row.get("kind") == "named_error":
        out["named_error_id"] = str(row.get("named_error_id") or "")
    out["created_at"] = row.get("created_at")
    return out


def parse_body(body: Any) -> tuple[Optional[dict], Optional[tuple[int, dict]]]:
    """PUT {error_id} | {new_name} | {no_error: true}: exactly one. Pure."""
    fields: dict = body if isinstance(body, dict) else {}
    chosen = [k for k in ("error_id", "new_name", "no_error") if k in fields]
    if len(chosen) != 1:
        return None, _error(400, "INVALID_INPUT",
                            "Send exactly one of error_id, new_name or no_error.")
    key = chosen[0]
    if key == "no_error":
        if fields["no_error"] is not True:
            return None, _error(400, "INVALID_INPUT", "no_error must be true.")
        return {"kind": "no_error", "error_id": None, "new_name": None}, None
    value = fields[key]
    if not isinstance(value, str) or not value.strip():
        return None, _error(400, "INVALID_INPUT", f"{key} must be a non-empty string.")
    if key == "error_id":
        return {"kind": "error", "error_id": value.strip(), "new_name": None}, None
    name = " ".join(value.split())
    if len(name) > NAME_MAX:
        return None, _error(400, "INVALID_INPUT", "The name is too long.")
    return {"kind": "named_error", "error_id": None, "new_name": name}, None


def read(database: Any, *, take_session_id: str, snippet_id: str,
         coach_id: str) -> tuple[int, dict]:
    """GET: the choices in the lock's order and this coach's current
    diagnosis. The route has already enforced the blind gate."""
    take, snip = str(take_session_id), str(snippet_id)
    request = database.get_exercise_coach_request(take, snip)
    heard = machine_heard_error_ids(request)
    library = database.list_speaking_errors() or []
    named = database.list_coach_named_errors(unlinked_only=True) or []
    current = database.get_coach_moment_diagnosis(snippet_id=snip, coach_id=str(coach_id))
    return 200, {
        "errors": error_choices(library, named, heard),
        "diagnosis": diagnosis_payload(current),
    }


def diagnose(database: Any, *, take_session_id: str, snippet_id: str,
             coach_id: str, body: Any) -> tuple[int, dict]:
    """PUT: save this coach's diagnosis of the moment; the same one again
    changes nothing, a different one replaces it and keeps the old in
    history (Q-B12 A). The route has already enforced the blind gate."""
    parsed, error = parse_body(body)
    if error or parsed is None:
        return error or _error(400, "INVALID_INPUT", "That diagnosis is not valid.")
    try:
        row = database.set_coach_moment_diagnosis(
            take_session_id=str(take_session_id), snippet_id=str(snippet_id),
            coach_id=str(coach_id), kind=parsed["kind"],
            error_id=parsed["error_id"], new_name=parsed["new_name"])
    except Exception as e:  # the database's refusal, named
        for code, refusal in _REFUSALS.items():
            if code in str(e):
                return _error(*refusal)
        _log.error("coach diagnosis not saved take=%s snip=%s: %s",
                   take_session_id, snippet_id, e, exc_info=True)
        return _error(500, "V2_ERROR", "Could not save the diagnosis.")
    if not isinstance(row, dict):
        return _error(500, "V2_ERROR", "Could not save the diagnosis.")
    return 200, {"diagnosis": diagnosis_payload(row)}


def review(database: Any, *, take_session_id: str, snippet_id: str,
           coach_id: str, method: str, body: Any = None) -> tuple[int, dict]:
    """GET reads, PUT diagnoses; one entry for the route."""
    if method == "GET":
        return read(database, take_session_id=take_session_id,
                    snippet_id=snippet_id, coach_id=coach_id)
    return diagnose(database, take_session_id=take_session_id,
                    snippet_id=snippet_id, coach_id=coach_id, body=body)
