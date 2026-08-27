from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "migrations" / "add_mlc2_confidence_producer_dark_integration.sql"
)
SQL = MIGRATION.read_text()


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def _table(name: str) -> str:
    start = SQL.index(f"CREATE TABLE IF NOT EXISTS public.{name}")
    end = SQL.find("CREATE TABLE IF NOT EXISTS public.", start + 1)
    return SQL[start:end if end >= 0 else len(SQL)]


def test_manifest_appends_slice4_as_0304():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-2] == (
        "0304\tadd_mlc2_confidence_producer_dark_integration.sql"
    )


def test_take_promotion_and_outbox_are_one_atomic_rpc():
    function = _function(
        "promote_recording_attempt_with_mlc2_confidence_v1"
    )
    assert function.index("promote_recording_attempt_to_take_v1") < \
        function.index("enqueue_mlc2_outbox_event_v1")
    assert function.index("enqueue_mlc2_outbox_event_v1") < \
        function.index("INSERT INTO public.ml_confidence_producer_receipts")
    for requirement in (
        "cloudflare_r2", "pooled_model_improvement", "resolved speaker",
        "pre-cutover Take", "source_manifest_sha256",
    ):
        assert requirement in function


def test_confidence_worker_claim_cannot_steal_another_surface():
    function = _function("claim_mlc2_confidence_outbox_v1")
    assert "learning_surface_id = 'confidence_classification'" in function
    assert "event_type = 'confidence_take_ready'" in function
    assert "FOR UPDATE SKIP LOCKED" in function
    assert "lease_expires_at" in function


def test_blind_packet_is_built_from_immutable_selected_evidence():
    function = _function("create_mlc2_confidence_blind_packet_v1")
    assert "row.selected AND row.eligible" in function
    assert "p_reviewer_principal_id = candidate_set.acquisition_principal_id" \
        in function
    assert "audio_sha256" in function
    assert "rating_audio_unclear" in function
    for answer_hint in (
        "machine_prediction", "confidence_score", "rank",
        "selection_reason_code", "sampling_probability", "rng_seed",
    ):
        assert f"'{answer_hint}'" not in function


def test_blind_judgment_requires_render_and_reveal_requires_judgment():
    submit = _function("submit_mlc2_confidence_blind_judgment_v1")
    reveal = _function("reveal_mlc2_confidence_review_v1")
    assert "ml_rendered_exposures" in submit
    assert "authenticated rendered exposure" in submit
    assert "ml_judgments" in submit
    assert "ml_review_assignment_events" in submit
    assert submit.index("INSERT INTO public.ml_judgments") < submit.index(
        "INSERT INTO public.ml_review_assignment_events"
    )
    assert "immutable judgment" in reveal
    assert "reveal_ml_review_assignment_v1" in reveal


def test_new_tables_are_append_only_rls_and_rpc_only():
    for table in (
        "ml_confidence_producer_receipts", "ml_confidence_blind_packets",
    ):
        assert "created_at" in _table(table)
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in SQL
        assert f"GRANT SELECT ON TABLE public.{table} TO service_role" in SQL
        assert f"{table}_append_only" in SQL
    assert "GRANT INSERT" not in SQL
    assert "GRANT UPDATE" not in SQL
    assert "GRANT DELETE" not in SQL


def test_slice4_stays_additive_and_has_no_release_training_or_promotion():
    destructive = re.sub(
        r"DROP TRIGGER IF EXISTS.*?;", "", SQL, flags=re.I | re.S,
    )
    assert not re.search(r"\bDROP\s+(TABLE|COLUMN)\b", destructive, re.I)
    assert not re.search(r"\bTRUNCATE\b", SQL, re.I)
    assert not re.search(r"\bDELETE\s+FROM\b", SQL, re.I)
    lowered = SQL.lower()
    assert "create table if not exists public.ml_dataset" not in lowered
    assert "create table if not exists public.ml_training" not in lowered
    assert "create table if not exists public.ml_promotion" not in lowered
    assert "moment_suggestion" not in lowered
    assert "confidence_labels" not in lowered


def test_health_keeps_all_downstream_capabilities_disabled():
    health = _function("get_mlc2_confidence_slice4_health_v1")
    assert "'producer_activation', 'disabled_in_application_config'" in health
    assert "'dataset_creation_enabled', false" in health
    assert "'training_enabled', false" in health
    assert "'promotion_enabled', false" in health
