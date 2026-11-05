"""WillpowerLab by invitation (founder, 4 November 2026, decisions log N471).

A person's link is the only way in. Without one, a person signs up to join
the waitlist, one email reaches the founder's inbox, and the founder answers
by replying with his own link. Until someone joins through a link they can
sign in, but they cannot start a project, record, or talk to Will.

NOTHING NEW IS STORED (N471 item 9). Membership is read from what is already
kept:

  * the switch is off (``INVITE_ONLY_SINCE`` set to "off"): everyone is a
    member, as before; unset, it is on from ``GO_LIVE`` (N480);
  * an admin or an allowlisted coach;
  * an account made before the switch (every user of today counts as
    invited by the founder, N470 item 3);
  * an account that joined through someone else's link: a chat made through
    a link records the link (``chat_threads.link_id``), and a replaced link
    keeps its row (``chat_links.revoked_at``);
  * an account that has a Take from before the switch: a guest who recorded
    then and signs up later is let in once (N471 item 11).

Everyone else is on the waitlist. ``status`` answers the app (``GET
/v2/me/access``) and sends the waitlist email once; ``refusal`` is the one
answer the routes give a waiting account or a guest; ``link_is_full`` keeps
a link to its daily number of joins (N471 item 7).

A member stays a member, so a YES is remembered for the life of the process;
a NO only for a short while, so a person who joins is let in at once. A
lookup that fails lets the person through and is logged: the loop is never
broken by an outage of this check (CLAUDE.md, Never 3).

No provider call and no recording here. The waitlist flag lives in the
account's own ``app_metadata`` and goes with the account.
"""
from __future__ import annotations

import html
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The answer to a waiting account, and to a guest, while the switch is on.
WAITLIST = "WAITLIST"
INVITE_ONLY = "INVITE_ONLY"

#: The moment invite-only began (founder, 4 November 2026, N480): noon, so
#: nobody who signed up that morning under the open rules waits. The
#: INVITE_ONLY_SINCE setting wins when it is set; set to "off" (or empty), the
#: switch is off and everyone is a member.
GO_LIVE = "2026-11-04T12:00:00Z"

_NO_TTL_S = 20.0
_lock = threading.Lock()
_members: set[str] = set()
_not_yet: dict[str, float] = {}


def since() -> Optional[datetime]:
    """The moment invite-only began, or None while it is off."""
    setting = os.getenv("INVITE_ONLY_SINCE")
    raw = GO_LIVE if setting is None else setting.strip()
    if not raw or raw.lower() == "off":
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.error("membership: INVITE_ONLY_SINCE=%r is not an ISO time; invite-only is off", raw)
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def on() -> bool:
    return since() is not None


def daily_limit() -> int:
    try:
        return max(1, int(os.getenv("INVITE_LINK_DAILY_LIMIT") or "10"))
    except ValueError:
        return 10


def forget() -> None:
    """Tests and a changed switch: forget every remembered answer."""
    with _lock:
        _members.clear()
        _not_yet.clear()


