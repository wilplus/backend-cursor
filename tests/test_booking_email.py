"""
STORY    As someone who signed up with WhatsApp, I want to give my email only
         when I book a call, so that the calendar invite reaches me and my
         account keeps the email for receipts and later invites.
OUTCOME
  O1  An account with no email books with the email it typed, and that
      address gets the link that makes it the account's email; once the
      link is opened, the account has it.
  O2  An account that has an email books with it, whatever is typed, and
      no link goes.
  O3  When the link cannot go (the address has another account), the
      booking still goes ahead.
PROVES   O1 -> test_an_account_without_email_books_with_the_one_it_typed
         O2 -> test_an_account_with_email_books_with_its_own
         O3 -> test_a_link_that_cannot_go_does_not_stop_the_booking
WHY      Founder 2026-10-27, N214 item 4.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from services import account_security as acc

USER = "11111111-1111-4111-8111-111111111111"
DOOR = "/v2/booking/artur/checkout"


class _Accounts:
    """Supabase Auth, the security log and the mailer, in memory."""

    base_url = "https://app.test"

    def __init__(self, users):
        self.users, self.rows, self.sent = users, [], []

    def get_user(self, user_id):
        return {"email": self.users[user_id], "providers": ["phone"]}

    def has_password(self, user_id):
        return False

    def email_in_use(self, email, except_user):
        return any(e == email for uid, e in self.users.items() if uid != except_user)

    def insert_event(self, row):
        row = {**row, "id": f"r{len(self.rows) + 1}"}
        self.rows.append(row)
        return row

    def latest_events(self, user_id, events, limit=1):
        mine = [r for r in self.rows if r["user_id"] == user_id and r["event"] in events]
        return list(reversed(mine))[:limit]

    def event_by_token(self, token_sha256):
        return next((r for r in self.rows if r.get("token_sha256") == token_sha256), None)

    def update_user(self, user_id, attributes):
        self.users[user_id] = attributes["email"]

    def send(self, to, mail):
        self.sent.append((to, mail))
        return True


@pytest.fixture()
def book(monkeypatch):
    """The checkout door on a test app. Returns a function that books as an
    account whose token carries `email`, the email the hold used, and the
    in-memory accounts."""
    from flask import Flask

    import auth
    from routes.v2 import booking as route
    from services.rate_limits import limiter

    if hasattr(limiter, "initialized"):
        monkeypatch.setattr(limiter, "initialized", False)
    app = Flask(__name__)
    app.register_blueprint(route.booking_bp)
    client = app.test_client()
    held: list[str] = []

    def _start_checkout(**kw):
        held.append(kw["email"])
        return {"url": "https://checkout.test"}

    monkeypatch.setattr(route.booking, "start_checkout", _start_checkout)

    def _book(token_email, typed, accounts):
        monkeypatch.setattr(auth, "verify_supabase_token",
                            lambda t: {"sub": USER, "email": token_email})
        monkeypatch.setattr(acc, "Ports", lambda: accounts)
        res = client.post(DOOR, headers={"Authorization": "Bearer jwt"},
                          json={"start": "2030-01-07T10:00:00Z", "name": "Ann",
                                "email": typed, "timezone": "Europe/Warsaw"})
        assert res.status_code == 200
        return held[-1]

    return _book


def test_an_account_without_email_books_with_the_one_it_typed(book):
    accounts = _Accounts({USER: ""})
    assert book("", " ann@example.com ", accounts) == "ann@example.com"
    [(to, mail)] = accounts.sent
    assert to == "ann@example.com" and mail["subject"] == "Confirm your new email"
    assert accounts.users[USER] == ""  # not before the link is opened
    token = parse_qs(urlparse(mail["url"]).query)["token"][0]
    acc.confirm_email(accounts, token)
    assert accounts.users[USER] == "ann@example.com"


def test_an_account_with_email_books_with_its_own(book):
    accounts = _Accounts({USER: "ann@example.com"})
    assert book("ann@example.com", "someone@else.com", accounts) == "ann@example.com"
    assert accounts.sent == []


def test_a_link_that_cannot_go_does_not_stop_the_booking(book):
    accounts = _Accounts({USER: "", "other": "ann@example.com"})
    assert book("", "ann@example.com", accounts) == "ann@example.com"
    assert accounts.sent == []
