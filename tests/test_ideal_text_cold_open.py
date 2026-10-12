from __future__ import annotations

import inspect
from unittest.mock import Mock

from flask import Flask, request


def test_enrichment_rejects_snapshot_that_turns_stale_during_readers(
        monkeypatch):
    import routes.v2.explore_ideal_text as route
    import services.learning_exposures as exposures

    selected = {
        "id": "snapshot-old",
        "payload": {
            "latest_take_session_id": "take-1",
            "take_count": 1,
            "version": 1,
            "title": "Test",
            "text": "Exact text.",
            "parts": [],
        },
        "enrichment_seed": {},
    }
    database = Mock()
    database.get_ideal_text_document_core.side_effect = [
        selected,
        {**selected, "id": "snapshot-new"},
    ]
    database.get_ideal_text_document_snapshot.return_value = selected
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (
        True,
        [{
            "id": "take-1",
            "owner_principal_id": "owner-1",
            "project_id": "project-1",
        }],
    ))
    prepared = Mock(return_value={
        "presentation_id": "presentation-1",
        "acknowledgement_token": "must-not-leave-server",
    })
    monkeypatch.setattr(
        exposures, "prepare_ideal_text_presentation", prepared)

    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>",
        view_func=inspect.unwrap(route.v2_explore_get_ideal_text_enrichment),
    )
    response = app.test_client().get(
        "/test/arc-1?document_snapshot_id=snapshot-old&sections=learning")

    assert response.status_code == 409
    assert response.get_json() == {
        "code": "SNAPSHOT_STALE",
        "current_document_snapshot_id": "snapshot-new",
    }
    assert b"must-not-leave-server" not in response.data
    assert database.get_ideal_text_document_core.call_count == 2
    prepared.assert_called_once()


# ---------------------------------------------------------------------------
#  A DEGRADED read must not be a SILENT one (2026-09-15)
#
#  The cold-open read is built to never 500: when the v2 RPC or its validator
#  fails, the arc is served the pre-#490 v1 document, and when that is missing
#  too the route answers `404 IDEAL_TEXT_DOCUMENT_PENDING, state=pending`.
#  Both are the right wire behaviour — a read fault must not take the recording
#  loop down with it.
#
#  What was missing is the other half. The fallbacks were recorded with
#  `logger.warning` into a stream nobody watches, so on 2026-09-15 every core
#  read in production degraded and the only signal that reached a human was the
#  founder opening the app. These tests pin the fallbacks as COUNTABLE, and pin
#  the two expected quiet paths as quiet, so the signal keeps meaning something.
# ---------------------------------------------------------------------------
