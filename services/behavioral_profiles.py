"""Canonical behavioral-profile labels used by the recommendation engine.

The four profiles model a student's failure/mastery mode for a single
session, based on acoustic telemetry. See `services.session_diagnosis` for
the classification waterfall that maps metrics to one of these labels.
"""

from __future__ import annotations

from enum import Enum


class BehavioralProfile(str, Enum):
    STRESSOR = "The Stressor"
    DRIFTER = "The Drifter"
    OVERWHELMED = "The Overwhelmed"
    MASTER = "The Master"


PROFILE_VALUES: frozenset[str] = frozenset(p.value for p in BehavioralProfile)


def is_valid_profile(value: object) -> bool:
    return isinstance(value, str) and value in PROFILE_VALUES
