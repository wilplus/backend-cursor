"""
STORY    As a speaker deleting my account, I want rows saved under my user id
         (coach readings, listener answers, votes) deleted too, so that
         nothing outlives my account (deletion).
OUTCOME
  O1  An account erasure whose principal id is not its user id deletes
      exactly my rows in each user-keyed table and leaves everyone else's.
  O2  A project erasure leaves those rows: they belong to the account.
  O3  A `principal` locator addresses only a column that holds a principal,
      so the next table keyed by a user id cannot be filed under it again.
PROVES   O1 -> test_an_account_erasure_deletes_the_rows_kept_under_my_user_id
         O2 -> test_a_project_erasure_leaves_the_rows_kept_under_my_user_id
         O3 -> test_a_principal_locator_only_points_at_a_principal_column
WHY      Found 2026-10-06 while building 0432: these tables were filed under
         `principal`, matched nothing and outlived a deleted account.

This file covers the PYTHON orchestrator only, through its public steps
(build_inventory, freeze_inventory, resolve_targets). `PurgeDb` below is an
in-memory stand-in for the tables and the purge RPCs, NOT the SQL: the freeze
and resolve functions are proved on the released lane by
tests/test_purge_scope_postgres.py and tests/test_project_purge_postgres.py.
tests/test_purge_owner_skip_rows.py, tests/test_purge_v1_4_rules.py and
tests/test_project_purge_scope.py import `PurgeDb` from here.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from services.data_purge_registry import DEPENDENCIES

#: code -> (relation, the column holding request.user_id)
USER_KEYED = {
    "coach_readings": ("coach_readings", "coach_id"),
    "lend_your_ear_answers": ("lend_your_ear_answers", "listener_user_id"),
    "delayed_measure_votes": ("delayed_measure_votes", "rater_id"),
    "coach_exercise_preference_by_coach": ("coach_exercise_preference", "coach_id"),
    "error_presence_audit_by_coach": ("error_presence_audit", "coach_id"),
    "coach_block_pick_by_coach": ("coach_block_pick", "coach_id"),
    "coach_clip_exposures": ("coach_clip_exposures", "coach_id"),
}

#: A real account: its owner principal's id is not its user id.
ACCOUNT = SubjectGraph(principal_ids=("principal-1",), user_ids=("user-1",),
                       project_ids=("project-1",), take_ids=("take-1",))
#: One project of that account, as resolve_phase1_purge_project_graph_v1
#: returns it: no principal, user, speaker or permit, by design.
PROJECT = SubjectGraph(principal_ids=(), project_ids=("project-1",),
                       take_ids=("take-1",))


class _Query:
    """One PostgREST call on an in-memory table: select, delete or update,
    filtered by eq/in_, paged by range."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._filters: list[tuple[str, set[str]]] = []
        self._action: tuple[str, dict] | None = None
        self._window: tuple[int, int] | None = None

    def select(self, *_columns):
        return self

    def delete(self):
        self._action = ("delete", {})
        return self

    def update(self, values):
        self._action = ("update", dict(values))
        return self

    def eq(self, column, value):
        self._filters.append((column, {str(value)}))
        return self

    def in_(self, column, values):
        self._filters.append((column, {str(value) for value in values}))
        return self

    def limit(self, _count):
        return self

    def range(self, start, end):
        self._window = (start, end)
        return self

    def _matches(self, row: dict) -> bool:
        return all(str(row.get(column)) in wanted
                   for column, wanted in self._filters)

    def execute(self):
        found = [row for row in self._rows if self._matches(row)]
        if self._action and self._action[0] == "delete":
            self._rows[:] = [row for row in self._rows if not self._matches(row)]
        elif self._action:
            for row in found:
                row.update(self._action[1])
        elif self._window is not None:
            found = found[self._window[0]:self._window[1] + 1]
        return SimpleNamespace(data=found)


