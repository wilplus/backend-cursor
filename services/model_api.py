"""A model's API and its money: the card, trying it, the terms, a key shown
once, the code, usage and pinned versions, the price and its split, a
teacher's earnings, and downloading its data (N528 items 6, 7, 11 and 12,
N531, N563, N566 items 8 to 10, N577, N581, N583; the locked prototype
``docs/design/model-launchpad-2026-11-09/``, version 8, screens card, try,
use, key, code, usage, price, earnings and download).

Like ``services/model_launchpad.py`` this module has no storage of its own:
every function takes plain dicts and returns plain dicts. The tables
(migration a_business_can_buy_a_model_s_answers) are read by
``services/model_api_store.py``.

MONEY IS IN STORED TOKEN UNITS (N583 item 2: "tokens per answer"). One stored
unit is what ``services/token_prices.py`` stores; ``token_prices.shown`` turns
it into the tokens a person sees. The prototype's euro samples translate at
one shown token (v4) to one euro cent: its €0.03 is 300 units, its €0.006
running cost 60 units, its €20 minimum payout 200,000 units.

THE SPLIT (N531 item 1, N577, N583 item 3), for each answer sold:
  1. the running costs, at cost;
  2. WillpowerLab: 20% of the margin (the price less the running costs);
  3. the model's founder: 10% of what is left;
  4. the teachers: the rest, by their points, fixed per version.
Integer units; the fee and the founder's part are rounded down, and the
remainder goes to the teachers, so the parts always add up to the price.
"""
from __future__ import annotations

import hashlib
import re
import math
import secrets
from typing import Any, Iterable, Optional

from services.model_launchpad import viewer_role

# ── The numbers (N577, N531, N566 item 9; the prototype's C) ────────────────
#: WillpowerLab's fee: 20% of the margin, every model and every version (N577 item 1).
FEE_SHARE = 0.20
#: The model's founder: 10% of what is left after the fee (N577 item 2).
FOUNDER_SHARE = 0.10
#: What one answer costs to run (the AI company and our servers), per base
#: model; the price's floor (N531 item 3). The prototype's €0.006.
RUNNING_COST_UNITS = {"gpt-4o-mini": 60}
DEFAULT_RUNNING_COST_UNITS = 60
#: "Similar models charge €0.02 to €0.05" and the three suggestions (N566 item 10).
SUGGESTED_PRICES_UNITS = (200, 300, 500)
DEFAULT_PRICE_UNITS = 300
#: The − and + step: a tenth of a shown token (the prototype rounds to €0.001).
PRICE_STEP_UNITS = 10
#: Free answers on a test key, which never bills (N566 item 9).
FREE_TEST_ANSWERS = 100
#: The monthly limits offered (the prototype's €20, €50, €100).
MONTHLY_LIMITS_UNITS = (200_000, 500_000, 1_000_000)
DEFAULT_MONTHLY_LIMIT_UNITS = 500_000
#: The minimum before earned tokens are credited (N531 item 4: "a starting
#: point: EUR 20"). Open. Nothing is paid out in money (N614): what a model
#: earned is credited as tokens, to spend in the app.
MINIMUM_PAYOUT_UNITS = 200_000
#: A hard clip is worth more (N531 item 2): the model was between these
#: sureness values on it; its answer's points are multiplied by HARD_WEIGHT.
HARD_LO, HARD_HI, HARD_WEIGHT = 0.40, 0.60, 1.5
#: The model is sure when its own confidence is at least this (N566 item 8).
SURE_AT = 0.70
#: How long a question may be.
MAX_QUESTION = 4000

KEY_PREFIX = {"test": "wpl_sk_test_", "live": "wpl_sk_live_"}

