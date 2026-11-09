"""Your chat on any website (founder, the Claude Code chat, 5 November 2026,
N567): the join link, as one line of code. Table: chat_widget_guests and
chat_threads.widget_owner_id (migration a_person_s_chat_opens_on_a_website).

The line a person pastes on their site, ``<script src=".../w.js"
data-link="<token>">``, carries their link's token (services/chat_links.py),
so a new link, or a link switched off, stops every pasted line with it. The
widget runs in an iframe on willpowerlab.com (``/w/<token>``); its visitor is
a guest with no account who can only tap (N567 item 4):

  * ``preview``: whose chat it is ({"name"}) and the three questions a
    visitor may ask; 404 for a wrong, replaced or switched-off link.
  * ``start``: "Agree and start": one chat of the visitor's own with the
    link's owner, named "Widget / Visitor {n}" with "From {site}" in the
    owner's list (N567 item 6); the owner's join questions begin (N487). The
    answer carries the visitor's secret, ``<guest id>.<secret>``, which only
    their browser keeps; its hash is kept here.
  * ``read``: the visitor's chat, as a member's is read (an answer still in
    its 5 seconds unseen; the owner's own setup lines' counterparts hidden).
  * ``answer_setup``, ``ask``, ``emoji``: the visitor's taps. ``ask`` posts
    one of ``ASKS`` marked for the owner to answer (``record_answer``), so
    the owner's bar's middle is "Record your answer" and the answer goes as
    every answer does (services/chats.py ``post_answer``).
  * ``recording``: an answer's voice, for the visitor.
  * ``keep``: "Keep this chat": a signed-in person takes the visitor's seat,
    and the chat is named after them, "Widget / {name}" (N567 item 7).

No provider call and no recording by the visitor: nothing here passes the
processing-authorization path; the owner's answer passes it as every
answer does (routes/v2/chats.py). A widget's chats never set
chat_threads.link_id, so they do not count toward the day's joins through a
link (services/membership.py ``link_is_full``). Deleted with the owner's
account: the purge registry takes the chats by ``widget_owner_id``, and the
guest rows go with them.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from services.chats import (
    AUDIO, EMOJI, MEMBERS, MESSAGES, THREADS, ChatsError, _answer_recording, _answers,
    _authors, _bytes, _held, _not_found, _rows, _shown, _table, _tell, _uuid, _words,
)

logger = logging.getLogger(__name__)

GUESTS = "chat_widget_guests"
#: The questions a visitor may ask, the same three in every widget until
#: Will's setup asks for the owner's own (N567 item 5; signed).
ASKS = ("What do you do?", "How do you work with people?", "Can we talk?")
#: How the visitor is named in the owner's list (N567 item 6; signed).
VISITOR = "Widget / Visitor {n}"
KEPT = "Widget / {name}"
FROM = "From {site}"
#: Random bytes in a visitor's secret.
SECRET_BYTES = 24
_SITE = re.compile(r"^(?=.{1,120}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
_MAX_MESSAGES = 200


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _site(value: Any) -> Optional[str]:
    """The host the widget was opened on, as ``w.js`` reads it, lower case,
    without ``www.``; None when it is not a plain host name."""
    host = str(value or "").strip().lower()
    host = host[4:] if host.startswith("www.") else host
    return host if _SITE.match(host) else None


def _link(database: Any, token: Any) -> dict:
    """The live link with this token, its owner a member (N471); else 404,
    as the join page answers."""
    from services import membership
    from services.chat_links import _open
    link = _open(database, token)
    if not membership.is_member(database, str(link["user_id"])):
        raise _not_found()
    return link


def preview(database: Any, token: Any) -> dict:
    """GET /v2/chats/widget/<token>: {"name", "asks"}."""
    return {"name": _link(database, token)["display_name"], "asks": list(ASKS)}


def _number(database: Any, owner: str) -> int:
    return len(_rows(_table(database, GUESTS).select("id").eq("owner_user_id", owner))) + 1


def start(database: Any, token: Any, site: Any) -> dict:
    """POST /v2/chats/widget/<token>/start {"site"}: "Agree and start". The
    visitor's chat with the link's owner, made now: {"guest": the visitor's
    secret, then what ``read`` answers}."""
    from services import join_questions
    link = _link(database, token)
    owner = str(link["user_id"])
    host = _site(site)
    n = _number(database, owner)
    rows = _rows(_table(database, THREADS).insert({
        "kind": "team", "title": link["display_name"], "widget_owner_id": owner,
        "pair_key": f"widget:{secrets.token_hex(16)}"}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not start the chat.", 503)
    thread = str(rows[0]["id"])
    try:
        seats = _rows(_table(database, MEMBERS).insert([
            {"thread_id": thread, "user_id": owner, "display_name": link["display_name"]},
            {"thread_id": thread, "user_id": None, "display_name": VISITOR.format(n=n),
             "subtitle": FROM.format(site=host) if host else None}]))
        by_user = {str(s.get("user_id")): s for s in seats}
        owner_seat, visitor_seat = by_user[owner], by_user["None"]
        secret = secrets.token_urlsafe(SECRET_BYTES)
        guests = _rows(_table(database, GUESTS).insert({
            "link_id": str(link["id"]), "owner_user_id": owner, "thread_id": thread,
            "member_id": str(visitor_seat["id"]), "secret_hash": _hash(secret),
            "site": host, "number": n}))
        if not guests:
            raise ChatsError("NOT_SAVED", "Could not start the chat.", 503)
    except Exception:
        logger.error("chat_widget: the chat %s missed its seats; removing it", thread, exc_info=True)
        _table(database, THREADS).delete().eq("id", thread).execute()
        raise
    join_questions.begin_for_visitor(database, thread, owner, str(owner_seat["id"]),
                                     str(visitor_seat["id"]))
    guest = f"{guests[0]['id']}.{secret}"
    return {"guest": guest, **read(database, token, guest)}


def _visitor(database: Any, token: Any, guest: Any) -> dict:
    """The visitor's seat ({"id", "thread_id"}) for this link and secret;
    404 otherwise, the same for a wrong secret, a replaced link and a chat
    that has gone."""
    link = _link(database, token)
    gid, _, secret = str(guest or "").partition(".")
    gid = _uuid(gid) or ""
    if not gid or not secret:
        raise _not_found()
    rows = _rows(_table(database, GUESTS).select("id,link_id,thread_id,member_id,secret_hash,kept_at")
                 .eq("id", gid).limit(1))
    row = rows[0] if rows else None
    if not row or str(row["link_id"]) != str(link["id"]) \
            or not hmac.compare_digest(str(row["secret_hash"]), _hash(secret)):
        raise _not_found()
    return {"id": str(row["member_id"]), "thread_id": str(row["thread_id"]),
            "guest_id": gid, "kept": bool(row.get("kept_at")), "owner": str(link["user_id"]),
            "name": link["display_name"]}


def read(database: Any, token: Any, guest: Any) -> dict:
    """GET /v2/chats/widget/<token>/messages: {"name", "asks", "messages",
    "kept"}, oldest first, as the visitor sees them."""
    from services import join_questions
    me = _visitor(database, token, guest)
    thread = me["thread_id"]
    newest = _rows(_table(database, MESSAGES)
                   .select("id,author_member_id,kind,body,meta,created_at")
                   .eq("thread_id", thread).order("created_at", desc=True).limit(_MAX_MESSAGES))
    newest = [r for r in newest if not _held(r) and not join_questions.hidden(r, me["id"])]
    authors = _authors(database, thread)
    words = _words(database, thread, newest)
    answers = _answers(database, newest)
    return {"name": me["name"], "asks": list(ASKS), "kept": me["kept"],
            "messages": [_shown(r, me["id"], authors, words, answers) for r in reversed(newest)]}


def answer_setup(database: Any, token: Any, guest: Any, message_id: Any, payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/setup/<message_id> {"picked", "date"?}:
    the visitor's tap on one of the owner's join questions."""
    from services import join_questions
    me = _visitor(database, token, guest)
    return join_questions.answer_as(database, me, None, message_id, payload)


