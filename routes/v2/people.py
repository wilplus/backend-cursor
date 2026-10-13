"""One person's profile and contact details (founder 2026-10-13, step 1).

Admin:
  GET    /v2/admin/people/<user_id>   the whole profile (services/admin_person.py)

The person themself:
  GET    /v2/user/whatsapp            {"phone": "+44…" | null}
  PUT    /v2/user/whatsapp            {"phone": "+44…"}  (E.164, as the app sends it)
  DELETE /v2/user/whatsapp            forget the number
  PUT    /v2/user/home-screen         they opened the app from their home screen
"""
from __future__ import annotations

import re

from flask import Blueprint, jsonify, request

from auth import require_auth
from routes.admin import require_admin
from services import admin_person

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
    return _reply({"phone": phone})


@people_bp.route("/v2/user/home-screen", methods=["PUT"])
@require_auth
def my_home_screen():
    return _reply({"home_screen_at": admin_person.mark_home_screen(_me())})
