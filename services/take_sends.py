"""Sending a Take to the people you tick (founder, the Claude Code chat, 4
November 2026, N470 and N479). No table of its own: each Take sent is a
message of kind ``take`` (migration a_chat_carries_a_take) in the sender's
chat with each person, and the choice is kept on the speaker's own line
under the recording in the Lounge (``metadata.share``, the N309 precedent:
the line is the record).

  * ``people``: whom the speaker can send to: the other person of each of
    their chats with a real person (no demo, no guest, nobody blocked either
    way, N466), the person sent to last first ("Last sent"), then the list
    of chats' order. A speaker with no chat with a person at all gets the
    founder (N479 item 7), with no chat yet: it is made on the first send,
    never on a read. The founder's account is the one with
    ``Config.ADMIN_EMAIL``, found once per process; the optional
    ``FOUNDER_CHAT_USER_ID`` wins when set.
  * ``last``: the speaker's last choice, for the screen's default.
  * ``send``: the caller's own Take, as their own message in their chat with
    each person chosen. Idempotent (each message's id is uuid5 of the Take
    and the chat): a retry or a second tap never posts twice, and a later
    call only adds people (N479 item 3); nothing is ever unsent. Each new
    message tells the receiver by the chats' push, "{name} sent you Take
    {n}" (N470).
  * ``opened``: what the receiver opens ("Open Take"): the Take's recording
    and its words slide by slide, for a member of that chat only; never its
    Ideal Text, feedback, moments or levels (Never 1, 2; N479 item 8).

Behind ``Config.TAKE_SEND_ENABLED`` (default off): while off, the reads
answer ``{"enabled": false}``, the send 409 SENDING_OFF, and nothing here
reads or writes anything. No provider call and no new recording: the Take
was recorded and uploaded through the processing-authorization path
already, and its route asks the recording consent again (routes/v2/chats.py),
as an answer's does. Deleted with the account: the messages go with the
sender's memberships (services/data_purge_registry.py), and the receiver's
audio answers 404 once the Take is gone.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from config import Config
from services import chats
from services.chats import MEMBERS, MESSAGES, RECORDINGS, SESSIONS, ChatsError, _rows, _table
from services.rewrite_declines import instant

logger = logging.getLogger(__name__)

#: The founder as the list names him until his profile says otherwise
#: (N470: "Artur, speaking coach").
FOUNDER_NAME, FOUNDER_TITLE = "Artur", "speaking coach"
PROFILES = "people_profiles"
#: How many of the speaker's newest share lines are looked at.
_LINES_READ = 10


def is_on() -> bool:
    return bool(Config.TAKE_SEND_ENABLED)


#: The founder's account id by admin email, per process: {email: (id, at)}.
#: A miss is asked again after ``_MISS_RETRY_S``; a hit is kept.
_FOUNDER_IDS: dict[str, tuple[Optional[str], float]] = {}
_MISS_RETRY_S = 600.0


def _founder(database: Any) -> Optional[str]:
    """The founder's account id: ``FOUNDER_CHAT_USER_ID`` when set (optional),
    else the account with ``ADMIN_EMAIL``. None when neither finds anybody;
    never raises."""
    if Config.FOUNDER_CHAT_USER_ID:
        return chats._uuid(Config.FOUNDER_CHAT_USER_ID)
    email = str(getattr(Config, "ADMIN_EMAIL", "") or "").strip().lower()
    if not email:
        return None
    cached = _FOUNDER_IDS.get(email)
    if cached and (cached[0] or time.monotonic() - cached[1] < _MISS_RETRY_S):
        return cached[0]
    try:
        found = chats._uuid(database.v2_find_user_id_by_email(email))
    except Exception:
        logger.warning("take_sends: the founder's account not found by email", exc_info=True)
        found = None
    _FOUNDER_IDS[email] = (found, time.monotonic())
    return found


def _off() -> ChatsError:
    return ChatsError("SENDING_OFF", "Sending a Take is not on yet.", 409)


# ── Whom the speaker can send to ─────────────────────────────────────────

def _profiles(database: Any, user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    try:
        return {str(r["user_id"]): r for r in _rows(
            _table(database, PROFILES).select("user_id,name,role,photo_type")
            .in_("user_id", user_ids))}
    except Exception:
        logger.warning("take_sends: profiles not read", exc_info=True)
        return {}


def _last_sent_chat(database: Any, my_member_ids: list[str]) -> Optional[str]:
    """The chat of the speaker's newest Take sent, or None."""
    if not my_member_ids:
        return None
    rows = _rows(_table(database, MESSAGES).select("thread_id,created_at")
                 .in_("author_member_id", my_member_ids).eq("kind", "take")
                 .order("created_at", desc=True).limit(1))
    return str(rows[0]["thread_id"]) if rows else None


