"""
STORY      As the founder, I want the research screen's label figures to count
           exactly what the label ledger counts, so that "how often two humans
           agree" means what a settled label means (N111, B3).
OUTCOME    Only blind answers in the ledger's lanes count; a self-report, a
           legacy "peer" lane, a row with no lane and an answer given after
           seeing the clip's other side don't. Two "Not sure" answers are two
           labels, but no agreement and no kappa pair.
PROVES     test_the_figures_count_what_the_ledger_counts
WHY        LEARNING-AND-QUORUM §3 B3: the figures counted the "peer" lane and
           rows with no lane, and treated Not sure as a definite answer.
"""
from __future__ import annotations

from services.research_quorum import quorum


def test_the_figures_count_what_the_ledger_counts():
    rows = [
        {"snippet_id": "a", "rater_id": "c1", "lane": "coach", "value": "yes"},
        {"snippet_id": "a", "rater_id": "p1", "lane": "game_peer", "value": "yes"},
        {"snippet_id": "b", "rater_id": "c1", "lane": "coach", "value": "not_sure"},
        {"snippet_id": "b", "rater_id": "c2", "lane": "coach", "value": "not_sure"},
        {"snippet_id": "c", "rater_id": "o1", "lane": "coach", "value": "no", "self_report": True},
        {"snippet_id": "c", "rater_id": "x1", "lane": "peer", "value": "no"},
        {"snippet_id": "c", "rater_id": "x2", "value": "no"},
        {"snippet_id": "c", "rater_id": "x3", "lane": "coach", "value": "no", "blind": False},
    ]
    out = quorum(rows)
    assert out["labels"] == 4
    assert out["moments"] == 2
    assert out["moments_with_two_humans"] == 2
    assert out["two_human_agreement"] == 0.5
