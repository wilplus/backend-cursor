from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path
from unittest.mock import Mock

from flask import Flask, request
from services import ideal_text_core_snapshot as core
from services.ideal_text_enrichment import run_sections


ROOT = Path(__file__).resolve().parents[1]


def test_stable_paragraph_identity_carries_proven_slide_lineage():
    previous = {
        "parts": [{"id": "p-1", "text": "Before."}],
        "pieces": [{
            "slide_index": 2,
            "snippet_id": "snippet-1",
            "take_session_id": "take-1",
            "take_index": 1,
        }],
    }
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {"auto_text": "Before.", "document": {"paragraphs": []}},
        "After.",
        [{"id": "p-1", "text": "After.", "root_phrase": "After"}],
        previous_payload=previous,
    )
    assert pieces == [{
        "piece_key": 0,
        "text": "After.",
        "root_phrase": "After",
        "root_type": "flagship",
        "slide_index": 2,
        "block_key": None,
        "snippet_id": "snippet-1",
        "take_session_id": "take-1",
        "take_index": 1,
        "status": "settled",
        "challenger": None,
    }]


def test_new_paragraph_identity_never_guesses_a_slide():
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {"auto_text": "Before.", "document": {"paragraphs": []}},
        "After.",
        [{"id": "new-id", "text": "After."}],
        previous_payload={
            "parts": [{"id": "old-id", "text": "Before."}],
            "pieces": [{"slide_index": 4}],
        },
    )
    assert pieces[0]["slide_index"] is None


def test_enrichment_sections_fail_independently_and_run_concurrently():
    def slow(value):
        time.sleep(0.06)
        return value

    def broken():
        raise RuntimeError("optional failure")

    started = time.perf_counter()
    sections, _timings = run_sections({
        "one": lambda: slow({"one": True}),
        "two": lambda: slow({"two": True}),
        "broken": broken,
    }, timeout_seconds=0.3)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.11
    assert sections["one"] == {"status": "ready", "data": {"one": True}}
    assert sections["two"] == {"status": "ready", "data": {"two": True}}
    assert sections["broken"] == {"status": "failed", "retryable": True}


def test_enrichment_timeout_is_retryable_and_does_not_block_response():
    started = time.perf_counter()
    sections, _timings = run_sections({
        "slow": lambda: (time.sleep(0.15), {"late": True})[1],
    }, timeout_seconds=0.02)
    assert time.perf_counter() - started < 0.08
    assert sections["slow"] == {"status": "pending", "retryable": True}


def test_core_handler_is_strictly_read_only_by_architecture():
    path = ROOT / "routes" / "v2" / "explore_ideal_text.py"
    source = path.read_text()
    tree = ast.parse(source)
    handler = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "v2_explore_get_ideal_text_core"
    )
    body = ast.get_source_segment(source, handler) or ""
    assert "get_ideal_text_document_core" in body
    called = set()
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    assert not called.intersection({
        "compose_locked", "persist_auto_ideal_text",
        "prepare_ideal_text_presentation", "_tracked_changes_block",
        "_moment_explanations_map", "_moment_playback_map",
        "_confidence_review_status_map",
    })


def test_snapshot_contract_is_rpc_only_and_owner_checked():
    sql = (ROOT / "migrations"
           / "add_ideal_text_core_snapshot.sql").read_text()
    assert "read_ideal_text_document_core_v1" in sql
    assert "publish_ideal_text_document_snapshot_v1" in sql
    assert "p_payload ?& ARRAY" in sql
    assert "source_generation" in sql
    assert "IDEAL_TEXT_DOCUMENT_SOURCE_STALE" in sql
    assert "advance_ideal_text_document_generation_v1" in sql
    assert "ready_take_advances_ideal_text_document_generation" in sql
    assert "generation.generation=snapshot.source_generation" in sql
    assert "REVOKE ALL ON public.ideal_text_document_snapshots" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "owner.user_id::text=p_actor_id" in sql


def test_every_canonical_writer_publishes_the_cold_open_snapshot():
    required = {
        "services/ideal_text_block.py": "publish_for_arc(database",
        "services/take_review.py": "publish_for_arc(database",
        "routes/v2/explore_ideal_text.py": "_publish_ideal_text_core",
        "routes/v2/coach.py": "publish_for_arc(db",
    }
    for relative, needle in required.items():
        assert needle in (ROOT / relative).read_text()


def test_publisher_retries_one_generation_race(monkeypatch):
    class FakeDatabase:
        generations = iter((5, 6))
        calls: list[int] = []

        def get_arc_sessions(self, _arc_id):
            return [{
                "id": "take-1", "take_index": 1, "analysis_state": "ready",
                "recording_kind": "spoken", "user_id": "actor-1",
            }]

        def get_ideal_text_document_generation(self, _arc_id):
            return next(self.generations)

        def get_ideal_text_document_snapshot(self, *_args):
            return None

        def publish_ideal_text_document_snapshot(self, **kwargs):
            self.calls.append(kwargs["source_generation"])
            return None if len(self.calls) == 1 else {"id": "snapshot-2"}

    monkeypatch.setattr(core, "build_snapshot", lambda *_args, **_kwargs: (
        {"text": "Current"}, {}, {
            "acquisition_principal_id": "owner-1",
            "project_id": "project-1",
            "source_take_session_id": "take-1",
            "version": 1,
            "source_fingerprint_sha256": "a" * 64,
        },
    ))
    database = FakeDatabase()
    result = core.publish_for_arc(database, "arc-1")
    assert result == {"id": "snapshot-2"}
    assert database.calls == [5, 6]


def test_durable_generation_sweeper_requeues_only_pending_rows(monkeypatch):
    class FakeDatabase:
        def list_pending_ideal_text_document_publications(self, _limit):
            return [
                {"arc_id": "arc-a", "generation": 3},
                {"arc_id": "", "generation": 4},
                {"arc_id": "arc-b", "generation": "bad"},
            ]

    queued = []
    monkeypatch.setattr(
        core, "enqueue_pending_publication",
        lambda arc_id, generation: queued.append((arc_id, generation)) or True,
    )
    assert core.sweep_pending_publications(FakeDatabase(), limit=20) == 1
    assert queued == [("arc-a", 3)]


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
