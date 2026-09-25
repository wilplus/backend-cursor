"""The history behind a Paragraph's bookmark (contract 16, founder 2026-09-25)."""
from __future__ import annotations

from pathlib import Path

from services.data_purge_registry import DEPENDENCIES
from services.paragraph_history import history_for_part, slide_history


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

    h = history_for_part(Db(), "arc", "user", "p1")
    assert h["slide_index"] == 1 and len(h["versions"]) == 2
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
