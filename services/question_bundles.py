"""One recording answers everyone who asked the same thing (founder, the
Claude Code chat, 9 November 2026, N584; the speaking coach's exercises made
universal). Tables: question_bundles, question_bundle_askers (migration
a_question_joins_its_bundle).

  * ``collect``: a voice question someone sends a host, once its words are
    known, joins the host's bundle that asks the same thing, or starts one
    (N584 item 1). When that bundle already has the host's answer, the asker
    gets it at once in their own chat, under their question, with its
    coloured mark for how sure the match is (N584 item 4, N580 item 3).
  * ``queue``: the host's bundles in Will's chat, one card each (N602):
    "{n} people asked", the question, the faces of who asked with "{name},
    {name} and {n} more", "See who asked" and the bar's "Record one answer";
    the ones still waiting first. ``who_asked``: the sheet "Who asked", each
    person's own words, name and where they asked, then "Split them up".
  * ``answer``: the host's one recording, a Take of their own, goes to
    everyone in the bundle, each privately in their own chat with the host,
    under their own question quoted (N584 item 3). It is a voice message that
    points at the Take, as every answer is (services/chats.py), so the
    recording is kept once and "Read it" opens its words (N576). Nobody is
    sent the same answer twice (N103).
  * ``split`` / ``merge``: the host moves questions out into a bundle of
    their own, or puts two bundles together (N584 item 1).

Matching by meaning, first version: by rules, the share of the words that
carry meaning two questions have in common, with no provider call. A
question shares a bundle at ``JOIN`` or more; its mark is green from
``SURE``, else yellow. A model reading the meaning can replace ``likeness``
later; nothing else changes. N152's rule (an exercise only when it matches)
is the same promise: nothing reaches anyone below ``JOIN``.

Behind the ring row ``chat_builder`` (N579 item 2): only a host with it
collects. No provider call and no new recording: the question's words were
transcribed when its voice note was sent, under the asker's authorization,
and the answer's Take was recorded and uploaded through the processing-
authorization path already. Deleted with either account (the purge
registry), and with the chat or the message each row points at.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from services.chats import (
    MEMBERS, MESSAGES, ChatsError, _answer_length, _not_found, _rows, _table, _take_of, _uuid,
)

logger = logging.getLogger(__name__)

BUNDLES, ASKERS = "question_bundles", "question_bundle_askers"
#: A question joins a bundle when this share of its meaning words matches.
JOIN = 0.5
#: ... and its mark is green from here; yellow below (N580 item 3).
SURE = 0.75
MAX_WORDS = 2000

# ── The words (drafted for the founder's OK, N584 item 2) ───────────────
#: The card and its sheet (N602, signed with the founder's choice).
ASKED = "{n} people asked"
SEE_WHO = "See who asked"
WHO_ASKED = "Who asked"
SPLIT = "Split them up"
ASSISTANT_ANSWERED = "Your assistant has answered them for now."
RECORD_ONE = "Record one answer"
#: Drafted for the founder's OK: a bundle of one, and where it was asked.
ONE_ASKED = "{name} asked"
IN_CHAT, ON_WEBSITE = "in your chat", "on your website"

_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset("""a an and are as at be but by can could do does for from had has have how i
i'm if in is it it's me my of on or should so that the their them there they this to was
what when where which who why will with would you your yours we our us am please any some
just about get""".split())


def meaning(words: str) -> frozenset[str]:
    """The words that carry a question's meaning: lowercase, without the
    small words, a plural's s dropped. Pure."""
    out = set()
    for w in _WORD.findall(str(words or "").lower()):
        if w in _STOP or len(w) < 2:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return frozenset(out)


