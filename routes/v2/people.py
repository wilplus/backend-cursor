"""One person's profile and contact details (founder 2026-10-13, step 1).

Admin:
  GET    /v2/admin/people/<user_id>   the whole profile (services/admin_person.py)

The person themself:
  GET    /v2/user/whatsapp            {"phone": "+44…" | null}
  PUT    /v2/user/whatsapp            {"phone": "+44…"}  (E.164, as the app sends it)
  DELETE /v2/user/whatsapp            forget the number
  PUT    /v2/user/home-screen         they opened the app from their home screen

Asks (services/person_asks.py):
  POST   /v2/admin/people/<user_id>/asks   {"kind", "consent_key"?}  send one
  GET    /v2/user/asks/next                the person's oldest open ask, or null
  POST   /v2/user/asks/<id>                {"event": "shown" | "opened"}

Prices for one person (step 3, services/plan_promotions.py):
  PUT    /v2/admin/people/<user_id>/promotion   {"plan", "price_cents", "ends_on": "YYYY-MM-DD"}
  DELETE /v2/admin/people/<user_id>/promotion   end it now
  GET    /v2/user/offers                        {"promotion", "lesson"} for the pricing screen
"""
from __future__ import annotations

import re
from functools import partial

from flask import Blueprint, jsonify, request

from auth import require_auth
from routes.admin import require_admin
from services import admin_person, person_asks, plan_promotions

people_bp = Blueprint("people", __name__)

PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _reply(payload, status: int = 200):
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


def _me() -> str:
    return str(getattr(request, "user_id", ""))


@people_bp.route("/v2/admin/people/<user_id>", methods=["GET"])
@require_admin
def get_person(user_id: str):
    profile = admin_person.person(user_id)
    if not profile:
        return _reply({"code": "NOT_FOUND", "error": "No account with this id"}, 404)
    return _reply(profile)


@people_bp.route("/v2/user/whatsapp", methods=["GET", "PUT", "DELETE"])
@require_auth
def my_whatsapp():
    if request.method == "GET":
        meta = (admin_person.auth_user(_me()) or {}).get("user_metadata") or {}
        return _reply({"phone": meta.get("whatsapp_phone") or None})
    if request.method == "DELETE":
        admin_person.set_metadata(_me(), {"whatsapp_phone": None})
        return _reply({"phone": None})
    phone = re.sub(r"[\s\-().]", "", str((request.get_json(silent=True) or {}).get("phone") or ""))
    if not PHONE_RE.match(phone):
        return _reply({"code": "INVALID_PHONE",
                       "error": "Enter the number with its country code, for example +44 7700 900123."}, 400)
    admin_person.set_metadata(_me(), {"whatsapp_phone": phone})
    # Never let the ask bookkeeping block saving the number itself.
    admin_person._safe("whatsapp ask", partial(person_asks.answered, _me(), "whatsapp"))
    return _reply({"phone": phone})


@people_bp.route("/v2/user/home-screen", methods=["PUT"])
@require_auth
def my_home_screen():
    return _reply({"home_screen_at": admin_person.mark_home_screen(_me())})


@people_bp.errorhandler(person_asks.AskError)
def _ask_refused(e: person_asks.AskError):
    return _reply({"code": e.code, "error": str(e)}, e.status)


@people_bp.route("/v2/admin/people/<user_id>/asks", methods=["POST"])
@require_admin
def send_ask(user_id: str):
    body = request.get_json(silent=True) or {}
    profile = admin_person.person(user_id)
    if not profile:
        return _reply({"code": "NOT_FOUND", "error": "No account with this id"}, 404)
    ask = person_asks.create(user_id, str(body.get("kind") or ""), body.get("consent_key"),
                             admin_id=_me(), consents=profile["consents"])
    return _reply({"ask": ask}, 201)


@people_bp.route("/v2/user/asks/next", methods=["GET"])
@require_auth
def my_next_ask():
    return _reply({"ask": person_asks.next_for(_me())})


@people_bp.route("/v2/user/asks/<ask_id>", methods=["POST"])
@require_auth
def mark_my_ask(ask_id: str):
    person_asks.mark(_me(), ask_id, str((request.get_json(silent=True) or {}).get("event") or ""))
    return _reply({"ok": True})


@people_bp.errorhandler(plan_promotions.PromotionError)
def _promotion_refused(e: plan_promotions.PromotionError):
    return _reply({"code": e.code, "error": str(e)}, e.status)


@people_bp.route("/v2/admin/people/<user_id>/promotion", methods=["PUT", "DELETE"])
@require_admin
def person_promotion(user_id: str):
    if request.method == "DELETE":
        plan_promotions.end(user_id)
        return _reply({"promotion": None})
    body = request.get_json(silent=True) or {}
    try:
        price = int(str(body.get("price_cents") or ""))
    except (TypeError, ValueError):
        return _reply({"code": "INVALID_PRICE", "error": "Enter their price."}, 400)
    return _reply({"promotion": plan_promotions.save(
        user_id, plan=str(body.get("plan") or ""), price_cents=price,
        ends_on=str(body.get("ends_on") or ""), admin_id=_me())})


@people_bp.route("/v2/user/offers", methods=["GET"])
@require_auth
def my_offers():
    """What the pricing screen shows for me: my plan promotion, if any, and
    my 1-on-1 lesson card."""
    return _reply({
        "promotion": admin_person._safe("promotion", partial(plan_promotions.active, _me())),
        "lesson": admin_person._safe("lesson", partial(person_asks.lesson_offer, _me())),
    })
