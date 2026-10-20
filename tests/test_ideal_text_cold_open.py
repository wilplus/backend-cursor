"""
STORY    As a speaker, I want opening my Ideal Text never to show it as missing
         when the read failed, and never to serve an out-of-date snapshot, so
         that the loop never breaks quietly.
OUTCOME
  O1  A failed cold-open read answers 503 IDEAL_TEXT_READ_FAILED, retryable,
      never the "pending" 404 that would show an existing Ideal Text as
      missing.
  O2  A snapshot that turns stale while the enrichment readers run answers
      409 SNAPSHOT_STALE with the current snapshot id, and the server-side
      acknowledgement token never leaves.
PROVES   O1 -> test_a_failed_cold_open_read_says_retry_not_pending
         O2 -> test_enrichment_rejects_snapshot_that_turns_stale_during_readers
WHY      Founder 2026-09-26: a dropped connection showed an existing Ideal Text
         as missing. (The old v1 fallback and its "degraded read is counted"
         tests are gone: a failed read is now a visible 503.)
NOTE     Stale-at-first-check refusals live in
         tests/test_ideal_text_route_contracts.py::test_enrichment_refusals;
         this file pins the stale-DURING-readers case only.
"""
from __future__ import annotations

import inspect
from unittest.mock import Mock

from flask import Flask, request


def _get(view, path):
    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule("/test/<arc_id>", view_func=inspect.unwrap(view))
    return app.test_client().get(path)


def test_a_failed_cold_open_read_says_retry_not_pending(monkeypatch):
    import routes.v2.explore_ideal_text as route
    from services.db import IdealTextCoreReadError

    database = Mock()
    database.get_ideal_text_document_core_v2.side_effect = IdealTextCoreReadError(
        "Server disconnected")
    monkeypatch.setattr(route, "db", database)

    response = _get(route.v2_explore_get_ideal_text_core, "/test/arc-1")

    assert response.status_code == 503
    assert response.get_json() == {
        "code": "IDEAL_TEXT_READ_FAILED", "retryable": True}
    assert response.headers["Retry-After"] == "2"


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
    database.get_ideal_text_document_core.return_value = selected
    database.get_ideal_text_document_fence.return_value = {"id": "snapshot-new"}
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

    response = _get(
        route.v2_explore_get_ideal_text_enrichment,
        "/test/arc-1?document_snapshot_id=snapshot-old&sections=learning")

    assert response.status_code == 409
    assert response.get_json() == {
        "code": "SNAPSHOT_STALE",
        "current_document_snapshot_id": "snapshot-new",
    }
    assert b"must-not-leave-server" not in response.data
    # The whole snapshot is read once; the post-reader check is the fence.
    assert database.get_ideal_text_document_core.call_count == 1
    database.get_ideal_text_document_fence.assert_called_once_with(
        "arc-1", "actor-1")
    assert "fence_read;dur=" not in response.headers.get("Server-Timing", "")
    prepared.assert_called_once()


def test_the_fence_read_is_the_head_and_the_generation_only(monkeypatch):
    """The post-reader check compares two ids; it reads two rows, not the
    whole snapshot again, and a generation that moved on reads as no head."""
    from services.db import db

    def reads(by_label):
        def execute(query_factory, *, label, **_):
            return Mock(data=by_label[label])
        return execute

    head = [{"snapshot_id": "snapshot-1",
             "ideal_text_document_snapshots": {"source_generation": 4}}]
    monkeypatch.setattr(db, "_execute_with_retry", reads({
        "ideal_text_fence_head": head,
        "ideal_text_fence_generation": [{"generation": 4}]}))
    assert db.get_ideal_text_document_fence("arc-1", "actor-1") == {
        "id": "snapshot-1"}

    monkeypatch.setattr(db, "_execute_with_retry", reads({
        "ideal_text_fence_head": head,
        "ideal_text_fence_generation": [{"generation": 5}]}))
    assert db.get_ideal_text_document_fence("arc-1", "actor-1") is None