def _person_chats(database: Any, user_id: str) -> tuple[dict[str, str], list[str], dict[str, dict]]:
    """({chat: my membership id}, the chats with a real person in the list
    of chats' order, {chat: the other member's row}). A real person: not a
    demo chat, the other member an account that is not mine."""
    mine = {str(m["thread_id"]): str(m["id"]) for m in chats._memberships(database, user_id)}
    if not mine:
        return mine, [], {}
    order = [c["id"] for c in chats.list_chats(database, user_id)["chats"]]
    ids = list(mine)
    demo = {str(t["id"]) for t in _rows(_table(database, chats.THREADS).select("id,demo_user_id")
                                        .in_("id", ids)) if t.get("demo_user_id")}
    others: dict[str, dict] = {}
    for m in _rows(_table(database, MEMBERS).select("id,thread_id,user_id,display_name,subtitle")
                   .in_("thread_id", ids)):
        if str(m["id"]) != mine.get(str(m["thread_id"])):
            others.setdefault(str(m["thread_id"]), m)
    real = [t for t in order if t in mine and t not in demo
            and (others.get(t) or {}).get("user_id") and str(others[t]["user_id"]) != user_id]
    return mine, real, others


def _unblocked(database: Any, chats_: list[str], mine: dict[str, str],
               others: dict[str, dict]) -> list[str]:
    """The chats where nobody blocked anybody, either way (N466)."""
    from services import chat_safety
    spans = chat_safety.spans_by_member(
        database, [mine[t] for t in chats_] + [str(others[t]["id"]) for t in chats_])

    def blocks(member_id: str) -> bool:
        return chat_safety.blocking({"blocked_spans": spans.get(member_id, [])})
    return [t for t in chats_ if not blocks(mine[t]) and not blocks(str(others[t]["id"]))]


def _the_founder(database: Any, user_id: str) -> list[dict]:
    """The founder, for a speaker with no chat with a person (N479 item 7),
    with no chat yet; nobody when no account has the admin email (and the
    optional FOUNDER_CHAT_USER_ID is unset)."""
    founder = _founder(database)
    if not founder or founder == user_id:
        return []
    profile = _profiles(database, [founder]).get(founder) or {}
    return [{"user_id": founder, "name": profile.get("name") or FOUNDER_NAME,
             "title": profile.get("role") or FOUNDER_TITLE, "avatar_url": None,
             "chat_id": None, "last_sent": False, "me": None}]


def _people(database: Any, user_id: str) -> list[dict]:
    """[{user_id, name, title, avatar_url, chat_id, last_sent, me}], ``me``
    being the speaker's own membership of that chat (None for the founder
    before his chat is made)."""
    mine, real, others = _person_chats(database, user_id)
    if not real:
        return _the_founder(database, user_id)
    open_ = _unblocked(database, real, mine, others)
    profiles = _profiles(database, [str(others[t]["user_id"]) for t in open_])
    last = _last_sent_chat(database, list(mine.values()))
    people = []
    for t in open_:
        other = others[t]
        profile = profiles.get(str(other["user_id"])) or {}
        people.append({
            "user_id": str(other["user_id"]),
            "name": profile.get("name") or other.get("display_name") or "",
            "title": profile.get("role") or other.get("subtitle") or None,
            "avatar_url": f"/api/v2/chats/{t}/profile/photo" if profile.get("photo_type") else None,
            "chat_id": t, "last_sent": t == last, "me": mine[t]})
    people.sort(key=lambda p: not p["last_sent"])
    return people


def _public(person: dict) -> dict:
    return {k: person[k] for k in ("user_id", "name", "title", "avatar_url", "chat_id", "last_sent")}


def people(database: Any, user_id: Any) -> dict:
    """GET /v2/user/takes/send/people: {enabled, people: [{user_id, name,
    title, avatar_url, chat_id, last_sent}]}."""
    if not is_on():
        return {"enabled": False}
    user = chats._require(database, user_id)
    return {"enabled": True, "people": [_public(p) for p in _people(database, user)]}


