"""The website chat is the host's own chat, on the public side (founder, the
Claude Code chat, 9 November 2026, N591; amends N567 items 4 and 5 and N569
items 2, 4 and 5). Table: chat_widget_guests and chat_threads.widget_owner_id
(migration a_person_s_chat_opens_on_a_website).

The line a person pastes on their site, ``<script src=".../w.js"
data-link="<token>">``, carries their link's token (services/chat_links.py),
so a new link, or a link switched off, stops every pasted line with it. The
chat runs in an iframe on willpowerlab.com (``/w/<token>``). Anyone on the
site can write to the host (N591 item 1):

  * ``preview``: whose chat it is, the host's welcome and how a visitor may
    write, from the chat's recipe (N591 item 2): ``{"name", "welcome",
    "writes": {"tap", "type", "record"}}``; 404 for a wrong, replaced or
    switched-off link. No fixed questions (N591 item 5).
  * ``start``: no card before a visitor writes (N595 item 1): the chat is
    made with the visitor's first message, or their first tap. It is in the
    host's list like any other, named "Widget / Visitor {n}" with "From
    {site}" under it (N567 item 6, N591 item 1), and begins with the host's
    welcome and the host's own questions, as for anyone who joins (N590
    item 2). The answer carries the visitor's secret, ``<guest
    id>.<secret>``, which only their browser keeps; its hash is kept here.
    Agreeing comes with the sign-up (its Terms and Privacy line, N595).
  * ``read``: the visitor's chat. Until they sign up, the host's answers wait
    behind the sign-up (N591 item 4): ``sign_up`` says the step is due,
    ``answered`` that an answer is waiting for it.
  * ``answer_setup``: a tap on one of the host's questions.
  * ``write``: the visitor's own message, as the chat's setup lets them
    write: one of the three emoji (a tap), or typed words when the setup
    allows typing. Recording waits for the sign-up (below).
  * ``recording``: an answer's voice, for a visitor who has signed up.
  * ``sign_up``: after asking, the visitor signs in (phone, email, Google or
    another sign-in, N591 item 4) and takes their seat: the chat is theirs,
    as for anyone who joined through the host's link (N471), named after
    them in the host's list. Their questions then join their bundles (N584).
  * ``first_notice``: the first answer after the sign-up goes to the phone
    or email they signed up with, once (N591 item 4).

The host answers as in any chat (N591 item 3): by recording
(routes/v2/chats.py ``/answer``) or by typing (``/messages`` with a text,
``assistants.may_type``). A question joins its bundle
(services/question_bundles.py, N584) and waits there for the host: until the
minimum is reached the assistant sends nothing (N606 item 1).

Every recording and provider call goes through the processing-authorization
path: a visitor without an account has no principal to authorize, so they
cannot record until they have signed up; after that they record as anyone in
a chat does (``/v2/chats/<id>/voice``). Typed words and taps call no
provider. A widget's chats never set chat_threads.link_id, so they do not
count toward the day's joins through a link (services/membership.py
``link_is_full``). Deleted with the host's account: the purge registry
takes the chats by ``widget_owner_id``, and the guest rows go with them.
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
#: The hidden switch (ring row; see ``shown``).
WEBSITE_CHAT = "website_chat"
#: A visitor's typed words are a question for the host, answerable however it
#: arrived (N591 item 3): marked as the app marks a question
#: (services/chats.py ``post_answer`` with ``asks``), so the host's thread
#: offers its answer.
QUESTION = {"question": True, "record_answer": True}
#: How the visitor is named in the host's list (N567 item 6, signed; N591
#: item 1 keeps "From {site}"): before the sign-up, then by their own name.
VISITOR = "Widget / Visitor {n}"
SIGNED_UP = "Widget / {name}"
FROM = "From {site}"
#: The first notice of the answer (N591 item 4), signed (N595 item 2,
#: Never 4). The email's subject is the line's first sentence; the link
#: follows the line, as a link and not as words.
NOTICE_LINE = "{name} answered your question. Open it in WillpowerLab."
NOTICE_SUBJECT = "{name} answered your question."
#: Random bytes in a visitor's secret.
SECRET_BYTES = 24
#: The longest message a visitor or the host types.
MAX_TEXT = 2000
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


def shown(database: Any, owner: Any) -> bool:
    """Is the website chat switched on for this host? The ring row
    ``website_chat``: no row until the founder makes one, so it is off for
    everyone (N569 item 1, N591 item 6: hidden until its words are signed,
    Never 4). Off, every public route answers 404, as for a wrong link."""
    from services import rings
    try:
        return bool(owner) and rings.feature_is_on_for_user(WEBSITE_CHAT, str(owner), database=database)
    except Exception:  # noqa: BLE001 -- a failed read keeps it hidden
        logger.warning("chat_widget: the switch could not be read; hidden", exc_info=True)
        return False


def _link(database: Any, token: Any) -> dict:
    """The live link with this token, its owner a member (N471) with the
    website chat switched on; else 404, as the join page answers."""
    from services import membership
    from services.chat_links import _open
    link = _open(database, token)
    if not shown(database, link["user_id"]) or not membership.is_member(database, str(link["user_id"])):
        raise _not_found()
    return link


def writes(database: Any, owner: str, *, signed_up: bool = False) -> dict:
    """How a visitor may write, from the host's recipe (N591 item 2; N578
    item 5): tap, type, record. Recording only once they have signed up,
    when the processing-authorization path has a principal to ask."""
    from services import assistants
    allowed = assistants.answer_with_of(database, owner)
    return {"tap": allowed["tap"], "type": allowed["type"],
            "record": allowed["record"] and signed_up}


def preview(database: Any, token: Any) -> dict:
    """GET /v2/chats/widget/<token>: {"name", "welcome", "writes"}: what the
    visitor sees before they write, with no card (N595 item 1); the welcome
    is the host's own (N590 item 2), the same lines ``start`` posts."""
    from services import assistants
    link = _link(database, token)
    owner = str(link["user_id"])
    recipe = assistants.recipe_of(database, owner) if assistants.on(database, owner) else None
    return {"name": link["display_name"], "welcome": list((recipe or {}).get("welcome") or []),
            "writes": writes(database, owner)}