# ── Signed words (N566 item 1: the locked prototype's words) ────────────────
WORDS: dict[str, str] = {
    # the card (MOD-39)
    "card_good_at": "Good at",
    "card_not_so_good_at": "Not so good at",
    "card_not_for": "Not for",
    "card_exam": "On its final exam",
    "card_exam_line": ("Coaches who didn’t know which answer was whose rated its answers "
                       "as good as a coach’s about {k} times in 10."),
    "card_unsure": "When it isn’t sure",
    "card_unsure_line": "It says so, and a coach answers instead",
    "card_version": "Version",
    "card_foot": "Try it for free. Use it in your own product, and pay for each answer.",
    "use_it": "Use it in your business",
    "try_it": "Try it",
    # trying it (MOD-40, MOD-45)
    "try_ready": "ready to use",
    "try_not_for_sale": "trying it · not for sale yet",
    "unsure_reply": ("I’m not sure about this one, so I won’t guess. One of the coaches "
                     "who taught me will answer it here within a day."),
    "unsure_mark": "Not sure · a coach will answer",
    # the terms (MOD-41)
    "use_title": "Use it in your business",
    "use_inside": "You can put {name} inside your own app or website.",
    "use_pay": ("You pay for each answer it gives. Part of what you pay goes to WillpowerLab, "
                "and the rest goes to the {people} who taught it."),
    "use_may": "You may use its answers in your product. You may not copy the model or resell its data.",
    "use_price": "{price} an answer",
    "use_no_fee": "No monthly fee. Stop any time.",
    "use_test_key": "Start with a test key",
    "use_test_key_line": "Free for your first 100 answers. It never bills you.",
    "use_limit": "Set a monthly limit",
    "use_limit_line": "{limit} · a mistake can never cost you more than you chose",
    "use_training": "Your users’ questions are not used to train it unless you allow it.",
    "create_key": "Create a key",
    "not_now": "Not now",
    # the key, once (MOD-42)
    "key_title": "Your key",
    "key_line": "This is your secret key. It lets your product talk to {name}.",
    "key_test": ("This is a test key: free for 100 answers. You see it only once. Keep it secret, "
                 "like a password. If it leaks, delete it and make a new one."),
    "copy": "Copy",
    "copied_it": "I copied it",
    # the code (MOD-43)
    "code_title": "Put it in your product",
    "code_line": ("Paste the key into your product, then send a question like this one. "
                  "The answer comes back as text."),
    "code_sure": ("Each answer comes with “sure”: true or false. When it is false, show the "
                  "answer as a draft, or pass the question to a person."),
    "done": "Done",
    "send_to_developer": "Send it to your developer",
    # usage (MOD-44)
    "usage_title": "Your usage",
    "usage_line": "{name} answered {n} questions for your users this month.",
    "usage_answers": "Answers this month",
    "usage_you_pay": "You pay",
    "usage_keys": "Keys",
    "usage_pays_teachers": "Every answer you pay for also pays the {people} who taught it.",
    "usage_send_unsure": "Send the questions it wasn’t sure about to its teachers",
    "usage_send_unsure_line": ("{k} this month, with your users’ names removed. Its teachers "
                               "answer them, and it gets better at what your users ask."),
    "usage_version": ("You use version {v}. When version {next} passes the same exam, "
                      "you choose when to switch."),
    "back_to_list": "Back to the list",
    "delete_key": "Delete this key",
    # the price (MOD-46)
    "price_title": "Set your price",
    "price_intro": ("{name} passed its final exam. Set the price for one answer; "
                    "you can change it at any time."),
    "price_unit": "for one answer",
    "price_similar": ("Similar models charge {low} to {high}. The lowest is {floor}, "
                      "what an answer costs to run."),
    "price_month": "{total} a month would go here:",
    "price_infra": "Infrastructure",
    "price_infra_line": "The AI company, our servers and WillpowerLab",
    "price_founder": "You, who started it",
    "price_teachers": "The teachers, by their points",
    "price_uses": "If businesses use it {n} times a month",
    "price_use": "Use {price}",
    # earnings (MOD-47)
    "earn_title": "Your earnings",
    "earn_line": "{name} version {v} earned you {amount} this month.",
    "earn_share": "Your share of version {v}",
    "earn_answers": "Your answers that trained it",
    "earn_next": "Next payout",
    "earn_fixed": ("Your share is fixed for version {v}. It grows with each answer that counts; "
                   "hard clips count for more. Answers you give now count toward version {next}."),
    # a model's own key (MOD-48)
    "own_product": "Use {name} in your own product.",
    # downloading its data (MOD-51)
    "download_title": "Download its data",
    "download_intro": "You can download what {name} has learned from, and build your own on it.",
    "download_with_words": ("You get your teachers’ ratings and answers, and what speakers said "
                            "with names and places removed. Recordings stay with WillpowerLab."),
    "download_licence": ("You may build on it, test it and research with it for free. To sell a "
                         "product built on it, you need a licence, and its teachers share what "
                         "that earns."),
    "download_go": "Download the data",
}

