"""The setup of a person's own chat, in Will's chat, one question at a time
(founder, the Claude Code chat, 9 November 2026: N578 item 4, N580 item 2,
N582 item 1, N586 items 1 and 5, N588 item 2). Will's words here are drafted
for the founder's OK (N582 item 1); a host's own answers are theirs (N578
item 6) and pass ``assistants.check_host_words``.

  * ``offer``: Will says what what you know is worth, with "Set up my chat"
    (N586 item 5); tapping it begins the setup.
  * ``begin``: the setup's first question, or its open question again.
  * ``answer``: a tap, or typed words, under Will's question; then his next
    lines. At the end, "Go live" keeps the recipe (``assistants.save``) and
    the person's chat is live (their assistant answers only once N606's
    minimum is reached, which is not built here); "Start again" begins again. Nothing is
    kept before "Go live".

The steps (N582 item 1): (1) the welcome; (2) navigation, how people answer
(record, type, tap answers, or any of these); (3) "What is your
specialization?", with what the person said of their field in their first
Take, and "Something else"; then what people learn with them, the join page's
one sentence (N601, N586 item 1); then N588's two lines: a
skill coach or a topic, and what they need to see; (4) the model, "Do you
want to automate your own chat?", after Will's plain line on what that
means; (5) the summary, to decide. The model's own setup (what it
recognises, its three answers, its signs) is the AI models' (MOD-*): the
recipe keeps only the person's choice.

Rows of the one Lounge thread (``lounge_messages``, kind "text"), each with
``metadata.chat_setup``: Will's sentence {"step": "say"}; Will's question
that waits {"step", "chips", "draft"}; the person's answer, role "user",
{"step": "answer", "to"}; the end {"step": "live"}.

In the MVP, Will's chat holds this setup, the model and its queue (N599):
nothing here writes a row for "Your principles", "The Sunday note" or "Your
life goals".

No provider call and no recording: nothing here passes the processing-
authorization path. Behind the ring row ``chat_builder`` (its routes).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from services import assistants
from services.assistants import RecipeError

logger = logging.getLogger(__name__)

_NS = uuid.UUID("3e8a1f52-7c4d-4b19-a6e2-91d0c5b7f3a8")
MAX_SAID = 300

# ── Will's words (drafted for the founder's OK, N582 item 1, N586 item 5) ─
WORTH = ("What you know can earn tokens: by teaching the models in your field, and you can "
         "spend them on a chat of your own that shares what you know while you're away, "
         "if you want it.")
SET_UP_MY_CHAT = "Set up my chat"
INTRO = "Let's set up your chat. People who join through your link will meet it."
WELCOME_Q = "What should people read first when they open your chat? Write it as you'd greet them."
NAV_Q = "How should people answer you in your chat?"
NAV = {"Record": ("record",), "Type": ("type",), "Tap answers": ("tap",),
       "Any of these": ("record", "type", "tap")}
SPEC_Q = "What is your specialization?"
SOMETHING_ELSE = "Something else"
LEARN_Q = "What can people learn in your chat? One sentence."
KIND_Q = "Do people come to you to be coached on how they do something, or with questions on a topic?"
HOW, TOPIC = "How they do it", "A topic"
NEEDS_Q = "What do you need to see to coach them?"
NEEDS = {"Them talking": "talking", "Them moving": "moving", "A photo": "photo",
         "Any message": "any"}
AUTOMATE_WHY = ("If you can't always be there, an assistant trained on your own answers can "
                "answer people while you're away, and bring every answer back to you here.")
AUTOMATE_Q = "Do you want to automate your own chat?"
AUTOMATE = {"Yes": "yes", "Not now": "no", "Help train an existing model": "help"}
#: Drafted for the founder's OK: the join page takes one short sentence (N601).
SHORTER = "Shorter, please: one sentence of about fifteen words, for your join page."
PEEK = "This is what someone new will meet in your chat:"
GO_LIVE, START_AGAIN = "Go live", "Start again"
#: Drafted for the founder's OK. The chat, not the assistant: the assistant
#: sends nothing until the minimum is reached (N606 item 1).
LIVE = "Your chat is live. Everyone who joins through your link meets it."
AGAIN = "Let's try that again. {reason}"
NOT_KEPT = "I can't put that in your chat: it reads like a score or a verdict about someone."

WAITS = ("offer", "welcome", "nav", "spec", "spec_own", "learn", "kind", "needs", "automate", "peek")


def _say(body: str) -> tuple:
    return (str(uuid.uuid4()), "bot", body, {"step": "say"})


def _ask(step: str, body: str, chips: list[str], draft: dict) -> tuple:
    return (str(uuid.uuid4()), "bot", body, {"step": step, "chips": chips, "draft": draft})


def _answer_id(question: str) -> str:
    return str(uuid.uuid5(_NS, f"{question}:answer"))


def _write(database: Any, user_id: str, items: list[tuple]) -> list[dict]:
    """Rows at the bottom of Will's chat, in order."""
    from services.lounge_messages import stamp_after, thread_stamp
    at = thread_stamp(database, user_id)
    rows = [{"client_id": cid, "role": role, "kind": "text", "body": body,
             "metadata": {"chat_setup": meta},
             "client_created_at": stamp_after(at, gap_ms=i) if i else at}
            for i, (cid, role, body, meta) in enumerate(items)]
    return database.insert_lounge_messages(str(user_id), rows) or []


