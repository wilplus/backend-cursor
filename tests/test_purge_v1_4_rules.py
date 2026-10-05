"""Retention schedule v1.4 in the purge, without a database (founder
2026-10-05, decisions log N48.4 Q15 A: product records are deleted with the
account or the project; job evidence is kept 12 months).

The purge change is HELD for the founder's signature in the only way that
matters: it merges inert and switches itself on when
scripts/phase1_retention_rules_v1_4.sql runs. These pin that:

  * the decided set: every ruled dependency names one of the two signed
    rules and that rule's category; only the job row was ever anything but
    external_review before v1.4; what v1.4 leaves for the founder stays
    external_review;
  * until a rule with that exact rule_code and category is ACTIVE, a ruled
    dependency builds exactly the target it built before v1.4, in the account
    and the project scope; a rehearsal or a wrong-category rule opens nothing;
  * with the rules active, a product record is a delete naming its rule and
    job evidence is retained under its own rule, the job row with its events;
  * resolution follows what the freeze decided, and a ruled delete re-checks
    its rule first and deletes nothing if the rule was withdrawn;
  * migration 0424 opens the trigger for exactly three tables, inside a
    running frozen purge, under an active product-records rule; the
    rehearsal lane carries it and the module that proves it on Postgres;
  * retention schedule v1.4 lists every dependency it decides or leaves for
    the founder.

The same behaviour against the real schema:
tests/test_product_records_purge_postgres.py.
"""
from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

import pytest

from scripts.migrate import destructive_statements
from services import data_purge_project_scope as scope
from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_registry import (
    DEPENDENCIES,
    JOB_EVIDENCE,
    JOB_EVIDENCE_RULE,
    PRODUCT_RECORDS,
    PRODUCT_RECORDS_RULE,
    RULE_CATEGORY,
    before_its_rule,
    dependency_by_code,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "migrations"
             / "a_purge_deletes_the_product_records_it_froze.sql").read_text()
SCHEDULE = (ROOT / "legal" / "phase1-2026.1" /
            "20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md")

RULED = [dependency for dependency in DEPENDENCIES if dependency.ruled_by]
RELATIONS = frozenset(d.relation for d in DEPENDENCIES) | {"data_retention_rules"}
ACTIVE = (
    {"id": "rule-p", "rule_code": PRODUCT_RECORDS_RULE,
     "evidence_category": PRODUCT_RECORDS, "active": True},
    {"id": "rule-j", "rule_code": JOB_EVIDENCE_RULE,
     "evidence_category": JOB_EVIDENCE, "active": True},
)
GRAPH = SubjectGraph(
    principal_ids=("principal-1",), user_ids=("user-1",),
    project_ids=("project-1",), take_ids=("take-1",), job_ids=("job-1",),
    snippet_ids=("snippet-1",), delivery_job_ids=("delivery-1",),
)


def _orchestrator(cls=DataPurgeOrchestrator, *, rules=(), rows=3):
    orchestrator = cls(SimpleNamespace(client=object()))
    tables = {"data_retention_rules": [dict(rule) for rule in rules]}

    def read(relation, _columns, *, selector=None, values=(),
             existing_relations=None):
        if existing_relations is not None and relation not in existing_relations:
            return []
        found = tables.get(relation, [])
        if selector:
            wanted = {str(value) for value in values}
            found = [row for row in found if str(row.get(selector)) in wanted]
        return found

    orchestrator._rows = read
    orchestrator._count = (
        lambda _dependency, values, _existing=None: rows if values else 0)
    return orchestrator, tables


# ── the decided set ─────────────────────────────────────────────────────


def test_every_ruled_dependency_names_a_v1_4_rule_and_its_category():
    assert len(RULED) == 50
    for dependency in RULED:
        assert dependency.ruled_by in RULE_CATEGORY, dependency.code
        assert dependency.retention_category == RULE_CATEGORY[dependency.ruled_by]
        expected = "delete" if dependency.ruled_by == PRODUCT_RECORDS_RULE else "retain"
        assert dependency.disposition == expected, dependency.code


def test_only_the_job_row_was_anything_but_external_review_before_v1_4():
    changed = {d.code: d.before_rule for d in RULED
               if d.before_rule != "external_review"}
    assert changed == {"phase1_jobs": "delete"}
    for dependency in DEPENDENCIES:
        if not dependency.ruled_by:
            assert before_its_rule(dependency) is dependency


