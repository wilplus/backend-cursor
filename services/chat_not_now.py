"""Each "Not now" kept as behavioural data (founder, 4 November 2026, N504
item 2; migration a_not_now_is_counted).

A person taps "Not now" under a question or a Take someone asked them in a
chat (N483 item 3, N493 item 3). Nobody is ever told (N483 item 3, N485
item 3). The system keeps it: who declined, whose question or Take, which
message, what it was, the flow, and when, once per person and message. The
founder reads it on the person's admin page, under the voice data from
their Takes; the matching may read it (N481 item 2's communication
profile). It is never shown to the person (Never 1).

  POST /v2/chats/<id>/messages/<message_id>/not-now   the caller declines it
  GET  /v2/admin/people/<user_id>/not-now             founder only
"""
from __future__ import annotations

import logging
from typing import Any

from services import chats
from services.chats import MEMBERS, MESSAGES, ChatsError, _rows, _table, _uuid

logger = logging.getLogger(__name__)

TABLE = "chat_not_now"
#: The newest declines the admin page lists; the count is of all of them.
SHOWN = 50


def _what(row: dict) -> str | None:
    """'take' for a Take, 'question' for a question asked to answer properly
    (N361, N498); None for anything that asks for no answer."""
    meta = row.get("meta") or {}
    if row.get("kind") == "take" and "made_here" not in meta:  # a tag asks nothing
        return "take"
    if meta.get("question") is True or meta.get("record_answer") is True:
        return "question"
    return None


def record(database: Any, user_id: Any, thread_id: Any, message_id: Any) -> dict:
    """The caller's "Not now" on a message the other person asked them in
    this chat, kept once. 404 for a chat or message that is not theirs, 400
    for their own message or one that asks for nothing. {"kept": true}."""
    me = chats.member(database, user_id, thread_id)
    message = _uuid(message_id)
    rows = _rows(_table(database, MESSAGES).select("id,kind,meta,author_member_id")
                 .eq("id", message).eq("thread_id", str(me["thread_id"])).limit(1)) if message else []
    if not rows:
        raise chats._not_found()
    row = rows[0]
    if str(row.get("author_member_id")) == str(me["id"]):
        raise ChatsError("NOT_ALLOWED", "Not now is for what someone asked you.")
    what = _what(row)
    if not what:
        raise ChatsError("NOT_ALLOWED", "This message asks for no answer.")
    flow = "match" if (row.get("meta") or {}).get("match") else "list"
    if _rows(_table(database, TABLE).select("id").eq("member_id", str(me["id"]))
             .eq("message_id", str(row["id"])).limit(1)):
        return {"kept": True}
    try:
        _table(database, TABLE).insert({
            "thread_id": str(me["thread_id"]), "member_id": str(me["id"]),
            "asker_member_id": str(row["author_member_id"]), "message_id": str(row["id"]),
            "what": what, "flow": flow}).execute()
    except Exception as e:
        if chats._UNIQUE_VIOLATION not in str(e):
            raise
    return {"kept": True}


def for_person(database: Any, user_id: Any) -> dict:
    """One person's declines, for the founder: how many, and the newest ones
    with when, what, the flow and whose it was. {"count", "declines"}."""
    person = _uuid(user_id)
    if not person:
        return {"count": 0, "declines": []}
    members = [str(m["id"]) for m in _rows(_table(database, MEMBERS).select("id").eq("user_id", person))]
    if not members:
        return {"count": 0, "declines": []}
    rows = _rows(_table(database, TABLE).select("member_id,asker_member_id,what,flow,created_at")
                 .in_("member_id", members).order("created_at", desc=True))
    askers = {str(r["asker_member_id"]) for r in rows[:SHOWN]}
    names = {str(m["id"]): m.get("display_name")
             for m in _rows(_table(database, MEMBERS).select("id,display_name").in_("id", list(askers)))} \
        if askers else {}
    return {"count": len(rows), "declines": [
        {"at": r.get("created_at"), "what": r.get("what"), "flow": r.get("flow"),
         "asker": names.get(str(r["asker_member_id"]))}
        for r in rows[:SHOWN]]}
