"""A model's API and its money, in storage: it reads the tables of
migration a_business_can_buy_a_model_s_answers (and the launchpad's own,
a_person_can_teach_and_start_ai_models) into the shapes
``services/model_api.py`` takes, and writes keys, calls, versions, shares
and payouts. The rules are all there.

Ring row ``ai_models`` (ring 6): anyone else gets 404, as for the rest of
the launchpad; a key whose buyer has lost the ring stops answering.

KEYS. Only a key's SHA-256 hash and its last four characters are stored.
The key itself is returned once, by ``create_key``, and is never logged:
nothing in this module passes it to a logger, and a lookup is by hash.

PROVIDER CALLS. ``try_it`` and ``answer_with_key`` call the model through
``services.llm.chat_complete``, which issues a permit for every call inside
the caller's authority: the route binds it (``phase1_provider_route`` for
"Try it", ``user_provider_scope`` for the buyer of a key). Nothing here
calls a provider outside that scope.

MONEY. A live key's answer is charged to its buyer in tokens at the model's
price (``token_account.charge_model_answer``), through the same atomic
charge as every other; an answer is given only when the whole price was
charged. Test keys never bill. Payouts are a founder's step
(``pay_month``), never a schedule; they credit tokens (N583 item 4).

  * ``card_for``        the card of a model for sale (MOD-39)
  * ``try_it``          "Try it", in text (MOD-40, MOD-45)
  * ``price_for``, ``set_price``   "Set your price" (MOD-46)
  * ``terms_for``       "Use it in your business" (MOD-41, MOD-48)
  * ``create_key``      a key, shown once (MOD-42)
  * ``code_for``        the code (MOD-43)
  * ``usage_for``, ``delete_key``, ``switch_key``, ``send_unsure``  usage (MOD-44)
  * ``key_for``, ``answer_with_key``   the API itself (MOD-43, MOD-44)
  * ``earnings_for``    a teacher's earnings (MOD-47)
  * ``record_version``, ``release``, ``pay_month``  the founder's steps (MOD-52)
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from services import model_api as rules
from services import model_launchpad as launchpad
from services import model_launchpad_store as models
from services.chats import ChatsError, _not_found, _rows, _table, _uuid

logger = logging.getLogger(__name__)

VERSIONS, SHARES, KEYS, CALLS, PAYOUTS = (
    "ai_model_versions", "ai_model_shares", "ai_model_api_keys", "ai_model_calls", "ai_model_payouts")
_VERSION_FIELDS = "id,model_id,number,status,base_model,provider_model,founder_id,card,exam,created_at,released_at"
_KEY_FIELDS = ("id,model_id,buyer_id,version_id,key_tail,kind,free_left,monthly_limit_units,"
               "allow_training,created_at,revoked_at")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_start(now: Optional[datetime] = None) -> str:
    return (now or _now()).strftime("%Y-%m-01")


def _in_month(row: dict, month: str) -> bool:
    return str(row.get("created_at") or "")[:7] == month[:7]


def _model(database: Any, me: str, model_id: Any) -> dict:
    """The model, with its price, if the caller may see it; else 404."""
    model = models._model(database, model_id)
    if launchpad.viewer_role(model, me) is None:
        raise _not_found()
    price = _rows(_table(database, models.MODELS).select("price_units").eq("id", model["id"]).limit(1))
    model["price_units"] = (price[0].get("price_units") if price else None)
    return model


def _versions(database: Any, model_id: str) -> list[dict]:
    rows = _rows(_table(database, VERSIONS).select(_VERSION_FIELDS).eq("model_id", model_id))
    return sorted(rows, key=lambda v: int(v.get("number") or 0))


def _latest_released(versions: list[dict]) -> Optional[dict]:
    rel = rules.released(versions)
    return rel[-1] if rel else None


def _owner_only(model: dict, me: str) -> None:
    if launchpad.viewer_role(model, me) != "owner":
        raise _not_found()


# ── The card and trying it ──────────────────────────────────────────────────
def card_for(database: Any, user_id: Any, model_id: Any) -> dict:
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    version = _latest_released(_versions(database, model["id"]))
    if version is None:
        raise _not_found()
    screen = rules.card(model, version, int(model.get("teachers") or 0))
    screen["for_sale"] = rules.for_sale(model, [version])
    return screen


def _ask(model: dict, version: Optional[dict], message: str) -> Optional[dict]:
    """One answer from the model, under the caller's provider scope (the
    route binds it). The version's own trained model when it has one, else
    its base model. Returns {answer, sure}, or None when the provider gave
    nothing."""
    from dataclasses import replace

    from services import llm
    from services.llm_config import SPEC_MODEL_API_ANSWER
    base = ((version or {}).get("provider_model") or (version or {}).get("base_model")
            or SPEC_MODEL_API_ANSWER.model)
    spec = replace(SPEC_MODEL_API_ANSWER, model=str(base))
    result = llm.chat_complete(spec=spec, system=rules.answer_prompt(model), user=message,
                               surface="model_api_answer")
    if result is None:
        return None
    return rules.read_answer(model, result.parsed)


def _clean_message(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        raise ChatsError("EMPTY_MESSAGE", "Write a message.", 400)
    return text[:rules.MAX_QUESTION]


def _queue_unsure(database: Any, model: dict, text: str, *, added_by: Optional[str]) -> None:
    """An unsure question goes to the model's teachers, names removed, as an
    example of this model alone (private: it never counts for another)."""
    try:
        _table(database, models.EXAMPLES).insert({
            "model_id": model["id"], "source": "business", "private": True,
            "added_by": added_by, "kind": "question",
            "content": {"text": rules.remove_names(text)}, "sureness": 0.0,
        }).execute()
    except Exception:
        logger.warning("model_api: an unsure question could not be queued model=%s",
                       model.get("id"), exc_info=True)


def try_it(database: Any, user_id: Any, model_id: Any, message: Any) -> dict:
    """"Try it" (MOD-40, MOD-45): anyone who may see a model that is
    learning or ready may talk to it, for free. When it is not sure it says
    so, and the question goes to its teachers."""
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    if model.get("status") not in ("learning", "ready"):
        raise _not_found()
    text = _clean_message(message)
    versions = _versions(database, model["id"])
    result = _ask(model, _latest_released(versions), text)
    if result is None:
        raise ChatsError("MODEL_UNAVAILABLE", "The model could not answer just now.", 503)
    reply = rules.try_reply(model, versions, result)
    if not reply["sure"]:
        _queue_unsure(database, model, text, added_by=me)
    return reply


# ── The price (MOD-46) ──────────────────────────────────────────────────────
def _base_model(versions: list[dict]) -> str:
    latest = _latest_released(versions) or (versions[-1] if versions else None)
    return str((latest or {}).get("base_model") or "gpt-4o-mini")


def price_for(database: Any, user_id: Any, model_id: Any, *, uses: int = 10_000,
              units: Optional[int] = None) -> dict:
    """"Set your price" for the owner. With ``units`` it previews a proposed
    price (each − and +) and its split without saving it; only "Use {price}"
    saves (``set_price``). ``saved_units`` is the price buyers pay now."""
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    _owner_only(model, me)
    uses = min(100_000, max(1_000, int(uses or 10_000)))
    saved = model.get("price_units")
    screen = rules.price_screen(model, units if units is not None else saved,
                                base_model=_base_model(_versions(database, model["id"])), uses=uses)
    screen["saved_units"] = saved
    return screen


def set_price(database: Any, user_id: Any, model_id: Any, units: Any) -> dict:
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    _owner_only(model, me)
    cost = rules.running_cost(_base_model(_versions(database, model["id"])))
    try:
        wanted = int(units)
    except (TypeError, ValueError):
        raise ChatsError("BAD_PRICE", "A price is a whole number of units.", 400)
    if wanted < cost:
        raise ChatsError("PRICE_BELOW_COST", "The price cannot be below what an answer costs to run.", 422)
    price = rules.clamp_price(wanted, cost)
    _table(database, models.MODELS).update({"price_units": price, "price_set_at": _now().isoformat()}) \
        .eq("id", model["id"]).execute()
    model["price_units"] = price
    return rules.price_screen(model, price, base_model=_base_model(_versions(database, model["id"])))


# ── The terms, keys and code (MOD-41 to MOD-43, MOD-48) ─────────────────────
def terms_for(database: Any, user_id: Any, model_id: Any) -> dict:
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    refused = rules.refusal(model, _versions(database, model["id"]), me)
    if refused:
        return {"title": rules.WORDS["use_title"], "refused": refused,
                "actions": [rules.WORDS["back_to_list"]]}
    return rules.terms(model, int(model.get("teachers") or 0), me)


def create_key(database: Any, user_id: Any, model_id: Any, *, kind: str = "test",
               monthly_limit_units: Any = None, allow_training: bool = False) -> dict:
    """A key, pinned to the latest released version. The first key a buyer
    makes for a model is a test key, free for 100 answers; there is one
    test key per buyer and model, ever. A live key always has a monthly
    limit. The key is in the answer once, and never stored or logged."""
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    versions = _versions(database, model["id"])
    refused = rules.refusal(model, versions, me)
    if refused:
        raise ChatsError("NOT_FOR_SALE", refused, 409)
    if kind not in ("test", "live"):
        raise ChatsError("BAD_KIND", "A key is a test key or a live key.", 400)
    mine = _rows(_table(database, KEYS).select("id,kind").eq("model_id", model["id"]).eq("buyer_id", me))
    if kind == "test" and any(k.get("kind") == "test" for k in mine):
        raise ChatsError("TEST_KEY_USED", "You already have a test key for this model.", 409)
    limit = None
    if kind == "live":
        try:
            limit = int(monthly_limit_units or rules.DEFAULT_MONTHLY_LIMIT_UNITS)
        except (TypeError, ValueError):
            raise ChatsError("BAD_LIMIT", "A monthly limit is a whole number of units.", 400)
        if limit <= 0:
            raise ChatsError("BAD_LIMIT", "A monthly limit is above zero.", 400)
    version = _latest_released(versions)
    if version is None:
        raise ChatsError("NOT_FOR_SALE", rules.DRAFTED["not_yet"], 409)
    made = rules.new_key(kind)
    row = _rows(_table(database, KEYS).insert({
        "model_id": model["id"], "buyer_id": me, "version_id": version["id"],
        "key_hash": made["hash"], "key_tail": made["tail"], "kind": kind,
        "free_left": rules.FREE_TEST_ANSWERS if kind == "test" else 0,
        "monthly_limit_units": limit, "allow_training": bool(allow_training),
    }))
    screen = rules.key_shown_once(model, kind, made["plain"])
    screen["id"] = str(row[0]["id"]) if row else None
    return screen


def code_for(database: Any, user_id: Any, model_id: Any, base_url: str) -> dict:
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    return rules.code_screen(model["id"], base_url)


def _my_key(database: Any, me: str, key_id: Any) -> dict:
    kid = _uuid(key_id)
    rows = _rows(_table(database, KEYS).select(_KEY_FIELDS).eq("id", kid).limit(1)) if kid else []
    if not rows or str(rows[0]["buyer_id"]) != me:
        raise _not_found()
    return rows[0]


def delete_key(database: Any, user_id: Any, key_id: Any) -> dict:
    me = models._require(database, user_id)
    key = _my_key(database, me, key_id)
    if not key.get("revoked_at"):
        _table(database, KEYS).update({"revoked_at": _now().isoformat()}).eq("id", key["id"]).execute()
    return {"deleted": True}


def switch_key(database: Any, user_id: Any, key_id: Any) -> dict:
    """The buyer chooses when to move to a newer version (N566 item 9)."""
    me = models._require(database, user_id)
    key = _my_key(database, me, key_id)
    latest = _latest_released(_versions(database, str(key["model_id"])))
    if latest is None:
        raise _not_found()
    _table(database, KEYS).update({"version_id": latest["id"]}).eq("id", key["id"]).execute()
    return {"version": int(latest["number"])}


def send_unsure(database: Any, user_id: Any, key_id: Any, on: bool) -> dict:
    """"Send the questions it wasn't sure about to its teachers": the
    business's yes, from now on (N566 item 9: never without it)."""
    me = models._require(database, user_id)
    key = _my_key(database, me, key_id)
    _table(database, KEYS).update({"allow_training": bool(on)}).eq("id", key["id"]).execute()
    return {"on": bool(on)}


