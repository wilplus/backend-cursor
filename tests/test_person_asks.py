"""
STORY    As a speaker, I want a "no" I give in the chat to stop the same consent
         being asked again for 30 days, and never to be asked for a consent no
         screen can answer, so that my consent stays freely given.
OUTCOME
  O1  Within 30 days of a "no" in the chat, asking again is refused
      (TOO_SOON); after 30 days it is allowed.
  O2  A consent no screen can answer (share, email) is never asked
      (INVALID_CONSENT).
PROVES   O1 -> test_a_no_in_the_chat_waits_thirty_days_before_asking_again
         O2 -> test_a_consent_no_screen_answers_is_not_asked
WHY      Founder 2026-10-18: privacy law wants consent given freely.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import person_asks
from tests.fakes import FakeSupabaseClient, swap_attr

USER = "9f4e75b8-268b-468d-9111-000000000088"


def _client(chat_no_at):
    """person_asks rows: the last chat answer for the consent, no open ask."""
    def rows(q):
        since = max(i for i, c in enumerate(q.calls) if c[0] in ("select", "insert", "update"))
        recent = q.calls[since:]
        if recent[0][0] == "insert":
            return [q.payload]
        if ("eq", ("status", "answered"), {}) in recent:
            return [{"resolved_at": chat_no_at}] if chat_no_at else []
        return []
    return FakeSupabaseClient({"person_asks": rows})


def _ask(chat_no_at, key="training"):
    with swap_attr(person_asks.db, "client", _client(chat_no_at)):
        return person_asks.create(USER, "consent", key, admin_id="admin",
                                  consents=[{"key": key, "state": "missing"}])


def test_a_no_in_the_chat_waits_thirty_days_before_asking_again():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(person_asks.AskError) as refused:
        _ask(yesterday)
    assert refused.value.code == "TOO_SOON"
    long_ago = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    assert _ask(long_ago)["consent_key"] == "training"


def test_a_consent_no_screen_answers_is_not_asked():
    for key in ("share", "email"):
        with pytest.raises(person_asks.AskError) as refused:
            _ask(None, key)
        assert refused.value.code == "INVALID_CONSENT"
