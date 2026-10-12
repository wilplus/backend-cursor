"""A refusal raised inside a ``@contextmanager`` reaches its caller as itself.

`ProcessingAuthorizationError` was a frozen dataclass. When it was raised
inside `protected_provider_scope` (or `ProcessingStageRecorder.stage`, the
worker's download step), contextlib re-raised it and set `__traceback__` on
the way out, the frozen instance refused that write, and the caller got
`dataclasses.FrozenInstanceError` in its place. Nothing was sent, so it
failed closed, but every `except ProcessingAuthorizationError` around these
scopes was skipped: the upload route answered a generic 500 instead of the
refusal's own code.
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