def likeness(a: str, b: str) -> float:
    """How much two questions ask the same thing, 0 to 1: the share of
    meaning words they have in common (Jaccard). Pure; never shown."""
    x, y = meaning(a), meaning(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def mark_of(score: float) -> str:
    return "green" if score >= SURE else "yellow" if score >= JOIN else "red"


def _askers_of(database: Any, bundle_ids: list[str]) -> dict[str, list[dict]]:
    """Each bundle's questions still kept, by bundle."""
    out: dict[str, list[dict]] = {}
    if not bundle_ids:
        return out
    for a in _rows(_table(database, ASKERS).select("bundle_id,words,created_at")
                   .in_("bundle_id", bundle_ids)):
        out.setdefault(str(a["bundle_id"]), []).append(a)
    return out


def _question(askers: list[dict]) -> str:
    """A bundle reads as its earliest question still kept; a bundle whose
    askers have all gone reads as nothing and matches nothing."""
    kept = sorted(askers, key=lambda a: str(a.get("created_at") or ""))
    return str(kept[0]["words"]) if kept else ""


def host_of_chat(database: Any, thread_id: Any) -> Optional[str]:
    """Whose chat this is: the owner of the link it was made through (N578
    item 1: you meet the chat of whoever's link you came by), or of the
    website it opened on (N591). None for a chat made otherwise, which
    bundles nothing."""
    from services.chat_links import LINKS
    rows = _rows(_table(database, "chat_threads").select("link_id,widget_owner_id")
                 .eq("id", str(thread_id)).limit(1))
    link = rows[0].get("link_id") if rows else None
    if not link:
        # A website visitor's chat is its owner's (N591 item 1).
        owner = rows[0].get("widget_owner_id") if rows else None
        return str(owner) if owner else None
    owners = _rows(_table(database, LINKS).select("user_id").eq("id", str(link)).limit(1))
    return str(owners[0]["user_id"]) if owners else None


def _host_member(database: Any, thread: str, host_id: str) -> Optional[str]:
    rows = _rows(_table(database, MEMBERS).select("id,user_id").eq("thread_id", thread))
    return next((str(m["id"]) for m in rows if str(m.get("user_id")) == host_id), None)


def _send(database: Any, host_id: str, asker: dict, bundle: dict,
          duration_ms: Any = None) -> Optional[str]:
    """The bundle's answer, in the asker's own chat with the host, under
    their question quoted; its message id, or None when it could not go."""
    take = _take_of(database, host_id, str(bundle["answer_take"]))
    host_member = _host_member(database, str(asker["thread_id"]), host_id)
    if not take or not host_member:
        return None
    try:
        ms = _answer_length(take, duration_ms)
    except ChatsError:
        return None
    meta = {"duration_ms": ms, "answer": True,
            "take": str(bundle["answer_take"]), "bundle": str(bundle["id"]),
            "quote": {"message_id": str(asker["message_id"]), "words": asker["words"]},
            "mark": asker["mark"]}
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": str(asker["thread_id"]), "author_member_id": host_member,
        "kind": "voice", "body": "", "meta": meta}))
    if not rows:
        return None
    sent = str(rows[0]["id"])
    # The same push as any answer: the host's name over its line (N385).
    from services.chats import _tell
    _tell(database, {"id": host_member, "thread_id": str(asker["thread_id"])}, rows[0])
    _table(database, ASKERS).update({"answered_message_id": sent}).eq("id", str(asker["id"])).execute()
    return sent


def collect(database: Any, host_id: Any, asker_id: Any, thread_id: Any, message_id: Any,
            words: Any) -> Optional[dict]:
    """A question just asked of ``host_id``, with its words: into its bundle.
    {"bundle", "mark", "answered": message id or None}; None when the host
    has no chat builder or nothing could be kept. Best-effort: the question
    is sent either way."""
    from services import assistants
    said = " ".join(str(words or "").split())[:MAX_WORDS]
    if not said or not meaning(said) or not assistants.on(database, host_id):
        return None
    try:
        bundles = _rows(_table(database, BUNDLES).select("id,answer_take")
                        .eq("host_id", str(host_id)).order("created_at", desc=True).limit(200))
        asked = _askers_of(database, [str(b["id"]) for b in bundles])
        best, score = None, 0.0
        for b in bundles:
            s = likeness(said, _question(asked.get(str(b["id"])) or []))
            if s > score:
                best, score = b, s
        if best is None or score < JOIN:
            best = _rows(_table(database, BUNDLES).insert({"host_id": str(host_id)}))[0]
            score = 1.0
        asker = _rows(_table(database, ASKERS).insert({
            "bundle_id": str(best["id"]), "asker_id": str(asker_id), "thread_id": str(thread_id),
            "message_id": str(message_id), "words": said, "mark": mark_of(score)}))[0]
        sent = _send(database, str(host_id), asker, best) if best.get("answer_take") else None
        return {"bundle": str(best["id"]), "mark": asker["mark"], "answered": sent}
    except Exception:  # noqa: BLE001 -- the question is sent either way
        logger.warning("question_bundles: a question was not bundled (message %s)", message_id,
                       exc_info=True)
        return None


