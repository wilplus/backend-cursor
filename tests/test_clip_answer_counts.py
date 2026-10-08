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


def _row(**over):
    row = {"state_id": "confidence", "lane": "coach", "self_report": False,
           "unrateable": False, "blind": True, "rater_id": "r1", "value": "yes"}
    row.update(over)
    return row


def test_a_non_blind_row_is_not_counted_like_the_quorum():
    """0411: a rating made after the rater saw the non-blind side counts for
    nothing in the quorum, so it counts for nothing here either."""
    assert cac.counted_answer(_row()) == "yes"
    assert cac.counted_answer(_row(blind=False)) is None
    assert lq.resolve([_row(blind=False)])["machine_votes"] == 0
    # A row from before 0411 (no column read) is blind by the column default.
    legacy = _row()
    legacy.pop("blind")
    assert cac.counted_answer(legacy) == "yes"


def test_historical_neutral_counts_as_not_sure():
    assert set(cac.NOT_SURE_VALUES) == set(lq.IDK_VALUES)
    assert cac.counted_answer(_row(value="neutral")) == "not_sure"
    assert cac.counted_answer(_row(value="not_sure")) == "not_sure"
    assert cac.counted_answer(_row(value="audio_unclear")) is None


def test_the_rest_of_the_filter_matches_the_database_function():
    assert cac.counted_answer(_row(lane="game_owner")) is None
    assert cac.counted_answer(_row(lane="bootstrap")) is None
    assert cac.counted_answer(_row(self_report=True)) is None
    assert cac.counted_answer(_row(unrateable=True)) is None
    assert cac.counted_answer(_row(rater_id=None)) is None
    assert cac.counted_answer(_row(state_id="warmth")) is None
    assert cac.counted_answer(_row(lane="game_peer", value="in_between")) == "in_between"


def test_the_sql_filter_carries_the_blind_rule_the_lock_and_neutral():
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations"
           / "answer_counts_per_clip_are_soft_label_data.sql").read_text()
    assert "AND label.blind IS NOT FALSE" in sql
    assert "value IN ('not_sure', 'neutral')" in sql
    assert "pg_advisory_xact_lock(hashtext(p_snippet_id::text))" in sql
    assert sql.index("pg_advisory_xact_lock") < sql.index("FROM public.confidence_labels label")
