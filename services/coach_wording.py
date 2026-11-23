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
    "When recommending a change to what the speaker says or how they deliver it, show one exact "
    "short line they can say aloud, in a separate wording object: {words, delivery, source}. "
    "Write the example in the speaker's language. Keep their facts, level of certainty, "
    "audience and intended action. Use only their words "
    "or a proposed phrasing supported by the exchange. Keep the answer brief and leave the "
    "full example in wording.words. Put an optional concrete delivery direction in wording.delivery "
    "(for example a pause before the deadline). Use natural punctuation in wording.words to show "
    "a pause when it helps them say the line. If audio is missing, state what you can tell from "
    "the words and demonstrate a way to say that exact line. Do not claim how the original sounded. "
    "When comparing recordings, make the example for the recording the speaker can improve "
    "and name that talk in the reply. "
    "When the audience is known but their intended action would change the line, ask once for "
    "that action. For discussion needing no example, return null for wording."
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