def test_the_four_tables_that_stopped_every_erasure_are_decided():
    assert {code: dependency_by_code(code).ruled_by for code in (
        "feedback_exposure", "feedback_self_report", "ideal_part_revision",
        "phase1_job_events")} == {
        "feedback_exposure": PRODUCT_RECORDS_RULE,
        "feedback_self_report": PRODUCT_RECORDS_RULE,
        "ideal_part_revision": PRODUCT_RECORDS_RULE,
        "phase1_job_events": JOB_EVIDENCE_RULE,
    }
    # Each event names its job ON DELETE RESTRICT: the job is kept with it.
    assert dependency_by_code("phase1_jobs").ruled_by == JOB_EVIDENCE_RULE


@pytest.mark.parametrize("code", [
    "arc_purchases_review", "admin_uploaded_reference_review",
    "ml_consent_snapshots", "learning_surface_presentations",
    "learning_surface_exposure_receipts",
    "ideal_text_user_edit_cas_operations", "feedback_v3_owner_responses",
    "legacy_snippets_table_review", "retired_stress_corpus",
    "v1_sessions_review", "student_tasks_review", "performance_scores_review",
    "pre_answers_review", "post_answers_review",
])
def test_what_v1_4_leaves_for_the_founder_or_a_check_stays_closed(code):
    dependency = dependency_by_code(code)
    assert dependency.disposition == "external_review"
    assert dependency.ruled_by is None


# ── before the rules are active: exactly as before ──────────────────────


@pytest.mark.parametrize("rules", [
    (),
    # The right code in the wrong category, and an inactive row.
    ({"id": "x", "rule_code": PRODUCT_RECORDS_RULE,
      "evidence_category": JOB_EVIDENCE, "active": True},
     {"id": "y", "rule_code": JOB_EVIDENCE_RULE,
      "evidence_category": JOB_EVIDENCE, "active": False}),
    # A rehearsal row in the right category under another code.
    ({"id": "z", "rule_code": "rehearsal-job_evidence-1",
      "evidence_category": JOB_EVIDENCE, "active": True},
     {"id": "w", "rule_code": "rehearsal-product_records-1",
      "evidence_category": PRODUCT_RECORDS, "active": True}),
])
def test_without_its_rule_a_ruled_dependency_acts_as_before(rules):
    orchestrator, _tables = _orchestrator(rules=rules)
    for dependency in RULED:
        target = orchestrator._dependency_target(dependency, GRAPH, RELATIONS)
        before = before_its_rule(dependency)
        assert target.metadata["disposition"] == before.disposition
        assert "retention_rule_id" not in target.metadata
        if before.disposition == "external_review":
            assert target.target_kind == "unknown", dependency.code
            assert target.metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"
        else:
            assert (dependency.code, target.target_kind) == (
                "phase1_jobs", "processing_queue")


# ── with the rules active ───────────────────────────────────────────────


def test_with_its_rule_a_product_record_is_a_delete_naming_the_rule():
    orchestrator, _tables = _orchestrator(rules=ACTIVE)
    for dependency in RULED:
        if dependency.ruled_by != PRODUCT_RECORDS_RULE:
            continue
        target = orchestrator._dependency_target(dependency, GRAPH, RELATIONS)
        assert target.target_kind != "unknown", dependency.code
        assert target.metadata["disposition"] == "delete"
        assert target.metadata["retention_rule_id"] == "rule-p"


def test_with_its_rule_job_evidence_is_kept_under_that_rule():
    rehearsal = {"id": "other", "rule_code": "rehearsal-job_evidence-2",
                 "evidence_category": JOB_EVIDENCE, "active": True}
    orchestrator, _tables = _orchestrator(rules=(rehearsal, *ACTIVE))
    for dependency in RULED:
        if dependency.ruled_by != JOB_EVIDENCE_RULE:
            continue
        target = orchestrator._dependency_target(dependency, GRAPH, RELATIONS)
        assert target.target_kind != "unknown", dependency.code
        assert target.metadata["disposition"] == "retain"
        assert target.metadata["retention_rule_id"] == "rule-j", dependency.code


