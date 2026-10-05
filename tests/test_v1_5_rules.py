"""Retention schedule v1.5 in the purge, without a database (founder
2026-10-05, decisions log N50 item 5: P1-P6 A, and P7, the clean-up's).

The purge change is HELD for the founder's signature: it merges inert and
switches itself on when scripts/phase1_retention_schedule_v1_5.sql registers
the signed document. These pin that:

  * the decided set: every v1.4 §5.1 and §5.6 entry is deleted with the
    account or the project (P1, P6); an arc purchase splits by its own
    columns into a free founding pass (deleted) and a paid arc (kept five
    years) (P2); the consent snapshot is consent evidence (P3); a reference
    video is deleted unless it is library content, which loses only the
    speaker's link (P4); four retired corpora get a resolver, the other six
    keep stopping the erasure (P5); every v1.5 entry names a rule an earlier
    signed version seeded, in that rule's category;
  * until v1.5 is registered every such entry builds exactly the target it
    built before, and a split table is one entry counting every row;
  * with it, the entries act, and the delete check turns what a delete
    could not finish into a stop for review before anything is frozen;
  * resolution deletes asking nothing back, by the row filter, and a
    library video is detached, not deleted;
  * migration 0429, the two scripts and the document say what the code
    does.

The same behaviour against the real schema: tests/test_v1_5_purge_postgres.py.
"""
from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

import pytest

from scripts.migrate import destructive_statements
from services import data_purge_project_scope as scope
from services.data_purge import DataPurgeOrchestrator, PurgeTarget, SubjectGraph
from services.data_purge_registry import (
    CONSENT_EVIDENCE_RULE,
    DEPENDENCIES,
    DETACH_LINKS,
    FINANCIAL_EVIDENCE_RULE,
    PRODUCT_RECORDS,
    PRODUCT_RECORDS_RULE,
    RULE_CATEGORY,
    SCHEDULE_V1_5,
    before_its_rule,
    carve_outs,
    dependency_by_code,
    row_matches,
)
from services.retention_cleaner import FINANCIAL_TABLES

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEGAL = ROOT / "legal" / "phase1-2026.1"
V1_4 = (LEGAL / "20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md"
        ).read_text(encoding="utf-8")
V1_5_DOC = LEGAL / "22-retention-schedule-v1.5-what-v1.4-left-open-DRAFT.md"
MIGRATION = (ROOT / "migrations"
             / "the_purge_reaches_what_v1_5_decided.sql").read_text()
SCRIPT = (ROOT / "scripts" / "phase1_retention_schedule_v1_5.sql").read_text()
COUNTS = (ROOT / "scripts" / "phase1_retention_v1_5_counts.sql").read_text()

V1_5 = [d for d in DEPENDENCIES if d.schedule]
RELATIONS = frozenset(d.relation for d in DEPENDENCIES) | {
    "data_retention_rules", "processing_legal_artifacts"}
RULES = (
    {"id": "rule-p", "rule_code": PRODUCT_RECORDS_RULE,
     "evidence_category": PRODUCT_RECORDS, "active": True},
    {"id": "rule-c", "rule_code": CONSENT_EVIDENCE_RULE,
     "evidence_category": "consent_evidence", "active": True},
    {"id": "rule-f", "rule_code": FINANCIAL_EVIDENCE_RULE,
     "evidence_category": "financial_evidence", "active": True},
)
REGISTERED = ({"id": "artifact-15", "artifact_kind": "retention_schedule",
               "version": "1.5"},)
GRAPH = SubjectGraph(principal_ids=("principal-1",), user_ids=("user-1",),
                     take_ids=("take-1",), project_ids=("project-1",))


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def _named(text: str) -> set[str]:
    return set(re.findall(r"`([a-z0-9_]+)`", text))


# ── the decided set ─────────────────────────────────────────────────────