def _number(database: Any, owner: str) -> int:
    return len(_rows(_table(database, GUESTS).select("id").eq("owner_user_id", owner))) + 1


def start(database: Any, token: Any, site: Any, first: Any = None) -> dict:
    """POST /v2/chats/widget/<token>/start {"site", "kind"?, "body"?}: the
    visitor's chat with the host, made at their first message or first tap,
    with no card before it (N595 item 1); the host's welcome and questions
    first, then ``first``, the visitor's message, as ``write`` takes it.
    {"guest": the visitor's secret, then what ``read`` answers}. A first
    message the chat does not take is refused before anything is made."""
    message = first if isinstance(first, dict) and first.get("body") is not None else None
    from services import assistants, join_questions
    link = _link(database, token)
    owner = str(link["user_id"])
    if message is not None:
        _checked(message, writes(database, owner))
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
    # As for anyone who joins through the host's link (chat_links.join): the
    # host's welcome first (N590 item 2), then their own questions (N487).
    assistants.welcome(database, thread, owner, str(owner_seat["id"]))
    join_questions.begin_for_visitor(database, thread, owner, str(owner_seat["id"]),
                                     str(visitor_seat["id"]))
    guest = f"{guests[0]['id']}.{secret}"
    if message is not None:
        write(database, token, guest, message)
    return {"guest": guest, **read(database, token, guest)}


def _visitor(database: Any, token: Any, guest: Any) -> dict:
    """The visitor's seat for this link and secret; 404 otherwise, the same
    for a wrong secret, a replaced link and a chat that has gone."""
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
            "guest_id": gid, "signed_up": bool(row.get("kept_at")),
            "owner": str(link["user_id"]), "name": link["display_name"]}


def _the_host_s(row: dict, me: str) -> bool:
    """A message from the host that answers (not their welcome, not their
    questions): what waits behind the sign-up (N591 item 4)."""
    meta = row.get("meta") or {}
    return str(row["author_member_id"]) != me and not any(
        k in meta for k in ("welcome", "setup", "setup_answer", "setup_card"))


