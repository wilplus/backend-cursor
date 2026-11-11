"""What a person gets back in a host's chat, made from the host's recipe
(founder, the Claude Code chat, 10 November 2026: N612 item 3, N616 items 4,
6, 11 and 13, N618 item 8, N606; the contract in backend PR #1893).

  * ``make``: one provider call, the cheap model with a maximum length,
    gives the output the host chose (an answer, their own words tidied, what
    to do next, or a mark on what they sent, said in words) and one line for
    each of the host's models, in the host's order. Every line passes the
    checks a host's own words pass: no score and no number about the person
    (N616 item 12). A line that fails is left out.
  * ``on_question``: a person wrote to a host. "Only you": nothing is
    drafted and the question waits for the host. "I draft, you send", or
    "I answer at once" before the host's own 20 answers (N616 item 11), or a
    chat about health, law or money (N616 item 13): the draft waits in the
    host's Will and the person gets nothing yet. "I answer at once" with 20
    or more and not health, law or money: sent at once as "{name}'s
    assistant".
  * ``try_it``: "Test my chat": the same reply for the host, kept nowhere.
  * ``drafts`` / ``send_draft``: the host's Will: what waits, and sending it
    (or the host's own words) from the host.
  * ``useful``: "Was this useful?" kept on the answer, Yes, No or Skip; it
    never stands before the next message (N616 item 6).

A visitor's message costs at most two provider calls (N620): one reader
call when a model of the recipe has a head whose gate is open (its answer
comes from the head, LEARN-02), and the one chat call, both made under the
processing authorization of the person who sent it (``user_provider_scope``)
or, for "Test my chat", of the host (the route's ``phase1_provider_route``).
Behind the host's ring row ``chat_builder``.

THE FEEDBACK WALK (N647 item 8, step 1). A host whose recipe holds a saved
walk: each of the host's own models whose head is ready (gate one open)
and sure says the host's own line (``says``) word for word, in the host's
order, when its answer is the first of its three (what the line is for),
and nothing otherwise. Each such line asks "Did this help?" on its own
(``meta.walk_line``, ``meta.useful_ask``; the answer is ``meta.useful``).
No provider call is added. Everything else, a recipe with no walk and
every model not ready, is as before.

A model still learning on the host's cards (N633 item 1) is left out of
the call: no line, no charge. The host's own words, when they answer a
question by typing or change a draft before sending it, become an example
of it (``chat_recipes.teach``).

TOKENS (TOK-01, TOK-02, N630 item 3). A line of another person's model in
a visitor's message is paid by the host, at the price saved on the
recipe's card when they added the model (never the owner's newer price),
once per message
(``model_api_store.pay_for_chat_line``); a host with too few tokens has
that line left out and the rest is sent. The person pays nothing and sees
no price. "Test my chat" is not charged. No provider call is added.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from services import assistants, chat_recipes
from services.chats import MEMBERS, MESSAGES, ChatsError, _not_found, _rows, _table, _uuid

logger = logging.getLogger(__name__)

#: N606, N616 item 11: the assistant answers by itself only after this many
#: of the host's own answers.
MINIMUM = 20
USEFUL = ("yes", "no", "skip")
MAX_SAID = 2000

_OUTPUTS = {
    "answer": "Give one message in words: a plain answer, at most five sentences.",
    "words": "Give back the person's own words, tidied: what they said, made clear, in their voice.",
    "todo": "Give a short list of what to do next: at most three steps, one line each.",
    "mark": "Say in words which one spot of what they sent matters most, and why, in two sentences.",
}


def _first(name: Any) -> str:
    parts = str(name or "").split()
    return parts[0] if parts else "WillpowerLab"


def prompt(recipe: dict, heads: Optional[dict] = None) -> str:
    """The one call's instructions, from the recipe, and each model's own
    answer where its head gave one (LEARN-02): the line then says that
    answer in words, never another."""
    heads = heads or {}
    lines = [f"You answer, in their chat, for a specialist: {recipe.get('spec') or 'a specialist'}.",
             f"Why people come to them: {recipe.get('line') or ''}".strip(),
             _OUTPUTS.get(str(recipe.get("out") or "answer"), _OUTPUTS["answer"]),
             "Write for a 12-year-old: short, warm, plain words. Never give a score, a number, a "
             "grade or a percentage about the person. For health, law or money never state a "
             "diagnosis or a final ruling."]
    models = recipe.get("models") or []
    for i, m in enumerate(models):
        lines.append(f"Model {i + 1} asks: {m.get('q')} Its answers: "
                     + "; ".join(str(o) for o in m.get("opts") or []) + ". "
                     + (f"When the answer is \"{(m.get('opts') or [''])[0]}\" it says, for example: "
                        f"{m.get('says')}" if m.get("says") else ""))
        if heads.get(i, {}).get("sure"):
            lines.append(f"Model {i + 1}'s own answer is \"{heads[i]['answer']}\": its line says that "
                         "answer in words, and no other.")
    lines.append('Reply with only a JSON object: {"answer": "<what the person gets back>", '
                 f'"lines": [{len(models)} strings, one sentence for each model in order, in '
                 "words, saying what that model notices in what the person sent]}.")
    return "\n".join(lines)


def _clean(text: Any, most: int) -> Optional[str]:
    said = " ".join(str(text or "").split())[:most] if isinstance(text, str) else ""
    return said if said and assistants.check_host_words(said) is None else None


def _heads(database: Any, host_id: Optional[str], recipe: dict, said: str) -> dict:
    """The heads' answers of the recipe's models, by place: one reader call
    at most (N620: with the chat's own, two). Nothing when none answers."""
    if database is None or not host_id or not any(m.get("model_id") for m in recipe.get("models") or []):
        return {}
    try:
        from services.model_head_store import chat_answers
        return chat_answers(database, host_id, recipe.get("models") or [], said[:MAX_SAID])
    except Exception:  # noqa: BLE001 -- the lines come from the recipe, as before
        logger.warning("chat_replies: the models' heads gave nothing", exc_info=True)
        return {}


def make(recipe: dict, said: str, host_name: Any, *, user_id: Optional[str],
         database: Any = None, host_id: Optional[str] = None,
         pay: Optional[Callable[[dict], bool]] = None) -> dict:
    """{"answer": words or None, "lines": [{"body", "by", "q"}]}: the one
    chat call, after one reader call when a model of the recipe has a head
    whose gate is open. ``pay``: asked for each line of another person's
    model that would be given, after the call; False leaves it out (TOK-01,
    TOK-02). The host's own models are free (N618 item 1)."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_CHAT_REPLY
    # A model still learning says nothing to the people who write and costs
    # nothing (N633 item 1): it is not in the call at all.
    recipe = {**recipe, "models": [m for m in recipe.get("models") or [] if not m.get("learning")]}
    heads = _heads(database, host_id, recipe, said)
    try:
        result = chat_complete(spec=SPEC_CHAT_REPLY, system=prompt(recipe, heads),
                               user=f"What the person sent: {said[:MAX_SAID]}",
                               surface="chat_reply", user_id=user_id)
    except Exception:  # noqa: BLE001 -- nothing is sent; the question waits
        logger.warning("chat_replies: no provider answer", exc_info=True)
        result = None
    parsed = getattr(result, "parsed", None) if result else None
    got = parsed if isinstance(parsed, dict) else {}
    given = got.get("lines")
    raw_lines: list = given if isinstance(given, list) else []
    lines = []
    walking = bool(recipe.get("walk"))
    for i, m in enumerate(recipe.get("models") or []):
        if walking and m.get("own", True) and heads.get(i, {}).get("sure"):
            # The feedback walk (N647 item 8, step 1): a ready own model says
            # the host's own line, word for word, when it notices what its
            # line is for (its first answer); otherwise nothing.
            line = walk_line(m, heads[i], host_name)
            if line:
                lines.append(line)
            continue
        if i in heads and not heads[i].get("sure"):
            continue  # its head is not sure: no line, never a guess (N566 item 8)
        body = _clean(raw_lines[i], 300) if i < len(raw_lines) else None
        if body and pay is not None and not m.get("own", True) and not pay(m):
            continue  # not paid for: left out, the chat goes on (TOK-02)
        if body:
            owner = _first(host_name) if m.get("own", True) else _first(m.get("by"))
            lines.append({"body": body, "by": f"{owner}'s model", "q": m.get("q")})
    return {"answer": _clean(got.get("answer"), 1200), "lines": lines}


def walk_line(model: dict, head: dict, host_name: Any) -> Optional[dict]:
    """The walk's line for one of the host's own ready models (N647 item 8,
    step 1): the host's words (``says``, N578: they pass the host's checks)
    when the model's sure answer is the one the line is for, its first
    (``opts[0]``). None when it noticed something else or has no line."""
    opts = model.get("opts") or []
    if not opts or head.get("answer") != opts[0]:
        return None
    body = _clean(model.get("says"), 300)
    if not body:
        return None
    return {"body": body, "by": f"{_first(host_name)}'s model", "q": model.get("q"),
            "walk": {"model_id": model.get("model_id"), "says": body}}


def _messages(reply: dict, by: str) -> list[dict]:
    out = [{"kind": "answer", "body": reply["answer"], "by": by}] if reply.get("answer") else []
    return out + [{"kind": "model", "body": line["body"], "by": line["by"],
                   **({"walk": True} if line.get("walk") else {})} for line in reply["lines"]]


# ── "Test my chat" (N618 item 8) ────────────────────────────────────────

def try_it(database: Any, user_id: Any, name: Any, body: Any) -> dict:
    """POST /v2/chats/setup/try {"body"}: what a person would get back, from
    the recipe as it stands, live or not; nothing is kept."""
    said = " ".join(str((body or {}).get("body") or "").split()) if isinstance(body, dict) else ""
    if not said or len(said) > MAX_SAID:
        raise ChatsError("NOT_ALLOWED", f"Write 1 to {MAX_SAID} characters.")
    recipe = chat_recipes.mine(database, user_id)
    if recipe is None:
        raise ChatsError("NOT_STARTED", "Say what you do first.", 409)
    reply = make(recipe, said, name, user_id=str(user_id), database=database, host_id=str(user_id))
    who = _first(name) if recipe.get("who") == "you" else assistants.assistant_name(name)
    return {"messages": _messages(reply, who), "useful": True}


# ── A person writes to a host ───────────────────────────────────────────

def _host_members(database: Any, host_id: str) -> list[dict]:
    return _rows(_table(database, MEMBERS).select("id,thread_id,user_id,display_name")
                 .eq("user_id", host_id))


def own_answers(database: Any, host_id: Any) -> int:
    """How many answers the host gave in their own words: to a question
    asked of them, a bundle's recording, or a draft they sent."""
    members = _host_members(database, str(host_id))
    ids = {str(m["id"]) for m in members}
    threads = list({str(m["thread_id"]) for m in members})
    if not threads:
        return 0
    rows = _rows(_table(database, MESSAGES).select("id,author_member_id,meta")
                 .in_("thread_id", threads).order("created_at", desc=True).limit(5000))
    count = 0
    for row in rows:
        meta = row.get("meta") or {}
        if str(row.get("author_member_id")) not in ids or not isinstance(meta, dict):
            continue
        said = meta.get("reply")
        reply: dict = said if isinstance(said, dict) else {}
        if meta.get("answer_to") or meta.get("answer") is True or reply.get("by") == "host":
            count += 1
    return count


