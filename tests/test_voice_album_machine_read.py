"""The Voice Album's Machine Yes is the clip's own machine read (founder
2026-10-05, Q5; N45): the read that colours a bar green and chooses the
follow-up, not the legacy star lane (switched off by default, so nothing
could enter). A clip that cannot be read is never a No.
"""
from __future__ import annotations

from unittest import mock

from services import judgement_follow_up as jfu
from services.voice_album import refresh_voice_album
from tests.test_voice_album import _coach, _Db

CLIPS = ("sn-confident", "sn-weak", "sn-unknown", "sn-unread")


def _album(clips):
    """Every clip has the user's Yes and the coach's Yes on Take t1, and an
    older entry is already in the Album."""
    return _Db(
        routes=[{"snippet_id": c, "response": "yes", "slide_index": 0}
                for c in clips],
        sessions=[{"id": "t1"}],
        snips={"t1": [{"id": c} for c in clips]},
        conf={c: _coach("yes") for c in clips},
        album=[{"snippet_id": "sn-old"}],
    )


def test_machine_yes_is_the_exact_clips_own_read():
    reads = {"sn-confident": "confident", "sn-weak": "weak",
             "sn-unknown": "unknown", "sn-unread": None}
    asked = []

    def read(_db, take_session_id, snippet_id):
        asked.append((take_session_id, snippet_id))
        return reads[snippet_id]

    with mock.patch.object(jfu, "clip_machine_read", side_effect=read):
        database = _album(CLIPS)
        refresh_voice_album("arc-1", database=database)
        # Only a confident read is a Machine Yes; weak and unknown are not.
        assert [e["snippet_id"] for e in database.inserted] == ["sn-confident"]
        # L3: each clip's read is asked of that exact Take and clip.
        assert sorted(asked) == sorted(("t1", c) for c in CLIPS)
        # An unread clip is never a No: it marks the refresh incomplete, so
        # nothing is removed on its account.
        assert database.deleted == []

        # Once every read completes, the refresh removes what no longer holds.
        database = _album(CLIPS[:3])
        refresh_voice_album("arc-1", database=database)
        assert [d["snippet_id"] for d in database.deleted] == ["sn-old"]


def test_clip_machine_read_is_the_follow_up_read():
    with mock.patch.object(jfu, "_clip_read", return_value={"read": "confident"}):
        assert jfu.clip_machine_read(object(), "t", "s") == "confident"
    with mock.patch.object(jfu, "_clip_read", return_value=None):
        assert jfu.clip_machine_read(object(), "t", "s") is None

