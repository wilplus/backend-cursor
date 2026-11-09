"""Every inviter's own chat, answered by "{name}'s assistant" (founder, the
Claude Code chat, 9 November 2026: N578, N579, N580, N585, N586, N588).

A person meets the chat of whoever's link they came by (N578 item 1). Will's
engine runs it underneath, with N565's rules and checks; the person's
assistant answers questions in that chat for them, labelled as theirs, so it
says plainly that an AI answers (AI Act article 50, N580 item 3). A Take is
never answered by an assistant: the person it reaches answers it in their
own voice (N580 item 7).

This module is the chat's contract, pure, with no table and no provider
call:

  * ``assistant_name``: "{name}'s assistant" (signed, N578 item 1).
  * The recipe (N578 item 7, N579): one per chat. ``DEFINABLE`` is what a
    host sets in the MVP (the welcome, the first Take's questions, how
    people answer); ``LATER`` comes after it (the profession, the style; of the
    model, only the host's yes is kept now); ``LOCKED`` is never a host's (the Nevers, consent, the recording
    screens, the walk's order, the bar, where the chat is offered).
    ``normalize`` turns what a host sends into a recipe or refuses it with a
    code; ``starting_questions`` is where the builder starts, Artur's five
    (N462, N579 item 1).
  * ``check_host_words``: a host's own words need no founder's OK, but pass
    the same checks as Will's written bubbles (N578 item 6): no number or
    verdict about the speaker (Never 1) and nothing that says they are
    broken.
  * ``mark``: an assistant's answer is green (sure), yellow (in between) or
    red (unsure), never a number (N580 item 3). ``read_line``: a host's
    simple recognizer reads on one line with two cuts (N585 item 2).
  * ``suits`` and ``nudge``: Will suggests a skill coach only for a message
    that shows the skill and a topic expert only for their topic; anyone may
    still be sent to, with one line (N588).
  * ``will_line``: the join page's line about Will's chat (N586 item 2).

Behind the ring row ``chat_builder`` (N579 item 2): the founder and the
people the founder adds. Everyone else keeps today's chat.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from services.chats import ChatsError

logger = logging.getLogger(__name__)

#: The ring row of the chat builder and of the assistants (N579 item 2). No
#: row until the founder makes one in the panel; until then it is off for
#: everyone, the founder included.
CHAT_BUILDER = "chat_builder"

# ── The words ───────────────────────────────────────────────────────────
#: Signed (N578 item 1, Never 4).
ASSISTANT = "{name}'s assistant"
#: Drafted for the founder's OK (N586 item 2): replaces "Your own chat with
#: Will, your speaking coach" on the join page.
WILL_LINE = "Will's chat is where you can set up a chat of your own."
#: Drafted for the founder's OK (N588 item 5); "Record" and "Send anyway".
NUDGE_HEAR = "{name} coaches {skill} and will need to hear you. Record it instead?"
NUDGE_SEE = "{name} coaches {skill} and will need to see you doing it. Record a video instead?"
RECORD, SEND_ANYWAY = "Record", "Send anyway"

# ── The recipe (N578 items 5 and 7, N579 items 1 and 4) ─────────────────
#: What a host sets in the MVP, and the two parts N586 and N588 add: the
#: lines that say who they are and what people learn with them (``about``,
#: N586 item 1) and the two lines of who their chat is for (``fit``: a
#: skill coach or a topic expert, and what they need to see, N588 item 2).
#: ``model`` keeps only the host's answer to "Do you want to automate your
#: own chat?" (N582 item 1, step 4); the model's own setup is the AI
#: models' (MOD-*).
DEFINABLE: tuple[str, ...] = ("welcome", "questions", "answer_with", "about", "fit", "model")
AUTOMATE: tuple[str, ...] = ("yes", "no", "help")
MAX_ABOUT_LINES = 2
MAX_TOPICS = 6
#: What comes after the MVP (N579 item 1); its fields are read but not set.
LATER: tuple[str, ...] = ("profession", "style")
#: Never a host's (N578 item 5).
LOCKED: tuple[str, ...] = ("nevers", "consent", "recording_screens", "walk_order",
                           "bar", "where_offered")
#: How people answer when the assistant asks something (N579 item 1): tap
#: answers, and whether they may type, record, or both.
ANSWER_WITH: tuple[str, ...] = ("tap", "type", "record")
MAX_WELCOME_LINES = 4
MAX_LINE = 300
MAX_QUESTIONS = 8
MAX_QUESTION = 160
MAX_UNDER = 120
MAX_TITLE = 40
MAX_ANSWERS = 6
MAX_ANSWER = 40


class RecipeError(ChatsError):
    """A recipe a host sent that cannot be kept, with its code: answered by
    the chats' routes as their own errors, 400."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code, message, status)


