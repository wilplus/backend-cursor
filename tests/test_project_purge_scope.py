"""
STORY    As a speaker deleting one project, I want only that project's rows
         deleted, and any account table the project purge cannot place to
         stop it for review, so that a project deletion never silently keeps
         a project's rows and never wipes my account (deletion).
OUTCOME
  O1  Every name the project scope places (re-pointed, account-level,
      wiped with its parent, held) is a real account-keyed registry entry,
      placed exactly once, and every re-pointed locator is one the project
      graph fills.
  O2  A re-pointed table counts only this project's rows; an account table
      nobody placed, where the account has rows, stops the purge for review.
  O3  The project orchestrator refuses an account request and the account
      orchestrator refuses a project request; each request is routed to its
      own orchestrator.
PROVES   O1 -> test_every_placement_names_an_account_keyed_entry_once
         O2 -> test_a_project_purge_counts_its_project_and_stops_on_the_unplaced
         O3 -> test_neither_orchestrator_runs_the_others_request
WHY      P1-B, decisions log N8/N12: the project graph lists no principal or
         user, so an unplaced account-keyed table would reach no row at all.

Python orchestrator only, over the in-memory `PurgeDb` of
tests/test_purge_user_locators.py; the real project purge runs on the
released lane in tests/test_project_purge_postgres.py. Whether each
re-pointed column exists in the schema is not checked here: that purge
would fail on a missing column there.
"""
from __future__ import annotations

from collections import Counter

import pytest

from services import data_purge_project_scope as scope
from services.data_purge import DataPurgeOrchestrator
from services.data_purge_registry import dependency_by_code
from tests.test_purge_user_locators import PurgeDb, inventory

#: The locators resolve_phase1_purge_project_graph_v1 fills.
PROJECT_GRAPH_LOCATORS = {"project", "take", "job", "snippet",
                          "practice_attempt"}


def test_every_placement_names_an_account_keyed_entry_once():
    placed = Counter([*scope.PROJECT_SELECTORS, *scope.ACCOUNT_LEVEL,
                      *scope.WIPED_WITH_PARENT, *scope.PROJECT_HOLDS])
    assert [code for code, n in placed.items() if n > 1] == []
    assert sorted(set(placed) - scope.account_keyed_codes()) == []
    for code, (_column, locator) in {**scope.PROJECT_SELECTORS,
                                     **scope.PROJECT_HOLDS}.items():
        assert locator in PROJECT_GRAPH_LOCATORS, code
    for code, parent in scope.WIPED_WITH_PARENT.items():
        assert dependency_by_code(parent) is not None, code


def test_a_project_purge_counts_its_project_and_stops_on_the_unplaced():
    database = PurgeDb({
        # Re-pointed from the user id to the Take: only this project's Take.
        "v2_sessions": [{"id": "take-1", "user_id": "user-1"},
                        {"id": "take-2", "user_id": "user-1"}],
        # An account-keyed lineage nobody placed (separately governed),
        # holding a row of this account.
        "feedback_revisions": [{"id": "rev-1", "rater_id": "principal-7",
                                "acquisition_principal_id": "principal-1"}],
    }, kind="project_deletion")

    targets = inventory(database, scope.ProjectPurgeOrchestrator)

    sessions = targets["dependency:v2_sessions"]
    assert (sessions.initial_match_count, sessions.metadata["locator_values"]) == (
        1, ["take-1"])
    unplaced = targets["dependency:feedback_revision_subjects"]
    assert unplaced.target_kind == "unknown"
    assert unplaced.metadata["reason_code"] == "PROJECT_SCOPE_UNRESOLVED"


@pytest.mark.parametrize("kind,wrong,right", [
    ("account_deletion", scope.ProjectPurgeOrchestrator, DataPurgeOrchestrator),
    ("project_deletion", DataPurgeOrchestrator, scope.ProjectPurgeOrchestrator),
])
def test_neither_orchestrator_runs_the_others_request(kind, wrong, right):
    database = PurgeDb({}, kind=kind)
    with pytest.raises(RuntimeError,
                       match="PURGE_NOT_A_PROJECT_DELETION|PURGE_SCOPE_MISMATCH"):
        wrong(database).build_inventory("purge-1")
    assert type(scope.orchestrator_for(database, "purge-1")) is right
