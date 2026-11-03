"""A person's profile, as on WhatsApp (founder, the Claude Code chat, 3
November 2026; N366, locked in docs/LOCKS.md with the prototype "One bar").
Table: people_profiles (migration a_person_has_a_profile).

  * ``mine``: your own profile: your name (yours if you set one, else the
    account's), who you are, your About, whether you have a photo, and the
    photos and files you sent in any chat.
  * ``save_mine``: change your name, who you are or your About. A new name
    is also the name the people you chat with see (``chat_members``).
  * ``set_photo`` / ``drop_photo`` / ``my_photo``: your circle.
  * ``theirs``: the profile of the other person in one of your chats, with
    the photos and files the two of you shared there; ``their_photo``.

Ring row ``chats``, ring 6, as the chats: anyone else gets 404. No provider
call and no recording, so nothing here passes the processing-authorization
path. Deleted with the account: the purge registry takes the row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.chat_links import name_of
from services.chats import (
    MEMBERS, MESSAGES, PHOTO_TYPES, ChatsError, _bytes, _not_found, _require, _rows,
    _table, member,
)

PROFILES = "people_profiles"
LIMITS = {"name": 40, "role": 60, "about": 300}
MAX_PHOTO_BYTES = 5 * 1024 * 1024


def _row(database: Any, user_id: str, fields: str = "name,role,about,about_edited_at,photo_type") -> Optional[dict]:
    rows = _rows(_table(database, PROFILES).select(fields).eq("user_id", user_id).limit(1))
    return rows[0] if rows else None


def _write(database: Any, user_id: str, change: dict) -> None:
    """Change the person's row, making it the first time."""
    if _row(database, user_id, "name"):
        _table(database, PROFILES).update(change).eq("user_id", user_id).execute()
    else:
        _table(database, PROFILES).insert({"user_id": user_id, **change}).execute()


def _shown(row: Optional[dict], name: str, role: Optional[str]) -> dict:
    row = row or {}
    return {"name": row.get("name") or name, "role": row.get("role") or role,
            "about": row.get("about"), "about_edited_at": row.get("about_edited_at"),
            "has_photo": bool(row.get("photo_type"))}


def _shared(database: Any, member_ids: list[str], thread_ids: list[str]) -> dict:
    """The photos and files in these chats, sent by these members (all of
    them when ``member_ids`` is empty), newest first."""
    if not thread_ids:
        return {"photos": [], "files": []}
    query = (_table(database, MESSAGES).select("id,thread_id,kind,body,created_at,author_member_id")
             .in_("thread_id", thread_ids).in_("kind", ["photo", "file"]))
    if member_ids:
        query = query.in_("author_member_id", member_ids)
    rows = _rows(query.order("created_at", desc=True).limit(200))
    pick = lambda kind: [{"id": r["id"], "chat_id": r["thread_id"], "name": r.get("body") or "",  # noqa: E731
                          "created_at": r["created_at"]} for r in rows if r["kind"] == kind]
    return {"photos": pick("photo"), "files": pick("file")}


def mine(database: Any, user_id: Any, token_payload: Any) -> dict:
    """GET /v2/profile: {name, role, about, about_edited_at, has_photo,
    photos, files}."""
    user_id = _require(database, user_id)
    memberships = _rows(_table(database, MEMBERS).select("id,thread_id").eq("user_id", user_id))
    out = _shown(_row(database, user_id), _full_name(token_payload), None)
    out.update(_shared(database, [str(m["id"]) for m in memberships],
                       [str(m["thread_id"]) for m in memberships]))
    return out


def _full_name(token_payload: Any) -> str:
    """The account's whole name; else name_of's first word, email or WillpowerLab."""
    payload: dict = token_payload if isinstance(token_payload, dict) else {}
    raw = payload.get("user_metadata")
    meta: dict = raw if isinstance(raw, dict) else {}
    name = " ".join(str(meta.get("full_name") or meta.get("name") or "").split())
    return name[:LIMITS["name"]] or name_of(payload)


