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
  O8  Moving the deadline keeps the practices done and counts the ones
      ahead: today's practice, already done, is not counted twice.
  O9  Two Takes in a row that reach the level start the next thing heard;
      three Takes on a level without moving are noted for the coach's
      queue, once; a coach's level is never moved; a level whose time ran
      out gives way at the next open, and that day's hello names the new
      level. Nothing about it is said in the chat.
  O10 A Take's walk reads the level the plan had when the Take was
      recorded, so it reads the same on every opening; off a plan, or on
      "Make it yours", the walk is as today.
  O11 While a speaker is onboarded (the questions; a new speaker's plan
      until the first Take), the principles show nothing and Will's chat
      does not answer as them; after the first Take they are back; a plan
      waiting for the next Take holds nothing back (N243).
  O12 A voice answer with no speech in it, or no words, is not kept and
      not sent on: Will says "Sorry, I didn't quite catch that. Could you
      say it again?" and the same question stays (N262).
  O13 An answer that puts Will right is not an answer to his question:
      Will agrees, says back what he now has, and asks the same question
      again; the correction takes the old answer's place and the old one
      stays in the history (N262).
  O14 A new speaker can record before answering: "Start your first
      recording" is offered while the questions are asked; after that
      Take's walk Will asks again where he was; the plan, once made, counts
      that Take as its first practice (N262).
PROVES   O1 -> test_without_the_ring_nothing_happens
         O2 -> test_a_new_speaker_is_asked_once
         O3 -> test_no_date_gives_two_months_then_the_voice_message
         O4 -> test_voice_answers_are_kept_and_the_key_line_comes_first
         O5 -> test_ratings_are_kept_quietly_and_the_calls_lead_to_the_plan
         O6 -> test_a_practice_day_hello_and_the_fifteen_minutes
         O7 -> test_a_new_project_asks_whether_it_is_for_the_same_event
         O8 -> test_moving_the_deadline_keeps_the_practices_done
         O9 -> test_the_level_moves_on_after_two_takes_that_reach_it
               test_a_level_whose_time_ran_out_gives_way
         O10 -> test_a_walk_reads_the_level_of_its_takes_time
         O11 -> test_the_principles_wait_while_the_speaker_is_onboarded
         O12 -> test_an_answer_with_nothing_heard_is_asked_again
         O13 -> test_a_correction_is_taken_and_the_question_asked_again
         O14 -> test_a_new_speaker_can_record_before_answering
WHY      The plan, built one to one with the prototype (founder 2026-10-26,
         N203, N204); a level moving on, N134 items 3 and 4, N209; the
         principles waiting for the onboarding, N243; record first, Will
         asking again and a correction taken, N262; the rules
         are frontend docs/flows/the-plan.md §1.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from services import plan as P
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
        self.clips = {}

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

    def get_snippets_by_session(self, session_id):
        return list(self.clips.get(session_id, []))

    def insert_plan_level_event(self, row):
        self.events.append({**row, "created_at": datetime.now(timezone.utc).isoformat()})
        return True

    def list_plan_level_events(self, user_id, plan_id):
        return [e for e in self.events if e["plan_id"] == plan_id]

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
    # The plan's own yes is tests/test_plan_consent.py; here the plan asks as
    # it does once the yes is given, which is the switch off.
    from config import Config
    monkeypatch.setattr(Config, "PLAN_CONSENT_ENABLED", False)
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
    assert plan["facts"]["key_answer_id"] == next(a["id"] for a in db.answers if a["kind"] == "key")
    assert plan["facts"]["language"] == "en"  # which coaches may hear them before a Take (N213)
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
                   "Every plan starts with a kickoff session with your coach. Would you like "
                   "to book it now?"]
    F.book_call(db, USER, "kickoff", None)
    F.book_call(db, USER, "summary", None)
    assert bodies(db)[-3:] == [
        "Every learning cycle also finishes with a summary session after your deadline. "
        "Would you like to choose it now?", "You're all set. Here's your plan.", ""]
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
    # The new plan's questions take their answers like a first plan's (N276).
    F.answer_deadline(db, USER, None, tz="UTC")
    _say(db, "It's our board pitch for two more hires.")
    _say(db, "We need the hires before spring.")
    assert len(db.get_open_plan(USER)["asked"]) == 2