def _at(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _rows(result: Any) -> list[dict]:
    data = getattr(result, "data", None)
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _auth_user(user_id: str) -> Any:
    from services.db import new_client
    return new_client().auth.admin.get_user_by_id(user_id).user


def _staff(user_id: str) -> bool:
    """An admin or a coach. Those checks read the signed-in caller's own
    token, so they answer only for the caller, never for someone else."""
    try:
        from flask import has_request_context, request
        if not has_request_context() or str(getattr(request, "user_id", "")) != user_id:
            return False
        from routes.admin import is_admin, is_coach
        return bool(is_admin(user_id) or is_coach(user_id))
    except Exception:  # noqa: BLE001 -- outside a request there is no staff
        return False


def joined_through_a_link(database: Any, user_id: str) -> bool:
    """True when the person is in a chat made through someone else's link."""
    client = database.client
    seats = _rows(client.table("chat_members").select("thread_id").eq("user_id", user_id).execute())
    threads = [str(s["thread_id"]) for s in seats if s.get("thread_id")]
    if not threads:
        return False
    made = _rows(client.table("chat_threads").select("id,link_id").in_("id", threads).execute())
    links = [str(t["link_id"]) for t in made if t.get("link_id")]
    if not links:
        return False
    owners = _rows(client.table("chat_links").select("id,user_id").in_("id", links).execute())
    return any(str(o.get("user_id")) != user_id for o in owners)


def _take_before(database: Any, user_id: str, moment: datetime) -> bool:
    first = _rows(database.client.table("v2_sessions").select("id,created_at")
                  .eq("user_id", user_id).order("created_at").limit(1).execute())
    made = _at(first[0].get("created_at")) if first else None
    return bool(made and made < moment)


def is_member(database: Any, user_id: Any, *, account_made: Any = None) -> bool:
    """Whether this signed-in account may use WillpowerLab (the rule above)."""
    moment = since()
    if moment is None or not user_id:
        return moment is None
    uid = str(user_id)
    with _lock:
        if uid in _members:
            return True
        if _not_yet.get(uid, 0.0) > time.monotonic():
            return False
    try:
        made = _at(account_made)
        if made is None:
            made = _at(getattr(_auth_user(uid), "created_at", None))
        member = bool(
            (made is not None and made < moment)
            or _staff(uid)
            or joined_through_a_link(database, uid)
            or _take_before(database, uid, moment))
    except Exception:  # noqa: BLE001 -- an outage never breaks the loop
        logger.warning("membership: could not read %s; letting them through", uid, exc_info=True)
        return True
    with _lock:
        if member:
            _members.add(uid)
            _not_yet.pop(uid, None)
        else:
            _not_yet[uid] = time.monotonic() + _NO_TTL_S
    return member


def admitted(user_id: Any) -> None:
    """A join just let this person in: no need to ask again."""
    if user_id:
        with _lock:
            _members.add(str(user_id))
            _not_yet.pop(str(user_id), None)


def refusal(database: Any, user_id: Any) -> Optional[tuple[dict, int]]:
    """None when the caller may go on; else the one answer the routes give:
    403 WAITLIST to a waiting account, 401 INVITE_ONLY to a guest."""
    if not on():
        return None
    if not user_id:
        return ({"code": INVITE_ONLY,
                 "error": "WillpowerLab is by invitation. Sign in to continue."}, 401)
    if is_member(database, user_id):
        return None
    return ({"code": WAITLIST, "error": "This account is on the waitlist."}, 403)


def link_is_full(database: Any, owner_id: str, joiner_id: str) -> bool:
    """True when the owner's links already let in the day's number of people
    and the joiner is not yet a member: the joiner goes to the waitlist."""
    if not on() or is_member(database, joiner_id):
        return False
    client = database.client
    links = [str(r["id"]) for r in _rows(client.table("chat_links").select("id")
                                         .eq("user_id", owner_id).execute()) if r.get("id")]
    if not links:
        return False
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    made = _rows(client.table("chat_threads").select("id,created_at").in_("link_id", links).execute())
    today = sum(1 for t in made if (_at(t.get("created_at")) or day_ago) > day_ago)
    return today >= daily_limit()


# ── The app's question, and the one waitlist email ─────────────────────────

def _provider(user: Any) -> str:
    meta = getattr(user, "app_metadata", None) or {}
    names = {"google": "Google", "linkedin_oidc": "LinkedIn", "apple": "Apple",
             "email": "Email", "phone": "WhatsApp"}
    raw = str(meta.get("provider") or "")
    return names.get(raw, raw.capitalize() or "Email")


def _name(user: Any) -> str:
    meta = getattr(user, "user_metadata", None) or {}
    for key in ("full_name", "name"):
        if str(meta.get(key) or "").strip():
            return str(meta[key]).strip()
    email = str(getattr(user, "email", "") or "")
    return email.split("@")[0] if email else "Someone"


def _send_waitlist_email(user: Any) -> bool:
    """The one email to the founder's inbox (signed words, N471 item 5)."""
    from config import Config
    from services.email_service import send_email_resend

    name = _name(user)
    email = str(getattr(user, "email", "") or "")
    phone = str(getattr(user, "phone", "") or "")
    when = _at(getattr(user, "created_at", None)) or datetime.now(timezone.utc)
    rows = [("Name", name), ("Email", email or "(none)"),
            ("Joined the waitlist", f"with {_provider(user)}, {when:%d %b %Y, %H:%M} UTC")]
    if phone:
        rows.insert(2, ("WhatsApp", phone))
    subject = f"{name} wants to join WillpowerLab"
    lines = "".join(f"<tr><td style='color:#737373;padding:2px 12px 2px 0'>{html.escape(k)}</td>"
                    f"<td>{html.escape(v)}</td></tr>" for k, v in rows)
    body = (f"<p style='font-size:16px'><b>{html.escape(subject)}</b></p>"
            f"<table style='font-size:14px'>{lines}</table>"
            f"<p style='font-size:14px'>To let {html.escape(name)} in, reply with your link.</p>")
    text = "\n".join([subject, ""] + [f"{k}: {v}" for k, v in rows]
                     + ["", f"To let {name} in, reply with your link."])
    headers = {"Reply-To": email} if email else None
    result = send_email_resend(to=Config.WAITLIST_INBOX, subject=subject, html=body,
                               text=text, headers=headers)
    return not (isinstance(result, dict) and result.get("sent") is False)


def status(database: Any, user_id: str) -> dict:
    """GET /v2/me/access: {"member": bool, "invite_only": bool}. A waiting
    account's first ask sends the waitlist email, once."""
    if not on():
        return {"member": True, "invite_only": False}
    # A remembered YES answers at once. This is the question the app waits on
    # behind a full-screen loader before /chat opens, and a member's answer
    # never needs the account: only a waiting account's email does.
    with _lock:
        known = str(user_id) in _members
    if known:
        return {"member": True, "invite_only": True}
    try:
        user = _auth_user(user_id)
    except Exception:  # noqa: BLE001 -- see is_member: never break the loop
        logger.warning("membership: no auth user for %s; letting them through", user_id, exc_info=True)
        return {"member": True, "invite_only": True}
    if is_member(database, user_id, account_made=getattr(user, "created_at", None)):
        return {"member": True, "invite_only": True}
    meta = dict(getattr(user, "app_metadata", None) or {})
    if not meta.get("waitlist_emailed_at"):
        try:
            if _send_waitlist_email(user):
                from services.db import new_client
                meta["waitlist_emailed_at"] = datetime.now(timezone.utc).isoformat()
                new_client().auth.admin.update_user_by_id(user_id, {"app_metadata": meta})
        except Exception:  # noqa: BLE001 -- the next ask tries again
            logger.error("membership: the waitlist email for %s failed", user_id, exc_info=True)
    return {"member": False, "invite_only": True}
