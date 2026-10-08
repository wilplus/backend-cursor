"""V4 B1.5: each pick learns whether its paragraph rose (build plan D-ML-10;
founder P5, V10b A, V11 B, V12 A; migration 0451)."""
from __future__ import annotations

import pathlib

from services import v4_pick_outcomes as po
from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"


def test_only_a_clear_rise_counts():
    assert po.outcome(0.40, 0.46) == "rose"
    assert po.outcome(0.40, 0.45) == "did_not_rise"
    assert po.outcome(0.40, 0.30) == "did_not_rise"
    assert po.outcome(None, 0.5) == "not_measured"
    assert (po.MARGIN, po.MARGIN_VERSION) == (0.05, "rise-margin-v0-placeholder")


def test_a_moment_belongs_to_the_one_paragraph_all_its_clips_are_bound_to():
    frame = {"blocks": [
        {"block_id": "b1", "snippet_ids": ["c1", "c2"]},
        {"block_id": "b2", "snippet_ids": ["c3", "c4"]},
        {"block_id": "b3", "snippet_ids": ["c5"]},
        {"block_id": "b4", "snippet_ids": ["c6"]},
    ]}
    bound = {"pieces": [
        {"snippet_id": "c1", "part_id": P1}, {"snippet_id": "c2", "part_id": P1},
        {"snippet_id": "c3", "part_id": P1}, {"snippet_id": "c4", "part_id": P2},
        {"snippet_id": "c5"},
        {"snippet_id": "c6", "part_id": P1}, {"snippet_id": "c6", "part_id": P2},
    ]}
    assert po.paragraph_map(frame, bound) == [
        {"block_id": "b1", "paragraph_id": P1},
        {"block_id": "b2", "paragraph_id": None},   # straddles: slide backup
        {"block_id": "b3", "paragraph_id": None},   # unproven: slide backup
        {"block_id": "b4", "paragraph_id": None},   # a clip in two: none
    ]
    assert po.paragraph_map(frame, None)[0] == {"block_id": "b1", "paragraph_id": None}


class _Db:
    def __init__(self, error=None):
        self.error, self.maps, self.computed = error, [], []

    def record_v4_moment_paragraphs(self, take, mapping):
        if self.error:
            raise self.error
        self.maps.append((take, mapping))
        return {"outcome": "mapped"}

    def compute_v4_pick_outcomes(self, take):
        if self.error:
            raise self.error
        self.computed.append(take)
        return {"outcome": "computed"}


def test_the_side_writes_never_raise(monkeypatch):
    import services.ideal_text_parts as parts
    monkeypatch.setattr(parts, "bind_pieces_to_parts", lambda doc, **_: doc)
    frame = {"blocks": [{"block_id": "b1", "snippet_ids": ["c1"]}]}
    doc = {"pieces": [{"snippet_id": "c1", "part_id": P1}]}
    db = _Db()
    po.map_paragraphs(db, "t", frame, doc, served_text="", slide_regions={}, parts=lambda: [])
    assert db.maps == [("t", [{"block_id": "b1", "paragraph_id": P1}])]
    assert po.map_paragraphs(_Db(RuntimeError("x")), "t", frame, doc, served_text="",
                             slide_regions={}, parts=lambda: []) is None
    assert po.map_paragraphs(db, "t", frame, doc, served_text="", slide_regions={},
                             parts=lambda: 1 / 0) is None
    assert po.compute(_Db(RuntimeError("x")), "t") is None
    assert po.compute(db, "t") == {"outcome": "computed"} and db.computed == ["t"]


def test_the_rise_share_counts_measured_picks_of_the_kinds_asked():
    rows = [
        {"outcome": "rose", "v3_picks": ["rewrite"]},
        {"outcome": "did_not_rise", "v3_picks": ["exercise"]},
        {"outcome": "rose", "v3_picks": ["praise"]},
        {"outcome": "not_measured", "v3_picks": ["rewrite"]},
        {"outcome": "rose", "v3_picks": []},
    ]
    assert po.rise_share(rows, ["rewrite", "exercise"]) == 0.5
    assert po.rise_share(rows, ["nothing"]) is None


def test_wiring_map_before_the_read_and_outcomes_after_it():
    changes = (ROOT / "services" / "ideal_text_changes.py").read_text()
    assert changes.index("map_paragraphs(db, _arm_sid") < changes.index("enqueue_read(_arm_sid)")
    job = (ROOT / "services" / "willfidence.py").read_text()
    assert job.index("record_v4_willfidence_reads(take") < job.index("compute(db, take)")


def test_the_outcomes_go_with_both_takes():
    rows = {d.code: d for d in DEPENDENCIES}
    assert rows["v4_moment_paragraphs"].disposition == "delete"
    assert rows["v4_pick_outcomes"].selector_column == "take_session_id"
    assert rows["v4_pick_outcomes_next"].selector_column == "next_take_session_id"


def test_no_route_reads_the_outcomes():
    for path in (ROOT / "routes").rglob("*.py"):
        text = path.read_text()
        assert "v4_pick_outcomes" not in text and "v4_moment_paragraphs" not in text, path
