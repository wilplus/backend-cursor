"""Q3 (founder 2026-09-29): the coach's practice door opens on any saved
answer but Audio unclear.

Both doors (the practice review and the exercise request) share one
predicate, so they cannot drift apart again.
"""
from routes.v2 import coach


def test_the_four_answers_open_the_door():
    for value in ("yes", "in_between", "no", "not_sure"):
        assert coach._practice_door_open(
            {"rating_value": value, "rating_unrateable": False}), value


def test_audio_unclear_and_no_answer_keep_it_shut():
    assert not coach._practice_door_open(
        {"rating_value": "audio_unclear", "rating_unrateable": False})
    assert not coach._practice_door_open(
        {"rating_value": "yes", "rating_unrateable": True})
    assert not coach._practice_door_open(
        {"rating_value": None, "rating_unrateable": False})
    assert not coach._practice_door_open({})
    assert not coach._practice_door_open(None)


def test_both_doors_use_the_one_predicate():
    source = open(coach.__file__, encoding="utf-8").read()
    # The practice review, the exercise request, and (2026-09-30) the
    # `_moment_gate` shared by the answer draft and the named errors.
    assert source.count("if not _practice_door_open(") == 3
    assert 'not in ("yes", "no")' not in source
