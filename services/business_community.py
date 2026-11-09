"""A business's community: who joins it, the newcomer's one offer, and the
pool someone new is suggested from (founder, the Claude Code chat,
9 November 2026, N559 item 1; N572's tree; migration
a_business_has_a_community_people_join).

Someone new for a Take comes only from the speaker's business community
(N559 item 1), and joining is how a person belongs to it. A newcomer is
offered the community of the business of the person whose link they came by,
once, while Take 1 is processed, with Join and Not now (N572: after "Here's
how others will see you:", before "What would you like to do here first?").
The way-in screens own where it shows; this module is the data and the API
they call:

  GET  /v2/me/community-offer   {"offer": {"id", "name", "inviter"} | null}
                                The one offer, or none: the caller joined
                                through a member's link, that member's
                                business has a community, and the caller has
                                neither joined it nor answered it. Asking
                                again gives the same offer until it is
                                answered; never after.
  POST /v2/me/community-offer   {"id": community id, "answer": "join" |
                                "not_now"} -> {"offer": null, "joined": bool}.
                                Join makes the caller a member. Not now is
                                kept, and the offer never comes back on its
                                own. 404 for a community never offered.
  POST /v2/admin/business-communities   founder only: {"owner_id", "name"}
                                -> {"community": {"id", "name"}}; the owner
                                is its first member.

The question's words are drafted for the founder's OK (Never 4) and live in
the frontend. Nothing here is a recording or a provider call, and nothing
is shown as a number. The walk is never delayed by it: a failed read is no
offer (Never 3).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.chats import (
    MEMBERS, THREADS, ChatsError, _not_found, _rows, _table, _UNIQUE_VIOLATION, _uuid,
)

logger = logging.getLogger(__name__)

COMMUNITIES = "business_communities"
MEMBERS_OF = "business_community_members"
OFFERS = "business_community_offers"
LINKS = "chat_links"
MAX_ROWS = 500
#: Ids per read, as ``db._chunks``.
CHUNK = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i:i + CHUNK] for i in range(0, len(ids), CHUNK)]


def communities_of(database: Any, user_id: str) -> list[str]:
    """The open communities a person joined, oldest join first."""
    joined = sorted(_rows(_table(database, MEMBERS_OF).select("community_id,joined_at")
                          .eq("user_id", user_id).limit(MAX_ROWS)),
                    key=lambda r: str(r.get("joined_at") or ""))
    ids = [str(r["community_id"]) for r in joined]
    if not ids:
        return []
    open_ids = {str(r["id"]) for part in _chunks(ids) for r in _rows(
        _table(database, COMMUNITIES).select("id,closed_at").in_("id", part))
        if not r.get("closed_at")}
    return [c for c in ids if c in open_ids]


def people(database: Any, user_id: str, cap: int = 2000) -> set[str]:
    """Everyone in the person's business communities, them included: the
    only people someone new is suggested from (N559 item 1)."""
    out: set[str] = set()
    for part in _chunks(communities_of(database, user_id)):
        out |= {str(r["user_id"]) for r in _rows(
            _table(database, MEMBERS_OF).select("user_id").in_("community_id", part)
            .order("user_id").limit(cap)) if r.get("user_id")}
    if len(out) >= cap:
        logger.warning("business_community: the pool of %s is cut at %s people", user_id, cap)
    return out


def _join(database: Any, community_id: str, user_id: str) -> None:
    try:
        _table(database, MEMBERS_OF).insert({"community_id": community_id, "user_id": user_id,
                                             "joined_at": _now()}).execute()
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise


def create(database: Any, owner_id: Any, name: Any) -> dict:
    """The founder makes a business's community; its owner joins it."""
    owner, title = str(owner_id or "").strip(), str(name or "").strip()
    if not owner or not 1 <= len(title) <= 80:
        raise ChatsError("BAD_REQUEST", "An owner and a name of 1 to 80 characters.", 400)
    rows = _rows(_table(database, COMMUNITIES).insert({"owner_id": owner, "name": title}))
    if not rows:
        raise ChatsError("UNAVAILABLE", "Please try again.", 503)
    _join(database, str(rows[0]["id"]), owner)
    return {"community": {"id": str(rows[0]["id"]), "name": title}}


