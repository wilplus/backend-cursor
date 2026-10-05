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

import pickle
from contextlib import ExitStack

import pytest

from services.authorized_provider import (
    _protected_call_scope,
    protected_provider_scope,
)
from services.processing_authorization import ProcessingAuthorizationError
from services.processing_stages import ProcessingStageRecorder


def _refusal() -> ProcessingAuthorizationError:
    return ProcessingAuthorizationError(
        "PROVIDER_PERMIT_INVALID", "No permit.", 403,
    )


def test_a_refusal_inside_the_provider_scope_keeps_its_type_and_code():
    refusal = _refusal()

    with pytest.raises(ProcessingAuthorizationError) as caught:
        with protected_provider_scope(object(), idempotency_prefix="take-1"):
            raise refusal

    assert caught.value is refusal
    assert (caught.value.code, caught.value.message, caught.value.status) == (
        "PROVIDER_PERMIT_INVALID", "No permit.", 403,
    )
    assert _protected_call_scope.get() is None, (
        "the scope outlived the refusal"
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


def test_the_interpreter_can_still_write_to_it():
    """The other writes a frozen instance refused: `ExitStack` setting
    `__context__` on an exception its callback raised, `add_note`, and the
    state restore when unpickling."""
    def refuse():
        raise _refusal()

    with pytest.raises(ProcessingAuthorizationError):
        with ExitStack() as stack:
            stack.callback(refuse)

    noted = _refusal()
    noted.add_note("take-1")
    assert noted.__notes__ == ["take-1"]

    restored = pickle.loads(pickle.dumps(_refusal()))
    assert (restored.code, restored.message, restored.status) == (
        "PROVIDER_PERMIT_INVALID", "No permit.", 403,
    )


@pytest.mark.parametrize("field", ["code", "message", "status"])
def test_the_fields_stay_read_only(field):
    refusal = _refusal()

    with pytest.raises(AttributeError):
        setattr(refusal, field, "changed")

    assert str(refusal) == "No permit."
