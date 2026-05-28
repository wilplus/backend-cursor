"""Shared utilities for the backend."""
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now_iso() -> str:
    """Return the current UTC time as a Z-suffixed ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def render_admin_dont_ask_block(notes: Optional[str]) -> Optional[str]:
    """Render ``user_settings.private_admin_notes`` as a prompt block, or None.

    Used by every chat-LLM prompt builder so the admin's private
    notes about a user influence what the model will and won't
    surface. The wording covers both interview-style endpoints
    (where the LLM ASKS questions) and Q&A endpoints (where the
    LLM ANSWERS) — "asking about or surfacing" plus "never quote,
    repeat, or reference" instructs the model in both directions.

    Whitespace-only is treated as empty so an admin clearing the
    field doesn't leave a sentinel-but-vacuous block in the prompt.

    Returns the addendum string (no trailing newline; callers add
    spacing) or ``None`` when there's nothing to inject.
    """
    if not notes:
        return None
    text = notes.strip()
    if not text:
        return None
    return (
        "[ADMIN-PRIVATE CONTEXT — DO NOT ECHO OR REFERENCE]\n"
        "The user's coach has flagged the following as topics to "
        "AVOID asking about or surfacing in your response. Treat "
        "this as background to navigate around silently — never "
        "quote, repeat, or reference these notes to the user, and "
        "never generate questions or answers that touch on them.\n"
        "---\n"
        f"{text}\n"
        "---"
    )


def score_01_from_recording_row(rec: Any) -> Optional[float]:
    """Read 0..1 score from recordings.performance_metrics_v2.scoring_debug (set by recording_1/2 job)."""
    if not isinstance(rec, dict):
        return None
    pm = rec.get("performance_metrics_v2")
    if not isinstance(pm, dict):
        return None
    dbg = pm.get("scoring_debug")
    if not isinstance(dbg, dict):
        return None
    for key in ("score_01", "final_score_01"):
        v = dbg.get(key)
        if v is None:
            continue
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            continue
    return None