def _inviters(database: Any, user_id: str) -> list[tuple[str, str]]:
    """Whose links the person came by, the first first: (their id, the name
    they go by in that chat)."""
    threads = [str(r["thread_id"]) for r in _rows(
        _table(database, MEMBERS).select("thread_id").eq("user_id", user_id).limit(MAX_ROWS))]
    made: list[tuple[str, str, str]] = []
    for part in _chunks(threads):
        for t in _rows(_table(database, THREADS).select("id,link_id,created_at").in_("id", part)):
            if t.get("link_id"):
                made.append((str(t.get("created_at") or ""), str(t["id"]), str(t["link_id"])))
    out: list[tuple[str, str]] = []
    for _at, thread, link in sorted(made):
        owner = _rows(_table(database, LINKS).select("user_id,display_name").eq("id", link).limit(1))
        if not owner or str(owner[0]["user_id"]) == user_id:
            continue
        who = str(owner[0]["user_id"])
        shown = next((str(m.get("display_name") or "") for m in _rows(
            _table(database, MEMBERS).select("user_id,display_name").eq("thread_id", thread))
            if str(m.get("user_id")) == who), "") or str(owner[0].get("display_name") or "")
        out.append((who, shown.split(" ")[0] if shown else ""))
    return out


def _offers(database: Any, user_id: str) -> dict[str, dict]:
    return {str(r["community_id"]): r for r in _rows(
        _table(database, OFFERS).select("*").eq("user_id", user_id).limit(MAX_ROWS))}


def _name(database: Any, community_id: str) -> Optional[str]:
    rows = _rows(_table(database, COMMUNITIES).select("name,closed_at").eq("id", community_id).limit(1))
    return str(rows[0]["name"]) if rows and not rows[0].get("closed_at") else None


def offer(database: Any, user_id: Any) -> dict:
    """GET /v2/me/community-offer: the one offer, or none (never an error:
    the wait for Take 1 goes on either way)."""
    me = str(user_id)
    try:
        mine = set(communities_of(database, me))
        asked = _offers(database, me)
        for community, row in asked.items():
            if not row.get("answer") and community not in mine:
                name = _name(database, community)
                if name:
                    return {"offer": {"id": community, "name": name,
                                      "inviter": _first(database, me, row.get("inviter_id"))}}
        if asked:
            return {"offer": None}
        for inviter, first in _inviters(database, me):
            for community in communities_of(database, inviter):
                if community in mine:
                    continue
                name = _name(database, community)
                if not name:
                    continue
                try:
                    _table(database, OFFERS).insert({"user_id": me, "community_id": community,
                                                     "inviter_id": inviter,
                                                     "offered_at": _now()}).execute()
                except Exception as e:
                    if _UNIQUE_VIOLATION not in str(e):
                        raise
                return {"offer": {"id": community, "name": name, "inviter": first or None}}
    except Exception:  # noqa: BLE001 -- no offer rather than a broken wait (Never 3)
        logger.error("business_community: the offer for %s failed", me, exc_info=True)
    return {"offer": None}


def _first(database: Any, user_id: str, inviter: Any) -> Optional[str]:
    return next((first for who, first in _inviters(database, user_id)
                 if who == str(inviter or "")), None) or None


def answer(database: Any, user_id: Any, community_id: Any, said: Any) -> dict:
    """POST /v2/me/community-offer: Join or Not now, once."""
    me, community = str(user_id), _uuid(community_id)
    if said not in ("join", "not_now"):
        raise ChatsError("BAD_REQUEST", "Say join or not_now.", 400)
    row = _offers(database, me).get(community or "")
    if not community or not row:
        raise _not_found()
    joined = said == "join"
    if not row.get("answer"):
        if joined:
            _join(database, community, me)
        _table(database, OFFERS).update({"answer": "joined" if joined else "not_now",
                                         "answered_at": _now()}) \
            .eq("user_id", me).eq("community_id", community).execute()
    else:
        joined = row["answer"] == "joined"
    return {"offer": None, "joined": joined}
