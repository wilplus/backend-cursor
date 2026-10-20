"""
STORY    As a developer, I want a processing refusal raised inside a
         processing stage to reach callers as itself, so that the upload
         route answers with the refusal's own code, not a generic 500.
OUTCOME
  O1  A refusal raised inside a processing stage comes out as the same
      refusal, with its code intact.
PROVES   O1 -> test_a_refusal_inside_a_processing_stage_keeps_its_code
WHY      The refusal was a frozen object; the stage wrapper turned it into an
         unrelated error, and the upload route answered a generic 500.
"""
from __future__ import annotations

import pytest

from services.processing_authorization import ProcessingAuthorizationError
from services.processing_stages import ProcessingStageRecorder


def _refusal() -> ProcessingAuthorizationError:
    return ProcessingAuthorizationError(
        "PROVIDER_PERMIT_INVALID", "No permit.", 403,
    )


def test_a_refusal_inside_a_processing_stage_keeps_its_code():
    """The worker's audio download issues its permit inside `stage("upload")`."""
    recorder = ProcessingStageRecorder(
        database=None, owner_principal_id="", project_id="", take_id="take-1",
    )

    with pytest.raises(ProcessingAuthorizationError) as caught:
        with recorder.stage("upload"):
            raise _refusal()

    assert caught.value.code == "PROVIDER_PERMIT_INVALID"
