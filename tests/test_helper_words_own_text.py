"""The helper words are their own text (contract 14, founder 2026-09-25).

A Take rewrites the Paragraph from what was said; the locked helper words
persist through that rewrite until the user picks new ones. The position of
the words inside the Paragraph is only a render hint.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.db import _carried_root
from services.ideal_text_parts import root_span_in, serve

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / \
    "helper_words_are_their_own_text.sql"


@pytest.mark.parametrize("text,phrase,start,end,expected", [
    # the stored span still proves the words
    ("We cut it from nine days to two.", "nine days to two", 15, 31, (15, 31)),
    # stale span, words occur once in the new text → re-found
    ("From nine days to two, and shipping.", "nine days to two", 16, 32,
     (5, 21)),
    # said differently → no position, never guessed
    ("Onboarding used to take nine days; now two.", "nine days to two",
     16, 32, None),
    # twice → ambiguous → no position
    ("two to two to two", "to two", None, None, None),
    # nothing stored
    ("Any text.", None, None, None, None),
])
def test_root_span_in(text, phrase, start, end, expected):
    assert root_span_in(text, phrase, start, end) == expected


def test_a_rewritten_part_keeps_its_helper_words():
    previous = {
        "text": "We cut onboarding from nine days to two.",
        "root_phrase": "nine days to two",
        "root_start": 23, "root_end": 39,
        "root_selected_at": "2026-09-25T10:00:00Z",
    }
    carried = _carried_root(
        previous, "Onboarding used to take nine days. Now it takes two.")
    assert carried == {
        "root_phrase": "nine days to two",
        "root_start": None, "root_end": None,
        "root_selected_at": "2026-09-25T10:00:00Z",
    }


def test_a_part_without_helper_words_stays_without():
    assert _carried_root({"text": "x", "root_phrase": None}, "y") == {
        "root_phrase": None, "root_start": None, "root_end": None,
        "root_selected_at": None,
    }
    assert _carried_root(None, "y")["root_phrase"] is None


def test_serve_keeps_the_phrase_when_the_words_moved_on():
    rows = [{
        "id": "p1", "ord": 0,
        "text": "Onboarding used to take nine days. Now it takes two.",
        "locked_at": "2026-09-25T10:00:00Z",
        "root_phrase": "nine days to two", "root_start": 23, "root_end": 39,
    }]
    [part] = serve(rows)
    assert part["root_phrase"] == "nine days to two"
    assert "root_start" not in part and "root_end" not in part


def test_serve_refinds_a_moved_phrase():
    rows = [{
        "id": "p1", "ord": 0,
        "text": "From nine days to two, and shipping.",
        "root_phrase": "nine days to two", "root_start": 40, "root_end": 56,
    }]
    [part] = serve(rows)
    assert (part["root_start"], part["root_end"]) == (5, 21)


def test_migration_allows_a_phrase_without_a_span_and_is_idempotent():
    sql = MIGRATION.read_text()
    assert "DROP CONSTRAINT IF EXISTS ideal_text_part_root_span" in sql
    assert "(root_start IS NULL AND root_end IS NULL)" in sql
    # a phrase still needs its selection time
    assert "root_selected_at IS NOT NULL" in sql
