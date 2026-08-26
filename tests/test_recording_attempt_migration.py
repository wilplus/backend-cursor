import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "add_recording_attempt_take_boundary.sql"
SQL = MIGRATION.read_text()


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_migration_is_additive_and_manifested_as_0297():
    destructive = re.sub(
        r"DROP TRIGGER IF EXISTS.*?;", "", SQL, flags=re.I | re.S,
    )
    assert not re.search(r"\bDROP\s+(TABLE|COLUMN)\b", destructive, re.I)
    assert not re.search(r"\bTRUNCATE\b", SQL, re.I)
    assert not re.search(r"\bDELETE\s+FROM\b", SQL, re.I)
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-1] == "0297\tadd_recording_attempt_take_boundary.sql"


def test_attempt_take_and_transition_tables_are_service_role_only():
    for table in ("recording_attempts", "takes", "processing_transition_events"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in SQL
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;" in SQL
        assert f"GRANT ALL ON TABLE public.{table} TO service_role;" in SQL
    assert "CREATE POLICY" not in SQL


def test_failed_attempts_cannot_consume_a_take_ordinal():
    promotion = _function("promote_recording_attempt_to_take_v1")
    assert "recording_kind <> 'spoken'" in promotion
    assert "FOR UPDATE" in promotion
    assert "max(row.take_index)" in promotion
    assert "INSERT INTO public.takes" in promotion
    assert "canonical_take_index = next_index" in promotion
    assert "PERFORM public.record_processing_transition_v1" in promotion
    assert "id = recording_attempt_id" in SQL


def test_retry_exceptions_are_narrow_and_terminal_history_stays_append_only():
    transition = _function("record_processing_transition_v1")
    assert "terminal recording attempt is immutable" in transition
    assert "p_stage = 'manual_retry'" in transition
    assert "p_stage = 'ideal_text_retry'" in transition
    assert "processing_transition_events_append_only" in SQL
    assert "BEFORE UPDATE OR DELETE ON public.processing_transition_events" in SQL


def test_attempt_coordinates_are_immutable_and_deletes_are_explicitly_rejected():
    guard = _function("protect_recording_attempt_coordinates")
    assert "IF TG_OP = 'DELETE'" in guard
    for coordinate in (
        "owner_principal_id", "project_id", "upload_idempotency_key",
        "recording_id", "storage_bucket", "storage_key", "recording_kind",
    ):
        assert re.search(
            rf"NEW\.{coordinate}\s+IS DISTINCT FROM\s+OLD\.{coordinate}",
            guard,
        )


def test_security_definer_rpc_execute_is_revoked_from_browser_roles():
    for signature in (
        "public.register_recording_attempt_v1(",
        "public.record_processing_transition_v1(",
        "public.promote_recording_attempt_to_take_v1(",
    ):
        assert f"REVOKE ALL ON FUNCTION {signature}" in SQL
    assert SQL.count("TO service_role;") >= 6
