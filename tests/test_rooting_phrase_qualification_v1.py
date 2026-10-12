from pathlib import Path

import pytest

from services.rooting_phrase_qualification_v1 import (
    controls_for_state,
)

ROOT = Path(__file__).resolve().parents[1]
P2_SQL = (
    ROOT
    / "migrations/add_mlc3_fresh_offer_and_paired_review_restoration.sql"
).read_text()


@pytest.mark.parametrize(
    ("state", "primary", "secondary", "coverage"),
    [
        (
            "eligible_direct",
            "lock_and_make_rooting_phrase",
            "lock_only",
            "ready",
        ),
        (
            "eligible_after_rerecord",
            "make_rooting_phrase",
            "not_now",
            "ready",
        ),
        ("pending_recording", "practice_this_phrase", None, "pending"),
        (
            "pending_owner_alignment_confirmation",
            "confirm_phrase_anchors_point",
            "reject_for_slide",
            "pending",
        ),
        ("blocked_semantic_mismatch", None, None, "pending"),
    ],
)
def test_qualitative_controls_never_surface_scores(
    state, primary, secondary, coverage
):
    controls = controls_for_state(state)
    assert (controls.primary_action, controls.secondary_action) == (primary, secondary)
    assert controls.coverage_state == coverage
    assert "score" not in repr(controls).lower()


def test_paired_review_preserves_blindness_and_five_distinct_answers():
    for answer in (
        "prefer_left",
        "prefer_right",
        "same",
        "not_sure",
        "audio_unusable",
    ):
        assert answer in P2_SQL
    assert "known_prior_context" in P2_SQL
    assert "exercise-reviewer-context:" in P2_SQL
    assert "chronology_revealed" in P2_SQL
    assert "EXERCISE_SERVICE_EXPOSURE_DISABLED" in P2_SQL
