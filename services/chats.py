"""The chats between people, first slice (founder, the Claude Code chat, 31
October 2026, N298 to N316; prototype: the Ember & Air one kept with N298).
Tables: chat_threads, chat_members, chat_messages (migration
people_chat_with_each_other), chat_message_audio, a voice note's
recording (a_chat_voice_note_keeps_its_recording; N321 item 2), and
chat_message_files, a photo's or a file's bytes
(a_chat_keeps_its_photos_and_files; N351).

A chat is between two people (N302 item 1): a person and a colleague
(``team``) or a person and a customer (``customer``). The other member may be
a guest with no account (a customer, a demo person). Separate from the
Lounge, the chat with Will (lounge_messages), which this module never reads
and writes once only: Will's line after an answer is taken back (N441 item
5, ``undo_answer``).

  * ``list_chats``: the chats a person is in, each named for the other member
    (their name as the title, their line as the subtitle), with its last
    message; the newest first.
  * ``read``: a chat's messages, oldest first, each marked ``mine`` for the
    caller. Only for a member, a voice note with its words (N331) and an answer
    with its Take's words and when each slide starts (N355).
  * ``post``: an emoji, one of the three with one meaning each (N311 item 1):
    👍 it's good, 👀 seen, I'll answer, 🙏 thanks. Its meaning is kept as a
    clean label in ``meta``.
  * ``post_voice``: a voice note (N321 item 2: "you can always answer with
    an emoji or a mic"), up to two minutes: a message of kind ``voice`` with
    its length in ``meta``, kept with its recording; then turned into words
    (N324), kept with the recording (``words``) and going when it goes. The
    words are in the chat's messages, for its members to open under the
    player (N331: "Read it"), never in the list, and fed nowhere else. A note
    that cannot be turned into words is sent all the same, ``words`` NULL.
  * ``recording``: a voice note's recording, for any member of its chat
    (an answer's and a sent Take's: its Take's own).
  * A Take sent to the people the speaker ticked (N470, N479) is a message
    of kind ``take`` made by services/take_sends.py; the receiver's meta
    has no Take id, and its push says "{name} sent you Take {n}".
  * ``post_answer``: an answer recorded with "Record an answer" (N363), held
    on the server for its 5 seconds (N441 item 3): until then nobody else
    sees it, the list does not show it and no push goes. ``undo_answer``
    takes it back while it is held, and Will says so in the speaker's chat
    with him (N441 item 5).
  * ``post_file``: a photo (a raster image) or a file (any type), up to 10
    MB, sent from the "+" (N351): a message of kind ``photo`` or ``file``
    (a file's body is its own name, for the list's line), kept with its
    bytes. Each opens a new question for the other person (N335 item 3,
    N341 item 2): its ``meta`` says ``question``, the flag the app's mic
    reads, and so does the sender's next voice note when it follows it
    straight away, the voice note that says what they need (N337).
  * ``sent_file``: a photo's or a file's bytes, type and name, for any member
    of its chat.
  * ``seed_demo``: a customer's chat and a colleague's for the person, once,
    so the chats can be seen before anyone else is in them.

A real chat between two people is made by the join link
(services/chat_links.py, N308, N328): nothing in this module makes one.

Ring row ``chats``, ring 6 (the founder's). A person without it gets 404 from
every route. A photo or a file makes no provider call and is no recording of
the speaker, so it does not pass the processing-authorization path. One
provider call, for a voice note only: its transcription,
through the authorized provider (``AuthorizedProviderAdapter.transcribe_audio``,
the adapter the route hands ``post_voice``, as the voice notebook's notes),
never a provider SDK of its own. A voice note is a speaker's recording, so its
route (routes/v2/chats.py) passes the processing-authorization path before
``post_voice`` runs: ``phase1_provider_route``, as the voice notebook's notes,
and the recording consent a Take asks for (``require_current``, operation
"recording"); the transcription's permit is issued under that same
authority. Deleted with the account: the purge registry takes the voice notes
a person recorded, the photos and files they sent, their memberships and
their demo chats, and the messages go with them.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

THREADS, MEMBERS, MESSAGES = "chat_threads", "chat_members", "chat_messages"
AUDIO = "chat_message_audio"
#: A Take's recording row (services/lab_recording_persistence.py): its owner,
#: its session, where its audio is kept and how long it is.
RECORDINGS = "recordings"
#: A Take's row, for an answer's words and slides (N355).
SESSIONS = "v2_sessions"
#: An answer is a Take, as long as the person needs (N486 item 4, which
#: lifted N363 item 3's five minutes); a voice note stays at two
#: (MAX_VOICE_MS). Only the length the app measures, used while the Take's
#: own is not known yet, is bounded, at a day, to keep nonsense out.
MAX_ANSWER_MS = 24 * 3600 * 1000
#: An answer waits this long on the server for its Undo (N345 item 2, N441
#: item 3), counted from Finish take: the app sends what is left of it.
ANSWER_HOLD_MS = 5_000
#: And this much longer, so an Undo pressed in the last moment still lands.
_UNDO_GRACE_MS = 2_000
#: Will's line in the speaker's chat with him after an Undo (N441 item 5,
#: signed); the Take's feedback follows as for any Take.
TAKEN_BACK = "You took this one back, so {name} didn't hear it. Here's what I noticed, for practice."
_TAKEN_BACK_KEYS = uuid.UUID("6f1d2c9e-3b7a-4e55-9a0c-2d8e41b7c5f3")
FILES = "chat_message_files"
#: A voice note is up to two minutes long ...
MAX_VOICE_MS = 120_000
#: ... and up to 12 MB, what chat_message_audio holds (migration 0504).
MAX_VOICE_BYTES = 12 * 1024 * 1024
#: The longest content type chat_message_audio holds.
_MAX_TYPE_LEN = 100
#: The most of a voice note's words chat_message_audio keeps (N324).
MAX_WORDS = 20_000
#: A photo or a file is up to 10 MB, what chat_message_files holds.
MAX_FILE_BYTES = 10 * 1024 * 1024
#: The longest file name chat_message_files keeps.
_MAX_NAME_LEN = 255
#: What a photo may be: a raster image a browser shows. Never SVG, which can
#: carry a script.
PHOTO_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp",
                         "image/heic", "image/heif", "image/avif"})
#: A plain media type, type/subtype with no parameters.
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")
#: The three emoji and the label each one means (N311 item 1).
EMOJI = {"👍": "good", "👀": "seen", "🙏": "thanks"}
#: The demo customer's question, which Will marks (N361 item 1).
_DEMO_QUESTION = ("Itchy for two months, thinning at the top. I wash every day. "
                  "What should I do?")
#: The demo chats (founder only, ring 6): the guest, their line, and what
#: they said, in order.
DEMO = (
    {"kind": "customer", "name": "Sarah", "subtitle": "Customer · Invita",
     # Will's mark, made once here: it asks about a treatment (N361 item 1).
     "marked": True,
     "said": [("text", _DEMO_QUESTION)]},
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
    """Does this person have the chats? Everyone signed in does (N456: the
    list of chats is the default for everyone; was ring 6, feature
    `chats`). No ring is read."""
    del database
    return bool(user_id)


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


def member(database: Any, user_id: Any, thread_id: Any) -> dict:
    """The caller's membership of a chat, with the ring on; else 404. The
    first check of every route that names a chat."""
    return _member_of(database, _require(database, user_id), thread_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _held(row: dict) -> bool:
    """An answer still in its 5 seconds (N441 item 3): nobody sees it yet."""
    until = (row.get("meta") or {}).get("held_until")
    if not isinstance(until, str):
        return False
    try:
        return datetime.fromisoformat(until) > _now()
    except ValueError:
        return False


#: What ``_last`` reads of a chat: its newest messages, these columns.
_RECENT, _RECENT_COLUMNS = 20, "author_member_id,kind,body,meta,created_at"
_THREAD_COLUMNS = "id,kind,title,created_at,link_id"


def _recent(database: Any, thread_id: str) -> list[dict]:
    """The chat's 20 newest messages, newest first: where ``_last`` looks."""
    return _rows(_table(database, MESSAGES).select(_RECENT_COLUMNS)
                 .eq("thread_id", thread_id).order("created_at", desc=True).limit(_RECENT))


