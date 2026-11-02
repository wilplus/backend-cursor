"""The chats between people, first slice (founder, the Claude Code chat, 31
October 2026, N298 to N316; prototype: the Ember & Air one kept with N298).
Tables: chat_threads, chat_members, chat_messages (migration
people_chat_with_each_other).

A chat is between two people (N302 item 1): a person and a colleague
(``team``) or a person and a customer (``customer``). The other member may be
a guest with no account (a customer, a demo person). Separate from the
Lounge, the chat with Will (lounge_messages), which this module never reads
or writes.

  * ``list_chats``: the chats a person is in, each named for the other member
    (their name as the title, their line as the subtitle), with its last
    message; the newest first.
  * ``read``: a chat's messages, oldest first, each marked ``mine`` for the
    caller. Only for a member.
  * ``post``: an emoji, one of the three with one meaning each (N311 item 1):
    👍 it's good, 👀 seen, I'll answer, 🙏 thanks. Its meaning is kept as a
    clean label in ``meta``. Nothing else yet: the recording comes later.
  * ``seed_demo``: a customer's chat and a colleague's for the person, once,
    so the chats can be seen before anyone else is in them.

Ring row ``chats``, ring 6 (the founder's). A person without it gets 404 from
every route. No model or provider call here, so nothing in this module goes
through the processing-authorization path. Deleted with the account: the
purge registry takes a person's memberships and their demo chats, and the
messages go with them.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

FEATURE = "chats"
THREADS, MEMBERS, MESSAGES = "chat_threads", "chat_members", "chat_messages"
#: The three emoji and the label each one means (N311 item 1).
EMOJI = {"👍": "good", "👀": "seen", "🙏": "thanks"}
#: The demo chats (founder only, ring 6): the guest, their line, and what
#: they said, in order.
DEMO = (
    {"kind": "customer", "name": "Sarah", "subtitle": "Customer · Invita",
     "said": [("text", "Itchy for two months, thinning at the top. I wash "
                       "every day. What should I do?")]},
    {"kind": "team", "name": "Ariel", "subtitle": "Your colleague · Invita",
     "said": [("text", "On slide 1: name the treatment and let it land."),
              ("emoji", "👍")]},
)
#: How the signed-in person is named in a demo chat (seen only by the
#: other member, who is a demo guest).
_YOU = "You"
_MAX_CHATS = 50
_MAX_MESSAGES = 500
_UNIQUE_VIOLATION = "23505"


class ChatsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _not_found() -> ChatsError:
    return ChatsError("NOT_FOUND", "Not found.", 404)


def enabled(database: Any, user_id: Any) -> bool:
    """Does this person have the chats? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)


def _require(database: Any, user_id: Any) -> str:
    if not enabled(database, user_id):
        raise _not_found()
    return str(user_id)


