"""
STORY    As an authenticated speaker, I want to rename my project from its
         project row, so that the project keeps its contents and lifecycle.
OUTCOME
  O1  A signed-in owner can rename the owned, unerased project and receives a
      stable project id/name response.
  O2  A different user or a missing project receives the existing non-
      disclosing project-not-found contract.
  O3  Blank names are rejected without a project mutation.
PROVES   O1 -> test_authenticated_rename_returns_stable_contract
         test_rename_updates_only_the_owned_live_project
         O2 -> test_cross_user_rename_is_forbidden_without_project_disclosure
         test_rename_missing_or_cross_user_project_is_not_found
         O3 -> test_rename_rejects_invalid_input_before_mutation
WHY      Founder-approved project-row Edit/Rename action.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask, request

from routes.v2 import projects as projects_route
from services.project_rename import ProjectRenameError, ProjectRenameService

PROJECT = "22222222-2222-4222-8222-222222222222"
USER = "11111111-1111-4111-8111-111111111111"
STRANGER = "99999999-9999-4999-8999-999999999999"


class _Update:
    def __init__(self, rows):
        self.rows = rows
        self.payload = None
        self.filters: list[tuple] = []

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


def _service(rows):
    query = _Update(rows)
    client = MagicMock()
    client.table.return_value = query
    return ProjectRenameService(SimpleNamespace(client=client)), query


def test_rename_updates_only_the_owned_live_project():
    service, query = _service([{"id": PROJECT, "display_name": "Renamed"}])

    result = service.rename("owner-1", PROJECT, "Renamed")

    assert result == {"project_id": PROJECT, "display_name": "Renamed"}
    assert query.payload == {"display_name": "Renamed"}
    assert query.filters == [
        ("eq", "id", PROJECT),
        ("eq", "owner_principal_id", "owner-1"),
        ("is", "tombstoned_at", "null"),
    ]


def test_rename_missing_or_cross_user_project_is_not_found():
    service, _query = _service([])

    try:
        service.rename("owner-1", PROJECT, "Renamed")
    except ProjectRenameError as error:
        assert (error.code, error.status) == ("PROJECT_NOT_FOUND", 404)
    else:  # pragma: no cover
        raise AssertionError("missing owned project must be rejected")


def _endpoint(body, *, user_id=USER, project_exists=True):
    app = Flask(__name__)
    owner = SimpleNamespace(id=f"owner-{user_id}")
    database = SimpleNamespace(client=MagicMock())
    with app.test_request_context(method="PATCH", json=body), \
            patch.object(projects_route, "db", database), \
            patch.object(projects_route.ProjectRepository,
                         "owner_for_user", return_value=owner), \
            patch.object(projects_route.ProjectRenameService, "rename",
                         return_value=(
                             {"project_id": PROJECT,
                              "display_name": "Renamed"}
                             if project_exists else None)) as rename:
        request.user_id = user_id
        if not project_exists:
            rename.side_effect = ProjectRenameError("PROJECT_NOT_FOUND", 404)
        response, status = projects_route.v2_rename_project.__wrapped__(PROJECT)
        return response.get_json(), status, rename


def test_authenticated_rename_returns_stable_contract():
    body, status, _rename = _endpoint({"display_name": "  Renamed  "})

    assert (status, body) == (200, {
        "project_id": PROJECT,
        "display_name": "Renamed",
    })


def test_cross_user_rename_is_forbidden_without_project_disclosure():
    body, status, _rename = _endpoint(
        {"display_name": "Renamed"}, user_id=STRANGER, project_exists=False)

    assert (status, body) == (404, {
        "code": "PROJECT_NOT_FOUND",
        "error": "Project not found",
    })


def test_missing_project_returns_the_same_not_found_contract():
    body, status, _rename = _endpoint({"display_name": "Renamed"},
                                      project_exists=False)

    assert (status, body) == (404, {
        "code": "PROJECT_NOT_FOUND",
        "error": "Project not found",
    })


def test_rename_rejects_invalid_input_before_mutation():
    body, status, rename = _endpoint({"display_name": "  "})

    assert status == 400
    assert body["code"] == "INVALID_INPUT"
    rename.assert_not_called()