def test_every_v1_5_entry_names_an_earlier_rule_in_its_category():
    assert len(V1_5) == 138
    for dependency in V1_5:
        assert dependency.schedule == SCHEDULE_V1_5, dependency.code
        assert dependency.ruled_by in RULE_CATEGORY, dependency.code
        assert dependency.retention_category == RULE_CATEGORY[dependency.ruled_by]
        assert dependency.before_rule == "external_review", dependency.code
        assert before_its_rule(dependency).disposition == "external_review"
    # v1.5 seeds no rule: it points only at the three earlier ones.
    assert {d.ruled_by for d in V1_5} == {
        PRODUCT_RECORDS_RULE, CONSENT_EVIDENCE_RULE, FINANCIAL_EVIDENCE_RULE}


def test_p1_and_p6_delete_every_entry_v1_4_proposed():
    p1 = _named(_section(V1_4, "**5.1", "**5.2"))
    p6 = _named(_section(V1_4, "**5.6", "**5.7")) & {
        d.code for d in DEPENDENCIES}
    assert len(p1) == 9 and len(p6) == 120
    decided = {d.code: d for d in V1_5}
    for code in p1 | p6:
        dependency = decided[code]
        assert dependency.disposition == "delete", code
        assert dependency.ruled_by == PRODUCT_RECORDS_RULE, code


def test_p2_tells_an_arc_purchase_apart_by_its_own_columns():
    founding, paid = (dependency_by_code("arc_purchases_founding_pass"),
                      dependency_by_code("arc_purchases_paid"))
    assert (founding.disposition, founding.ruled_by) == (
        "delete", PRODUCT_RECORDS_RULE)
    assert (paid.disposition, paid.ruled_by, paid.retention_category) == (
        "retain", FINANCIAL_EVIDENCE_RULE, "financial_evidence")
    rows = {
        "pass": {"kind": "founding_pass", "source": "invite_code"},
        "credits": {"kind": "paid", "source": "credits", "credits_charged": 25},
        "stripe": {"kind": "paid", "source": "stripe", "amount_minor": 15000,
                   "stripe_session_id": "cs_1"},
        "manual": {"kind": "paid", "source": "manual"},
        "pass_that_paid": {"kind": "founding_pass", "source": "invite_code",
                           "credits_charged": 25},
    }
    claimed = {name: [d.code for d in carve_outs("arc_purchases_review")
                      if row_matches(d, row)] for name, row in rows.items()}
    assert claimed == {
        "pass": ["arc_purchases_founding_pass"],
        "credits": ["arc_purchases_paid"], "stripe": ["arc_purchases_paid"],
        "manual": [], "pass_that_paid": [],
    }


def test_p3_the_consent_snapshot_is_kept_six_years():
    snapshot = dependency_by_code("ml_consent_snapshots")
    assert (snapshot.disposition, snapshot.ruled_by,
            snapshot.retention_category) == (
        "retain", CONSENT_EVIDENCE_RULE, "consent_evidence")


def test_p4_a_library_video_loses_only_the_speakers_link():
    library = dependency_by_code("reference_videos_library")
    own = dependency_by_code("reference_videos_own")
    assert (library.disposition, own.disposition) == ("tombstone", "delete")
    assert DETACH_LINKS["admin_uploaded_reference_videos"] == (
        "user_id", "session_id", "draft_id")
    assert [d.code for d in carve_outs("admin_uploaded_reference_review")] == [
        "reference_videos_library", "reference_videos_own"]
    assert row_matches(library, {"is_universal": True})
    assert not row_matches(own, {"is_universal": True})
    assert row_matches(own, {"is_universal": False})


def test_p5_four_retired_corpora_get_a_resolver_and_six_wait():
    resolved = {d.code: (d.relation, d.selector_column)
                for d in V1_5 if d.code.startswith("legacy_")}
    assert resolved == {
        "legacy_reflection_clips": ("reflection_clips", "user_id"),
        "legacy_strong_sides": ("strong_sides_library", "user_id"),
        "legacy_recording_reviews": ("recording_reviews", "session_id"),
        "legacy_recording_review_annotations": (
            "recording_review_annotations", "session_id"),
    }
    for code in ("legacy_snippets_table_review", "retired_stress_corpus",
                 "legacy_acoustic_labels", "legacy_shadow_predictions",
                 "legacy_snippet_labels", "legacy_training_labels"):
        dependency = dependency_by_code(code)
        assert (dependency.disposition, dependency.ruled_by) == (
            "external_review", None), code


