"""The blank setup of a host's chat, the recipe ``"v": 2`` (founder, the
Claude Code chat, 10 November 2026: N612, N616, N617, N618; the locked
prototype ``docs/design/the-blank-setup-2026-11-10/``). The contract, every
field with the prototype step that fills it, is in backend PR #1893.

  * ``start``: "What do you do?" typed in Will's chat: a blank recipe with
    Will's suggestions (``chat_suggestions.suggest``), each field set to his
    first one. Nothing from Artur's chat (N612 item 2).
  * ``set_part``: one decision, Keep or Change, saved (N616 item 7).
  * ``read``: the recipe, its parts as the prototype's "Your chat" lists
    them, the host's own chat for the list of chats, and its cost.
  * ``edit``: "I want to edit my chat", in any words: the parts open again
    (N618 item 8).
  * ``cost``: what the chat costs its host, in tokens (N617 item 2, N618
    items 1 and 5).
  * ``shared_models``: "Models you can use." (N617 item 1), and the models
    still learning, free, which the host's own answers teach (N633 item 1:
    ``teach``; ``price_changes`` once one passes its exam).
  * ``skipped_models``: someone else's models left out of a person's
    answer because the host had too few tokens (TOK-02), in ``read``.

Kept in ``people_profiles.chat_recipe`` beside the older builder's ``"v":
1`` recipe (``services/assistants.py``), which keeps working; ``welcome`` and
``answer_with`` are derived on every save, so joining and the bar read what
they read today. Behind the ring row ``chat_builder``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services import assistants, chat_suggestions
from services.assistants import RecipeError

logger = logging.getLogger(__name__)

V = 2
#: The prototype's "Something else", always the last tap (N604).
SOMETHING_ELSE = "Something else"
#: The prototype's "Here are your chat's parts. Tap one to change it."
PARTS_LINE = "Here are your chat's parts. Tap one to change it."
#: The prototype's ``done`` step: each part and its title.
PART_TITLES: tuple[tuple[str, str], ...] = (
    ("line", "Why people come"), ("send", "They send"), ("out", "They get back"),
    ("hello", "Your hello"), ("questions", "First questions"), ("taps", "They can ask"),
    ("models", "Your models"), ("who", "Who answers"))
WHO = tuple(w[1] for w in chat_suggestions.WHO)
PRICES = tuple(chat_suggestions.PRICES)
PARTS = ("line", "send", "out", "hello", "questions", "taps", "smart", "way", "models", "who",
         "share", "price", "cost", "care", "sensitive", "live")
MAX_QUESTIONS, MAX_MODELS = 3, 3
DAYS = 30


def _words(value: Any, most: int, field: str, *, empty: bool = False) -> str:
    text = " ".join(str(value or "").split()) if isinstance(value, str) else ""
    if not text and empty:
        return ""
    if not text or len(text) > most:
        raise RecipeError("RECIPE_INVALID", f"{field} must be 1 to {most} characters.")
    reason = assistants.check_host_words(text, verdicts=False)
    if reason:
        raise RecipeError("RECIPE_WORDS", f"{field}: {reason}.")
    return text


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise RecipeError("RECIPE_INVALID", f"{field} is yes or no.")
    return value


def _whole(value: Any, least: int, most: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not least <= value <= most:
        raise RecipeError("RECIPE_INVALID", f"{field} is a whole number from {least} to {most}.")
    return value


def _model(raw: Any, i: int) -> dict:
    if not isinstance(raw, dict):
        raise RecipeError("RECIPE_INVALID", f"Model {i + 1} must be an object.")
    opts = raw.get("opts")
    if not isinstance(opts, list) or len(opts) != 3:
        raise RecipeError("RECIPE_INVALID", f"Model {i + 1} has three answers.")
    out: dict[str, Any] = {"q": _words(raw.get("q"), 90, f"Model {i + 1}"),
                           "opts": [_words(o, 22, f"An answer of model {i + 1}") for o in opts],
                           "says": _words(raw.get("says"), 200, f"Model {i + 1}'s line", empty=True),
                           "own": raw.get("own", True) is not False}
    if out["own"] and raw.get("model_id"):
        # Kept only when it is the one made for this card (``_real_models``).
        out["model_id"] = str(raw["model_id"])[:64]
    if not out["own"]:
        out["model_id"] = str(raw.get("model_id") or "")[:64]
        if not out["model_id"]:
            raise RecipeError("RECIPE_INVALID", f"Model {i + 1} is someone's: name it.")
        out["by"] = _words(raw.get("by"), 60, f"Model {i + 1}'s owner")
        out["price"] = _whole(raw.get("price"), 0, 100000, f"Model {i + 1}'s price")
    return out


def _one_of(allowed: Any, message: str) -> Any:
    def check(value: Any) -> Any:
        if isinstance(value, bool) or value not in allowed:
            raise RecipeError("RECIPE_INVALID", message)
        return value
    return check


def _send(value: Any) -> list:
    if not isinstance(value, list) or not value or any(v not in chat_suggestions.SEND for v in value):
        raise RecipeError("RECIPE_INVALID", "Tick at least one of rec, text, photo, file.")
    return list(dict.fromkeys(value))


def _questions(value: Any) -> list:
    if not isinstance(value, list) or len(value) > MAX_QUESTIONS:
        raise RecipeError("RECIPE_INVALID", f"Up to {MAX_QUESTIONS} first questions.")
    return [{"q": _words(q.get("q") if isinstance(q, dict) else q, 160, f"Question {i + 1}")}
            for i, q in enumerate(value)]


def _taps(value: Any) -> list:
    # "Type my own" makes one tap; Will's suggestions are three (the prototype).
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise RecipeError("RECIPE_INVALID", "One to three taps.")
    taps = [_words(t, 44, f"Tap {i + 1}") for i, t in enumerate(value)]
    if SOMETHING_ELSE in taps:
        raise RecipeError("RECIPE_INVALID", f"“{SOMETHING_ELSE}” is always there.")
    return taps


def _models(value: Any) -> list:
    if not isinstance(value, list) or len(value) > MAX_MODELS:
        raise RecipeError("RECIPE_INVALID", f"Up to {MAX_MODELS} models.")
    return [_model(m, i) for i, m in enumerate(value)]


def _cost(value: Any) -> dict:
    if not isinstance(value, dict):
        raise RecipeError("RECIPE_INVALID", "How many people, and how often each sends.")
    return {"people": _whole(value.get("people"), 1, 100000, "People"),
            "sends": _whole(value.get("sends"), 1, 1000, "Sends")}


#: Each part's check, as the contract says (PR #1893).
_CLEAN: dict[str, Any] = {
    "line": lambda v: _words(v, 160, "Why people come"),
    "hello": lambda v: _words(v, 220, "Your hello"),
    "send": _send,
    "out": _one_of(tuple(chat_suggestions.OUT), "They get back answer, words, todo or mark."),
    "questions": _questions,
    "taps": _taps,
    "models": _models,
    "way": _one_of(("use", "own"), "Use one, or train your own."),
    "who": _one_of(WHO, "Who answers is shadow, you or assistant."),
    "price": _one_of(PRICES, f"A price is one of {list(PRICES)} tokens."),
    "cost": _cost,
    **{p: (lambda v, p=p: _bool(v, p)) for p in ("smart", "share", "care", "sensitive", "live")},
}


def _clean_part(part: str, value: Any) -> Any:
    """One part's value, checked as the contract says, or 400."""
    check = _CLEAN.get(part)
    if check is None:
        raise RecipeError("NOT_FOUND", "No such part.", 404)
    return check(value)