def _threads_with_recent(database: Any, ids: list[str]) -> Optional[list[dict]]:
    """The chats and each one's ``_recent`` messages in ONE read: PostgREST
    embeds a thread's messages through ``chat_messages.thread_id`` (its
    foreign key) and orders and limits them per thread, over the index on
    (thread_id, created_at). The list used to read every chat's messages on
    their own, one read per chat (N+1), up to eight at a time. Each thread
    row comes back as the threads read gives it, with its messages under
    ``MESSAGES``. None when the read fails or answers another shape; the
    caller then reads as before."""
    try:
        rows = _rows(_table(database, THREADS)
                     .select(f"{_THREAD_COLUMNS},{MESSAGES}({_RECENT_COLUMNS})")
                     .in_("id", ids)
                     .order("created_at", desc=True, foreign_table=MESSAGES)
                     .limit(_RECENT, foreign_table=MESSAGES))
    except Exception as e:  # noqa: BLE001 -- the reads one per chat follow
        logger.warning("chats: one-read list failed, reading per chat: %s", e, exc_info=True)
        return None
    if not all(isinstance(r, dict) and isinstance(r.get(MESSAGES), list) for r in rows):
        logger.warning("chats: one-read list answered another shape, reading per chat")
        return None
    return rows


def _last(rows: list[dict], unheard: Any = None, me: str = "") -> Optional[dict]:
    """The chat's newest message the caller gets, of its ``_recent`` rows:
    not an answer still held, nor one from the person they blocked, sent
    while blocked (N466). With ``mine`` (the caller sent it), and for a sent
    Take its number only (``meta.take_index``), for the list's "{name} sent
    you Take {n}" (N470); never its Take's id."""
    from services.join_questions import hidden
    row = next((r for r in rows if not _held(r) and not (unheard and unheard(r))
                and not (me and hidden(r, me))), None)
    if not row:
        return None
    last = {"kind": row["kind"], "body": row["body"], "created_at": row["created_at"],
            "mine": bool(me) and str(row.get("author_member_id")) == me}
    if row["kind"] == "take":
        last["meta"] = {"take_index": (row.get("meta") or {}).get("take_index")}
    if "setup_card" in (row.get("meta") or {}):
        # The owner's card of the joiner's answers: the list says "{name}'s
        # answers" (N487 item 7, N502 item 5).
        last["meta"] = {"setup_card": True}
    return last


#: How many of the list's reads run at once: each is one call to the
#: database, so the list waits for about the slowest, not for their sum.
_LIST_READERS = 8


def _side_by_side(calls: list) -> list:
    """Run these zero-argument reads at once; their results in the same
    order. Each keeps the request's context (its timing and its id)."""
    if len(calls) <= 1:
        return [c() for c in calls]
    with ThreadPoolExecutor(max_workers=min(_LIST_READERS, len(calls)),
                            thread_name_prefix="chats-list") as pool:
        futures = [pool.submit(copy_context().run, c) for c in calls]
        return [f.result() for f in futures]


