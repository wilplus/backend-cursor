"""V4 B1.4b: the reached bar from blind coach answers (founder O4, V8 A,
V9 A; build plan D-ML-15)."""
from __future__ import annotations

import pytest

from services import v4_reached_bar as rb


def _coach(value, **kw):
    row = {"lane": "coach", "rater_id": "c1", "value": value, "blind": True}
    row.update(kw)
    return row


@pytest.mark.parametrize("row", [
    _coach("not_sure"), _coach("yes", lane="game_peer"), _coach("yes", self_report=True),
    _coach("yes", unrateable=True), _coach("yes", blind=False), _coach("yes", rater_id=None),
    _coach("yes", state_id="other"), None,
])
def test_only_blind_coach_answers_count(row):
    assert rb.answer_value(row) is None