def _derived(recipe: dict) -> dict:
    """``welcome`` and ``answer_with`` as the older readers read them."""
    send = recipe.get("send") or []
    recipe["welcome"] = [recipe["hello"]] if recipe.get("hello") else []
    recipe["answer_with"] = {"record": "rec" in send, "type": "text" in send,
                             "tap": bool(recipe.get("taps"))}
    if not any(recipe["answer_with"].values()):
        recipe["answer_with"]["type"] = True
    return recipe


def _store(database: Any, user_id: str, recipe: dict) -> dict:
    stamp = datetime.now(timezone.utc).isoformat()
    stored = {**_derived(recipe), "v": V, "updated_at": stamp}
    table = database.client.table(assistants.PROFILES)
    if table.select("user_id").eq("user_id", str(user_id)).limit(1).execute().data or []:
        database.client.table(assistants.PROFILES).update(
            {assistants.COLUMN: stored, "updated_at": stamp}).eq("user_id", str(user_id)).execute()
    else:
        database.client.table(assistants.PROFILES).insert(
            {"user_id": str(user_id), assistants.COLUMN: stored}).execute()
    return stored


def mine(database: Any, user_id: Any) -> Optional[dict]:
    """The host's blank-setup recipe, or None (none, or the older one)."""
    recipe = assistants.recipe_of(database, user_id)
    return recipe if recipe and recipe.get("v") == V else None