def _asked(rows: list[dict], me: str) -> bool:
    """The visitor has written something of their own (not a tap on the
    host's questions): the sign-up is due after asking (N591 item 4)."""
    return any(str(r["author_member_id"]) == me and "setup_answer" not in (r.get("meta") or {})
               for r in rows)


def read(database: Any, token: Any, guest: Any) -> dict:
    """GET /v2/chats/widget/<token>/messages: {"name", "writes", "messages",
    "signed_up", "notice_to", "sign_up", "answered"}, oldest first, as the
    visitor sees them; ``notice_to`` ("email" | "phone", once signed up) is
    where the first notice goes. Before the sign-up the host's answers are not in ``messages``:
    ``answered`` says one waits, ``sign_up`` that the step is due."""
    from services import join_questions
    me = _visitor(database, token, guest)
    thread = me["thread_id"]
    newest = _rows(_table(database, MESSAGES)
                   .select("id,author_member_id,kind,body,meta,created_at")
                   .eq("thread_id", thread).order("created_at", desc=True).limit(_MAX_MESSAGES))
    newest = [r for r in newest if not _held(r) and not join_questions.hidden(r, me["id"])]
    waiting = [] if me["signed_up"] else [r for r in newest if _the_host_s(r, me["id"])]
    shown = [r for r in newest if r not in waiting]
    authors = _authors(database, thread)
    words = _words(database, thread, shown)
    answers = _answers(database, shown)
    return {"name": me["name"], "writes": writes(database, me["owner"], signed_up=me["signed_up"]),
            "signed_up": me["signed_up"],
            "notice_to": _notice_to_of(database, me) if me["signed_up"] else None,
            "sign_up": not me["signed_up"] and _asked(newest, me["id"]),
            "answered": bool(waiting),
            "messages": [_shown(r, me["id"], authors, words, answers) for r in reversed(shown)]}