def test_p7_is_the_clean_ups_and_the_purge_keeps_the_ledgers():
    for code in ("token_ledger_review", "llm_usage_review"):
        dependency = dependency_by_code(code)
        assert (dependency.disposition, dependency.schedule) == ("retain", None)
    # P7 named the ledger and the LLM usage only, so the clean-up's Rule 4
    # does not reach a paid arc (P2); the document puts that to the founder.
    assert "arc_purchases" not in FINANCIAL_TABLES
    assert "nothing yet deletes a paid arc" in V1_5_DOC.read_text(
        encoding="utf-8")


def test_a_carve_out_is_only_ever_a_part_of_its_original_entry():
    for dependency in DEPENDENCIES:
        if dependency.carved_from:
            original = dependency_by_code(dependency.carved_from)
            assert original is not None and original.relation == dependency.relation
            assert original.disposition == "external_review"
            assert dependency.row_filter, dependency.code
            assert dependency.schedule == SCHEDULE_V1_5


# ── before v1.5 is registered: exactly as before ────────────────────────


def _orchestrator(cls=DataPurgeOrchestrator, *, rules=RULES, artifacts=(),
                  arcs=(), rows=3):
    orchestrator = cls(SimpleNamespace(client=object()))
    tables = {"data_retention_rules": [dict(rule) for rule in rules],
              "processing_legal_artifacts": [dict(a) for a in artifacts],
              "arc_purchases": [dict(arc) for arc in arcs]}

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
    count = orchestrator._count

    def counted(dependency, values, existing=None):
        if dependency.relation == "arc_purchases":
            return count(dependency, values, existing)
        return rows if values else 0

    orchestrator._count = counted
    return orchestrator, tables


ARCS = (
    {"user_id": "user-1", "kind": "founding_pass", "source": "invite_code"},
    {"user_id": "user-1", "kind": "paid", "source": "credits",
     "credits_charged": 25},
    {"user_id": "user-1", "kind": "paid", "source": "manual"},
)


@pytest.mark.parametrize("rules,artifacts", [
    (RULES, ()),                     # the rules, not the schedule
    ((), REGISTERED),                # the schedule, not the rules
    ((), ()),
])
def test_until_both_hold_a_v1_5_entry_acts_as_before(rules, artifacts):
    orchestrator, _ = _orchestrator(rules=rules, artifacts=artifacts, arcs=ARCS)
    for dependency in V1_5:
        target = orchestrator._dependency_target(dependency, GRAPH, RELATIONS)
        if dependency.carved_from:
            assert target is None, dependency.code
            continue
        if not GRAPH.values(dependency.locator_kind):
            continue
        assert target.target_kind == "unknown", dependency.code
        assert target.metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"
        assert "retention_schedule" not in target.metadata
    remainder = orchestrator._dependency_target(
        dependency_by_code("arc_purchases_review"), GRAPH, RELATIONS)
    assert remainder.initial_match_count == 3


def test_with_v1_5_and_its_rules_the_entries_act():
    orchestrator, _ = _orchestrator(artifacts=REGISTERED, arcs=ARCS)
    for dependency in V1_5:
        if not GRAPH.values(dependency.locator_kind):
            continue
        target = orchestrator._dependency_target(dependency, GRAPH, RELATIONS)
        assert target.target_kind != "unknown", dependency.code
        assert target.metadata["disposition"] == dependency.disposition
        assert target.metadata["retention_schedule"] == "1.5"
        assert target.metadata["retention_rule_id"] == {
            PRODUCT_RECORDS_RULE: "rule-p", CONSENT_EVIDENCE_RULE: "rule-c",
            FINANCIAL_EVIDENCE_RULE: "rule-f"}[dependency.ruled_by]
    counts = {code: orchestrator._dependency_target(
                  dependency_by_code(code), GRAPH, RELATIONS).initial_match_count
              for code in ("arc_purchases_founding_pass", "arc_purchases_paid",
                           "arc_purchases_review")}
    assert counts == {"arc_purchases_founding_pass": 1, "arc_purchases_paid": 1,
                      "arc_purchases_review": 1}


