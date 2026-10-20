"""
STORY    As a speaker, I want my Take found only when the Take, the project
         and the owner all match, so that no one can read my Take by guessing
         ids.
OUTCOME
  O1  Looking up my Take with the right project but someone else as owner
      returns nothing, because all three ids are checked together.
PROVES   O1 -> test_take_lookup_requires_take_project_and_owner_coordinates_together
"""
from __future__ import annotations

from types import SimpleNamespace

from services.db import DatabaseService


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.table_name = None
        self.filters = []

    def table(self, name):
        self.table_name = name
        return self

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _limit):
        return self

    def execute(self):
        matching = [
            row for row in self.rows
            if all(str(row.get(column)) == str(value)
                   for column, value in self.filters)
        ]
        return SimpleNamespace(data=matching)


def _service(rows):
    service = DatabaseService.__new__(DatabaseService)
    query = _Query(rows)
    service.client = query
    return service, query


def test_take_lookup_requires_take_project_and_owner_coordinates_together():
    service, query = _service([
        {"id": "take-a", "project_id": "project-a",
         "owner_principal_id": "owner-a"},
    ])

    assert service.takes.get_project_take_for_owner(
        "project-a", "take-a", "owner-b") is None
    assert query.table_name == "v2_sessions"
    assert query.filters == [
        ("id", "take-a"),
        ("project_id", "project-a"),
        ("owner_principal_id", "owner-b"),
    ]