def answer_setup(database: Any, token: Any, guest: Any, message_id: Any, payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/setup/<message_id> {"picked", "date"?}:
    the visitor's tap on one of the host's questions."""
    from services import join_questions
    me = _visitor(database, token, guest)
    return join_questions.answer_as(database, me, None, message_id, payload)


def _checked(payload: Any, allowed: dict) -> tuple[str, str]:
    """A visitor's message as the chat takes it, ``(kind, body)``, or 400:
    an emoji is a tap; typed words need the setup's typing (N591 item 2)."""
    body = payload if isinstance(payload, dict) else {}
    kind = body.get("kind") or "emoji"
    sent = body.get("body")
    if kind == "emoji":
        if not isinstance(sent, str) or sent not in EMOJI:
            raise ChatsError("NOT_ALLOWED", "Only 👍, 👀 or 🙏 for now.")
        return kind, sent
    if kind == "text" and allowed["type"]:
        words = " ".join(str(sent or "").split())
        if not words or len(words) > MAX_TEXT:
            raise ChatsError("NOT_ALLOWED", f"Write 1 to {MAX_TEXT} characters.")
        return kind, words
    raise ChatsError("NOT_ALLOWED", "This chat is not answered that way.")


def write(database: Any, token: Any, guest: Any, payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/messages {"kind": "emoji" | "text",
    "body"}: the visitor's own message, as the chat's setup lets them write
    (N591 item 2). {"message", "sign_up"}."""
    me = _visitor(database, token, guest)
    kind, said = _checked(payload, writes(database, me["owner"], signed_up=me["signed_up"]))
    if kind == "emoji":
        message = _post(database, me, "emoji", said, {"label": EMOJI[said]})
    else:
        message = _post(database, me, "text", said, dict(QUESTION))
        if me["signed_up"]:
            asker = _seat_user(database, me["id"])
            if asker:
                bundle(database, me["owner"], asker, me["thread_id"], message["id"], said)
    return {"message": message, "sign_up": not me["signed_up"]}


def _post(database: Any, me: dict, kind: str, body: str, meta: dict) -> dict:
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": me["thread_id"], "author_member_id": me["id"], "kind": kind,
        "body": body, "meta": meta}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, rows[0])
    return _shown(rows[0], me["id"], _authors(database, me["thread_id"]))


def recording(database: Any, token: Any, guest: Any, message_id: Any) -> dict:
    """GET /v2/chats/widget/<token>/messages/<message_id>/audio: an answer's
    voice (its Take's own recording), or a voice note, in the visitor's chat,
    once they have signed up; 404 otherwise, as for a message not theirs."""
    me = _visitor(database, token, guest)
    message = _uuid(message_id)
    if not message or not me["signed_up"]:
        raise _not_found()
    rows = _rows(_table(database, AUDIO).select("content_type,audio")
                 .eq("message_id", message).eq("thread_id", me["thread_id"]).limit(1))
    audio = _bytes(rows[0].get("audio")) if rows else b""
    if audio:
        return {"content_type": rows[0].get("content_type") or "audio/webm", "audio": audio}
    return _answer_recording(database, me["thread_id"], message)


def _seat_user(database: Any, member_id: str) -> Optional[str]:
    rows = _rows(_table(database, MEMBERS).select("user_id").eq("id", member_id).limit(1))
    return str(rows[0]["user_id"]) if rows and rows[0].get("user_id") else None


def sign_up(database: Any, user_id: Any, token: Any, guest: Any, token_payload: Any) -> dict:
    """POST /v2/chats/widget/<token>/sign-up, signed in: after asking, the
    visitor has signed in with a phone, email, Google or another sign-in
    (N591 item 4). They take the visitor's seat; the chat is theirs from now
    on, named after them in the host's list ("From {site}" stays under it),
    and their questions join their bundles (N584). {"chat": {"id"}, then what
    ``read`` answers}, or {"waitlist": true} past the day's joins (N471 item
    7). The host signing up on their own visitor's chat is 400."""
    from services import membership
    from services.chat_links import _NO_NAME, name_of
    me = _visitor(database, token, guest)
    uid = str(user_id or "")
    if not uid:
        raise _not_found()
    if uid == me["owner"]:
        raise ChatsError("OWN_LINK", "This is your own link.")
    if not me["signed_up"]:
        if membership.link_is_full(database, me["owner"], uid):
            return {"waitlist": True}
        seat: dict[str, Any] = {"user_id": uid}
        name = name_of(token_payload)
        if name != _NO_NAME:  # a phone sign-in has no name: "Widget / Visitor {n}" stays
            seat["display_name"] = SIGNED_UP.format(name=name)
        _table(database, MEMBERS).update(seat).eq("id", me["id"]).execute()
        _table(database, GUESTS).update({"kept_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", me["guest_id"]).execute()
        membership.admitted(uid)
        _bundle_asked(database, me, uid)
    told = notice_to(token_payload)
    if told:
        _NOTICE_TO[me["guest_id"]] = told
    return {"chat": {"id": me["thread_id"]}, **read(database, token, guest)}


#: Where each signed-up visitor's first notice goes, by guest id, so the
#: widget's polling ``read`` asks the account once (bounded; a restart asks
#: again).
_NOTICE_TO: dict[str, str] = {}
_NOTICE_TO_MAX = 10_000


def _notice_to_of(database: Any, me: dict) -> Optional[str]:
    """``notice_to`` for the widget's own read, which has no sign-in token:
    from the visitor's account, as ``_send_notice`` reads it (N595 item 2's
    line after signing up, shown in the widget's tab)."""
    known = _NOTICE_TO.get(me["guest_id"])
    if known:
        return known
    uid = _seat_user(database, me["id"])
    if not uid:
        return None
    told: Optional[str] = None
    try:
        if database.get_user_email_from_auth(uid):
            told = "email"
        else:
            from services import admin_person
            told = "phone" if (admin_person.auth_user(uid) or {}).get("phone") else None
    except Exception:  # noqa: BLE001 -- the widget reads without it
        logger.warning("chat_widget: where the notice goes could not be read", exc_info=True)
        return None
    if told:
        if len(_NOTICE_TO) >= _NOTICE_TO_MAX:
            _NOTICE_TO.clear()
        _NOTICE_TO[me["guest_id"]] = told
    return told


def notice_to(token_payload: Any) -> Optional[str]:
    """Where the first notice goes, for the line after signing up (N595 item
    2: "... comes to your phone." or "... to your email."): "email" when the
    account has one, else "phone", as ``_send_notice`` sends it."""
    payload = token_payload if isinstance(token_payload, dict) else {}
    if str(payload.get("email") or "").strip():
        return "email"
    return "phone" if str(payload.get("phone") or "").strip() else None


def _bundle_asked(database: Any, me: dict, uid: str) -> None:
    """The visitor's typed questions, asked before the sign-up, join their
    bundles now that they have an account to answer (N584 item 4, N591 item
    3); each waits there for the host (N606 item 1)."""
    try:
        rows = _rows(_table(database, MESSAGES).select("id,kind,body,meta")
                     .eq("thread_id", me["thread_id"]).eq("author_member_id", me["id"])
                     .order("created_at"))
    except Exception:  # noqa: BLE001 -- the sign-up stands either way
        logger.warning("chat_widget: the questions of %s were not read", me["thread_id"])
        return
    for r in rows:
        if r.get("kind") == "text" and "setup_answer" not in (r.get("meta") or {}):
            bundle(database, me["owner"], uid, me["thread_id"], str(r["id"]), r.get("body"))


def bundle(database: Any, host: str, asker: str, thread: str, message_id: str,
           words: Any) -> Optional[dict]:
    """A question asked of ``host`` joins its bundle (N584, N591 item 3):
    ``question_bundles.collect``, where it waits for the host (N606 item
    1). Best-effort: the question is sent either way."""
    from services import question_bundles
    try:
        return question_bundles.collect(database, host, asker, thread, message_id, words)
    except Exception:  # noqa: BLE001
        logger.warning("chat_widget: a question was not bundled (message %s)", message_id,
                       exc_info=True)
        return None


# ── The first notice (N591 item 4) ──────────────────────────────────────

def first_notice(database: Any, thread: str, sender_member: str, recipient_member: str,
                 recipient: str, sender_name: str) -> str:
    """Called for every message sent in a chat (services/chats.py
    ``_tell``), for each member it reaches. When it reaches a website
    visitor who has signed up (their seat is the guest row's), the host's
    first answer after the sign-up goes to the email they signed up with,
    or, with no email, to their phone on WhatsApp; once, in the signed words
    (N595 item 2). What happened, as a word; never raises."""
    try:
        rows = _rows(_table(database, GUESTS).select("thread_id,kept_at")
                     .eq("member_id", str(recipient_member)).limit(1))
        if not rows or not rows[0].get("kept_at") or str(rows[0]["thread_id"]) != str(thread):
            return "not_a_signed_up_visitor"
        kept = str(rows[0]["kept_at"])
        sent = _rows(_table(database, MESSAGES).select("id,meta,created_at")
                     .eq("thread_id", str(thread)).eq("author_member_id", str(sender_member)))
        answers = [r for r in sent if str(r.get("created_at") or "") >= kept
                   and not any(k in (r.get("meta") or {}) for k in ("welcome", "setup", "setup_card"))]
        if len(answers) != 1:
            return "not_the_first"
        return _send_notice(database, recipient, sender_name)
    except Exception:  # noqa: BLE001 -- the answer is sent either way
        logger.warning("chat_widget: the first notice was not sent (thread %s)", thread,
                       exc_info=True)
        return "failed"


def _send_notice(database: Any, user_id: str, name: str) -> str:
    from config import Config
    first = (str(name or "").split() or ["WillpowerLab"])[0]
    link = f"{(Config.FRONTEND_URL or '').rstrip('/')}/chat"
    line = NOTICE_LINE.format(name=first)
    email = database.get_user_email_from_auth(user_id)
    if email:
        if not Config.SEND_EMAILS:
            return "send_emails_off"
        from services.email_service import send_email_resend
        send_email_resend(to=email, subject=NOTICE_SUBJECT.format(name=first),
                          html=f'<p>{_escape(line)}</p><p><a href="{_escape(link)}">{_escape(link)}</a></p>',
                          text=f"{line}\n{link}")
        return "email"
    from services import admin_person, whatsapp_notify
    phone = (admin_person.auth_user(user_id) or {}).get("phone")
    if phone:
        number = whatsapp_notify.normalize_phone(f"+{str(phone).lstrip('+')}")
        whatsapp_notify.send_template(number, template="", params=[], text=f"{line}\n{link}")
        return "phone"
    return "no_contact"


def _escape(text: str) -> str:
    import html
    return html.escape(text)
