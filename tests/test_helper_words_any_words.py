"""Helper words: up to eight, any words of the paragraph, read in the order
said (founder 2026-10-15)."""
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
