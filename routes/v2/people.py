"""One person's profile and contact details (founder 2026-10-13, step 1).

Admin:
  GET    /v2/admin/people/<user_id>   the whole profile (services/admin_person.py)

The person themself:
  (The WhatsApp number lives in routes/v2/user_whatsapp.py, one copy in
  user_settings; the second handler that kept it in auth metadata is gone.)
  PUT    /v2/user/home-screen         they opened the app from their home screen

Asks (services/person_asks.py):
  POST   /v2/admin/people/<user_id>/asks   {"kind", "consent_key"?}  send one
  GET    /v2/user/asks/next                the person's oldest open ask, or null
  POST   /v2/user/asks/<id>                {"event": "shown" | "opened"}

Prices for one person (step 3, services/plan_promotions.py):
  PUT    /v2/admin/people/<user_id>/promotion   {"plan", "price_cents", "ends_on": "YYYY-MM-DD"}
  DELETE /v2/admin/people/<user_id>/promotion   end it now
  GET    /v2/user/offers                        {"promotion", "lesson"} for the pricing screen

Takes and acoustic data (services/admin_takes.py, admin only):
  GET    /v2/admin/people/<user_id>/takes                  every Take with its measures
  GET    /v2/admin/people/<user_id>/takes/<session_id>     one Take's pieces, every measure

Deleting an account (the person's own deletion road, seven-day window):
  POST   /v2/admin/people/<user_id>/delete              request it
  POST   /v2/admin/people/<user_id>/delete/<id>/cancel  cancel it inside the window
"""
from __future__ import annotations

from functools import partial

from flask import Blueprint, jsonify, request

from auth import require_auth
from routes.admin import require_admin
from services import admin_person, person_asks, plan_promotions

people_bp = Blueprint("people", __name__)



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


@people_bp.route("/v2/admin/people/<user_id>/delete", methods=["POST"])
@require_admin
def delete_person(user_id: str):
    from services.processing_authorization import ProcessingAuthorizationError
    if user_id == _me():
        return _reply({"code": "SELF", "error": "You cannot delete your own account here."}, 409)
    try:
        return _reply({"deletion": admin_person.request_deletion(user_id, _me())}, 202)
    except ProcessingAuthorizationError as e:
        return _reply({"code": e.code, "error": e.message}, e.status)


@people_bp.route("/v2/admin/people/<user_id>/delete/<request_id>/cancel", methods=["POST"])
@require_admin
def cancel_delete_person(user_id: str, request_id: str):
    from services.processing_authorization import ProcessingAuthorizationError
    try:
        return _reply({"deletion": admin_person.cancel_deletion(user_id, request_id)})
    except ProcessingAuthorizationError as e:
        return _reply({"code": e.code, "error": e.message}, e.status)


@people_bp.route("/v2/admin/people/<user_id>/takes", methods=["GET"])
@require_admin
def person_takes(user_id: str):
    from services import admin_takes
    return _reply(admin_takes.takes(user_id))


@people_bp.route("/v2/admin/people/<user_id>/takes/<session_id>", methods=["GET"])
@require_admin
def person_take_pieces(user_id: str, session_id: str):
    from services import admin_takes
    rows = admin_takes.pieces(user_id, session_id)
    if rows is None:
        return _reply({"code": "NOT_FOUND", "error": "No such Take for this person"}, 404)
    return _reply({"pieces": rows})
