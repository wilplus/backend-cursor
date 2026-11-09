"""One Take, its answers in one place (founder, the Claude Code chat, 9
November 2026, N587 items 3 to 5, with N588 item 4).

A Take sent to several people (N470, N471) is one private copy in each chat;
each person answers in their chat with the sender, in their own voice (N580
item 7). This gathers those answers under the Take, for the sender only:

  * ``gathered``: GET /v2/user/takes/<take>/answers. The smart bubble under
    the Take, in the chat it was first sent in (your coach's): your coach's
    answer and the best of the others, with the faces (names) of everyone who
    answered; and all of them, under "On your speaking" (skill coaches,
    N588 item 1) and "On the matter" (topic experts), each with a way into
    that person's chat (its chat id). Nobody is hidden (item 5): everyone who
    answered is named.

Which answer shows in full, first version: the first to come in under each
heading. N587 item 5 asks for the one that answers most directly what was
asked; a model's reading can take its place later, never a score anyone sees
(Never 1). Whose heading: the person's recipe (``assistants``, N588 item 2);
a person with none is a skill coach, as every coach is today.

An answer is the other person's first answer or voice note after the Take in
that chat, before the sender's next Take there. Only the sender reads this;
the people who answered never see each other's (N587 item 4). Behind the
ring row ``chat_builder``. No provider call, no recording, nothing written.
"""
from __future__ import annotations

from typing import Any, Optional

from services import assistants
from services.chats import MEMBERS, MESSAGES, _not_found, _rows, _table, _uuid

#: The two headings (N587 item 3; the founder's words in the entry).
ON_SPEAKING, ON_MATTER = "On your speaking", "On the matter"


def _first_answer(rows: list[dict], sent_at: str, mine: str) -> Optional[dict]:
    """The other member's first answer after the Take, before my next Take."""
    for r in sorted(rows, key=lambda r: str(r.get("created_at") or "")):
        if str(r.get("created_at") or "") <= sent_at:
            continue
        if str(r.get("author_member_id")) == mine:
            if r.get("kind") == "take":
                return None
            continue
        if r.get("kind") == "voice" and not (r.get("meta") or {}).get("held_until"):
            return r
    return None


def gathered(database: Any, user_id: Any, take: Any) -> dict:
    """{"bubble": {"shown": [answers], "faces": [names]}, "groups": [{"title",
    "answers"}]} for the caller's own Take; 404 when it was sent nowhere."""
    me = str(user_id)
    session = _uuid(take)
    if not session:
        raise _not_found()
    mine = {str(m["id"]): str(m["thread_id"]) for m in _rows(
        _table(database, MEMBERS).select("id,thread_id").eq("user_id", me))}
    sent = [r for r in _rows(_table(database, MESSAGES).select("id,thread_id,author_member_id,meta,created_at")
                             .eq("kind", "take").in_("author_member_id", list(mine)))
            if str((r.get("meta") or {}).get("take_session_id")) == session] if mine else []
    if not sent:
        raise _not_found()
    sent.sort(key=lambda r: str(r.get("created_at") or ""))
    answers = []
    for i, s in enumerate(sent):
        thread = str(s["thread_id"])
        rows = _rows(_table(database, MESSAGES).select("id,author_member_id,kind,meta,created_at")
                     .eq("thread_id", thread))
        got = _first_answer(rows, str(s.get("created_at") or ""), str(s["author_member_id"]))
        if not got:
            continue
        other = next((m for m in _rows(_table(database, MEMBERS).select("id,user_id,display_name")
                                       .eq("thread_id", thread))
                      if str(m["id"]) == str(got["author_member_id"])), {})
        fit = (assistants.recipe_of(database, other.get("user_id")) or {}).get("fit") or {}
        answers.append({"message_id": str(got["id"]), "chat": thread, "coach": i == 0,
                        "name": str(other.get("display_name") or "").split(" ")[0] or None,
                        "title": ON_MATTER if fit.get("coaches") == "topic" else ON_SPEAKING,
                        "at": got.get("created_at")})
    groups = [{"title": t, "answers": [a for a in answers if a["title"] == t]}
              for t in (ON_SPEAKING, ON_MATTER)]
    shown = [a for a in answers if a["coach"]]
    for g in groups:
        best = next((a for a in g["answers"] if not a["coach"]), None)
        if best:
            shown.append(best)
    return {"bubble": {"shown": shown, "faces": [a["name"] for a in answers]},
            "groups": [g for g in groups if g["answers"]]}