def _host_name(database: Any, thread: str, host_id: str) -> tuple[Optional[str], Any]:
    rows = _rows(_table(database, MEMBERS).select("id,user_id,display_name").eq("thread_id", thread))
    host = next((m for m in rows if str(m.get("user_id")) == host_id), None)
    return (str(host["id"]), host.get("display_name")) if host else (None, None)


def _post(database: Any, thread: str, member: str, reply: dict, to: str, by: str,
          name: str) -> list[dict]:
    from services.chats import _tell
    rows: list[dict] = []
    if reply.get("answer"):
        rows.append({"thread_id": thread, "author_member_id": member, "kind": "text",
                     "body": reply["answer"], "meta": {"reply": {"to": to, "by": by, "name": name}}})
    for line in reply.get("lines") or []:
        meta: dict[str, Any] = {"model_line": {"q": line.get("q"), "by": line["by"]},
                "reply": {"to": to, "by": by, "name": name}}
        if line.get("walk"):
            # Each line of the walk asks "Did this help?" on its own, so the
            # host can read back how each line does (N647 item 6).
            meta = {**meta, "walk_line": dict(line["walk"]), "useful_ask": True}
        rows.append({"thread_id": thread, "author_member_id": member, "kind": "text",
                     "body": line["body"], "meta": meta})
    if not rows:
        return []
    rows[-1]["meta"]["useful_ask"] = True
    made = _rows(_table(database, MESSAGES).insert(rows))
    if made:
        _tell(database, {"id": member, "thread_id": thread}, made[0])
    return made


