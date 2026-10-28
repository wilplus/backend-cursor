"""
STORY    As someone booking a session, I want the join link on WhatsApp 10
         minutes before, at the number my account holds, so that I don't
         miss it.
OUTCOME
  O1  The reminder goes once, about 10 minutes before, with the Meet link; a
      second run sends nothing, and a booking further away or without a
      number gets nothing.
  O2  A booking that carries no number reminds the number saved on the
      account, once the switch is on; with it off, nothing goes there.
  O3  A booking forgets the number it carries once its reminder has gone,
      and any booking more than an hour past its start forgets it too.
PROVES   O1 -> test_the_reminder_goes_once_10_minutes_before
         O2 -> test_the_reminder_goes_to_the_accounts_number
         O3 -> test_a_booking_forgets_its_number_after_the_reminder
WHY      Founder 2026-10-25, N144; 10 minutes before, N165; the WhatsApp
         confirmation gone, N189; the words, N200; the account's number and
         no number on the booking form, N207; the number forgotten, N233.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

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
                            "WHATSAPP_BOOKING_REMINDER_TEMPLATE": "booking_reminder",
                            "SUPABASE_JWT_SECRET": "test-secret"}.items():
            stack.enter_context(patch.object(booking.config, name, value, create=True))
        stack.enter_context(patch.object(wn.httpx, "post", _post))
        stack.enter_context(patch.object(booking, "get_settings", return_value=dict(SETTINGS)))
        stack.enter_context(patch.object(booking, "user_price", return_value=None))
        yield bodies


def _params(body: dict) -> list[str]:
    return [p["text"] for p in body["template"]["components"][0]["parameters"]]


class _Bookings:
    """The bookings table and the accounts' numbers (user_settings), as far
    as the reminders read and write them."""

    def __init__(self, rows, settings=()):
        self.tables = {"bookings": rows, "user_settings": list(settings)}
        self.rows, self._filters, self._values, self._not = rows, [], None, False

    def table(self, name):
        self.rows, self._filters, self._values, self._not = self.tables[name], [], None, False
        return self

    @property
    def not_(self):
        self._not = True
        return self

    def limit(self, _n):
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
        negate, self._not = self._not, False
        self._filters.append(lambda r: (r.get(column) is None) != negate)
        return self

    def lt(self, column, value):
        self._filters.append(lambda r: booking._dt(r[column]) < booking._dt(value))
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


def test_the_reminder_goes_once_10_minutes_before(sent):
    now = datetime(2030, 1, 7, 5, 2, tzinfo=timezone.utc)

    def row(id_, minutes, phone="+48600100200", reminded=None):
        return {"id": id_, "status": "confirmed", "guest_whatsapp": phone,
                "guest_timezone": "Europe/Warsaw", "meet_url": MEET,
                "whatsapp_reminder_sent_at": reminded,
                "start_at": (now + timedelta(minutes=minutes)).isoformat()}

    table = _Bookings([row("due", 8), row("later", 60), row("no-number", 6, phone=None),
                       row("already", 9, reminded=now.isoformat())])
    with patch.object(booking, "db", table):
        assert booking.send_whatsapp_reminders(now) == {"due": 1, "sent": 1}
        assert booking.send_whatsapp_reminders(now + timedelta(minutes=5)) == {"due": 0, "sent": 0}
    assert len(sent) == 1 and sent[0]["template"]["name"] == "booking_reminder"
    assert _params(sent[0]) == [MEET]


def test_the_reminder_goes_to_the_accounts_number(sent):
    now = datetime(2030, 1, 7, 5, 2, tzinfo=timezone.utc)
    rows = [{"id": id_, "user_id": user, "status": "confirmed", "guest_whatsapp": None,
             "meet_url": MEET, "whatsapp_reminder_sent_at": None,
             "start_at": (now + timedelta(minutes=8)).isoformat()}
            for id_, user in (("with-number", "u1"), ("no-number", "u2"))]
    table = _Bookings(rows, settings=[{"user_id": "u1", "whatsapp_phone": "+48600100200"},
                                      {"user_id": "u2", "whatsapp_phone": None}])
    with patch.object(booking, "db", table):
        with patch.object(booking.config, "BOOKING_WHATSAPP_TO_ACCOUNT", False, create=True):
            assert booking.send_whatsapp_reminders(now) == {"due": 0, "sent": 0}
        with patch.object(booking.config, "BOOKING_WHATSAPP_TO_ACCOUNT", True, create=True):
            assert booking.send_whatsapp_reminders(now) == {"due": 1, "sent": 1}
    assert [m["to"] for m in sent] == ["48600100200"]


def test_a_booking_forgets_its_number_after_the_reminder(sent):
    now = datetime(2030, 1, 7, 5, 2, tzinfo=timezone.utc)

    def row(id_, minutes):
        return {"id": id_, "status": "confirmed", "guest_whatsapp": "+48600100200",
                "meet_url": MEET, "whatsapp_reminder_sent_at": None,
                "start_at": (now + timedelta(minutes=minutes)).isoformat()}

    rows = [row("due", 8), row("tomorrow", 60 * 24), row("long-past", -61), row("just-past", -30)]
    table = _Bookings(rows)
    with patch.object(booking, "db", table):
        assert booking.send_whatsapp_reminders(now) == {"due": 1, "sent": 1}
        assert booking.forget_past_booking_numbers(now) == 1
    kept = {r["id"]: r["guest_whatsapp"] for r in rows}
    assert kept == {"due": None, "tomorrow": "+48600100200", "long-past": None,
                    "just-past": "+48600100200"}
