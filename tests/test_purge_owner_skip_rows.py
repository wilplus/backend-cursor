"""
STORY    As a speaker deleting my account, I want my "skip" answers emptied
         but kept as a receipt, so that my erasure finishes instead of
         stalling (deletion).
OUTCOME
  O1  An account erasure finds my skip rows by my user id (not my
      principal) and files them as a tombstone under the deletion-evidence
      rule; someone else's skips and coaches' rows are not counted.
  O2  A coach's own rows in the same table still stop that coach's account
      erasure for review.
  O3  A project erasure leaves my skip rows to the wipe of the project's
      evidence spans: it neither counts them nor stops on them.
PROVES   O1 -> test_an_account_erasure_keeps_my_skips_as_a_receipt
         O2 -> test_a_coachs_rows_still_stop_the_coachs_erasure
         O3 -> test_a_project_erasure_leaves_my_skips_to_the_parent_wipe
WHY      Rehearsed 2026-10-08: the erasure stalled on these rows after
         deleting everything else (founder Q1-Q4, "empty receipt", 0448).

Python orchestrator only (build_inventory), over the in-memory `PurgeDb` of
tests/test_purge_user_locators.py. The wipe itself is proved on the real
schema by tests/test_a_skip_keeps_an_empty_receipt_postgres.py.
"""
from __future__ import annotations

from services.data_purge import SubjectGraph
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from tests.test_purge_user_locators import PurgeDb, inventory

SKIPS = "dependency:feedback_revision_owner_raters"
COACH_ROWS = "dependency:feedback_revision_reviewers"
RULES = [{"id": "rule-1", "rule_code": "deletion-evidence",
          "evidence_category": "deletion_evidence", "active": True}]


def _tables():
    return {"data_retention_rules": RULES, "feedback_revisions": [
        # The speaker's skips: their user id, no acquisition principal
        # (record_root_phrase_skip_v1).
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
    ]}


def test_an_account_erasure_keeps_my_skips_as_a_receipt():
    targets = inventory(PurgeDb(_tables()))

    skips = targets[SKIPS]
    assert skips.initial_match_count == 2
    assert skips.metadata["disposition"] == "tombstone"
    assert skips.metadata["retention_rule_id"] == "rule-1"
    assert skips.metadata["locator_values"] == ["user-1"]
    assert "reason_code" not in skips.metadata
    # Nothing of this table stops the erasure.
    assert targets[COACH_ROWS].initial_match_count == 0
    assert not [t for t in targets.values() if t.target_kind == "unknown"]


def test_a_coachs_rows_still_stop_the_coachs_erasure():
    coach = SubjectGraph(principal_ids=("principal-9",), user_ids=("user-9",))

    targets = inventory(PurgeDb(_tables(), account=coach))

    assert targets[COACH_ROWS].target_kind == "unknown"
    assert targets[COACH_ROWS].metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"
    assert targets[SKIPS].initial_match_count == 0


def test_a_project_erasure_leaves_my_skips_to_the_parent_wipe():
    targets = inventory(PurgeDb(_tables(), kind="project_deletion"),
                        ProjectPurgeOrchestrator)

    skips = targets[SKIPS]
    assert skips.initial_match_count == 0
    assert "reason_code" not in skips.metadata
    assert not [t for t in targets.values() if t.target_kind == "unknown"]
