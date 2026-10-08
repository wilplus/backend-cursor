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
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from services.data_purge_registry import DEPENDENCIES, dependency_by_code

USER_KEYED = {
    "coach_readings": ("coach_readings", "coach_id"),
    "lend_your_ear_answers": ("lend_your_ear_answers", "listener_user_id"),
    "delayed_measure_votes": ("delayed_measure_votes", "rater_id"),
    "coach_exercise_preference_by_coach": ("coach_exercise_preference", "coach_id"),
    "error_presence_audit_by_coach": ("error_presence_audit", "coach_id"),
    "coach_block_pick_by_coach": ("coach_block_pick", "coach_id"),
    "coach_clip_exposures": ("coach_clip_exposures", "coach_id"),
}


def _by_code():
    return {d.code: d for d in DEPENDENCIES}


def test_user_keyed_rows_use_the_user_locator():
    by = _by_code()
    for code, (relation, column) in USER_KEYED.items():
        dep = by[code]
        assert (dep.relation, dep.selector_column, dep.locator_kind) == (
            relation, column, "user"), code
        assert dep.disposition == "delete", code


def test_an_account_graph_reaches_them_by_user_id():
    graph = SubjectGraph(principal_ids=("p-1",), user_ids=("u-1",))
    by = _by_code()
    for code in USER_KEYED:
        assert graph.values(by[code].locator_kind) == ("u-1",), code


#: A real account: its owner principal's id is not its user id.
ACCOUNT = SubjectGraph(principal_ids=("principal-1",), user_ids=("user-1",))
#: The project graph lists no principal and no user (data_purge_project_scope).
PROJECT = SubjectGraph(principal_ids=(), project_ids=("project-1",),
                       take_ids=("take-1",))

#: `principal` locators on a column not named `*principal_id`, each checked
#: by hand: the principal table's own key, and feedback_revisions.rater_id,
#: whose coach rows name the coach's owner principal (the coaching bundle's
#: p_reviewer_principal_id). Its owner rows (record_root_phrase_skip_v1) name
#: a user id and are reached by feedback_revision_owner_raters (0448).
PRINCIPAL_KEYS_BY_OTHER_NAMES = frozenset({
    ("owner_principals", "id"),
    ("feedback_revisions", "rater_id"),
})


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
def test_each_is_addressed_by_the_user_locator_and_nothing_else_moved(code):
    dependency = dependency_by_code(code)
    assert dependency is not None
    assert (dependency.relation, dependency.selector_column) == USER_KEYED[code]
    assert dependency.locator_kind == "user"
    assert (dependency.disposition, dependency.target_kind,
            dependency.delete_order, dependency.ruled_by) == (
        "delete", "derived_feedback", 35, None)


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


@pytest.mark.parametrize("code", sorted(USER_KEYED))
def test_a_project_purge_leaves_them_with_the_account(code):
    orchestrator, client, dependency = _purge(code, ProjectPurgeOrchestrator)
    relation = dependency.relation

    target = orchestrator._dependency_target(
        dependency, PROJECT, frozenset({relation}))

    assert target is not None
    assert target.target_kind != "unknown"
    assert target.initial_match_count == 0
    orchestrator._resolve_dependency({"id": "target-1", **target.payload()},
                                     PROJECT)
    assert len(client.tables[relation]) == 3
    assert [call["p_state"] for call in client.resolved] == ["not_found"]


def test_a_principal_locator_addresses_only_a_column_that_holds_one():
    """A column named for a user, a coach, a listener or a rater holds
    request.user_id. A table keyed that way says so with `user`; a column
    that holds a principal under another name is checked and listed above."""
    for dependency in DEPENDENCIES:
        named_for_a_principal = dependency.selector_column.endswith("principal_id")
        key = (dependency.relation, dependency.selector_column)
        if dependency.locator_kind == "principal":
            assert named_for_a_principal or key in PRINCIPAL_KEYS_BY_OTHER_NAMES, (
                dependency.code)
        else:
            assert not named_for_a_principal, dependency.code