# ── The choice, on the line under the recording ──────────────────────────

def _lines(database: Any, user_id: str) -> list[dict]:
    try:
        return [r for r in database.list_lounge_share_lines(user_id, limit=_LINES_READ) or []
                if isinstance(r, dict)]
    except Exception:
        logger.warning("take_sends: share lines not read", exc_info=True)
        return []


def _people_share(metadata: Any) -> Optional[dict]:
    share = (metadata if isinstance(metadata, dict) else {}).get("share")
    if not isinstance(share, dict) or share.get("kind") != "people":
        return None
    ids = share.get("user_ids")
    names = share.get("names")
    return {"all": share.get("all") is True,
            "user_ids": [str(i) for i in ids if chats._uuid(i)] if isinstance(ids, list) else [],
            "names": [str(n) for n in names] if isinstance(names, list) else []}


def last(database: Any, user_id: Any) -> dict:
    """GET /v2/user/takes/send/last: {enabled, choice: {all, user_ids} |
    null}, the newest line that carries a choice of people."""
    if not is_on():
        return {"enabled": False}
    user = chats._require(database, user_id)
    for line in _lines(database, user):
        share = _people_share(line.get("metadata"))
        if share:
            return {"enabled": True, "choice": {"all": share["all"], "user_ids": share["user_ids"]}}
    return {"enabled": True, "choice": None}


def _written_before(line: dict, recorded_at: Any) -> bool:
    """The line was stored before the Take's row was: both times are the
    database's own clock (``lounge_messages.created_at`` and
    ``v2_sessions.created_at``, the row made at the upload), never the
    phone's. False when either is unreadable."""
    stored, recorded = instant(line.get("created_at")), instant(recorded_at)
    return stored is not None and recorded is not None and stored <= recorded


def _record_line(database: Any, user_id: str, take: str, everyone: bool,
                 sent: list[dict], recorded_at: Any) -> None:
    """The choice kept on the Take's line: the line naming this Take, else
    the newest line when it names no Take and was written before this
    recording (``recorded_at``, the Take's ``created_at``), never one
    written for a later Take: a late send (N541 item 2) can come after the
    next Take's line. Only ever adds people. Best-effort: the Take is sent
    either way, and with no line to keep it on, nothing is written."""
    lines = _lines(database, user_id)
    line = next((r for r in lines if (r.get("metadata") or {}).get("take_session_id") == take), None)
    if line is None and lines and not (lines[0].get("metadata") or {}).get("take_session_id") \
            and _written_before(lines[0], recorded_at):
        line = lines[0]
    if line is None or not line.get("client_id"):
        return
    meta = dict(line.get("metadata") or {})
    before = _people_share(meta) or {"all": False, "user_ids": [], "names": []}
    pairs = list(zip(before["user_ids"], before["names"])) \
        if len(before["names"]) == len(before["user_ids"]) else [(i, "") for i in before["user_ids"]]
    for person in sent:
        if person["user_id"] not in {i for i, _ in pairs}:
            pairs.append((person["user_id"], person["name"]))
    meta["share"] = {"kind": "people", "all": before["all"] or everyone,
                     "user_ids": [i for i, _ in pairs], "names": [n for _, n in pairs]}
    try:
        database.rewrite_lounge_message(user_id, str(line["client_id"]),
                                        str(line.get("body") or ""), meta)
    except Exception:
        logger.warning("take_sends: the choice was not kept on the line", exc_info=True)


# ── Sending ──────────────────────────────────────────────────────────────

