"""One list of learning surfaces, eight long, seven with packets.

Founder 2026-09-29, decision 2 (audit G-5; the 29 Sep report's item Q7).
The registry has held eight rows since 0313; three Python modules each kept
their own literal set of seven. They now import the one list, and the reason
the eighth carries no packet is written beside it.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services import dataset_releases, learning_exposures, mlc2_foundation
from services.learning_surfaces import (
    EXERCISE_ADEQUACY_SURFACE,
    LEARNING_SURFACE_ORDER,
    LEARNING_SURFACES,
    NO_PACKET_REASON,
    PACKET_SURFACES,
)

ROOT = Path(__file__).parents[1]
SEVEN = {
    "confidence_classification", "correction_generation",
    "coach_comment_generation", "praise_generation", "praise_selection",
    "correction_selection", "ideal_text_generation",
}


def test_the_registry_order_names_eight_with_module_8_last():
    assert len(LEARNING_SURFACE_ORDER) == 8
    assert LEARNING_SURFACE_ORDER[-1] == EXERCISE_ADEQUACY_SURFACE
    assert set(LEARNING_SURFACE_ORDER[:7]) == SEVEN
    assert LEARNING_SURFACES == SEVEN | {EXERCISE_ADEQUACY_SURFACE}
    assert PACKET_SURFACES == SEVEN


def test_the_three_modules_read_the_one_list():
    assert mlc2_foundation.LEARNING_SURFACES is LEARNING_SURFACES
    assert dataset_releases.LEARNING_SURFACES is LEARNING_SURFACES
    assert learning_exposures.LEARNING_SURFACES is PACKET_SURFACES


def test_no_module_keeps_its_own_literal_set_of_the_seven():
    """A literal set naming all seven surfaces outside the shared module is
    the drift this list exists to end."""
    offenders = []
    for path in sorted((ROOT / "services").glob("*.py")):
        if path.name == "learning_surfaces.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                names = {
                    element.value for element in node.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                if SEVEN <= names:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def test_module_8_is_refused_a_packet_with_its_reason():
    from unittest.mock import Mock

    with pytest.raises(learning_exposures.LearningExposureError) as refused:
        learning_exposures.prepare_presentation(
            database=Mock(),
            owner_principal_id="o", project_id="p", take_id="t",
            learning_surface=EXERCISE_ADEQUACY_SURFACE,
            actor_role="owner", actor_id="a",
            complete_candidate_set=[{"candidate_key": "x"}],
            selected_candidate={"candidate_key": "x"},
            visible_payload={"quote": "shown"}, versions={"v": "1"},
        )
    assert str(refused.value) == NO_PACKET_REASON
    assert "confident_voice_exercise_exposures" in NO_PACKET_REASON


def test_the_release_builder_accepts_module_8_as_a_surface_name():
    """Naming is not authorizing: the constants stay False and the epoch
    CHECK stays; a manifest may now say which surface it is for."""
    from config import Config

    assert Config.MLC2_DATASET_RELEASES_ENABLED is False
    assert EXERCISE_ADEQUACY_SURFACE in dataset_releases.LEARNING_SURFACES


def test_the_foundation_canonicalises_module_8_and_types_its_payload():
    assert mlc2_foundation.canonical_surface_id(EXERCISE_ADEQUACY_SURFACE) == \
        EXERCISE_ADEQUACY_SURFACE
    assert mlc2_foundation.PAYLOAD_TYPES[EXERCISE_ADEQUACY_SURFACE] == \
        "exercise_adequacy_event"
    assert set(mlc2_foundation.PAYLOAD_TYPES) == LEARNING_SURFACES
