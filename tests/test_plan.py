"""
STORY    As a speaker with an event coming, I want the app to turn my
         deadline and my voice into a plan, so that each practice works on
         the one thing that will help most, in words, never a score.
OUTCOME
  O1  A deadline three weeks away gives three practices a week, nine in
      all; two weeks or less gives every day; no date gives two months.
  O2  The practice count reads the Takes done plus one and never passes the
      total; the next practice day is a weekday name, or "tomorrow".
  O3  The level comes from what was measured today, strongest first: a key
      line said faster than the rest gives "Let your key line land"; with
      nothing measured it is "Make it yours", never a guess.
  O4  The key line is always the first follow-up, and never more than three;
      a fact already said is not asked again, a named worry still is.
  O5  The AI's question is kept only in its signed template's shape;
      anything else falls back to the plain template, and a slot the AI
      left unfilled ("{who they will speak to}") never reaches the speaker:
      not in the question, not in the facts, not on the plan card.
  O6  The dates read as the chat writes them ("14 November", "Sat 14 Nov",
      "Tuesday 27 October, 10:00").
  O7  A Take reaches its level when the check that picked it no longer
      fires; the next level is the next thing heard, never one the plan
      already had, else "Make it yours"; a level runs a week, or two in a
      longer plan, and a plan of two weeks or less keeps one level.
PROVES   O1 -> test_the_deadline_sets_the_journey
         O2 -> test_practice_count_and_next_day
         O3 -> test_the_level_comes_from_what_was_measured
         O4 -> test_the_key_line_first_and_at_most_three
         O5 -> test_the_ai_question_must_keep_its_template
         O6 -> test_dates_read_as_the_chat_writes_them
         O7 -> test_a_level_is_reached_on_its_own_check
WHY      The plan, built one to one with the prototype (founder 2026-10-26,
         N203, N204); a level moving on, N134 items 3 and 4, N209; the rules
         are frontend docs/flows/the-plan.md §1.
"""
from datetime import date, datetime

from services import plan

SAT = date(2026, 10, 24)


def test_the_deadline_sets_the_journey():
    j = plan.journey(SAT, date(2026, 11, 14))
    assert (j.every_day, j.total) == (False, 9)
    close = plan.journey(SAT, date(2026, 11, 3))
    assert close.every_day and close.total == 10
    given = plan.given_deadline(SAT)
    assert given == date(2026, 12, 19)
    assert plan.journey(SAT, given).total == 24


def test_practice_count_and_next_day():
    assert plan.practice_number(0, 9) == 1
    assert plan.practice_number(1, 9) == 2
    assert plan.practice_number(20, 9) == 9
    deadline = date(2026, 11, 14)
    assert plan.next_day_text(SAT, deadline, (1, 3, 5), False) == "Monday"
    assert plan.next_day_text(SAT, deadline, (1, 3, 5), True) == "tomorrow"
    assert plan.next_day_text(date(2026, 11, 13), deadline, (1, 3, 5), False) is None
    assert plan.is_practice_day(date(2026, 10, 26), deadline, (1, 3, 5), False)
    assert not plan.is_practice_day(date(2026, 10, 27), deadline, (1, 3, 5), False)
    assert not plan.is_practice_day(deadline, deadline, (1, 3, 5), True)


def test_the_level_comes_from_what_was_measured():
    assert plan.pick_level({"wpm": 150, "key_wpm": 170}).level == "key_line"
    assert plan.pick_level({"wpm": 150, "key_wpm": 152, "pauses_per_min": 2}).level == "pauses"
    assert plan.pick_level({"pauses_per_min": 9, "fillers_per_min": 6}).level == "say_once"
    assert plan.pick_level({"pauses_per_min": 9, "flat_pitch": True}).level == "voice_moves"
    assert plan.pick_level({}).level == "make_it_yours"
    assert plan.level_name("key_line") == "Let your key line land"
    assert plan.today_one("pauses").startswith("Today, one thing: a short pause")
    assert plan.why_line("key_line", "the board").startswith(
        "It's the sentence you want the board to remember")