def test_moving_the_deadline_keeps_the_practices_done(db, monkeypatch):
    plan = _active(db)
    took = datetime.fromisoformat(plan["started_at"]) + timedelta(seconds=1)
    db.takes.rows = [{"created_at": took.isoformat(), "arc_id": "arc-1", "take_index": 1}]
    today = took.astimezone(timezone.utc).date()
    monkeypatch.setattr(F, "today_in", lambda name: today)
    out = F.change(db, USER, deadline=(today + timedelta(days=10)).isoformat(), tz="UTC")
    # One practice done (today's); nine days ahead, every day: 1 + 9.
    assert out["plan"]["every_day"] and out["plan"]["total"] == 10
    assert F.P.practice_number(1, out["plan"]["total"]) == 2


FEW_PAUSES = [{"transcript": "We need two more hires this quarter.", "duration_ms": 60000,
               "metrics": {"pause_count": 1, "pause_ms": 300}}]
MANY_PAUSES = [{"transcript": "We need two more hires this quarter.", "duration_ms": 60000,
                "metrics": {"pause_count": 9, "pause_ms": 650}}]
FILLERS = [{"transcript": "So basically, you know, we basically, you know, need, basically, "
            "you know, two hires, basically.", "duration_ms": 30000,
            "metrics": {"pause_count": 6, "pause_ms": 650}}]


def _take(db, plan, n, clips):
    started = datetime.fromisoformat(plan["started_at"])
    db.takes.rows.append({"id": f"t{n}", "created_at": (started + timedelta(minutes=n)).isoformat(),
                          "arc_id": "arc-1", "take_index": n})
    db.clips[f"t{n}"] = clips
    F.after_take(db, USER)
    return db.get_open_plan(USER)


def test_the_level_moves_on_after_two_takes_that_reach_it(db, monkeypatch):
    plan = _active(db)
    monkeypatch.setattr(F.P, "is_practice_day", lambda *a, **k: False)
    db.update_plan(USER, plan["id"], {"level": "pauses", "level_by": "machine"})
    said = len(db.thread)
    plan = _take(db, plan, 1, FEW_PAUSES)
    plan = _take(db, plan, 2, MANY_PAUSES)
    assert plan["level"] == "pauses"
    plan = _take(db, plan, 3, FILLERS)  # reached twice in a row; the fillers are heard next
    assert plan["level"] == "say_once"
    assert [e["reason"] for e in db.events][-1:] == ["reached"]
    assert len(db.thread) == said  # the speaker just sees the next level (N134 item 3)
    for n in (4, 5, 6, 7):
        plan = _take(db, plan, n, FILLERS)
    assert plan["level"] == "say_once"
    assert [e["reason"] for e in db.events].count("stuck") == 1
    db.update_plan(USER, plan["id"], {"level": "pauses", "level_by": "coach"})
    for n in (8, 9):
        plan = _take(db, plan, n, MANY_PAUSES)
    assert plan["level"] == "pauses"  # a coach's level is never moved (C5)


def test_a_level_whose_time_ran_out_gives_way(db, monkeypatch):
    plan = _active(db)
    monkeypatch.setattr(F.P, "is_practice_day", lambda *a, **k: True)
    db.update_plan(USER, plan["id"], {"level": "key_line", "level_by": "machine"})
    plan = _take(db, plan, 1, FEW_PAUSES)  # no key line said: not read, still the level
    assert plan["level"] == "key_line"
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(F, "today_in", lambda name: today + timedelta(days=8))
    F.state(db, USER, tz="UTC", first_name="Artur")
    plan = db.get_open_plan(USER)
    assert plan["level"] == "pauses" and db.events[-1]["reason"] == "time"
    hello = next(r["body"] for r in reversed(db.thread) if r["metadata"].get("plan_hello"))
    assert hello.endswith(": Pauses that hold the room.")


