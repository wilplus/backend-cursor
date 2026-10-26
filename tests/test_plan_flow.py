"""
STORY    As a new speaker on the plan's ring, I want Will to ask me a few
         questions in the Lounge before my first Take and give me a plan, so
         that my practice starts from my event and my own voice.
OUTCOME
  O1  Someone without the plan sees nothing of it: no plan, nothing written.
  O2  A new speaker with no Take is asked, once: "Hi Artur! A few quick
      questions before your first practice." and "When is your deadline?".
  O3  "No date yet" gives two months, said in words; then the voice
      message's two questions.
  O4  Each voice answer is transcribed under the caller's authorization,
      kept with its recording, kept for Will, and shown as the speaker's
      voice bubble; when the AI fails Will says the plain words, and the key
      line is always the first follow-up.
  O5  The two ratings are kept and never shown back as a number; then the
      kickoff call is offered, then the summary call; skipping both still
      gives "You're all set. Here's your plan." and the card.
  O6  On a practice day after the first Take, the first open writes the
      hello and today's one thing, once; after a Take on a practice day the
      15 minutes lines come, once.
  O7  A new project's first Take asks "Is this for {date}?"; Yes keeps the
      plan, No starts "When is your deadline?" for a new one, the old plan
      kept in the history.
PROVES   O1 -> test_without_the_ring_nothing_happens
         O2 -> test_a_new_speaker_is_asked_once
         O3 -> test_no_date_gives_two_months_then_the_voice_message
         O4 -> test_voice_answers_are_kept_and_the_key_line_comes_first
         O5 -> test_ratings_are_kept_quietly_and_the_calls_lead_to_the_plan
         O6 -> test_a_practice_day_hello_and_the_fifteen_minutes
         O7 -> test_a_new_project_asks_whether_it_is_for_the_same_event
WHY      The plan, built one to one with the prototype (founder 2026-10-26,
         N203, N204); the rules are frontend docs/flows/the-plan.md §1.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from services import plan_flow as F

USER = "11111111-1111-1111-1111-111111111111"


class _Takes:
    def __init__(self):
        self.rows = []

    def list_user_arc_sessions(self, user_id, strict=False):
        return list(self.rows)


class _Db:
    def __init__(self):
        self.plans, self.answers, self.audio, self.events, self.thread = [], [], {}, [], []
        self.takes = _Takes()

    def get_open_plan(self, user_id):
        rows = [p for p in self.plans if p["status"] in ("asking", "active", "ending")]
        return dict(rows[-1]) if rows else None

    def get_latest_plan(self, user_id):
        return dict(self.plans[-1]) if self.plans else None

    def insert_plan(self, row):
        if row.get("status") in ("asking", "active") and self.get_open_plan(USER):
            return None
        stored = {"id": str(uuid.uuid4()), "practice_days": [1, 3, 5], "facts": {}, "asked": [],
                  "calls": {}, "level": None, "level_by": None, "deadline": None,
                  "deadline_given": False, "every_day": False, "total": None, "hello_on": None,
                  "done_on": None, "started_at": None, "time_zone": None, **row}
        self.plans.append(stored)
        return dict(stored)

    def update_plan(self, user_id, plan_id, fields):
        for p in self.plans:
            if p["id"] == plan_id:
                p.update(fields)
                return dict(p)
        return None

    def insert_plan_answer(self, row):
        stored = {"id": str(uuid.uuid4()), **row}
        self.answers.append(stored)
        return stored

    def list_plan_answers(self, user_id, plan_id):
        return [a for a in self.answers if a["plan_id"] == plan_id]

    def insert_plan_answer_audio(self, answer_id, user_id, content_type, audio):
        self.audio[answer_id] = audio
        return True

    def insert_plan_level_event(self, row):
        self.events.append(row)
        return True

    def list_user_bookings(self, user_id, *, ids=None, start_at=None):
        return []

    def get_lounge_messages_page(self, user_id, *, limit, before=None):
        return list(reversed(self.thread))[:limit]

    def insert_lounge_messages(self, user_id, rows):
        known = {r["client_id"] for r in self.thread}
        new = [r for r in rows if r["client_id"] not in known]
        self.thread.extend(new)
        return new


class _Adapter:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def transcribe_audio(self, audio, filename, **kw):
        self.calls += 1
        return {"text": self.text, "language": "en", "duration": 4.0}


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr("services.rings.feature_is_on_for_user", lambda *a, **k: True)
    monkeypatch.setattr("services.speaker_memory.record", lambda *a, **k: None)
    monkeypatch.setattr(F, "_readings", lambda *a, **k: {})
    monkeypatch.setattr(F, "_turn", lambda *a, **k: None)  # the AI fails: plain words
    return _Db()


def bodies(db):
    return [r["body"] for r in db.thread]


def test_without_the_ring_nothing_happens(monkeypatch):
    monkeypatch.setattr("services.rings.feature_is_on_for_user", lambda *a, **k: False)
    d = _Db()
    assert F.state(d, USER, tz="Europe/Warsaw", first_name="Artur") == {
        "enabled": False, "plan": None, "wrote": False}
    assert d.thread == [] and d.plans == []
    assert F.after_take(d, USER) == []


def test_a_new_speaker_is_asked_once(db):
    first = F.state(db, USER, tz="Europe/Warsaw", first_name="Artur")
    assert first["wrote"] and first["plan"]["step"] == "deadline"
    assert bodies(db) == ["Hi Artur! A few quick questions before your first practice.",
                          "When is your deadline?"]
    again = F.state(db, USER, tz="Europe/Warsaw", first_name="Artur")
    assert not again["wrote"] and len(db.thread) == 2


def test_no_date_gives_two_months_then_the_voice_message(db):
    F.state(db, USER, tz="UTC", first_name=None)
    F.answer_deadline(db, USER, None, tz="UTC")
    given = F.P.fmt_day(datetime.now(timezone.utc).date() + timedelta(days=56))
    assert bodies(db)[2:] == [
        "No date yet",
        f"That's fine. Let's give it two months, until {given}.",
        "I assume you came here to practise for some important event in your life.",
        "Please tell me, why does it matter and what is it about?",
    ]
    with pytest.raises(F.PlanError):
        F.answer_deadline(db, USER, None, tz="UTC")  # asked once


def _to_ratings(db):
    F.state(db, USER, tz="UTC", first_name="Artur")
    F.answer_deadline(db, USER, (date.today() + timedelta(days=21)).isoformat(), tz="UTC")
    for said in ("It's our board pitch for two more hires.", "The window closes soon.",
                 "Five board members.", "About three minutes."):
        F.answer_voice(db, USER, _Adapter(said), b"audio", filename="a.webm",
                       content_type="audio/webm", duration_ms=4000)


def test_voice_answers_are_kept_and_the_key_line_comes_first(db):
    _to_ratings(db)
    voice = [r for r in db.thread if (r["metadata"] or {}).get("plan_voice")]
    assert len(voice) == 4 and all(r["role"] == "user" for r in voice)
    assert len(db.audio) == 4
    said = bodies(db)
    ack = "Thank you. Now I can hear you talking about your goal and why it matters. "
    assert ack + "I can already hear your main vocal cues and verbal habits." in said
    key = said.index("If your audience remembers one sentence from you, what is it? "
                     "Say it the way you'll say it.")
    assert key > said.index("Let me draft your plan. A few more questions first.")
    assert said[-2:] == ["Two quick taps before your plan.", "How stressed do you feel about it right now?"]
    plan = db.get_open_plan(USER)
    assert plan["facts"]["key_line"] == "The window closes soon."
    assert len(plan["asked"]) == 3


def test_ratings_are_kept_quietly_and_the_calls_lead_to_the_plan(db):
    _to_ratings(db)
    before = len(db.thread)
    F.answer_rating(db, USER, 7)
    F.answer_rating(db, USER, 4)
    assert [a["value"] for a in db.answers if a.get("value")] == [7, 4]
    new = bodies(db)[before:]
    assert "7" not in new and "4" not in new
    assert new == ["How ready do you feel for it right now?",
                   "Before I show you your plan, pick a time for a 15-minute call with your "
                   "coach. It's your kickoff call."]
    F.book_call(db, USER, "kickoff", None)
    F.book_call(db, USER, "summary", None)
    assert bodies(db)[-3:] == [
        "Would you also like to book your summary call? It's after your deadline, to look "
        "back and plan what's next.", "You're all set. Here's your plan.", ""]
    assert db.thread[-1]["metadata"]["plan_card"] is True
    plan = db.get_open_plan(USER)
    assert plan["status"] == "active" and plan["total"] == 9 and plan["level"]


def test_a_practice_day_hello_and_the_fifteen_minutes(db, monkeypatch):
    _to_ratings(db)
    F.answer_rating(db, USER, 7)
    F.answer_rating(db, USER, 4)
    F.book_call(db, USER, "kickoff", None)
    F.book_call(db, USER, "summary", None)
    plan = db.get_open_plan(USER)
    started = datetime.fromisoformat(plan["started_at"])
    db.takes.rows = [{"created_at": (started + timedelta(minutes=5)).isoformat(),
                      "arc_id": "arc-1", "take_index": 1}]
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(F.P, "is_practice_day", lambda *a, **k: True)
    F.after_take(db, USER)
    assert bodies(db)[-2:] == ["That's your 15 minutes for today.",
                               "Now go and live it, away from the phone."]
    n = len(db.thread)
    F.after_take(db, USER)
    assert len(db.thread) == n  # once a day
    # The next practice day: the hello and today's one thing, once.
    monkeypatch.setattr(F, "today_in", lambda name: today + timedelta(days=2))
    out = F.state(db, USER, tz="UTC", first_name="Artur")
    assert out["wrote"]
    hello, one = db.thread[-2], db.thread[-1]
    assert hello["body"].startswith("Hi Artur, good to see you back! Today is practice 2 of 9: ")
    assert hello["metadata"]["day_line"]
    assert one["body"].startswith("Today, one thing: ")
    assert one["metadata"]["arc_id"] == "arc-1" and one["metadata"]["take_index"] == 1
    assert not F.state(db, USER, tz="UTC", first_name="Artur")["wrote"]


def _active(db):
    _to_ratings(db)
    F.answer_rating(db, USER, 7)
    F.answer_rating(db, USER, 4)
    F.book_call(db, USER, "kickoff", None)
    F.book_call(db, USER, "summary", None)
    return db.get_open_plan(USER)


def test_a_new_project_asks_whether_it_is_for_the_same_event(db, monkeypatch):
    plan = _active(db)
    started = datetime.fromisoformat(plan["started_at"])
    monkeypatch.setattr(F.P, "is_practice_day", lambda *a, **k: False)
    db.takes.rows = [{"created_at": (started + timedelta(minutes=5)).isoformat(), "arc_id": "arc-1", "take_index": 1}]
    F.after_take(db, USER)
    assert "Is this for" not in " ".join(bodies(db))
    db.takes.rows.append({"created_at": (started + timedelta(days=2)).isoformat(), "arc_id": "arc-2", "take_index": 1})
    F.after_take(db, USER)
    deadline = F.P.fmt_day(date.fromisoformat(plan["deadline"]))
    assert bodies(db)[-1] == f"Is this for {deadline}?"
    out = F.same_event(db, USER, False, tz="UTC", first_name="Artur")
    assert bodies(db)[-2:] == ["No", "When is your deadline?"]
    assert out["plan"]["status"] == "asking"
    assert [p["status"] for p in db.plans] == ["replaced", "asking"]