# ── The routes' work ────────────────────────────────────────────────────

def start(database: Any, user_id: Any, body: Any) -> dict:
    """POST /v2/chats/setup/start {"what"}: a blank recipe, each field Will's
    first suggestion; 0 provider calls for a profession built in, else 1."""
    what = (body or {}).get("what") if isinstance(body, dict) else None
    spec = _words(what, chat_suggestions.MAX_SPEC, "What you do")
    spec = spec[0].upper() + spec[1:]
    sug, _calls = chat_suggestions.suggest(spec, user_id=str(user_id))
    first_out = sug["out"][0]
    # "A message" is ticked by default, so a visitor can type (N625 item 1).
    send = [sug["send"][0], *(["text"] if sug["send"][0] != "text" else [])]
    recipe = {"spec": spec, "suggest": sug, "line": sug["line"][0], "send": send,
              "out": first_out, "hello": sug["hello"][0], "questions": [{"q": sug["qs"][0]}],
              "taps": list(sug["taps"][0])[:3], "smart": False, "models": [], "who": WHO[0],
              "share": False, "sensitive": True, "live": False}
    return {"recipe": _store(database, str(user_id), recipe)}


def set_part(database: Any, user_id: Any, part: str, body: Any) -> dict:
    """PUT /v2/chats/setup/<part> {"value"}: one decision saved."""
    if part not in PARTS:
        raise RecipeError("NOT_FOUND", "No such part.", 404)
    recipe = mine(database, user_id)
    if recipe is None:
        raise RecipeError("NOT_STARTED", "Say what you do first.", 409)
    value = _clean_part(part, (body or {}).get("value") if isinstance(body, dict) else None)
    if part == "models":
        value = _agreed_prices(database, str(user_id), recipe, value)
        value = _real_models(database, str(user_id), recipe, value)
    if part == "who" and value == "assistant" and recipe.get("sensitive") is not False:
        # Health, law or money, or not answered yet: nothing goes out until
        # the host sends it (N616 item 13, N622 item 1).
        raise RecipeError("RECIPE_INVALID", "In this chat the host sends each answer.")
    if part in ("care", "sensitive"):
        # "Is your work about health, law or money?" (N622 item 1): ``care``
        # is its answer and sets ``sensitive``; with yes, "I answer at once"
        # falls back to "I draft, you send".
        recipe = {**recipe, "care": value, "sensitive": value}
        if value and recipe.get("who") == "assistant":
            recipe["who"] = WHO[0]
        stored = _store(database, str(user_id), recipe)
        return {"recipe": stored, "cost": cost(stored)}
    recipe = {**recipe, part: value}
    if part == "smart" and value is False:
        recipe["models"] = []
    if part == "share" and value is False:
        recipe.pop("price", None)
    stored = _store(database, str(user_id), recipe)
    return {"recipe": stored, "cost": cost(stored)}


