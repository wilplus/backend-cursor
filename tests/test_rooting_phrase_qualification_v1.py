"""
STORY    As a speaker, I want each rooting-phrase qualification state to give
         me clear next steps and never a score, so that I am never shown a
         number.
OUTCOME
  O1  Each ready/pending state maps to its own named actions and coverage.
  O2  Every blocked, stale or invalidated state offers no action and reads
      "pending" - never a dead end that exposes why the machine refused.
  O3  Never-1: no state's controls carry a score or a number.
PROVES   O1 -> test_each_state_gives_its_next_steps
         O2 -> test_blocked_states_offer_no_action
         O3 -> test_each_state_gives_its_next_steps, test_blocked_states_offer_no_action
WHY      Paired-review blindness (Never-2) lives in SQL behind a disabled
         exposure flag; a grep of the migration could not prove it, so it is
         not claimed here.
"""
import re
from typing import get_args

import pytest

from services.rooting_phrase_qualification_v1 import (
    RoutingState,
    controls_for_state,
)

ACTIONABLE = {
    "eligible_direct": ("lock_and_make_rooting_phrase", "lock_only", "ready"),
    "eligible_after_rerecord": ("make_rooting_phrase", "not_now", "ready"),
    "pending_recording": ("practice_this_phrase", None, "pending"),
    "pending_owner_alignment_confirmation": (
        "confirm_phrase_anchors_point", "reject_for_slide", "pending"),
}
BLOCKED = sorted(set(get_args(RoutingState)) - set(ACTIONABLE))


def _assert_no_score(controls):
    text = repr(controls).lower()
    assert "score" not in text
    assert not re.search(r"\d", text)


@pytest.mark.parametrize(("state", "expected"), sorted(ACTIONABLE.items()))
def test_each_state_gives_its_next_steps(state, expected):
    controls = controls_for_state(state)
    assert (controls.primary_action, controls.secondary_action,
            controls.coverage_state) == expected
    _assert_no_score(controls)


@pytest.mark.parametrize("state", BLOCKED)
def test_blocked_states_offer_no_action(state):
    controls = controls_for_state(state)
    assert (controls.primary_action, controls.secondary_action,
            controls.coverage_state) == (None, None, "pending")
    _assert_no_score(controls)