def test_a_registration_read_that_fails_answers_no():
    orchestrator, _ = _orchestrator()

    def broken(*_args, **_kwargs):
        raise RuntimeError("UNRESOLVED_DEPENDENCY:processing_legal_artifacts:500")

    reads = orchestrator._rows

    def read(relation, *args, **kwargs):
        if relation == "processing_legal_artifacts":
            broken()
        return reads(relation, *args, **kwargs)

    orchestrator._rows = read
    target = orchestrator._dependency_target(
        dependency_by_code("feedback_v3_owner_responses"), GRAPH, RELATIONS)
    assert target.metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"


# ── the delete check ────────────────────────────────────────────────────


class _Rpc:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(data=self.answer)


def _delete(code, order, *, schedule=True, row_filter=False, count=2):
    metadata = {"dependency_code": code, "relation": code,
                "selector_column": "acquisition_principal_id",
                "locator_values": ["principal-1"], "disposition": "delete",
                "delete_order": order}
    if schedule:
        metadata["retention_schedule"] = "1.5"
    if row_filter:
        metadata["row_filter"] = [["kind", "eq", "x"]]
    return PurgeTarget("database_row", f"dependency:{code}", count, metadata)


@pytest.mark.parametrize("answer,reason", [
    ({"can_delete": True, "blocked_by": {}}, None),
    ({"can_delete": False, "blocked_by": {}}, "PURGE_CANNOT_DELETE_HERE"),
    ({"can_delete": True, "blocked_by": {"public.correction_decisions": 1}},
     "KEPT_ROWS_STILL_POINT_HERE"),
    (RuntimeError("PGRST202"), "DELETE_CHECK_UNAVAILABLE"),
])
def test_a_v1_5_delete_that_could_not_finish_stops_the_erasure(answer, reason):
    orchestrator = DataPurgeOrchestrator(SimpleNamespace(client=_Rpc(answer)))
    checked = orchestrator._checked_v1_5_deletes([_delete("items", 44)])
    if reason is None:
        assert checked[0].target_kind == "database_row"
    else:
        assert (checked[0].target_kind, checked[0].metadata["reason_code"]) == (
            "unknown", reason)
        assert checked[0].target_ref == "dependency:items"


def test_the_check_gets_every_delete_ranked_as_the_purge_runs_them():
    client = _Rpc({"can_delete": True, "blocked_by": {}})
    orchestrator = DataPurgeOrchestrator(SimpleNamespace(client=client))
    targets = [_delete("memberships", 52), _delete("items", 44),
               _delete("snippets", 45, schedule=False),
               _delete("passes", 300, row_filter=True),
               _delete("empty", 10, count=0)]
    orchestrator._checked_v1_5_deletes(targets)
    plans = {params["p_relation"]: (params["p_rank"], params["p_plan"])
             for _name, params in client.calls}
    # Checked: v1.5's deletes with rows; the ranks are the run order.
    assert set(plans) == {"memberships", "items", "passes"}
    assert plans["items"][0] == 0 and plans["memberships"][0] == 2
    # A filtered delete covers nothing; an empty one is not run at all.
    assert [entry["relation"] for entry in plans["items"][1]] == [
        "items", "snippets", "memberships"]


def test_no_v1_5_delete_no_check():
    client = _Rpc(RuntimeError("never asked"))
    orchestrator = DataPurgeOrchestrator(SimpleNamespace(client=client))
    targets = [_delete("snippets", 45, schedule=False)]
    assert orchestrator._checked_v1_5_deletes(targets) == targets
    assert client.calls == []


# ── resolution ──────────────────────────────────────────────────────────


