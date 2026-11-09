"""The join link, the chats' second slice (founder, the Claude Code chat, 2
November 2026: "go, build the join link slice"; N308, N328, N335). Table:
chat_links (migration a_person_has_a_link_to_join_them), with chat_threads'
link_id and pair_key.

Everyone has their own link to join them in a chat (N308). Whoever opens it
and joins gets a chat with its owner; that is the only way a person comes
into someone's chats (N328): no list of people, no search, no message to
someone you are not already in a chat with. Joining is a new member's
onboarding (N335 item 1).

  * ``my_link``: the caller's live link, made the first time it is asked
    for. Its secret is ``token``; the page is ``/c/<token>``.
  * ``renew``: the caller's link replaced; the old one stops working.
  * ``preview``: for the join page, before anyone signs in: the first name
    of whose link it is, and nothing else. A wrong, replaced or switched-off
    link is 404, the same answer for each.
  * ``join``: the signed-in caller joins: one chat with the link's owner,
    made once for the two of them (chat_threads.pair_key), however often
    either opens a link. Your own link is refused. By invitation (N471):
    the chat made through a link is what lets a new person in
    (services/membership.py); a waiting account's link opens nothing, and
    past the day's number of joins the joiner goes to the waitlist.
  * ``joined_through``: for a chat's screen, the first name of whose link
    the caller joined through, or None (the owner, a demo chat).

Ring row ``chats``, ring 6: the link's owner and the person joining both need
it; anyone else gets 404, as the other chats routes answer. No provider call,
no recording: nothing here passes the processing-authorization path, because
nothing here is a speaker's recording. A voice note sent in the chat later
passes it, as every voice note does. Deleted with the account: the purge
registry takes a person's links; their place in each chat goes as their
memberships do (services/chats.py).
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from services.chats import (
    MEMBERS, THREADS, ChatsError, _not_found, _require, _rows, _table, _UNIQUE_VIOLATION,
    _uuid, enabled,
)

logger = logging.getLogger(__name__)

LINKS = "chat_links"
#: Random bytes in a link's secret: 24 URL-safe characters.
TOKEN_BYTES = 18
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
#: How a person is named when their account has no name and no email.
_NO_NAME = "WillpowerLab"


def name_of(token_payload: Any) -> str:
    """The first word of the account's name; else the part of its email
    before the @; else WillpowerLab. Shown on the join page and as the
    person's name in the chat."""
    payload: dict = token_payload if isinstance(token_payload, dict) else {}
    raw_meta = payload.get("user_metadata")
    meta: dict = raw_meta if isinstance(raw_meta, dict) else {}
    words = str(meta.get("full_name") or meta.get("name") or meta.get("display_name") or "").split()
    if words:
        return words[0][:120]
    local = str(payload.get("email") or "").split("@")[0].strip()
    return local[:120] or _NO_NAME


def _live(database: Any, user_id: str) -> Optional[dict]:
    rows = _rows(_table(database, LINKS).select("id,token,display_name")
                 .eq("user_id", user_id).is_("revoked_at", "null").limit(1))
    return rows[0] if rows else None


def _shown(link: dict) -> dict:
    return {"token": link["token"], "path": f"/c/{link['token']}"}


def my_link(database: Any, user_id: Any, token_payload: Any) -> dict:
    """GET /v2/chats/link: {"token", "path"}. Made the first time; a second
    request racing the first meets the one-live-link index and reads it."""
    user_id = _require(database, user_id)
    name = name_of(token_payload)
    link = _live(database, user_id)
    if link:
        if link.get("display_name") != name:
            _table(database, LINKS).update({"display_name": name}).eq("id", link["id"]).execute()
        return _shown(link)
    try:
        rows = _rows(_table(database, LINKS).insert({
            "user_id": user_id, "token": secrets.token_urlsafe(TOKEN_BYTES),
            "display_name": name}))
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise
        rows = []
    link = rows[0] if rows else _live(database, user_id)
    if not link:
        raise ChatsError("NOT_SAVED", "Could not make your link.", 503)
    return _shown(link)


