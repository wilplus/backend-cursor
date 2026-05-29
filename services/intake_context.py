"""Per-session speech-context intake (Task 9).

The user fills out a tiny 3-field form before a full-audit / upload-
recording run so the downstream pacer + tone calibrator + snippet
scorer have actual context about what they're listening to:

    topic                  — what the user is speaking about
    audience               — who they're addressing
    target_length_seconds  — how long the talk is meant to run

All three fields are optional. NULL throughout = "use defaults"
(pre-task-9 behaviour) which keeps in-flight legacy jobs unaffected.

Two entry points:

  validate_intake_context_body(body)
    Manual validator that matches the rest of v2_routes.py's
    style (the codebase has no Pydantic dependency). Returns the
    cleaned dict on success; raises IntakeContextError with a
    user-friendly message on failure.

  snapshot_intake_context(session_id)
    Read the persisted blob from v2_sessions.intake_context AT
    ENQUEUE TIME so a user editing the form between submit and
    job-pickup can't drift the payload mid-pipeline. Wraps
    db.get_session_intake_context with one extra guarantee — the
    returned dict (if any) carries the three canonical keys with
    their None-or-value, so consumers can use a single .get()
    pattern without re-checking shape.

The route handler in routes/v2_routes.py owns the
GET/PUT /v2/user/sessions/<id>/intake-context endpoints; this
module is the validation + snapshot layer they call into.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Bounds match the FE form's UX: short tags, not paragraphs.
_MAX_TEXT_LEN = 200
# Seconds: 30s minimum keeps the form honest (anything shorter is
# the warmup gate), 7200s = 2h is the longest realistic talk.
_MIN_TARGET_SECONDS = 30
_MAX_TARGET_SECONDS = 7200

# Canonical key order — every caller iterates this list when
# building the response so the JSON shape stays stable.
_FIELDS = ("topic", "audience", "target_length_seconds")


class IntakeContextError(ValueError):
    """Validation error with an FE-renderable message.

    Raised by ``validate_intake_context_body``. The route handler
    catches and 400s with the message verbatim — matches the
    INVALID_INPUT pattern the rest of v2_routes.py uses.
    """


def _norm_text(value: Any, field_name: str) -> Optional[str]:
    """Whitespace-trim a string. Empty-after-trim collapses to None
    so "1-char min when present" is a free invariant."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntakeContextError(f"{field_name}: must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_TEXT_LEN:
        raise IntakeContextError(
            f"{field_name}: must be {_MAX_TEXT_LEN} characters or fewer"
        )
    return cleaned


def _norm_seconds(value: Any) -> Optional[int]:
    """Integer in [30, 7200] or None. Bool rejected (Python's
    bool-is-int trick would otherwise let True through as 1)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise IntakeContextError(
            "target_length_seconds: must be an integer"
        )
    if not isinstance(value, int):
        raise IntakeContextError(
            "target_length_seconds: must be an integer"
        )
    if not (_MIN_TARGET_SECONDS <= value <= _MAX_TARGET_SECONDS):
        raise IntakeContextError(
            "target_length_seconds: must be between "
            f"{_MIN_TARGET_SECONDS} and {_MAX_TARGET_SECONDS} seconds"
        )
    return value


def validate_intake_context_body(body: Any) -> dict[str, Any]:
    """Parse + validate the PUT body, returning the canonical dict.

    Accepts:
      - dict with any subset of the three keys
      - missing keys are treated as None (cleared)
      - empty body {} is valid → all-None dict (clears the column)

    Raises IntakeContextError with a user-friendly message on:
      - body not a dict
      - wrong type on any field
      - text field over the 200-char cap
      - target_length_seconds out of [30, 7200]
      - bool sneaking in where int is expected

    The returned dict always carries the three canonical keys with
    None-or-value, so callers can write it straight into the JSONB
    column without further normalization.
    """
    if not isinstance(body, dict):
        raise IntakeContextError("Body must be a JSON object")

    return {
        "topic": _norm_text(body.get("topic"), "topic"),
        "audience": _norm_text(body.get("audience"), "audience"),
        "target_length_seconds": _norm_seconds(
            body.get("target_length_seconds"),
        ),
    }


def snapshot_intake_context(session_id: str) -> Optional[dict[str, Any]]:
    """Read the persisted intake_context AT ENQUEUE TIME.

    The pattern matches the spec's anti-drift contract: snapshot
    when the audit / snippet job is queued, NOT when it's picked
    up. A user editing the form between submit and job pickup
    can't change what the job sees, because the job carries the
    snapshot in its payload.

    Returns the canonical 3-key dict (each value is None or
    populated) or None when the column is unset / row missing /
    DB hiccup. ``None`` means "use defaults" — consumers fall
    through to pre-task-9 behaviour on every None path.

    Consumers should write::

        ctx = (job_payload.get("intake_context") or {})
        topic          = ctx.get("topic")
        audience       = ctx.get("audience")
        target_seconds = ctx.get("target_length_seconds")
        # Every None path == legacy default == in-flight jobs unaffected.
    """
    from services.db import db

    raw = db.get_session_intake_context(session_id)
    if not raw:
        return None
    # Return the canonical 3-key shape so consumers don't have to
    # defensively re-check whether the JSONB blob carries extra
    # keys (an admin tool could in theory write any JSON; the read
    # path normalizes back to the contract).
    return {key: raw.get(key) for key in _FIELDS}