def _setup_of(row: Optional[dict]) -> dict:
    meta = (row or {}).get("metadata") or {}
    setup = meta.get("chat_setup") if isinstance(meta, dict) else None
    return setup if isinstance(setup, dict) else {}


def _field(database: Any, user_id: str) -> list[str]:
    """What the person said of their field, for the specialization's
    bubbles (N582 item 1, step 3): the topic their plan keeps from their
    first Take, when there is one. Read by rules, no provider call."""
    try:
        plan = database.get_open_plan(str(user_id)) or {}
    except Exception:  # noqa: BLE001 -- no bubble, "Something else" still
        logger.warning("chat_setup: the plan could not be read", exc_info=True)
        return []
    raw = plan.get("facts")
    facts: dict = raw if isinstance(raw, dict) else {}
    topic = " ".join(str(facts.get("topic") or "").split())
    return [topic[:40].capitalize()] if topic and assistants.check_host_words(topic) is None else []


# ── The steps ───────────────────────────────────────────────────────────

def _own(said: str, step: str, body: str, draft: dict) -> Optional[list[tuple]]:
    """The person's own words checked (N578 item 6): None when they may be
    kept, else Will's line why and the same question again."""
    if assistants.check_host_words(said, verdicts=False) is None:
        return None
    return [_say(NOT_KEPT), _ask(step, body, [], draft)]