class PurgeDb:
    """In-memory tables plus the RPCs a purge calls. The catalog lists the
    tables given; the freeze files `unknown` targets as unknown and the rest
    as pending, as freeze_phase1_purge_inventory_v4 does. Not the SQL."""

    def __init__(self, tables: dict[str, list[dict]], *, kind="account_deletion",
                 account: SubjectGraph = ACCOUNT, project: SubjectGraph = PROJECT):
        self.tables = {name: [dict(row) for row in rows]
                       for name, rows in tables.items()}
        self.tables["data_purge_requests"] = [{
            "id": "purge-1", "acquisition_principal_id": account.principal_ids[0],
            "trigger_kind": kind, "state": "requested",
            "project_id": project.project_ids[0] if kind == "project_deletion" else None,
        }]
        self.account, self.project = account, project
        self.client = self

    def table(self, name):
        return _Query(self.tables.setdefault(name, []))

    def rpc(self, name, params):
        data = getattr(self, f"_{name}")(params)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))

    def _audit_phase1_purge_catalog_v1(self, _params):
        return {"catalog_sha256": "catalog-1", "unknown_relations": [],
                "existing_allowlisted_relations": sorted(self.tables)}

    def _resolve_phase1_purge_subject_graph_v3(self, _params):
        return self.account.payload()

    def _resolve_phase1_purge_project_graph_v1(self, _params):
        return self.project.payload()

    def _freeze_phase1_purge_inventory_v4(self, params):
        self.tables["data_purge_inventory_manifests"] = [{
            "purge_request_id": params["p_purge_request_id"],
            "resolver_version": params["p_resolver_version"],
            "dependency_manifest_sha256": params["p_dependency_manifest_sha256"],
            "catalog_sha256": params["p_catalog_sha256"],
            "subject_graph": params["p_subject_graph"],
        }]
        self.tables["data_purge_targets"] = [{
            **target, "id": f"target-{n}",
            "purge_request_id": params["p_purge_request_id"],
            "state": "unknown" if target["target_kind"] == "unknown" else "pending",
            "remaining_match_count": target["initial_match_count"],
        } for n, target in enumerate(params["p_targets"])]
        return {"state": "frozen"}

    _freeze_phase1_project_purge_inventory_v1 = _freeze_phase1_purge_inventory_v4

    def _resolve_phase1_purge_target_v3(self, params):
        for row in self.tables["data_purge_targets"]:
            if row["id"] == params["p_target_id"]:
                row.update(state=params["p_state"],
                           remaining_match_count=params["p_remaining_match_count"],
                           last_error_code=params["p_last_error_code"])
        return None

    # ── what a test reads back ──

    def target(self, code: str) -> dict:
        """The frozen target for one registry code."""
        return next(row for row in self.tables["data_purge_targets"]
                    if row["target_ref"] == f"dependency:{code}")


def inventory(database: PurgeDb, cls=DataPurgeOrchestrator) -> dict:
    """build_inventory's targets, by target_ref."""
    built = cls(database).build_inventory("purge-1")
    return {target.target_ref: target for target in built["targets"]}


def erase(database: PurgeDb, cls=DataPurgeOrchestrator) -> None:
    """Freeze, then resolve (finalize is the SQL's to judge)."""
    orchestrator = cls(database)
    orchestrator.freeze_inventory("purge-1")
    orchestrator.resolve_targets("purge-1")


def _mine_and_theirs(code):
    relation, column = USER_KEYED[code]
    return {relation: [{"id": "mine-1", column: "user-1"},
                       {"id": "mine-2", column: "user-1"},
                       {"id": "theirs", column: "user-2"}]}


@pytest.mark.parametrize("code", sorted(USER_KEYED))
def test_an_account_erasure_deletes_the_rows_kept_under_my_user_id(code):
    database = PurgeDb(_mine_and_theirs(code))

    erase(database)

    relation = USER_KEYED[code][0]
    assert [row["id"] for row in database.tables[relation]] == ["theirs"]
    assert database.target(code)["initial_match_count"] == 2
    assert database.target(code)["state"] == "deleted"


@pytest.mark.parametrize("code", sorted(USER_KEYED))
def test_a_project_erasure_leaves_the_rows_kept_under_my_user_id(code):
    database = PurgeDb(_mine_and_theirs(code), kind="project_deletion")

    erase(database, ProjectPurgeOrchestrator)

    relation = USER_KEYED[code][0]
    assert [row["id"] for row in database.tables[relation]] == [
        "mine-1", "mine-2", "theirs"]
    assert database.target(code)["state"] == "not_found"


#: The two reviewed exceptions: the principal table's own id, and the mixed
#: rater_id whose coach rows name a principal (feedback_revision_reviewers).
PRINCIPAL_COLUMN_EXCEPTIONS = {("owner_principals", "id"),
                               ("feedback_revisions", "rater_id")}


def test_a_principal_locator_only_points_at_a_principal_column():
    misfiled = [
        (dependency.code, dependency.selector_column)
        for dependency in DEPENDENCIES
        if dependency.locator_kind == "principal"
        and "principal" not in dependency.selector_column
        and (dependency.relation, dependency.selector_column)
        not in PRINCIPAL_COLUMN_EXCEPTIONS
    ]
    assert misfiled == []