def list_chats(database: Any, user_id: Any) -> dict:
    """GET /v2/chats: {"chats": [{id, kind, title, subtitle, last,
    joined_through}]}. ``joined_through`` is the first name of whose link the
    caller joined the chat through, while the chat has no message yet, else
    None: the row keeps "You joined through {name}'s link." until the first
    message (N488)."""
    user_id = _require(database, user_id)
    from services import chat_safety
    from services.chat_links import joined_through
    mine = {str(m["thread_id"]): str(m["id"]) for m in _memberships(database, user_id)}
    if not mine:
        return {"chats": []}
    ids = list(mine)
    # Every read below needs only the caller's memberships, so they run side
    # by side: the list waits for the slowest, not for all of them in turn.
    spans, embedded, members = _side_by_side([
        # Whom the caller blocked, and what therefore never reaches them (N466).
        lambda: chat_safety.spans_by_member(database, list(mine.values())),
        lambda: _threads_with_recent(database, ids),
        lambda: _rows(_table(database, MEMBERS).select("id,thread_id,user_id,display_name,subtitle")
                      .in_("thread_id", ids)),
    ])
    if embedded is not None:
        threads = [{k: v for k, v in t.items() if k != MESSAGES} for t in embedded]
        recent_of = {str(t["id"]): t[MESSAGES] for t in embedded}
    else:
        threads, *recent = _side_by_side([
            lambda: _rows(_table(database, THREADS).select(_THREAD_COLUMNS).in_("id", ids)),
            *[(lambda t=t: _recent(database, t)) for t in ids],
        ])
        recent_of = dict(zip(ids, recent))
    others: dict[str, dict] = {}
    for m in members:
        if str(m["id"]) != mine.get(str(m["thread_id"])):
            others.setdefault(str(m["thread_id"]), m)
    lasts: dict[str, Optional[dict]] = {}
    for t in threads:
        me = mine[str(t["id"])]
        lasts[str(t["id"])] = _last(recent_of.get(str(t["id"]), []),
                                    chat_safety.unheard(me, spans.get(me, [])), me)
    # A chat with no message yet, joined through a link: whose (N488).
    joining = [str(t["id"]) for t in threads if lasts[str(t["id"])] is None and t.get("link_id")]
    through = dict(zip(joining, _side_by_side(
        [(lambda t=t: joined_through(database, user_id, t)) for t in joining])))
    # Every person has an assistant that answers for them in the chat with
    # them, labelled as theirs (N580 items 1 and 3), for the chat builder's
    # ring (N579 item 2); a guest (a demo person, a customer) has none.
    from services import assistants, rings
    labelled = rings.feature_is_on_for_user(assistants.CHAT_BUILDER, user_id, database=database)
    chats: list[tuple[str, dict]] = []
    for t in threads:
        other = others.get(str(t["id"])) or {}
        person = labelled and t["kind"] == "team" and other.get("user_id")
        me = mine[str(t["id"])]
        last = lasts[str(t["id"])]
        chats.append(((last or t)["created_at"] or "", {
            "id": str(t["id"]), "kind": t["kind"],
            "title": other.get("display_name") or t["title"],
            "subtitle": other.get("subtitle"), "last": last,
            "joined_through": through.get(str(t["id"])),
            "assistant": assistants.assistant_name(other.get("display_name")) if person else None,
            "blocked": chat_safety.blocking({"blocked_spans": spans.get(me, [])})}))
    chats.sort(key=lambda pair: str(pair[0]), reverse=True)
    return {"chats": [chat for _, chat in chats]}


#: The line a push shows for a message: the chat list's own (ChatList.tsx
#: lastLine, N322 item 3, N351; N311 item 1's meanings). No word of ours.
_PUSH_LINE = {"voice": "🎤 Voice message", "photo": "📷"}
_EMOJI_MEANING = {"👍": "It's good", "👀": "Seen, I'll answer", "🙏": "Thanks"}
#: A Take sent to the people the speaker ticked (N470, signed).
TAKE_SENT = "{name} sent you Take {n}"


def push_line(message: dict, sender: str = "") -> str:
    kind, body = message.get("kind"), str(message.get("body") or "")
    if kind == "take":
        n = (message.get("meta") or {}).get("take_index")
        return TAKE_SENT.format(name=sender, n=n if isinstance(n, int) else "").strip()
    if kind in _PUSH_LINE:
        return _PUSH_LINE[kind]
    if kind == "file":
        return f"📄 {body}"
    if kind == "emoji":
        meaning = _EMOJI_MEANING.get(body)
        return f"{body} {meaning}" if meaning else body
    return body.splitlines()[0] if body else ""


def _tell(database: Any, me: dict, message: dict) -> None:
    """A push to everyone else in the chat (N385 item 1): the sender's name
    over the message's line, opening the chat. Best-effort, beside the send."""
    try:
        from services import push_devices
        thread = str(me["thread_id"])
        members = _rows(_table(database, MEMBERS).select("id,user_id,display_name")
                        .eq("thread_id", thread))
        sender = next((m for m in members if str(m["id"]) == str(me["id"])), {})
        name = str(sender.get("display_name") or "")
        # No push to someone who blocked the sender (N466 item 2).
        from services import chat_safety
        spans = chat_safety.spans_by_member(database, [str(m["id"]) for m in members
                                                       if str(m["id"]) != str(me["id"])])
        for other in members:
            if str(other["id"]) == str(me["id"]) or not other.get("user_id"):
                continue
            if chat_safety.blocking({"blocked_spans": spans.get(str(other["id"]), [])}):
                continue
            push_devices.push_later(database, str(other["user_id"]),
                                    title=name or None,
                                    body=push_line(message, name), path=f"/chat?with={thread}")
            # A website visitor who signed up: the first answer also goes
            # to their phone or email (N591 item 4).
            from services import chat_widget
            chat_widget.first_notice(database, thread, str(me["id"]), str(other["id"]),
                                     str(other["user_id"]), name)
    except Exception as e:  # noqa: BLE001 -- the message is sent either way
        logger.warning("chats: push not started: %s", e)


def _authors(database: Any, thread_id: str) -> dict[str, str]:
    return {str(m["id"]): m["display_name"]
            for m in _rows(_table(database, MEMBERS).select("id,display_name")
                           .eq("thread_id", thread_id))}