def _uuid(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _table(database: Any, name: str) -> Any:
    return database.client.table(name)


def _rows(query: Any) -> list[dict]:
    return list(query.execute().data or [])


# ── Reading ──────────────────────────────────────────────────────────────

def _memberships(database: Any, user_id: str) -> list[dict]:
    return _rows(_table(database, MEMBERS).select("id,thread_id")
                 .eq("user_id", user_id).order("created_at", desc=True).limit(_MAX_CHATS))


def _member_of(database: Any, user_id: str, thread_id: Any) -> dict:
    """The caller's membership of a chat, or 404 (a chat that is not theirs
    and a chat that does not exist answer the same)."""
    thread = _uuid(thread_id)
    if not thread:
        raise _not_found()
    rows = _rows(_table(database, MEMBERS).select("id,thread_id")
                 .eq("thread_id", thread).eq("user_id", user_id).limit(1))
    if not rows:
        raise _not_found()
    return rows[0]


def _last(database: Any, thread_id: str) -> Optional[dict]:
    rows = _rows(_table(database, MESSAGES).select("kind,body,created_at")
                 .eq("thread_id", thread_id).order("created_at", desc=True).limit(1))
    if not rows:
        return None
    return {"kind": rows[0]["kind"], "body": rows[0]["body"],
            "created_at": rows[0]["created_at"]}


def list_chats(database: Any, user_id: Any) -> dict:
    """GET /v2/chats: {"chats": [{id, kind, title, subtitle, last}]}."""
    user_id = _require(database, user_id)
    mine = {str(m["thread_id"]): str(m["id"]) for m in _memberships(database, user_id)}
    if not mine:
        return {"chats": []}
    ids = list(mine)
    threads = _rows(_table(database, THREADS).select("id,kind,title,created_at").in_("id", ids))
    others: dict[str, dict] = {}
    for m in _rows(_table(database, MEMBERS).select("id,thread_id,display_name,subtitle")
                   .in_("thread_id", ids)):
        if str(m["id"]) != mine.get(str(m["thread_id"])):
            others.setdefault(str(m["thread_id"]), m)
    chats: list[tuple[str, dict]] = []
    for t in threads:
        other = others.get(str(t["id"])) or {}
        last = _last(database, str(t["id"]))
        chats.append(((last or t)["created_at"] or "", {
            "id": str(t["id"]), "kind": t["kind"],
            "title": other.get("display_name") or t["title"],
            "subtitle": other.get("subtitle"), "last": last}))
    chats.sort(key=lambda pair: str(pair[0]), reverse=True)
    return {"chats": [chat for _, chat in chats]}


def _authors(database: Any, thread_id: str) -> dict[str, str]:
    return {str(m["id"]): m["display_name"]
            for m in _rows(_table(database, MEMBERS).select("id,display_name")
                           .eq("thread_id", thread_id))}


def _shown(row: dict, me: str, authors: dict[str, str]) -> dict:
    author = str(row["author_member_id"])
    return {"id": str(row["id"]), "mine": author == me, "author": authors.get(author, ""),
            "kind": row["kind"], "body": row["body"], "meta": row.get("meta") or {},
            "created_at": row["created_at"]}


def read(database: Any, user_id: Any, thread_id: Any) -> dict:
    """GET /v2/chats/<id>/messages: {"messages": [...]}, oldest first."""
    user_id = _require(database, user_id)
    me = _member_of(database, user_id, thread_id)
    thread = str(me["thread_id"])
    newest = _rows(_table(database, MESSAGES)
                   .select("id,author_member_id,kind,body,meta,created_at")
                   .eq("thread_id", thread).order("created_at", desc=True)
                   .limit(_MAX_MESSAGES))
    authors = _authors(database, thread)
    return {"messages": [_shown(r, str(me["id"]), authors) for r in reversed(newest)]}


# ── Writing ──────────────────────────────────────────────────────────────

def post(database: Any, user_id: Any, thread_id: Any, body: Any) -> dict:
    """POST /v2/chats/<id>/messages {kind: "emoji", body}: one of the three
    emoji (N311), or 400. {"message": {...}}."""
    user_id = _require(database, user_id)
    me = _member_of(database, user_id, thread_id)
    payload = body if isinstance(body, dict) else {}
    emoji = payload.get("body")
    if payload.get("kind") != "emoji" or not isinstance(emoji, str) or emoji not in EMOJI:
        raise ChatsError("NOT_ALLOWED", "Only 👍, 👀 or 🙏 for now.")
    thread = str(me["thread_id"])
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": "emoji",
        "body": emoji, "meta": {"label": EMOJI[emoji]}}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    return {"message": _shown(rows[0], str(me["id"]), _authors(database, thread))}


def _demo_kinds(database: Any, user_id: str) -> set[str]:
    return {r["kind"] for r in _rows(_table(database, THREADS).select("kind")
                                     .eq("demo_user_id", user_id))}


def _seed_one(database: Any, user_id: str, demo: dict, start: datetime) -> None:
    """One demo chat: the thread, the person and the guest, what the guest
    said. A half-made chat is removed, so the next seed makes it again. A
    second seed racing this one meets the one-of-each-kind index and stops."""
    try:
        rows = _rows(_table(database, THREADS).insert({
            "kind": demo["kind"], "title": demo["name"], "demo_user_id": user_id}))
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise
        return
    if not rows:
        return
    thread = str(rows[0]["id"])
    try:
        members = _rows(_table(database, MEMBERS).insert([
            {"thread_id": thread, "user_id": user_id, "display_name": _YOU},
            {"thread_id": thread, "user_id": None, "display_name": demo["name"],
             "subtitle": demo["subtitle"]}]))
        guest = next(str(m["id"]) for m in members if m.get("user_id") is None)
        said = demo["said"]
        # A second apart, the last one now: in order, and never after a
        # message the person sends next.
        _rows(_table(database, MESSAGES).insert([
            {"thread_id": thread, "author_member_id": guest, "kind": kind, "body": body,
             "meta": {"label": EMOJI[body]} if kind == "emoji" else {},
             "created_at": (start - timedelta(seconds=len(said) - 1 - i)).isoformat()}
            for i, (kind, body) in enumerate(said)]))
    except Exception:
        logger.error("chats: demo %s for %s failed; removing it", demo["kind"], user_id,
                     exc_info=True)
        _table(database, THREADS).delete().eq("id", thread).execute()
        raise


def seed_demo(database: Any, user_id: Any) -> dict:
    """POST /v2/chats/demo: a customer's chat and a colleague's, once per
    person (chat_threads.demo_user_id, one of each kind); then the list."""
    user_id = _require(database, user_id)
    have = _demo_kinds(database, user_id)
    start = datetime.now(timezone.utc)
    for demo in DEMO:
        if demo["kind"] not in have:
            _seed_one(database, user_id, demo, start)
    return list_chats(database, user_id)