class _Writes:
    def __init__(self):
        self.calls: list[tuple] = []

    def table(self, relation):
        self.calls.append(("table", relation))
        return self

    def delete(self, **kwargs):
        self.calls.append(("delete", getattr(kwargs.get("returning"), "value", None)))
        return self

    def update(self, values, **kwargs):
        self.calls.append(("update", values,
                           getattr(kwargs.get("returning"), "value", None)))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.calls.append(("in", column, list(values)))
        return self

    def is_(self, column, value):
        self.calls.append(("is", column, value))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def _resolving(rules=RULES):
    orchestrator, _ = _orchestrator(rules=rules, artifacts=REGISTERED)
    client = _Writes()
    orchestrator.client = client
    orchestrator._count = lambda *_args: 0
    resolved: list[dict] = []
    orchestrator._resolve = lambda target, **kwargs: resolved.append(kwargs)
    return orchestrator, client, resolved


def test_a_v1_5_delete_asks_nothing_back_and_keeps_to_its_filter():
    orchestrator, client, resolved = _resolving()
    target = {"id": "t", "initial_match_count": 1, "metadata": {
        "dependency_code": "arc_purchases_founding_pass",
        "disposition": "delete", "retention_rule_id": "rule-p"}}
    orchestrator._resolve_dependency(target, GRAPH)
    assert client.calls == [
        ("table", "arc_purchases"), ("delete", "minimal"),
        ("eq", "user_id", "user-1"), ("eq", "kind", "founding_pass"),
        ("eq", "source", "invite_code"), ("is", "amount_minor", "null"),
        ("is", "credits_charged", "null"), ("is", "stripe_session_id", "null"),
    ]
    assert resolved[-1]["state"] == "deleted"


def test_a_library_video_is_detached_not_deleted():
    orchestrator, client, resolved = _resolving()
    target = {"id": "t", "initial_match_count": 1, "metadata": {
        "dependency_code": "reference_videos_library",
        "disposition": "tombstone", "retention_rule_id": "rule-p",
        "locator_values": ["user-1"]}}
    orchestrator._resolve_dependency(target, GRAPH)
    assert client.calls == [
        ("table", "admin_uploaded_reference_videos"),
        ("update", {"user_id": None, "session_id": None, "draft_id": None},
         "minimal"),
        ("eq", "user_id", "user-1"), ("eq", "is_universal", "true"),
    ]
    assert (resolved[-1]["state"], resolved[-1]["retention_rule_id"]) == (
        "retained", "rule-p")


# ── the project scope ───────────────────────────────────────────────────


def test_the_project_graph_lists_the_projects_memberships():
    graph = scope.ProjectSubjectGraph(
        principal_ids=(), project_ids=("project-1",),
        feedback_v3_membership_ids=("membership-1",))
    assert graph.values("feedback_v3_membership") == ("membership-1",)
    assert graph.payload()["feedback_v3_membership_ids"] == ["membership-1"]
    assert SubjectGraph(principal_ids=()).values("feedback_v3_membership") == ()
    assert "feedback_v3_membership_ids" not in SubjectGraph(
        principal_ids=()).payload()


def test_every_account_keyed_v1_5_entry_is_placed_once():
    account_keyed = {d.code for d in V1_5
                     if d.locator_kind in {"principal", "user", "speaker"}}
    placements = (set(scope.PROJECT_SELECTORS), set(scope.ACCOUNT_LEVEL),
                  set(scope.PROJECT_REVIEW))
    for code in account_keyed:
        assert sum(code in placed for placed in placements) == 1, code


@pytest.mark.parametrize("code", [
    "feedback_v3_membership_items", "feedback_v3_owner_responses",
    "feedback_v3_service_render_receipts",
    "feedback_v3_service_response_bindings",
])
def test_the_rows_of_a_membership_go_with_its_project(code):
    assert scope.PROJECT_SELECTORS[code] == (
        "membership_id", "feedback_v3_membership")


# ── migration 0429 ──────────────────────────────────────────────────────


def test_0429_is_in_the_manifest_and_deletes_nothing_itself():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0429\tthe_purge_reaches_what_v1_5_decided.sql" in manifest
    assert destructive_statements(MIGRATION) == []
    assert MIGRATION.count("BEGIN;") == 1 and MIGRATION.rstrip().endswith("COMMIT;")