def _waiting(database: Any, me: dict) -> bool:
    """The visitor's newest question has no answer from the owner yet."""
    rows = _rows(_table(database, MESSAGES).select("author_member_id,meta")
                 .eq("thread_id", me["thread_id"]).order("created_at", desc=True).limit(50))
    for r in rows:
        if str(r["author_member_id"]) != me["id"]:
            return False
        if "widget_ask" in (r.get("meta") or {}):
            return True
    return False


def ask(database: Any, token: Any, guest: Any, payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/ask {"i"}: one of ``ASKS``, marked for
    the owner to answer out loud; 409 while the last one waits."""
    me = _visitor(database, token, guest)
    body = payload if isinstance(payload, dict) else {}
    i = body.get("i")
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(ASKS):
        raise ChatsError("NOT_ALLOWED", "Tap one of the questions.")
    if _waiting(database, me):
        raise ChatsError("WAITING", "Your question waits for its answer.", 409)
    return _post(database, me, "text", ASKS[i], {"widget_ask": i, "record_answer": True})


def emoji(database: Any, token: Any, guest: Any, payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/messages {"body"}: one of the three
    emoji."""
    me = _visitor(database, token, guest)
    sent = (payload if isinstance(payload, dict) else {}).get("body")
    if not isinstance(sent, str) or sent not in EMOJI:
        raise ChatsError("NOT_ALLOWED", "Only 👍, 👀 or 🙏 for now.")
    return _post(database, me, "emoji", sent, {"label": EMOJI[sent]})


def _post(database: Any, me: dict, kind: str, body: str, meta: dict) -> dict:
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": me["thread_id"], "author_member_id": me["id"], "kind": kind,
        "body": body, "meta": meta}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, rows[0])
    return {"message": _shown(rows[0], me["id"], _authors(database, me["thread_id"]))}


