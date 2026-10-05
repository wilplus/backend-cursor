"""The upload's typed refusals reach their handler as themselves.

`RecordingRejected`, `RecordingIntakeError` and `RecordingPersistenceError`
were frozen dataclasses. Python writes to an exception after it is raised:
contextlib sets `__traceback__` when it re-raises through a
`@contextmanager`, `ExitStack` sets `__context__`, `add_note` sets
`__notes__`, and unpickling restores `__dict__` with setattr. A frozen
instance refuses each write, so the caller would get
`dataclasses.FrozenInstanceError` and `v2_lab_create_recording`'s typed
`except` clauses would be skipped for a generic 500. None of the three is
raised inside a context manager today; these tests keep it that way should
one be wrapped later.
"""
from __future__ import annotations

import pickle
from contextlib import ExitStack, contextmanager
from typing import Any, Callable

import pytest

from services.lab_recording_gate import RecordingRejected
from services.lab_recording_intake import RecordingIntakeError
from services.lab_recording_persistence import RecordingPersistenceError

_GATE = {"ok": False, "reason": "no_speech", "speech_seconds": 0.0}

# (build, fields): build() makes a fresh instance; fields are what it carries.
_ERRORS: dict[str, tuple[Callable[[], Exception], dict[str, Any]]] = {
    "RecordingRejected": (
        lambda: RecordingRejected(_GATE),
        {"gate": _GATE},
    ),
    "RecordingIntakeError": (
        lambda: RecordingIntakeError("AUDIO_ONLY", "audio only", 415),
        {"code": "AUDIO_ONLY", "message": "audio only", "status": 415},
    ),
    "RecordingPersistenceError": (
        lambda: RecordingPersistenceError("Failed to store recording"),
        {"message": "Failed to store recording"},
    ),
}

_FIELDS = [(name, field) for name, (_, fields) in _ERRORS.items()
           for field in fields]


@contextmanager
def _scope():
    yield


def _assert_carries(error: Exception, fields: dict[str, Any]) -> None:
    assert {name: getattr(error, name) for name in fields} == fields


@pytest.mark.parametrize("name", _ERRORS)
def test_raised_inside_a_contextmanager_it_comes_out_as_itself(name):
    build, fields = _ERRORS[name]
    error = build()

    with pytest.raises(type(error)) as caught:
        with _scope():
            raise error

    assert caught.value is error
    _assert_carries(caught.value, fields)


@pytest.mark.parametrize("name", _ERRORS)
def test_raised_inside_an_exitstack_it_comes_out_as_itself(name):
    build, fields = _ERRORS[name]
    error = build()

    def refuse():
        raise error

    with pytest.raises(type(error)) as caught:
        with ExitStack() as stack:
            stack.callback(refuse)

    assert caught.value is error
    _assert_carries(caught.value, fields)


@pytest.mark.parametrize("name", _ERRORS)
def test_add_note_and_pickle_still_work(name):
    build, fields = _ERRORS[name]

    noted = build()
    noted.add_note("take-1")
    assert noted.__notes__ == ["take-1"]

    restored = pickle.loads(pickle.dumps(build()))
    assert type(restored) is type(noted)
    _assert_carries(restored, fields)


@pytest.mark.parametrize("name", _ERRORS)
def test_keyword_construction_matches_positional(name):
    build, fields = _ERRORS[name]
    positional = build()

    keyword = type(positional)(**fields)

    _assert_carries(keyword, fields)
    assert keyword.args == positional.args == tuple(fields.values())
    assert str(keyword) == str(positional)


@pytest.mark.parametrize(("name", "field"), _FIELDS)
def test_each_field_stays_read_only(name, field):
    build, fields = _ERRORS[name]
    error = build()

    with pytest.raises(AttributeError):
        setattr(error, field, "changed")

    _assert_carries(error, fields)
