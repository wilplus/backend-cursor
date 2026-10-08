"""A speaker's skip rows stop a deletion before anything is erased.

record_root_phrase_skip_v1 writes feedback_revisions rows with
rater_role='owner', rater_id = the speaker's USER id and
acquisition_principal_id NULL. The two older entries address that table by
principal, and an owner principal's id is its own random UUID, never the
user's, so an account purge counted none of these rows. The lineage wipe
then raised on them (the table's guard refuses every UPDATE since 0327) and
the erasure stalled after deleting everything else (rehearsed 2026-10-08).

Founder 2026-10-08: such a row stops an account deletion, and a project
deletion, for review before anything is erased. Pins:
  * `feedback_revision_owner_raters` reaches the rows by the `user` locator;
  * an account purge whose principal id is not its user id files them as
    an unknown target (the erasure stops before the first destructive call),
    and does not count a coach's rows, which name a principal;
  * a project purge stops for them too: the code is left unplaced.
"""
from __future__ import annotations

from types import SimpleNamespace

from services import data_purge_project_scope as scope
from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from services.data_purge_registry import dependency_by_code

CODE = "feedback_revision_owner_raters"

#: A real account: its owner principal's id is not its user id.
ACCOUNT = SubjectGraph(principal_ids=("principal-1",), user_ids=("user-1",))
PROJECT = SubjectGraph(principal_ids=(), project_ids=("project-1",),
                       take_ids=("take-1",))


class _Query:
    """One PostgREST read on an in-memory table, filtered by eq/in_."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._filters: list[tuple[str, set[str]]] = []

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self._filters.append((column, {str(value)}))
        return self

    def in_(self, column, values):
        self._filters.append((column, {str(value) for value in values}))
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        return SimpleNamespace(data=[
            row for row in self._rows
            if all(str(row.get(column)) in wanted
                   for column, wanted in self._filters)])


class _Client:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def table(self, name):
        assert name == "feedback_revisions", name
        return _Query(self.rows)


def _rows():
    return [
        # The speaker's skips: their user id, no acquisition principal.
        {"id": "skip-1", "rater_role": "owner", "rater_id": "user-1",
         "acquisition_principal_id": None},
        {"id": "skip-2", "rater_role": "owner", "rater_id": "user-1",
         "acquisition_principal_id": None},
        # A coach's row about someone else names the coach's principal.
        {"id": "coach-1", "rater_role": "coach", "rater_id": "principal-9",
         "acquisition_principal_id": "principal-8"},
        # Someone else's skip.
        {"id": "skip-x", "rater_role": "owner", "rater_id": "user-2",
         "acquisition_principal_id": None},
    ]


def _target(cls, graph, code=CODE):
    orchestrator = cls(SimpleNamespace(client=_Client(_rows())))
    if cls is ProjectPurgeOrchestrator:
        orchestrator._principal_id = "principal-1"
        orchestrator._account_graph = ACCOUNT
    dependency = dependency_by_code(code)
    assert dependency is not None
    return orchestrator._dependency_target(
        dependency, graph, frozenset({"feedback_revisions"}))


def test_the_entry_reads_rater_id_by_user_and_stops_for_review():
    dependency = dependency_by_code(CODE)
    assert dependency is not None
    assert (dependency.relation, dependency.selector_column,
            dependency.locator_kind, dependency.disposition,
            dependency.ruled_by) == (
        "feedback_revisions", "rater_id", "user", "external_review", None)


def test_the_principal_entries_miss_the_skips():
    """Why the entry exists: addressed by principal, the account's skips
    count zero, because no principal id equals a user id."""
    for code in ("feedback_revision_subjects", "feedback_revision_reviewers"):
        target = _target(DataPurgeOrchestrator, ACCOUNT, code)
        assert target is not None and target.initial_match_count == 0, code


def test_an_account_purge_stops_before_erasing_anything():
    target = _target(DataPurgeOrchestrator, ACCOUNT)

    assert target is not None
    assert target.target_kind == "unknown"
    assert target.target_ref == f"dependency:{CODE}"
    assert target.initial_match_count == 2
    assert target.metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"
    assert target.metadata["locator_values"] == ["user-1"]


def test_an_account_without_skips_is_not_stopped():
    graph = SubjectGraph(principal_ids=("principal-9",), user_ids=("user-9",))
    target = _target(DataPurgeOrchestrator, graph)

    assert target is not None
    assert target.target_kind == "derived_feedback"
    assert target.initial_match_count == 0


def test_a_project_purge_stops_for_them_too():
    assert CODE not in (
        set(scope.PROJECT_SELECTORS) | scope.ACCOUNT_LEVEL
        | set(scope.WIPED_WITH_PARENT) | set(scope.PROJECT_HOLDS))
    target = _target(ProjectPurgeOrchestrator, PROJECT)

    assert target is not None
    assert target.target_kind == "unknown"
    assert target.initial_match_count == 2
    assert target.metadata["reason_code"] == "PROJECT_SCOPE_UNRESOLVED"