#: The prototype marks these as drafted (its N(...)); they are listed in the
#: PR under "Words to sign" and are not signed yet.
DRAFTED: dict[str, str] = {
    "only_team": "Only its team can use a private model.",
    "not_yet": ("This model can’t be used in a product yet. It opens once its first training "
                "passes its final exam."),
    "people_taught": "{people} taught it.",
    "key_live": ("This is a live key: it bills you for each answer, up to your monthly limit. "
                 "You see it only once. Keep it secret, like a password. If it leaks, delete it "
                 "and make a new one."),
    "usage_test_keys": "{n} · a test key, {left} free answers left",
    "usage_live_keys": "{n} · a live key, limit {limit} a month",
    "free_used_title": "Your test key used its 100 free answers.",
    "free_used_line": ("Your product gets no more answers from it. Make a live key to go on; "
                       "it bills you for each answer, up to your monthly limit."),
    "make_live_key": "Make a live key",
    "limit_title": "You reached your monthly limit of {limit}.",
    "limit_line": "Your product gets no more answers this month. Raise the limit, or wait for next month.",
    "newer_title": "Version {v} passed the same exam.",
    "newer_line": "You use version {v}. Nothing changes until you switch.",
    "switch_to": "Switch to version {v}",
    "earn_none": ("None of your models earns yet. A model earns once its first version passes "
                  "its exam and businesses use it."),
    "earn_when_minimum": "When you have earned {minimum}",
    "earn_next_month": "At the end of this month, in tokens",
    "download_only_team": "Only its owner and its teachers can download its data.",
    "download_without_words": ("You get your teachers’ ratings and answers. What speakers said is "
                               "left out until the training yes says it may be shared. Recordings "
                               "stay with WillpowerLab."),
}

_PEOPLE = ("no one", "one person", "two people", "three people", "four people", "five people",
           "six people", "seven people", "eight people", "nine people", "ten people")


def people_words(n: int) -> str:
    n = max(0, int(n or 0))
    return _PEOPLE[n] if n < len(_PEOPLE) else f"{n:,} people"


def tokens_text(units: Optional[int]) -> str:
    """Stored units as the tokens a person sees: "3 tokens", "0.6 tokens",
    "1 token" (one decimal at most, never rounded up)."""
    from services.token_prices import display_unit
    unit = display_unit()
    n = max(0, int(units or 0))
    whole, rest = divmod(n, unit)
    tenth = (rest * 10) // unit if unit > 1 else 0
    value = f"{whole:,}" + (f".{tenth}" if tenth else "")
    return f"{value} token" + ("" if value == "1" else "s")


def running_cost(base_model: Optional[str]) -> int:
    return int(RUNNING_COST_UNITS.get(str(base_model or ""), DEFAULT_RUNNING_COST_UNITS))


# ── The split (N531 item 1, N577, N583 item 3) ──────────────────────────────
def split(price_units: int, cost_units: int, *, uses: int = 1) -> dict:
    """Where the price of ``uses`` answers goes, in stored units. The parts
    always add up to the total; "infra" is the running costs plus
    WillpowerLab's fee, the one row the price screen shows (N566 item 10)."""
    uses = max(0, int(uses))
    price, cost = max(0, int(price_units)), max(0, int(cost_units))
    total = price * uses
    costs = min(total, cost * uses)
    margin = total - costs
    fee = (margin * int(FEE_SHARE * 100)) // 100
    rest = margin - fee
    founder = (rest * int(FOUNDER_SHARE * 100)) // 100
    return {"total": total, "costs": costs, "fee": fee, "infra": costs + fee,
            "founder": founder, "teachers": rest - founder}


