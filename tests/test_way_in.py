"""
STORY    As a newcomer in Artur's chat, while my first Take is processed, I
         want Will to check what he heard and ask what I'd like to do here,
         so that my plan and my next step are mine before the walk ends.
OUTCOME
  W1  Once Take 1 is sent: "While your feedback is being prepared, check
      what I heard.", then "What would you like to do here first?" with
      "Something else" first, "Learn from others", "Share what I know",
      "Prepare a talk", several then "Send" (FT-05, WID-04; N453, N573).
  W2  Once the Take's words are stored: "Here's how others will see you:"
      and the card from slide 1 (the role, About, topics as "Ask about
      {topic}", the name from sign-up); "That's right" keeps it, and only
      then may others see it; "Change it" brings "Tell me what to change."
      (FT-06; N453 item 2).
  W3  "Prepare a talk" alone asks "When is it?" with "No date yet", once;
      its date is the plan's; nobody is asked "When is your deadline?"
      (FT-10, PLAN-16; N564 item 1).
  W4  "Share what I know" brings the questions for people who join into
      the wait, then the agreement "Do you accept it?" with "I agree", and
      one "You're set." with "Copy my link ›" and "Your questions for
      people who join ›" (FT-11, FT-12, FT-13; N572).
  W5  Everyone gets the plan card and one "You're set."; nobody outside a
      team or sharing is asked the agreement (FT-12, FT-13).
  W6  After "You're set.": "Your feedback is almost ready. It will appear
      at the top of this chat." while it is prepared; "Your feedback is
      ready." with "Open your feedback ›" once it is; after the walk one
      bubble by the choice, the talk first, then sharing; "Record Take 2"
      stays faded until the walk is done (N592; WAYIN-N592-1..4).
  W7  "Learn from others" leads to "Next, ask someone who knows. Tap + to
      start." (FT-14, N592 item 2).
  W8  A speaking coach's link meets none of the choice's beats; the way in
      is in the speaking chat only (N572, N590; WAYIN-N590-1).
  W9  A first Take on which nothing was heard still gets its plan and
      "You're set." once its walk is done; no card is checked (N459 item 1).
  W10 With the chat builder, "Share what I know" is followed by "Next, open
      Your chat below, and set it up." (N634 item 3), never "set up your
      assistant", and nothing opens the earlier setup.
PROVES   W1, W2, W3, W5, W6 -> test_a_talk_the_wait_and_what_comes_next
         W9 -> test_a_take_with_nothing_heard_still_gets_its_plan
         W2 -> test_change_it_asks_what_to_change_and_draws_the_card_again
         W4 -> test_sharing_brings_the_join_questions_and_the_agreement
         W6, W7 -> test_learning_after_the_walk_and_record_take_2_waits
         W8 -> test_a_coachs_link_and_another_chat_meet_none_of_it
         W10 -> test_with_the_new_setup_sharing_points_to_your_chat
WHY      N453, N564, N572, N573, N590, N592; the rules are frontend
         docs/flows/the-plan.md §2.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from services import join_setup
from services import plan_flow as F
from services import way_in as W
from tests.test_plan_flow import USER, _Db, _rings

SAID = ["I'm a reporter on the politics desk. I read bills for a living.",
        "How to read a bill in five minutes: start with who pays.",
        "The young reporters on my desk.",
        "Last week, a bill changed my mind.",
        "A good story starts with one person."]
CARD = {"role": "Reporter on the politics desk", "about": "I read bills for a living.",
        "topics": ["reading bills", "politics"]}


@pytest.fixture
def db(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "PLAN_CONSENT_ENABLED", False)
    _rings(monkeypatch, calls=False, first_take=True)
    monkeypatch.setattr("services.speaker_memory.record", lambda *a, **k: None)
    monkeypatch.setattr(F, "_readings", lambda *a, **k: {})
    monkeypatch.setattr(F, "_read_first_take", lambda *a, **k: {"facts": {"topic": "Reading bills"},
                                                                 "deadline": None})
    monkeypatch.setattr(W, "_read_profile", lambda *a, **k: dict(CARD))
    d = _Db()
    F.state(d, USER, tz="UTC", first_name="Anna")
    plan = d.get_open_plan(USER)
    took = datetime.now(timezone.utc)
    d.update_plan(USER, plan["id"], {"created_at": (took - timedelta(minutes=5)).isoformat()})
    d.takes.rows = [{"id": "t1", "created_at": took.isoformat(), "arc_id": "arc-1", "take_index": 1}]
    return d


def _words_stored(db):
    db.clips["t1"] = [{"transcript": s, "duration_ms": 6000, "metrics": {"piece": {"slide_index": i}}}
                      for i, s in enumerate(SAID)]


def said(db, since=0):
    return [r["body"] for r in db.thread[since:]]


def step(db, **kw):
    return W.step(db, USER, first_name="Anna", **kw)


def answer(db, beat, **kw):
    return step(db, answer={"beat": beat, **kw})


def _processed(db):
    F.after_processing(db, {"recording_kind": "spoken", "user_id": USER, "session_id": "t1"}, b"")


def test_a_talk_the_wait_and_what_comes_next(db):
    start = len(db.thread)
    step(db, chat="artur")
    # The words are not stored yet: the choice does not wait for them.
    assert said(db, start) == ["While your feedback is being prepared, check what I heard.",
                               "What would you like to do here first?"]
    choice = db.thread[-1]["metadata"]
    assert choice["chips"] == ["Something else", "Learn from others", "Share what I know",
                               "Prepare a talk"]
    assert choice["multi"] is True and choice["send"] == "Send"

    _words_stored(db)
    answer(db, "choice", picked=["Prepare a talk"])
    assert said(db)[-3:] == ["Prepare a talk", "Here's how others will see you:", ""]
    card = db.thread[-1]["metadata"]["way_in_profile"]
    assert card == {"name": "Anna", "role": "Reporter on the politics desk",
                    "about": "I read bills for a living.",
                    "topics": ["Ask about reading bills", "Ask about politics"]}
    assert db.thread[-1]["metadata"]["chips"] == ["That's right", "Change it"]
    assert W.profile_card(db, USER) is None  # nobody sees it before "That's right"

    answer(db, "profile", picked="That's right")
    assert W.profile_card(db, USER)["role"] == "Reporter on the politics desk"
    assert said(db)[-1] == "When is it?"
    assert db.thread[-1]["metadata"]["chips"] == ["Pick a date", "No date yet"]

    day = date.today() + timedelta(days=20)
    answer(db, "talk_date", date=day.isoformat())
    tail = said(db)[-4:]
    assert tail[1] == ""  # the plan card
    assert db.thread[-3]["metadata"].get("plan_card") is True
    assert tail[2:] == ["You're set.",
                        "Your feedback is almost ready. It will appear at the top of this chat."]
    assert "links" not in db.thread[-2]["metadata"]  # not a sharer
    everything = said(db)
    assert everything.count("You're set.") == 1
    assert "When is your deadline?" not in everything and "You're all set. Here's your plan." not in everything
    assert "Do you accept it?" not in everything  # not in a team, not sharing
    view = F.state(db, USER, tz="UTC")["plan"]
    assert view["deadline"] == day.isoformat() and not view["deadline_given"]
    assert view["way_in"]["record_next"] is False

    _processed(db)
    assert said(db)[-1] == "Your feedback is ready."
    assert db.thread[-1]["metadata"]["chips"] == ["Open your feedback ›"]

    F.after_take(db, USER, first_name="Anna")
    assert said(db)[-1] == "Next, record Take 2 of your talk."
    assert F.state(db, USER, tz="UTC")["plan"]["way_in"]["record_next"] is True
    assert [a["kind"] for a in db.answers] == ["why", "audience", "key"]  # kept once


def test_change_it_asks_what_to_change_and_draws_the_card_again(db, monkeypatch):
    _words_stored(db)
    step(db)
    answer(db, "profile", picked="Change it")
    assert said(db)[-2:] == ["Change it", "Tell me what to change."]
    monkeypatch.setattr(W, "_read_profile", lambda *a, **k: {**CARD, "role": "Political reporter"})
    answer(db, "profile", said="I'm a political reporter")
    assert said(db)[-3:] == ["I'm a political reporter", "Here's how others will see you:", ""]
    assert db.thread[-1]["metadata"]["way_in_profile"]["role"] == "Political reporter"
    answer(db, "profile", picked="That's right")
    assert said(db)[-1] == "What would you like to do here first?"


def test_sharing_brings_the_join_questions_and_the_agreement(db, monkeypatch):
    questions = {"set": False}
    monkeypatch.setattr(join_setup, "is_set", lambda d, u: questions["set"])
    monkeypatch.setattr(join_setup, "begin", lambda d, u: d.thread.append(
        {"client_id": "js", "role": "bot", "body": join_setup.INTRO, "metadata": {}}) or {"started": True})
    _words_stored(db)
    step(db)
    answer(db, "profile", picked="That's right")
    answer(db, "choice", picked=["Share what I know"])
    assert said(db)[-1] == join_setup.INTRO  # the questions for people who join, in the wait
    assert "When is it?" not in said(db)

    questions["set"] = True  # "That's right" on their summary
    W.after_share(db, USER)
    assert said(db)[-2:] == ["", "Do you accept it?"]
    assert db.thread[-1]["metadata"]["chips"] == ["I agree"]
    answer(db, "agreement", picked="I agree")
    assert said(db)[-3:-1] == ["I agree", "You're set."]
    assert db.thread[-2]["metadata"]["links"] == ["Copy my link ›", "Your questions for people who join ›"]
    assert said(db).count("You're set.") == 1


def test_learning_after_the_walk_and_record_take_2_waits(db, monkeypatch):
    monkeypatch.setattr("services.assistants.on", lambda *_a, **_k: False)  # no chat builder
    _words_stored(db)
    step(db, known={"team": False})
    answer(db, "profile", picked="That's right")
    _processed(db)
    F.after_take(db, USER, first_name="Anna")  # the walk, opened before the choice
    assert F.state(db, USER, tz="UTC")["plan"]["way_in"]["record_next"] is True
    answer(db, "choice", picked=["Learn from others", "Something else"], said="Find a mentor")
    assert said(db)[-2:] == ["You're set.",
                             "Next, ask someone who knows. Tap + to start. "
                             "Tell me what you'd like to do, and I'll show you where."]
    assert "When is it?" not in said(db) and "Do you accept it?" not in said(db)
    # The choices not taken yet wait under it as taps (N604).
    assert db.thread[-1]["metadata"]["chips"] == ["Prepare a talk", "Share what I know"]
    answer(db, "else", said="Maybe a book club")
    assert said(db)[-1] == "Maybe a book club"


def test_something_else_after_the_walk_offers_taps_that_say_what_comes_next(db, monkeypatch):
    monkeypatch.setattr("services.assistants.on", lambda *_a, **_k: False)  # no chat builder
    _words_stored(db)
    step(db, known={"team": False})
    answer(db, "profile", picked="That's right")
    _processed(db)
    F.after_take(db, USER, first_name="Anna")
    answer(db, "choice", picked=["Something else"], said="Not sure yet")
    assert said(db)[-1] == "Tell me what you'd like to do, and I'll show you where."
    assert db.thread[-1]["metadata"]["chips"] == ["Prepare a talk", "Share what I know", "Learn from others"]
    answer(db, "else", picked="Share what I know")
    assert said(db)[-2:] == ["Share what I know",
                             "Next, set up your assistant, so people who join you are met your way."]
    assert db.thread[-1]["metadata"]["opens"] == "setup_chat"


def test_with_the_new_setup_sharing_points_to_your_chat(db):
    # N634 item 3 (after N632 item 5): with the chat builder, "Share what I
    # know" is followed by "Next, open Your chat below, and set it up.",
    # never "set up your assistant", and nothing opens the earlier setup;
    # the other signed sentences stay as they are.
    _words_stored(db)
    step(db, known={"team": False})
    answer(db, "profile", picked="That's right")
    _processed(db)
    F.after_take(db, USER, first_name="Anna")
    answer(db, "choice", picked=["Something else"], said="Not sure yet")
    assert db.thread[-1]["metadata"]["chips"] == ["Prepare a talk", "Share what I know", "Learn from others"]
    answer(db, "else", picked="Share what I know")
    assert said(db)[-2:] == ["Share what I know", "Next, open Your chat below, and set it up."]
    assert "opens" not in db.thread[-1]["metadata"]
    assert "set up your assistant" not in " ".join(said(db))
    row = W._after_walk_row(["Share what I know", "Prepare a talk"], ring=True)
    assert row[1] == "Next, record Take 2 of your talk. Next, open Your chat below, and set it up."
    assert "opens" not in row[2]


def test_a_take_with_nothing_heard_still_gets_its_plan(db):
    step(db, known={"team": False})
    answer(db, "choice", picked=["Learn from others"])
    assert "You're set." not in said(db)  # the card waits for the reading
    _processed(db)
    F.after_take(db, USER, first_name="Anna")
    assert said(db)[-2:] == ["You're set.", "Next, ask someone who knows. Tap + to start."]
    assert "Here's how others will see you:" not in said(db)
    assert F.state(db, USER, tz="UTC")["plan"]["way_in"]["record_next"] is True


def test_several_choices_say_the_talk_first_then_sharing():
    row = W._after_walk_row(["Share what I know", "Prepare a talk"])
    assert row[1] == ("Next, record Take 2 of your talk. Next, set up your assistant, "
                      "so people who join you are met your way.")
    assert row[2]["opens"] == "setup_chat"


def test_a_coachs_link_and_another_chat_meet_none_of_it(db):
    with pytest.raises(W.WayInError) as e:
        step(db, chat="kasia")
    assert e.value.code == "NOT_HERE"
    _words_stored(db)
    step(db, known={"coach_link": True})
    answer(db, "profile", picked="That's right")
    assert "What would you like to do here first?" not in said(db)