def save_mine(database: Any, user_id: Any, token_payload: Any, body: Any) -> dict:
    """PATCH /v2/profile {name?, role?, about?}: each trimmed; an empty role
    or About clears it, an empty name is refused; over its limit is 400."""
    user_id = _require(database, user_id)
    body = body if isinstance(body, dict) else {}
    change: dict[str, Any] = {}
    for key, most in LIMITS.items():
        if key not in body:
            continue
        value = " ".join(str(body.get(key) or "").split()) if key != "about" else str(body.get(key) or "").strip()
        if len(value) > most:
            raise ChatsError("NOT_ALLOWED", f"At most {most} characters.")
        if key == "name" and not value:
            raise ChatsError("NOT_ALLOWED", "A name is needed.")
        change[key] = value or None
    if not change:
        return mine(database, user_id, token_payload)
    now = datetime.now(timezone.utc).isoformat()
    if "about" in change:
        change["about_edited_at"] = now
    change["updated_at"] = now
    _write(database, user_id, change)
    if change.get("name"):
        # The name the people you chat with see.
        _table(database, MEMBERS).update({"display_name": change["name"]}).eq("user_id", user_id).execute()
    return mine(database, user_id, token_payload)


def set_photo(database: Any, user_id: Any, data: bytes, content_type: Any) -> dict:
    """PUT /v2/profile/photo: a photo (one of PHOTO_TYPES, up to 5 MB)."""
    user_id = _require(database, user_id)
    kind = str(content_type or "").split(";")[0].strip().lower()
    if kind not in PHOTO_TYPES or not data:
        raise ChatsError("NOT_ALLOWED", "Only a photo.")
    if len(data) > MAX_PHOTO_BYTES:
        raise ChatsError("TOO_LARGE", "A photo is at most 5 MB.", 413)
    _write(database, user_id, {"photo": "\\x" + data.hex(), "photo_type": kind,
                               "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"has_photo": True}


def drop_photo(database: Any, user_id: Any) -> dict:
    """DELETE /v2/profile/photo."""
    user_id = _require(database, user_id)
    _table(database, PROFILES).update({"photo": None, "photo_type": None}).eq("user_id", user_id).execute()
    return {"has_photo": False}


def _photo(database: Any, user_id: str) -> dict:
    row = _row(database, user_id, "photo,photo_type") or {}
    data = _bytes(row.get("photo"))
    if not data or row.get("photo_type") not in PHOTO_TYPES:
        raise _not_found()
    return {"content_type": row["photo_type"], "data": data}


def my_photo(database: Any, user_id: Any) -> dict:
    """GET /v2/profile/photo: your photo, or 404."""
    return _photo(database, _require(database, user_id))


def _other(database: Any, user_id: Any, thread_id: Any) -> dict:
    """The other person in a chat of yours: their membership row; else 404."""
    me = member(database, user_id, thread_id)
    rows = [r for r in _rows(_table(database, MEMBERS).select("id,user_id,display_name,subtitle")
                             .eq("thread_id", str(me["thread_id"])))
            if str(r["id"]) != str(me["id"]) and r.get("user_id")]
    if not rows:
        raise _not_found()
    return {**rows[0], "thread_id": str(me["thread_id"])}


def theirs(database: Any, user_id: Any, thread_id: Any) -> dict:
    """GET /v2/chats/<id>/profile: the other person's profile, with the
    photos and files the two of you shared in this chat."""
    other = _other(database, user_id, thread_id)
    out = _shown(_row(database, str(other["user_id"])), other.get("display_name") or "",
                 other.get("subtitle"))
    out.update(_shared(database, [], [other["thread_id"]]))
    return out


def their_photo(database: Any, user_id: Any, thread_id: Any) -> dict:
    """GET /v2/chats/<id>/profile/photo: the other person's photo, or 404."""
    return _photo(database, str(_other(database, user_id, thread_id)["user_id"]))

