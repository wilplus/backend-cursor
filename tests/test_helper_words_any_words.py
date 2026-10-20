"""
STORY    As a speaker, I want to pick up to eight helper words from my paragraph,
         in the order I said them, so that my cues match my talk.
OUTCOME
  O1  Words picked apart from each other are saved (without a position).
  O2  Words out of order, or words I never said, are refused.
  O3  Eight words are accepted; a ninth is refused.
  O4  Words picked apart are also accepted against an earlier Take's text.
PROVES   O1 -> test_words_picked_apart_save_without_a_span
         O2 -> test_words_out_of_order_or_not_said_are_refused
         O3 -> test_eight_words_is_the_cap
         O4 -> test_an_earlier_take_takes_words_picked_apart
WHY      Founder 2026-10-15.
"""
from services.rooting_phrase import validate_rooting_phrase
from services.slide_helper_words import phrase_in_version

TEXT = "Last year we lost three clients because nobody called them back."


def test_words_picked_apart_save_without_a_span():
    saved = validate_rooting_phrase(TEXT, "three · nobody called", None, None)
    assert saved == {"text": "three · nobody called", "start": None, "end": None}


def test_words_out_of_order_or_not_said_are_refused():
    assert validate_rooting_phrase(TEXT, "nobody · three", None, None) is None
    assert validate_rooting_phrase(TEXT, "three · doubled", None, None) is None


def test_eight_words_is_the_cap():
    eight = "Last year we lost three clients because nobody"
    assert validate_rooting_phrase(TEXT, eight, 0, len(eight)) is not None
    nine = "Last year we lost three clients because nobody called"
    assert validate_rooting_phrase(TEXT, nine, 0, len(nine)) is None


def test_an_earlier_take_takes_words_picked_apart():
    assert phrase_in_version("year · them back", [TEXT]) == "year · them back"
