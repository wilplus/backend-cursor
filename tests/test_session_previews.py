"""Pure contracts for admin session-preview normalization and schema drift."""
from types import SimpleNamespace

import pytest

from services.db import (
    _session_preview_row,
    _sessions_with_schema_fallback,
)


def test_preview_prefers_sniper_wpm_and_normalizes_legacy_duration():
    session = {
        "id": "s1",
        "recording_1_id": "r1",
        "student_self_rating": "4",
        "self_rating_submitted_at": "2026-08-22T10:00:00Z",
    }
    recordings = {"r1": {
        "transcription_text": "x" * 400,
        "words_per_minute": 121,
        "filler_words_count": {"total": 3},
        "duration": 12.25,
    }}
    sniper = {"s1": {"wpm": 137.26, "pause_ms": 420}}

    row = _session_preview_row(
        session,
        tuple(session),
        recordings,
        sniper,
    )

    assert row["words_per_minute"] == 137.3
    assert row["wpm"] == 137.3
    assert row["duration_seconds"] == 12.2
    assert row["filler_words_count"] == 3
    assert row["student_rating_1_10"] == 4
    assert row["self_rating_label"] == "4"
    assert len(row["recording_preview"]["transcription_preview"]) == 300


def test_preview_marks_submitted_rating_without_value_as_skipped():
    row = _session_preview_row(
        {
            "id": "s1",
            "recording_1_id": None,
            "self_rating_submitted_at": "2026-08-22T10:00:00Z",
        },
        ("id", "recording_1_id", "self_rating_submitted_at"),
        {},
        {},
    )

    assert row["self_rating_skipped"] is True
    assert row["self_rating_label"] == "Skipped"


class _Query:
    def __init__(self):
        self.selects = []
        self.attempt = 0

    def select(self, columns):
        self.selects.append(columns)
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        self.attempt += 1
        if self.attempt == 1:
            raise RuntimeError(
                "42703 column v2_sessions.task_score does not exist")
        return SimpleNamespace(data=[{"id": "s1"}])


class _Client:
    def __init__(self, query):
        self.query = query

    def table(self, _name):
        return self.query


def test_schema_fallback_retries_without_the_missing_column():
    query = _Query()
    database = SimpleNamespace(
        client=_Client(query),
        _v2_sessions_missing_columns=set(),
    )

    rows, fields = _sessions_with_schema_fallback(
        database, "u1", 50, ["id", "task_score"],
    )

    assert rows == [{"id": "s1"}]
    assert fields == ("id",)
    assert database._v2_sessions_missing_columns == {"task_score"}
    assert query.selects == ["id, task_score", "id"]


def test_schema_fallback_does_not_hide_non_schema_errors():
    class BrokenQuery(_Query):
        def execute(self):
            raise RuntimeError("connection timed out")

    database = SimpleNamespace(
        client=_Client(BrokenQuery()),
        _v2_sessions_missing_columns=set(),
    )

    with pytest.raises(RuntimeError, match="timed out"):
        _sessions_with_schema_fallback(database, "u1", 50, ["id"])
