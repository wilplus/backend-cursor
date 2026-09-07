from __future__ import annotations

import inspect
from unittest.mock import Mock

import pytest
from flask import Flask, request

from services.recording_roots import RecordingRootsStale, project_recording_roots


def _snapshot(*, slide_index=1):
    return {
        "id": "snapshot-1",
        "payload_sha256": "a" * 64,
        "payload": {
            "text": "The exact accepted sentence.",
            "parts": [{
                "id": "part-1", "ord": 0,
                "text": "The exact accepted sentence.", "locked": False,
                "iteration": 0,
            }],
            "pieces": [{
                "text": "The exact accepted sentence.",
                "slide_index": slide_index,
            }],
        },
    }


def _live_rows():
    return [{
        "id": "part-1", "ord": 0,
        "text": "The exact accepted sentence.",
        "locked_at": "2026-09-07T10:00:00Z", "iteration": 1,
        "root_phrase": "accepted sentence", "root_start": 10,
        "root_end": 27,
    }]


def test_live_root_overlays_a_matching_immutable_slide_mapping():
    assert project_recording_roots(_snapshot(), _live_rows()) == [{
        "part_id": "part-1", "slide_index": 1,
        "text": "accepted sentence", "type": "flagship",
    }]


def test_missing_slide_lineage_is_never_guessed():
    assert project_recording_roots(_snapshot(slide_index=None), _live_rows()) == []


@pytest.mark.parametrize("mutation", ["id", "text", "span", "lock"])
def test_stale_or_invalid_live_root_fails_closed(mutation):
    rows = _live_rows()
    if mutation == "id":
        rows[0]["id"] = "part-foreign"
    elif mutation == "text":
        rows[0]["text"] = "Changed text."
    elif mutation == "span":
        rows[0]["root_start"] = 0
    else:
        rows[0]["locked_at"] = None
    with pytest.raises(RecordingRootsStale):
        project_recording_roots(_snapshot(), rows)


def test_recording_roots_route_returns_the_live_root(monkeypatch):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core.return_value = _snapshot()
    database.get_ideal_text_parts.return_value = _live_rows()
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (True, []))

    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>",
        view_func=inspect.unwrap(route.v2_explore_get_recording_roots),
    )
    response = app.test_client().get("/test/arc-1")

    assert response.status_code == 200
    assert response.get_json()["roots"][0]["text"] == "accepted sentence"
    database.get_ideal_text_parts.assert_called_once_with(
        "arc-1", "actor-1", with_lock=True)
