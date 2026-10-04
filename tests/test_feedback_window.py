"""The window of three (founder lock 2026-09-30, task 11; contract 24b)."""
from services.feedback_window import choose_open_moments, window_rows


def _m(id_, start, tier, score, *, practise=True, status=None):
    row = {"id": id_, "source": "confident_voice",
           "feedback_family": "confident_voice", "span": {"start": start},
           "bookmark_tier": tier, "status": status}
    if practise and tier == "weak":
        row["practice_exercise"] = {"exercise_id": "x"}
    row["_score"] = score
    return row


def _note(id_, start, family="rewrite_clarity", status=None):
    return {"id": id_, "feedback_family": family, "span": {"start": start},
            "status": status}


def _para(row):
    return row["span"]["start"] // 100


def _score(row):
    return row.get("_score")


def test_three_or_fewer_open_moments_all_show():
    rows = [_m("a", 0, "confident", 0.5), _m("b", 100, "weak", -0.4),
            _m("c", 200, "standard", None)]
    assert [r["id"] for r in choose_open_moments(rows, _score)] == ["a", "b", "c"]


def test_the_two_ends_first_then_the_farther_side():
    rows = [_m("c1", 0, "confident", 0.8), _m("c2", 100, "confident", 0.5),
            _m("w1", 200, "weak", -0.9), _m("w2", 300, "weak", -0.4),
            _m("c3", 400, "confident", 0.2), _m("w3", 500, "weak", -0.1)]
    chosen = [r["id"] for r in choose_open_moments(rows, _score)]
    # highest confident, lowest weak, then the next farthest: w2 (0.4) is
    # farther below than c2 (0.5) is above? No: 0.5 > 0.4, so c2.
    assert chosen == ["c1", "c2", "w1"]


def test_never_three_of_one_colour():
    rows = [_m("c1", 0, "confident", 0.9), _m("c2", 100, "confident", 0.8),
            _m("c3", 200, "confident", 0.7), _m("w1", 300, "weak", -0.1)]
    chosen = [r["id"] for r in choose_open_moments(rows, _score)]
    assert chosen == ["c1", "c2", "w1"]


def test_one_side_only_shows_at_most_two():
    rows = [_m("c1", 0, "confident", 0.9), _m("c2", 100, "confident", 0.8),
            _m("c3", 200, "confident", 0.7), _m("c4", 300, "confident", 0.6)]
    assert [r["id"] for r in choose_open_moments(rows, _score)] == ["c1", "c2"]


def test_weak_without_a_practise_and_unread_fill_only_what_the_ends_leave():
    rows = [_m("c1", 0, "confident", 0.9), _m("u1", 100, "standard", None),
            _m("w0", 200, "weak", -0.5, practise=False),
            _m("u2", 300, "standard", None)]
    chosen = [r["id"] for r in choose_open_moments(rows, _score)]
    assert chosen == ["c1", "u1", "w0"]


def test_a_saved_paragraph_leaves_the_window_and_frees_its_slot():
    rows = [_m("c1", 0, "confident", 0.9), _m("c2", 100, "confident", 0.8),
            _m("w1", 200, "weak", -0.9), _m("w2", 300, "weak", -0.4),
            _note("n1", 0), _note("n2", 300)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs={0},
                      score_of=_score)
    ids = [r["id"] for r in out]
    # Paragraph 0 is saved: its moment and its note are gone; the slot it
    # frees goes to w2, and w2's note rides along.
    assert ids == ["c2", "w1", "w2", "n2"]


def test_answered_rows_always_stay_and_a_withheld_moment_takes_its_note():
    rows = [_m("done", 0, "confident", 0.9, status="approved"),
            _m("c1", 100, "confident", 0.8), _m("c2", 200, "confident", 0.7),
            _m("w1", 300, "weak", -0.9), _m("w2", 400, "weak", -0.2),
            _note("n-done", 0, status="dismissed"), _note("n-w2", 400)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs=set(),
                      score_of=_score)
    ids = [r["id"] for r in out]
    assert ids == ["done", "c1", "c2", "w1", "n-done"]


def test_the_score_never_reaches_the_served_row():
    rows = [_m("c1", 0, "confident", 0.9)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs=set(),
                      score_of=lambda r: 0.9)
    assert "candidate_score" not in out[0] and "delivery_band" not in out[0]


# F1 Repair Plan Phase 1 (founder lock 2026-09-30, Q2 A: "never three of one
# colour").

def test_three_greens_show_two_even_with_only_three_moments():
    rows = [_m("c1", 0, "confident", 0.9), _m("c2", 100, "confident", 0.8),
            _m("c3", 200, "confident", 0.7)]
    assert [r["id"] for r in choose_open_moments(rows, _score)] == ["c1", "c2"]


def test_unscored_coloured_moments_still_keep_the_colour_cap():
    rows = [_m("c1", 0, "confident", None), _m("c2", 100, "confident", None),
            _m("c3", 200, "confident", None), _m("u1", 300, "standard", None)]
    assert [r["id"] for r in choose_open_moments(rows, _score)] == ["c1", "c2", "u1"]


def test_unscored_greens_and_oranges_fill_two_and_one():
    rows = [_m("w1", 0, "weak", None), _m("w2", 100, "weak", None),
            _m("w3", 200, "weak", None), _m("c1", 300, "confident", None)]
    assert [r["id"] for r in choose_open_moments(rows, _score)] == ["w1", "w2", "c1"]
