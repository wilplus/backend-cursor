"""Speakable lines offered in chat and saved by the project owner."""
from __future__ import annotations

import re
import uuid
from typing import Any

META = "coach_wording"
SAVED = "coach_wording_saved"
_NAMESPACE = uuid.UUID("68d52323-d7ec-43e8-9310-b2e059b128bb")
_UNSAFE = re.compile(r"https?://|www\.|[\x00-\x08\x0b-\x1f]|\b(?:wpm|willfidence)\b", re.I)

# The same rule is used by both coaching entry points.
WORDING_RULES = (
    "When giving a rewrite or demonstrating delivery, put one short line the speaker could "
    "actually say in wording.words, using their language. Put the line itself there, without "
    "an introduction or surrounding quotes. Keep the chat answer conversational and show "
    "the full example only in the wording card. Preserve the facts, the intended audience "
    "and action, and any real conditions on that action. For a hesitant recommendation, "
    "lead with the recommendation and remove filler such as 'I think we could maybe'. "
    "'I recommend we review the draft' is a direct proposal, with no new commitment. "
    "For a request, ask the audience plainly in the words they would actually use. "
    "When showing how to deliver a line, include one specific, audible move in wording.delivery: "
    "a pause at a named point or emphasis on an exact word. 'Say it confidently' and 'use a firm "
    "tone' do not show what to do. If the original audio is unavailable and the speaker asks how "
    "they sounded, say what their words show and leave the original delivery open. Give the "
    "exact line and a concrete cue they can try when they say it again. "
    "When comparing recordings, name the talk you would change and write the line for that talk. "
    "If they request a rewrite that depends on a missing action, ask what they need the audience "
    "to do. Return null for wording on turns that need no example."
)


def _line(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or _UNSAFE.search(value):
        return None
    value = " ".join(value.split())
    return value if 0 < len(value) <= limit else None


def proposal(value: Any, *, arc_id: str = "", take_id: str = "") -> dict | None:
    """The model writes words. Only the caller supplies verified project and Take IDs."""
    if not isinstance(value, dict) or not (words := _line(value.get("words"), 320)):
        return None
    result = {"words": words}
    if delivery := _line(value.get("delivery"), 180):
        result["delivery"] = delivery
    if arc_id and take_id:
        result.update(arc_id=arc_id, take_session_id=take_id)
    return result


def _sources_in_force(database: Any, user: str, arc: str, sessions: list[dict], take_ids: set[str]) -> set[str]:
    from services.project_deletion import ProjectDeletionService
    from services.speaker_lookup import _takes_in_force

    visibility = ProjectDeletionService(database)
    if arc in visibility.erased_projects([arc]) or arc in visibility.archived_projects([arc]):
        return set()
    owned = [s for s in sessions if str(s.get("id") or "") in take_ids and str(s.get("user_id") or "") == user
             and str(s.get("arc_id") or arc) == arc and not s.get("deleted_at") and not s.get("archived_at")]
    return _takes_in_force(database, owned) if owned else set()


def read(database: Any, user: str, arc: str, sessions: list[dict]) -> list[dict]:
    rows = database.get_saved_coach_wording(user, arc) or []
    if not rows:
        return []
    source_ids = {str((row.get("metadata") or {}).get("take_session_id") or "") for row in rows}
    eligible = _sources_in_force(database, user, arc, sessions, source_ids)
    items = []
    for row in rows:
        meta = row.get("metadata") or {}
        raw = meta.get(META) or {}
        take = meta.get("take_session_id")
        if take in eligible and meta.get("arc_id") == arc:
            wording = proposal(raw, arc_id=arc, take_id=take)
            if wording:
                items.append({**wording, "reply_id": meta.get("wording_reply_id")})
    return items


def save(database: Any, user: str, arc: str, sessions: list[dict], reply_id: str) -> tuple[dict, int]:
    from services.lounge_messages import stamp_after

    row = database.get_lounge_message_by_client_id(user, reply_id) or {}
    metadata = row.get("metadata") or {}
    raw = metadata.get(META)
    # Only a displayed bot reply can be saved. Its validated scope is separate
    # from the conversation scope: a general coach reply can save into a project.
    if row.get("role") != "bot" or row.get("chat_erased") or not isinstance(raw, dict):
        return {"code": "NOT_FOUND"}, 404
    take = str(raw.get("take_session_id") or "")
    if raw.get("arc_id") != arc or take not in _sources_in_force(database, user, arc, sessions, {take}):
        return {"code": "NOT_FOUND"}, 404
    wording = proposal(raw, arc_id=arc, take_id=take)
    if not wording:
        return {"code": "NOT_FOUND"}, 404
    client_id = str(uuid.uuid5(_NAMESPACE, f"{user}:{arc}:{reply_id}"))
    stored = database.insert_lounge_messages(user, [{
        "client_id": client_id, "role": "system", "kind": "text",
        "body": wording["words"], "client_created_at": stamp_after(row.get("client_created_at")),
        "metadata": {"arc_id": arc, "take_session_id": take, "place": "speaking",
                     SAVED: True, META: wording, "wording_reply_id": reply_id},
    }])
    if not stored:
        return {"code": "COACH_WORDING_SAVE_FAILED"}, 503
    return {"wording": {**wording, "reply_id": reply_id}}, 200
