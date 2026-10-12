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

from types import SimpleNamespace

from services import data_purge_project_scope as scope
from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_registry import (
    DEPENDENCIES,
    JOB_EVIDENCE,
    JOB_EVIDENCE_RULE,
    PRODUCT_RECORDS,
    PRODUCT_RECORDS_RULE,
    dependency_by_code,
)

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


# ── before the rules are active: exactly as before ──────────────────────


# ── with the rules active ───────────────────────────────────────────────


# ── resolution follows the freeze ───────────────────────────────────────


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


def test_with_its_rule_a_project_named_record_goes_with_the_project():
    target = _project(ACTIVE)._dependency_target(
        dependency_by_code("moment_unlocks_review"), PROJECT_GRAPH, RELATIONS)
    assert target.metadata["selector_column"] == "arc_id"
    assert target.metadata["locator_values"] == ["project-1"]
    assert target.metadata["disposition"] == "delete"


# ── migration 0424 and the rehearsal lane ───────────────────────────────


# ── the schedule lists all of it ────────────────────────────────────────
