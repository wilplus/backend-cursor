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
from unittest.mock import MagicMock

from services.project_archive import ProjectArchiveError, ProjectArchiveService

try:
    from flask import Flask, request

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