def _real_models(database: Any, user_id: str, recipe: dict, models: list[dict]) -> list[dict]:
    """Each model the host makes here gets the real model behind it, made by
    the models' own "Start your own" (``model_setup_store.begin_from_chat``):
    owned by the host, private, ready for "Teach it". The same card kept
    again keeps its model: by the id it carries, or by its question. Only
    for a host with the AI models (ring ``ai_models``); without it the card
    stays as it is, with no ``model_id``."""
    from services import model_launchpad_store, model_setup_store
    before = [m for m in recipe.get("models") or [] if m.get("own", True) and m.get("model_id")]
    ids = {str(m["model_id"]) for m in before}
    by_q = {m["q"]: str(m["model_id"]) for m in before}
    sends = (recipe.get("send") or ["text"])[0]
    out = []
    for m in models:
        if not m.get("own", True):
            out.append(m)
            continue
        made = m.get("model_id") if m.get("model_id") in ids else by_q.get(m["q"])
        if not made and model_launchpad_store.enabled(database, user_id):
            made = model_setup_store.begin_from_chat(
                database, user_id, question=m["q"], answers=m["opts"], sends=sends)["model_id"]
            ids.add(made)
            by_q[m["q"]] = made
        out.append({**{k: v for k, v in m.items() if k != "model_id"},
                    **({"model_id": made} if made else {})})
    return out


def parts(recipe: dict) -> list[dict]:
    names = dict(chat_suggestions.SEND)
    gets = dict(chat_suggestions.OUT)
    labels = {w[1]: w[0] for w in chat_suggestions.WHO}
    values = {"line": recipe.get("line"),
              "send": " · ".join(names[k][0] for k in recipe.get("send") or [] if k in names),
              "out": gets.get(recipe.get("out") or "answer", ("",))[0],
              "hello": recipe.get("hello"),
              "questions": " · ".join(q["q"] for q in recipe.get("questions") or []),
              "taps": " · ".join(recipe.get("taps") or []),
              "models": " · ".join(m["q"] for m in recipe.get("models") or []) or "None yet",
              "who": labels.get(recipe.get("who") or "", "")}
    return [{"part": p, "title": t, "value": values[p]} for p, t in PART_TITLES]


def cost(recipe: Optional[dict]) -> Optional[dict]:
    """What the chat costs its host (N617 item 2): each model with its
    price, Free (0) for the host's own (N618 item 1); per send; a month
    from the typed people and sends."""
    if not recipe:
        return None
    lines = [{"q": m["q"], "by": m.get("by"), "price": 0 if m.get("own", True) else int(m.get("price") or 0)}
             for m in recipe.get("models") or []]
    per = sum(line["price"] for line in lines)
    typed = recipe.get("cost") or {}
    month = per * int(typed.get("people") or 0) * int(typed.get("sends") or 0) * DAYS if typed else None
    return {"lines": lines, "per_send": per, "month": month, "nothing": per == 0}


_YOU = "People come to you"


def join_line(recipe: Optional[dict], name: Any) -> Optional[str]:
    """The host's "Why people come" as a newcomer reads it before joining
    (N622 item 2): "People come to you ..." becomes "People come to
    {name} ..."; any other line as the host wrote it."""
    line = str((recipe or {}).get("line") or "").strip()
    if not line:
        return None
    first = str(name or "").split()
    who = first[0] if first else "WillpowerLab"
    return f"People come to {who}{line[len(_YOU):]}" if line.startswith(_YOU) else line


def own_chat(recipe: Optional[dict], name: Any) -> Optional[dict]:
    """The host's own chat in their list of chats, under their name
    (N618 item 8)."""
    if not recipe:
        return None
    first = str(name or "").split()
    return {"title": first[0] if first else "WillpowerLab", "line": recipe.get("hello"),
            "join_line": join_line(recipe, name)}


def read(database: Any, user_id: Any, token_payload: Any) -> dict:
    """GET /v2/chats/setup. ``own_chat.link`` is the host's own join link,
    the one GET /v2/chats/link gives ({"token", "path"}), made the first
    time as there, for the finished screen's link."""
    from services.chat_links import my_link, name_of
    recipe = mine(database, user_id)
    chat = own_chat(recipe, name_of(token_payload))
    if chat is not None:
        chat["link"] = my_link(database, user_id, token_payload)
    return {"recipe": recipe, "parts": parts(recipe) if recipe else [],
            "own_chat": chat, "cost": cost(recipe), "skipped_models": skipped_models(database, user_id, recipe),
            "price_changes": price_changes(database, recipe)}