def assistant_name(name: Any) -> str:
    """"{name}'s assistant", by the person's first name; a person with no
    name is named as the chats name them (``chat_links.name_of``)."""
    first = str(name or "").split()
    return ASSISTANT.format(name=first[0] if first else "WillpowerLab")


def starting_questions() -> list[dict]:
    """The builder's start: Artur's five, one slide each (N462, N579 item 1),
    to keep, change, add to or remove."""
    from services.plan import FIRST_TAKE_SLIDES
    return [{"title": title, "q": q, "under": under, "answers": []}
            for title, q, under, _ in FIRST_TAKE_SLIDES]


# ── A host's own words (N578 item 6) ────────────────────────────────────
#: A verdict about the speaker, or words that say they are broken (Never 1,
#: N557). Whole words, any case. A host may name a number of their own
#: ("five minutes"), never a score about the person.
_VERDICTS: tuple[str, ...] = (
    "score", "scores", "scored", "rating", "rated", "grade", "graded", "verdict",
    "wrong", "mistake", "mistakes", "weak", "weakness", "broken", "bad", "worst",
    "fail", "failed", "failing", "failure", "fix", "fixing",
)
_SCORE = re.compile(r"\d\s*(%|/\s*\d|out of\b|points?\b|pts\b|stars?\b)", re.I)
_WORD = re.compile(r"[a-z']+")


def check_host_words(text: Any) -> Optional[str]:
    """None when a host's own line may reach the people in their chat, else
    the reason. Pure."""
    said = str(text or "").strip()
    if not said:
        return "empty"
    if _SCORE.search(said):
        return "a score (Never 1)"
    words = set(_WORD.findall(said.lower()))
    for word in _VERDICTS:
        if word in words:
            return f"a verdict: {word}"
    return None


def _line(value: Any, longest: int, field: str) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > longest:
        raise RecipeError("RECIPE_INVALID", f"{field} must be 1 to {longest} characters.")
    reason = check_host_words(text)
    if reason:
        raise RecipeError("RECIPE_WORDS", f"{field}: {reason}.")
    return text


def _question(raw: Any, i: int) -> dict:
    if not isinstance(raw, dict):
        raise RecipeError("RECIPE_INVALID", f"Question {i + 1} must be an object.")
    out: dict[str, Any] = {"q": _line(raw.get("q"), MAX_QUESTION, f"Question {i + 1}")}
    for key, longest in (("title", MAX_TITLE), ("under", MAX_UNDER)):
        if raw.get(key):
            out[key] = _line(raw.get(key), longest, f"Question {i + 1}'s {key}")
    answers = raw.get("answers") or []
    if not isinstance(answers, list) or len(answers) > MAX_ANSWERS:
        raise RecipeError("RECIPE_INVALID", f"Question {i + 1} takes up to {MAX_ANSWERS} answers.")
    out["answers"] = [_line(a, MAX_ANSWER, f"An answer to question {i + 1}") for a in answers]
    return out


def normalize(body: Any) -> dict:
    """What a host sends to the builder, as a recipe: ``{"welcome": [lines],
    "questions": [{"q", "title"?, "under"?, "answers"}], "answer_with":
    {"tap", "type", "record"}}``. A locked or later field is refused, so
    nothing a host sends reaches what is not theirs."""
    if not isinstance(body, dict):
        raise RecipeError("RECIPE_INVALID", "Send the recipe as an object.")
    for key in body:
        if key in LOCKED:
            raise RecipeError("RECIPE_LOCKED", f"{key} is not yours to set.")
        if key not in DEFINABLE:
            raise RecipeError("RECIPE_INVALID", f"{key} cannot be set yet.")
    welcome = body.get("welcome") or []
    if not isinstance(welcome, list) or len(welcome) > MAX_WELCOME_LINES:
        raise RecipeError("RECIPE_INVALID", f"The welcome is up to {MAX_WELCOME_LINES} lines.")
    questions = body.get("questions") or []
    if not isinstance(questions, list) or len(questions) > MAX_QUESTIONS:
        raise RecipeError("RECIPE_INVALID", f"Up to {MAX_QUESTIONS} questions.")
    raw_with = body.get("answer_with")
    with_ = raw_with if isinstance(raw_with, dict) else {}
    answer_with = {k: bool(with_.get(k, True)) for k in ANSWER_WITH}
    if not (answer_with["type"] or answer_with["record"] or answer_with["tap"]):
        raise RecipeError("RECIPE_INVALID", "People need at least one way to answer.")
    about = body.get("about") or []
    if not isinstance(about, list) or len(about) > MAX_ABOUT_LINES:
        raise RecipeError("RECIPE_INVALID", f"Who you are is up to {MAX_ABOUT_LINES} lines.")
    out = {"welcome": [_line(w, MAX_LINE, f"Welcome line {i + 1}") for i, w in enumerate(welcome)],
           "questions": [_question(q, i) for i, q in enumerate(questions)],
           "answer_with": answer_with,
           "about": [_line(a, MAX_LINE, f"About line {i + 1}") for i, a in enumerate(about)]}
    if body.get("fit") is not None:
        out["fit"] = _fit(body.get("fit"))
    if body.get("model") is not None:
        model = body.get("model")
        if not isinstance(model, dict) or model.get("automate") not in AUTOMATE:
            raise RecipeError("RECIPE_INVALID", "Say whether to automate your chat.")
        out["model"] = {"automate": model["automate"]}
    return out