def _names(database: Any, askers: list[dict]) -> dict[tuple[str, str], str]:
    threads = list({str(a["thread_id"]) for a in askers})
    if not threads:
        return {}
    rows = _rows(_table(database, MEMBERS).select("thread_id,user_id,display_name").in_("thread_id", threads))
    return {(str(m["thread_id"]), str(m.get("user_id"))): str(m.get("display_name") or "").split(" ")[0]
            for m in rows}


def _faces(names: list[str]) -> str:
    """"{name}, {name} and {n} more" (N602 item 1, signed); fewer people,
    every name."""
    names = [n for n in names if n] or ["Someone"]
    if len(names) > 3:
        return f"{names[0]}, {names[1]} and {len(names) - 2} more"
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _bundle_rows(database: Any, host_id: str) -> tuple[list[dict], list[dict]]:
    bundles = _rows(_table(database, BUNDLES).select("id,answer_take,created_at")
                    .eq("host_id", str(host_id)).order("created_at", desc=True).limit(200))
    ids = [str(b["id"]) for b in bundles]
    askers = _rows(_table(database, ASKERS).select(
        "id,bundle_id,asker_id,thread_id,message_id,words,mark,answered_message_id,created_at")
        .in_("bundle_id", ids)) if ids else []
    return bundles, sorted(askers, key=lambda a: str(a.get("created_at") or ""))


def queue(database: Any, host_id: Any) -> dict:
    """GET /v2/chats/bundles: one card per bundle in Will's chat (N602): the
    ones still waiting for an answer first."""
    bundles, askers = _bundle_rows(database, str(host_id))
    names = _names(database, askers)
    out: list[dict[str, Any]] = []
    for b in bundles:
        mine = [a for a in askers if str(a["bundle_id"]) == str(b["id"])]
        if not mine:
            continue
        who = [names.get((str(a["thread_id"]), str(a["asker_id"]))) or "" for a in mine]
        out.append({"id": str(b["id"]),
                    "title": ASKED.format(n=len(mine)) if len(mine) > 1
                    else ONE_ASKED.format(name=who[0] or "Someone"),
                    "question": _question(mine), "faces": who, "who": _faces(who),
                    # Only true once the assistant has answered each of them;
                    # it doesn't yet, so the line waits (N602 item 1).
                    "note": None, "see": SEE_WHO,
                    "answered": bool(b.get("answer_take")),
                    "record": None if b.get("answer_take") else RECORD_ONE})
    out.sort(key=lambda b: b["answered"])
    return {"bundles": out}


def _where(database: Any, thread_ids: list[str]) -> dict[str, str]:
    """Where each question was asked: "on your website" for a website
    visitor's chat (N591), else "in your chat" (N602 item 2)."""
    rows = _rows(_table(database, "chat_threads").select("id,widget_owner_id")
                 .in_("id", thread_ids)) if thread_ids else []
    return {str(r["id"]): ON_WEBSITE if r.get("widget_owner_id") else IN_CHAT for r in rows}


def who_asked(database: Any, host_id: Any, bundle_id: Any) -> dict:
    """GET /v2/chats/bundles/<id>: the sheet "Who asked" (N602 item 2): each
    person's own words, their name and where they asked, then "Split them
    up"."""
    bundle = _own_bundle(database, str(host_id), bundle_id)
    askers = [a for a in _bundle_rows(database, str(host_id))[1]
              if str(a["bundle_id"]) == str(bundle["id"])]
    names = _names(database, askers)
    where = _where(database, list({str(a["thread_id"]) for a in askers}))
    return {"title": WHO_ASKED, "split": SPLIT,
            "people": [{"id": str(a["id"]), "words": a["words"], "mark": a["mark"],
                        "name": names.get((str(a["thread_id"]), str(a["asker_id"]))),
                        "where": where.get(str(a["thread_id"]), IN_CHAT),
                        "chat": str(a["thread_id"]), "sent": bool(a.get("answered_message_id"))}
                       for a in askers]}


