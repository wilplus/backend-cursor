"""
STORY    As a speaker, I want to change my email and my password on Data &
         consent, with a link for a forgotten password, so that I keep my
         account when I lose an address or a password; and as the founder, I
         want every request, change and wrong password kept in a security log,
         so that a taken-over account can be traced.
OUTCOME
  O1  Change email: a wrong current password changes nothing and is logged;
      the right one sends a link to the new address and a notice to the old
      one, and the email stays until the link is opened. The log keeps the
      token's SHA-256, never the token, and never a password.
  O2  An address another account has is refused before any link goes, and
      the refusal is logged.
  O3  The link changes the email once and logs it; opened twice it changes
      nothing more. An older link after a newer request, an expired link and
      an unknown token change nothing.
  O4  Change password: a wrong current password or one under 6 characters
      changes nothing; the right one sets the new password, signs out the
      other devices, sends the notice and is logged with the IP address and
      the device.
  O5  An account that signs in with Google has no password to ask for: its
      email change needs none, Set a password sends the set email, and the
      saved password is logged as its first; a reset link's password is a
      change and gets the notice.
  O6  When the email doesn't go, the card is told so: nothing is reported
      as sent.
PROVES   O1 -> test_an_email_change_waits_for_the_link_from_the_new_address
         O2 -> test_an_address_with_an_account_is_refused_before_any_link
         O3 -> test_the_link_changes_the_email_once_and_only_the_newest
         O4 -> test_a_password_change_checks_the_current_one_and_signs_out_the_rest
         O5 -> test_a_google_account_sets_its_first_password_with_a_link
         O6 -> test_an_email_that_didnt_go_is_not_reported_as_sent
WHY      WIL-95 (founder 2026-10-26, N190: "approved, implement it"; rules in
         the frontend's docs/flows/consent-screens.md §1).
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from services import account_security as acc
from services.account_security import AccountError, Caller

ALEX = "u-alex"
CALLER = Caller(user_id=ALEX, jwt="jwt-alex", ip="203.0.113.7",
                user_agent="Mozilla/5.0 (iPhone)")


class _Ports:
    """Supabase Auth, the log table and the mailer, in memory."""

    base_url = "https://app.test"

    def __init__(self):
        self.users = {ALEX: {"email": "alex@example.com", "providers": ["email"],
                             "password": "practice"}}
        self.rows, self.sent, self.signed_out = [], [], []
        self.mail_works = True

    def get_user(self, user_id):
        user = self.users[user_id]
        return {"email": user["email"], "providers": list(user["providers"])}

    def has_password(self, user_id):
        return bool(self.users[user_id].get("password"))

    def email_in_use(self, email, except_user):
        return any(u["email"] == email for uid, u in self.users.items() if uid != except_user)

    def password_matches(self, email, password):
        return any(u["email"] == email and u.get("password") == password
                   for u in self.users.values())

    def update_user(self, user_id, attributes):
        self.users[user_id].update(attributes)

    def sign_out_others(self, jwt):
        self.signed_out.append(jwt)

    def recovery_token_hash(self, email):
        return "hash-for-" + email

    def insert_event(self, row):
        row = {**row, "id": f"r{len(self.rows) + 1}",
               "created_at": datetime.now(timezone.utc).isoformat()}
        self.rows.append(row)
        return row

    def latest_events(self, user_id, events, limit=1):
        mine = [r for r in self.rows if r["user_id"] == user_id and r["event"] in events]
        return list(reversed(mine))[:limit]

    def event_by_token(self, token_sha256):
        return next((r for r in self.rows if r.get("token_sha256") == token_sha256
                     and r["event"] == "email_change_requested"), None)

    def send(self, to, mail):
        if self.mail_works:
            self.sent.append((to, mail))
        return self.mail_works

    # -- what the tests read --
    def events(self):
        return [r["event"] for r in self.rows]

    def link_token(self, to):
        mail = next(m for t, m in self.sent if t == to and m["url"])
        return parse_qs(urlparse(mail["url"]).query)["token"][0]


@pytest.fixture
def ports():
    return _Ports()


def _never_a_secret(ports, *secrets):
    for row in ports.rows:
        for value in row.values():
            assert all(s not in str(value) for s in secrets), row


def test_an_email_change_waits_for_the_link_from_the_new_address(ports):
    with pytest.raises(AccountError) as wrong:
        acc.change_email(ports, CALLER, "alex@newco.com", "nope")
    assert wrong.value.code == "WRONG_PASSWORD"
    assert ports.sent == [] and ports.events() == ["password_check_failed"]

    assert acc.change_email(ports, CALLER, " Alex@NewCo.com ", "practice") == {
        "sent_to": "alex@newco.com"}
    assert [(to, m["subject"]) for to, m in ports.sent] == [
        ("alex@newco.com", "Confirm your new email"),
        ("alex@example.com", "Your email is changing")]
    assert ports.users[ALEX]["email"] == "alex@example.com"
    request = ports.rows[-1]
    assert request["event"] == "email_change_requested"
    assert (request["old_email"], request["new_email"]) == ("alex@example.com", "alex@newco.com")
    assert (request["ip"], request["user_agent"]) == ("203.0.113.7", "Mozilla/5.0 (iPhone)")
    token = ports.link_token("alex@newco.com")
    assert request["token_sha256"] == acc._sha(token)
    _never_a_secret(ports, token, "practice", "nope")


def test_an_address_with_an_account_is_refused_before_any_link(ports):
    ports.users["u-sam"] = {"email": "sam@example.com", "providers": ["email"]}
    with pytest.raises(AccountError) as taken:
        acc.change_email(ports, CALLER, "sam@example.com", "practice")
    assert taken.value.code == "EMAIL_TAKEN"
    assert ports.sent == [] and ports.events() == ["email_change_refused"]
    for value, code in (("not an email", "EMAIL_INVALID"), ("alex@example.com", "EMAIL_SAME")):
        with pytest.raises(AccountError) as refused:
            acc.change_email(ports, CALLER, value, "practice")
        assert refused.value.code == code


def test_the_link_changes_the_email_once_and_only_the_newest(ports):
    acc.change_email(ports, CALLER, "first@newco.com", "practice")
    older = ports.link_token("first@newco.com")
    acc.change_email(ports, CALLER, "second@newco.com", "practice")
    newest = ports.link_token("second@newco.com")

    for token in (older, "made-up", None):
        with pytest.raises(AccountError) as invalid:
            acc.confirm_email(ports, token)
        assert invalid.value.code == "LINK_INVALID"
    assert ports.users[ALEX]["email"] == "alex@example.com"

    assert acc.confirm_email(ports, newest, "198.51.100.2", "Mail") == {"email": "second@newco.com"}
    assert ports.users[ALEX]["email"] == "second@newco.com"
    changed = ports.rows[-1]
    assert (changed["event"], changed["old_email"], changed["new_email"], changed["ip"]) == (
        "email_changed", "alex@example.com", "second@newco.com", "198.51.100.2")
    acc.confirm_email(ports, newest)
    assert ports.events().count("email_changed") == 1

    acc.change_email(ports, CALLER, "third@newco.com", "practice")
    ports.rows[-1]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with pytest.raises(AccountError):
        acc.confirm_email(ports, ports.link_token("third@newco.com"))
    assert ports.users[ALEX]["email"] == "second@newco.com"


def test_a_password_change_checks_the_current_one_and_signs_out_the_rest(ports):
    for current, new, code in (("nope", "longer-one", "WRONG_PASSWORD"),
                               ("practice", "short", "PASSWORD_TOO_SHORT")):
        with pytest.raises(AccountError) as refused:
            acc.change_password(ports, CALLER, current, new)
        assert refused.value.code == code
    assert ports.users[ALEX]["password"] == "practice" and ports.signed_out == []

    assert acc.change_password(ports, CALLER, "practice", "longer-one") == {"changed": True}
    assert ports.users[ALEX]["password"] == "longer-one"
    assert ports.signed_out == ["jwt-alex"]
    assert [(to, m["subject"]) for to, m in ports.sent] == [
        ("alex@example.com", "Your password was changed")]
    changed = ports.rows[-1]
    assert (changed["event"], changed["source"], changed["ip"]) == (
        "password_changed", "settings", "203.0.113.7")
    _never_a_secret(ports, "practice", "longer-one", "jwt-alex")


def test_a_google_account_sets_its_first_password_with_a_link(ports):
    ports.users[ALEX] = {"email": "alex@example.com", "providers": ["google"]}
    assert acc.state(ports, CALLER) == {
        "email": "alex@example.com", "has_password": False, "provider": "Google"}
    assert acc.change_email(ports, CALLER, "alex@newco.com")["sent_to"] == "alex@newco.com"

    ports.sent.clear()
    assert acc.send_password_link(ports, CALLER) == {"sent_to": "alex@example.com", "kind": "set"}
    to, mail = ports.sent[-1]
    assert mail["subject"] == "Set your password"
    assert "You can still sign in with Google." in mail["lines"][0]
    assert mail["url"] == ("https://app.test/auth/callback?type=recovery"
                           "&token_hash=hash-for-alex%40example.com")
    assert acc.password_link_used(ports, CALLER) == {"event": "password_set"}
    assert len(ports.sent) == 1                       # a first password: no notice

    ports.users[ALEX]["password"] = "now-set"
    assert acc.send_password_link(ports, CALLER)["kind"] == "reset"
    assert ports.sent[-1][1]["subject"] == "Reset your password"
    assert acc.password_link_used(ports, CALLER) == {"event": "password_changed"}
    assert ports.sent[-1][1]["subject"] == "Your password was changed"
    assert ports.events() == ["email_change_requested", "password_set_requested",
                              "password_set", "password_reset_requested",
                              "password_changed"]
    assert [r["source"] for r in ports.rows if r["event"] in ("password_set", "password_changed")] == [
        "link", "link"]


def test_an_email_that_didnt_go_is_not_reported_as_sent(ports):
    ports.mail_works = False
    for send in (lambda: acc.change_email(ports, CALLER, "alex@newco.com", "practice"),
                 lambda: acc.send_password_link(ports, CALLER)):
        with pytest.raises(AccountError) as failed:
            send()
        assert failed.value.code == "SEND_FAILED"
    assert "password_reset_requested" not in ports.events()