def _on_welcome(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id, picked
    refused = _own(said, "welcome", WELCOME_Q, draft)
    if refused:
        return refused
    draft["welcome"] = [said]
    return [_ask("nav", NAV_Q, list(NAV), draft)]


def _on_nav(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del said
    ways = NAV[picked]
    draft["answer_with"] = {k: k in ways for k in assistants.ANSWER_WITH}
    return [_ask("spec", SPEC_Q, [*_field(database, user_id), SOMETHING_ELSE], draft)]


def _on_spec(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id
    if picked == SOMETHING_ELSE:
        return [_ask("spec_own", SPEC_Q, [], draft)]
    return _spec(draft, picked or said)


def _on_spec_own(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id, picked
    return _spec(draft, said)


def _spec(draft: dict, spec: str) -> list[tuple]:
    refused = _own(spec, "spec_own", SPEC_Q, draft)
    if refused:
        return refused
    draft["spec"] = spec[:40]
    return [_ask("learn", LEARN_Q, [], draft)]


def _on_learn(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id, picked
    refused = _own(said, "learn", LEARN_Q, draft)
    if refused:
        return refused
    if assistants.learn_sentence_problem(said):
        return [_say(SHORTER), _ask("learn", LEARN_Q, [], draft)]
    draft["learn"] = said
    return [_ask("kind", KIND_Q, [HOW, TOPIC], draft)]


def _on_kind(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id, said
    if picked == HOW:
        draft["fit"] = {"coaches": "skill", "skill": draft.get("spec", "").lower()}
        return [_ask("needs", NEEDS_Q, list(NEEDS), draft)]
    draft["fit"] = {"coaches": "topic", "needs": "any", "topics": [draft.get("spec", "")]}
    return _automate(draft)


def _on_needs(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id, said
    draft["fit"] = {**(draft.get("fit") or {}), "needs": NEEDS[picked]}
    return _automate(draft)


def _automate(draft: dict) -> list[tuple]:
    return [_say(AUTOMATE_WHY), _ask("automate", AUTOMATE_Q, list(AUTOMATE), draft)]


def _on_automate(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, said
    draft["automate"] = AUTOMATE[picked]
    return _peek(user_id, draft)


def _recipe(name: str, draft: dict) -> dict:
    """The draft as a recipe: what people learn is the join page's one
    sentence (N601 item 1, N586 item 1); the specialization goes to the
    recipe's fit, not to the page."""
    del name
    learn = str(draft.get("learn") or "").strip()
    return {"welcome": draft.get("welcome") or [], "answer_with": draft.get("answer_with"),
            "about": [learn] if learn else [], "fit": draft.get("fit"),
            "model": {"automate": draft.get("automate", "no")}}


def _peek(user_id: str, draft: dict) -> list[tuple]:
    del user_id
    name = str(draft.get("name") or "WillpowerLab")
    recipe = _recipe(name, draft)
    # The join page in its three lines (N601), then the welcome inside.
    lines = [assistants.INVITED.format(name=name), *recipe["about"], assistants.ONLY_TWO,
             *recipe["welcome"]]
    return [_ask("peek", "\n".join([PEEK, *lines]), [GO_LIVE, START_AGAIN], draft)]


def _on_peek(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del said
    if picked == START_AGAIN:
        name = draft.get("name")
        return [_ask("welcome", WELCOME_Q, [], {"name": name} if name else {})]
    recipe = _recipe(str(draft.get("name") or "WillpowerLab"), draft)
    # The setup asks no first-Take questions: the ones set in the builder stay.
    recipe["questions"] = (assistants.recipe_of(database, user_id) or {}).get("questions") or []
    assistants.save(database, user_id, recipe)
    return [(str(uuid.uuid4()), "bot", LIVE, {"step": "live"})]


def _on_offer(database: Any, user_id: str, draft: dict, picked: str, said: str) -> list[tuple]:
    del database, user_id, picked, said
    return [_say(INTRO), _ask("welcome", WELCOME_Q, [], draft)]


STEPS = {"offer": _on_offer, "welcome": _on_welcome, "nav": _on_nav, "spec": _on_spec,
         "spec_own": _on_spec_own, "learn": _on_learn, "kind": _on_kind, "needs": _on_needs,
         "automate": _on_automate, "peek": _on_peek}
#: The steps answered by a tap only.
TAPPED = ("offer", "nav", "kind", "needs", "automate", "peek")


# ── In and out ──────────────────────────────────────────────────────────

def _open_question(database: Any, user_id: str) -> Optional[dict]:
    for row in database.get_lounge_messages_page(str(user_id), limit=60) or []:
        setup = _setup_of(row)
        if setup:
            return row if setup.get("step") in WAITS else None
    return None


def retired(database: Any, user_id: str) -> bool:
    """N632 item 1: for a person with the chat builder, the chat is set up in
    the overlay (services/chat_recipes.py), one decision per screen; Will's
    chat no longer gets this setup's offer line or its questions as
    bubbles. A chat already made here keeps working (its recipe stays and is
    read as before) until its owner sets it up again."""
    return assistants.on(database, user_id)


def offer(database: Any, user_id: str, name: str) -> dict:
    """Will's line on what you know is worth, with "Set up my chat" (N586
    item 5), once while no setup waits. Never for a person with the new
    setup (N632 item 1)."""
    if retired(database, user_id) or _open_question(database, user_id):
        return {"offered": False}
    _write(database, user_id, [_ask("offer", WORTH, [SET_UP_MY_CHAT], {"name": name})])
    return {"offered": True}


def begin(database: Any, user_id: str, name: str) -> dict:
    """The setup's first lines, or its open question again at the bottom.
    Nothing for a person with the new setup (N632 item 1)."""
    if retired(database, user_id):
        return {"started": False}
    waiting = _open_question(database, user_id)
    if waiting:
        items = [(str(uuid.uuid4()), "bot", waiting.get("body") or "", _setup_of(waiting))]
    else:
        items = [_say(INTRO), _ask("welcome", WELCOME_Q, [], {"name": name})]
    _write(database, user_id, items)
    return {"started": True}


def answer(database: Any, user_id: str, payload: Any) -> dict:
    """The person's tap, or their words, under Will's question; then his next
    lines. {"messages": the rows written}. For a person with the new setup
    no question of this setup waits any more (N632 item 1): 404."""
    if retired(database, user_id):
        raise RecipeError("NOT_FOUND", "No such question.", 404)
    body = payload if isinstance(payload, dict) else {}
    to = str(body.get("to") or "")
    setup = _setup_of(database.get_lounge_message_by_client_id(str(user_id), to) if to else None)
    step = setup.get("step")
    if step not in WAITS:
        raise RecipeError("NOT_FOUND", "No such question.", 404)
    if database.get_lounge_message_by_client_id(str(user_id), _answer_id(to)):
        raise RecipeError("ANSWERED", "Already answered.", 409)
    picked = str(body.get("picked") or "").strip()
    said = " ".join(str(body.get("said") or "").split())[:MAX_SAID]
    chips = list(setup.get("chips") or [])
    if (picked and picked not in chips) or not (picked or said) or (step in TAPPED and not picked):
        raise RecipeError("PICK_ONE", "Tap one of the answers.")
    draft = dict(setup.get("draft") or {})
    rows = STEPS[step](database, user_id, draft, picked, "" if picked else said)
    mine_ = (_answer_id(to), "user", picked or said, {"step": "answer", "to": to})
    return {"messages": _write(database, user_id, [mine_, *rows])}
