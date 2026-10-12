"""Which open moments reach the page (founder lock 2026-10-12)."""
from services.feedback_window import window_rows


def _m(id_, para, tier="standard", *, practise=False, status=None):
    return {"id": id_, "source": "confident_voice",
            "feedback_family": "confident_voice",
            "span": {"start": para * 100}, "bookmark_tier": tier,
            "practice_prompt": practise, "status": status}


def _para(row):
    return row["span"]["start"] // 100


def test_green_moments_and_the_exercise_show_nothing_else_open_does():
    rows = [_m("g1", 0, "confident"), _m("plain", 1), _m("g2", 2, "confident"),
            _m("ex", 3, practise=True), _m("done", 4, status="approved"),
            _m("g3", 5, "confident")]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs={5})
    assert [r["id"] for r in out] == ["g1", "g2", "ex", "done"]
    assert all("candidate_score" not in r and "delivery_band" not in r for r in out)


def test_a_take_with_nothing_picked_still_shows_two_moments():
    rows = [_m("a", 0), _m("b", 1), _m("c", 2)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs=set())
    assert [r["id"] for r in out] == ["a", "b"]
