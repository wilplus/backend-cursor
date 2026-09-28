"""The deck keeps its slides when a project has no published head
(founder 2026-09-28: "the text was not assigned to the slides ... there
should be at least five slides and it was all concatenated into two pages").

Three defects, one screen: the unlinked "Your talk" section with no slide
picture.

1. A Take without the denormalised ``owner_principal_id`` copy -- most of
   them -- made ``build_snapshot`` refuse (LINEAGE_REQUIRED), so the project
   never got a head at all.
2. With no head, every open fell back to the composing read, whose
   provenance threw every Slide away the moment the served words differed
   from the stored Take-1 body.
3. Nothing ever repaired the missing head (decision 16A: build and save it
   the moment it's opened).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, request

from services import ideal_text_core_snapshot as core


ARC = "00000000-0000-0000-0000-000000000040"
USER = "00000000-0000-0000-0000-000000000030"
OWNER = "00000000-0000-0000-0000-000000000050"
TAKE = "00000000-0000-0000-0000-000000000020"
TEXT = "Hello everybody.\n\nSo, what we came up with is a.\n\nshort mechanism."


def _stub_reads(monkeypatch):
    monkeypatch.setattr(core, "resolve_ideal_text_source", lambda row: (
        SimpleNamespace(machine_text=TEXT, version=1)))
    monkeypatch.setattr(core, "resolve_live_text", lambda *a, **k: (
        SimpleNamespace(text=TEXT, user_edited=False, status="ready",
                        prior_edit=None)))
    monkeypatch.setattr(core, "resolve_suggestion_display", lambda *a, **k: (
        SimpleNamespace(text=TEXT, enabled=False)))
    monkeypatch.setattr(core, "resolve_project_read", lambda *a, **k: (
        SimpleNamespace(
            spoken_rows=[{"id": TAKE, "project_id": ARC,
                          "owner_principal_id": None, "take_index": 1}],
            latest_take_session_id=TAKE, title="Talk",
            can_record_take=True, presentation_ref=None, slide_titles=[])))


def _database():
    database = Mock()
    database.ideal_text.get_coach_arc_ideal_text.return_value = {
        "auto_text": TEXT,
        "document": {"paragraphs": [
            {"slide_index": 0}, {"slide_index": 1}, {"slide_index": 2},
        ]},
    }
    database.get_ideal_text_parts.return_value = []
    database.replace_ideal_text_parts.return_value = False
    database.get_project_owner_principal.return_value = OWNER
    return database


def test_a_take_without_the_owner_copy_still_publishes_with_its_slides(
        monkeypatch):
    _stub_reads(monkeypatch)
    database = _database()

    payload, _seed, lineage = core.build_snapshot(database, ARC, USER, [])

    # The project is the authoritative owner; the Take's copy is optional.
    database.get_project_owner_principal.assert_called_once_with(ARC)
    assert lineage["acquisition_principal_id"] == OWNER
    assert lineage["project_id"] == ARC
    assert [p["slide_index"] for p in payload["pieces"]] == [0, 1, 2]


def test_a_project_with_no_owner_anywhere_still_refuses(monkeypatch):
    _stub_reads(monkeypatch)
    database = _database()
    database.get_project_owner_principal.return_value = ""

    try:
        core.build_snapshot(database, ARC, USER, [])
    except ValueError as error:
        assert str(error) == "IDEAL_TEXT_DOCUMENT_LINEAGE_REQUIRED"
    else:  # pragma: no cover - the assertion is the point
        raise AssertionError("a document with no provable owner published")


def test_the_fallback_read_keeps_slides_slot_for_slot_when_words_changed():
    import routes.v2.explore_ideal_text as route

    stored = [{"slide_index": 0, "snippet_id": "a"},
              {"slide_index": 1, "snippet_id": "b"},
              {"slide_index": 1, "snippet_id": "c"}]
    rewritten = "Hello all.\n\nA new second slot.\n\nThe third, reworded."
    rows = route._ideal_piece_provenance_by_slot(stored, rewritten)  # noqa: SLF001
    assert [row["slide_index"] for row in rows] == [0, 1, 1]
    assert [row["snippet_id"] for row in rows] == ["a", "b", "c"]


def test_the_fallback_read_still_refuses_a_changed_shape():
    import routes.v2.explore_ideal_text as route

    stored = [{"slide_index": 0}, {"slide_index": 1}, {"slide_index": 2}]
    assert route._ideal_piece_provenance_by_slot(  # noqa: SLF001
        stored, "One.\n\nTwo and three, merged.") is None
    assert route._ideal_piece_provenance_by_slot(stored, "") is None  # noqa: SLF001


def _open_core(monkeypatch, *, reads, owned=True, published=True):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core_v2.side_effect = reads
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller",
                        lambda arc_id: (owned, []))
    publish = Mock(return_value={"id": "head"} if published else None)
    monkeypatch.setattr(core, "publish_for_arc", publish)
    core._missing_head_publish_attempts.clear()  # noqa: SLF001
    app = Flask(__name__)
    with app.test_request_context("/v2/core"):
        request.user_id = USER
        response = route.v2_explore_get_ideal_text_core.__wrapped__(ARC)
    return response, database, publish


def _core_read():
    return {
        "snapshot": {"id": "s", "payload_sha256": "a" * 64,
                     "payload": {"text": TEXT}},
        "dynamic_overlay": {
            "owner_edit": None, "confident_moment_summary": None,
            "confident_moment_summary_status": None,
        },
    }


def test_an_owner_opening_a_project_with_no_head_gets_one_built(monkeypatch):
    response, database, publish = _open_core(
        monkeypatch, reads=[None, _core_read()])

    publish.assert_called_once()
    assert publish.call_args.args[1:] == (ARC, USER)
    assert database.get_ideal_text_document_core_v2.call_count == 2
    assert response.status_code == 200
    assert response.get_json()["text"] == TEXT


def test_an_existing_head_is_only_read(monkeypatch):
    response, _database, publish = _open_core(
        monkeypatch, reads=[_core_read()])

    publish.assert_not_called()
    assert response.status_code == 200


def test_a_non_owner_never_triggers_a_build(monkeypatch):
    response, _database, publish = _open_core(
        monkeypatch, reads=[None], owned=False)

    publish.assert_not_called()
    assert response.status_code == 404


def test_a_build_that_fails_stays_an_honest_pending_and_is_not_retried_hot(
        monkeypatch):
    response, database, publish = _open_core(
        monkeypatch, reads=[None, None], published=False)
    assert response.status_code == 404
    assert publish.call_count == 1

    # The client polls every few seconds; the next open inside the window
    # reads without building again.
    assert core.read_core_or_publish(
        database, ARC, USER, is_owner=lambda: True) is None
    assert publish.call_count == 1


def test_the_page_reads_go_through_the_reconnecting_retry():
    """Decision 15: a dropped connection is retried for the reads the Ideal
    Text page stands on, not only for the core read."""
    from services.ideal_text_repository import IdealTextRepository

    database = Mock()
    rows = SimpleNamespace(data=[{"arc_id": ARC}])
    database._execute_with_retry.return_value = rows
    repository = IdealTextRepository(database)

    assert repository.get_coach_arc_ideal_text(ARC) == {"arc_id": ARC}
    database._execute_with_retry.assert_called_once()
    assert database._execute_with_retry.call_args.kwargs["label"] == (
        "get_coach_arc_ideal_text")


def test_a_repository_without_the_retry_still_reads():
    from services.table_repository import TableRepository

    query = Mock()
    query.execute.return_value = "rows"
    repository = TableRepository(SimpleNamespace(client=None))
    assert repository._execute(lambda: query, label="x") == "rows"  # noqa: SLF001
