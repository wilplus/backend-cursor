"""A person's own chats: one kind of chat, decided by use (founder, N700).

Every chat of one's own is the same kind of chat, in one flat list. A chat
becomes what it is used for: recording a Take or adding slides in it gives it
its project (one per chat); asking about oneself keeps it a coaching chat.
The rows live in ``own_chats`` (migration 0535). Messages stay in
``lounge_messages``; a message written in a chat names it in its metadata
(``chat_id``).

Rows written before N700 have no ``chat_id``. They are placed at read time:
a row of a project goes to that project's chat, any other row to the chat
that carries on its old section (``legacy_place``: speaking, principles or
will; ``services.lounge_messages.place_of``). The first list makes those
chats: "Speaking coach" always, one per project, and Principles or Will only
for a person who has rows there.

A bot row written with no chat and no Take (Will's unprompted messages: the
Sunday note, strengths, plan reminders) goes to the chat used last
(``stamp_unplaced``, called where Lounge rows are inserted).

Public API:
  list_chats(database, user_id) -> list[dict]
  create_chat(database, user_id, title=None) -> dict
  rename_chat(database, user_id, chat_id, title) -> Optional[dict]
  touch(database, user_id, chat_id) -> None
  attach_project(database, user_id, chat_id, arc_id) -> Optional[dict]
  owned(database, user_id, chat_id) -> Optional[dict]
  chat_of_row(row, chats) -> Optional[str]
  stamp_unplaced(database, user_id, rows) -> list[dict]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

TABLE = "own_chats"
_COLUMNS = "id,title,arc_id,legacy_place,created_at,last_used_at"
MAX_TITLE = 200
NEW_CHAT = "New chat"
#: The names a carried-on section starts with; the app shows them in the
#: person's language until they are renamed.
SECTION_TITLES = {"speaking": "Speaking coach", "principles": "Principles", "will": "Will"}
#: Rows read to see whether a person has written in a section before N700.
_SCAN_ROWS = 300
_TAKE_KEYS = ("take_session_id", "session_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table(database: Any) -> Any:
    return database.client.table(TABLE)


def _rows(query: Any) -> list[dict]:
    return [row for row in (query.execute().data or []) if isinstance(row, dict)]


def clean_title(title: Any) -> Optional[str]:
    text = " ".join(str(title or "").split())[:MAX_TITLE]
    return text or None


def _read(database: Any, user_id: str) -> list[dict]:
    return _rows(_table(database).select(_COLUMNS).eq("user_id", user_id)
                 .order("last_used_at", desc=True))


def read_chats(database: Any, user_id: Any) -> list[dict]:
    """The person's own chats as they are, without making any (a cheap read
    for labelling a page of messages). [] when none or unreadable."""
    try:
        return _read(database, str(user_id))
    except Exception as error:  # noqa: BLE001 - before migration 0536, or a hiccup
        logger.info("own_chats unread: %s", type(error).__name__)
        return []


def label_page(messages: list[dict], chats: list[dict]) -> None:
    """Each message says the own chat it belongs to (``own_chat_id``), so the
    app shows a chat's messages from the one page it reads. Rows of a Take
    that name only their Take fall to their section's chat. In place."""
    if not chats:
        return
    for message in messages:
        if isinstance(message, dict):
            message["own_chat_id"] = chat_of_row(message, chats)


def _insert(database: Any, row: dict) -> Optional[dict]:
    try:
        made = _rows(_table(database).insert(row))
        return made[0] if made else None
    except Exception as error:  # noqa: BLE001 - a race made it first: read it back
        logger.info("own_chats insert skipped: %s", type(error).__name__)
        return None


def _sections_written(database: Any, user_id: str) -> set[str]:
    from services.lounge_messages import place_of

    reader = getattr(database, "get_lounge_messages_page", None)
    rows = reader(user_id, limit=_SCAN_ROWS) if callable(reader) else []
    return {place_of(row) for row in (rows or []) if isinstance(row, dict)}


def _projects(database: Any, user_id: str) -> list[dict]:
    from services.user_trainings import list_trainings

    return [p for p in (list_trainings(database, user_id, every_project=False) or []) if isinstance(p, dict) and p.get("arc_id")]


def _ensure(database: Any, user_id: str, chats: list[dict]) -> bool:
    """Make the chats rows written before N700 belong to. True when one was made."""
    have_places = {c.get("legacy_place") for c in chats if c.get("legacy_place")}
    have_arcs = {str(c.get("arc_id")) for c in chats if c.get("arc_id")}
    made = False
    places = {"speaking"} | (_sections_written(database, user_id) if not have_places else set())
    for place in sorted(places - have_places):
        if place in SECTION_TITLES:
            made |= _insert(database, {"user_id": user_id, "title": SECTION_TITLES[place],
                                       "legacy_place": place}) is not None
    for project in _projects(database, user_id):
        arc = str(project["arc_id"])
        if arc not in have_arcs:
            title = clean_title(project.get("topic")) or NEW_CHAT
            made |= _insert(database, {"user_id": user_id, "title": title, "arc_id": arc,
                                       "last_used_at": project.get("last_take_at") or _now()}) is not None
    return made


