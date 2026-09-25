"""Helper words belong to the Slide (contract 13-14, founder 2026-09-25).

Q12 A: they belong to the Slide, in pick order, however a Take splits it.
Q14 A: picks in the same Take add up; the first pick LOCKED in a later Take
replaces the Slide's older set.
"""
from __future__ import annotations

from pathlib import Path

from services.data_purge_registry import DEPENDENCIES
from services.slide_helper_words import (
    lock,
    merge_recording_roots,
    pick,
    project,
    slide_of_part,
)

NOW = "2026-09-25T15:00:00+00:00"


def _phrases(rows):
    return [(r["phrase"], r["take_session_id"], bool(r["locked_at"]))
            for r in sorted(rows, key=lambda r: r["ord"])]


def _take1_both_paragraphs_locked():
    rows = pick([], take_id="t1", part_id="p1", phrase="nine days", now=NOW)
    rows = lock(rows, take_id="t1", part_id="p1", locked=True, now=NOW)
    rows = pick(rows, take_id="t1", part_id="p2", phrase="week one", now=NOW)
    return lock(rows, take_id="t1", part_id="p2", locked=True, now=NOW)


def test_picks_in_the_same_take_add_up_in_pick_order():
    assert _phrases(_take1_both_paragraphs_locked()) == [
        ("nine days", "t1", True), ("week one", "t1", True)]


def test_a_repick_on_the_same_paragraph_replaces_it_in_place():
    rows = pick([], take_id="t1", part_id="p1", phrase="nine days", now=NOW)
    rows = pick(rows, take_id="t1", part_id="p2", phrase="week one", now=NOW)
    rows = pick(rows, take_id="t1", part_id="p1", phrase="two days", now=NOW)
    assert _phrases(rows) == [("two days", "t1", False),
                              ("week one", "t1", False)]


def test_a_repick_after_the_lock_stays_locked():
    """The sheet re-saves the words after Lock when the text was edited on
    the lock screen; that must not quietly unlock the Slide's words."""
    rows = pick(_take1_both_paragraphs_locked(), take_id="t1", part_id="p1",
                phrase="nine days", now=NOW)
    assert _phrases(rows) == [("nine days", "t1", True),
                              ("week one", "t1", True)]


def test_a_later_take_pick_waits_for_its_lock_before_replacing():
    rows = pick(_take1_both_paragraphs_locked(), take_id="t3", part_id="p9",
                phrase="first week", now=NOW)
    # Picked but not locked: the locked Take-1 set still stands.
    assert [r["text"] for r in project(
        [dict(r, slide_index=3) for r in rows])] == ["nine days", "week one"]
    rows = lock(rows, take_id="t3", part_id="p9", locked=True, now=NOW)
    assert _phrases(rows) == [("first week", "t3", True)]


def test_locking_without_a_new_pick_keeps_the_older_set():
    rows = _take1_both_paragraphs_locked()
    assert lock(rows, take_id="t3", part_id="p9", locked=True, now=NOW) == rows


def test_clearing_a_pick_removes_only_that_paragraphs_words():
    rows = _take1_both_paragraphs_locked()
    rows = pick(rows, take_id="t1", part_id="p1", phrase=None, now=NOW)
    assert _phrases(rows) == [("week one", "t1", True)]
    assert [r["ord"] for r in rows] == [0]


def test_unlock_clears_that_paragraphs_words():
    rows = lock(_take1_both_paragraphs_locked(), take_id="t1",
                part_id="p2", locked=False, now=NOW)
    assert _phrases(rows) == [("nine days", "t1", True)]


def test_project_serves_locked_words_slide_by_slide():
    rows = [
        {"slide_index": 2, "ord": 1, "phrase": "b", "locked_at": NOW,
         "source_part_id": "p2"},
        {"slide_index": 2, "ord": 0, "phrase": "a", "locked_at": NOW,
         "source_part_id": "p1"},
        {"slide_index": 0, "ord": 0, "phrase": "open", "locked_at": None},
        {"slide_index": 1, "ord": 0, "phrase": "", "locked_at": NOW},
    ]
    assert project(rows) == [
        {"part_id": "p1", "slide_index": 2, "text": "a", "type": "flagship"},
        {"part_id": "p2", "slide_index": 2, "text": "b", "type": "flagship"},
    ]


def test_slide_rows_win_and_older_paragraph_roots_fill_the_rest():
    legacy = [
        {"part_id": "x", "slide_index": 1, "text": "old", "type": "flagship"},
        {"part_id": "y", "slide_index": 4, "text": "kept", "type": "flagship"},
    ]
    slide = [{"part_id": "p", "slide_index": 1, "text": "new",
              "type": "flagship"}]
    assert [r["text"] for r in merge_recording_roots(legacy, slide)] == [
        "new", "kept"]


def test_slide_of_part_needs_the_core_pairing():
    snap = {"payload": {
        "parts": [{"id": "P1"}, {"id": "p2"}],
        "pieces": [{"slide_index": 0}, {"slide_index": None}],
    }}
    assert slide_of_part(snap, "p1") == 0
    assert slide_of_part(snap, "p2") is None
    assert slide_of_part(snap, "p3") is None
    broken = {"payload": {"parts": [{"id": "p1"}], "pieces": []}}
    assert slide_of_part(broken, "p1") is None
    assert slide_of_part(None, "p1") is None


def test_the_table_is_registered_for_deletion_and_locked_down():
    assert "ideal_text_slide_helper_words" in {
        d.relation for d in DEPENDENCIES}
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "helper_words_belong_to_the_slide.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.ideal_text_slide_helper_words" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
