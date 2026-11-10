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
  * ``shared_models``: "Models you can use." (N617 item 1).

Kept in ``people_profiles.chat_recipe`` beside the older builder's ``"v":
1`` recipe (``services/assistants.py``), which keeps working; ``welcome`` and
``answer_with`` are derived on every save, so joining and the bar read what
they read today. Behind the ring row ``chat_builder``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services import assistants, chat_suggestions
from services.assistants import RecipeError

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
         "share", "price", "cost", "sensitive", "live")
MAX_QUESTIONS, MAX_MODELS = 3, 3
DAYS = 30


def _words(value: Any, most: int, field: str, *, empty: bool = False) -> str:
    text = " ".join(str(value or "").split()) if isinstance(value, str) else ""
    if not text and empty:
        return ""
    if not text or len(text) > most:
        raise RecipeError("RECIPE_INVALID", f"{field} must be 1 to {most} characters.")
    reason = assistants.check_host_words(text)
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
    if not out["own"]:
        out["model_id"] = str(raw.get("model_id") or "")[:64]
        if not out["model_id"]:
            raise RecipeError("RECIPE_INVALID", f"Model {i + 1} is someone's: name it.")
        out["by"] = _words(raw.get("by"), 60, f"Model {i + 1}'s owner")
        out["price"] = _whole(raw.get("price"), 0, 100000, f"Model {i + 1}'s price")
    return out


def _clean_part(part: str, value: Any) -> Any:
    """One part's value, checked as the contract says, or 400."""
    if part == "line":
        return _words(value, 160, "Why people come")
    if part == "hello":
        return _words(value, 220, "Your hello")
    if part == "send":
        if not isinstance(value, list) or not value or any(v not in chat_suggestions.SEND for v in value):
            raise RecipeError("RECIPE_INVALID", "Tick at least one of rec, text, photo, file.")
        return list(dict.fromkeys(value))
    if part == "out":
        if value not in chat_suggestions.OUT:
            raise RecipeError("RECIPE_INVALID", "They get back answer, words, todo or mark.")
        return value
    if part == "questions":
        if not isinstance(value, list) or len(value) > MAX_QUESTIONS:
            raise RecipeError("RECIPE_INVALID", f"Up to {MAX_QUESTIONS} first questions.")
        return [{"q": _words(q.get("q") if isinstance(q, dict) else q, 160, f"Question {i + 1}")}
                for i, q in enumerate(value)]
    if part == "taps":
        if not isinstance(value, list) or len(value) != 3:
            raise RecipeError("RECIPE_INVALID", "Three taps.")
        taps = [_words(t, 44, f"Tap {i + 1}") for i, t in enumerate(value)]
        if SOMETHING_ELSE in taps:
            raise RecipeError("RECIPE_INVALID", f"“{SOMETHING_ELSE}” is always there.")
        return taps
    if part == "models":
        if not isinstance(value, list) or len(value) > MAX_MODELS:
            raise RecipeError("RECIPE_INVALID", f"Up to {MAX_MODELS} models.")
        return [_model(m, i) for i, m in enumerate(value)]
    if part == "way":
        if value not in ("use", "own"):
            raise RecipeError("RECIPE_INVALID", "Use one, or train your own.")
        return value
    if part == "who":
        if value not in WHO:
            raise RecipeError("RECIPE_INVALID", "Who answers is shadow, you or assistant.")
        return value
    if part == "price":
        if value not in PRICES or isinstance(value, bool):
            raise RecipeError("RECIPE_INVALID", f"A price is one of {list(PRICES)} tokens.")
        return value
    if part == "cost":
        if not isinstance(value, dict):
            raise RecipeError("RECIPE_INVALID", "How many people, and how often each sends.")
        return {"people": _whole(value.get("people"), 1, 100000, "People"),
                "sends": _whole(value.get("sends"), 1, 1000, "Sends")}
    if part in ("smart", "share", "sensitive", "live"):
        return _bool(value, part)
    raise RecipeError("NOT_FOUND", "No such part.", 404)


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
    recipe = {"spec": spec, "suggest": sug, "line": sug["line"][0], "send": [sug["send"][0]],
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
    recipe = {**recipe, part: value}
    if part == "smart" and value is False:
        recipe["models"] = []
    if part == "share" and value is False:
        recipe.pop("price", None)
    stored = _store(database, str(user_id), recipe)
    return {"recipe": stored, "cost": cost(stored)}


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


def own_chat(recipe: Optional[dict], name: Any) -> Optional[dict]:
    """The host's own chat in their list of chats, under their name
    (N618 item 8)."""
    if not recipe:
        return None
    first = str(name or "").split()
    return {"title": first[0] if first else "WillpowerLab", "line": recipe.get("hello")}


def read(database: Any, user_id: Any, name: Any) -> dict:
    """GET /v2/chats/setup."""
    recipe = mine(database, user_id)
    return {"recipe": recipe, "parts": parts(recipe) if recipe else [],
            "own_chat": own_chat(recipe, name), "cost": cost(recipe)}


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
    every public model someone else priced, with its question, three
    answers, owner and price per use in tokens; one that does not fit
    what this host's people send is greyed out (``fits`` false) and says
    what it needs."""
    from services import model_launchpad_store as models
    from services.token_prices import shown
    try:
        rows = (database.client.table(models.MODELS)
                .select("id,owner_id,owner_name,visibility,status,recipe,price_units")
                .eq("visibility", "public").limit(200).execute().data or [])
    except Exception:  # noqa: BLE001 -- none listed
        return {"models": []}
    send = set((mine(database, user_id) or {}).get("send") or [])
    out = []
    for row in rows:
        if str(row.get("owner_id")) == str(user_id) or row.get("price_units") is None \
                or row.get("status") == "archived":
            continue
        card = row.get("recipe") if isinstance(row.get("recipe"), dict) else {}
        opts = card.get("scale") or card.get("options") or []
        needs = {"voice": "rec", "audio": "rec", "text": "text", "image": "photo",
                 "photo": "photo", "file": "file"}.get(str(card.get("input") or "text"), "text")
        out.append({"model_id": str(row["id"]), "q": card.get("question") or "",
                    "opts": [str(o.get("label") if isinstance(o, dict) else o) for o in opts][:3],
                    "by": row.get("owner_name") or "", "price": shown(row.get("price_units")),
                    "needs": needs, "fits": needs in send})
    return {"models": out}