def usage_for(database: Any, user_id: Any, model_id: Any) -> dict:
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    versions = _versions(database, model["id"])
    number = {str(v["id"]): int(v["number"]) for v in versions}
    keys = _rows(_table(database, KEYS).select(_KEY_FIELDS).eq("model_id", model["id"]).eq("buyer_id", me))
    for k in keys:
        k["version_number"] = number.get(str(k.get("version_id")))
    month = _month_start()
    calls = [c for c in _rows(_table(database, CALLS).select("price_units,sure,created_at")
                              .eq("model_id", model["id"]).eq("buyer_id", me)) if _in_month(c, month)]
    return rules.usage_screen(model, keys, calls, int(model.get("teachers") or 0), versions)


# ── The API itself ──────────────────────────────────────────────────────────
class KeyRefused(ChatsError):
    """A refusal on the API, with the plain code a developer reads."""


def key_for(database: Any, plain: Any) -> Optional[dict]:
    """The live row for a presented key, found by its hash, or None."""
    if not rules.looks_like_key(plain):
        return None
    rows = _rows(_table(database, KEYS).select(_KEY_FIELDS).eq("key_hash", rules.hash_key(str(plain))).limit(1))
    return rows[0] if rows and not rows[0].get("revoked_at") else None


def _take_a_free_answer(database: Any, key: dict) -> bool:
    """A test key spends one of its free answers: compare-and-set, so two
    calls at once cannot both spend the last one."""
    for _ in range(3):
        rows = _rows(_table(database, KEYS).select("free_left").eq("id", key["id"]).limit(1))
        left = int((rows[0] if rows else {}).get("free_left") or 0)
        if left <= 0:
            return False
        done = _rows(_table(database, KEYS).update({"free_left": left - 1})
                     .eq("id", key["id"]).eq("free_left", left))
        if done:
            return True
    return False


