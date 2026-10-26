"""
STORY    As someone booking a session, I want to leave my WhatsApp number and
         get the confirmation of my time and a reminder 1 hour before there,
         so that I don't miss it.
OUTCOME
  O1  A number left on the booking form is kept with the booking, and the
      confirmation goes to it with the time in my own zone and the Meet link.
      A number without its country code is refused with words that say so.
  O2  The reminder goes once, about 1 hour before; a second run sends
      nothing, and a booking further away or without a number gets nothing.
  O3  The reminders' door is shut without its secret.
PROVES   O1 -> test_a_number_on_the_booking_gets_the_confirmation_in_their_own_time
         O2 -> test_the_reminder_goes_once_an_hour_before
         O3 -> test_the_reminders_door_needs_its_secret
WHY      Founder 2026-10-25, N144.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from routes.v2 import booking as booking_routes
from services import booking
from services import whatsapp_notify as wn

SETTINGS = {"id": 1, "slug": "artur", "enabled": True, "title": "1-on-1 lesson",
            "host_name": "Artur Willoński", "duration_min": 15, "price_cents": 12000,
            "currency": "usd", "horizon_days": 30, "timezone": "Europe/Warsaw",
            "new_user_discount_pct": 0, "buffer_before_min": 0, "buffer_after_min": 0,
            "notice_hours": 0, "weekly_hours": {str(d): [["00:00", "23:59"]] for d in range(7)},
            "calendar_ics_url": "", "meet_url": "https://meet.google.com/abc"}
MEET = "https://meet.google.com/abc"


@pytest.fixture()
def sent():
    """WhatsApp switched on, with each message Meta receives kept here."""
    bodies: list[dict] = []

    def _post(url, json, headers, timeout):
        bodies.append(json)
        return MagicMock(status_code=200)

    with ExitStack() as stack:
        for name, value in {"WHATSAPP_NOTIFICATIONS": True, "WHATSAPP_ACCESS_TOKEN": "tok",
                            "WHATSAPP_PHONE_NUMBER_ID": "1055", "WHATSAPP_TEMPLATE_LANGUAGE": "en",
                            "WHATSAPP_REDIRECT_TO": "",
                            "WHATSAPP_BOOKING_CONFIRMED_TEMPLATE": "booking_confirmed",
                            "WHATSAPP_BOOKING_REMINDER_TEMPLATE": "booking_reminder",
                            "SUPABASE_JWT_SECRET": "test-secret"}.items():
            stack.enter_context(patch.object(booking.config, name, value, create=True))
        stack.enter_context(patch.object(wn.httpx, "post", _post))
        stack.enter_context(patch.object(booking, "get_settings", return_value=dict(SETTINGS)))
        stack.enter_context(patch.object(booking, "user_price", return_value=None))
        yield bodies


def _params(body: dict) -> list[str]:
    return [p["text"] for p in body["template"]["components"][0]["parameters"]]


def test_a_number_on_the_booking_gets_the_confirmation_in_their_own_time(sent):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)
    checkout = dict(slug="artur", user_id="u1", start_iso=start.isoformat(), name="Ann",
                    email="a@x.co", guest_timezone="UTC", link=booking.make_price_link(0))
    with patch.object(booking, "db", MagicMock()) as db, patch.object(booking, "_confirm"):
        booking.start_checkout(**checkout, whatsapp="+48 600 100 200")
        with pytest.raises(booking.BookingError) as refused:
            booking.start_checkout(**checkout, whatsapp="600 100 200")
    kept = [c.args[0].get("guest_whatsapp") for c in db.client.table.return_value.update.call_args_list]
    assert "+48600100200" in kept
    assert refused.value.code == "WHATSAPP_INVALID" and "country code" in str(refused.value)

    booking.send_confirmation_whatsapp({
        "guest_whatsapp": "+48600100200", "guest_timezone": "Europe/Warsaw", "meet_url": MEET,
        "start_at": "2030-01-07T06:00:00+00:00", "end_at": "2030-01-07T06:15:00+00:00"})
    assert sent[-1]["to"] == "48600100200" and sent[-1]["template"]["name"] == "booking_confirmed"
    assert _params(sent[-1]) == ["Monday, January 7, 7:00 AM – 7:15 AM (Warsaw time)", MEET]


class _Bookings:
    """The bookings table, as far as the reminders read and write it."""

    def __init__(self, rows):
        self.rows, self._filters, self._values = rows, [], None

    def table(self, _name):
        self._filters, self._values = [], None
        return self

    @property
    def client(self):
        return self

    def select(self, *_):
        return self

    def update(self, values):
        self._values = values
        return self

    def eq(self, column, value):
        self._filters.append(lambda r: r.get(column) == value)
        return self

    def is_(self, column, _null):
        self._filters.append(lambda r: r.get(column) is None)
        return self

    def gt(self, column, value):
        self._filters.append(lambda r: booking._dt(r[column]) > booking._dt(value))
        return self

    def lte(self, column, value):
        self._filters.append(lambda r: booking._dt(r[column]) <= booking._dt(value))
        return self

    def execute(self):
        hit = [r for r in self.rows if all(f(r) for f in self._filters)]
        for r in hit if self._values is not None else []:
            r.update(self._values)
        return MagicMock(data=[dict(r) for r in hit])


def test_the_reminder_goes_once_an_hour_before(sent):
    now = datetime(2030, 1, 7, 5, 2, tzinfo=timezone.utc)

    def row(id_, minutes, phone="+48600100200", reminded=None):
        return {"id": id_, "status": "confirmed", "guest_whatsapp": phone,
                "guest_timezone": "Europe/Warsaw", "meet_url": MEET,
                "whatsapp_reminder_sent_at": reminded,
                "start_at": (now + timedelta(minutes=minutes)).isoformat()}

    table = _Bookings([row("due", 58), row("later", 180), row("no-number", 50, phone=None),
                       row("already", 55, reminded=now.isoformat())])
    with patch.object(booking, "db", table):
        assert booking.send_whatsapp_reminders(now) == {"due": 1, "sent": 1}
        assert booking.send_whatsapp_reminders(now + timedelta(minutes=5)) == {"due": 0, "sent": 0}
    assert len(sent) == 1 and sent[0]["template"]["name"] == "booking_reminder"
    assert _params(sent[0]) == ["7:00 AM (Warsaw time)", MEET]


def test_the_reminders_door_needs_its_secret(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(booking_routes.booking_bp)
    door = "/v2/internal/booking/whatsapp-reminders"
    monkeypatch.delenv("BOOKING_REMINDER_SECRET", raising=False)
    assert app.test_client().post(door).status_code == 503
    monkeypatch.setenv("BOOKING_REMINDER_SECRET", "s3cret")
    assert app.test_client().post(door, headers={"X-Internal-Secret": "wrong"}).status_code == 401
