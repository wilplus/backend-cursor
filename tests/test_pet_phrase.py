"""A phrase the speaker keeps using gets one other way to say it (WIL-26).

The speaker's outcomes: a phrase said three times in a Take is offered once,
on its last use, with the AI's alternative in place; the topic itself is
never treated as a habit; an alternative with a name, a number or the same
phrase again never reaches them; and with the switch off nothing happens.
"""
from __future__ import annotations

from services.pet_phrase import (
    PET_PHRASE_VERSION,
    clean_alternative,
    find_pet_phrase,
    generate_for_session,
    rewrite_row,
)

TAKE = ("At the end of the day, customers want speed. We tested three tools "
        "and at the end of the day only one shipped on time. The onboarding "
        "flow matters. The onboarding flow is slow. We rebuilt the onboarding "
        "flow. So at the end of the day we pick the fastest one.")
SLIDES = "Onboarding flow\nWhy it is slow"


def _stored(alternative: str) -> dict:
    return {"version": PET_PHRASE_VERSION, "phrase": "At the end of the day",
            "alternative": alternative}


def test_a_phrase_said_three_times_is_found_but_the_topic_is_not():
    assert find_pet_phrase(TAKE, SLIDES) == {
        "phrase": "At the end of the day", "uses": 3}
    twice = TAKE.replace("So at the end of the day we", "So we")
    assert find_pet_phrase(twice, SLIDES) is None


def test_its_last_use_is_offered_with_the_alternative_in_place():
    row = rewrite_row(TAKE, _stored("in the end"),
                      take_session_id="take-1", snippet_id="snip-1")
    assert row["quote"] == "So at the end of the day we pick the fastest one."
    assert row["proposed_text"] == "So in the end we pick the fastest one."
    assert TAKE[row["span"]["start"]:row["span"]["end"]] == row["quote"]
    assert row["feedback_family"] == "rewrite_clarity"
    assert row["why_key"] == "clarity"
    dropped = rewrite_row(TAKE, _stored(""), take_session_id="take-1",
                          snippet_id="snip-1")
    assert dropped["proposed_text"] == "So we pick the fastest one."


def test_no_offer_once_the_ideal_text_no_longer_has_the_habit():
    fewer = TAKE.replace("So at the end of the day we", "So we")
    assert rewrite_row(fewer, _stored("in the end"), take_session_id="take-1",
                       snippet_id="snip-1") is None


def test_an_alternative_with_a_name_a_number_or_the_same_phrase_is_refused():
    phrase = "at the end of the day"
    assert clean_alternative("in the end", phrase) == "in the end"
    assert clean_alternative("as Acme Corp says", phrase) is None
    assert clean_alternative("in 2024", phrase) is None
    assert clean_alternative("at the end of the day", phrase) is None


def test_switched_off_it_makes_no_call_and_stores_nothing():
    class NoDatabase:
        def __getattr__(self, name):
            raise AssertionError("the database was touched while switched off")

    assert generate_for_session("take-1", "arc-1", database=NoDatabase()) is False
