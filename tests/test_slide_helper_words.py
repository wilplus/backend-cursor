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
    phrase_in_version,
    pick,
    project,
    slide_of_part,
    version_of_take,
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
    rows = pick(_take1_both_paragraphs_locked(), take_id="t3", part_id="p2",
                phrase="first week", now=NOW)
    # Picked but not locked: the locked Take-1 set still stands.
    assert [r["text"] for r in project(
        [dict(r, slide_index=3) for r in rows])] == ["nine days", "week one"]
    rows = lock(rows, take_id="t3", part_id="p2", locked=True, now=NOW)
    # The lock replaces THAT paragraph's earlier words; p1's stay (F1 Repair
    # Plan Phase 5: a lock on one paragraph never drops another's words).
    assert _phrases(rows) == [("nine days", "t1", True),
                              ("first week", "t3", True)]


def test_a_lock_on_one_paragraph_keeps_a_siblings_words():
    rows = pick(_take1_both_paragraphs_locked(), take_id="t3", part_id="p9",
                phrase="first week", now=NOW)
    rows = lock(rows, take_id="t3", part_id="p9", locked=True, now=NOW)
    assert _phrases(rows) == [("nine days", "t1", True),
                              ("week one", "t1", True),
                              ("first week", "t3", True)]


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


def test_slide_rows_win_for_their_paragraph_and_older_roots_fill_the_rest():
    legacy = [
        {"part_id": "x", "slide_index": 1, "text": "sibling", "type": "flagship"},
        {"part_id": "P", "slide_index": 1, "text": "old", "type": "flagship"},
        {"part_id": "y", "slide_index": 4, "text": "kept", "type": "flagship"},
        {"slide_index": 1, "text": "no part", "type": "flagship"},
    ]
    slide = [{"part_id": "p", "slide_index": 1, "text": "new",
              "type": "flagship"}]
    # Phase 5: a Slide row covers its own paragraph, so a sibling's older
    # words on the same Slide are no longer hidden; a legacy row naming no
    # paragraph is still covered by its Slide.
    assert [r["text"] for r in merge_recording_roots(legacy, slide)] == [
        "sibling", "new", "kept"]


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


# Helper words from any earlier Take (founder lock 2026-09-30, B4, D5, Q3).

HISTORY = {"versions": [
    {"take_index": 1, "paragraphs": ["We cut  onboarding.", "Nine days to two."]},
    {"take_index": 2, "paragraphs": ["We cut it down.", "Two days now."]},
]}


def test_a_take_s_version_is_found_by_its_number():
    assert version_of_take(HISTORY, 1)["paragraphs"][1] == "Nine days to two."
    assert version_of_take(HISTORY, 3) is None
    assert version_of_take(HISTORY, "1") is None
    assert version_of_take(HISTORY, True) is None
    assert version_of_take({}, 1) is None


def test_the_words_must_be_exact_words_of_that_one_version():
    v1 = version_of_take(HISTORY, 1)["paragraphs"]
    assert phrase_in_version("nine days", v1) is None  # case is the speaker's
    assert phrase_in_version("Nine days", v1) == "Nine days"
    assert phrase_in_version("cut   onboarding", v1) == "cut onboarding"
    # One Take, one phrase (Q3): words of Take 2 are not words of Take 1.
    assert phrase_in_version("Two days", v1) is None
    assert phrase_in_version("**Nine**", v1) is None
    assert phrase_in_version("", v1) is None
    assert phrase_in_version("Nine", None) is None


def test_the_route_takes_words_from_a_take_and_clears_the_paragraph_span():
    source = (Path(__file__).resolve().parents[1]
              / "routes/v2/explore_ideal_text.py").read_text()
    start = source.index("def v2_explore_set_part_helper_words_from_take")
    end = source.index("@v2_bp.route", start)
    route = source[start:end]
    assert "version_of_take(history, body.get(\"take_index\"))" in route
    assert "phrase_in_version(body.get(\"phrase\")" in route
    assert "phrase=None" in route
    assert "record_pick(db, arc_id, user_id, str(part_id)" in route


def test_the_four_word_cap_holds_on_the_server():
    # Founder lock 2026-09-30, B3; F1 Repair Plan Phase 5.
    from services.slide_helper_words import HELPER_WORDS_MAX, within_cap
    assert HELPER_WORDS_MAX == 4
    assert within_cap("one")
    assert within_cap("one two three four")
    assert not within_cap("one two three four five")
    assert not within_cap("")
    assert not within_cap(None)


def test_every_save_route_checks_the_cap():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    explore = (root / "routes/v2/explore_ideal_text.py").read_text()
    assert explore.count("within_cap(") == 2
    practice = (root / "services/practice_adoption.py").read_text()
    assert "within_cap(words)" in practice