def _shown(row: dict, me: str, authors: dict[str, str],
           words: Optional[dict[str, str]] = None,
           answers: Optional[dict[str, dict]] = None) -> dict:
    """A message as its members see it; a voice note with its ``words``
    (N331), null until they are ready or when there are none. An answer
    (N355) also carries ``slides``: when each slide it was said over starts,
    in ms, for the strip that follows its voice; its words are its Take's."""
    author = str(row["author_member_id"])
    meta = dict(row.get("meta") or {})
    if author != me:
        # An answer's Take is the speaker's own: the person it was sent to
        # gets just the answer (N336 item 2).
        meta.pop("take", None)
        # A Take sent to them (N470): the sender's Take id stays theirs;
        # the receiver opens it through its message (services/take_sends.py).
        meta.pop("take_session_id", None)
    shown = {"id": str(row["id"]), "mine": author == me, "author": authors.get(author, ""),
             "kind": row["kind"], "body": row["body"], "meta": meta,
             "created_at": row["created_at"]}
    if row["kind"] == "voice" and meta.get("answer"):
        answer = (answers or {}).get(str(row["id"])) or {}
        shown["words"] = answer.get("words") or None
        shown["slides"] = answer.get("slides") or []
    elif row["kind"] == "voice":
        shown["words"] = (words or {}).get(str(row["id"])) or None
    return shown


def _answers(database: Any, rows: list[dict]) -> dict[str, dict]:
    """What the answers among ``rows`` were said over (N355, N331): by
    message, {"words": the Take's words, slide by slide, or None while it is
    processing; "slides": each slide's start in ms}. Read from the Take's
    per-slide transcript (v2_sessions.slide_transcripts); the Take's number
    and anything about how it went stay out (N336 item 2, Never 1). An
    unreadable Take reads as not ready."""
    takes = {str(r["id"]): str((r.get("meta") or {}).get("take") or "")
             for r in rows if r["kind"] == "voice" and (r.get("meta") or {}).get("answer")}
    ids = sorted({t for t in takes.values() if _uuid(t)})
    if not ids:
        return {}
    try:
        sessions = {str(r["id"]): r.get("slide_transcripts")
                    for r in _rows(_table(database, SESSIONS).select("id,slide_transcripts")
                                   .in_("id", ids))}
    except Exception:
        logger.warning("chats: the answers' words could not be read", exc_info=True)
        return {}
    out: dict[str, dict] = {}
    for message, take in takes.items():
        parts = sessions.get(take)
        parts = sorted((p for p in parts if isinstance(p, dict)),
                       key=lambda p: int(p.get("index") or 0)) if isinstance(parts, list) else []
        said = "\n\n".join(t for t in (str(p.get("transcript") or "").strip() for p in parts) if t)
        starts = []
        for p in parts:
            try:
                starts.append(max(0, int(p.get("start_offset_ms") or 0)))
            except (TypeError, ValueError):
                starts.append(0)
        out[message] = {"words": said[:MAX_WORDS] or None, "slides": starts}
    return out


def _words(database: Any, thread_id: str, rows: list[dict]) -> dict[str, str]:
    """The words of the voice notes among ``rows`` (N324, N331), by message;
    only this chat's recordings are read."""
    ids = [str(r["id"]) for r in rows if r["kind"] == "voice"]
    if not ids:
        return {}
    return {str(a["message_id"]): a["words"]
            for a in _rows(_table(database, AUDIO).select("message_id,words")
                           .eq("thread_id", thread_id).in_("message_id", ids))
            if a.get("words")}


def read(database: Any, user_id: Any, thread_id: Any) -> dict:
    """GET /v2/chats/<id>/messages: {"messages": [...], "joined_through":
    the first name of whose link the caller joined through, or null}
    (services/chat_links.py), oldest first."""
    from services import chat_safety
    from services.chat_links import joined_by, joined_through
    user_id = _require(database, user_id)
    me = _member_of(database, user_id, thread_id)
    thread = str(me["thread_id"])
    newest = _rows(_table(database, MESSAGES)
                   .select("id,author_member_id,kind,body,meta,created_at")
                   .eq("thread_id", thread).order("created_at", desc=True)
                   .limit(_MAX_MESSAGES))
    # What the person the caller blocked sent while blocked never reaches
    # them (N466 item 2).
    spans = chat_safety.spans_by_member(database, [str(me["id"])]).get(str(me["id"]), [])
    unheard = chat_safety.unheard(str(me["id"]), spans)
    from services import join_questions
    newest = [r for r in newest if not _held(r) and not unheard(r)
              and not join_questions.hidden(r, str(me["id"]))]
    _mark_demo_question(database, thread, newest)
    authors = _authors(database, thread)
    words = _words(database, thread, newest)
    answers = _answers(database, newest)
    through = joined_through(database, user_id, thread)
    return {"messages": [_shown(r, str(me["id"]), authors, words, answers)
                         for r in reversed(newest)],
            "joined_through": through,
            # The joiner's line at the top: with a few questions first, or not
            # (N496); the owner's: who joined through their link (N502 item 5).
            "joined_asks": bool(through) and join_questions.asks(database, thread),
            "joined_by": None if through else joined_by(database, user_id, thread),
            "blocked": chat_safety.blocking({"blocked_spans": spans})}


# ── Writing ──────────────────────────────────────────────────────────────

def post(database: Any, user_id: Any, thread_id: Any, body: Any) -> dict:
    """POST /v2/chats/<id>/messages {kind: "emoji", body}: one of the three
    emoji (N311); or {kind: "text", body, to?}: typed words, in a chat whose
    setup allows them (N591 items 2 and 3, ``assistants.may_type``); else
    400. With ``to``, the id of the other person's question that waits, the
    words are its answer (N610 item 4, "Type your answer"). {"message":
    {...}}; an answer to one of the host's own questions also carries
    {"messages": [the answer, then the host's next lines]}."""
    user_id = _require(database, user_id)
    me = _member_of(database, user_id, thread_id)
    payload = body if isinstance(body, dict) else {}
    if payload.get("kind") == "text":
        return _post_text(database, user_id, me, payload.get("body"), payload.get("to"))
    emoji = payload.get("body")
    if payload.get("kind") != "emoji" or not isinstance(emoji, str) or emoji not in EMOJI:
        raise ChatsError("NOT_ALLOWED", "Only 👍, 👀 or 🙏 for now.")
    thread = str(me["thread_id"])
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": "emoji",
        "body": emoji, "meta": {"label": EMOJI[emoji]}}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, rows[0])
    return {"message": _shown(rows[0], str(me["id"]), _authors(database, thread))}


