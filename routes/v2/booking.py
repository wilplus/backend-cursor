"""Booking page v1 (founder 2026-10-13). Logic in services/booking.py.

Public (no login):
  GET  /v2/booking/<slug>                    the page: title, length, price
  GET  /v2/booking/<slug>/slots?from=&to=    open start times, UTC ISO
  GET  /v2/booking/confirmation?session_id=  what the success page shows

Signed in (booking needs a WillpowerLab account):
  GET  /v2/booking/<slug>/offer[?as=]        my price and tokens (admins may preview anyone)
  POST /v2/booking/<slug>/checkout           hold the slot, open Stripe at my price

Admin:
  GET  /v2/admin/booking                     settings + upcoming bookings
  PUT  /v2/admin/booking/settings            save settings
  GET/PUT /v2/admin/booking/user-price       one person's lesson price

The Stripe webhook (routes/internal_webhooks.py) confirms on
checkout.session.completed with metadata.kind == "booking".
"""
from __future__ import annotations

from datetime import timedelta, timezone

from flask import Blueprint, jsonify, request

from auth import require_auth
from routes.admin import is_admin, require_admin
from services import booking
from services.rate_limits import client_ip, limiter

booking_bp = Blueprint("booking", __name__)

MAX_RANGE_DAYS = 45


def _reply(payload, status: int = 200):
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


@booking_bp.errorhandler(booking.BookingError)
def _refused(e: booking.BookingError):
    return _reply({"code": e.code, "error": str(e)}, e.status)


@booking_bp.route("/v2/booking/<slug>", methods=["GET"])
def booking_page(slug: str):
    return _reply(booking.public_settings(slug))


@booking_bp.route("/v2/booking/<slug>/slots", methods=["GET"])
def booking_slots(slug: str):
    booking.public_settings(slug)
    try:
        start = booking._dt(request.args.get("from", ""))
        end = booking._dt(request.args.get("to", ""))
    except (TypeError, ValueError):
        return _reply({"code": "INVALID_RANGE", "error": "from and to must be ISO times"}, 400)
    if end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
        return _reply({"code": "INVALID_RANGE", "error": f"Ask for at most {MAX_RANGE_DAYS} days"}, 400)
    slots = booking.open_slots(booking.get_settings(), start.astimezone(timezone.utc),
                               end.astimezone(timezone.utc))
    return _reply({"slots": [s.isoformat().replace("+00:00", "Z") for s in slots]})


@booking_bp.route("/v2/booking/<slug>/offer", methods=["GET"])
@require_auth
def booking_offer(slug: str):
    """The signed-in person's price and tokens. An admin may pass ?as=<user_id>
    to see someone else's page as they will."""
    user_id = str(getattr(request, "user_id", ""))
    preview = (request.args.get("as") or "").strip()
    if preview and preview != user_id:
        if not is_admin(user_id):
            return _reply({"code": "FORBIDDEN", "error": "Admin access required"}, 403)
        return _reply({**booking.offer_for(slug, preview), "preview": True})
    payload = getattr(request, "token_payload", None) or {}
    meta = payload.get("user_metadata") or {}
    return _reply({**booking.offer_for(slug, user_id), "preview": False,
                   "email": payload.get("email") or "",
                   "name": meta.get("full_name") or meta.get("name") or ""})


@booking_bp.route("/v2/booking/<slug>/checkout", methods=["POST"])
@limiter.limit("30 per hour", key_func=client_ip, scope="booking_checkout")
@require_auth
def booking_checkout(slug: str):
    body = request.get_json(silent=True) or {}
    return _reply(booking.start_checkout(
        slug=slug,
        user_id=str(getattr(request, "user_id", "")),
        start_iso=str(body.get("start") or ""),
        name=str(body.get("name") or ""),
        email=str((getattr(request, "token_payload", None) or {}).get("email") or ""),
        guest_timezone=str(body.get("timezone") or "UTC"),
        note=str(body.get("note") or ""),
        embedded=body.get("embedded") is True,
        skip_payment=body.get("skip_payment") is True,
    ))


@booking_bp.route("/v2/booking/confirmation", methods=["GET"])
def booking_confirmation():
    row = booking.booking_for_guest(
        session_id=(request.args.get("session_id") or "").strip(),
        booking_id=(request.args.get("booking") or "").strip(),
    )
    if not row:
        return _reply({"code": "NOT_FOUND", "error": "No booking found"}, 404)
    return _reply(row)


@booking_bp.route("/v2/admin/booking", methods=["GET"])
@require_admin
def admin_booking():
    return _reply({"settings": booking.get_settings(), "bookings": booking.admin_bookings()})


@booking_bp.route("/v2/admin/booking/settings", methods=["PUT"])
@require_admin
def admin_booking_settings():
    return _reply({"settings": booking.save_settings(request.get_json(silent=True) or {})})


@booking_bp.route("/v2/admin/booking/user-price", methods=["GET", "PUT"])
@require_admin
def admin_booking_user_price():
    """One person's lesson price, set from /admin/tokens. PUT
    {"user_id", "price_cents"}; price_cents null goes back to the list price."""
    if request.method == "GET":
        user_id = (request.args.get("user_id") or "").strip()
        if not user_id:
            return _reply({"code": "INVALID_INPUT", "error": "user_id is required"}, 400)
        settings = booking.get_settings()
        return _reply({"user_id": user_id, "price_cents": booking.user_price(user_id),
                       "list_price_cents": settings["price_cents"], "slug": settings["slug"]})
    body = request.get_json(silent=True) or {}
    user_id = str(body.get("user_id") or "").strip()
    if not user_id:
        return _reply({"code": "INVALID_INPUT", "error": "user_id is required"}, 400)
    raw = body.get("price_cents")
    try:
        price = None if raw is None or raw == "" else int(raw)
    except (TypeError, ValueError):
        return _reply({"code": "INVALID_INPUT", "error": "price_cents must be a whole number"}, 400)
    return _reply({"user_id": user_id, "price_cents": booking.set_user_price(user_id, price)})