def on_question(database: Any, host_id: Any, asker_id: Any, thread_id: Any, message_id: Any,
                said: Any) -> Optional[dict]:
    """A person's message to a host with a live blank-setup recipe.
    {"waits": true} or {"messages": [...], "useful": true}; None for a chat
    the blank setup does not run. Best-effort: the message is sent either
    way."""
    host, thread, message = str(host_id), str(thread_id), str(message_id)
    try:
        if not assistants.on(database, host):
            return None
        recipe = chat_recipes.for_visitors(chat_recipes.settle(database, host, chat_recipes.mine(database, host)))
        if recipe is None:
            return None
        who = recipe.get("who") or "shadow"
        if who == "you":
            return {"waits": True}
        at_once = (who == "assistant" and recipe.get("sensitive") is False
                   and own_answers(database, host) >= MINIMUM)
        member, host_name = _host_name(database, thread, host)
        if not member:
            return {"waits": True}
        from routes.v2.processing_authorization import user_provider_scope
        with user_provider_scope(str(asker_id), operation="ai_conversation", prefix="chat-reply"):
            reply = make(recipe, str(said or ""), host_name, user_id=str(asker_id),
                         database=database, host_id=host, pay=_payer(database, host, message))
        if not reply.get("answer") and not reply.get("lines"):
            return {"waits": True}
        if at_once:
            name = assistants.assistant_name(host_name)
            made = _post(database, thread, member, reply, message, "assistant", name)
            return {"messages": made, "useful": True}
        _table(database, MESSAGES).update({"meta": {**_meta(database, message),
                                                    "draft": {**reply, "sent": False}}}) \
            .eq("id", message).execute()
        return {"waits": True}
    except Exception:  # noqa: BLE001 -- the question is sent either way
        logger.warning("chat_replies: no reply to message %s", message, exc_info=True)
        return {"waits": True}