#: The longest typed message (N591).
MAX_TEXT = 2000


def _post_text(database: Any, user_id: str, me: dict, said: Any, to: Any = None) -> dict:
    """Typed words, where the chat's setup allows them: the host answering
    (N591 item 3), or someone writing to a host whose recipe lets them type
    (N591 item 2). A question to the host joins its bundle (N584); words
    typed ``to`` a question that waits are its answer, not a question
    (N610 item 4)."""
    from services import assistants, chat_widget
    thread = str(me["thread_id"])
    if not assistants.may_type(database, thread, user_id):
        raise ChatsError("NOT_ALLOWED", "This chat is not answered that way.")
    words = " ".join(str(said or "").split())
    if not words or len(words) > MAX_TEXT:
        raise ChatsError("NOT_ALLOWED", f"Write 1 to {MAX_TEXT} characters.")
    if to is not None:
        return _typed_answer(database, user_id, me, words, to)
    host, _ = assistants.whose(database, thread)
    asks = bool(host) and host != user_id
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": "text",
        "body": words, "meta": dict(chat_widget.QUESTION) if asks else {}}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, rows[0])
    if asks and host:
        chat_widget.bundle(database, host, user_id, thread, str(rows[0]["id"]), words)
    return {"message": _shown(rows[0], str(me["id"]), _authors(database, thread))}


def _typed_answer(database: Any, user_id: str, me: dict, words: str, to: Any) -> dict:
    """Words typed as the answer to what the other person asked (N610 item
    4): one of the host's own questions, answered as a tap answers it
    (``join_questions.answer_typed``), or a question they sent (``meta``
    question, asked or record_answer), answered with a message that says
    which (``meta.answer_to``) and asks nothing back. 404 for a message
    that is not the other person's in this chat, 400 for one that asks for
    no answer."""
    from services import join_questions
    thread, message = str(me["thread_id"]), _uuid(to)
    rows = _rows(_table(database, MESSAGES).select("id,author_member_id,meta")
                 .eq("id", message).eq("thread_id", thread).limit(1)) if message else []
    if not rows or str(rows[0].get("author_member_id")) == str(me["id"]):
        raise _not_found()
    meta = rows[0].get("meta") or {}
    if "setup" in meta:
        answered = join_questions.answer_typed(database, me, user_id, message, words)
        return {"message": answered["messages"][0], **answered}
    if not any(meta.get(k) is True for k in ("question", "asked", "record_answer")):
        raise ChatsError("NOT_ALLOWED", "This message asks for no answer.")
    sent = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": "text",
        "body": words, "meta": {"answer_to": message}}))
    if not sent:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, sent[0])
    return {"message": _shown(sent[0], str(me["id"]), _authors(database, thread))}


def _duration(value: Any, most: int = MAX_VOICE_MS) -> Optional[int]:
    """``duration_ms`` as the app sends it, a whole number of 1 to ``most``
    (a voice note's two minutes unless said otherwise); None otherwise."""
    try:
        ms = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return ms if 1 <= ms <= most else None


def post_voice(database: Any, user_id: Any, thread_id: Any, audio: bytes, *,
               adapter: Any, filename: str, content_type: Any,
               duration_ms: Any) -> dict:
    """POST /v2/chats/<id>/voice: a voice note, its message and then its
    recording, then its words. The route has passed the processing-
    authorization path first, with the recording consent. A recording that is
    missing, empty, not audio, or not 1 ms to two minutes long is 400; over
    12 MB, 413. Either both rows are kept or neither is. Once they are, the
    same bytes are transcribed under the caller's authorization (``adapter``,
    the one provider call here; N324); a note with no words is sent all the
    same. {"message": {...}}, as ``post``, with its ``words`` (N331)."""
    me = member(database, user_id, thread_id)
    kind = str(content_type or "").strip()
    if not audio:
        raise ChatsError("NOT_ALLOWED", "No recording.")
    if not kind.startswith("audio/") or len(kind) > _MAX_TYPE_LEN:
        raise ChatsError("NOT_ALLOWED", "Only an audio recording.")
    ms = _duration(duration_ms)
    if ms is None:
        raise ChatsError("NOT_ALLOWED", "A voice note is 1 ms to two minutes long.")
    if len(audio) > MAX_VOICE_BYTES:
        raise ChatsError("TOO_LARGE", "A voice note is at most 12 MB.", 413)
    thread = str(me["thread_id"])
    meta: dict[str, Any] = {"duration_ms": ms}
    if _after_my_photo_or_file(database, thread, str(me["id"])):
        meta["question"] = True
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": "voice",
        "body": "", "meta": meta}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    message = rows[0]
    if not _keep_recording(database, message, str(user_id), kind, ms, audio):
        _forget(database, message)
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, message)
    said = _keep_words(database, adapter, str(message["id"]), str(user_id), audio, filename)
    if meta.get("question") and said:
        message = _marked(database, message, said, str(user_id))
    return {"message": _shown(message, str(me["id"]), _authors(database, thread),
                              {str(message["id"]): said} if said else None)}


def read_kind(text: Any) -> Optional[bool]:
    """The model's one word: True for yes, False for no, None for anything
    else. Pure."""
    word = str(text or "").strip().strip(".!\"'").lower()
    return {"yes": True, "no": False}.get(word)