def _the_take(database: Any, user_id: str, take: Any) -> dict:
    """The caller's own Take, uploaded, and not an answer: {session, index,
    project_title, duration_ms, created_at}; else 404 (an answer: 400)."""
    session = chats._uuid(take)
    if not session:
        raise chats._not_found()
    rows = _rows(_table(database, SESSIONS).select("id,user_id,take_index,project_id,created_at")
                 .eq("id", session).limit(1))
    if not rows or str(rows[0].get("user_id")) != user_id:
        raise chats._not_found()
    recording = chats._take_of(database, user_id, session)
    if not recording:
        raise chats._not_found()
    mine = [str(m["id"]) for m in chats._memberships(database, user_id)]
    if mine and any((r.get("meta") or {}).get("answer") for r in _rows(
            _table(database, MESSAGES).select("meta").in_("author_member_id", mine)
            .eq("kind", "voice").eq("meta->>take", session).limit(1))):
        # An answer reached its chat already (N363); it is never sent again.
        raise ChatsError("NOT_ALLOWED", "An answer is not sent as a Take.")
    project_title = None
    if rows[0].get("project_id"):
        projects = _rows(_table(database, "projects").select("display_name")
                         .eq("id", str(rows[0]["project_id"])).limit(1))
        project_title = (projects[0].get("display_name") or None) if projects else None
    try:
        ms: Optional[int] = int(recording.get("duration") or 0) * 1000 or None
    except (TypeError, ValueError):
        ms = None
    index = rows[0].get("take_index")
    return {"session": session, "index": index if isinstance(index, int) else None,
            "project_title": project_title, "duration_ms": ms,
            "created_at": rows[0].get("created_at")}


def _choice(body: Any) -> tuple[bool, list[str]]:
    payload = body if isinstance(body, dict) else {}
    everyone = payload.get("all") is True
    raw = payload.get("user_ids")
    ids = [u for u in (chats._uuid(i) for i in raw) if u] if isinstance(raw, list) else []
    if not everyone and not ids:
        raise ChatsError("NOTHING_CHOSEN", "Choose someone to send it to.")
    return everyone, ids


def _founder_chat(database: Any, user_id: str, founder: str, token_payload: Any) -> dict:
    """The speaker's chat with the founder, made now (N479 item 7) as the
    founder's join link makes one, so the chat says whose link it came
    through; without a live link, the same pair chat with none. Returns the
    speaker's membership {id, thread_id}."""
    from services import chat_links
    link = chat_links._live(database, founder)
    if link:
        thread = chat_links.join(database, user_id, link["token"], token_payload)["chat"]["id"]
    else:
        key = ":".join(sorted((founder, user_id)))
        people = [{"user_id": founder, "display_name": FOUNDER_NAME},
                  {"user_id": user_id, "display_name": chat_links.name_of(token_payload)}]
        thread = chat_links._pair_chat(database, key)
        if not thread:
            try:
                made = _rows(_table(database, chats.THREADS).insert(
                    {"kind": "team", "title": FOUNDER_NAME, "pair_key": key}))
            except Exception as e:
                if chats._UNIQUE_VIOLATION not in str(e):
                    raise
                made = []
            thread = str(made[0]["id"]) if made else chat_links._pair_chat(database, key)
        if not thread:
            raise ChatsError("NOT_SAVED", "Could not send it.", 503)
        chat_links._seat(database, thread, people)
    return chats._member_of(database, user_id, thread)


def _post_one(database: Any, me: dict, take: dict) -> str:
    """The Take as my message in this chat, once; the push only when it is
    new. Its id."""
    thread = str(me["thread_id"])
    message = str(uuid.uuid5(uuid.UUID(take["session"]), thread))
    if _rows(_table(database, MESSAGES).select("id").eq("id", message).limit(1)):
        return message
    try:
        rows = _rows(_table(database, MESSAGES).insert({
            "id": message, "thread_id": thread, "author_member_id": str(me["id"]),
            "kind": "take", "body": "",
            "meta": {"take_session_id": take["session"], "take_index": take["index"],
                     "project_title": take["project_title"],
                     "duration_ms": take["duration_ms"]}}))
    except Exception as e:
        if chats._UNIQUE_VIOLATION not in str(e):
            raise
        return message  # a second tap got there first
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    chats._tell(database, me, rows[0])
    return message


def send(database: Any, user_id: Any, take: Any, body: Any, token_payload: Any = None) -> dict:
    """POST /v2/user/takes/<take>/send {all, user_ids}: {enabled, sent:
    [{user_id, chat_id, message_id}]}. ``all``: everyone in the list now;
    else the people named that are in it (anyone else is left out
    quietly, as a block is, N466)."""
    if not is_on():
        raise _off()
    user = chats._require(database, user_id)
    the_take = _the_take(database, user, take)
    everyone, ids = _choice(body)
    listed = _people(database, user)
    chosen = listed if everyone else [p for p in listed if p["user_id"] in set(ids)]
    sent = []
    for person in chosen:
        me = ({"id": person["me"], "thread_id": person["chat_id"]} if person["me"]
              else _founder_chat(database, user, person["user_id"], token_payload))
        sent.append({"user_id": person["user_id"], "chat_id": str(me["thread_id"]),
                     "message_id": _post_one(database, me, the_take), "name": person["name"]})
    if sent:
        _record_line(database, user, the_take["session"], everyone, sent, the_take["created_at"])
    return {"enabled": True, "sent": [{k: s[k] for k in ("user_id", "chat_id", "message_id")}
                                      for s in sent]}


