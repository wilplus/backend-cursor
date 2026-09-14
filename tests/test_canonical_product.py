import pytest

from services.canonical_product import EvidenceLocator, ProcessingState


def test_evidence_locator_requires_exact_project_take_and_position():
    locator = EvidenceLocator(
        project_id="project-1",
        take_id="take-1",
        slide_index=2,
        paragraph_index=3,
        evidence_span={"start": 4, "end": 9},
    )
    assert locator.slide_index == 2


@pytest.mark.parametrize("slide,paragraph", [(-1, 0), (0, -1)])
def test_evidence_locator_rejects_negative_positions(slide, paragraph):
    with pytest.raises(ValueError):
        EvidenceLocator("p", "t", slide, paragraph, {"start": 0, "end": 1})


def test_take_processing_states_are_one_closed_contract():
    assert {state.value for state in ProcessingState} == {
        "processing", "ready", "failed",
    }