def clamp_price(units: Any, cost_units: int) -> int:
    """A price the founder may set: a whole step, never below the running
    cost ("−" stops at the running cost, MOD-46)."""
    try:
        n = int(units)
    except (TypeError, ValueError):
        n = 0
    n = (n // PRICE_STEP_UNITS) * PRICE_STEP_UNITS
    return max(int(cost_units), n)


def price_screen(model: dict, price_units: Optional[int], *, base_model: str = "gpt-4o-mini",
                 uses: int = 10_000) -> dict:
    """"Set your price" (MOD-46): − and +, three suggestions, the floor, and
    the split live for ``uses`` answers a month."""
    cost = running_cost(base_model)
    price = clamp_price(price_units or DEFAULT_PRICE_UNITS, cost)
    s = split(price, cost, uses=uses)
    low, high = SUGGESTED_PRICES_UNITS[0], SUGGESTED_PRICES_UNITS[-1]
    return {
        "title": WORDS["price_title"],
        "intro": WORDS["price_intro"].format(name=model.get("name")),
        "price_units": price, "price": tokens_text(price), "unit": WORDS["price_unit"],
        "floor_units": cost, "step_units": PRICE_STEP_UNITS,
        "minus_enabled": price - PRICE_STEP_UNITS >= cost,
        "suggestions": [{"units": u, "label": tokens_text(u)} for u in SUGGESTED_PRICES_UNITS],
        "similar": WORDS["price_similar"].format(low=tokens_text(low), high=tokens_text(high),
                                                 floor=tokens_text(cost)),
        "uses": uses, "uses_line": WORDS["price_uses"].format(n=f"{uses:,}"),
        "month": WORDS["price_month"].format(total=tokens_text(s["total"])),
        "split": [
            {"part": "infra", "label": WORDS["price_infra"], "line": WORDS["price_infra_line"],
             "units": s["infra"], "amount": tokens_text(s["infra"])},
            {"part": "founder", "label": WORDS["price_founder"], "units": s["founder"],
             "amount": tokens_text(s["founder"])},
            {"part": "teachers", "label": WORDS["price_teachers"], "units": s["teachers"],
             "amount": tokens_text(s["teachers"])},
        ],
        "action": WORDS["price_use"].format(price=tokens_text(price)),
    }


# ── Versions, and who may buy (N528 item 7, N566 item 9) ────────────────────
def released(versions: Iterable[dict]) -> list[dict]:
    return sorted((v for v in versions if v.get("status") == "released"),
                  key=lambda v: int(v.get("number") or 0))


def for_sale(model: dict, versions: Iterable[dict]) -> bool:
    """A model is sold only after its first training passed its final exam
    and was released, and only while it has a price (N528 item 7)."""
    return (model.get("status") not in ("archived", "draft") and bool(released(versions))
            and bool(model.get("price_units")))


def may_buy(model: dict, viewer_id: Any) -> bool:
    """Anyone signed in may buy a public model's answers (N583 item 1); only
    a private model's team may use theirs (N528 item 7)."""
    role = viewer_role(model, viewer_id)
    return role in ("owner", "contributor") or (role == "public" and model.get("visibility") == "public")


def refusal(model: dict, versions: Iterable[dict], viewer_id: Any) -> Optional[str]:
    """Why this person may not create a key, in the prototype's words, or None."""
    if not may_buy(model, viewer_id):
        return DRAFTED["only_team"]
    if not for_sale(model, versions):
        return DRAFTED["not_yet"]
    return None


# ── The card (MOD-39) ───────────────────────────────────────────────────────
def card(model: dict, version: dict, teachers: int) -> dict:
    """A ready model's card, before a business uses it. Its exam line says
    how often blind coaches rated its answers as good as a coach's, out of
    10 (the version's exam, N566 item 8)."""
    c = version.get("card") or {}
    exam = version.get("exam") or {}
    in_ten = exam.get("as_good_in_ten")
    date = str(version.get("released_at") or version.get("created_at") or "")[:10]
    rows = [
        {"label": WORDS["card_good_at"], "value": c.get("good_at") or ""},
        {"label": WORDS["card_not_so_good_at"], "value": c.get("not_so_good_at") or ""},
        {"label": WORDS["card_not_for"], "value": c.get("not_for") or ""},
    ]
    if in_ten is not None:
        rows.append({"label": WORDS["card_exam"],
                     "value": WORDS["card_exam_line"].format(k=int(in_ten))})
    rows += [
        {"label": WORDS["card_unsure"], "value": WORDS["card_unsure_line"]},
        {"label": WORDS["card_version"], "value": f"{int(version.get('number') or 1)} · passed its exam on {date}"},
    ]
    return {
        "title": model.get("name"),
        "line": f"{model.get('name')} passed its final exam. "
                + DRAFTED["people_taught"].format(people=people_words(teachers).capitalize()),
        "description": model.get("description") or "",
        "rows": rows,
        "foot": WORDS["card_foot"],
        "actions": [WORDS["use_it"], WORDS["try_it"]],
    }


# ── The terms (MOD-41) and a model's own key (MOD-48) ───────────────────────
def terms(model: dict, teachers: int, viewer_id: Any) -> dict:
    price = int(model.get("price_units") or 0)
    screen = {
        "title": WORDS["use_title"],
        "lines": [WORDS["use_inside"].format(name=model.get("name")),
                  WORDS["use_pay"].format(people=people_words(teachers)),
                  WORDS["use_may"]],
        "price_units": price,
        "price": WORDS["use_price"].format(price=tokens_text(price)),
        "price_line": WORDS["use_no_fee"],
        "test_key": {"label": WORDS["use_test_key"], "line": WORDS["use_test_key_line"],
                     "free_answers": FREE_TEST_ANSWERS},
        "limit": {"label": WORDS["use_limit"], "default_units": DEFAULT_MONTHLY_LIMIT_UNITS,
                  "options": [{"units": u, "label": tokens_text(u),
                               "line": WORDS["use_limit_line"].format(limit=tokens_text(u))}
                              for u in MONTHLY_LIMITS_UNITS]},
        "training": WORDS["use_training"],
        "actions": [WORDS["create_key"], WORDS["not_now"]],
    }
    if viewer_role(model, viewer_id) == "owner":
        screen["own_product"] = WORDS["own_product"].format(name=model.get("name"))
    return screen


# ── Keys (MOD-42) ───────────────────────────────────────────────────────────
def new_key(kind: str) -> dict:
    """A fresh key: the plaintext, shown once and never stored or logged,
    its SHA-256 hash (what the table keeps) and its last four characters."""
    if kind not in KEY_PREFIX:
        raise ValueError("kind")
    plain = KEY_PREFIX[kind] + secrets.token_urlsafe(30).replace("-", "x").replace("_", "y")
    return {"plain": plain, "hash": hash_key(plain), "tail": plain[-4:]}


def hash_key(plain: str) -> str:
    return hashlib.sha256(str(plain or "").encode("utf-8")).hexdigest()


def looks_like_key(plain: Any) -> bool:
    s = str(plain or "")
    return any(s.startswith(p) for p in KEY_PREFIX.values()) and 20 <= len(s) <= 120


def key_shown_once(model: dict, kind: str, plain: str) -> dict:
    return {
        "title": WORDS["key_title"],
        "line": WORDS["key_line"].format(name=model.get("name")),
        "key": plain,
        "note": WORDS["key_test"] if kind == "test" else DRAFTED["key_live"],
        "actions": [WORDS["copy"], WORDS["copied_it"]],
    }


def key_label(row: dict) -> str:
    """How a key appears after it was shown: its prefix and its last four."""
    return f"{KEY_PREFIX.get(str(row.get('kind') or ''), '')}…{row.get('key_tail') or ''}"


# ── The code (MOD-43) ───────────────────────────────────────────────────────
_EXAMPLE_QUESTION = "How do I answer: what is your biggest weakness?"


def code_screen(model_id: str, base_url: str) -> dict:
    """JavaScript, Python and curl, each reading the key from the
    environment (never the key itself), and "sure" in every answer."""
    url = f"{base_url.rstrip('/')}/v2/models/{model_id}/answer"
    q = _EXAMPLE_QUESTION
    return {
        "title": WORDS["code_title"],
        "line": WORDS["code_line"],
        "tabs": [
            {"lang": "js", "label": "JavaScript", "code": (
                f'const res = await fetch("{url}", {{\n  method: "POST",\n'
                '  headers: { Authorization: `Bearer ${process.env.WILLPOWERLAB_KEY}`,\n'
                '             "Content-Type": "application/json" },\n'
                f'  body: JSON.stringify({{ message: "{q}" }}),\n}});\n'
                'const { answer, sure } = await res.json();')},
            {"lang": "py", "label": "Python", "code": (
                'import os, requests\n\nres = requests.post(\n'
                f'    "{url}",\n'
                '    headers={"Authorization": f"Bearer {os.environ[\'WILLPOWERLAB_KEY\']}"},\n'
                f'    json={{"message": "{q}"}},\n)\n'
                'answer, sure = res.json()["answer"], res.json()["sure"]')},
            {"lang": "curl", "label": "curl", "code": (
                f'curl {url} \\\n  -H "Authorization: Bearer $WILLPOWERLAB_KEY" \\\n'
                '  -H "Content-Type: application/json" \\\n'
                f'  -d \'{{"message": "{q}"}}\'')},
        ],
        "sure": WORDS["code_sure"],
        "actions": [WORDS["done"], WORDS["send_to_developer"]],
    }


# ── A call: may it run, and what it costs (N566 item 9) ─────────────────────
def call_refusal(key: dict, price_units: int, spent_this_month: int) -> Optional[str]:
    """Why a key may not get one more answer: 'revoked', 'free_used' (a test
    key's 100 are used), 'limit' (one more would pass the monthly limit), or
    None. A live key stops BEFORE an answer that would pass its limit, so a
    mistake never costs more than the limit."""
    if key.get("revoked_at"):
        return "revoked"
    if key.get("kind") == "test":
        return None if int(key.get("free_left") or 0) > 0 else "free_used"
    limit = key.get("monthly_limit_units")
    if limit is not None and int(spent_this_month) + int(price_units) > int(limit):
        return "limit"
    return None


def call_row(key: dict, model: dict, version: dict, *, sure: bool, base_model: str) -> dict:
    """The usage row for one answer: free on a test key, else the price split."""
    if key.get("kind") == "test":
        return {"test": True, "sure": bool(sure), "price_units": 0, "cost_units": 0,
                "fee_units": 0, "founder_units": 0, "teachers_units": 0}
    s = split(int(model.get("price_units") or 0), running_cost(base_model))
    return {"test": False, "sure": bool(sure), "price_units": s["total"], "cost_units": s["costs"],
            "fee_units": s["fee"], "founder_units": s["founder"], "teachers_units": s["teachers"]}


# ── What the model is asked, and how sure it is (N566 item 8) ───────────────
def answer_prompt(model: dict) -> str:
    """The system prompt for one answer, from the recipe card (N563 item 2).
    The model answers in JSON with its confidence; nothing in the prompt
    names a person."""
    recipe = model.get("recipe") or {}
    steps = recipe.get("steps") or ["words"]
    lines = [f"You are {model.get('name')}, a specialised assistant taught by people who know "
             f"this field well. {model.get('description') or ''}".strip(),
             "Answer the user's message for this skill only."]
    if "rate" in steps and recipe.get("scale"):
        lines.append(f"Question: {recipe.get('question')}. Choose exactly one of: "
                     + "; ".join(str(s) for s in recipe["scale"]) + ".")
    if "pick" in steps and recipe.get("options"):
        lines.append(f"Question: {recipe.get('pick_question') or recipe.get('question')}. "
                     "Choose exactly one of: " + "; ".join(str(o) for o in recipe["options"]) + ".")
    if "words" in steps:
        lines.append("Answer in your own words, plainly, in at most five sentences.")
    lines.append('Reply as JSON: {"answer": "<your answer>", "confidence": <0 to 1, how sure '
                 'you are that a teacher of this model would agree>}. If the message is outside '
                 'what you were taught, set confidence below 0.5.')
    return "\n".join(lines)


def read_answer(model: dict, parsed: Any) -> dict:
    """The model's reply as the API returns it: {answer, sure}. Unsure when
    its confidence is below SURE_AT, when it gave no answer, or when a
    choice is not one the recipe offers."""
    if not isinstance(parsed, dict):
        return {"answer": "", "sure": False}
    answer = str(parsed.get("answer") or "").strip()[:4000]
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    recipe = model.get("recipe") or {}
    steps = recipe.get("steps") or ["words"]
    allowed = (recipe.get("scale") if "rate" in steps else None) or (
        recipe.get("options") if "pick" in steps else None)
    valid = bool(answer) and (allowed is None or "words" in steps
                              or answer.lower() in {str(a).lower() for a in allowed})
    return {"answer": answer, "sure": bool(valid and math.isfinite(confidence) and confidence >= SURE_AT)}


def try_reply(model: dict, versions: Iterable[dict], result: dict) -> dict:
    """What "Try it" shows (MOD-40, MOD-45): the answer, or the unsure line
    and its mark; the header says whether it is for sale."""
    sub = WORDS["try_ready"] if released(versions) else WORDS["try_not_for_sale"]
    if not result.get("sure"):
        return {"sub": sub, "text": WORDS["unsure_reply"], "sure": False, "mark": WORDS["unsure_mark"]}
    return {"sub": sub, "text": result.get("answer") or "", "sure": True}


# ── Usage (MOD-44) ──────────────────────────────────────────────────────────
def _usage_rows(answered: int, spent: int, live: list[dict], test: list[dict]) -> list[dict]:
    rows = [{"label": WORDS["usage_answers"], "value": f"{answered:,}"},
            {"label": WORDS["usage_you_pay"], "value": tokens_text(spent)}]
    if test:
        rows.append({"label": WORDS["usage_keys"], "value": DRAFTED["usage_test_keys"].format(
            n=len(test), left=sum(int(k.get("free_left") or 0) for k in test))})
    if live:
        rows.append({"label": WORDS["usage_keys"], "value": DRAFTED["usage_live_keys"].format(
            n=len(live), limit=tokens_text(max(int(k.get("monthly_limit_units") or 0) for k in live)))})
    return rows


def _usage_version(latest: int, pinned: int) -> dict:
    if latest > pinned:
        return {"title": DRAFTED["newer_title"].format(v=latest),
                "line": DRAFTED["newer_line"].format(v=pinned),
                "action": DRAFTED["switch_to"].format(v=latest)}
    return {"line": WORDS["usage_version"].format(v=pinned, next=pinned + 1)}


def usage_screen(model: dict, keys: list[dict], calls: list[dict], teachers: int,
                 versions: Iterable[dict]) -> dict:
    """A buyer's month with one model: answers, what they pay, their keys,
    the unsure questions, and the version their keys are pinned to."""
    answered = len(calls)
    spent = sum(int(c.get("price_units") or 0) for c in calls)
    unsure = sum(1 for c in calls if not c.get("sure"))
    rel = released(versions)
    latest = int(rel[-1]["number"]) if rel else 1
    live = [k for k in keys if k.get("kind") == "live" and not k.get("revoked_at")]
    test = [k for k in keys if k.get("kind") == "test" and not k.get("revoked_at")]
    pinned = min((int(k.get("version_number") or latest) for k in live + test), default=latest)
    alerts = []
    if test and not live and all(int(k.get("free_left") or 0) == 0 for k in test):
        alerts.append({"title": DRAFTED["free_used_title"], "line": DRAFTED["free_used_line"],
                       "action": DRAFTED["make_live_key"]})
    return {
        "title": WORDS["usage_title"],
        "line": WORDS["usage_line"].format(name=model.get("name"), n=f"{answered:,}"),
        "alerts": alerts,
        "rows": _usage_rows(answered, spent, live, test),
        "pays_teachers": WORDS["usage_pays_teachers"].format(people=people_words(teachers)),
        "send_unsure": {"label": WORDS["usage_send_unsure"],
                        "line": WORDS["usage_send_unsure_line"].format(k=unsure),
                        "on": any(k.get("allow_training") for k in live + test)},
        "keys": [{"id": str(k["id"]), "kind": k.get("kind"), "label": key_label(k),
                  "version": int(k.get("version_number") or latest)} for k in live + test],
        "version": _usage_version(latest, pinned),
        "actions": [WORDS["back_to_list"], WORDS["delete_key"]],
    }


# ── Points and shares, fixed per version (N531 item 2, N583 item 4) ─────────
def points(answers: Iterable[dict], reliability: dict[str, float]) -> dict[str, dict]:
    """Each teacher's points from the answers that counted: one point per
    answer, weighed by the teacher's reliability (0.2 to 1), and a hard clip
    (the model was between HARD_LO and HARD_HI sure of it) worth HARD_WEIGHT.
    Returns {teacher_id: {"points", "answers"}}."""
    out: dict[str, dict] = {}
    for a in answers:
        if not a.get("counted"):
            continue
        who = str(a.get("teacher_id"))
        rel = reliability.get(who)
        rel = 1.0 if rel is None else min(1.0, max(0.2, float(rel)))
        s = a.get("sureness")
        hard = s is not None and HARD_LO <= float(s) <= HARD_HI
        row = out.setdefault(who, {"points": 0.0, "answers": 0})
        row["points"] += rel * (HARD_WEIGHT if hard else 1.0)
        row["answers"] += 1
    for row in out.values():
        row["points"] = round(row["points"], 3)
    return out


def share_of(shares: list[dict], user_id: Any) -> float:
    """A teacher's share of a version: their points over the version's
    total. Someone who left is no longer a row, so their share goes to the
    others (N528 item 11)."""
    total = sum(float(s.get("points") or 0) for s in shares)
    mine = sum(float(s.get("points") or 0) for s in shares if str(s.get("user_id")) == str(user_id))
    return mine / total if total > 0 else 0.0


def divide(units: int, weights: dict[str, float]) -> dict[str, int]:
    """Split ``units`` by ``weights`` in whole units; the remainder goes, one
    unit each, to the largest fractional parts (ties by id), so the parts
    always add up."""
    units = max(0, int(units))
    total = sum(max(0.0, float(w)) for w in weights.values())
    if units == 0 or total <= 0:
        return {k: 0 for k in weights}
    exact = {k: units * max(0.0, float(w)) / total for k, w in weights.items()}
    out = {k: int(math.floor(v)) for k, v in exact.items()}
    left = units - sum(out.values())
    for k in sorted(exact, key=lambda k: (-(exact[k] - out[k]), k))[:left]:
        out[k] += 1
    return out


def month_payouts(calls: Iterable[dict], shares: list[dict], founder_id: Optional[str]) -> dict[tuple[str, str], int]:
    """What one version owes for one month, by (user_id, role): the
    founder's part to the model's founder, the teachers' part by points.
    With no founder left (an erased account), their part goes to the
    teachers; with no teachers, the teachers' part stays unassigned."""
    founder_units = sum(int(c.get("founder_units") or 0) for c in calls)
    teacher_units = sum(int(c.get("teachers_units") or 0) for c in calls)
    if not founder_id:
        teacher_units, founder_units = teacher_units + founder_units, 0
    out: dict[tuple[str, str], int] = {}
    if founder_id and founder_units:
        out[(str(founder_id), "founder")] = founder_units
    weights = {str(s["user_id"]): float(s.get("points") or 0) for s in shares}
    for uid, units in divide(teacher_units, weights).items():
        if units:
            out[(uid, "teacher")] = units
    return out


def payable(owed_units: int) -> bool:
    """Credited in tokens above the minimum (N531 item 4, N614); below it,
    it waits."""
    return int(owed_units) >= MINIMUM_PAYOUT_UNITS


# ── Earnings (MOD-47) ───────────────────────────────────────────────────────
def earnings_screen(model: Optional[dict], version_number: Optional[int], share: float,
                    answers: int, month_units: int, owed_units: int) -> dict:
    """A teacher's earnings for the version that pays them most. Shares are
    a percentage of the version (N566 item 10); money is never about how
    well someone speaks."""
    if not model or not version_number:
        return {"title": WORDS["earn_title"], "line": DRAFTED["earn_none"], "rows": [],
                "actions": [WORDS["back_to_list"]]}
    v = int(version_number)
    nxt = DRAFTED["earn_next_month"] if payable(owed_units + month_units) else \
        DRAFTED["earn_when_minimum"].format(minimum=tokens_text(MINIMUM_PAYOUT_UNITS))
    return {
        "title": WORDS["earn_title"],
        "line": WORDS["earn_line"].format(name=model.get("name"), v=v, amount=tokens_text(month_units)),
        "rows": [{"label": WORDS["earn_share"].format(v=v), "value": f"{round(share * 100)}%"},
                 {"label": WORDS["earn_answers"], "value": f"{int(answers):,}"},
                 {"label": WORDS["earn_next"], "value": nxt}],
        "fixed": WORDS["earn_fixed"].format(v=v, next=v + 1),
        "actions": [WORDS["back_to_list"]],
    }


# ── Downloading its data (MOD-51; N528 item 12) ─────────────────────────────
def download_screen(model: dict, *, speakers_words_allowed: bool = False) -> dict:
    return {
        "title": WORDS["download_title"],
        "lines": [WORDS["download_intro"].format(name=model.get("name")),
                  WORDS["download_with_words"] if speakers_words_allowed
                  else DRAFTED["download_without_words"],
                  WORDS["download_licence"]],
        "actions": [WORDS["download_go"], WORDS["not_now"]],
    }


def may_download(model: dict, viewer_id: Any, answered: bool) -> bool:
    """Its owner, its teachers who answered, and a private model's team."""
    role = viewer_role(model, viewer_id)
    if role == "owner":
        return True
    if role == "contributor":
        return answered or model.get("visibility") == "private"
    return False


def download_rows(model: dict, answers: list[dict], examples: dict[str, dict], *,
                  sees_private: bool = False) -> list[dict]:
    """The teachers' own ratings and answers, one row each, in the order
    given. Each teacher and each example is a number within this download,
    never an id or a name; an answer to an example in the sealed final exam
    never leaves (N566 item 5), and an answer to a private example (a
    company's own data, N563 item 3) leaves only for the owner and the
    teachers invited to the model (``sees_private``; N615 item 2). An answer
    whose example cannot be read is left out: it cannot be shown to be
    neither. Until the training yes carries the line that
    lets speakers' words be shared, a row holds only what the teacher gave
    and the question asked: never a speaker, a Take, the example's content
    or the machine's read (N528 item 12)."""
    recipe = model.get("recipe") or {}
    teacher_no: dict[str, int] = {}
    example_no: dict[str, int] = {}
    rows = []
    for a in answers:
        eid = str(a.get("example_id"))
        ex = examples.get(eid)
        if not ex or ex.get("in_exam"):
            continue          # the sealed exam stays sealed; unknown is left out
        if ex.get("private") and not sees_private:
            continue          # a private example never reaches someone from the door
        rows.append({
            "example": example_no.setdefault(eid, len(example_no) + 1),
            "kind": ex.get("kind"),
            "source": ex.get("source"),
            "step": a.get("step"),
            "question": recipe.get("pick_question") if a.get("step") == "pick" else recipe.get("question"),
            "answer": a.get("answer"),
            "counted": bool(a.get("counted")),
            "teacher": teacher_no.setdefault(str(a.get("teacher_id")), len(teacher_no) + 1),
        })
    return rows


# ── Names removed (N563 item 4: "from businesses that allowed it, names removed") ──
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_URL = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_WORD = re.compile(r"(?<![\w’'])([A-ZÀ-ÖØ-Þ][\w’'-]*)")
_SENTENCE_END = re.compile(r"[.!?:]\s*$|^\s*$")
_KEEP = {"I", "I’m", "I'm", "I’ve", "I've", "I’d", "I'd", "I’ll", "I'll", "OK"}
REMOVED = "[…]"


def remove_names(text: Any) -> str:
    """A business user's question with what could name someone removed,
    before any teacher sees it: e-mail addresses, links, phone numbers, and
    every capitalised word that does not start a sentence (names, places,
    companies). It removes too much rather than too little."""
    s = _EMAIL.sub(REMOVED, str(text or ""))
    s = _URL.sub(REMOVED, s)
    s = _PHONE.sub(REMOVED, s)

    def word(m: "re.Match[str]") -> str:
        if m.group(1) in _KEEP or _SENTENCE_END.search(s[:m.start()]):
            return m.group(1)
        return REMOVED
    return _WORD.sub(word, s)[:MAX_QUESTION]
