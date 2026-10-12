"""A speaker's skip rows are kept as an empty receipt (N12).

record_root_phrase_skip_v1 writes feedback_revisions rows with
rater_role='owner', rater_id = the speaker's USER id and
acquisition_principal_id NULL. The two older entries address that table by
principal, and an owner principal's id is its own random UUID, never the
user's, so an account purge counted none of these rows. The lineage wipe
then raised on them (the table's guard refuses every UPDATE since 0327) and
the erasure stalled after deleting everything else (rehearsed 2026-10-08).

Founder 2026-10-08 (decision tree Q1/Q2) first made such a row stop the
deletion for review; Q3/Q4 (YES, "empty receipt") then had 0448 give the
table a guard that lets the wipe empty an owner row's payload. Pins:
  * `feedback_revision_owner_raters` reaches the rows by the `user` locator
    and is a tombstone under the deletion-evidence rule, wiped by the
    lineage function (feedback_revisions is a lineage tombstone);
  * an account purge whose principal id is not its user id counts them as a
    tombstone target, not an unknown one, and does not count a coach's rows,
    which name a principal (those still stop the inventory);
  * a project purge leaves them to the wipe of the project's evidence spans
    (WIPED_WITH_PARENT), not to the account-wide stop.
tests/test_a_skip_keeps_an_empty_receipt_postgres.py proves the wipe on the
real schema.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from services.data_purge_registry import dependency_by_code

CODE = "feedback_revision_owner_raters"

#: A real account: its owner principal's id is not its user id.
ACCOUNT = SubjectGraph(principal_ids=("principal-1",), user_ids=("user-1",))


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
        if name == "data_retention_rules":
            return _Query([{"id": "rule-1", "rule_code": "deletion-evidence",
                            "evidence_category": "deletion_evidence",
                            "active": True}])
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
        dependency, graph,
        frozenset({"feedback_revisions", "data_retention_rules"}))


def test_an_account_purge_keeps_them_as_a_receipt():
    target = _target(DataPurgeOrchestrator, ACCOUNT)

    assert target is not None
    assert target.target_kind == "derived_feedback"
    assert target.target_ref == f"dependency:{CODE}"
    assert target.initial_match_count == 2
    assert target.metadata["disposition"] == "tombstone"
    assert target.metadata["retention_rule_id"] == "rule-1"
    assert target.metadata["locator_values"] == ["user-1"]
    assert "reason_code" not in target.metadata
