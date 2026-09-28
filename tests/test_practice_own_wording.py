"""A practice is held to the shown words unless the coach's shared exercise
asks for different wording (founder 2026-09-28, decision 14B)."""
from __future__ import annotations

from pathlib import Path

from routes.v2.user_sessions import _coach_asked_own_wording


def test_the_shown_words_are_required_by_default():
    assert _coach_asked_own_wording({}) is False
    assert _coach_asked_own_wording({"coach_shared_exercise": None}) is False
    assert _coach_asked_own_wording(
        {"coach_shared_exercise": {"title": "Pause"}}) is False


def test_a_coach_exercise_asking_for_new_words_lifts_the_check():
    assert _coach_asked_own_wording(
        {"coach_shared_exercise": {"own_wording": True}}) is True
    # Only an explicit True counts.
    assert _coach_asked_own_wording(
        {"coach_shared_exercise": {"own_wording": "yes"}}) is False


def test_the_coach_route_records_the_flag_on_the_shared_exercise():
    source = (Path(__file__).resolve().parents[1]
              / "routes" / "v2" / "coach.py").read_text()
    assert 'body.get("own_wording") is True' in source
    assert 'snapshot["own_wording"] = True' in source