def _give_back_a_free_answer(database: Any, key: dict) -> None:
    try:
        rows = _rows(_table(database, KEYS).select("free_left").eq("id", key["id"]).limit(1))
        left = int((rows[0] if rows else {}).get("free_left") or 0)
        _table(database, KEYS).update({"free_left": min(rules.FREE_TEST_ANSWERS, left + 1)}) \
            .eq("id", key["id"]).eq("free_left", left).execute()
    except Exception:
        logger.warning("model_api: a free answer could not be given back key=%s", key.get("id"),
                       exc_info=True)


def answer_with_key(database: Any, key: dict, model_id: Any, message: Any) -> dict:
    """One answer through the API: {answer, sure, version}. The key must be
    this model's; its buyer must still have the ring and may buy it; a test
    key spends a free answer; a live key stops before its monthly limit and
    is charged the whole price before the answer is returned."""
    buyer = str(key["buyer_id"])
    if _uuid(model_id) != str(key["model_id"]):
        raise KeyRefused("INVALID_KEY", "This key is not for this model.", 401)
    if not models.enabled(database, buyer):
        raise KeyRefused("MODEL_API_CLOSED", "This model's API is not open to this key.", 403)
    model = models._model(database, key["model_id"])
    price_rows = _rows(_table(database, models.MODELS).select("price_units").eq("id", model["id"]).limit(1))
    model["price_units"] = price_rows[0].get("price_units") if price_rows else None
    versions = _versions(database, model["id"])
    if rules.refusal(model, versions, buyer):
        raise KeyRefused("NOT_FOR_SALE", "This model is not for sale.", 403)
    version = next((v for v in versions if str(v["id"]) == str(key["version_id"])), None)
    if version is None or version.get("status") == "retired":
        raise KeyRefused("VERSION_RETIRED", "This key's version is retired. Switch to the newest.", 410)
    text = _clean_message(message)
    price = int(model.get("price_units") or 0)
    if key.get("kind") == "live":
        from services import token_account
        if not token_account.enabled():
            raise KeyRefused("BILLING_OFF", "Live keys are not billing yet. Use a test key.", 503)
        month = _month_start()
        spent = sum(int(c.get("price_units") or 0) for c in _rows(
            _table(database, CALLS).select("price_units,created_at").eq("key_id", key["id"]))
            if _in_month(c, month))
        why = rules.call_refusal(key, price, spent)
        if why:
            raise KeyRefused("MONTHLY_LIMIT", "This key reached its monthly limit.", 429)
    elif not _take_a_free_answer(database, key):
        raise KeyRefused("FREE_ANSWERS_USED", "This test key used its 100 free answers.", 402)

    result = _ask(model, version, text)
    if result is None:
        if key.get("kind") == "test":
            _give_back_a_free_answer(database, key)
        raise KeyRefused("MODEL_UNAVAILABLE", "The model could not answer just now.", 503)

    call_id = str(uuid.uuid4())
    row = rules.call_row(key, model, version, sure=result["sure"], base_model=_base_model([version]))
    if not row["test"]:
        from services import token_account
        charged = token_account.charge_model_answer(buyer, row["price_units"], ref_id=call_id)
        if charged.charged != row["price_units"]:
            raise KeyRefused("NOT_ENOUGH_TOKENS", "Not enough tokens. Top up to go on.", 402)
    _table(database, CALLS).insert({"id": call_id, "key_id": key["id"], "buyer_id": buyer,
                                    "model_id": model["id"], "version_id": version["id"], **row}).execute()
    _table(database, KEYS).update({"last_used_at": _now().isoformat()}).eq("id", key["id"]).execute()
    if not result["sure"] and key.get("allow_training"):
        _queue_unsure(database, model, text, added_by=None)
    return {"answer": result["answer"], "sure": bool(result["sure"]), "version": int(version["number"])}


