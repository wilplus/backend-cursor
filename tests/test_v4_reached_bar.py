"""V4 B1.4b: the reached bar from blind coach answers (founder O4, V8 A,
V9 A; build plan D-ML-15)."""
from __future__ import annotations

import pathlib

import pytest

from services import v4_reached_bar as rb

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _coach(value, **kw):
    row = {"lane": "coach", "rater_id": "c1", "value": value, "blind": True}
    row.update(kw)
    return row


def test_answers_count_yes_one_in_between_half_no_zero():
    assert rb.answer_value(_coach("yes")) == 1.0
    assert rb.answer_value(_coach("in_between")) == 0.5
    assert rb.answer_value(_coach("no")) == 0.0


@pytest.mark.parametrize("row", [
    _coach("not_sure"), _coach("yes", lane="game_peer"), _coach("yes", self_report=True),
    _coach("yes", unrateable=True), _coach("yes", blind=False), _coach("yes", rater_id=None),
    _coach("yes", state_id="other"), None,
])
def test_only_blind_coach_answers_count(row):
    assert rb.answer_value(row) is None


def test_the_bar_is_where_coaches_say_yes_about_seven_in_ten():
    # Above 0.6 coaches say Yes 8 in 10; from 0.4 to 0.6, 5 in 10; below, never.
    pairs = []
    for i in range(20):
        pairs.append((0.6 + i * 0.01, 1.0 if i % 5 else 0.0))
    for i in range(20):
        pairs.append((0.4 + i * 0.01, 1.0 if i % 2 else 0.0))
    for i in range(20):
        pairs.append((0.1 + i * 0.01, 0.0))
    report = rb.calibrate(pairs)
    assert report["status"] == "calibrated"
    assert report["share_at_or_above"] >= rb.TARGET_SHARE
    assert 0.4 <= report["bar"] <= 0.6
    above = [v for level, v in pairs if level >= report["bar"]]
    assert sum(above) / len(above) >= 0.7
    lower = max(level for level, _ in pairs if level < report["bar"])
    below_too = [v for level, v in pairs if level >= lower]
    assert sum(below_too) / len(below_too) < 0.7


def test_in_between_counts_half_in_the_share():
    pairs = [(0.9, 0.5)] * 20 + [(0.8, 1.0)] * 20
    assert rb.calibrate(pairs)["bar"] == 0.8  # 0.75 at or above 0.8 ... and 0.75 overall
    pairs = [(0.9, 0.5)] * 30 + [(0.8, 1.0)] * 10
    assert rb.calibrate(pairs)["status"] == "placeholder"  # 0.625 never reaches 0.7


def test_too_few_answers_keep_the_placeholder():
    report = rb.calibrate([(0.9, 1.0)] * (rb.MIN_ANSWERS - 1))
    assert (report["bar"], report["status"], report["reason"]) == (
        0.6, "placeholder", "not_enough_answers")


def test_the_bar_in_force_is_the_versioned_placeholder():
    assert (rb.BAR, rb.BAR_VERSION, rb.PLACEHOLDER) == (
        0.6, "reached-bar-v0-placeholder", 0.6)


def test_answers_meet_their_moment_through_the_frame():
    reads = [{"take_session_id": "t", "block_id": "b1", "s": 0.8, "w": 0.5},
             {"take_session_id": "t", "block_id": "b2", "s": None, "w": 0.5}]
    frames = {"t": {"blocks": [{"block_id": "b1", "snippet_ids": ["c1", "c2"]},
                               {"block_id": "b2", "snippet_ids": ["c3"]}]}}
    labels = [_coach("yes", snippet_id="c1"), _coach("no", snippet_id="c2"),
              _coach("yes", snippet_id="c3"), _coach("yes", snippet_id="cx")]
    assert rb.pairs_from(reads, frames, labels) == [(0.4, 1.0), (0.4, 0.0)]


def test_no_route_or_payload_carries_the_bar():
    for path in (ROOT / "routes").rglob("*.py"):
        assert "v4_reached_bar" not in path.read_text(), path