def recording(database: Any, token: Any, guest: Any, message_id: Any) -> dict:
    """GET /v2/chats/widget/<token>/messages/<message_id>/audio: an answer's
    voice (its Take's own recording), or a voice note, in the visitor's
    chat; 404 otherwise."""
    me = _visitor(database, token, guest)
    message = _uuid(message_id)
    if not message:
        raise _not_found()
    rows = _rows(_table(database, AUDIO).select("content_type,audio")
                 .eq("message_id", message).eq("thread_id", me["thread_id"]).limit(1))
    audio = _bytes(rows[0].get("audio")) if rows else b""
    if audio:
        return {"content_type": rows[0].get("content_type") or "audio/webm", "audio": audio}
    return _answer_recording(database, me["thread_id"], message)


def keep(database: Any, user_id: Any, token: Any, guest: Any, token_payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/keep, signed in: "Keep this chat". The
    caller takes the visitor's seat and the chat is named after them; it is
    theirs in the app from now on. {"chat": {"id"}}, or {"waitlist": true}
    past the day's joins (N471 item 7). The owner keeping their own visitor's
    chat is 400."""
    from services import membership
    from services.chat_links import name_of
    me = _visitor(database, token, guest)
    uid = str(user_id or "")
    if not uid:
        raise _not_found()
    if uid == me["owner"]:
        raise ChatsError("OWN_LINK", "This is your own link.")
    if not me["kept"]:
        if membership.link_is_full(database, me["owner"], uid):
            return {"waitlist": True}
        _table(database, MEMBERS).update({
            "user_id": uid, "display_name": KEPT.format(name=name_of(token_payload))}) \
            .eq("id", me["id"]).execute()
        _table(database, GUESTS).update({"kept_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", me["guest_id"]).execute()
        membership.admitted(uid)
    return {"chat": {"id": me["thread_id"]}}
