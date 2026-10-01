"""Bold voices and the once-per-Take steps (founder 2026-10-01; Phase 3 of
the after-practice paths), dark behind ``Config.PRAISE_AFTER_PRACTICE_ENABLED``.

After the first practice that lands, the speaker may hear bold voices: their
own landed attempt first, then a coach's model readings
(``services.coach_readings``, published ones, never the coach's name).
Others' shared clips and the licensed corpus wait for Phase 4 and counsel
(C2, F4). Plays only: nothing is judged, nothing is counted at the speaker,
and a "heard" receipt is kept per play (migration 0409).

Each after-practice step is shown at most once per Take, tracked
separately: the bridge and Lend your ear (Phase 4) at the first practice
that lands, Bold voices at the first practice ending, landed or not. The
speaker's screens are the designer session's; this is their data.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

STEPS = ("bridge", "lend_your_ear", "bold_voices")
CLIP_KINDS = ("own_attempt", "coach_reading")


def _enabled() -> bool:
    from services.after_practice import praise_after_practice_enabled
    return praise_after_practice_enabled()


def _owned_take(database: Any, take_session_id: str, owner_user_id: str) -> Any:
    session = database.v2_get_session_by_id(str(take_session_id)) or None
    if not session or str(session.get("user_id")) != str(owner_user_id):
        return None
    return session


def bold_voices_for_take(database: Any, *, take_session_id: str,
                         owner_user_id: str) -> tuple[int, dict]:
    """(status, payload): the speaker's own landed attempts on this Take,
    the published coach readings (no names), and which steps this Take has
    shown. 404 while the switch is off or the Take is not theirs."""
    from services.audio_ref_resolver import resolve_playable_ref
    if not _enabled() or _owned_take(database, take_session_id, owner_user_id) is None:
        return 404, {"code": "NOT_FOUND", "error": "Take not found"}
    own = []
    for practice in database.list_landed_practices_for_take(
            str(take_session_id), str(owner_user_id)) or []:
        landed = next((a for a in database.list_confident_voice_practice_attempts(
            str(practice.get("id"))) or []
            if str(a.get("id")) == str(practice.get("selected_attempt_id"))), None)
        if not isinstance(landed, dict):
            continue
        own.append({
            "clip_id": str(landed.get("id")),
            "practice_id": str(practice.get("id")),
            "passage": practice.get("exact_passage") or "",
            "audio_ref": resolve_playable_ref(landed.get("audio_ref")),
            "duration_ms": landed.get("duration_ms"),
        })
    readings = [{
        "clip_id": str(row.get("id")),
        "passage": row.get("passage") or "",
        "media_url": row.get("media_url"),
        "media_kind": row.get("media_kind") or "audio",
    } for row in database.list_published_coach_readings() or []
        if isinstance(row, dict) and row.get("media_url")]
    shown = {str(row.get("step")): row.get("shown_at")
             for row in database.list_after_practice_steps(str(take_session_id)) or []
             if isinstance(row, dict) and row.get("step") in STEPS}
    # Phase 4 (F4): others' shared clips the quorum settled Yes and the
    # licensed corpus a coach labelled Yes; [] until the peer lane opens.
    from services.lend_your_ear import others_for_bold_voices
    others = others_for_bold_voices(database, listener_id=str(owner_user_id))
    return 200, {"own": own, "coach_readings": readings, "others": others,
                 "steps_shown": shown}


def mark_step(database: Any, *, take_session_id: str, owner_user_id: str,
              body: Any) -> tuple[int, dict]:
    """The Take showed this step; once per Take, however often it arrives.
    {"recorded": True} the first time, False after."""
    fields: dict = body if isinstance(body, dict) else {}
    step = fields.get("step")
    if step not in STEPS:
        return 400, {"code": "INVALID_INPUT", "error": "step is not one of the three"}
    if not _enabled() or _owned_take(database, take_session_id, owner_user_id) is None:
        return 404, {"code": "NOT_FOUND", "error": "Take not found"}
    first = database.mark_after_practice_step(
        owner_user_id=str(owner_user_id), take_session_id=str(take_session_id),
        step=str(step))
    return 200, {"recorded": bool(first)}


def after_practice_counts(database: Any, *, since: str) -> dict:
    """Counts for the founder's ledger (never a speaker-facing number)."""
    return {"since": since, **(database.count_after_practice(since) or {})}


def record_heard(database: Any, *, take_session_id: str, owner_user_id: str,
                 body: Any) -> tuple[int, dict]:
    """The speaker heard a clip: a receipt, nothing judged."""
    fields: dict = body if isinstance(body, dict) else {}
    kind, clip_id = fields.get("clip_kind"), fields.get("clip_id")
    if kind not in CLIP_KINDS or not isinstance(clip_id, str) or not clip_id.strip():
        return 400, {"code": "INVALID_INPUT", "error": "clip_kind and clip_id are required"}
    if not _enabled() or _owned_take(database, take_session_id, owner_user_id) is None:
        return 404, {"code": "NOT_FOUND", "error": "Take not found"}
    database.record_bold_voices_play(
        owner_user_id=str(owner_user_id), take_session_id=str(take_session_id),
        clip_kind=str(kind), clip_id=clip_id.strip())
    return 200, {"recorded": True}
