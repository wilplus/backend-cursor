"""The coach answers a practice recording the same five ways (0390; founder
2026-09-29, Q3/Q3a)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "migrations" / "a_coach_answers_practice_five_ways.sql").read_text()
FIVE = ("yes", "in_between", "no", "not_sure", "audio_unclear")


def test_the_column_takes_the_five_answers():
    for answer in FIVE:
        assert f"'{answer}'" in MIGRATION
    assert "coach_confidence_decision IS NULL OR" in MIGRATION


def test_the_route_accepts_them_and_nothing_else():
    from services.practice_adoption import ANSWERS
    assert set(ANSWERS) == set(FIVE)
    route = (ROOT / "routes" / "v2" / "coach.py").read_text()
    assert "selected_attempt_decision not in _FIVE_ANSWERS" in route


def test_the_db_writer_accepts_the_five():
    from services.db import DatabaseService

    class _Res:
        data = [{"id": "a"}]

    class _Q:
        def update(self, *_a, **_k): return self
        def eq(self, *_a, **_k): return self
        def execute(self): return _Res()

    class _Client:
        def table(self, _name): return _Q()

    svc = DatabaseService.__new__(DatabaseService)
    svc.client = _Client()
    for answer in FIVE:
        assert svc.set_confident_voice_practice_attempt_coach_decision(
            "p", "a", answer, "coach") == {"id": "a"}
    assert svc.set_confident_voice_practice_attempt_coach_decision(
        "p", "a", "maybe", "coach") is None
