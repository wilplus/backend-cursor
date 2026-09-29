"""exercise-more-confident-v1 in Python, and its wiring (0388).

The database writes the result; this pins that the Python statement of the
rule matches the migration's, that the coach's save triggers it without ever
failing on it, and that nothing surfaces it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.practice_more_confident import (
    machine_leg, outcome, record_after_coach_decision,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "migrations" / "a_practice_sounds_more_confident.sql").read_text()


@pytest.mark.parametrize("original, attempt, expected", [
    (-0.4, 0.35, "higher"),
    (0.1, 0.1000001, "higher"),
    (0.3, 0.3, "not_higher"),
    (0.3, -0.2, "not_higher"),
    (None, 0.2, "unmeasurable"),
    (0.2, None, "unmeasurable"),
    (True, 0.2, "unmeasurable"),
])
def test_machine_leg(original, attempt, expected):
    assert machine_leg(original, attempt) == expected


@pytest.mark.parametrize("machine, coach, expected", [
    ("higher", "yes", "helped"),
    ("higher", "no", "not_helped"),
    ("not_higher", "yes", "not_helped"),
    ("not_higher", "no", "not_helped"),
    ("unmeasurable", "yes", "pending"),
    ("higher", None, "pending"),
    ("higher", "maybe", "pending"),
])
def test_outcome(machine, coach, expected):
    assert outcome(machine, coach) == expected


def test_the_migration_states_the_same_rule():
    assert "WHEN v_attempt > v_original THEN 'higher'" in MIGRATION
    assert "WHEN v_machine = 'unmeasurable' OR v_coach IS NULL THEN 'pending'" in MIGRATION
    assert "WHEN v_machine = 'higher' AND v_coach = 'yes' THEN 'helped'" in MIGRATION
    assert "CHECK (is_label = false)" in MIGRATION
    assert "CHECK (serves_user = false)" in MIGRATION


class _Db:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def record_practice_more_confident(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("PRACTICE_MORE_CONFIDENT_NOT_FOUND")
        return {"outcome": "helped"}


def test_recorded_after_the_coach_decides():
    database = _Db()
    assert record_after_coach_decision(database, "p", "a") == {"outcome": "helped"}
    assert database.calls == [{"practice_id": "p", "attempt_id": "a"}]


def test_a_failure_never_fails_the_coach_save():
    assert record_after_coach_decision(_Db(fail=True), "p", "a") is None


def test_the_coach_route_records_it_after_saving_the_judgment():
    route = (ROOT / "routes" / "v2" / "coach.py").read_text()
    saved = route.index("set_confident_voice_practice_attempt_coach_decision(")
    recorded = route.index("record_after_coach_decision(\n", saved)
    assert saved < recorded


def test_nothing_serves_it():
    for path in (ROOT / "routes").rglob("*.py"):
        text = path.read_text()
        assert "practice_more_confident_outcomes" not in text, path
        assert not re.search(r"\boutcome\b.*more_confident", text), path
