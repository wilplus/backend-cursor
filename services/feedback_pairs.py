"""The pairs (founder 2026-09-30, C2 and C5; build plan P2-1).

One rule, one place: a (draft, final) pair is recorded only when a model's
draft was SHOWN to the coach and the coach's final DIFFERS from it. The row
is stamped with its surface, the draft's model version, the pattern and the
moment; the coach is its author; `owner_user_id` names whose passage the
words are about, for the consent door later (L1 of the learning page).

Three surfaces, and they never mix: the praise line, the clearer version,
the exercise script. The exercise lane records two finals per version, the
coach's text and the video's transcript.

NEVER FROM AN OWNER'S ANSWER (L3): only coach routes call `record_pair`,
and `coach_id` is required. Nothing here is a score, and no row reaches a
speaker. Each recorded pair is also mirrored, best-effort, into the
annotation ledger the dark export reads, under the same surface name, so a
release authorised later finds them where the exporter looks.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

_log = logging.getLogger(__name__)

SURFACES = ("praise_line", "clearer_version", "exercise_script")
FINAL_KINDS = ("final", "transcript")
_WS = re.compile(r"\s+")


def normalised(text: Any) -> str:
    """Whitespace-collapsed, stripped; the comparison the rule uses."""
    return _WS.sub(" ", text).strip() if isinstance(text, str) else ""


def differs(draft: Any, final: Any) -> bool:
    """True when both are words and the final is not the draft."""
    a, b = normalised(draft), normalised(final)
    return bool(a) and bool(b) and a != b


def record_pair(
    database: Any, *, surface: str, draft: Any, final: Any, coach_id: Any,
    model_version: Optional[str] = None, pattern_key: Optional[str] = None,
    owner_user_id: Optional[str] = None, take_session_id: Optional[str] = None,
    snippet_id: Optional[str] = None, request_id: Optional[str] = None,
    exercise_id: Optional[str] = None, exercise_version: Optional[int] = None,
    final_kind: str = "final",
) -> Optional[dict]:
    """The one write. None when the rule says no row, or the write failed:
    a pair that is not recorded never breaks the answer it rode on."""
    if surface not in SURFACES or final_kind not in FINAL_KINDS:
        return None
    coach = str(coach_id or "").strip()
    if not coach or not differs(draft, final):
        return None
    if not request_id and not exercise_id:
        return None
    writer = getattr(database, "insert_feedback_pair", None)
    if writer is None:
        return None
    try:
        row = writer(
            surface=surface, draft_text=str(draft).strip(),
            final_text=str(final).strip(), final_kind=final_kind,
            draft_model_version=model_version or None,
            pattern_key=pattern_key or None, coach_id=coach,
            owner_user_id=owner_user_id or None,
            take_session_id=take_session_id or None,
            snippet_id=snippet_id or None, request_id=request_id or None,
            exercise_id=exercise_id or None,
            exercise_version=int(exercise_version) if exercise_version else None,
        )
    except Exception as e:  # noqa: BLE001 -- the answer stands
        _log.warning("feedback pair not recorded surface=%s: %s", surface, e,
                     exc_info=True)
        return None
    if isinstance(row, dict):
        _mirror(database, row, coach)
        return row
    return None


def _mirror(database: Any, row: dict, coach: str) -> None:
    """The dark export's ledger, same surface name, best-effort."""
    mirror = getattr(database, "create_admin_annotation_event", None)
    if mirror is None:
        return
    try:
        mirror(
            user_id=str(row.get("owner_user_id") or coach),
            session_id=row.get("take_session_id"),
            section_type="coach_answer",
            field_name=str(row.get("surface")),
            ai_original_text=row.get("draft_text"),
            coach_final_text=row.get("final_text"),
            reason_chip=None, custom_reason=None, created_by=coach,
        )
    except Exception as e:  # noqa: BLE001 -- the pair row is the record
        _log.info("feedback pair mirror skipped: %s", e)


def counts(database: Any) -> dict:
    """Per surface: how many pairs exist and how many await export.
    Every surface is named, at zero when nothing was written."""
    reader = getattr(database, "count_feedback_pairs", None)
    raw: dict = {}
    if reader is not None:
        try:
            raw = reader() or {}
        except Exception as e:  # noqa: BLE001 -- a count, not a fault
            _log.warning("feedback pair count failed: %s", e, exc_info=True)
            raw = {}
    out = {}
    for surface in SURFACES:
        entry = raw.get(surface) if isinstance(raw, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        out[surface] = {
            "total": int(entry.get("total") or 0),
            "unexported": int(entry.get("unexported") or 0),
        }
    return out
