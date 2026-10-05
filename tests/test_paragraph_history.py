"""The history behind a Paragraph's bookmark (contract 16, founder 2026-09-25)."""
from __future__ import annotations

from pathlib import Path

from services.data_purge_registry import DEPENDENCIES
from services.paragraph_history import (
    history_for_part,
    slide_history,
    with_accepted_corrections,
)


def _version(n, blocks, slides, at=None):
    return {"version": n, "text": "\n\n".join(blocks), "created_at": at,
            "document": {"paragraphs": [{"slide_index": s} for s in slides]}}


VERSIONS = [
    _version(1, ["A one.", "B one."], [0, 1], "t1"),
    # Take 2 did not speak slide 1: its words are unchanged.
    _version(2, ["A two.", "B one."], [0, 1], "t2"),
    _version(3, ["A two.", "B three, first.", "B three, second."], [0, 1, 1],
             "t3"),
]


def test_a_slide_history_lists_only_the_versions_where_its_words_changed():
    h = slide_history(VERSIONS, [], 1)
    assert [(v["version"], v["paragraphs"]) for v in h["versions"]] == [
        (1, ["B one."]),
        (3, ["B three, first.", "B three, second."]),
    ]


def test_helper_word_sets_are_listed_in_order():
    log = [{"phrases": ["nine days"], "created_at": "a"},
           {"phrases": ["first week"], "created_at": "b"}]
    assert slide_history([], log, 0)["helper_words"] == [
        {"phrases": ["nine days"], "at": "a"},
        {"phrases": ["first week"], "at": "b"}]


def test_a_version_without_a_slide_map_is_left_out_never_guessed():
    old = {"version": 1, "text": "Whole text.", "document": None}
    broken = _version(2, ["A.", "B."], [0])  # map does not tile the text
    assert slide_history([old, broken], [], 0)["versions"] == []


def test_history_for_part_resolves_the_slide_from_the_published_core():
    class Db:
        def get_ideal_text_document_core(self, arc_id, user_id):
            return {"payload": {"parts": [{"id": "p0"}, {"id": "p1"}],
                                "pieces": [{"slide_index": 0},
                                           {"slide_index": 1}]}}

        def list_ideal_text_versions(self, arc_id):
            return VERSIONS

        def list_slide_helper_words_log(self, arc_id, user_id, slide):
            assert slide == 1
            return []

        def list_practice_adoptions(self, arc_id, user_id, slide):
            return [{"before_text": "B one.", "after_text": "B practised.",
                     "created_at": "p"}]

        def list_accepted_rewrite_revisions(self, arc_id, user_id, part_id):
            assert part_id == "p1"
            return []

    h = history_for_part(Db(), "arc", "user", "p1")
    assert h["slide_index"] == 1 and len(h["versions"]) == 2
    assert {v["kind"] for v in h["versions"]} == {"take"}
    assert h["practice"] == [{"before": "B one.", "after": "B practised.",
                              "at": "p"}]
    assert history_for_part(Db(), "arc", "user", "unknown") is None


def test_the_log_table_is_registered_and_locked_down():
    assert "ideal_text_slide_helper_words_log" in {
        d.relation for d in DEPENDENCIES}
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "helper_words_keep_a_history.sql").read_text()
    assert "ENABLE ROW LEVEL SECURITY" in sql


def test_each_version_names_its_take_when_the_snapshot_says_so():
    tagged = _version(1, ["A one."], [0])
    tagged["document"]["take_index"] = 2
    untagged = _version(2, ["A two."], [0])
    untagged["document"]["take_index"] = True
    h = slide_history([tagged, untagged], [], 0)
    assert [v["take_index"] for v in h["versions"]] == [2, None]


# AN ACCEPTED CORRECTION IS ITS OWN ROW (founder 2026-10-05, N48.1; C11).

def _take(n, at):
    return {"kind": "take", "version": n, "take_index": n,
            "paragraphs": [f"Take {n} words."], "at": at}


def test_an_accepted_correction_sits_between_the_takes_by_time():
    takes = [_take(1, "2026-10-05T09:00:00+00:00"),
             _take(2, "2026-10-05T11:00:00+00:00")]
    merged = with_accepted_corrections(takes, [
        {"text": "Nobody trusted the figures.",
         "created_at": "2026-10-05T10:00:00.123456+00:00"}])
    assert [row["kind"] for row in merged] == [
        "take", "accepted_correction", "take"]
    assert merged[1] == {"kind": "accepted_correction", "version": None,
                         "take_index": None,
                         "paragraphs": ["Nobody trusted the figures."],
                         "at": "2026-10-05T10:00:00.123456+00:00"}
    # The Take rows are untouched and keep their order.
    assert merged[0] is takes[0] and merged[2] is takes[1]


def test_corrections_after_the_last_take_come_last_in_their_order():
    takes = [_take(1, "2026-10-05T09:00:00Z")]
    merged = with_accepted_corrections(takes, [
        {"text": "First fix.", "created_at": "2026-10-05T10:00:00Z"},
        {"text": "Second fix.", "created_at": "2026-10-05T10:05:00Z"}])
    assert [row["paragraphs"] for row in merged] == [
        ["Take 1 words."], ["First fix."], ["Second fix."]]


def test_a_correction_with_no_words_or_no_time_is_left_out_never_guessed():
    takes = [_take(1, "2026-10-05T09:00:00Z")]
    assert with_accepted_corrections(takes, [
        {"text": "  ", "created_at": "2026-10-05T10:00:00Z"},
        {"text": "No time.", "created_at": None},
        {"text": "Bad time.", "created_at": "yesterday"},
        "junk"]) == takes
    assert with_accepted_corrections(takes, None) == takes


def test_history_for_part_reads_this_paragraphs_accepted_corrections():
    class Db:
        def get_ideal_text_document_core(self, arc_id, user_id):
            return {"payload": {"parts": [{"id": "p0"}],
                                "pieces": [{"slide_index": 0}]}}

        def list_ideal_text_versions(self, arc_id):
            one = _version(1, ["A one."], [0], "2026-10-05T09:00:00+00:00")
            one["document"]["take_index"] = 1
            two = _version(2, ["A two."], [0], "2026-10-05T11:00:00+00:00")
            two["document"]["take_index"] = 2
            return [one, two]

        def list_slide_helper_words_log(self, arc_id, user_id, slide):
            return []

        def list_practice_adoptions(self, arc_id, user_id, slide):
            return []

        def list_accepted_rewrite_revisions(self, arc_id, user_id, part_id):
            assert (arc_id, user_id, part_id) == ("arc", "user", "p0")
            return [{"text": "A corrected.",
                     "created_at": "2026-10-05T10:00:00+00:00"}]

    h = history_for_part(Db(), "arc", "user", "p0")
    assert [(v["kind"], v["take_index"], v["paragraphs"])
            for v in h["versions"]] == [
        ("take", 1, ["A one."]),
        ("accepted_correction", None, ["A corrected."]),
        ("take", 2, ["A two."])]
