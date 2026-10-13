"""Booking page v1 (founder 2026-10-13). Logic in services/booking.py.

Public (no login; the guest has no account):
  GET  /v2/booking/<slug>                    the page: title, length, price
  GET  /v2/booking/<slug>/slots?from=&to=    open start times, UTC ISO
  POST /v2/booking/<slug>/checkout           hold the slot, open Stripe
  GET  /v2/booking/confirmation?session_id=  what the success page shows

Admin:
  GET  /v2/admin/booking                     settings + upcoming bookings
  PUT  /v2/admin/booking/settings            save settings

The Stripe webhook (routes/internal_webhooks.py) confirms on
checkout.session.completed with metadata.kind == "booking".
"""
from __future__ import annotations

from datetime import timedelta, timezone

from flask import Blueprint, jsonify, request

from routes.admin import require_admin
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


@booking_bp.route("/v2/booking/<slug>/checkout", methods=["POST"])
@limiter.limit("30 per hour", key_func=client_ip, scope="booking_checkout")
def booking_checkout(slug: str):
    body = request.get_json(silent=True) or {}
    return _reply(booking.start_checkout(
        slug=slug,
        start_iso=str(body.get("start") or ""),
        name=str(body.get("name") or ""),
        email=str(body.get("email") or ""),
        guest_timezone=str(body.get("timezone") or "UTC"),
        note=str(body.get("note") or ""),
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