# ── Earnings (MOD-47) ───────────────────────────────────────────────────────
def earnings_for(database: Any, user_id: Any) -> dict:
    """The caller's earnings, for the version whose share of theirs is
    largest: their share, the answers that trained it, this month, and
    when it is paid."""
    me = models._require(database, user_id)
    mine = _rows(_table(database, SHARES).select("version_id,user_id,points,answers").eq("user_id", me))
    best: Optional[tuple[float, dict, dict]] = None
    for s in mine:
        v = _rows(_table(database, VERSIONS).select(_VERSION_FIELDS).eq("id", s["version_id"]).limit(1))
        if not v or v[0].get("status") not in ("released", "retired"):
            continue
        everyone = _rows(_table(database, SHARES).select("user_id,points").eq("version_id", s["version_id"]))
        share = rules.share_of(everyone, me)
        if best is None or share > best[0]:
            best = (share, v[0], s)
    if best is None:
        return rules.earnings_screen(None, None, 0.0, 0, 0, 0)
    share, version, row = best
    model = models._model(database, version["model_id"])
    month = _month_start()
    calls = [c for c in _rows(_table(database, CALLS).select("founder_units,teachers_units,created_at")
                              .eq("version_id", version["id"])) if _in_month(c, month)]
    everyone = _rows(_table(database, SHARES).select("user_id,points").eq("version_id", version["id"]))
    owed_now = rules.month_payouts(calls, everyone, version.get("founder_id"))
    month_units = sum(u for (uid, _role), u in owed_now.items() if uid == me)
    owed = sum(int(p.get("units") or 0) for p in _rows(
        _table(database, PAYOUTS).select("units,status").eq("user_id", me).eq("status", "owed")))
    return rules.earnings_screen(model, int(version["number"]), share, int(row.get("answers") or 0),
                                 month_units, owed)


