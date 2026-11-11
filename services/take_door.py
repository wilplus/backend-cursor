"""A Take recorded in a host's chat: the second door into the one loop
(founder, the Claude Code chat, 11 November 2026: N642 item 7, N644, N648
item 8). The loop is not copied. The Take is recorded by the route every
Take uses (POST /v2/lab/recordings: membership, project, the
processing-authorization path, recording consent, processing, transcript,
Ideal Text, feedback walk, coaches) and stays the person's own, as today.
This module only tags it with the host's chat it was made in.

  * ``door_open``: does this chat let the caller record a Take? Only for a
    person on the ring row ``chat_builder``, in their chat with the speaking
    host, whose recipe takes a recording (``send`` has "rec") and whose saved
    feedback walk ends in an Ideal Text (``walk.out`` "ideal_text", N641).
    The speaking host is ``Config.SPEAKING_HOST_USER_ID`` when set, else the
    founder's account, found as services/take_sends.py finds it. One
    speaking host for now (the coordinator, 11 November 2026).
  * ``tag``: POST /v2/chats/<id>/take {take}: the caller's own Take, already
    uploaded, tagged with this chat once. The tag is one message of kind
    ``take`` (migration a_chat_carries_a_take) written by the speaker, its
    meta ``{"made_here": <take id>, "take_index": n}``, its id
    uuid5(Take, "made:" + chat), so a retry posts nothing new and it never
    meets the message of the same Take sent with take_sends (uuid5(Take,
    chat)). No push.
  * ``made_in`` and ``takes_made_in``: the seam for the transcript and Ideal
    Text, practice, the plan and the feelings check, and coaches: which chat
    a Take was made in, and the Takes made in a chat.

What the host never gets (Privacy 4f: a person's Take reaches someone else
only when the person sends it, services/take_sends.py): the tag is drawn for
the speaker only (``mine_only``: services/chats.py leaves it out of the
host's messages and the list's last line), and it carries no
``take_session_id`` or ``take``, so neither "Open Take" nor the audio route
opens anything through it.

No provider call and no recording here; the route asks the recording
consent again, as an answer's does. No migration. Deleted with the account:
the message goes with the speaker's membership (chat_messages ON DELETE
CASCADE, services/data_purge_registry.py).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from config import Config
from services import chats
from services.chats import MEMBERS, MESSAGES, ChatsError, _rows, _table

logger = logging.getLogger(__name__)

#: The tag's meta key: the Take's id, read by this module only.
MADE_HERE = "made_here"
#: What the host's recipe must hold to open the door.
REC, IDEAL_TEXT = "rec", "ideal_text"


def mine_only(row: dict, me: str) -> bool:
    """Is this message a tag the caller must not see (someone else's)?"""
    meta = row.get("meta") or {}
    return MADE_HERE in meta and str(row.get("author_member_id")) != str(me)


def speaking_host(database: Any) -> Optional[str]:
    """The speaking host's account id, or None."""
    configured = getattr(Config, "SPEAKING_HOST_USER_ID", None)
    if configured:
        return chats._uuid(configured)
    from services import take_sends
    return take_sends._founder(database)


def _opens(recipe: Optional[dict]) -> bool:
    """A recipe that takes a recording and ends its saved walk in an Ideal
    Text. A walk never saved is only Will's suggestion: it opens nothing."""
    from services import chat_recipes
    if not recipe or recipe.get("v") != chat_recipes.V:
        return False
    walk = recipe.get("walk")
    return REC in (recipe.get("send") or []) and isinstance(walk, dict) \
        and walk.get("out") == IDEAL_TEXT


def _other(database: Any, thread: str, me: str) -> Optional[str]:
    rows = _rows(_table(database, MEMBERS).select("id,user_id").eq("thread_id", thread))
    others = [str(r["user_id"]) for r in rows if str(r["id"]) != me and r.get("user_id")]
    return others[0] if len(others) == 1 else None


def door_open(database: Any, user_id: Any, thread: str, me: str) -> bool:
    """Does this chat open the door for the caller? Never raises."""
    from services import assistants
    try:
        if not assistants.on(database, user_id):
            return False
        host = speaking_host(database)
        if not host or host == str(user_id) or _other(database, thread, me) != host:
            return False
        return _opens(assistants.recipe_of(database, host))
    except Exception:
        logger.warning("take_door: the door could not be read for chat %s", thread, exc_info=True)
        return False


def doors(database: Any, user_id: Any, mine: dict[str, str]) -> set[str]:
    """Of the caller's chats ({chat: their membership}), those that open the
    door: one read of the ring and the host's recipe for all of them."""
    from services import assistants
    try:
        if not mine or not assistants.on(database, user_id):
            return set()
        host = speaking_host(database)
        if not host or host == str(user_id) or not _opens(assistants.recipe_of(database, host)):
            return set()
        rows = _rows(_table(database, MEMBERS).select("thread_id,user_id")
                     .in_("thread_id", list(mine)).eq("user_id", host))
        return {str(r["thread_id"]) for r in rows}
    except Exception:
        logger.warning("take_door: the doors could not be read", exc_info=True)
        return set()


def _tag_id(take: str, thread: str) -> str:
    return str(uuid.uuid5(uuid.UUID(take), "made:" + thread))


def tag(database: Any, user_id: Any, thread_id: Any, take: Any) -> dict:
    """POST /v2/chats/<id>/take {take}: {"message_id", "take"}. 404 for a
    chat that is not the caller's, a chat whose door is shut, or a Take that
    is not theirs. Idempotent."""
    me = chats.member(database, user_id, thread_id)
    thread, mine = str(me["thread_id"]), str(me["id"])
    session = chats._uuid(take)
    if not session or not door_open(database, user_id, thread, mine):
        raise chats._not_found()
    owned = _rows(_table(database, chats.SESSIONS).select("id,take_index")
                  .eq("id", session).eq("user_id", str(user_id)).limit(1))
    if not owned:
        raise chats._not_found()
    message = _tag_id(session, thread)
    if not _rows(_table(database, MESSAGES).select("id").eq("id", message).limit(1)):
        try:
            rows = _rows(_table(database, MESSAGES).insert({
                "id": message, "thread_id": thread, "author_member_id": mine,
                "kind": "take", "body": "",
                "meta": {MADE_HERE: session, "take_index": owned[0].get("take_index")}}))
        except Exception as e:
            if chats._UNIQUE_VIOLATION not in str(e):
                raise
            rows = [{"id": message}]  # a retry got there first
        if not rows:
            raise ChatsError("NOT_SAVED", "Could not keep it.", 503)
    return {"message_id": message, "take": session}


# ── The seam ─────────────────────────────────────────────────────────────

def _tags(database: Any, **eq: str) -> list[dict]:
    query = _table(database, MESSAGES).select("thread_id,meta,created_at").eq("kind", "take")
    for column, value in eq.items():
        query = query.eq(column, value)
    return [r for r in _rows(query) if (r.get("meta") or {}).get(MADE_HERE)]


def made_in(database: Any, take_id: Any) -> Optional[str]:
    """The host's chat this Take was made in, or None (made anywhere else)."""
    take = chats._uuid(take_id)
    if not take:
        return None
    rows = _rows(_table(database, MESSAGES).select("thread_id,meta").eq("kind", "take")
                 .eq("meta->>" + MADE_HERE, take).limit(1))
    return str(rows[0]["thread_id"]) if rows else None


def takes_made_in(database: Any, thread_id: Any) -> list[str]:
    """The Takes made in this chat, the first made first."""
    thread = chats._uuid(thread_id)
    if not thread:
        return []
    rows = sorted(_tags(database, thread_id=thread), key=lambda r: str(r.get("created_at") or ""))
    return list(dict.fromkeys(str(r["meta"][MADE_HERE]) for r in rows))