# ── What the receiver opens ──────────────────────────────────────────────

def opened(database: Any, user_id: Any, thread_id: Any, message_id: Any) -> dict:
    """GET /v2/chats/<id>/messages/<message_id>/take: {audio_url, duration_ms,
    slides: [{index, title, words}]} of a Take sent in this chat, for a
    member of it; 404 otherwise, and once the Take is gone. Only the
    recording and its words: never the Ideal Text, the feedback, the
    moments or any level (Never 1, 2)."""
    if not is_on():
        return {"enabled": False}
    from services import chat_safety
    user_id = chats._require(database, user_id)
    thread, message = chats._uuid(thread_id), chats._uuid(message_id)
    if not thread:
        raise chats._not_found()
    # Two rounds of reads side by side, not six in a row (founder
    # 2026-11-09: 908 ms to open a Take, 6 calls one after another). The
    # message is read beside the membership but never returned unless the
    # caller is a member of its chat.
    mine, rows = chats._side_by_side([
        lambda: _rows(_table(database, MEMBERS).select("id,thread_id,blocked_spans")
                      .eq("thread_id", thread).eq("user_id", user_id).limit(1)),
        lambda: _rows(_table(database, MESSAGES)
                      .select("id,kind,meta,author_member_id,created_at")
                      .eq("id", message).eq("thread_id", thread).limit(1)) if message else []])
    if not mine:
        raise chats._not_found()
    me = mine[0]
    row = rows[0] if rows else None
    unheard = chat_safety.unheard(str(me["id"]), me.get("blocked_spans") or [])
    if not row or row.get("kind") != "take" or unheard(row):
        raise chats._not_found()
    meta = row.get("meta") or {}
    session = chats._uuid(meta.get("take_session_id"))
    recordings, slides = chats._side_by_side([
        lambda: _recording(database, row, session),
        lambda: _slides(database, str(session)) if session else []])
    if not recordings or not (recordings[0].get("storage_path") or recordings[0].get("audio_url")):
        raise chats._not_found()
    from services.snippet_audio_url import recording_playback_url
    try:
        audio_url = recording_playback_url(recordings[0], database, Config)
    except Exception:
        logger.warning("take_sends: no playable link for message %s", message, exc_info=True)
        audio_url = None
    return {"audio_url": audio_url, "duration_ms": meta.get("duration_ms"),
            "slides": slides}


def _recording(database: Any, row: dict, session: Optional[str]) -> list[dict]:
    """The Take's recording, only when its author recorded it."""
    authors = _rows(_table(database, MEMBERS).select("user_id")
                    .eq("id", str(row["author_member_id"])).limit(1))
    owner = str(authors[0].get("user_id") or "") if authors else ""
    if not session or not owner:
        return []
    return _rows(_table(database, RECORDINGS)
                 .select("storage_path,audio_url,recording_origin,duration")
                 .eq("session_v2_id", session).eq("user_id", owner).limit(1))


def _slides(database: Any, session: str) -> list[dict]:
    """The Take's words slide by slide, [] while it is processing."""
    try:
        rows = _rows(_table(database, SESSIONS).select("id,slide_transcripts")
                     .eq("id", session).limit(1))
    except Exception:
        logger.warning("take_sends: the Take's words could not be read", exc_info=True)
        return []
    parts = rows[0].get("slide_transcripts") if rows else None
    if not isinstance(parts, list):
        return []
    out = []
    for p in sorted((p for p in parts if isinstance(p, dict)), key=lambda p: int(p.get("index") or 0)):
        title = p.get("title")
        out.append({"index": int(p.get("index") or 0),
                    "title": title.strip() or None if isinstance(title, str) else None,
                    "words": str(p.get("transcript") or "").strip()[:chats.MAX_WORDS]})
    return out