def renew(database: Any, user_id: Any, token_payload: Any) -> dict:
    """POST /v2/chats/link: the live link replaced by a new one; the old one
    answers 404 from now on. {"token", "path"}."""
    user_id = _require(database, user_id)
    _table(database, LINKS).update({"revoked_at": datetime.now(timezone.utc).isoformat()}) \
        .eq("user_id", user_id).is_("revoked_at", "null").execute()
    return my_link(database, user_id, token_payload)


def _open(database: Any, token: Any) -> dict:
    """The live link with this secret, its owner having the chats; else
    404 (wrong, replaced and switched off answer the same)."""
    if not isinstance(token, str) or not _TOKEN.match(token):
        raise _not_found()
    rows = _rows(_table(database, LINKS).select("id,user_id,display_name")
                 .eq("token", token).is_("revoked_at", "null").limit(1))
    if not rows or not enabled(database, str(rows[0]["user_id"])):
        raise _not_found()
    return rows[0]


def preview(database: Any, token: Any) -> dict:
    """GET /v2/chats/join/<token>, no sign-in: {"name"}, whose link it is.
    A link whose owner has the chat builder (N579 item 2) also says whose
    assistant answers there (N578 item 1) and Will's line for the joiner's
    own chat (N586 item 2): {"assistant", "will_line"}."""
    from services import assistants, rings
    link = _open(database, token)
    out: dict = {"name": link["display_name"]}
    if rings.feature_is_on_for_user(assistants.CHAT_BUILDER, str(link["user_id"]), database=database):
        out["assistant"] = assistants.assistant_name(link["display_name"])
        out["will_line"] = assistants.will_line()
        about = assistants.about_lines(database, str(link["user_id"]))
        if about:
            out["about"] = about
    return out


def _pair_chat(database: Any, key: str) -> Optional[str]:
    rows = _rows(_table(database, THREADS).select("id").eq("pair_key", key).limit(1))
    return str(rows[0]["id"]) if rows else None


def _seat(database: Any, thread: str, people: list[dict]) -> None:
    """Both people in the chat: whoever is missing is added (a chat left
    without its members by a crash between the two inserts would otherwise
    keep the pair out for good, its pair_key taken). A second request racing
    this one meets the one-per-person index, which is fine."""
    have = {str(m["user_id"]) for m in _rows(_table(database, MEMBERS).select("user_id")
                                             .eq("thread_id", thread))}
    missing = [{"thread_id": thread, **p} for p in people if p["user_id"] not in have]
    if not missing:
        return
    try:
        _rows(_table(database, MEMBERS).insert(missing))
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise


def join(database: Any, user_id: Any, token: Any, token_payload: Any) -> dict:
    """POST /v2/chats/join/<token>: {"chat": {"id"}}, the caller's chat with
    the link's owner, made now or found. Your own link is 400."""
    from services import membership

    user_id = _require(database, user_id)
    link = _open(database, token)
    owner = str(link["user_id"])
    if owner == user_id:
        raise ChatsError("OWN_LINK", "This is your own link.")
    # By invitation (N471): only a member's link lets anyone in, and the same
    # answer as a wrong link, so a waiting account's link opens nothing.
    if not membership.is_member(database, owner):
        raise _not_found()
    people = [{"user_id": owner, "display_name": link["display_name"]},
              {"user_id": user_id, "display_name": name_of(token_payload)}]
    found = _pair_chat(database, _pair_key(people))
    if found:
        _seat(database, found, people)
        return {"chat": {"id": found}}
    # After the day's number of joins through this person's links, the next
    # one goes to the waitlist (N471 item 7): no chat is made.
    if membership.link_is_full(database, owner, user_id):
        return {"waitlist": True}
    thread, made = _open_pair(database, people, link["display_name"], link_id=str(link["id"]))
    if made:
        membership.admitted(user_id)
        # The host's welcome first (N590 item 2), then the questions the
        # link's owner set for whoever joins (N487).
        from services import assistants
        owner_member = next((str(m["id"]) for m in _rows(_table(database, MEMBERS)
                             .select("id,user_id").eq("thread_id", thread))
                             if str(m.get("user_id")) == owner), None)
        if owner_member:
            assistants.welcome(database, thread, owner, owner_member)
        from services import join_questions
        join_questions.begin(database, thread, owner, user_id)
    return {"chat": {"id": thread}}