# ── resolution follows the freeze ───────────────────────────────────────


class _DeleteClient:
    def __init__(self):
        self.deleted: list[tuple[str, str, list]] = []
        self._relation = ""

    def table(self, relation):
        self._relation = relation
        return self

    def delete(self):
        return self

    def eq(self, column, value):
        self.deleted.append((self._relation, column, [value]))
        return self

    def in_(self, column, values):
        self.deleted.append((self._relation, column, list(values)))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def _resolver(rules):
    orchestrator, tables = _orchestrator(rules=rules)
    client = _DeleteClient()
    orchestrator.client = client
    orchestrator._count = lambda *_args: 0
    resolved: list[dict] = []
    orchestrator._resolve = lambda target, **kwargs: resolved.append(kwargs)
    return orchestrator, client, resolved, tables


def _frozen(code, disposition, rule_id=None):
    metadata = {"dependency_code": code, "disposition": disposition}
    if rule_id:
        metadata["retention_rule_id"] = rule_id
    return {"id": "target-1", "initial_match_count": 2, "metadata": metadata}


def test_a_target_frozen_before_the_rule_never_deletes_after_it():
    orchestrator, client, resolved, _ = _resolver(ACTIVE)
    orchestrator._resolve_dependency(
        _frozen("feedback_exposure", "external_review"), GRAPH)
    assert client.deleted == []
    assert resolved[-1]["state"] == "unknown"
    assert resolved[-1]["error_code"] == "EXPLICIT_RESOLVER_REQUIRED"


def test_a_ruled_delete_whose_rule_was_withdrawn_deletes_nothing():
    orchestrator, client, resolved, tables = _resolver(ACTIVE)
    tables["data_retention_rules"][0]["active"] = False
    orchestrator._resolve_dependency(
        _frozen("feedback_exposure", "delete", "rule-p"), GRAPH)
    assert client.deleted == []
    assert (resolved[-1]["state"], resolved[-1]["error_code"]) == (
        "failed", "RETENTION_RULE_INACTIVE")


def test_a_ruled_delete_under_its_active_rule_deletes_and_names_it():
    orchestrator, client, resolved, _ = _resolver(ACTIVE)
    orchestrator._resolve_dependency(
        _frozen("feedback_exposure", "delete", "rule-p"), GRAPH)
    assert client.deleted == [("take_feedback_exposure", "take_session_id",
                               ["take-1"])]
    assert resolved[-1]["state"] == "deleted"
    assert resolved[-1]["retention_rule_id"] == "rule-p"


def test_the_job_row_frozen_as_before_is_deleted_as_before():
    orchestrator, client, resolved, _ = _resolver(())
    orchestrator._resolve_dependency(_frozen("phase1_jobs", "delete"), GRAPH)
    assert client.deleted == [("phase1_processing_jobs",
                               "acquisition_principal_id", ["principal-1"])]
    assert resolved[-1]["state"] == "deleted"
    assert resolved[-1]["retention_rule_id"] is None


def test_the_job_row_frozen_under_the_rule_is_kept():
    orchestrator, client, resolved, _ = _resolver(ACTIVE)
    orchestrator._resolve_dependency(
        _frozen("phase1_jobs", "retain", "rule-j"), GRAPH)
    assert client.deleted == []
    assert (resolved[-1]["state"], resolved[-1]["retention_rule_id"]) == (
        "retained", "rule-j")


# ── the project scope ───────────────────────────────────────────────────


def _project(rules):
    orchestrator, _tables = _orchestrator(scope.ProjectPurgeOrchestrator,
                                          rules=rules)
    orchestrator._project_id, orchestrator._principal_id = "project-1", "principal-1"
    orchestrator._account = lambda: GRAPH
    return orchestrator


PROJECT_GRAPH = SubjectGraph(
    principal_ids=(), project_ids=("project-1",), take_ids=("take-1",),
    job_ids=("job-1",),
)


@pytest.mark.parametrize("code", ["coach_ai_review", "life_consent_review",
                                  "moment_unlocks_review", "few_shot_review"])
def test_an_unready_account_keyed_record_still_stops_a_project_purge(code):
    target = _project(())._dependency_target(
        dependency_by_code(code), PROJECT_GRAPH, RELATIONS)
    assert target.target_kind == "unknown"
    assert target.metadata["reason_code"] == "PROJECT_SCOPE_UNRESOLVED"


