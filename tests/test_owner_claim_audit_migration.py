import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "add_owner_claim_audit.sql"
SQL = MIGRATION.read_text()


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_claim_audit_is_manifested_and_never_deletes_the_guest_origin():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    entries = dict(line.split("\t", 1) for line in manifest if "\t" in line)
    assert entries["0298"] == "add_owner_claim_audit.sql"
    claim = _function("claim_guest_owner")
    assert "INSERT INTO public.owner_claim_events" in claim
    assert "DELETE FROM public.owner_principals" not in claim
    assert "claimed_by_owner_principal_id = target.id" in claim


def test_claim_event_is_append_only_and_service_role_only():
    assert "CREATE TABLE IF NOT EXISTS public.owner_claim_events" in SQL
    assert "ALTER TABLE public.owner_claim_events ENABLE ROW LEVEL SECURITY;" in SQL
    assert "REVOKE ALL ON TABLE public.owner_claim_events FROM anon, authenticated;" in SQL
    assert "GRANT ALL ON TABLE public.owner_claim_events TO service_role;" in SQL
    assert "owner_claim_events_append_only" in SQL
    assert "BEFORE UPDATE OR DELETE ON public.owner_claim_events" in SQL


def test_claim_retry_uses_double_hashed_proof_and_exact_user_binding():
    claim = _function("claim_guest_owner")
    assert "digest(p_guest_secret_hash, 'sha256')" in claim
    assert "event.claimed_user_id = p_user_id" in claim
    assert "event.claim_proof_hash = proof_hash" in claim
    assert "event.idempotency_key = claim_key" in claim
    assert "RETURN target" in claim


def test_audited_transfer_moves_current_graph_but_not_frozen_releases():
    claim = _function("claim_guest_owner")
    transferred = {
        "projects", "v2_sessions", "recording_attempts", "takes",
        "processing_transition_events", "transcript_versions", "slides",
        "paragraphs", "evidence_spans", "acoustic_feature_snapshots",
        "candidate_sets", "machine_predictions", "generation_runs",
        "processing_stage_runs",
    }
    for table in transferred:
        assert f"UPDATE public.{table}" in claim
    for frozen in (
        "dataset_releases", "dataset_split_assignments",
        "dataset_release_items", "dataset_exclusions",
    ):
        assert f"UPDATE public.{frozen}" not in claim


def test_append_only_exception_changes_only_the_audited_owner_coordinate():
    guard = _function("reject_canonical_feedback_mutation")
    assert "event.source_owner_principal_id::text = source_id" in guard
    assert "event.target_owner_principal_id::text = target_id" in guard
    assert "(old_row - 'owner_principal_id')" in guard
    assert "(new_row - 'owner_principal_id')" in guard
    assert "TG_OP = 'UPDATE'" in guard
    assert "RAISE EXCEPTION 'canonical feedback evidence is append-only'" in guard


def test_attempt_transfer_is_atomic_across_deferred_coordinate_constraints():
    assert "DEFERRABLE INITIALLY DEFERRED" in SQL
    attempt_guard = _function("protect_recording_attempt_coordinates")
    assert "owner_claim_events event" in attempt_guard
    assert "(old_row - 'owner_principal_id')" in attempt_guard
    assert "TG_OP = 'DELETE'" in attempt_guard


def test_claim_rpc_is_not_executable_from_browser_roles():
    assert (
        "REVOKE ALL ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)\n"
        "    FROM PUBLIC, anon, authenticated;"
    ) in SQL
    assert (
        "GRANT EXECUTE ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)\n"
        "    TO service_role;"
    ) in SQL
