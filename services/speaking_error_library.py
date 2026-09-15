"""Authoring for the speaking error library — naming, never detection.

Founder 2026-09-15: a coach should be able to add a pattern's NAME the moment
they notice it, without waiting for a deploy. `status` is the seam that makes
that safe, and this module is where the two refusals that hold it live:

  * nothing written here may claim `detected`. That status means code can find
    the pattern in audio; no form submission can make that true, and a name
    claiming it would route exercises off a capability that does not exist.

  * an entry that IS already detected cannot be saved from here at all. The
    write is an upsert, so re-saving `ending_compression` from an authoring
    form would carry `status: observed` over it, and matching would quietly
    stop routing that error — no exception, no log, nothing to notice. That
    silent failure is the thing this library exists to prevent, so it is
    refused rather than merged.

The route is a thin caller: the repository's route fence caps a new route at
one database call, and correctly — a check-then-write belongs behind one
function that owns both halves.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# Mirrors `speaking_error_id_shape` in the migration. Duplicated on purpose:
# the database is the real guard, and this exists so an author gets a sentence
# explaining why rather than a 500 from a constraint violation.
ERROR_ID_SHAPE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class LibraryRefusal(Exception):
    """A refusal an author needs to read, not a bug."""

    def __init__(self, message: str, *, code: str = "INVALID_INPUT",
                 status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def save_observed_error(database: Any, body: Any) -> Optional[dict]:
    """Validate and write one `observed` library entry.

    Raises LibraryRefusal for anything an author can fix; returns None only
    when the write itself failed.
    """
    fields: dict = body if isinstance(body, dict) else {}
    error_id = str(fields.get("error_id") or "").strip()
    if not ERROR_ID_SHAPE.match(error_id):
        raise LibraryRefusal(
            "error_id: lower-case letters, digits and underscores only. "
            "Matching is string overlap, so a space or a capital would match "
            "nothing, raise nothing, and route nothing.")
    if fields.get("status") not in (None, "observed"):
        raise LibraryRefusal(
            "status: this surface records an OBSERVED pattern. Marking one "
            "detected requires a detector in code, and is set by the "
            "migration that adds it.")

    label = str(fields.get("label") or "").strip()
    definition = str(fields.get("definition") or "").strip()
    asks = str(fields.get("asks") or "").strip()
    if not label or not definition or not asks:
        raise LibraryRefusal(
            "an entry needs a label, a written definition of what is "
            "measured, and the single question it asks — a name with no "
            "definition is the exact defect the construct fence exists to "
            "prevent")

    existing = database.get_speaking_error(error_id)
    if isinstance(existing, dict) and existing.get("status") == "detected":
        raise LibraryRefusal(
            "this error is already detected in code; saving it here would "
            "demote it to observed and silently stop it routing exercises",
            code="ALREADY_DETECTED", status=409)

    observed_by = str(fields.get("observed_by") or "").strip()
    active = fields.get("active")
    return database.upsert_speaking_error({
        "error_id": error_id,
        "label": label,
        "definition": definition,
        "asks": asks,
        # Never read from the caller: see the module note.
        "status": "observed",
        "observed_by": observed_by or None,
        "active": active if isinstance(active, bool) else True,
    })