def _owner_prices(database: Any, model_ids: list[str]) -> dict[str, Optional[int]]:
    """Each model's price as its owner set it now, in shown tokens."""
    from services.token_prices import shown
    if not model_ids:
        return {}
    try:
        rows = (database.client.table("ai_models").select("id,price_units")
                .in_("id", model_ids).execute().data or [])
    except Exception:  # noqa: BLE001 -- unknown: nothing is offered or changed
        logger.warning("chat_recipes: owners' prices could not be read", exc_info=True)
        return {}
    return {str(r["id"]): shown(r.get("price_units")) for r in rows}


def _used(recipe: Optional[dict]) -> list[dict]:
    return [m for m in (recipe or {}).get("models") or [] if not m.get("own", True) and m.get("model_id")]


def price_changes(database: Any, recipe: Optional[dict]) -> list[dict]:
    """[{"model_id", "q", "by", "was", "now"}]: another person's model in
    this host's chat whose owner's price ("now", tokens) is no longer the one
    saved when the host added it ("was"), which the host still pays (N630
    item 3). A model added while still learning shows here once it passed
    its exam and has a price, with "was" 0; until the host keeps it, it
    gives no line (N633 item 1). Keeping it at "now" is saving its card with
    that price; dropping it is saving the cards without it. This is only
    what changed; Will's words for it are N633 item 4's."""
    used = _used(recipe)
    now = _owner_prices(database, [str(m["model_id"]) for m in used])
    passed = _shared_for_tokens(database, [str(m["model_id"]) for m in used if m.get("learning")])
    return [{"model_id": m["model_id"], "q": m.get("q"), "by": m.get("by"),
             "was": int(m.get("price") or 0), "now": now[str(m["model_id"])]}
            for m in used if now.get(str(m["model_id"])) is not None
            and (not m.get("learning") or str(m["model_id"]) in passed)
            and now[str(m["model_id"])] != int(m.get("price") or 0)]


def _agreed_prices(database: Any, user_id: str, recipe: dict, models: list[dict]) -> list[dict]:
    """A card of another person's model carries the price the host agreed
    to: its owner's price now, or the one already saved on this host's card
    for that model (N630 item 3). Never any other number. A model still
    learning (no passed exam) is free: its card is saved with price 0 and
    ``learning`` true, and the host joins its teachers (N633 item 1). Once
    it passes, a card still learning stays so (no line, nothing charged)
    until the host keeps it at its owner's price (``price_changes``)."""
    saved = {str(m["model_id"]): m for m in _used(recipe)}
    theirs = [m for m in models if not m.get("own", True)]
    ids = [str(m["model_id"]) for m in theirs]
    now = _owner_prices(database, ids)
    passed = _shared_for_tokens(database, ids)
    out = []
    for i, m in enumerate(models):
        if m.get("own", True):
            out.append(m)
            continue
        mid, price = str(m["model_id"]), int(m["price"])
        before = saved.get(mid) or {}
        if mid not in passed or (before.get("learning") and price == 0):
            if price != 0 or (mid not in passed and not before.get("learning")
                              and not _may_learn_here(database, user_id, mid)):
                raise RecipeError("RECIPE_INVALID", f"Model {i + 1}'s price is its owner's price.")
            if mid not in saved:
                _join_teachers(database, user_id, mid)
            out.append({**m, "price": 0, "learning": True})
            continue
        allowed = {p for p in (now.get(mid), None if before.get("learning") else before.get("price"))
                   if p is not None}
        if price not in {int(p) for p in allowed}:
            raise RecipeError("RECIPE_INVALID", f"Model {i + 1}'s price is its owner's price.")
        out.append({k: v for k, v in m.items() if k != "learning"})
    return out


def _join_teachers(database: Any, user_id: str, model_id: str) -> None:
    """The host joins a model still learning as one of its teachers, by its
    own door (``model_launchpad_store.enter``, "This is my field"); one
    already teaching it stays as they are."""
    from services import model_launchpad_store
    from services.model_launchpad import viewer_role
    if viewer_role(model_launchpad_store._model(database, model_id), user_id) == "public":
        model_launchpad_store.enter(database, user_id, model_id)