def _payer(database: Any, host: str, message: str) -> Callable[[dict], bool]:
    """Another person's model in this host's chat: the host pays the price
    saved on its card when they added it (N630 item 3), for this message,
    once (``model_api_store.pay_for_chat_line``)."""
    def pay(model: dict) -> bool:
        from services.model_api_store import pay_for_chat_line
        return pay_for_chat_line(database, host, message, model.get("model_id"), price=model.get("price"))
    return pay


def _meta(database: Any, message_id: str) -> dict:
    rows = _rows(_table(database, MESSAGES).select("id,meta").eq("id", message_id).limit(1))
    meta = rows[0].get("meta") if rows else None
    return dict(meta) if isinstance(meta, dict) else {}


# ── The host's Will: what waits ─────────────────────────────────────────

def _waiting(database: Any, host_id: str) -> list[tuple[dict, dict]]:
    members = _host_members(database, host_id)
    mine_ = {str(m["id"]) for m in members}
    threads = list({str(m["thread_id"]) for m in members})
    if not threads:
        return []
    rows = _rows(_table(database, MESSAGES).select("id,thread_id,author_member_id,body,meta,created_at")
                 .in_("thread_id", threads).order("created_at").limit(5000))
    out = []
    for row in rows:
        meta = row.get("meta") or {}
        draft = meta.get("draft") if isinstance(meta, dict) else None
        if isinstance(draft, dict) and draft.get("sent") is False \
                and str(row.get("author_member_id")) not in mine_:
            out.append((row, draft))
    return out


