"""The Voice Album's Machine Yes is the clip's own machine read (founder
2026-10-05, Q5; N45): the read that colours a bar green and chooses the
follow-up, not the legacy star lane (switched off by default, so nothing
could enter). A clip that cannot be read is never a No.
"""
from __future__ import annotations

from unittest import mock

from services import judgement_follow_up as jfu
from services import voice_album as va


def test_the_album_asks_the_clip_read():
    with mock.patch.object(jfu, "clip_machine_read", return_value="confident") as read:
        assert va._machine_reads_confident(object(), "take-1", "snip-1") is True
    read.assert_called_once()
    assert read.call_args.args[1:] == ("take-1", "snip-1")


def test_weak_and_unknown_are_not_a_yes():
    for value in ("weak", "unknown"):
        with mock.patch.object(jfu, "clip_machine_read", return_value=value):
            assert va._machine_reads_confident(object(), "t", "s") is False


def test_an_unread_clip_is_neither_yes_nor_no():
    with mock.patch.object(jfu, "clip_machine_read", return_value=None):
        assert va._machine_reads_confident(object(), "t", "s") is None


def test_an_unread_clip_marks_the_refresh_incomplete():
    complete = [True]
    with mock.patch.object(jfu, "clip_machine_read",
                           side_effect=lambda _db, take, snip:
                           {"a": "confident", "b": None, "c": "weak"}[snip]):
        out = va._machine_yes(object(), {"a": "t1", "b": "t1", "c": "t1"}, complete)
    assert out == {"a"}
    assert complete == [False]


def test_clip_machine_read_is_the_follow_up_read():
    with mock.patch.object(jfu, "_clip_read", return_value={"read": "confident"}):
        assert jfu.clip_machine_read(object(), "t", "s") == "confident"
    with mock.patch.object(jfu, "_clip_read", return_value=None):
        assert jfu.clip_machine_read(object(), "t", "s") is None


def test_the_star_lane_is_no_longer_read():
    source = va.__file__
    with open(source) as handle:
        text = handle.read()
    assert "get_moment_suggestions_by_arc" not in text