def asks_about_a_product_or_treatment(words: str, *, user_id: Optional[str]) -> Optional[bool]:
    """Will's mark on a question (N361 item 1): does it ask about a product
    or a treatment? None when the model gives no clear yes or no. Called
    inside the route's provider scope, so its permit is the caller's."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_QUESTION_KIND
    from services.prompts.question_kind import SYSTEM
    result = chat_complete(spec=SPEC_QUESTION_KIND, system=SYSTEM,
                           user=f"Question: {words.strip()[:1500]}",
                           surface="question_kind", user_id=user_id)
    return read_kind(getattr(result, "text", None) if result else None)


def _marked(database: Any, message: dict, words: str, user_id: str) -> dict:
    """A question's message with Will's mark kept in its meta
    (``record_answer``); the message as it was when there is no clear mark or
    it cannot be kept. Never in the way: the note is sent either way."""
    try:
        mark = asks_about_a_product_or_treatment(words, user_id=user_id)
    except Exception:
        logger.warning("chats: no mark on question %s", message.get("id"), exc_info=True)
        return message
    if mark is None:
        return message
    meta = {**(message.get("meta") or {}), "record_answer": mark}
    try:
        _table(database, MESSAGES).update({"meta": meta}).eq("id", str(message["id"])).execute()
    except Exception:
        logger.warning("chats: mark on question %s not kept", message.get("id"), exc_info=True)
        return message
    return {**message, "meta": meta}


def _mark_demo_question(database: Any, thread: str, newest: list[dict]) -> None:
    """The founder's demo customer, seeded before Will's mark existed, gets
    it once (N361): its question asks about a treatment. Any other chat:
    nothing."""
    for row in newest:
        meta = row.get("meta") or {}
        if row.get("kind") != "text" or row.get("body") != _DEMO_QUESTION or "record_answer" in meta:
            continue
        demo = _rows(_table(database, THREADS).select("demo_user_id")
                     .eq("id", thread).limit(1))
        if not demo or not demo[0].get("demo_user_id"):
            return
        row["meta"] = {**meta, "record_answer": True}
        try:
            _table(database, MESSAGES).update({"meta": row["meta"]}).eq("id", str(row["id"])).execute()
        except Exception:
            logger.warning("chats: demo mark not kept", exc_info=True)
        return


def _keep_recording(database: Any, message: dict, user_id: str,
                    content_type: str, duration_ms: int, audio: bytes) -> bool:
    """The recording of a voice message just written; False when it was not
    kept."""
    try:
        _table(database, AUDIO).insert({
            "message_id": str(message["id"]),
            # Invariant: thread_id is always the chat of this same
            # chat_messages row, never taken from the request, so a
            # recording and its message name one chat, and ``recording``,
            # which reads by both, never answers it in another chat.
            "thread_id": str(message["thread_id"]),
            "user_id": user_id, "content_type": content_type,
            "duration_ms": duration_ms, "audio": "\\x" + audio.hex(),
            "words": None}).execute()
        return True
    except Exception:
        logger.error("chats: recording of voice message %s not kept",
                     message.get("id"), exc_info=True)
        return False


def _keep_words(database: Any, adapter: Any, message_id: str, user_id: str,
                audio: bytes, filename: str) -> Optional[str]:
    """What was said in a voice note just kept (N324 item 1): transcribed
    under the caller's authorization (``adapter``) as the voice notebook's
    notes are, cut to MAX_WORDS and kept with its recording, nowhere else.
    Never in the way (item 2): no words, a provider error or timeout, or a
    refusal at the permit leaves ``words`` NULL and the note sent. The log
    names the message, never the audio or the words: a database error can
    quote the row it refused, so only the error's kind and code are logged.
    The words kept, or None."""
    try:
        result = adapter.transcribe_audio(
            audio, filename, usage_surface="chat_voice_note",
            usage_user_id=user_id, usage_session_id=message_id) or {}
        words = str(result.get("text") or "").strip()[:MAX_WORDS]
        if words:
            _table(database, AUDIO).update({"words": words}).eq(
                "message_id", message_id).execute()
            return words
        reason = "no words"
    except Exception as error:  # noqa: BLE001 -- the note is sent either way
        reason = " ".join(filter(None, (type(error).__name__,
                                        str(getattr(error, "code", "") or "")[:64])))
    logger.warning("chats: voice message %s kept without its words (%s)",
                   message_id, reason)
    return None


def _after_my_photo_or_file(database: Any, thread_id: str, member_id: str) -> bool:
    """Does a voice note about to be sent follow the sender's own photo or
    file straight away? Then it says what they need (N337) and is part of
    the question the photo or file opened for the other person (N341 item
    2)."""
    rows = _rows(_table(database, MESSAGES).select("author_member_id,kind")
                 .eq("thread_id", thread_id).order("created_at", desc=True).limit(1))
    return bool(rows) and str(rows[0]["author_member_id"]) == member_id \
        and rows[0]["kind"] in ("photo", "file")


def _forget(database: Any, message: dict) -> None:
    """A message whose recording, photo or file was not kept goes, so no chat
    shows one that cannot be opened."""
    try:
        _table(database, MESSAGES).delete().eq("id", str(message["id"])).execute()
    except Exception:
        logger.error("chats: message %s left without its recording or file",
                     message.get("id"), exc_info=True)


def _bytes(raw: Any) -> bytes:
    """bytea as PostgREST answers it ("\\x" and hex), as bytes; b"" when
    unreadable."""
    try:
        if isinstance(raw, str):
            return bytes.fromhex(raw[2:]) if raw.startswith("\\x") else b""
        return bytes(raw or b"")
    except (TypeError, ValueError):
        return b""


def recording(database: Any, user_id: Any, thread_id: Any, message_id: Any) -> dict:
    """GET /v2/chats/<id>/messages/<message_id>/audio: {content_type, audio}
    of a voice note in this chat, or of an answer or a sent Take (its Take's
    own recording), for any member of it; 404 otherwise."""
    me = member(database, user_id, thread_id)
    message = _uuid(message_id)
    if not message:
        raise _not_found()
    thread = str(me["thread_id"])
    rows = _rows(_table(database, AUDIO).select("content_type,audio")
                 .eq("message_id", message).eq("thread_id", thread).limit(1))
    audio = _bytes(rows[0].get("audio")) if rows else b""
    if audio:
        return {"content_type": rows[0].get("content_type") or "audio/webm", "audio": audio}
    return _answer_recording(database, thread, message)


def post_answer(database: Any, user_id: Any, thread_id: Any, take: Any,
                duration_ms: Any = None, hold_ms: Any = None, asks: bool = False) -> dict:
    """POST /v2/chats/<id>/answer: an answer recorded with "Record your
    answer" (N321 item 4, N336, N363, N483 item 5), sent as soon as its Take
    is uploaded. With ``asks`` (POST /v2/chats/<id>/question), a question
    recorded with "Record your question" (N483 item 4, N498): the same
    message, held and taken back the same way, marked as a question for the
    other person to answer (``asked``, ``question``, ``record_answer``), so
    their bar's middle is "Record your answer". The Take
    is already processing on its own; the answer is a voice message that
    points at it, so its recording is sent once, not twice. ``hold_ms``, what
    is left of its 5 seconds (N441 item 3, at most ``ANSWER_HOLD_MS``), holds
    it here: nobody else sees it, the list does not show it and the push
    waits until then, while ``undo_answer`` can take it back; with none left
    it goes at once (Send again, N441 item 1). The Take must be the caller's
    own (404 otherwise), of any length (N486 item 4), and its length known
    (400): the Take's, or the app's ``duration_ms`` while the Take's is not
    known yet. The caller sees it with its Take; the other person gets
    just the answer (N336 item 2). {"message": {...}}."""
    me = member(database, user_id, thread_id)
    session = _uuid(take)
    if not session:
        raise ChatsError("NOT_ALLOWED", "An answer names its Take.")
    take_row = _take_of(database, str(user_id), session)
    if not take_row:
        raise _not_found()
    ms = _answer_length(take_row, duration_ms)
    hold = _hold(hold_ms)
    meta: dict = {"duration_ms": ms, "answer": True, "take": session}
    if asks:
        meta.update({"asked": True, "question": True, "record_answer": True})
    if hold:
        meta["held_until"] = (_now() + timedelta(milliseconds=hold + _UNDO_GRACE_MS)).isoformat()
    thread = str(me["thread_id"])
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": "voice", "body": "",
        "meta": meta}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    if hold:
        _after((hold + _UNDO_GRACE_MS) / 1000, lambda: _tell_if_kept(database, me, rows[0]))
    else:
        _tell(database, me, rows[0])
    return {"message": _shown(rows[0], str(me["id"]), _authors(database, thread))}


def _hold(value: Any) -> int:
    """What is left of an answer's 5 seconds, in ms: 0 to ``ANSWER_HOLD_MS``."""
    try:
        return max(0, min(ANSWER_HOLD_MS, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _after(seconds: float, then) -> None:
    """``then`` once ``seconds`` have passed, beside the request."""
    timer = threading.Timer(seconds, then)
    timer.daemon = True
    timer.start()


def _tell_if_kept(database: Any, me: dict, message: dict) -> None:
    """The push for a held answer, once its hold is over and if it was not
    taken back."""
    try:
        kept = _rows(_table(database, MESSAGES).select("id").eq("id", str(message["id"])).limit(1))
    except Exception:
        logger.warning("chats: a held answer could not be read for its push", exc_info=True)
        return
    if kept:
        _tell(database, me, message)


def undo_answer(database: Any, user_id: Any, thread_id: Any, message: Any = None,
                project: Any = None) -> dict:
    """POST /v2/chats/<id>/answer/undo: Undo (N345 item 2, N441 items 3 and
    5). ``message``, an answer of mine still held, is taken back before
    anyone sees it (gone: 409 ALREADY_SENT; not my answer here: 404). Its
    Take stays mine and its feedback comes as for any Take, after Will's line
    in my chat with him, written once per answer (``project``, the answer's
    own project, names it before its message exists). {"undone": true}."""
    me = member(database, user_id, thread_id)
    answer, about = _uuid(message), _uuid(project)
    key = about or answer
    if not key:
        raise ChatsError("NOT_ALLOWED", "Undo names its answer.")
    if answer:
        rows = _rows(_table(database, MESSAGES).select("id,author_member_id,meta")
                     .eq("id", answer).eq("thread_id", str(me["thread_id"])).limit(1))
        row = rows[0] if rows else None
        if (not row or str(row["author_member_id"]) != str(me["id"])
                or not (row.get("meta") or {}).get("answer")):
            raise _not_found()
        if not _held(row):
            raise ChatsError("ALREADY_SENT", "It has gone already.", 409)
        _table(database, MESSAGES).delete().eq("id", answer).execute()
    _will_says_taken_back(database, str(user_id), me, key)
    return {"undone": True}


def _will_says_taken_back(database: Any, user_id: str, me: dict, key: str) -> None:
    """Will's line in my chat with him (N441 item 5), named for the other
    person in this chat. Best-effort: the Undo stands either way."""
    try:
        thread = str(me["thread_id"])
        names = [str(m.get("display_name") or "").strip()
                 for m in _rows(_table(database, MEMBERS).select("id,display_name")
                                .eq("thread_id", thread))
                 if str(m["id"]) != str(me["id"])]
        if not names or not names[0]:
            return
        database.insert_lounge_messages(user_id, [{
            "client_id": str(uuid.uuid5(_TAKEN_BACK_KEYS, f"{thread}:{key}")),
            "role": "bot", "kind": "text", "body": TAKEN_BACK.format(name=names[0]),
            "metadata": {"answer_taken_back": True},
            "client_created_at": _now().isoformat()}])
    except Exception:
        logger.warning("chats: Will's line after an Undo was not written", exc_info=True)


def _take_of(database: Any, user_id: str, session: str) -> Optional[dict]:
    """The caller's recording row of the Take ``session``, or None."""
    rows = _rows(_table(database, RECORDINGS).select("storage_path,duration")
                 .eq("session_v2_id", session).eq("user_id", user_id).limit(1))
    return rows[0] if rows else None


def _answer_length(row: dict, duration_ms: Any) -> int:
    """An answer's length in ms: its Take's, else what the app measured;
    any length (N486 item 4), but known, else 400."""
    try:
        ms = int(row.get("duration") or 0) * 1000
    except (TypeError, ValueError):
        ms = 0
    if not ms:
        ms = _duration(duration_ms, MAX_ANSWER_MS) or 0
    if ms < 1:
        raise ChatsError("NOT_ALLOWED", "This answer's length is not known yet.")
    return ms


def _answer_recording(database: Any, thread: str, message: str) -> dict:
    """An answer's recording: the Take it points at, read from where the Take
    is kept, for a member of the chat; 404 when the message is no answer or
    the Take's audio is gone (its owner deleted it)."""
    rows = _rows(_table(database, MESSAGES).select("kind,meta,author_member_id")
                 .eq("id", message).eq("thread_id", thread).limit(1))
    meta = (rows[0].get("meta") or {}) if rows else {}
    # An answer points at its Take; so does a Take sent to the people the
    # speaker ticked (N470), by ``take_session_id``.
    sent = rows[0].get("kind") == "take" if rows else False
    session = _uuid(meta.get("take_session_id") if sent else meta.get("take")) \
        if (sent or meta.get("answer")) else None
    if not session:
        raise _not_found()
    authors = _rows(_table(database, MEMBERS).select("user_id")
                    .eq("id", str(rows[0]["author_member_id"])).limit(1))
    take = _take_of(database, str(authors[0]["user_id"]), session) if authors else None
    key = str((take or {}).get("storage_path") or "")
    if not key:
        raise _not_found()
    from services.lab_audio_storage import get_lab_audio_bytes
    from services.training_import import content_type_for
    try:
        audio = get_lab_audio_bytes(key)
    except Exception:
        logger.warning("chats: an answer's recording could not be read (message %s)", message)
        raise _not_found()
    return {"content_type": content_type_for(key), "audio": audio}


def _sent_type(kind: str, content_type: Any) -> str:
    """The type kept for a photo, one of PHOTO_TYPES, else 400; for a file,
    its own plain media type, or application/octet-stream when it has none a
    browser could be trusted with."""
    sent = str(content_type or "").split(";")[0].strip().lower()
    if kind == "photo":
        if sent not in PHOTO_TYPES:
            raise ChatsError("NOT_ALLOWED", "Only a photo.")
        return sent
    if _MEDIA_TYPE.match(sent) and len(sent) <= _MAX_TYPE_LEN:
        return sent
    return "application/octet-stream"


def _file_name(value: Any) -> str:
    """A file's own name as it came, without any folder or unprintable
    character, cut to _MAX_NAME_LEN."""
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(ch for ch in name if ch.isprintable()).strip()[:_MAX_NAME_LEN]


def post_file(database: Any, user_id: Any, thread_id: Any, kind: str, data: bytes, *,
              content_type: Any, file_name: Any, meta: Optional[dict] = None) -> dict:
    """POST /v2/chats/<id>/photo and /file (N351): a photo, one of
    PHOTO_TYPES, or a file of any type, from the "+". Missing, empty, or a
    photo that is not one of them is 400; over 10 MB, 413. Its message (kind
    ``photo`` or ``file``; a file's body is its own name) opens a new
    question for the other person (``meta.question``, N341 item 2). Either
    the message and its bytes are both kept or neither is. No provider call.
    ``meta``: what else the message carries (a photo a question asked for,
    ``join_questions.answer_photo``). {"message": {...}}, as ``post``."""
    me = member(database, user_id, thread_id)
    sent_type = _sent_type(kind, content_type)
    if not data:
        raise ChatsError("NOT_ALLOWED", "No file.")
    if len(data) > MAX_FILE_BYTES:
        raise ChatsError("TOO_LARGE", "A photo or a file is at most 10 MB.", 413)
    name = _file_name(file_name)
    thread = str(me["thread_id"])
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": str(me["id"]), "kind": kind,
        "body": name if kind == "file" else "", "meta": {**(meta or {}), "question": True}}))
    if not rows:
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    message = rows[0]
    if not _keep_file(database, message, str(user_id), sent_type, name, data):
        _forget(database, message)
        raise ChatsError("NOT_SAVED", "Could not send it.", 503)
    _tell(database, me, message)
    return {"message": _shown(message, str(me["id"]), _authors(database, thread))}


