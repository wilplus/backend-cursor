"""The rooting phrase saves on the step that chose it, lock or no lock.

Regression cover for a live break. `#442` moved the emphasis save onto the
emphasis step, where the paragraph has not been locked yet — and on "No", "Not
sure" and "Audio unclear" the Lock step is not built at all. The route still
required a lock, so every first-pass emphasis save answered 409 and put an
error on the sheet. Founder 2026-09-24: "Just save the rooting phrases orange,
but do not let them lock that text."

Nothing here asserts that an unlocked root is *eligible*. It is recorded, and
`test_recording_roots.py` holds the other half: reads still yield locked roots
only.
"""
from __future__ import annotations

import inspect
from unittest.mock import Mock

import pytest
from flask import Flask, request

import routes.v2.explore_ideal_text as route

TEXT = "The exact accepted sentence."
PHRASE = "accepted sentence"
START, END = 10, 27


def _part(*, locked: bool):
    return {"id": "part-1", "ord": 0, "text": TEXT, "locked": locked}


def _client(monkeypatch, *, locked: bool, saved: bool = True):
    database = Mock()
    database.set_ideal_text_part_root.return_value = saved
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (True, []))
    monkeypatch.setattr(
        route, "_locked_parts",
        lambda _arc, _user, _echo: [_part(locked=locked)],
    )

    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>/<part_id>",
        view_func=inspect.unwrap(route.v2_explore_set_part_root),
        methods=["PUT"],
    )
    return app.test_client(), database


@pytest.mark.parametrize("locked", [False, True])
def test_a_rooting_phrase_saves_whether_or_not_the_paragraph_is_locked(
        monkeypatch, locked):
    client, database = _client(monkeypatch, locked=locked)

    response = client.put(
        "/test/arc-1/part-1",
        json={"text_echo": TEXT, "phrase": PHRASE,
              "start": START, "end": END},
    )

    assert response.status_code == 200
    database.set_ideal_text_part_root.assert_called_once_with(
        arc_id="arc-1", user_id="actor-1", part_id="part-1",
        phrase=PHRASE, start=START, end=END,
    )


def test_an_unlocked_paragraph_is_never_answered_with_part_not_locked(
        monkeypatch):
    """The exact failure the speaker saw: 409 on the ordinary first pass."""
    client, _ = _client(monkeypatch, locked=False)

    response = client.put(
        "/test/arc-1/part-1",
        json={"text_echo": TEXT, "phrase": PHRASE,
              "start": START, "end": END},
    )

    assert response.status_code != 409
    assert (response.get_json() or {}).get("code") != "PART_NOT_LOCKED"


def test_a_skip_is_recorded_on_an_unlocked_paragraph_too(monkeypatch):
    client, database = _client(monkeypatch, locked=False)

    response = client.put(
        "/test/arc-1/part-1", json={"text_echo": TEXT, "phrase": None},
    )

    assert response.status_code == 200
    database.set_ideal_text_part_root.assert_called_once_with(
        arc_id="arc-1", user_id="actor-1", part_id="part-1",
        phrase=None, start=None, end=None,
    )


def test_words_outside_the_paragraph_are_still_refused_when_unlocked(
        monkeypatch):
    """Lifting the lock precondition lifts nothing else. The span must still
    be exact words of this paragraph — that guard is what keeps an orange
    phrase pointing at text the speaker actually has."""
    client, database = _client(monkeypatch, locked=False)

    response = client.put(
        "/test/arc-1/part-1",
        json={"text_echo": TEXT, "phrase": "words never spoken",
              "start": START, "end": END},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_ROOT_PHRASE"
    database.set_ideal_text_part_root.assert_not_called()


def test_a_stale_document_is_still_refused_when_unlocked(monkeypatch):
    client, database = _client(monkeypatch, locked=False)
    monkeypatch.setattr(route, "_locked_parts", lambda *_a: [])

    response = client.put(
        "/test/arc-1/part-1",
        json={"text_echo": TEXT, "phrase": PHRASE,
              "start": START, "end": END},
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "STALE_DOCUMENT"
    database.set_ideal_text_part_root.assert_not_called()
