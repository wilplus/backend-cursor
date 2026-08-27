import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "add_learning_surface_exposure_receipts.sql"
SQL = MIGRATION.read_text()

SURFACES = {
    "confidence_classification", "correction_generation",
    "coach_comment_generation", "praise_generation", "praise_selection",
    "correction_selection", "ideal_text_generation",
}


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_migration_is_0299_and_contains_all_seven_distinct_surfaces():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0299\tadd_learning_surface_exposure_receipts.sql" in manifest
    for surface in SURFACES:
        assert f"'{surface}'" in SQL
    assert "generic_label" not in SQL


def test_prepared_packet_and_true_receipt_are_separate_append_only_tables():
    for table in (
        "learning_surface_presentations",
        "learning_surface_exposure_receipts",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in SQL
        assert f"ALTER TABLE public.{table}" in SQL
        assert "ENABLE ROW LEVEL SECURITY" in SQL
        assert f"GRANT ALL ON TABLE public.{table} TO service_role;" in SQL
        assert f"{table}_append_only" in SQL


def test_ack_is_post_render_only_and_shadow_is_unacknowledgeable():
    ack = _function("ack_learning_surface_exposure_v1")
    assert "p_render_instance_id" in ack
    assert "presentation.evaluation_only" in ack
    assert "presentation.delivery_mode = 'shadow'" in ack
    assert "shadow presentation cannot be rendered" in ack
    assert "INSERT INTO public.learning_surface_exposure_receipts" in ack
    for forbidden in ("skip", "close", "timeout", "negative", "decision"):
        assert forbidden not in ack.lower()


def test_presentation_freezes_inventory_selection_versions_and_visible_payload():
    table = re.search(
        r"CREATE TABLE IF NOT EXISTS public\.learning_surface_presentations "
        r"\((.*?)\n\);", SQL, flags=re.S,
    ).group(1)
    for field in (
        "complete_candidate_set", "selected_candidate", "visible_payload",
        "versions", "content_hash", "actor_role", "actor_id",
        "delivery_mode", "evaluation_only",
    ):
        assert field in table


def test_only_a_successful_canonical_take_can_anchor_a_presentation():
    create = _function("create_learning_surface_presentation_v1")
    assert "JOIN public.takes canonical_take" in create
    assert "canonical_take.project_id = p_project_id" in create
    assert "canonical_take.owner_principal_id = p_owner_principal_id" in create


def test_blind_review_packet_rejects_prior_labels_predictions_and_transcript():
    create = _function("create_learning_surface_presentation_v1")
    for forbidden_key in (
        "machine_prediction", "user_self_report", "coach_judgment",
        "peer_judgment", "exact_text", "transcript_text",
    ):
        assert f"p_visible_payload ? '{forbidden_key}'" in create
    assert "coach draft requires an immutable blind judgment" in create
    assert "evidence_review_assignments" in create


def test_server_selection_timestamp_is_explicitly_not_render_proof():
    assert "shown_at is a legacy server-selection timestamp" in SQL
    assert "is not proof that a client rendered the item" in SQL


def test_claim_transfer_hook_preserves_new_surface_ownership():
    transfer = _function("transfer_learning_surfaces_on_owner_claim")
    assert "willab.owner_claim_source" in transfer
    assert "willab.owner_claim_target" in transfer
    assert "UPDATE public.learning_surface_presentations" in transfer
    assert "UPDATE public.learning_surface_exposure_receipts" in transfer