def _fit(raw: Any) -> dict:
    """The two lines of N588 item 2: a skill coach or a topic expert, and
    what they need to see."""
    if not isinstance(raw, dict) or raw.get("coaches") not in ("skill", "topic"):
        raise RecipeError("RECIPE_INVALID", "Say whether you coach a skill or answer a topic.")
    needs = raw.get("needs") or ("any" if raw["coaches"] == "topic" else None)
    if needs not in NEEDS:
        raise RecipeError("RECIPE_INVALID", "Say what you need to see.")
    topics = raw.get("topics") or []
    if not isinstance(topics, list) or len(topics) > MAX_TOPICS:
        raise RecipeError("RECIPE_INVALID", f"Up to {MAX_TOPICS} topics.")
    fit = {"coaches": raw["coaches"], "needs": needs,
           "topics": [_line(t, MAX_ANSWER, "A topic") for t in topics]}
    if raw.get("skill"):
        fit["skill"] = _line(raw["skill"], MAX_ANSWER, "The skill")
    return fit


# ── How sure (N580 item 3, N585 item 2) ─────────────────────────────────
GREEN, YELLOW, RED = "green", "yellow", "red"


def read_line(value: float, lower: float, upper: float, near: float) -> dict:
    """A simple recognizer's read on its one line, from its No answer to its
    Yes answer (N585 item 2): past ``upper`` it gives Yes, below ``lower``
    No; between them it can't tell, and the item goes to the queue in Will's
    chat. Its colour is how far it is from the nearest cut: green far,
    yellow within ``near``, red between. The numbers stay in the owner's
    setup (Never 1, N585 item 8): this answers a side and a colour only."""
    if lower > upper:
        lower, upper = upper, lower
    if value >= upper:
        side, gap = "yes", value - upper
    elif value <= lower:
        side, gap = "no", lower - value
    else:
        return {"answer": None, "mark": RED, "queue": True}
    return {"answer": side, "mark": GREEN if gap > near else YELLOW, "queue": False}


# ── Sensible suggestions (N588) ─────────────────────────────────────────
#: What a skill coach needs to see or hear (N588 item 2), and the message
#: kinds that show it.
NEEDS: dict[str, frozenset[str]] = {
    "talking": frozenset({"voice", "take", "video"}),
    "moving": frozenset({"video"}),
    "photo": frozenset({"photo", "video"}),
    "any": frozenset({"text", "voice", "take", "video", "photo", "file"}),
}


def suits(person: dict, message: dict) -> bool:
    """Will suggests ``person`` for ``message`` only when the message gives
    them what they need (N588 item 3). ``person``: ``{"coaches": "skill" |
    "topic", "needs": a key of NEEDS, "topics": [words]}``, the two lines of
    their setup; ``message``: ``{"kind", "topic"?: words}``. A skill coach
    needs the skill shown, whatever the topic; a topic expert needs their
    topic, from any message."""
    kind = str(message.get("kind") or "")
    if person.get("coaches") == "skill":
        return kind in NEEDS.get(str(person.get("needs") or ""), frozenset())
    topic = set(_WORD.findall(str(message.get("topic") or "").lower()))
    theirs = {w for t in person.get("topics") or [] for w in _WORD.findall(str(t).lower())}
    return bool(topic & theirs)


def nudge(name: str, person: dict, message: dict) -> Optional[dict]:
    """When the speaker adds someone their message doesn't suit, Will's one
    line, once, with "Record" and "Send anyway" (N588 item 5); None when it
    suits, or for a topic expert (anyone can be asked about their topic)."""
    if person.get("coaches") != "skill" or suits(person, message):
        return None
    skill = str(person.get("skill") or "").strip() or "this"
    hear = person.get("needs") == "talking"
    line = (NUDGE_HEAR if hear else NUDGE_SEE).format(name=name, skill=skill)
    return {"line": line, "chips": [RECORD, SEND_ANYWAY]}


