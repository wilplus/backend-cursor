"""Booking page v1 (founder 2026-10-13). Logic in services/booking.py.

Public (no login):
  GET  /v2/booking/<slug>[?link=]            the page: title, length, price
  GET  /v2/booking/<slug>/slots?from=&to=[&link=]  open start times, UTC ISO
                                             (a link with a length: times that fit it)
  GET  /v2/booking/confirmation?session_id=  what the success page shows

Signed in (booking needs a WillpowerLab account):
  GET  /v2/booking/<slug>/offer[?as=&link=] my price (admins may preview anyone)
  POST /v2/booking/<slug>/checkout           hold the slot, open Stripe at my price

Admin:
  GET  /v2/admin/booking                     settings + upcoming bookings
  PUT  /v2/admin/booking/settings            save settings
  GET/PUT /v2/admin/booking/user-price       one person's lesson price
  GET  /v2/admin/booking/price-link?price_cents=[&duration_min=]
                                             a link that charges that price
                                             and makes it the booker's own,
                                             for a meeting of that length

Internal (cron, X-Internal-Secret: BOOKING_REMINDER_SECRET):
  POST /v2/internal/booking/whatsapp-reminders  the WhatsApp reminders due
                                             10 minutes before (N165)

The Stripe webhook (routes/internal_webhooks.py) confirms on
checkout.session.completed with metadata.kind == "booking".
"""
from __future__ import annotations

import hmac
import os
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
    return _reply(booking.public_settings(slug, request.args.get("link", "")))


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
    settings = booking.settings_for_link(booking.get_settings(), request.args.get("link", ""))
    slots = booking.open_slots(settings, start.astimezone(timezone.utc), end.astimezone(timezone.utc))
    return _reply({"slots": [s.isoformat().replace("+00:00", "Z") for s in slots]})


@booking_bp.route("/v2/booking/<slug>/offer", methods=["GET"])
@require_auth
def booking_offer(slug: str):
    """The signed-in person's price. An admin may pass ?as=<user_id>
    to see someone else's page as they will."""
    user_id = str(getattr(request, "user_id", ""))
    preview = (request.args.get("as") or "").strip()
    link = request.args.get("link", "")
    if preview and preview != user_id:
        if not is_admin(user_id):
            return _reply({"code": "FORBIDDEN", "error": "Admin access required"}, 403)
        return _reply({**booking.offer_for(slug, preview, link), "preview": True})
    payload = getattr(request, "token_payload", None) or {}
    meta = payload.get("user_metadata") or {}
    return _reply({**booking.offer_for(slug, user_id, link), "preview": False,
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
        link=str(body.get("link") or ""),
        whatsapp=str(body.get("whatsapp") or ""),
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


@booking_bp.route("/v2/admin/booking/price-link", methods=["GET"])
@require_admin
def admin_booking_price_link():
    """The booking page link for one price (founder 2026-10-18). Whoever pays
    through it gets that price as their own lesson price. `duration_min` sets
    the meeting's length for this link (founder 2026-10-25)."""
    settings = booking.get_settings()
    link = booking.make_price_link(request.args.get("price_cents"), request.args.get("duration_min"))
    base = (booking.config.FRONTEND_URL or "https://www.willpowerlab.com").rstrip("/")
    return _reply({"url": f"{base}/book/{settings['slug']}?link={link}", "link": link,
                   "price_cents": booking.price_from_link(link),
                   "duration_min": booking.duration_from_link(link), "currency": settings["currency"]})


@booking_bp.route("/v2/internal/booking/whatsapp-reminders", methods=["POST"])
def booking_whatsapp_reminders():
    """The cron's door (bin/railway-booking-reminders-cron.sh, every 5
    minutes): send the WhatsApp reminders due 10 minutes before, with the
    join link (founder 2026-10-26, N165). One shared secret; 503 while BOOKING_REMINDER_SECRET is
    not set, so the door is shut by default."""
    secret = (os.environ.get("BOOKING_REMINDER_SECRET") or "").strip()
    if not secret:
        return _reply({"code": "NOT_SET_UP", "error": "BOOKING_REMINDER_SECRET not configured"}, 503)
    given = (request.headers.get("X-Internal-Secret") or "").strip()
    if not hmac.compare_digest(given.encode(), secret.encode()):
        return _reply({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}, 401)
    return _reply(booking.send_whatsapp_reminders())