def test_0429s_helper_names_exactly_a_running_purges_frozen_row():
    body = MIGRATION.split(
        "CREATE OR REPLACE FUNCTION public.phase1_purge_names_row_v1(", 1)[1]
    body = body.split("$$;", 1)[0]
    for clause in ("artifact.artifact_kind = 'retention_schedule'",
                   "artifact.version = '1.5'",
                   "purge.state = 'in_progress'",
                   "public.data_purge_inventory_manifests",
                   "target.state = 'pending'",
                   "target.metadata ->> 'relation' = p_relation",
                   "target.metadata ->> 'disposition' = 'delete'",
                   "target.metadata ->> 'retention_schedule' = '1.5'",
                   "rule.active",
                   "rule.evidence_category = 'product_records'",
                   "(target.metadata -> 'locator_values') ?"):
        assert clause in body, clause
    head = MIGRATION.split(
        "CREATE OR REPLACE FUNCTION public.phase1_purge_names_row_v1(", 1)[1]
    assert "LANGUAGE sql STABLE SECURITY DEFINER" in head.split("AS $$", 1)[0]


def test_0429_patches_the_nine_guards_and_guards_three_tables():
    patched = re.findall(r"\('([a-z0-9_]+)',\s*\$a\$", MIGRATION)
    assert patched == [
        "reject_mlc2_immutable_mutation", "reject_coach_guidance_d3_mutation_v1",
        "reject_confident_moment_mutation_v1",
        "reject_mlc3_general_service_mutation_v1",
        "reject_canonical_feedback_mutation", "reject_coach_inline_mutation_v1",
        "reject_immutable_feedback_mutation",
        "guard_exercise_practice_transcription_run_v1",
        "reject_retired_direction_write_v1"]
    guarded = MIGRATION.split("FOREACH relation_name IN ARRAY ARRAY[", 1)[1]
    assert set(re.findall(r"'([a-z0-9_]+)'", guarded.split("]", 1)[0])) == {
        "exercise_practice_upload_recoveries",
        "mlc3_service_principal_allowlist", "root_phrase_block_heads"}


def test_0429_grants_delete_on_exactly_the_tables_v1_5_deletes():
    granted = MIGRATION.split("FOR item IN SELECT * FROM (VALUES", 1)[1]
    granted = granted.split(") AS v(relation_name, selectors)", 1)[0]
    rows = re.findall(r"\('([a-z0-9_]+)', ARRAY\[([^\]]*)\]\)", granted)
    expected: dict[str, set[str]] = {}
    for dependency in V1_5:
        if dependency.disposition != "delete":
            continue
        expected.setdefault(dependency.relation, set()).add(
            dependency.selector_column)
        if dependency.code in scope.PROJECT_SELECTORS:
            expected[dependency.relation].add(
                scope.PROJECT_SELECTORS[dependency.code][0])
    legacy = {"arc_purchases", "admin_uploaded_reference_videos",
              "reflection_clips", "strong_sides_library", "recording_reviews",
              "recording_review_annotations"}
    # The capabilities table never holds a row at rest; the legacy tables
    # already carry Supabase's grants.
    for relation in legacy | {"confident_moment_text_update_capabilities"}:
        expected.pop(relation)
    assert {relation: set(re.findall(r"'([a-z0-9_]+)'", columns))
            for relation, columns in rows} == expected
    assert "confident_moment_text_update_capabilities" not in MIGRATION.split(
        "-- 4. DELETE", 1)[1]


def test_0429_reaches_the_project_memberships_and_frees_the_video_owner():
    assert "'feedback_v3_membership_ids'" in MIGRATION
    assert "WHEN 'feedback_v3_membership'" in MIGRATION
    assert re.search(r"ALTER TABLE public\.admin_uploaded_reference_videos\s+"
                     r"ALTER COLUMN user_id DROP NOT NULL;", MIGRATION)
    for function in ("phase1_purge_names_row_v1(TEXT, JSONB)",
                     "check_phase1_purge_delete_v1(\n    TEXT, TEXT, TEXT[], INTEGER, JSONB)"):
        assert f"GRANT EXECUTE ON FUNCTION public.{function}" in MIGRATION
        assert f"REVOKE ALL ON FUNCTION public.{function}" in MIGRATION


