"""
STORY    As the founder, I want one "Homework" email a day listing who sent a
         Take, not one email per Take, so that my inbox stays readable while
         the coach queue still shows every Take at once.
OUTCOME
  O1  The Takes noted during the day go out as one email from 8:00 in my
      time zone, a row per student with their Takes and moments; nothing
      before 8:00 and nothing twice in a day.
  O2  A day with no Takes sends nothing.
  O3  A failed send keeps its Takes for the next day's email.
PROVES   O1 -> test_one_email_a_day_lists_every_student
         O2 -> test_a_day_without_takes_sends_nothing
         O3 -> test_a_failed_send_keeps_its_takes_for_tomorrow
WHY      Founder 2026-10-26, N174 item 3: "One email a day with the list. The
         coach queue in the app still shows every Take straight away."
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from config import Config
from services import homework_digest as digest

ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LONDON = ZoneInfo("Europe/London")


class _Store:
    """The few Redis calls the digest makes, kept in memory."""

    def __init__(self):
        self.lists: dict[str, list] = {}
        self.flags: set[str] = set()

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value.encode())

    def expire(self, key, seconds):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.flags:
            return None
        self.flags.add(key)
        return True

    def rename(self, src, dst):
        if src not in self.lists:
            raise RuntimeError("ERR no such key")
        self.lists[dst] = self.lists.pop(src)

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    def delete(self, key):
        self.lists.pop(key, None)


class _Db:
    def v2_get_student_details(self, user_id):
        return {"name": {ALICE: "Alice", BOB: ""}[user_id]}


@pytest.fixture
def world(monkeypatch):
    store, sent = _Store(), []
    monkeypatch.setattr(digest, "_store", lambda: store)
    monkeypatch.setattr(digest, "_zone", lambda: LONDON)
    monkeypatch.setattr(Config, "SEND_EMAILS", True)
    monkeypatch.setattr(Config, "FRONTEND_URL", "https://www.willpowerlab.com")
    monkeypatch.setattr("services.session_publish._fetch_user_email",
                        lambda uid: {ALICE: "alice@example.com", BOB: "bob@example.com"}[uid])

    def send_email_resend(*, to, subject, html, text, **_kw):
        if sent and sent[-1] == "fail-next":
            sent.pop()
            raise RuntimeError("resend down")
        sent.append({"to": to, "subject": subject, "text": text})

    monkeypatch.setattr("services.email_service.send_email_resend", send_email_resend)
    return store, sent


def _at(hour, day=27):
    return datetime(2026, 10, day, hour, 0, tzinfo=LONDON).astimezone(timezone.utc)


def test_one_email_a_day_lists_every_student(world):
    _store, sent = world
    digest.record("t1", ALICE, 3)
    digest.record("t2", BOB, 0)
    digest.record("t3", ALICE, 2)

    assert digest.sweep_due(now=_at(7), database=_Db()) == "not_yet"
    assert digest.sweep_due(now=_at(8), database=_Db()) == "sent"
    assert digest.sweep_due(now=_at(9), database=_Db()) == "already_today"

    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == Config.ADMIN_EMAIL
    assert mail["subject"] == "Homework, Tuesday 27 October: 3 Takes"
    assert "Alice (alice@example.com): 2 Takes, 5 moments to review" in mail["text"]
    assert "bob@example.com: 1 Take\n" in mail["text"]
    assert f"/admin/students/{ALICE}" in mail["text"]


def test_a_day_without_takes_sends_nothing(world):
    _store, sent = world
    assert digest.sweep_due(now=_at(8), database=_Db()) == "nothing"
    assert sent == []


def test_a_failed_send_keeps_its_takes_for_tomorrow(world):
    _store, sent = world
    digest.record("t1", ALICE, 1)
    sent.append("fail-next")

    assert digest.sweep_due(now=_at(8), database=_Db()) == "failed"
    assert digest.sweep_due(now=_at(8, day=28), database=_Db()) == "sent"
    assert "Alice (alice@example.com): 1 Take, 1 moment to review" in sent[0]["text"]
