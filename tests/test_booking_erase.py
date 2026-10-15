"""Closing an account: a booking goes with it, except a paid lesson's
accounting record, wiped to date, price and Stripe reference (founder
2026-10-15, fix 6; Privacy 3.6 §7 and §9)."""
from __future__ import annotations

from unittest.mock import patch

from services import booking


class _Table:
    def __init__(self, rows):
        self.rows, self._op, self._filters, self._values = rows, None, [], None

    def select(self, *_):
        self._op = "select"
        return self

    def update(self, values):
        self._op, self._values = "update", values
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def _match(self, row):
        return all(str(row.get(c)) == str(v) for c, v in self._filters)

    def execute(self):
        hit = [r for r in self.rows if self._match(r)]
        if self._op == "update":
            for r in hit:
                r.update(self._values)
        elif self._op == "delete":
            for r in hit:
                self.rows.remove(r)
        self._filters = []
        return type("R", (), {"data": [dict(r) for r in hit]})()


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.client = self

    def table(self, _name):
        return _Table(self.rows)


def test_closing_an_account_deletes_bookings_and_keeps_paid_lessons_bare():
    rows = [
        {"id": "a", "user_id": "u1", "status": "confirmed", "price_cents": 6000,
         "stripe_session_id": "cs_1", "guest_name": "Ann", "guest_email": "a@x",
         "note": "hi", "guest_timezone": "Europe/Warsaw"},
        {"id": "b", "user_id": "u1", "status": "held", "price_cents": 6000,
         "stripe_session_id": None, "guest_name": "Ann", "guest_email": "a@x",
         "note": "", "guest_timezone": "Europe/Warsaw"},
        {"id": "c", "user_id": "u2", "status": "confirmed", "price_cents": 6000,
         "stripe_session_id": "cs_2", "guest_name": "Bo", "guest_email": "b@x",
         "note": "", "guest_timezone": "UTC"},
    ]
    with patch.object(booking, "db", _Db(rows)):
        assert booking.erase_for_user("u1") == {"deleted": 1, "kept_for_accounting": 1}
    paid = next(r for r in rows if r["id"] == "a")
    assert paid["user_id"] is None and paid["guest_name"] == "" and paid["guest_email"] == ""
    assert paid["note"] == "" and paid["price_cents"] == 6000 and paid["stripe_session_id"] == "cs_1"
    assert [r["id"] for r in rows] == ["a", "c"]