def will_line() -> str:
    """The join page's line about Will's chat (N586 item 2)."""
    return WILL_LINE


# ── The recipe, kept (people_profiles.chat_recipe,
#    migrations/a_person_keeps_their_chat_recipe.sql) ─────────────────────
PROFILES, COLUMN = "people_profiles", "chat_recipe"
MESSAGES, MEMBERS = "chat_messages", "chat_members"


def on(database: Any, user_id: Any) -> bool:
    """Does this person have the chat builder (N579 item 2)?"""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(CHAT_BUILDER, str(user_id), database=database)


def recipe_of(database: Any, user_id: Any) -> Optional[dict]:
    """A person's kept recipe, or None: none kept, or a database without the
    column yet, which reads as none (nothing anyone meets changes)."""
    try:
        rows = (database.client.table(PROFILES).select(f"user_id,{COLUMN}")
                .eq("user_id", str(user_id)).limit(1).execute().data or [])
    except Exception:
        logger.warning("assistants: the recipe could not be read", exc_info=True)
        return None
    value = rows[0].get(COLUMN) if rows else None
    return value if isinstance(value, dict) else None


def builder(database: Any, user_id: Any, name: Any) -> dict:
    """GET /v2/chats/recipe: the host's assistant's name, their recipe as
    kept (or null), the builder's start (Artur's five) and what stays
    locked."""
    return {"assistant": assistant_name(name), "recipe": recipe_of(database, user_id),
            "starting_questions": starting_questions(), "locked": list(LOCKED)}


def save(database: Any, user_id: Any, body: Any) -> dict:
    """PUT /v2/chats/recipe: the recipe replaced; {"recipe"}. Refused with
    the recipe's code (400) before anything is written."""
    from datetime import datetime, timezone
    recipe = normalize(body)
    stamp = datetime.now(timezone.utc).isoformat()
    stored = {**recipe, "v": 1, "updated_at": stamp}
    table = database.client.table(PROFILES)
    if (table.select("user_id").eq("user_id", str(user_id)).limit(1).execute().data or []):
        table.update({COLUMN: stored, "updated_at": stamp}).eq("user_id", str(user_id)).execute()
    else:
        table.insert({"user_id": str(user_id), COLUMN: stored}).execute()
    return {"recipe": stored}


def host_of(database: Any, user_id: Any, thread_id: Any) -> Optional[dict]:
    """GET /v2/chats/<id>/host: for someone in a chat with a host who has a
    recipe, what that chat is: {"assistant", "about", "questions",
    "answer_with"}. None for the host themself, for a chat with no other
    person, and for a host with no recipe (the chat is as it was)."""
    members = (database.client.table(MEMBERS).select("user_id,display_name")
               .eq("thread_id", str(thread_id)).execute().data or [])
    if str(user_id) not in {str(m.get("user_id")) for m in members}:
        return None
    host = next((m for m in members if m.get("user_id") and str(m["user_id"]) != str(user_id)), None)
    if not host or not on(database, host["user_id"]):
        return None
    recipe = recipe_of(database, host["user_id"])
    if not recipe:
        return None
    return {"assistant": assistant_name(host.get("display_name")),
            "about": recipe.get("about") or [], "questions": recipe.get("questions") or [],
            "answer_with": recipe.get("answer_with") or {k: True for k in ANSWER_WITH}}


def welcome(database: Any, thread: str, owner_id: str, owner_member: str) -> list[dict]:
    """A chat just made through a host's link: the host's welcome, first,
    as their assistant's messages (N590 item 2, N580 item 3), before their
    join questions. Best-effort: joining never fails on it; nothing for a
    host without the ring or without a welcome."""
    try:
        if not on(database, owner_id):
            return []
        recipe = recipe_of(database, owner_id) or {}
        posted: list[dict] = []
        for i, line in enumerate(recipe.get("welcome") or []):
            rows = (database.client.table(MESSAGES).insert({
                "thread_id": thread, "author_member_id": owner_member, "kind": "text",
                "body": line, "meta": {"welcome": {"i": i}, "assistant": True}}).execute().data or [])
            posted.extend(rows)
        return posted
    except Exception:  # noqa: BLE001
        logger.warning("assistants: the welcome did not begin in %s", thread, exc_info=True)
        return []


def about_lines(database: Any, owner_id: Any) -> list[str]:
    """The join page's lines on who the host is and what you can learn with
    them (N586 item 1): the host's own, from their recipe."""
    return list((recipe_of(database, owner_id) or {}).get("about") or [])
