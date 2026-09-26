"""Archive a project (founder 2026-09-26, decisions log N14).

The ⋯ on each project row offers Archive: the project leaves the list and
nothing else changes. Pinned here: only the owner's live project is touched,
restore brings it back, the list hides archived projects unless Data &
consent asks for them, and a project that is not the owner's is a 404.

Flask-route classes skip locally without app deps and run in CI.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.project_archive import ProjectArchiveError, ProjectArchiveService

try:
    from flask import Flask, request
    from routes.v2 import projects as v2_projects
    from services.canonical_product import OwnerPrincipal
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

PROJECT = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"


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
    return ProjectArchiveService(SimpleNamespace(client=client)), query, client


class ServiceTests(unittest.TestCase):

    def test_archive_touches_only_the_owners_live_project(self):
        service, query, client = _service(
            [{"id": PROJECT, "archived_at": "2026-09-26T10:00:00+00:00"}])
        out = service.archive("p1", PROJECT)
        client.table.assert_called_once_with("projects")
        self.assertEqual(set(query.payload), {"archived_at"})
        self.assertIsNotNone(query.payload["archived_at"])
        self.assertEqual(query.filters, [
            ("eq", "id", PROJECT),
            ("eq", "owner_principal_id", "p1"),
            ("is", "tombstoned_at", "null"),
        ])
        self.assertEqual(out["project_id"], PROJECT)

    def test_restore_clears_the_mark(self):
        service, query, _client = _service(
            [{"id": PROJECT, "archived_at": None}])
        out = service.restore("p1", PROJECT)
        self.assertEqual(query.payload, {"archived_at": None})
        self.assertIsNone(out["archived_at"])

    def test_not_the_owners_or_erased_is_404(self):
        service, _query, _client = _service([])
        with self.assertRaises(ProjectArchiveError) as ctx:
            service.archive("p1", PROJECT)
        self.assertEqual(ctx.exception.status, 404)


class FeedTests(unittest.TestCase):

    def _feed(self, include_archived):
        from services.project_deletion import with_deletion_state

        client = MagicMock()

        def table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.in_.return_value = chain
            rows = {
                "projects": [
                    {"id": PROJECT, "tombstoned_at": None, "archived_at": None},
                    {"id": OTHER, "tombstoned_at": None,
                     "archived_at": "2026-09-26T10:00:00Z"},
                ],
                "project_deletion_requests": [],
            }[name]
            chain.execute.return_value = SimpleNamespace(data=rows)
            return chain

        client.table.side_effect = table
        return with_deletion_state(
            SimpleNamespace(client=client),
            [{"arc_id": PROJECT}, {"arc_id": OTHER}],
            include_archived=include_archived)

    def test_the_list_hides_an_archived_project(self):
        out = self._feed(False)
        self.assertEqual([t["arc_id"] for t in out], [PROJECT])
        self.assertFalse(out[0]["archived"])

    def test_data_and_consent_sees_every_project_marked(self):
        out = self._feed(True)
        self.assertEqual({t["arc_id"]: t["archived"] for t in out},
                         {PROJECT: False, OTHER: True})

    def test_before_the_column_exists_nothing_is_hidden(self):
        from services.project_deletion import ProjectDeletionService

        client = MagicMock()
        chain = client.table.return_value.select.return_value
        chain.in_.return_value = chain
        chain.execute.side_effect = Exception(
            'column projects.archived_at does not exist')
        self.assertEqual(
            ProjectDeletionService(SimpleNamespace(client=client))
            .archived_projects([PROJECT]), set())


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.repo = MagicMock()
        self.repo.owner_for_user.return_value = OwnerPrincipal("p1", "u1", False)
        self.service = MagicMock()
        self._p = [
            patch.object(v2_projects, "ProjectRepository", return_value=self.repo),
            patch.object(v2_projects, "ProjectArchiveService",
                         return_value=self.service),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self, view, project=PROJECT):
        with self.app.test_request_context(method="POST"):
            request.user_id = "u1"
            resp, status = view.__wrapped__(project)
            return resp.get_json(), status

    def test_archive(self):
        self.service.archive.return_value = {
            "project_id": PROJECT, "archived_at": "2026-09-26T10:00:00Z"}
        body, status = self._call(v2_projects.v2_archive_project)
        self.assertEqual((status, body["archived"]), (200, True))
        self.service.archive.assert_called_once_with("p1", PROJECT)

    def test_restore(self):
        self.service.restore.return_value = {
            "project_id": PROJECT, "archived_at": None}
        body, status = self._call(v2_projects.v2_restore_project)
        self.assertEqual((status, body["archived"]), (200, False))

    def test_not_the_owners_project_is_404(self):
        self.service.archive.side_effect = ProjectArchiveError(
            "PROJECT_NOT_FOUND", 404)
        _body, status = self._call(v2_projects.v2_archive_project)
        self.assertEqual(status, 404)

    def test_bad_id_is_400(self):
        _body, status = self._call(v2_projects.v2_archive_project, "nope")
        self.assertEqual(status, 400)
        self.service.archive.assert_not_called()