def _own_bundle(database: Any, host_id: str, bundle_id: Any) -> dict:
    bid = _uuid(bundle_id)
    rows = _rows(_table(database, BUNDLES).select("id,host_id,answer_take")
                 .eq("id", bid).limit(1)) if bid else []
    if not rows or str(rows[0]["host_id"]) != host_id:
        raise _not_found()
    return rows[0]


def answer(database: Any, host_id: Any, bundle_id: Any, body: Any) -> dict:
    """POST /v2/chats/bundles/<id>/answer {take}: the host's one recording,
    a Take of their own (404 otherwise), sent to everyone in the bundle not
    yet sent it. {"sent": the number of people it reached}."""
    host = str(host_id)
    bundle = _own_bundle(database, host, bundle_id)
    take = _uuid((body or {}).get("take") if isinstance(body, dict) else None)
    if not take:
        raise ChatsError("NOT_ALLOWED", "An answer names its Take.")
    take_row = _take_of(database, host, take)
    if not take_row:
        raise _not_found()
    duration_ms = (body or {}).get("duration_ms")
    _answer_length(take_row, duration_ms)  # its length known, else 400
    from datetime import datetime, timezone
    _table(database, BUNDLES).update({"answer_take": take, "answered_at": datetime.now(
        timezone.utc).isoformat()}).eq("id", str(bundle["id"])).execute()
    bundle = {**bundle, "answer_take": take}
    waiting = [a for a in _rows(_table(database, ASKERS).select(
        "id,asker_id,thread_id,message_id,words,mark,answered_message_id")
        .eq("bundle_id", str(bundle["id"]))) if not a.get("answered_message_id")]
    sent = sum(1 for a in waiting if _send(database, host, a, bundle, duration_ms))
    return {"sent": sent}


def split(database: Any, host_id: Any, bundle_id: Any, body: Any) -> dict:
    """POST /v2/chats/bundles/<id>/split {questions: [asker row ids]}: those
    questions into a new bundle of their own, waiting for its own answer."""
    host = str(host_id)
    bundle = _own_bundle(database, host, bundle_id)
    picked = [str(q) for q in ((body or {}).get("questions") or [])] if isinstance(body, dict) else []
    rows = [a for a in _rows(_table(database, ASKERS).select("id,words,answered_message_id")
                             .eq("bundle_id", str(bundle["id"]))) if str(a["id"]) in picked]
    if not rows:
        raise ChatsError("PICK_ONE", "Pick the questions to move.")
    new = _rows(_table(database, BUNDLES).insert({"host_id": host}))[0]
    for a in rows:
        _table(database, ASKERS).update({"bundle_id": str(new["id"])}).eq("id", str(a["id"])).execute()
    return {"bundle": str(new["id"])}


def merge(database: Any, host_id: Any, bundle_id: Any, body: Any) -> dict:
    """POST /v2/chats/bundles/<id>/merge {into}: this bundle's questions
    join the other; the ones not yet answered get the other's answer, if it
    has one."""
    host = str(host_id)
    source = _own_bundle(database, host, bundle_id)
    target = _own_bundle(database, host, (body or {}).get("into") if isinstance(body, dict) else None)
    if str(source["id"]) == str(target["id"]):
        raise ChatsError("NOT_ALLOWED", "Pick another bundle.")
    askers = _rows(_table(database, ASKERS).select(
        "id,asker_id,thread_id,message_id,words,mark,answered_message_id")
        .eq("bundle_id", str(source["id"])))
    for a in askers:
        _table(database, ASKERS).update({"bundle_id": str(target["id"])}).eq("id", str(a["id"])).execute()
    if target.get("answer_take"):
        for a in askers:
            if not a.get("answered_message_id"):
                _send(database, host, a, target)
    _table(database, BUNDLES).delete().eq("id", str(source["id"])).execute()
    return {"bundle": str(target["id"])}
