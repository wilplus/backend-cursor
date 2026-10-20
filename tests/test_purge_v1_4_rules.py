"""
STORY    As the founder, I want the v1.4 retention rules to change nothing
         until I run the signed script, and then product records to be
         deleted and job evidence kept, so that nothing changes before I
         sign (deletion).
OUTCOME
  O1  Every ruled dependency names one of the two signed rules with that
      rule's category; before the rule only the job row was ever anything
      but external_review; the signed schedule names every one of them.
  O2  Inert until signed: with no rule, a rule of the wrong category or a
      withdrawn rule, a product record stops the erasure for review and the
      job row is a plain delete, exactly as before v1.4, in the account
      scope; in the project scope the record stops the purge as unplaced.
  O3  With the rules active, a product record is deleted under its rule
      (only my rows; in a project purge only that project's) and the job is
      kept under the job-evidence rule.
  O4  A rule withdrawn after the freeze deletes nothing.
PROVES   O1 -> test_every_ruled_dependency_names_a_signed_rule_and_the_schedule
         O2 -> test_until_the_rule_is_active_nothing_changes
         O3 -> test_with_the_rules_active_records_go_and_jobs_stay
               test_with_its_rule_a_project_record_goes_with_the_project
         O4 -> test_a_rule_withdrawn_after_the_freeze_deletes_nothing
WHY      Founder 2026-10-05, decisions log N48.4 Q15 A.

Python orchestrator only, over the in-memory `PurgeDb` of
tests/test_purge_user_locators.py. The real tables, scripts/
phase1_retention_rules_v1_4.sql and migration 0424's trigger are proved on
the released lane by tests/test_product_records_purge_postgres.py.
"""
from __future__ import annotations

import pathlib

import pytest

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from services.data_purge_registry import (
    DEPENDENCIES,
    JOB_EVIDENCE,
    JOB_EVIDENCE_RULE,
    PRODUCT_RECORDS,
    PRODUCT_RECORDS_RULE,
    RULE_CATEGORY,
)
from tests.test_purge_user_locators import PurgeDb, erase, inventory

SCHEDULE = (pathlib.Path(__file__).resolve().parents[1] / "legal" / "phase1-2026.1"
            / "20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md")
RECORD, JOB = "dependency:moment_unlocks_review", "dependency:phase1_jobs"
RULE_P = {"id": "rule-p", "rule_code": PRODUCT_RECORDS_RULE,
          "evidence_category": PRODUCT_RECORDS, "active": True}
RULE_J = {"id": "rule-j", "rule_code": JOB_EVIDENCE_RULE,
          "evidence_category": JOB_EVIDENCE, "active": True}


def _tables(rules):
    return {
        "data_retention_rules": rules,
        # A product record (moment_unlocks): mine in two projects, and a
        # stranger's.
        "moment_unlocks": [
            {"id": "u-1", "user_id": "user-1", "arc_id": "project-1"},
            {"id": "u-2", "user_id": "user-1", "arc_id": "project-2"},
            {"id": "u-x", "user_id": "user-2", "arc_id": "project-x"},
        ],
        "phase1_processing_jobs": [
            {"id": "job-1", "acquisition_principal_id": "principal-1"}],
    }


def test_every_ruled_dependency_names_a_signed_rule_and_the_schedule():
    ruled = [d for d in DEPENDENCIES if d.ruled_by]
    schedule = SCHEDULE.read_text()
    assert ruled
    for dependency in ruled:
        assert RULE_CATEGORY[dependency.ruled_by] == dependency.retention_category
        assert dependency.code in schedule or dependency.relation in schedule, (
            dependency.code)
    assert sorted({d.code for d in ruled if d.before_rule != "external_review"}) == [
        "phase1_jobs"]


@pytest.mark.parametrize("rules", [
    [],
    [{**RULE_P, "evidence_category": JOB_EVIDENCE},
     {**RULE_J, "evidence_category": PRODUCT_RECORDS}],
    [{**RULE_P, "active": False}, {**RULE_J, "active": False}],
], ids=["no_rule", "wrong_category", "withdrawn"])
def test_until_the_rule_is_active_nothing_changes(rules):
    account = inventory(PurgeDb(_tables(rules)))
    assert account[RECORD].target_kind == "unknown"
    assert account[RECORD].metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"
    assert account[JOB].metadata["disposition"] == "delete"
    assert "retention_rule_id" not in account[JOB].metadata

    project = inventory(PurgeDb(_tables(rules), kind="project_deletion"),
                        ProjectPurgeOrchestrator)
    assert project[RECORD].metadata["reason_code"] == "PROJECT_SCOPE_UNRESOLVED"


def test_with_the_rules_active_records_go_and_jobs_stay():
    database = PurgeDb(_tables([RULE_P, RULE_J]))

    erase(database)

    assert [row["id"] for row in database.tables["moment_unlocks"]] == ["u-x"]
    assert database.target("moment_unlocks_review")["state"] == "deleted"
    assert database.target("moment_unlocks_review")["metadata"][
        "retention_rule_id"] == "rule-p"
    assert database.tables["phase1_processing_jobs"] == [
        {"id": "job-1", "acquisition_principal_id": "principal-1"}]
    assert database.target("phase1_jobs")["state"] == "retained"
    assert database.target("phase1_jobs")["metadata"]["retention_rule_id"] == "rule-j"


def test_with_its_rule_a_project_record_goes_with_the_project():
    database = PurgeDb(_tables([RULE_P, RULE_J]), kind="project_deletion")

    erase(database, ProjectPurgeOrchestrator)

    assert [row["id"] for row in database.tables["moment_unlocks"]] == ["u-2", "u-x"]
    assert database.target("moment_unlocks_review")["metadata"][
        "locator_values"] == ["project-1"]


def test_a_rule_withdrawn_after_the_freeze_deletes_nothing():
    database = PurgeDb(_tables([RULE_P, RULE_J]))
    orchestrator = DataPurgeOrchestrator(database)
    orchestrator.freeze_inventory("purge-1")

    database.tables["data_retention_rules"][0]["active"] = False
    orchestrator.resolve_targets("purge-1")

    assert len(database.tables["moment_unlocks"]) == 3
    target = database.target("moment_unlocks_review")
    assert (target["state"], target["last_error_code"]) == (
        "failed", "RETENTION_RULE_INACTIVE")