def learning_models(recipe: Optional[dict]) -> list[str]:
    """The ids of the models still learning on this host's cards (N633 item
    1): they give no line and cost nothing; the host's answers teach them."""
    return [str(m["model_id"]) for m in _used(recipe) if m.get("learning")]


def teach(database: Any, host_id: Any, words: Any) -> list[str]:
    """The host answered someone in their own chat in their own words (a
    question answered by typing, or a draft they changed before sending):
    those words become an example of each model still learning on their
    cards, through the AI models' own "Add an example"
    (``model_launchpad_store.add_example``, source "teacher", added by the
    host), which the model's other teachers answer. Only the host's own
    words: nothing the person who wrote sent. Best-effort; the ids of the
    examples made."""
    from services import model_launchpad_store
    said = " ".join(str(words or "").split())
    made: list[str] = []
    if not said:
        return made
    recipe = mine(database, host_id)
    for mid in learning_models(recipe):
        try:
            made.append(model_launchpad_store.add_example(database, str(host_id), mid, {"text": said})["example_id"])
        except Exception:  # noqa: BLE001 -- the answer is sent either way
            logger.warning("chat_recipes: no example for model %s", mid, exc_info=True)
    return made


#: How far back "skipped_models" looks.
SKIPPED_DAYS = 7


def skipped_models(database: Any, user_id: Any, recipe: Optional[dict]) -> list[dict]:
    """[{"model_id", "q", "by", "on"}]: someone else's models in this host's
    chat left out of a person's answer in the last week because the host
    had too few tokens (TOK-02), newest first, one per model; "on" is the
    last day (YYYY-MM-DD). The words Will says about it wait for the
    founder; this is only what happened."""
    from datetime import timedelta

    from services import token_account
    theirs = {str(m.get("model_id")): m for m in (recipe or {}).get("models") or []
              if not m.get("own", True) and m.get("model_id")}
    if not theirs:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=SKIPPED_DAYS)).date().isoformat()
    return [{"model_id": r["model_id"], "q": theirs[r["model_id"]].get("q"),
             "by": theirs[r["model_id"]].get("by"), "on": r["on"]}
            for r in token_account.models_skipped(str(user_id), since=since, database=database)
            if r["model_id"] in theirs]


def edit(database: Any, user_id: Any, body: Any) -> dict:
    """POST /v2/chats/setup/edit {"said"}: any words open the parts again."""
    said = (body or {}).get("said") if isinstance(body, dict) else None
    if not isinstance(said, str) or not said.strip():
        raise RecipeError("RECIPE_INVALID", "Tell Will what to change.")
    recipe = mine(database, user_id)
    if recipe is None:
        raise RecipeError("NOT_STARTED", "Say what you do first.", 409)
    return {"line": PARTS_LINE, "parts": parts(recipe)}


def taps_of(recipe: dict) -> list[str]:
    return [*(recipe.get("taps") or []), SOMETHING_ELSE]


def for_visitors(recipe: Optional[dict]) -> Optional[dict]:
    """A recipe a person who joins may meet: the older one, or a blank-setup
    one the host opened (``live``)."""
    if not recipe:
        return None
    if recipe.get("v") == V and recipe.get("live") is not True:
        return None
    return recipe


def shared_models(database: Any, user_id: Any) -> dict:
    """GET /v2/chats/setup/models: "Models you can use." (N617 item 1):
    every public model someone else priced that passed its exam, with its
    question, three answers, owner and price per use in tokens; one that
    does not fit what this host's people send is greyed out (``fits``
    false) and says what it needs. Each says ``learning``: false for those;
    true for a public model, or one the host already teaches, that is
    still learning (N633 item 1), listed for a host with the AI models
    (ring ``ai_models``), whose ``price`` is 0: free while it learns. Never
    a photo model, never the host's own."""
    from services import model_launchpad_store as models
    teaching = _teaching(database, user_id)
    fields = "id,owner_id,owner_name,visibility,status,recipe,price_units"
    try:
        rows = (database.client.table(models.MODELS).select(fields)
                .eq("visibility", "public").limit(200).execute().data or [])
        extra = sorted((teaching or set()) - {str(r["id"]) for r in rows})
        if extra:
            rows += (database.client.table(models.MODELS).select(fields)
                     .in_("id", extra).execute().data or [])
    except Exception:  # noqa: BLE001 -- none listed
        return {"models": []}
    send = set((mine(database, user_id) or {}).get("send") or [])
    shared = _shared_for_tokens(database, [str(r["id"]) for r in rows])
    out = []
    for row in rows:
        learning = str(row["id"]) not in shared
        if _offered(row, str(user_id), teaching, learning):
            out.append(_offer(row, learning, send))
    return {"models": out}


