"""Your projects: every project, fast, and never a silent empty (D-CS-4;
consent lock §2, the settings page prototype's Your projects card).

GET /v2/user/trainings?include_archived=1 is the Data & consent read
(fetchTrainings({includeArchived: true})). Pins: N projects, some archived
and some with slides, all come back; the coach-edits check is ONE read for
all of them, never one per project; a database error there is a 500
V2_ERROR, never an empty 200; the picker read (no flag) keeps today's
behaviour, one check per project with slides and an empty list on a failed
read; the elapsed time is logged."""
from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request

from routes.v2 import user_sessions as route
from services.db import DatabaseService, db
from services.take_repository import TakeRepository

ARCS = [str(uuid.UUID(int=n + 1)) for n in range(6)]
ARCHIVED = {ARCS[1], ARCS[4]}
WITH_SLIDES = {ARCS[0], ARCS[1], ARCS[2]}


def _rows():
    rows = []
    for n, arc in enumerate(ARCS):
        context = {"topic": f"Project {n}"}
        if arc in WITH_SLIDES:
            context["slides"] = [{"title": "One"}, {"title": "Two"}]
        rows.append({"id": str(uuid.uuid4()), "arc_id": arc, "take_index": 1,
                     "created_at": f"2026-10-0{n + 1}T10:00:00Z",
                     "intake_context": context, "results_published_at": None})
    return rows


def _get(query: str, *, rows=None, sessions_error=None):
    per_arc = MagicMock(return_value={})
    batched = MagicMock(return_value={ARCS[0]: {0: "a", 1: "b"}})

    def sessions(_user, **kwargs):
        if sessions_error is not None and kwargs.get("strict"):
            raise sessions_error
        if sessions_error is not None:
            return []
        return _rows() if rows is None else rows

    app = Flask(__name__)
    with patch.object(db.takes, "list_user_arc_sessions", side_effect=sessions) as lister, \
            patch.object(db, "list_arc_batch_deliveries", return_value={}), \
            patch.object(db, "get_coach_best_presentation_edits", per_arc), \
            patch.object(db, "get_coach_best_presentation_edits_for_arcs", batched), \
            patch("services.project_deletion.ProjectDeletionService.open_for_projects",
                  return_value={}), \
            patch("services.project_deletion.ProjectDeletionService.erased_projects",
                  return_value=set()), \
            patch("services.project_deletion.ProjectDeletionService.archived_projects",
                  return_value=set(ARCHIVED)):
        with app.test_request_context(f"/v2/user/trainings{query}"):
            request.user_id = "u1"
            response, status = route.v2_user_list_trainings.__wrapped__()
    return status, response.get_json(), per_arc, batched, lister


def test_every_project_comes_back_archived_or_not():
    status, body, _, _, lister = _get("?include_archived=1")
    assert status == 200
    trainings = body["trainings"]
    assert sorted(t["arc_id"] for t in trainings) == sorted(ARCS)
    assert {t["arc_id"] for t in trainings if t["archived"]} == ARCHIVED
    assert lister.call_args.kwargs == {"strict": True}
    # The batched check still decides ideal_ready: two of two slides edited.
    by_arc = {t["arc_id"]: t for t in trainings}
    assert by_arc[ARCS[0]]["ideal_ready"] is True
    assert by_arc[ARCS[2]]["ideal_ready"] is False


def test_the_every_project_read_asks_once_not_once_per_project():
    _, _, per_arc, batched, _ = _get("?include_archived=1")
    per_arc.assert_not_called()
    batched.assert_called_once()
    assert sorted(batched.call_args.args[0]) == sorted(ARCS)


def test_the_batched_read_is_one_query_for_n_projects():
    calls: list = []

    class _Query:
        def select(self, *_a):
            return self

        def in_(self, column, values):
            calls.append((column, list(values)))
            return self

        def execute(self):
            return SimpleNamespace(data=[
                {"arc_id": ARCS[0], "slide_index": 0, "text": "a"},
                {"arc_id": ARCS[0], "slide_index": 1, "text": "b"},
                {"arc_id": ARCS[2], "slide_index": 0, "text": "c"},
            ])

    client = SimpleNamespace(table=lambda name: (calls.append(("table", name)), _Query())[1])
    out = DatabaseService.get_coach_best_presentation_edits_for_arcs(
        SimpleNamespace(client=client), ARCS)  # type: ignore[arg-type]
    assert [c for c in calls if c[0] == "table"] == [
        ("table", "coach_best_presentation_edits")]
    assert out == {ARCS[0]: {0: "a", 1: "b"}, ARCS[2]: {0: "c"}}


def test_a_database_error_is_a_500_not_an_empty_list():
    status, body, _, _, _ = _get("?include_archived=1",
                                 sessions_error=RuntimeError("connection reset"))
    assert (status, body["code"]) == (500, "V2_ERROR")


def test_the_picker_read_keeps_todays_behaviour():
    status, body, per_arc, batched, lister = _get("")
    assert status == 200
    assert sorted(t["arc_id"] for t in body["trainings"]) == sorted(
        set(ARCS) - ARCHIVED)
    assert lister.call_args.kwargs == {}
    batched.assert_not_called()
    assert per_arc.call_count == len(WITH_SLIDES)
    # A failed read there is still today's empty list.
    status, body, *_ = _get("", sessions_error=RuntimeError("connection reset"))
    assert (status, body["trainings"]) == (200, [])


def test_the_elapsed_time_is_logged(caplog):
    caplog.set_level(logging.INFO, logger=route.logger.name)
    _get("?include_archived=1")
    line = next(r.getMessage() for r in caplog.records
                if "user/trainings include_archived=1" in r.getMessage())
    assert "projects=6" in line and "elapsed_ms=" in line


def test_the_repository_read_raises_only_when_asked():
    class _Failing:
        def table(self, _name):
            raise RuntimeError("connection reset")

    repository = TakeRepository(SimpleNamespace(client=_Failing()))
    assert repository.list_user_arc_sessions("u1") == []
    with pytest.raises(RuntimeError):
        repository.list_user_arc_sessions("u1", strict=True)
