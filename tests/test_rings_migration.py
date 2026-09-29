"""0394 a_feature_reaches_a_person_by_ring.sql, read as text (no database).

The released-lane rehearsal (tests/test_rings_postgres.py) executes it; this
pins the shape the repository's rules require: manifest position, the rule's
clauses in the check function, definer RPCs with their grants revoked, the
R-1 grant shape (SELECT only for the service key), append-only change
tables, the seed at rings nobody holds, and no environment variable.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_feature_reaches_a_person_by_ring.sql"
SQL = MIGRATION.read_text()

WRITE_RPCS = (
    "set_feature_ring_v1", "kill_feature_v1", "set_principal_ring_v1",
    "set_principal_rings_bulk_v1", "set_ring_default_v1",
    "set_ring_announcement_v1", "record_ring_announcement_decision_v1",
)
READ_RPCS = (
    "ring_default_v1", "ring_consent_is_current_v1",
    "ring_consent_policy_exists_v1", "feature_reaches_v1", "feature_is_on_v1",
    "features_on_for_v1", "ring_eligible_principals_v1",
    "feature_ring_counts_v1", "get_ring_confidence_readiness_v1",
)
TABLES = (
    "feature_rings", "principal_rings", "ring_settings", "ring_announcements",
    "ring_announcement_decisions", "feature_ring_changes",
    "principal_ring_changes", "ring_setting_changes",
)


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL, flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_manifest_appends_rings_as_0394_after_0392():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    rings = "0394\ta_feature_reaches_a_person_by_ring.sql"
    previous = "0392\tthe_promotion_freezes_the_consent_snapshot.sql"
    assert rings in manifest
    assert manifest.index(previous) < manifest.index(rings)


def test_every_table_is_created_idempotently_with_rls():
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS public.{table} (" in SQL, table
    # One DO block enables RLS and revokes every role over the same list.
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    for table in TABLES:
        assert f"'{table}'" in SQL


def test_service_role_gets_select_and_only_the_purges_delete():
    assert "GRANT SELECT ON TABLE public.%I TO service_role" in SQL
    assert not re.search(r"GRANT\s+(ALL|INSERT|UPDATE)", SQL, re.I)
    assert "REVOKE ALL ON TABLE public.%I FROM %I" in SQL
    # DELETE only on the three person-keyed tables, for the Phase-1 purge.
    assert SQL.count("GRANT DELETE ON TABLE public.%I TO service_role") == 1
    assert ("IF v_table IN ('principal_rings', 'principal_ring_changes',\n"
            "                           'ring_announcement_decisions')") in SQL


def test_the_purge_registry_classifies_every_ring_table():
    from services import data_purge_registry as registry

    deletes = {d.relation: d for d in registry.DEPENDENCIES if d.disposition == "delete"}
    for table in ("principal_rings", "principal_ring_changes", "ring_announcement_decisions"):
        assert table in deletes, table
        assert deletes[table].selector_column == "principal_id"
    for table in ("feature_rings", "ring_settings", "ring_announcements",
                  "feature_ring_changes", "ring_setting_changes"):
        assert table in registry.NON_SUBJECT_RELATIONS, table


def test_the_check_function_implements_every_clause_of_the_rule():
    reaches = _function("feature_reaches_v1")
    assert "row_feature.killed" in reaches                      # not killed
    assert "my_ring < row_feature.min_ring" in reaches          # ring >= feature's ring
    assert "ring_default_v1()" in reaches                       # missing person = default
    assert "my_attributes := '{}'::jsonb" in reaches            # ... with no attributes
    assert "jsonb_each(row_feature.attribute_rule)" in reaches  # AND over every key
    assert "jsonb_array_elements_text" in reaches               # "key is in list"
    on = _function("feature_is_on_v1")
    assert "feature_reaches_v1(p_feature, p_principal)" in on
    assert "ring_consent_is_current_v1(p_principal, purpose)" in on
    assert "IF purpose IS NULL THEN\n        RETURN true;" in on


def test_consent_is_read_through_the_existing_doors_and_never_written():
    consent = _function("ring_consent_is_current_v1")
    assert "get_phase1_consent_choices_v1" in consent
    assert "get_mlc2_principal_consent_status_v1" in consent
    assert "to_regproc(" in consent  # a database without the door answers false
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b", consent, re.I)
    for name in ("feature_reaches_v1", "feature_is_on_v1", "features_on_for_v1",
                 "ring_consent_policy_exists_v1", "get_ring_confidence_readiness_v1"):
        assert "STABLE" in _function(name), name
        assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b", _function(name), re.I), name


def test_every_function_is_a_definer_with_search_path_and_revoked_execute():
    for name in WRITE_RPCS + READ_RPCS:
        body = _function(name)
        assert "SECURITY DEFINER" in body, name
        assert "SET search_path = public" in body, name
        assert re.search(
            rf"REVOKE ALL ON FUNCTION public\.{name}\([^)]*\)\s+FROM PUBLIC, anon, authenticated",
            SQL,
        ), name
        assert re.search(
            rf"GRANT EXECUTE ON FUNCTION public\.{name}\([^)]*\)\s+TO service_role",
            SQL,
        ), name
    trigger = _function("reject_ring_change_mutation")
    assert "append-only" in trigger
    assert "REVOKE ALL ON FUNCTION public.reject_ring_change_mutation()" in SQL


def test_every_write_rpc_records_a_change_row():
    for name in ("set_feature_ring_v1", "kill_feature_v1"):
        assert "INSERT INTO feature_ring_changes" in _function(name), name
    assert "INSERT INTO principal_ring_changes" in _function("set_principal_ring_v1")
    assert "set_principal_ring_v1(one, p_ring, NULL, p_changed_by)" in _function("set_principal_rings_bulk_v1")
    assert "INSERT INTO ring_setting_changes" in _function("set_ring_default_v1")
    assert "THEN 'UPDATE' ELSE 'UPDATE OR DELETE' END" in SQL


def test_a_one_way_row_kills_once_and_refuses_the_unkill():
    kill = _function("kill_feature_v1")
    assert "existing.one_way AND existing.killed AND NOT p_killed" in kill
    assert "RING_ONE_WAY_KILLED" in kill
    edit = _function("set_feature_ring_v1")
    assert "existing.one_way AND existing.killed" in edit
    assert "one_way = feature_rings.one_way OR EXCLUDED.one_way" in edit


def test_seed_puts_the_canaries_where_nobody_is_and_keeps_the_writer_state():
    assert "('default_ring', '2'::jsonb" in SQL
    assert "('canonical_take_rows', 5," in SQL
    assert "('confidence_learning_writes', 5, NULL, 'pooled_model_improvement', false,\n     true," in SQL
    assert "('exercise_service', 3, NULL, 'personalised_practice'" in SQL
    # No person row is created at the canary rings.
    assert "SELECT DISTINCT m.acquisition_principal_id, 3," in SQL
    assert "SELECT DISTINCT a.acquisition_principal_id, 3," in SQL
    assert "WHERE a.state = 'active'" in SQL
    # The writer state is not in the database at all: the constant is named
    # in prose only, never as a value a row could carry.
    body = re.sub(r"--[^\n]*", "", SQL)
    assert "founder_canary" not in body
    assert "CUTOVER_MODE" not in body.replace(
        "(MLC2_CONFIDENCE_CUTOVER_MODE) stays a code constant", "")


def test_announcement_copy_is_placeholder_only():
    for line in SQL.splitlines():
        stripped = line.strip()
        if stripped.startswith("'[") or "founder copy" in stripped:
            assert "[founder copy]" in stripped, line


def test_additive_idempotent_and_reads_no_environment():
    body = re.sub(r"--[^\n]*", "", SQL)
    assert not re.search(r"\bDROP\s+(TABLE|COLUMN|SCHEMA)\b", body, re.I)
    assert not re.search(r"\bTRUNCATE\b", body, re.I)
    assert not re.search(r"\bDELETE\s+FROM\b", body, re.I)
    assert "current_setting(" not in body
    assert "ON CONFLICT (feature) DO NOTHING" in SQL
    assert "ON CONFLICT (principal_id) DO NOTHING" in SQL
    assert "to_regclass('public.mlc3_service_cohort_members')" in SQL
    assert "to_regclass('public.mlc3_service_principal_allowlist')" in SQL


def test_the_lane_recipe_applies_it_twice():
    recipe = (ROOT / "tests" / "integration" / "confident_moment_rehearsal.sh").read_text()
    assert recipe.count("hard migrations/a_feature_reaches_a_person_by_ring.sql") == 2
    tier = (ROOT / "scripts" / "rehearsal_tier.sh").read_text()
    assert "tests/test_rings_postgres.py" in tier
