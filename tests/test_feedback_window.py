"""The window of three (founder lock 2026-09-30, task 11; contract 24b)."""
from services.feedback_window import window_rows


def _m(id_, start, tier, score, *, practise=True, status=None):
    row = {"id": id_, "source": "confident_voice",
           "feedback_family": "confident_voice", "span": {"start": start},
           "bookmark_tier": tier, "status": status}
    if practise and tier == "weak":
        row["practice_exercise"] = {"exercise_id": "x"}
    row["_score"] = score
    return row


def _para(row):
    return row["span"]["start"] // 100


def _score(row):
    return row.get("_score")


def test_the_score_never_reaches_the_served_row():
    rows = [_m("c1", 0, "confident", 0.9)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs=set(),
                      score_of=lambda r: 0.9)
    assert "candidate_score" not in out[0] and "delivery_band" not in out[0]


# F1 Repair Plan Phase 1 (founder lock 2026-09-30, Q2 A: "never three of one
# colour").
