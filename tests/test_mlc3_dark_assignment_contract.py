"""CI-fast boundaries; the executable PostgreSQL rehearsal is separate."""
from pathlib import Path

from services.data_purge_registry import DEPENDENCIES, NON_SUBJECT_RELATIONS


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/add_mlc3_dark_assignment_frames.sql").read_text()
TABLES = (
    "learning_profile_observations", "exercise_selection_feature_snapshots",
    "exercise_candidate_sets", "exercise_candidates", "exercise_assignments",
    "exercise_randomization_assignments", "exercise_requests",
)


def test_migration_additive_and_no_activation_or_legacy_learning_writes():
    assert "0314\tadd_mlc3_dark_assignment_frames.sql" in (ROOT / "migrations/manifest.txt").read_text()
    assert SQL.startswith("-- 0314") and SQL.rstrip().endswith("COMMIT;")
    for forbidden in (
        "UPDATE public.processing_purpose_registry", "INSERT INTO public.ml_judgments",
        "INSERT INTO public.ml_rendered_exposures", "INSERT INTO public.ml_dataset",
        "INSERT INTO public.confident_voice_practice", "INSERT INTO public.ml_model_runs",
        "CREATE POLICY", "GRANT ALL",
    ):
        assert forbidden not in SQL


def test_every_personal_table_is_dark_rpc_only_append_only_and_purge_classified():
    deps = {d.relation: d for d in DEPENDENCIES}
    for table in TABLES:
        begin = SQL.index(f"CREATE TABLE IF NOT EXISTS public.{table} (")
        end = SQL.index("\n);", begin)
        definition = SQL[begin:end]
        assert "serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user)" in definition
        assert "dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)" in definition
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in SQL
        assert deps[table].disposition == "external_review"
        assert deps[table].selector_column == "acquisition_principal_id"
        assert deps[table].locator_kind == "principal"
    assert "exercise_media_availability_checks" in NON_SUBJECT_RELATIONS
    assert "REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role" in SQL
    assert "GRANT SELECT ON public.%I TO service_role" in SQL
    assert "reject_mlc2_immutable_mutation" in SQL


def test_snapshot_and_inventory_derived_by_database_not_payload():
    finalizer = SQL[SQL.index("CREATE OR REPLACE FUNCTION public.finalize_exercise_dark_assignment_v1("):]
    signature = finalizer[:finalizer.index(") RETURNS")]
    assert "JSONB" not in signature
    for field in ("source_visibility_snapshot PG_SNAPSHOT", "recorded_xid XID8", "pg_visible_in_snapshot", "observed_at < assignment_at", "SOURCE_NOT_COMMITTED_ASOF", "CONCURRENT_HISTORY_RETRY"):
        assert field in SQL
    assert "FROM public.exercise_catalog_snapshot_items i" in finalizer
    assert "INVENTORY_INCOMPLETE" in finalizer
    assert "CATALOG_STALE" in finalizer
    assert "not_collected_dark" in finalizer


def test_rng_is_not_dataset_split_or_a_label():
    for item in ("exercise-80-20-simulation-v1", "sha256-first52-v1", "protected_seed BYTEA", "probability_numerator", "probability_denominator", "insufficient_assignment_probability", "dark_non_exposure", "deterministic_singleton"):
        assert item in SQL
    assert "ml_supervision_examples" not in SQL
    assert "UPDATE public.ml_speaker_split_assignments" not in SQL


def test_no_runtime_route_imports_assignment_rpc():
    for directory in ("routes", "workers"):
        for path in (ROOT / directory).rglob("*.py"):
            contents = path.read_text()
            assert "finalize_exercise_dark_assignment_v1" not in contents
            assert "register_exercise_no_match_request_v1" not in contents


def test_exact_postblind_requests_require_live_authority_before_replay():
    body = SQL[SQL.index("CREATE OR REPLACE FUNCTION public.register_exercise_no_match_request_v1("):]
    assert body.index("require_exercise_assignment_authority_v1") < body.index("IF result.id IS NOT NULL")
    for clause in ("judgment.actor_provenance <> 'blind_coach'", "judgment.evidence_span_id <> review.evidence_span_id", "packet.audio_lineage_id <> a.audio_lineage_id", "post_judgment_reveal_accessed", "dark_pending"):
        assert clause in body
