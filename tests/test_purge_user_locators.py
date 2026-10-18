"""Rows keyed by a signed-in user's id are found by the `user` locator.

coach_id, listener_user_id and rater_id on the 0409-0411 tables hold
request.user_id, never an owner principal's id. Under the `principal`
locator they matched nothing and outlived a deleted account (found
2026-10-06 while building 0432). This pins them to `user`, and checks
that an account's purge graph reaches them through its user ids.

Also, against an in-memory table: an account purge whose principal id is
not its user id counts, freezes and deletes exactly that account's rows
(addressed as a principal it counted none); a project purge leaves them;
and a `principal` locator addresses only a column that holds one, so the
next table keyed by a user id cannot repeat this unnoticed.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_registry import dependency_by_code

USER_KEYED = {
    "coach_readings": ("coach_readings", "coach_id"),
    "lend_your_ear_answers": ("lend_your_ear_answers", "listener_user_id"),
    "delayed_measure_votes": ("delayed_measure_votes", "rater_id"),
    "coach_exercise_preference_by_coach": ("coach_exercise_preference", "coach_id"),
    "error_presence_audit_by_coach": ("error_presence_audit", "coach_id"),
    "coach_block_pick_by_coach": ("coach_block_pick", "coach_id"),
    "coach_clip_exposures": ("coach_clip_exposures", "coach_id"),
    # A speaker's own coach videos, set and praise lines (0477, N77).
    "speaker_exercise_set": ("speaker_exercise_set", "owner_user_id"),
    "owned_praise_lines": ("feedback_catalogue", "owner_user_id"),
    "owned_exercise_versions": ("diagnostic_exercise_version", "owner_user_id"),
    "owned_exercises": ("diagnostic_exercise", "owner_user_id"),
}


#: A real account: its owner principal's id is not its user id.
ACCOUNT = SubjectGraph(principal_ids=("principal-1",), user_ids=("user-1",))


class _Query:
    """One PostgREST call on an in-memory table: select or delete, filtered
    by eq/in_, paged by range."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._filters: list[tuple[str, set[str]]] = []
        self._deleting = False
        self._window: tuple[int, int] | None = None

    def select(self, _columns):
        return self

    def delete(self):
        self._deleting = True
        return self

    def eq(self, column, value):
        self._filters.append((column, {str(value)}))
        return self

    def in_(self, column, values):
        self._filters.append((column, {str(value) for value in values}))
        return self

    def range(self, start, end):
        self._window = (start, end)
        return self

    def _matches(self, row: dict) -> bool:
        return all(str(row.get(column)) in wanted
                   for column, wanted in self._filters)

    def execute(self):
        found = [row for row in self._rows if self._matches(row)]
        if self._deleting:
            self._rows[:] = [row for row in self._rows if not self._matches(row)]
        elif self._window is not None:
            found = found[self._window[0]:self._window[1] + 1]
        return SimpleNamespace(data=found)


class _Client:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables
        self.resolved: list[dict] = []

    def table(self, name):
        return _Query(self.tables.setdefault(name, []))

    def rpc(self, name, params):
        assert name == "resolve_phase1_purge_target_v3", name
        self.resolved.append(dict(params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=None))


def _purge(code, cls=DataPurgeOrchestrator):
    """An orchestrator over one table holding two of this account's rows
    and one of someone else's."""
    dependency = dependency_by_code(code)
    assert dependency is not None, code
    column = dependency.selector_column
    client = _Client({dependency.relation: [
        {"id": "mine-1", column: "user-1"},
        {"id": "mine-2", column: "user-1"},
        {"id": "theirs", column: "user-2"},
    ]})
    return cls(SimpleNamespace(client=client)), client, dependency


@pytest.mark.parametrize("code", sorted(USER_KEYED))
def test_an_account_purge_deletes_the_rows_kept_under_its_user_id(code):
    orchestrator, client, dependency = _purge(code)
    relation = dependency.relation

    target = orchestrator._dependency_target(
        dependency, ACCOUNT, frozenset({relation}))

    assert target is not None
    assert target.initial_match_count == 2
    # What freeze_phase1_purge_inventory_v4 compares with the graph's user_ids.
    assert target.metadata["locator_kind"] == "user"
    assert target.metadata["locator_values"] == ["user-1"]

    orchestrator._resolve_dependency({"id": "target-1", **target.payload()},
                                     ACCOUNT)

    assert [row["id"] for row in client.tables[relation]] == ["theirs"]
    assert [(call["p_state"], call["p_remaining_match_count"])
            for call in client.resolved] == [("deleted", 0)]