@pytest.mark.parametrize("code", ["coach_ai_review", "life_consent_review",
                                  "few_shot_review"])
def test_with_its_rule_an_account_record_is_left_to_the_account(code):
    target = _project(ACTIVE)._dependency_target(
        dependency_by_code(code), PROJECT_GRAPH, RELATIONS)
    assert target.target_kind != "unknown"
    assert target.initial_match_count == 0


def test_with_its_rule_a_project_named_record_goes_with_the_project():
    target = _project(ACTIVE)._dependency_target(
        dependency_by_code("moment_unlocks_review"), PROJECT_GRAPH, RELATIONS)
    assert target.metadata["selector_column"] == "arc_id"
    assert target.metadata["locator_values"] == ["project-1"]
    assert target.metadata["disposition"] == "delete"


@pytest.mark.parametrize("rules,disposition", [((), "delete"),
                                                (ACTIVE, "retain")])
def test_the_project_job_row_is_deleted_before_and_kept_after(rules, disposition):
    target = _project(rules)._dependency_target(
        dependency_by_code("phase1_jobs"), PROJECT_GRAPH, RELATIONS)
    assert target.metadata["selector_column"] == "id"
    assert target.metadata["disposition"] == disposition


# ── migration 0424 and the rehearsal lane ───────────────────────────────


def test_0424_is_in_the_manifest_and_deletes_nothing_itself():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0424\ta_purge_deletes_the_product_records_it_froze.sql" in manifest
    assert destructive_statements(MIGRATION) == []
    assert "CREATE OR REPLACE FUNCTION public.reject_immutable_feedback_mutation()" in MIGRATION
    assert re.search(r"REVOKE ALL ON FUNCTION public\.reject_immutable_feedback_mutation\(\)\s+"
                     r"FROM PUBLIC, anon, authenticated;", MIGRATION)


def test_0424_opens_three_tables_inside_a_frozen_purge_under_the_rule():
    body = MIGRATION.split("AS $$", 1)[1].split("$$;", 1)[0]
    opening = body.split("THEN", 1)[0]
    assert "TG_OP = 'DELETE'" in opening
    assert set(re.findall(r"'([a-z_]+)'", opening)) == {
        "take_feedback_exposure", "take_feedback_self_report",
        "ideal_text_part_revision"}
    for guard in ("purge.state = 'in_progress'",
                  "public.data_purge_inventory_manifests",
                  "target.state = 'pending'",
                  "target.metadata ->> 'relation' = TG_TABLE_NAME",
                  "target.metadata ->> 'disposition' = 'delete'",
                  "rule.active",
                  "rule.evidence_category = 'product_records'",
                  "(target.metadata -> 'locator_values') ?"):
        assert guard in body, guard
    # Every other case still raises, with the message it always had.
    assert body.rstrip().endswith(
        "RAISE EXCEPTION 'immutable feedback evidence cannot be changed';\nEND;")
    assert "TG_OP = 'UPDATE'" not in body


def test_the_released_lane_applies_0424_and_runs_its_proof():
    recipe = (ROOT / "tests" / "integration" /
              "confident_moment_rehearsal.sh").read_text()
    released = recipe[recipe.rindex('if [ "$LANE" = "released" ]; then\n  hard '
                                    'migrations/add_learning_surface'):]
    assert released.count(
        "hard migrations/a_purge_deletes_the_product_records_it_froze.sql") == 2
    tier = (ROOT / "scripts" / "rehearsal_tier.sh").read_text()
    lane = next(line for line in tier.splitlines()
                if line.lstrip().startswith('"confident-moment released|'))
    assert "tests/test_product_records_purge_postgres.py" in lane


# ── the schedule lists all of it ────────────────────────────────────────


def test_the_schedule_names_every_dependency_it_decides_or_leaves_open():
    """v1.4 §2 and §4: every dependency that was external_review before
    v1.4 is named, by code, in the document the founder signs."""
    text = SCHEDULE.read_text(encoding="utf-8")
    missing = sorted(
        d.code for d in DEPENDENCIES
        if (d.ruled_by or d.disposition == "external_review")
        and f"`{d.code}`" not in text
    )
    assert missing == []