def drafts(database: Any, host_id: Any) -> dict:
    """GET /v2/chats/setup/drafts: oldest first."""
    host = str(host_id)
    recipe = chat_recipes.mine(database, host) or {}
    names = {str(m["id"]): m.get("display_name")
             for m in _rows(_table(database, MEMBERS).select("id,display_name,user_id")
                            .in_("thread_id", list({str(m["thread_id"]) for m in _host_members(database, host)})))}
    return {"drafts": [{"message_id": str(row["id"]), "thread_id": str(row["thread_id"]),
                        "from": _first(names.get(str(row.get("author_member_id")))),
                        "said": row.get("body") or "", "answer": d.get("answer"),
                        "lines": [{"body": x["body"], "by": x["by"]} for x in d.get("lines") or []],
                        "sensitive": recipe.get("sensitive") is not False}
                       for row, d in _waiting(database, host)]}


def send_draft(database: Any, host_id: Any, message_id: Any, body: Any) -> dict:
    """POST /v2/chats/setup/drafts/<message_id>/send {"body"?}: the draft, or
    the host's own words, from the host. 404 for anything not waiting."""
    host, message = str(host_id), _uuid(message_id)
    found = next(((row, d) for row, d in _waiting(database, host) if str(row["id"]) == message), None)
    if not message or not found:
        raise _not_found()
    row, draft = found
    own = (body or {}).get("body") if isinstance(body, dict) else None
    reply = dict(draft)
    words = None
    if own is not None:
        words = " ".join(str(own).split())
        if not words or len(words) > MAX_SAID:
            raise ChatsError("NOT_ALLOWED", f"Write 1 to {MAX_SAID} characters.")
        reply = {"answer": words, "lines": draft.get("lines") or []}
    if not reply.get("answer"):
        raise ChatsError("NOT_ALLOWED", "Write the answer.")
    thread = str(row["thread_id"])
    member, name = _host_name(database, thread, host)
    if not member:
        raise _not_found()
    made = _post(database, thread, member, reply, message, "host", _first(name))
    meta = {**(row.get("meta") or {}), "draft": {**draft, "sent": True}}
    _table(database, MESSAGES).update({"meta": meta}).eq("id", message).execute()
    if words and words != draft.get("answer"):
        # Changed before sending: the host's own words teach the models
        # still learning on their cards (N633 item 1).
        chat_recipes.teach(database, host, words)
    return {"message": made[0] if made else None, "messages": made}


# ── "Was this useful?" (N616 item 6) ────────────────────────────────────

def useful(database: Any, user_id: Any, thread_id: Any, message_id: Any, body: Any) -> dict:
    """POST /v2/chats/<id>/messages/<message_id>/useful {"answer"}: kept on
    the reply that asked it. Only the person it was sent to answers it."""
    from services.chats import _member_of
    me = _member_of(database, str(user_id), thread_id)
    answer = (body or {}).get("answer") if isinstance(body, dict) else None
    if answer not in USEFUL:
        raise ChatsError("NOT_ALLOWED", "Yes, No or Skip.")
    rows = _rows(_table(database, MESSAGES).select("id,thread_id,author_member_id,meta")
                 .eq("id", _uuid(message_id)).eq("thread_id", str(me["thread_id"])).limit(1))
    meta = (rows[0].get("meta") or {}) if rows else {}
    if not rows or not meta.get("useful_ask") or str(rows[0].get("author_member_id")) == str(me["id"]):
        raise _not_found()
    _table(database, MESSAGES).update({"meta": {**meta, "useful": answer}}) \
        .eq("id", str(rows[0]["id"])).execute()
    return {"ok": True}
