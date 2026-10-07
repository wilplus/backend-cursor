"""Answer counts per clip as soft-label data (V4 brief 1.7; D-ML-11): the
pure rule, the side write, and the two places it is made. The database half
is tests/test_answer_counts_per_clip_are_soft_label_data_postgres.py."""
from __future__ import annotations

from fractions import Fraction

from services import clip_answer_counts as cac
from services import label_quorum as lq


def test_in_between_counts_half_and_nobody_means_no_label():
    assert cac.soft_label(0, 0, 0) is None
    assert cac.soft_label(1, 0, 0) == 1
    assert cac.soft_label(0, 1, 0) == Fraction(1, 2)
    assert cac.soft_label(0, 0, 1) == 0
    assert cac.soft_label(1, 1, 1) == Fraction(1, 2)
    assert cac.soft_label(2, 1, 1) == Fraction(5, 8)


def test_the_quorum_keeps_its_humans_only_rule_beside_the_counts():
    """Q3: the ledger's quorum is untouched by the counts; the counts read
    exactly the lanes the quorum counts."""
    assert lq.MACHINE_VOTES == 0
    assert tuple(cac.LANES_COUNTED) == tuple(lq.QUORUM_LANES) == ("coach", "game_peer")
    assert cac.RULE_VERSION == "soft-label-v1"


class _Db:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    def refresh_clip_answer_counts(self, snippet_id):
        self.calls.append(snippet_id)
        if self.error:
            raise self.error
        return self.result


def test_refresh_is_a_side_write_that_never_raises():
    db = _Db(result={"snippet_id": "s", "perceptual_count": 1})
    assert cac.refresh(db, "s") == {"snippet_id": "s", "perceptual_count": 1}
    assert db.calls == ["s"]
    assert cac.refresh(_Db(error=RuntimeError("down")), "s") is None
    assert cac.refresh(_Db(result=None), "s") is None
    assert cac.refresh(object(), "s") is None
    assert cac.refresh(db, "") is None


def test_a_peer_label_and_a_coach_s_judgment_of_record_refresh_the_counts():
    """The two writers of a human vote call the refresh after the write
    (lend_your_ear._peer_label; the coach's _first_coach_rating). A
    reconsideration changes no ledger row, so it refreshes nothing."""
    import inspect

    from routes.v2 import coach
    from services import lend_your_ear

    peer = inspect.getsource(lend_your_ear._peer_label)
    assert "clip_answer_counts" in peer and "refresh(" in peer
    first = inspect.getsource(coach._first_coach_rating)
    assert "clip_answer_counts" in first and "refresh(" in first
    again = inspect.getsource(coach._reconsider_coach_rating)
    assert "clip_answer_counts" not in again