# ── The founder's steps (MOD-52, N563 item 5) ───────────────────────────────
def record_version(database: Any, model_id: Any, *, provider_model: Optional[str],
                   card: dict, exam: dict, base_model: str = "gpt-4o-mini") -> dict:
    """A version that passed its final exam: its number, the provider's
    model it runs on, its card and exam, the model's founder now, and the
    teachers' shares FIXED from the answers that counted so far (N531 item
    2: a version pays the people whose answers trained it). WillpowerLab's
    founder records it after the training run; the model's founder releases
    it (``release``)."""
    model = models._model(database, model_id)
    versions = _versions(database, model["id"])
    number = (int(versions[-1]["number"]) + 1) if versions else 1
    made = _rows(_table(database, VERSIONS).insert({
        "model_id": model["id"], "number": number, "status": "passed", "base_model": base_model,
        "provider_model": provider_model, "founder_id": model.get("owner_id"),
        "card": {k: str(card.get(k) or "")[:300] for k in ("good_at", "not_so_good_at", "not_for")},
        "exam": dict(exam or {}),
    }))
    version = made[0]
    answers = _rows(_table(database, models.ANSWERS).select("example_id,teacher_id,counted")
                    .eq("model_id", model["id"]).eq("counted", True))
    ids = sorted({str(a["example_id"]) for a in answers})
    sureness = {str(e["id"]): e.get("sureness") for e in (
        _rows(_table(database, models.EXAMPLES).select("id,sureness").in_("id", ids)) if ids else [])}
    for a in answers:
        a["sureness"] = sureness.get(str(a["example_id"]))
    team = _rows(_table(database, models.TEACHERS).select("user_id,trust_kappa").eq("model_id", model["id"]))
    reliability = {str(t["user_id"]): float(t["trust_kappa"]) for t in team if t.get("trust_kappa") is not None}
    pts = rules.points(answers, reliability)
    if pts:
        _table(database, SHARES).insert([
            {"version_id": version["id"], "user_id": uid, "points": p["points"], "answers": p["answers"]}
            for uid, p in sorted(pts.items())]).execute()
    return {"id": str(version["id"]), "number": number, "teachers": len(pts)}