def _pair_key(people: list[dict]) -> str:
    return ":".join(sorted(str(p["user_id"]) for p in people))


def open_pair(database: Any, people: list[dict], title: str,
              link_id: Optional[str] = None) -> str:
    """The chat of two people, found or made now, both seated: one chat per
    pair (``pair_key``). ``people`` are the two ``{"user_id",
    "display_name"}``; ``title`` the chat's; ``link_id`` the link it was made
    through (N308), or none for a chat made by an answer (N478)."""
    return _open_pair(database, people, title, link_id)[0]


def _open_pair(database: Any, people: list[dict], title: str,
               link_id: Optional[str] = None) -> tuple[str, bool]:
    """``open_pair``, and whether the chat was made just now (a join's
    welcome follows only a chat it made, N471, N487)."""
    key = _pair_key(people)
    found = _pair_chat(database, key)
    if found:
        _seat(database, found, people)
        return found, False
    thread_row: dict = {"kind": "team", "title": title, "pair_key": key}
    if link_id:
        thread_row["link_id"] = link_id
    try:
        rows = _rows(_table(database, THREADS).insert(thread_row))
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise
        found = _pair_chat(database, key)
        if found:
            _seat(database, found, people)
            return found, False
        raise
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not join.", 503)
    thread = str(rows[0]["id"])
    try:
        _rows(_table(database, MEMBERS).insert([{"thread_id": thread, **p} for p in people]))
    except Exception:
        logger.error("chat_links: the chat %s for %s missed its members; removing it",
                     thread, key, exc_info=True)
        _table(database, THREADS).delete().eq("id", thread).execute()
        raise
    return thread, True


def joined_through(database: Any, user_id: str, thread_id: Any) -> Optional[str]:
    """The first name of whose link the caller joined this chat through, or
    None: for the link's owner, for a demo chat and for a chat whose link has
    gone. For the line "You joined through {name}'s link." (N335 item 2)."""
    thread = _uuid(thread_id)
    rows = _rows(_table(database, THREADS).select("link_id").eq("id", thread).limit(1)) if thread else []
    link_id = rows[0].get("link_id") if rows else None
    if not link_id:
        return None
    links = _rows(_table(database, LINKS).select("user_id,display_name").eq("id", str(link_id)).limit(1))
    if not links or str(links[0]["user_id"]) == str(user_id):
        return None
    return str(links[0]["display_name"])


def joined_by(database: Any, user_id: str, thread_id: Any) -> Optional[str]:
    """For the link's owner: the first name of whoever joined this chat
    through their link, or None, for the line "{name} joined through your
    link." (N502 item 5)."""
    thread = _uuid(thread_id)
    rows = _rows(_table(database, THREADS).select("link_id").eq("id", thread).limit(1)) if thread else []
    link_id = rows[0].get("link_id") if rows else None
    if not link_id:
        return None
    links = _rows(_table(database, LINKS).select("user_id").eq("id", str(link_id)).limit(1))
    if not links or str(links[0]["user_id"]) != str(user_id):
        return None
    other = next((m for m in _rows(_table(database, MEMBERS).select("user_id,display_name")
                                   .eq("thread_id", thread))
                  if str(m.get("user_id")) != str(user_id)), None)
    name = str((other or {}).get("display_name") or "").strip()
    return name.split()[0] if name else None
