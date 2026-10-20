"""
STORY    As a speaker, I want to archive a project so it leaves my list and
         can be restored, so that my list stays tidy without losing anything.
OUTCOME
  O1  Archive stamps archived_at only on the owner's own, not-erased project.
  O2  Restore clears archived_at on that same project.
  O3  A project that is not the owner's (or is erased) is a 404.
  O4  The list hides an archived project; Data & consent (include_archived)
      still lists it, marked archived.
PROVES   O1 -> test_archive_touches_only_the_owners_live_project
         O2 -> test_restore_brings_it_back
         O3 -> test_not_the_owners_or_erased_is_404
         O4 -> test_the_list_hides_an_archived_project,
               test_data_and_consent_still_lists_it
WHY      Founder 2026-09-26, decisions log N14.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.project_archive import ProjectArchiveError, ProjectArchiveService

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


OWNER_FILTERS = [("eq", "id", PROJECT), ("eq", "owner_principal_id", "p1"),
                 ("is", "tombstoned_at", "null")]


class ServiceTests(unittest.TestCase):

    def test_archive_touches_only_the_owners_live_project(self):
        service, query, client = _service(
            [{"id": PROJECT, "archived_at": "2026-09-26T10:00:00+00:00"}])
        out = service.archive("p1", PROJECT)
        client.table.assert_called_once_with("projects")
        self.assertTrue(query.payload["archived_at"])
        self.assertEqual(query.filters, OWNER_FILTERS)
        self.assertEqual(out["project_id"], PROJECT)

    def test_restore_brings_it_back(self):
        service, query, _client = _service([{"id": PROJECT, "archived_at": None}])
        out = service.restore("p1", PROJECT)
        self.assertEqual(query.payload, {"archived_at": None})
        self.assertEqual(query.filters, OWNER_FILTERS)
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

    def test_data_and_consent_still_lists_it(self):
        out = self._feed(True)
        self.assertEqual([(t["arc_id"], t["archived"]) for t in out],
                         [(PROJECT, False), (OTHER, True)])