def release(database: Any, user_id: Any, model_id: Any, number: Any) -> dict:
    """The model's founder releases a version that passed (N563 item 5).
    Its keys stay on the version they were made on until each buyer
    switches."""
    me = models._require(database, user_id)
    model = _model(database, me, model_id)
    _owner_only(model, me)
    v = next((v for v in _versions(database, model["id"]) if str(v["number"]) == str(number)), None)
    if v is None or v.get("status") != "passed":
        raise _not_found()
    _table(database, VERSIONS).update({"status": "released", "released_at": _now().isoformat()}) \
        .eq("id", v["id"]).execute()
    _table(database, models.MODELS).update({"status": "ready"}).eq("id", model["id"]).execute()
    return {"released": int(v["number"])}


def pay_month(database: Any, month: str, *, pay: bool = False) -> dict:
    """The month's payouts, for every version that sold: written once per
    (version, person, role, month) as owed. With ``pay``, everyone whose
    owed total reaches the minimum is paid in tokens, each payout row its
    own idempotent grant. Run by WillpowerLab's founder; never scheduled."""
    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])(-01)?", str(month or "")):
        raise ChatsError("BAD_MONTH", "A month is YYYY-MM.", 400)
    month = str(month)[:7] + "-01"
    calls = [c for c in _rows(_table(database, CALLS)
                              .select("version_id,founder_units,teachers_units,test,created_at"))
             if _in_month(c, month) and not c.get("test")]
    by_version: dict[str, list[dict]] = defaultdict(list)
    for c in calls:
        by_version[str(c["version_id"])].append(c)
    written = 0
    for vid, vcalls in sorted(by_version.items()):
        v = _rows(_table(database, VERSIONS).select("id,founder_id").eq("id", vid).limit(1))
        shares = _rows(_table(database, SHARES).select("user_id,points").eq("version_id", vid))
        have = {(str(p["user_id"]), p["role"]) for p in _rows(
            _table(database, PAYOUTS).select("user_id,role").eq("version_id", vid).eq("month", month))}
        for (uid, role), units in sorted(rules.month_payouts(
                vcalls, shares, (v[0] if v else {}).get("founder_id")).items()):
            if (uid, role) in have:
                continue
            _table(database, PAYOUTS).insert({"version_id": vid, "user_id": uid, "role": role,
                                              "month": month, "units": units,
                                              "status": "owed"}).execute()
            written += 1
    paid = 0
    if pay:
        from services import token_account
        owed = _rows(_table(database, PAYOUTS).select("id,user_id,units,status").eq("status", "owed"))
        per: dict[str, list[dict]] = defaultdict(list)
        for p in owed:
            per[str(p["user_id"])].append(p)
        for uid, rows in sorted(per.items()):
            if not rules.payable(sum(int(p.get("units") or 0) for p in rows)):
                continue
            for p in rows:
                done = token_account.model_earnings_grant(uid, int(p["units"]), ref_id=str(p["id"]))
                if done.get("ok"):
                    _table(database, PAYOUTS).update({"status": "paid", "paid_at": _now().isoformat()}) \
                        .eq("id", p["id"]).execute()
                    paid += 1
    return {"month": month, "written": written, "paid": paid}
