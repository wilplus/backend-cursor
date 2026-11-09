"""
STORY    As a speaker, I want the app to turn my voice into a plan, so that
         each Take works on the one thing that will help most, in words,
         never a score.
OUTCOME
  O1  The plan is three levels of four Takes, twelve in all, with no
      practice days (N564 item 2).
  O2  The bar shows the level's name and its four marks, the done ones
      filled, never more than four and never a points total, a score or a
      percentage; after four Takes the next level starts, after the third
      level the set is done (N564 items 3 and 5).
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
      already had, else "Make it yours".
PROVES   O1 -> test_the_plan_is_three_levels_of_four_takes
         O2 -> test_the_bar_is_the_level_and_its_marks_never_points
         O3 -> test_the_level_comes_from_what_was_measured
         O4 -> test_the_key_line_first_and_at_most_three
         O5 -> test_the_ai_question_must_keep_its_template
         O6 -> test_dates_read_as_the_chat_writes_them
         O7 -> test_a_level_is_reached_on_its_own_check
WHY      The plan, built one to one with the prototype (founder 2026-10-26,
         N203, N204); a level moving on, N134 items 3 and 4, N209; the
         training as levels of four Takes, never points, N564; the rules
         are frontend docs/flows/the-plan.md §1.
"""
from datetime import date, datetime

from services import plan


def test_the_plan_is_three_levels_of_four_takes():
    assert (plan.LEVEL_TAKES, plan.SET_LEVELS, plan.SET_TAKES) == (4, 3, 12)
    for gone in ("journey", "given_deadline", "is_practice_day", "next_day_text", "level_days"):
        assert not hasattr(plan, gone)  # no practice days, no two months (N564 item 7)


def test_the_bar_is_the_level_and_its_marks_never_points():
    bar = plan.bar("pauses", 2, 1)
    assert bar == {"level": "pauses", "level_name": "Pauses that hold the room", "marks": 2,
                   "of": 4, "level_n": 1, "levels": 3}
    assert plan.bar("key_line", 9, 7)["marks"] == 4 and plan.bar("key_line", 9, 7)["level_n"] == 3
    assert plan.bar(None, None)["level_name"] == "Make it yours" and plan.bar(None, None)["marks"] == 0
    assert not set(bar) & {"points", "score", "percent", "total"}
    assert not plan.level_full(3) and plan.level_full(4)
    assert not plan.set_full(["pauses", "say_once"]) and plan.set_full(["pauses", "say_once", "key_line"])


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
    texts = ["Good morning, everyone.", "The window closes once the incumbents match our price."]
    assert plan.key_line_at(texts, "The window closes once incumbents match our price") == 1
    assert plan.key_line_at(texts, "We need two more hires") is None
