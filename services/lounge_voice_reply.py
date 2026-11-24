"""Private audio and delivery analysis for a sent chat recording."""
from hashlib import sha256

from services.chats import _bytes
from services.refusal import Refusal
from utils.ids import is_uuid

TABLE = "lounge_voice_replies"
MAX_BYTES = 4 * 1024 * 1024
MIMES = {"audio/webm", "audio/mp4", "audio/ogg", "audio/wav"}


def _message(database, user: str, turn: str) -> dict:
    row = database.get_lounge_message_by_client_id(user, turn) if is_uuid(turn) else None
    if (not row or row.get("chat_erased") or row.get("role") != "user"
            or (row.get("metadata") or {}).get("voice_clip") is not True):
        raise Refusal("NOT_FOUND", "Recording not found.", 404)
    return row


def _attachment(database, key: str, fields: str) -> dict | None:
    rows = (database.client.table(TABLE).select(fields).eq("message_id", key)
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def _scope(row: dict, user: str, turn: str) -> dict:
    meta = row.get("metadata") or {}
    focus = meta.get("review_focus")
    return {
        "user": user, "turn": turn, "project": meta.get("arc_id"),
        "take": meta.get("take_session_id"), "snippet": focus.get("snippet_id") if isinstance(focus, dict) else None,
    }


def save(database, user: str, turn: str, raw: bytes, content_type: str, receipt: str) -> dict:
    from services.chat_voice_attempt import analyze, receipt_payload

    if not raw or len(raw) > MAX_BYTES or content_type not in MIMES:
        raise Refusal("INVALID_AUDIO", "This recording could not be attached.", 422)
    row = _message(database, user, turn)
    digest = sha256(raw).hexdigest()
    existing = _attachment(database, row["id"], "sha256")
    if existing:
        if existing["sha256"] != digest:
            raise Refusal("RECORDING_CHANGED", "A different recording is already attached.", 409)
        return {"attached": True}
    payload = receipt_payload(receipt)
    if (not payload or payload.get("audio_hash") != digest
            or any(payload.get(key) != value for key, value in _scope(row, user, turn).items())):
        raise Refusal("VOICE_RECEIPT_INVALID", "This recording could not be verified.", 422)
    created = (database.client.table(TABLE).upsert({
        "message_id": row["id"], "content_type": content_type,
        "audio": "\\x" + raw.hex(), "sha256": digest,
        "analysis": analyze(database, user, raw, payload),
    }, on_conflict="message_id", ignore_duplicates=True).execute().data or [])
    if not created:
        winner = _attachment(database, row["id"], "sha256")
        if not winner or winner.get("sha256") != digest:
            raise Refusal("RECORDING_CHANGED", "A different recording is already attached.", 409)
    return {"attached": True}


def read_analysis(database, user: str, turn: str, project: str | None) -> dict | None:
    """Recheck ownership and chat scope before reading saved delivery evidence."""
    try:
        row = _message(database, user, turn)
    except Refusal:
        return None
    meta = row.get("metadata") or {}
    if meta.get("arc_id") != project or (not project and (meta.get("place") != "speaking" or meta.get("chat"))):
        return None
    stored = _attachment(database, row["id"], "analysis")
    return stored.get("analysis") if stored else None


def read(database, user: str, turn: str) -> tuple[bytes, str]:
    row = _message(database, user, turn)
    clip = _attachment(database, row["id"], "audio,content_type")
    audio = _bytes(clip.get("audio")) if clip else b""
    if not clip or not audio:
        raise Refusal("NOT_FOUND", "Recording not found.", 404)
    return audio, clip["content_type"]