def _offered(row: dict, user_id: str, teaching: Optional[set[str]], learning: bool) -> bool:
    """Is this model in the host's "Models you can use"? Not theirs, not
    archived or a draft, never a photo model (N616 item 9, LEARN-06); one
    that passed: public and priced; one still learning: public or one they
    teach, for a host with the AI models (N633 item 1)."""
    card = row.get("recipe") if isinstance(row.get("recipe"), dict) else {}
    if str(card.get("input") or "text") in ("image", "photo"):
        return False  # no model reads a photo yet (N616 item 9, LEARN-06)
    if str(row.get("owner_id")) == user_id or row.get("status") in ("archived", "draft"):
        return False
    if learning:
        return teaching is not None and (row.get("visibility") == "public" or str(row["id"]) in teaching)
    return row.get("price_units") is not None and row.get("visibility") == "public"


def _offer(row: dict, learning: bool, send: set) -> dict:
    from services.token_prices import shown
    card = row.get("recipe") if isinstance(row.get("recipe"), dict) else {}
    opts = card.get("scale") or card.get("options") or []
    needs = {"voice": "rec", "audio": "rec", "text": "text", "image": "photo",
             "photo": "photo", "file": "file"}.get(str(card.get("input") or "text"), "text")
    return {"model_id": str(row["id"]), "q": card.get("question") or "",
            "opts": [str(o.get("label") if isinstance(o, dict) else o) for o in opts][:3],
            "by": row.get("owner_name") or "", "price": 0 if learning else shown(row.get("price_units")),
            "needs": needs, "fits": needs in send, "learning": learning}


def _teaching(database: Any, user_id: Any) -> Optional[set[str]]:
    """The models this host teaches, by id; None for a host
    without the AI models (ring ``ai_models``), who is offered no model
    still learning: teaching one needs that ring."""
    from services import model_launchpad_store as models
    if not models.enabled(database, user_id):
        return None
    try:
        return {str(t["model_id"]) for t in database.client.table(models.TEACHERS).select("model_id,user_id")
                .eq("user_id", str(user_id)).execute().data or []}
    except Exception:  # noqa: BLE001 -- public ones only
        return set()


def _may_learn_here(database: Any, user_id: str, model_id: str) -> bool:
    """May this host add this model still learning (N633 item 1)? As it is
    offered in "Models you can use" (``_offered``)."""
    from services import model_launchpad_store as models
    teaching = _teaching(database, user_id)
    if teaching is None:
        return False
    try:
        rows = (database.client.table(models.MODELS).select("id,owner_id,visibility,status,recipe")
                .eq("id", model_id).limit(1).execute().data or [])
    except Exception:  # noqa: BLE001 -- not added
        return False
    return bool(rows) and _offered(rows[0], user_id, teaching, learning=True)


def _shared_for_tokens(database: Any, model_ids: list[str]) -> set[str]:
    """The models that passed their exam, as the app computed it: only they
    may be shared for tokens (N616 item 10: gate two, LEARN-04)."""
    if not model_ids:
        return set()
    from services.model_api import exam_passed
    try:
        rows = (database.client.table("ai_model_versions").select("model_id,status,exam")
                .in_("model_id", model_ids).execute().data or [])
    except Exception:  # noqa: BLE001 -- none shared
        return set()
    return {str(v["model_id"]) for v in rows
            if v.get("status") in ("passed", "released") and exam_passed(v)}