def test_the_released_lane_applies_0429_and_runs_its_proof():
    recipe = (ROOT / "tests" / "integration" /
              "confident_moment_rehearsal.sh").read_text()
    mine = "hard migrations/the_purge_reaches_what_v1_5_decided.sql"
    assert recipe.count(mine) == 2
    # After every earlier migration the recipe applies, as in the manifest.
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    for line in manifest:
        version, _, filename = line.partition("\t")
        step = f"hard migrations/{filename}"
        if version.isdigit() and int(version) < 429 and step in recipe:
            assert recipe.rindex(step) < recipe.index(mine), filename
    tier = (ROOT / "scripts" / "rehearsal_tier.sh").read_text()
    lane = next(line for line in tier.splitlines()
                if line.lstrip().startswith('"confident-moment released|'))
    assert "tests/test_v1_5_purge_postgres.py" in lane.rstrip('"').split()


# ── the two scripts and the document ────────────────────────────────────


def test_the_registration_is_run_by_hand_seeds_no_rule_and_waits_for_its_hash():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "phase1_retention_schedule_v1_5.sql" not in manifest
    assert not (ROOT / "migrations" / "phase1_retention_schedule_v1_5.sql").exists()
    assert "v_sha256 TEXT := '[[sha256 of the signed PDF" in SCRIPT
    assert "INSERT INTO public.data_retention_rules" not in SCRIPT
    for refusal in ("RETENTION_SCHEDULE_V1_5_UNSIGNED",
                    "RETENTION_SCHEDULE_V1_5_RULES_MISSING",
                    "RETENTION_SCHEDULE_V1_5_PURGE_NOT_DEPLOYED",
                    "RETENTION_SCHEDULE_VERSION_CONFLICT"):
        assert refusal in SCRIPT
    for rule in (PRODUCT_RECORDS_RULE, CONSENT_EVIDENCE_RULE,
                 FINANCIAL_EVIDENCE_RULE):
        assert f"'{rule}'" in SCRIPT


def test_the_count_only_reads_and_names_every_table_v1_4_left_waiting():
    statements = [s for s in re.sub(r"--[^\n]*", "", COUNTS).split(";") if s.strip()]
    assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|GRANT|"
                         r"TRUNCATE)\b", statements[0])
    assert "to_regclass('public.' || t.table_name) IS NULL" in COUNTS
    named = set(re.findall(r"\(\d+, '[^']*', '([a-z0-9_]+)'", COUNTS))
    section3 = {"recording_sessions", "pre_recording_answers",
                "post_recording_answers", "tasks", "performance_scores"}
    section56 = {d.relation for d in DEPENDENCIES
                 if d.code in _named(_section(V1_4, "**5.6", "**5.7"))}
    assert len(section56) == 101
    assert section3 | section56 <= named


def test_the_document_names_everything_v1_5_decides_or_leaves_open():
    text = V1_5_DOC.read_text(encoding="utf-8")
    missing = sorted(
        d.code for d in DEPENDENCIES
        if (d.schedule or d.disposition == "external_review"
            or d.code in {"token_ledger_review", "llm_usage_review"})
        and f"`{d.code}`" not in text)
    assert missing == []
    for phrase in ("supersedes 1.4", "scripts/phase1_retention_schedule_v1_5.sql",
                   "scripts/phase1_retention_v1_5_counts.sql",
                   "migrations/the_purge_reaches_what_v1_5_decided.sql"):
        assert phrase in text, phrase


def test_the_signing_record_awaits_v1_5():
    record = (LEGAL / "SIGNED-ARTIFACTS.md").read_text(encoding="utf-8")
    awaiting = record[record.index("## Awaiting signature"):]
    assert re.search(r"06 v1\.5 .*`[0-9a-f]{64}`", awaiting)
    readme = (LEGAL / "README.md").read_text(encoding="utf-8")
    assert "22-retention-schedule-v1.5-what-v1.4-left-open-DRAFT.md" in readme
