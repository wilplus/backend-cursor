"""Executable fences for the ED-PLF-1.3 Phase-1 boundary."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "migrations" / "add_phase1_processing_boundary.sql").read_text()
REHEARSAL = (
    ROOT / "tests" / "integration" / "phase1_processing_rehearsal.sql"
).read_text()


def _function_args(path: str, function_name: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == function_name:
            return {argument.arg for argument in (
                node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            )}
    raise AssertionError(f"{function_name} not found")


def test_power_score_has_no_retired_direction_inputs():
    args = _function_args("services/power_phrase_ranking.py", "power_score")
    assert "direction" not in args
    assert "breakthrough" not in args
    source = (ROOT / "services" / "power_phrase_ranking.py").read_text()
    assert "_DIRECTION_TERM" not in source
    assert "_W_D" not in source
    assert "_W_B" not in source


def test_universal_voice_confidence_has_no_demographic_runtime_contract():
    source = (ROOT / "services" / "voice_confidence.py").read_text()
    tree = ast.parse(source)
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    identifiers |= {
        node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
    }
    for retired in (
        "sex", "gender", "profile_sex", "sex_source",
        "male", "female", "speaker_sex",
    ):
        assert retired not in identifiers
    assert 'VERSION = "voice-confidence-universal-v3"' in source


def test_protected_user_data_modules_do_not_import_provider_client():
    protected = (
        "services/analysis_worker.py",
        "services/recording_transcription.py",
        "services/recording_piece_analysis.py",
        "services/best_presentation.py",
        "services/coach_comment_drafter.py",
        "services/master_doc_rag.py",
        "services/moment_suggestions.py",
        "services/stickiness.py",
        "routes/v2/lab_recording.py",
        "routes/v2/projects.py",
        "routes/v2/coach.py",
    )
    for relative in protected:
        source = (ROOT / relative).read_text()
        assert "services.openai_service" not in source, relative
        assert "from openai" not in source, relative
        assert "import openai" not in source, relative


def test_exercise_surface_is_registry_only_and_fail_closed():
    user_routes = (ROOT / "routes" / "v2" / "user_sessions.py").read_text()
    coach_routes = (ROOT / "routes" / "v2" / "coach.py").read_text()
    marker = '@operational_purpose_disabled("personalized_exercise_recommendation")'
    assert user_routes.count(marker) == 4
    assert coach_routes.count(marker) == 1
    assert "personalized_exercise_recommendation', 'phase2'" in MIGRATION
    assert "PHASE2_PURPOSE_FORBIDDEN" in MIGRATION


def test_retired_learning_tables_are_write_blocked_but_not_dropped():
    for table in (
        "training_labels", "shadow_predictions", "model_versions",
        "reflection_clips", "stress_snippets",
    ):
        assert f"'{table}'" in MIGRATION
    assert "RETIRED_DIRECTION_PIPELINE_WRITE_FORBIDDEN" in MIGRATION
    assert "DROP TABLE" not in MIGRATION.upper()


def test_phase1_evidence_and_release_fences_are_explicit():
    assert MIGRATION.count("CHECK (NOT pooled_learning_eligible)") >= 2
    assert "POLICY_COPY_HASH_MISMATCH" in MIGRATION
    assert "ORPHAN_CLEANUP_IN_PROGRESS" in MIGRATION
    assert "claim_phase1_orphan_audio_v1" in MIGRATION
    assert "has_table_privilege('service_role'" in REHEARSAL
    assert "passive authorization check created acceptance" in REHEARSAL
    assert "recording boundary replay duplicated canonical rows" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")


def test_no_direct_policy_or_acceptance_seed_exists():
    assert "INSERT INTO public.processing_policy_versions" not in MIGRATION
    assert "INSERT INTO public.processing_authorization_receipts" not in MIGRATION
    assert "register_phase1_policy_v1" in MIGRATION
    assert "activate_phase1_policy_v1" in MIGRATION


def test_cleanup_migration_is_pending_and_explicitly_not_manifested():
    pending = (
        ROOT / "migrations" / "pending" / "cleanup_retired_sex_data.sql"
    ).read_text()
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "PREVIEW" in pending.upper()
    assert "cleanup_retired_sex_data.sql" not in manifest
