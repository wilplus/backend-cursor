"""
STORY    As a speaker, I want one message when my coach is done with my Take,
         not one for every answer, so that my phone buzzes once and only
         when I have not already seen it.
OUTCOME
  O1  A coach who leaves a word and answers four moments sends one message,
      after the last share, naming the Take of the last share; the job of
      an earlier share sends nothing, and a job that runs twice sends once.
  O2  With a WhatsApp number the WhatsApp goes and no email; without one
      the email goes, counting every moment the coach answered.
  O3  A speaker who opened the coach's feedback before it was due (the
      orange dot cleared) gets nothing.
  O4  A later sitting counts only its own moments.
PROVES   O1 -> test_a_sitting_sends_one_message_after_the_last_share
         O2 -> test_a_sitting_sends_one_message_after_the_last_share,
               test_without_a_number_one_email_counts_every_moment
         O3 -> test_nothing_goes_when_the_speaker_already_opened_it
         O4 -> test_a_later_sitting_counts_only_its_own_moments
WHY      Founder 2026-10-26, N171 items 3 and 4 and N174 item 2: "Today, if a
         coach answers 5 moments and leaves a note, the speaker's phone
         buzzes 6 times and 6 emails arrive."
"""
from __future__ import annotations

import pytest

from services import coach_feedback_notice as notice
from services import job_queue

USER = "11111111-1111-4111-8111-111111111111"
TAKE_1 = "22222222-2222-4222-8222-222222222221"
TAKE_2 = "22222222-2222-4222-8222-222222222222"


class _Store:
    """The few Redis calls the notice makes, kept in memory (bytes back, as
    redis-py returns them)."""

    def __init__(self):
        self.hashes: dict[str, dict] = {}
        self.flags: set[str] = set()

    def hincrby(self, key, field, n):
        row = self.hashes.setdefault(key, {})
        row[field] = int(row.get(field, 0)) + int(n)
        return row[field]

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def expire(self, key, seconds):
        return True

    def hgetall(self, key):
        return {k.encode(): str(v).encode() for k, v in self.hashes.get(key, {}).items()}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.flags:
            return None
        self.flags.add(key)
        return True


class _Db:
    def __init__(self, seen=False):
        self.seen = seen

    def v2_get_session_by_id(self, sid):
        return {"user_id": USER, "arc_id": "arc-1", "id": sid}

    def new_coach_feedback_by_project(self, _user):
        return {"arc-1": not self.seen}


@pytest.fixture
def world(monkeypatch):
    sent = {"whatsapp": [], "email": [], "jobs": [], "has_number": True}
    store = _Store()
    monkeypatch.setattr(notice, "_store", lambda: store)

    def enqueue(func_path, *args, delay_seconds=0, rq_job_id=None, **_kw):
        assert func_path == notice._JOB and delay_seconds == notice.QUIET_SECONDS
        sent["jobs"].append(args)
        return True

    def whatsapp(_db, user_id, take_session_id=None):
        if sent["has_number"]:
            sent["whatsapp"].append((user_id, take_session_id))
        return sent["has_number"]

    def email(_db, *, take_session_id, moments):
        sent["email"].append((take_session_id, moments))
        return "sent"

    monkeypatch.setattr(job_queue, "enqueue", enqueue)
    monkeypatch.setattr("services.whatsapp_notify.notify_coach_feedback_in", whatsapp)
    monkeypatch.setattr("services.coach_feedback_email.send_coach_feedback_email", email)
    return sent


def _sitting(db, *, word_take=TAKE_1, moment_take=TAKE_2, moments=4):
    notice.coach_shared(db, user_id=USER, take_session_id=word_take, moments=0)
    for _ in range(moments):
        notice.coach_shared(db, user_id=USER, take_session_id=moment_take, moments=1)


def _run(jobs, db):
    return [notice.send_when_quiet(*args, database=db) for args in jobs]


def test_a_sitting_sends_one_message_after_the_last_share(world):
    db = _Db()
    _sitting(db)
    assert len(world["jobs"]) == 5 and world["whatsapp"] == []

    outcomes = _run(world["jobs"], db)

    assert outcomes == ["coach_not_done"] * 4 + ["whatsapp"]
    assert world["whatsapp"] == [(USER, TAKE_2)] and world["email"] == []
    assert notice.send_when_quiet(*world["jobs"][-1], database=db) == "already_sent"
    assert len(world["whatsapp"]) == 1


def test_without_a_number_one_email_counts_every_moment(world):
    world["has_number"] = False
    db = _Db()
    _sitting(db)

    _run(world["jobs"], db)

    assert world["email"] == [(TAKE_2, 4)]


def test_nothing_goes_when_the_speaker_already_opened_it(world):
    db = _Db(seen=True)
    _sitting(db)

    assert _run(world["jobs"], db)[-1] == "seen"
    assert world["whatsapp"] == [] and world["email"] == []


def test_a_later_sitting_counts_only_its_own_moments(world):
    world["has_number"] = False
    db = _Db()
    _sitting(db, moments=3)
    _run(world["jobs"], db)
    world["jobs"].clear()

    _sitting(db, moments=2)
    _run(world["jobs"], db)

    assert world["email"] == [(TAKE_2, 3), (TAKE_2, 2)]
