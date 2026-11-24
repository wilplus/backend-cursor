"""Book a confirmed calendar slot from a Speaking Coach reply."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from services import booking, human_coach_reviews as handoff


def settings() -> dict:
    if not handoff.email_available():
        raise booking.BookingError("NOT_SET_UP", "The calendar is unavailable.", 503)
    config = booking.get_settings()
    if not config.get("enabled") or not config.get("meet_url"):
        raise booking.BookingError("NOT_SET_UP", "The calendar is unavailable.", 503)
    return config


def availability(user: str, name: str, email: str) -> dict:
    config = settings()
    now = datetime.now(timezone.utc)
    offer = booking.offer_for(config["slug"], user)
    return {
        "duration_min": config["duration_min"], "timezone": config["timezone"],
        "price_cents": offer["price_cents"], "currency": offer["currency"],
        "needs_name": not bool(name), "needs_email": not bool(email),
        "slots": [at.isoformat() for at in booking.open_slots(
            config, now, now + timedelta(days=int(config["horizon_days"])), now=now)],
    }


def _confirmed(database, user: str, at: str, key: str) -> dict | None:
    rows = (database.client.table("bookings")
            .select("id,start_at,end_at,confirmed_at,guest_timezone")
            .eq("user_id", user).eq("start_at", at).eq("status", "confirmed")
            .eq("human_coach_request_id", key).limit(1).execute().data or [])
    return rows[0] if rows else None


def _remember(database, user: str, project: str | None, row: dict) -> dict:
    at = row["confirmed_at"]
    when = booking._when(booking._dt(row["start_at"]), booking._dt(row["end_at"]),
                         row.get("guest_timezone") or "UTC")
    receipt = {
        "client_id": str(uuid5(NAMESPACE_URL, f"willpowerlab:human-coach-booking:{row['id']}")),
        "client_created_at": at,
        "role": "bot",
        "kind": "text",
        "body": f"Call booked with Artur\n{when}",
        "metadata": {
            "place": "speaking", "take_exchange": False,
            **({"arc_id": project, "project_chat": True} if project else {}),
        },
    }
    database.insert_lounge_messages(user, [receipt])
    return {"start_at": row["start_at"], "end_at": row["end_at"], "when": when, "message": receipt}


def confirm(database, user: str, body: dict, name: str, email: str) -> dict:
    project = body.get("project_id")
    if project is not None:
        handoff.require_project(database, user, project)
    at = body.get("start")
    if not isinstance(at, str) or len(at) > 50:
        raise booking.BookingError("INVALID_TIME", "That time is not valid.")
    try:
        at = booking._dt(at).astimezone(timezone.utc).isoformat()
    except ValueError as error:
        raise booking.BookingError("INVALID_TIME", "That time is not valid.") from error
    price, minutes, currency = (body.get(key) for key in ("price_cents", "duration_min", "currency"))
    if type(price) is not int or type(minutes) is not int or not isinstance(currency, str):
        raise booking.BookingError("INVALID_INPUT", "Choose a time and review the price.")
    config = settings()
    key = str(uuid5(NAMESPACE_URL, f"willpowerlab:human-coach:{user}:{project}:{at}"))
    if existing := _confirmed(database, user, at, key):
        return _remember(database, user, project, existing)

    try:
        booking.start_checkout(
            slug=config["slug"], user_id=user, start_iso=at,
            name=name or _string(body.get("name")), email=email or _string(body.get("email")),
            guest_timezone=config["timezone"], skip_payment=True,
            expected_offer=(price, minutes, currency),
            human_coach_request_id=key,
        )
    except booking.BookingError as error:
        if error.code == "SLOT_TAKEN" and (existing := _confirmed(database, user, at, key)):
            return _remember(database, user, project, existing)
        raise
    row = _confirmed(database, user, at, key)
    if not row:
        raise booking.BookingError("NOT_CONFIRMED", "We couldn’t confirm this call. Try again.", 503)
    return _remember(database, user, project, row)


def _string(value) -> str:
    return value if isinstance(value, str) else ""
