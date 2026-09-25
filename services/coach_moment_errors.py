"""The coach names the error on a moment, and attaching teaches the library.

FOUNDER 2026-09-25, on the coach's Confident Voice practice review:

* "Naming a new error tags the clip, stored as coach provenance."
* "Attach = both": giving an exercise to the speaker for this moment also
  records, in the library, that the exercise fixes this moment's error.

PROVENANCE (L3). Three different things meet here and none may become
another:

* the MACHINE's reading of the clip: ``observed_problem_tags``, a detector
  verdict;
* the COACH's naming of the error on the clip: ``coach_moment_error_event``,
  a judgement about one recording, never shown to the speaker and never a
  training label;
* the LIBRARY's claim about an exercise: ``acoustic_problem_tags``, what the
  exercise fixes, used to match any speaker on their OWN detector verdict.

Teaching turns one of the first two into the third, and records which one it
was (``source``), so the claim always says where it came from.

The rules are pure functions; the few functions under "what the route
calls" do the reading and writing, so the routes stay inside the route fence.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from services.confident_voice_practice import (
    detected_problem_vocabulary,
    observed_problem_tags,
    stored_practice_verdict,
)

SOURCE_COACH_NAMED = "coach_named"
SOURCE_MACHINE_OBSERVED = "machine_observed"


def current_named_errors(events: Iterable[Any]) -> list[str]:
    """The errors the coach has named on this moment and not withdrawn.

    ``events`` arrive in the order they happened. The latest event for each
    error decides it, and the result keeps the order each was first named in,
    so the list does not reshuffle when one is withdrawn and named again.
    """
    latest: dict[str, str] = {}
    order: list[str] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        error_id = str(event.get("error_id") or "")
        action = event.get("action")
        if not error_id or action not in ("named", "withdrawn"):
            continue
        if error_id not in latest:
            order.append(error_id)
        latest[error_id] = action
    return [e for e in order if latest[e] == "named"]


def teachable_errors(
    practice: Any, named: Iterable[str], database: Any,
) -> tuple[list[str], str]:
    """What attaching an exercise to this moment teaches, and on whose word.

    THE COACH'S NAMING WINS. If the coach named errors on this moment, those
    are what the exercise is taught to fix: the coach listened, and may have
    heard something other than what the machine flagged. Only the named errors
    the machine can DETECT are teachable, because the library matches an
    exercise against detector verdicts; a name no detector produces would
    match nobody, ever. If every name is detector-less, nothing is taught.
    The machine's reading is NOT substituted, since the coach said it was
    something else.

    OTHERWISE THE MACHINE'S READING, which the coach accepted by attaching an
    exercise to it.
    """
    vocabulary = detected_problem_vocabulary(database)
    named_list = [str(e) for e in named or [] if e]
    if named_list:
        teachable = [e for e in named_list if not vocabulary or e in vocabulary]
        return teachable, SOURCE_COACH_NAMED
    observed = observed_problem_tags(
        stored_practice_verdict(practice), vocabulary=vocabulary)
    return sorted(observed), SOURCE_MACHINE_OBSERVED


def live_library_teachings(rows: Iterable[Any]) -> list[dict]:
    """Teachings from this moment that CHANGED the library and still stand.

    These are the ones worth telling the coach about and offering to undo. A
    teaching that found the tag already there changed nothing the coach could
    see, so it carries no notice.
    """
    rows = [r for r in rows or [] if isinstance(r, dict)]
    undone = {str(r.get("undoes_id")) for r in rows
              if r.get("action") == "undone" and r.get("undoes_id")}
    return [
        {
            "teaching_id": str(r.get("id")),
            "exercise_id": str(r.get("exercise_id") or ""),
            "error_id": str(r.get("error_id") or ""),
        }
        for r in rows
        if r.get("action") == "taught" and r.get("changed_tags")
        and str(r.get("id")) not in undone
    ]


def error_labels(database: Any) -> dict[str, str]:
    """error_id → the name people read, retired entries included.

    Retired entries stay readable, so a name given before an error was
    retired still shows as a name rather than a bare code.
    """
    if not hasattr(database, "list_speaking_errors"):
        return {}
    rows = database.list_speaking_errors(active_only=False) or []
    return {
        str(row.get("error_id")): str(row.get("label") or row.get("error_id"))
        for row in rows
        if isinstance(row, dict) and row.get("error_id")
    }


# ── what the route calls ────────────────────────────────────────────────────
# The route fence (tests/test_route_fence.py) allows a route one direct db
# call, and the practice route is grandfathered and may only shrink. So every
# read and write the coach's review adds lives here, and the route spends a
# line or two calling it.

def moment_teaching(practice: Any, database: Any) -> tuple[list[str], str]:
    """The errors this moment would teach an exercise, and on whose word."""
    named = current_named_errors(
        database.list_coach_moment_error_events(str(practice.get("id"))))
    return teachable_errors(practice, named, database)


def with_moment_errors(custom_body: Any, practice: Any, database: Any) -> Any:
    """A coach's own exercise treats THIS moment's error unless they said
    otherwise.

    The form never sent one, so since founder decision 04 (#643), when this
    path started filing into the library, every exercise a coach wrote here
    was refused for naming no error. It takes the errors attaching would
    teach: the coach's own naming where there is one, the machine's reading
    where there is not. With neither, the body is left alone and the
    catalogue's refusal says why.
    """
    if not isinstance(custom_body, dict) or custom_body.get(
            "acoustic_problem_tags"):
        return custom_body
    errors, _source = moment_teaching(practice, database)
    return {**custom_body, "acoustic_problem_tags": errors} if errors \
        else custom_body


def teach_on_attach(
    database: Any, practice: Any, exercise_id: str, coach_id: str,
) -> None:
    """ "Attach = both" (founder 2026-09-25): attaching teaches the library.

    Called after the save, never before it and never in its way. A teaching
    that fails leaves the attach standing, and the coach is not told of a
    teaching that did not happen, because the payload lists only teachings
    that were recorded.
    """
    errors, source = moment_teaching(practice, database)
    if errors and exercise_id:
        database.teach_diagnostic_exercise(
            exercise_id, str(practice.get("id")), coach_id, errors, source)


def apply_moment_edit(
    database: Any, practice: Any, body: Any, coach_id: str,
) -> tuple[int, Optional[dict]]:
    """PATCH on the coach's practice review: one edit per request.

    ``{"name_error": {"error_id": str, "named": bool}}`` names (or withdraws)
    an error on this moment. The error must already be in the library; a new
    one is filed there first, through POST /coach/speaking-errors, which is
    where names are made. A retired entry can be withdrawn but not newly
    given. Naming what is already named, or withdrawing what is not, writes
    nothing.

    ``{"undo_teaching": "<id>"}`` undoes what attaching taught the library,
    from THIS moment only. Undoing twice is not an error.

    Returns ``(status, None)`` on success, or ``(status, error_body)``.
    """
    body = body if isinstance(body, dict) else {}
    practice_id = str(practice.get("id"))
    if "name_error" in body:
        return _name_error(database, practice_id, body["name_error"], coach_id)
    if "undo_teaching" in body:
        return _undo_teaching(database, practice_id, body["undo_teaching"],
                              coach_id)
    return 400, {"code": "INVALID_INPUT",
                 "error": "name_error or undo_teaching is required"}


def _name_error(
    database: Any, practice_id: str, edit: Any, coach_id: str,
) -> tuple[int, Optional[dict]]:
    edit = edit if isinstance(edit, dict) else {}
    error_id = edit.get("error_id")
    named = edit.get("named")
    if not isinstance(error_id, str) or not error_id.strip() \
            or not isinstance(named, bool):
        return 400, {"code": "INVALID_INPUT",
                     "error": "error_id and named are required"}
    error_id = error_id.strip()
    entry = database.get_speaking_error(error_id)
    if not entry or (named and entry.get("active") is False):
        return 404, {"code": "ERROR_NOT_IN_LIBRARY",
                     "error": "Add this error to the library first."}
    already = error_id in current_named_errors(
        database.list_coach_moment_error_events(practice_id))
    if named == already:
        return 200, None
    written = database.insert_coach_moment_error_event(
        practice_id, error_id, coach_id, "named" if named else "withdrawn")
    if not written:
        return 503, {"code": "V2_ERROR", "error": "Could not save the error."}
    return 200, None


_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _undo_teaching(
    database: Any, practice_id: str, teaching_id: Any, coach_id: str,
) -> tuple[int, Optional[dict]]:
    if not isinstance(teaching_id, str) or not _UUID.match(teaching_id):
        return 400, {"code": "INVALID_INPUT",
                     "error": "undo_teaching must be a teaching id"}
    result = database.undo_diagnostic_exercise_teaching(
        teaching_id, practice_id, coach_id)
    if result is None:
        return 503, {"code": "V2_ERROR", "error": "Could not undo."}
    if not result.get("undone") and result.get("reason") == "not_found":
        return 404, {"code": "NOT_FOUND",
                     "error": "Nothing to undo on this moment."}
    return 200, None


def coach_moment_fields(practice: Any, database: Any) -> dict:
    """The coach's names on this moment, and what attaching taught.

    COACH ONLY. The speaker's payload (_practice_user_payload) carries
    neither, so a speaker never sees a coach's judgement about their
    recording.
    """
    practice_id = str(practice.get("id"))
    labels = error_labels(database)
    named = current_named_errors(
        database.list_coach_moment_error_events(practice_id))
    teachings = live_library_teachings(
        database.list_diagnostic_exercise_teachings(practice_id))
    return {
        "named_errors": [
            {"error_id": error_id, "label": labels.get(error_id, error_id)}
            for error_id in named
        ],
        "library_teachings": [
            {**teaching,
             "error_label": labels.get(teaching["error_id"],
                                       teaching["error_id"])}
            for teaching in teachings
        ],
    }
