"""
STORY    As a speaker, I want my chosen helper words to stay on their slide
         after a later Take, and out-of-date ones refused, so that my helper
         words stay until I pick new ones.
OUTCOME
  O1  Helper words whose Paragraph was changed or belongs elsewhere are
      refused rather than shown in the wrong place.
  O2  The helper-words route returns the helper words currently chosen.
  O3  Helper words picked in an earlier Take still appear, on the slide's
      Paragraph now.
PROVES   O1 -> test_stale_or_invalid_live_root_fails_closed
         O2 -> test_recording_roots_route_returns_the_live_root
         O3 -> test_helper_words_from_an_earlier_take_stay_on_their_slide
WHY      Never-rule 5; founder 2026-10-13, project "S".
"""
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


@pytest.mark.parametrize("mutation", ["id", "text"])
def test_stale_or_invalid_live_root_fails_closed(mutation):
    rows = _live_rows()
    if mutation == "id":
        rows[0]["id"] = "part-foreign"
    else:
        rows[0]["text"] = "Changed text."
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


def _route_response(monkeypatch, *, live_rows, slide_rows):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core.return_value = _snapshot()
    database.get_ideal_text_parts.return_value = live_rows
    database.get_slide_helper_words.return_value = slide_rows
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
    return app.test_client().get("/test/arc-1")


def test_helper_words_from_an_earlier_take_stay_on_their_slide(monkeypatch):
    """Founder 2026-10-13, project "S": the Paragraph the words were picked
    on is gone after a later Take, and the live Paragraphs are mid-change.
    The words still reach the page, on the Slide's Paragraph now."""
    rows = _live_rows()
    rows[0]["text"] = "Changed text."
    response = _route_response(monkeypatch, live_rows=rows, slide_rows=[{
        "slide_index": 1, "ord": 0, "phrase": "accepted sentence",
        "take_session_id": "take-1", "source_part_id": "part-from-take-1",
        "locked_at": "2026-10-10T09:00:00Z",
    }])

    assert response.status_code == 200
    assert response.get_json()["roots"] == [{
        "part_id": "part-1", "slide_index": 1,
        "text": "accepted sentence", "type": "flagship",
    }]