def list_chats(database: Any, user_id: Any) -> list[dict]:
    """The person's own chats, the newest used first."""
    user = str(user_id)
    chats = _read(database, user)
    try:
        if _ensure(database, user, chats):
            chats = _read(database, user)
    except Exception as error:  # noqa: BLE001 - the list stands without the carried-on chats
        logger.warning("own_chats ensure failed: %s", type(error).__name__)
    return chats


def create_chat(database: Any, user_id: Any, title: Any = None) -> Optional[dict]:
    return _insert(database, {"user_id": str(user_id), "title": clean_title(title) or NEW_CHAT})


def owned(database: Any, user_id: Any, chat_id: Any) -> Optional[dict]:
    if not chat_id:
        return None
    rows = _rows(_table(database).select(_COLUMNS).eq("user_id", str(user_id)).eq("id", str(chat_id)))
    return rows[0] if rows else None


def rename_chat(database: Any, user_id: Any, chat_id: Any, title: Any) -> Optional[dict]:
    clean = clean_title(title)
    if not clean or not owned(database, user_id, chat_id):
        return None
    rows = _rows(_table(database).update({"title": clean})
                 .eq("user_id", str(user_id)).eq("id", str(chat_id)))
    return rows[0] if rows else None


def touch(database: Any, user_id: Any, chat_id: Any) -> None:
    """The chat was used now: Will's next unprompted message goes there."""
    if not chat_id:
        return
    try:
        (_table(database).update({"last_used_at": _now()})
         .eq("user_id", str(user_id)).eq("id", str(chat_id)).execute())
    except Exception as error:  # noqa: BLE001 - only the order of the list waits on it
        logger.info("own_chats touch failed: %s", type(error).__name__)


def attach_project(database: Any, user_id: Any, chat_id: Any, arc_id: Any) -> Optional[dict]:
    """The chat's first Take or slides give it its project (one per chat). A
    chat that has one keeps it."""
    chat = owned(database, user_id, chat_id)
    if not chat or not arc_id:
        return None
    if chat.get("arc_id"):
        return chat
    try:
        rows = _rows(_table(database).update({"arc_id": str(arc_id)})
                     .eq("user_id", str(user_id)).eq("id", str(chat_id)).is_("arc_id", "null"))
    except Exception as error:  # noqa: BLE001 - another chat holds this project (one per project)
        logger.info("own_chats attach refused: %s", type(error).__name__)
        return None
    return rows[0] if rows else owned(database, user_id, chat_id)


def last_used(database: Any, user_id: Any) -> Optional[str]:
    rows = _rows(_table(database).select("id").eq("user_id", str(user_id))
                 .order("last_used_at", desc=True).limit(1))
    return str(rows[0]["id"]) if rows else None


def _meta(row: dict) -> dict:
    meta = row.get("metadata")
    return meta if isinstance(meta, dict) else {}


def take_projects(database: Any, user_id: Any) -> dict[str, str]:
    """{take session id: project id} for the person's Takes, for rows that
    name only their Take."""
    out: dict[str, str] = {}
    for project in _projects(database, str(user_id)):
        for take in project.get("takes") or []:
            if isinstance(take, dict) and take.get("session_id"):
                out[str(take["session_id"])] = str(project["arc_id"])
    return out


def chat_of_row(row: dict, chats: Iterable[dict],
                take_arcs: Optional[dict[str, str]] = None) -> Optional[str]:
    """The own chat a Lounge row belongs to: the one it names, else (a row
    written before N700) its project's chat, else its section's chat. Pure."""
    from services.lounge_messages import place_of

    listed = list(chats)
    meta = _meta(row)
    named = str(meta.get("chat_id") or "")
    ids = {str(c.get("id")) for c in listed}
    if named:
        return named if named in ids else None
    take = next((str(meta[key]) for key in _TAKE_KEYS if meta.get(key)), "")
    arc = str(meta.get("arc_id") or (take_arcs or {}).get(take) or "")
    if arc:
        for chat in listed:
            if str(chat.get("arc_id") or "") == arc:
                return str(chat["id"])
    place = place_of(row)
    for chat in listed:
        if chat.get("legacy_place") == place:
            return str(chat["id"])
    return None


def _unplaced(row: dict) -> bool:
    meta = _meta(row)
    return (row.get("role") != "user" and not meta.get("chat_id") and not meta.get("arc_id")
            and not any(meta.get(key) for key in _TAKE_KEYS))


def stamp_unplaced(database: Any, user_id: Any, rows: list[dict]) -> list[dict]:
    """Will's rows written with no chat and no Take go to the chat used last
    (N700 item 5). Rows of a Take keep going to their project's chat."""
    if not user_id or not any(_unplaced(row) for row in rows):
        return rows
    try:
        chat = last_used(database, user_id)
    except Exception as error:  # noqa: BLE001 - unstamped rows are still placed by section
        logger.info("own_chats last_used unread: %s", type(error).__name__)
        return rows
    if not chat:
        return rows
    out = []
    for row in rows:
        if _unplaced(row):
            row = {**row, "metadata": {**_meta(row), "chat_id": chat}}
        out.append(row)
    return out