def test_the_key_line_first_and_at_most_three():
    assert plan.next_plain_bank([], {}) == "key"
    assert plan.next_plain_bank(["key"], {"audience": "the board"}) == "length"
    assert plan.next_plain_bank(["key", "length"], {"audience": "x", "worry": "my voice"}) == "worry"
    assert plan.next_plain_bank(["key", "audience", "length"], {}) is None


def test_the_ai_question_must_keep_its_template():
    key = {"bank": "key", "question": "If the board remembers one sentence from you, "
           "what is it? Say it the way you'll say it.", "opener": None}
    assert plan.fitted_question(key, [])["question"].startswith("If the board")
    assert plan.who_from_key_question(key["question"]) == "the board"
    assert plan.fitted_question({**key, "bank": "audience"}, []) is None
    assert plan.fitted_question({"bank": "length", "question": "Tell me more!"}, ["key"]) is None
    assert plan.fitted_question(key, ["key"]) is None
    worry = {"bank": "worry", "question": "What worries you most about it?",
             "opener": "You said you don't want to cry halfway through."}
    assert plan.fitted_question(worry, ["key"])["opener"].startswith("You said")
    assert plan.fitted_ack("Thank you. On 14 November you'll ask the board for two more hires.")
    assert plan.fitted_ack("Great job!") is None
    assert plan.fitted_ack("Thank you. You scored 7/10.") is None
    unfilled = {"bank": "key", "question": "If {who they will speak to} remembers one sentence "
                "from you, what is it? Say it the way you'll say it.", "opener": None}
    assert plan.fitted_question(unfilled, []) is None  # the plain template is said instead
    assert plan.who_from_key_question(unfilled["question"]) is None
    assert "who" not in plan.clean_facts({"who": "{who they will speak to}"})
    assert plan.why_line("key_line", "{who they will speak to}").startswith(
        "It's the sentence you want them to remember")


def test_dates_read_as_the_chat_writes_them():
    assert plan.fmt_day(date(2026, 11, 14)) == "14 November"
    assert plan.fmt_short(date(2026, 11, 14)) == "Sat 14 Nov"
    assert plan.fmt_long(date(2026, 10, 26)) == "Monday 26 October"
    assert plan.fmt_when(datetime(2026, 10, 27, 10, 0)) == "Tuesday 27 October, 10:00"
    assert plan.fmt_when_short(datetime(2026, 10, 27, 10, 0)) == "Tue 27 Oct, 10:00"
    assert plan.days_text((1, 3, 5)) == "Mon, Wed, Fri"
    assert plan.days_text((5, 1, 3), joined=True) == "Mon, Wed and Fri"


def test_a_level_is_reached_on_its_own_check():
    assert plan.reached("key_line", {"wpm": 150, "key_wpm": 170}) is False
    assert plan.reached("key_line", {"wpm": 150, "key_wpm": 152}) is True
    assert plan.reached("key_line", {"wpm": 150}) is None  # the key line wasn't said
    assert plan.reached("pauses", {"pauses_per_min": 9, "mean_pause_ms": 600}) is True
    assert plan.reached("make_it_yours", {"wpm": 150}) is None
    heard = {"pauses_per_min": 2, "fillers_per_min": 6}
    assert plan.next_level(heard, ["key_line"]) == "pauses"
    assert plan.next_level(heard, ["key_line", "pauses"]) == "say_once"
    assert plan.next_level({}, ["pauses"]) == "make_it_yours"
    assert plan.level_days(SAT, date(2026, 11, 14)) == 7
    assert plan.level_days(SAT, date(2026, 12, 19)) == 14
    assert plan.level_days(SAT, date(2026, 11, 3)) is None
    texts = ["Good morning, everyone.", "The window closes once the incumbents match our price."]
    assert plan.key_line_at(texts, "The window closes once incumbents match our price") == 1
    assert plan.key_line_at(texts, "We need two more hires") is None
