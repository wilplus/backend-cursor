from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations" / "add_mlc2_confidence_dark_contracts.sql").read_text()


def _table(name: str) -> str:
    start = SQL.index(f"CREATE TABLE IF NOT EXISTS public.{name}")
    next_table = SQL.find("CREATE TABLE IF NOT EXISTS public.", start + 1)
    return SQL[start: next_table if next_table >= 0 else len(SQL)]


def _function(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION public.{name}")
    next_function = SQL.find("CREATE OR REPLACE FUNCTION public.", start + 1)
    return SQL[start: next_function if next_function >= 0 else len(SQL)]


def test_manifest_appends_confidence_dark_contracts_as_0303():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-1] == "0303\tadd_mlc2_confidence_dark_contracts.sql"


def test_classification_and_selection_are_typed_runs_on_one_surface():
    model_runs = _table("ml_model_runs")
    selection = _table("ml_selection_runs")
    assert "'classification', 'deterministic_policy'" in model_runs
    assert "learning_surface_id = 'confidence_classification'" in model_runs
    assert "pipeline_stage_id = 'classify'" in model_runs
    assert "pipeline_stage_id = 'select'" in model_runs
    assert "execution_kind = 'deterministic_policy'" in selection
    assert "exploration_probability = 0.20" in selection
    assert "classification_run_id" in selection
    assert "CREATE TABLE IF NOT EXISTS public.ml_confidence_selection" not in SQL


def test_machine_predictions_are_not_semantic_generation_artifacts():
    prediction = _table("ml_machine_predictions")
    assert "classification_run_id" in prediction
    assert "evidence_span_id" in prediction
    assert "confidence_score" in prediction
    assert "probability_distribution" in prediction
    assert "ml_semantic_artifacts" not in SQL
    assert "ml_generation_runs" not in SQL


def test_sampling_frame_freezes_complete_reproducible_selection():
    candidate_set = _table("ml_candidate_sets")
    candidates = _table("ml_candidates")
    selection = _table("ml_selection_runs")
    for token in (
        "pool_size", "eligible_count", "excluded_count", "selected_count",
        "frame_manifest", "immutable_pool_sha256", "candidate_set_version",
        "project_id", "recording_attempt_id", "take_id",
    ):
        assert token in candidate_set
    for token in (
        "exclusion_reason_code", "score", "rank", "selected",
        "selection_mode", "selection_reason_code", "sampling_probability",
        "rng_draw_index",
    ):
        assert token in candidates
    for token in (
        "selection_policy_version", "eligibility_policy_version",
        "threshold_version", "rng_algorithm", "rng_seed", "rng_draws",
    ):
        assert token in selection


def test_frame_finalization_is_atomic_idempotent_and_fail_closed():
    function = _function("finalize_mlc2_confidence_frame_v1")
    assert function.index("finalize_mlc2_outbox_event_v1") < function.index(
        "INSERT INTO public.ml_model_runs"
    )
    for insertion in (
        "ml_object_artifacts", "ml_evidence_spans", "ml_machine_predictions",
        "ml_candidate_sets", "ml_candidates",
    ):
        assert f"INSERT INTO public.{insertion}" in function
    assert "idempotent confidence replay changed immutable frame" in function
    assert "idempotent confidence replay changed canonical envelope" in function
    assert "confidence frame lacks current model-improvement consent" in function
    assert "exact positive span" in function
    assert "non-empty audio" in function
    assert "confidence outbox was finalized without its sampling frame" in function
    assert "complete candidate pool" in function
    assert "digest(convert_to(frame_manifest::text" in function


def test_new_tables_are_rls_append_only_and_rpc_only():
    for table in (
        "ml_model_runs", "ml_classification_runs", "ml_machine_predictions",
        "ml_selection_runs", "ml_candidate_sets", "ml_candidates",
    ):
        assert f"'{table}'" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    assert "REVOKE ALL ON TABLE public.%I FROM anon, authenticated" in SQL
    assert "GRANT SELECT ON TABLE public.%I TO service_role" in SQL
    assert "reject_mlc2_immutable_mutation" in SQL
    assert "REVOKE ALL ON FUNCTION public.finalize_mlc2_confidence_frame_v1" in SQL
    assert "GRANT EXECUTE ON FUNCTION public.finalize_mlc2_confidence_frame_v1" in SQL


def test_slice_contains_no_dataset_training_promotion_or_cutover_write():
    lowered = SQL.lower()
    assert "create table if not exists public.ml_dataset" not in lowered
    assert "create table if not exists public.ml_training" not in lowered
    assert "create table if not exists public.ml_promotion" not in lowered
    assert "moment_suggestion" not in lowered
    assert "confidence_labels" not in lowered