def test_a_walk_reads_the_level_of_its_takes_time(db, monkeypatch):
    from services import plan_walk
    plan = _active(db)
    monkeypatch.setattr(F.P, "is_practice_day", lambda *a, **k: False)
    first = {"created_at": plan["started_at"]}
    assert plan_walk.level_for_take(db, USER, first) is None  # "Make it yours": as today
    db.update_plan(USER, plan["id"], {"level": "pauses", "level_by": "machine"})
    F._event(db, USER, plan, "pauses", "coach", "the coach's level")
    first = {"created_at": datetime.now(timezone.utc).isoformat()}
    for n, clips in ((1, MANY_PAUSES), (2, FILLERS)):
        plan = _take(db, plan, n, clips)
    assert plan["level"] == "say_once"
    later = {"created_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()}
    assert plan_walk.level_for_take(db, USER, first) == "pauses"
    assert plan_walk.level_for_take(db, USER, later) == "say_once"
    assert plan_walk.walk_inputs(db, USER, later)["plan_level"] == "say_once"
    monkeypatch.setattr("services.rings.feature_is_on_for_user", lambda *a, **k: False)
    assert plan_walk.walk_inputs(db, USER, later) == {}


def test_the_principles_wait_while_the_speaker_is_onboarded(db, monkeypatch):
    from services import life_goals, sunday_note, voice_notebook
    consent = {"decision": "yes"}
    db.get_voice_notebook_consent = lambda user: consent
    db.list_voice_notebook_consents = lambda: [{"user_id": USER, "time_zone": "UTC"}]
    db.get_sunday_note_for_week = lambda user, week: None
    monkeypatch.setattr("services.job_queue.enqueue", lambda path, *a, **k: True)
    monkeypatch.setattr("services.life_store.list_goals", lambda *a, **k: [])
    sunday_evening = datetime(2026, 10, 25, 18, 5, tzinfo=timezone.utc)

    def silent():
        return (voice_notebook.chat_turn(db, USER, "# the hotel was loud") is None
                and sunday_note.chat_turn(db, USER, "sunday note") is None
                and life_goals.chat_turn(db, USER, "#goals") is None
                and life_goals.after_note(db, USER) == []
                and life_goals.quarter_due(db, USER) == []
                and sunday_note.sweep_due(db, sunday_evening) == 0)

    assert F.state(db, USER, tz="UTC", first_name="Artur")["plan"]["onboarding"]
    assert silent()  # the questions
    plan = _active(db)
    assert F.state(db, USER, tz="UTC")["plan"]["onboarding"] and silent()  # before the first Take

    took = datetime.fromisoformat(plan["started_at"]) + timedelta(minutes=5)
    db.takes.rows = [{"created_at": took.isoformat(), "arc_id": "arc-1", "take_index": 1}]
    assert not F.state(db, USER, tz="UTC")["plan"]["onboarding"]
    assert sunday_note.sweep_due(db, sunday_evening) == 1  # back after the first Take
    consent = None
    assert voice_notebook.chat_turn(db, USER, "# the hotel was loud")["answer"] == voice_notebook.COPY["ask"]

    F.new_event(db, USER, tz="UTC")
    assert not F.onboarding(db, USER)  # a new event's questions wait for the next Take
    F.after_take(db, USER)
    consent = {"decision": "yes"}
    assert F.onboarding(db, USER) and silent()  # and while they are asked


def _to_why(db):
    F.state(db, USER, tz="UTC", first_name="Artur")
    F.answer_deadline(db, USER, None, tz="UTC")


def _say(db, said):
    return F.answer_voice(db, USER, _Adapter(said), b"audio", filename="a.webm",
                          content_type="audio/webm", duration_ms=4000)


def test_an_answer_with_nothing_heard_is_asked_again(db, monkeypatch):
    _to_why(db)
    asked = len(db.thread)
    silence = _Adapter("Thank you.")  # what a transcriber makes of silence
    monkeypatch.setattr("services.min_content_gate.evaluate_min_content_bytes",
                        lambda audio: {"ok": False, "reason": "no_speech", "voiced_sec": 0.0})
    out = F.answer_voice(db, USER, silence, b"audio", filename="a.webm",
                         content_type="audio/webm", duration_ms=6000)
    assert silence.calls == 0  # not sent on
    assert bodies(db)[asked:] == ["Sorry, I didn't quite catch that. Could you say it again?"]
    assert out["plan"]["step"] == "why" and db.answers == [] and db.audio == {}
    monkeypatch.setattr("services.min_content_gate.evaluate_min_content_bytes",
                        lambda audio: {"ok": True, "reason": None, "voiced_sec": 0.8})
    _say(db, "")  # heard, but no words
    assert bodies(db)[-1] == "Sorry, I didn't quite catch that. Could you say it again?"
    assert db.get_open_plan(USER)["step"] == "why" and db.answers == []
    # Asked again twice, Will moves on (N276): the third time nothing is heard
    # (here the transcriber's stock line, N275), he asks the next question in
    # its plain words, with no ack, for nothing was heard to name.
    before = len(db.thread)
    _say(db, "Thanks for watching!")
    assert bodies(db)[before:] == [P.BANK["key"][0]]
    assert db.get_open_plan(USER)["step"] == "followup" and db.answers == []
    _say(db, "Five people.")  # a short answer is heard
    assert len(db.answers) == 1


def test_a_correction_is_taken_and_the_question_asked_again(db, monkeypatch):
    _to_why(db)
    # Kept before N276, with the transcriber's stock line still in it.
    _say(db, "It's our board pitch for two more hires. Thank you for watching.")
    key_q = bodies(db)[-1]
    seen = []

    def turn(database, user_id, plan, asked, answering=None):
        seen.append(F._transcript(database, user_id, plan, answering))
        return {"facts": {"event": "a board pitch for funding"},
                "correction": {"of": "why", "said_back": "You'll ask the board for funding."}}

    monkeypatch.setattr(F, "_turn", turn)
    before = len(db.thread)
    out = _say(db, "No, that's not what I meant. It's about funding, not hires.")
    ack = ("Will", "Thank you. Now I can hear you talking about your goal and why it matters.")
    assert seen[0][-3:] == [ack, ("Will", key_q), ("Speaker (voice message)",
                            "No, that's not what I meant. It's about funding, not hires.")]
    assert ("Speaker (voice message)", "It's our board pitch for two more hires.") in seen[0]
    assert bodies(db)[before:] == [
        "No, that's not what I meant. It's about funding, not hires.",
        "Got it, thank you for putting me right. You'll ask the board for funding.",
        key_q]
    plan = db.get_open_plan(USER)
    assert out["plan"]["step"] == "followup" and len(plan["asked"]) == 1  # not an answer to it
    assert plan["facts"]["event"] == "a board pitch for funding"
    assert [a["kind"] for a in db.answers] == ["why", "why"]  # takes its place; the old stays
    assert "key_line" not in plan["facts"]
    # One correction per question (N275): the next answer to it is an answer,
    # whatever the AI reads, so a misheard correction can't loop.
    _say(db, "Board members and our CEO.")
    assert bodies(db)[-1] != key_q and len(db.get_open_plan(USER)["asked"]) == 2
    # What Will says back comes from what the speaker just said (N150 rule 1):
    # a correction with none of their words in it is the AI's, and the
    # answer counts as an answer.
    _say(db, "About five minutes, with slides.")
    assert not any("putting me right" in b for b in bodies(db)[-3:])
    assert len(db.get_open_plan(USER)["asked"]) == 3


def test_a_new_speaker_can_record_before_answering(db, monkeypatch):
    out = F.state(db, USER, tz="UTC", first_name="Artur")
    assert out["plan"]["record_now"] and not out["plan"]["waiting"]
    F.answer_deadline(db, USER, None, tz="UTC")
    _say(db, "It's our board pitch for two more hires.")
    key_q = bodies(db)[-1]
    plan = db.get_open_plan(USER)
    took = datetime.now(timezone.utc)
    db.update_plan(USER, plan["id"], {"created_at": (took - timedelta(minutes=5)).isoformat()})
    db.takes.rows = [{"created_at": took.isoformat(), "arc_id": "arc-1", "take_index": 1}]
    out = F.state(db, USER, tz="UTC")
    assert out["plan"]["waiting"] and not out["plan"]["record_now"]  # the Take's walk first
    F.after_take(db, USER)
    assert bodies(db)[-1] == key_q  # asked again, where it was
    assert not F.state(db, USER, tz="UTC")["plan"]["waiting"]
    for said in ("The window closes soon.", "Five board members.", "About three minutes."):
        _say(db, said)
    F.answer_rating(db, USER, 7)
    F.answer_rating(db, USER, 4)
    F.book_call(db, USER, "kickoff", None)
    out = F.book_call(db, USER, "summary", None)
    assert out["plan"]["status"] == "active"
    view = F.view(db, USER, out["plan"])
    assert view["first_take_done"] and view["done"] == 1  # that Take is the first practice