def _keep_file(database: Any, message: dict, user_id: str, content_type: str,
               file_name: str, data: bytes) -> bool:
    """The bytes of a photo or file message just written; False when they
    were not kept. The log names the message, never the file."""
    try:
        _table(database, FILES).insert({
            "message_id": str(message["id"]),
            # As for a recording: always the chat of this same message.
            "thread_id": str(message["thread_id"]),
            "user_id": user_id, "content_type": content_type,
            "file_name": file_name, "data": "\\x" + data.hex()}).execute()
        return True
    except Exception:
        logger.error("chats: file of message %s not kept", message.get("id"), exc_info=True)
        return False


def sent_file(database: Any, user_id: Any, thread_id: Any, message_id: Any) -> dict:
    """GET /v2/chats/<id>/messages/<message_id>/file: {content_type,
    file_name, data} of a photo or file in this chat, for any member of it;
    404 otherwise. With no name of its own, the message's id names it."""
    me = member(database, user_id, thread_id)
    message = _uuid(message_id)
    if not message:
        raise _not_found()
    rows = _rows(_table(database, FILES).select("content_type,file_name,data")
                 .eq("message_id", message).eq("thread_id", str(me["thread_id"]))
                 .limit(1))
    data = _bytes(rows[0].get("data")) if rows else b""
    if not data:
        raise _not_found()
    return {"content_type": rows[0].get("content_type") or "application/octet-stream",
            "file_name": rows[0].get("file_name") or message, "data": data}


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
             "meta": ({"label": EMOJI[body]} if kind == "emoji"
                      else {"record_answer": True} if demo.get("marked") else {}),
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
