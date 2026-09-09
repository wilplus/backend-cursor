from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask, request

from routes.v2.coach import _coach_inline_canonical_queue_rows
from routes.v2 import coach_guidance_delivery as guidance_routes
from services.coach_guidance_delivery import inline_authoring_is_enabled
from services.data_purge_registry import DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "migrations/add_mlc3_coach_inline_exercise_authoring_d5.sql"
).read_text()
ROUTE = (ROOT / "routes/v2/coach_guidance_delivery.py").read_text()
COACH_ROUTE = (ROOT / "routes/v2/coach.py").read_text()
COACH_SERVICE_ROUTE = (
    ROOT / "routes/v2/mlc3_first_client_coach.py"
).read_text()
SERVICE = (ROOT / "services/coach_guidance_delivery.py").read_text()


def _function(name: str) -> str:
    marker = f"CREATE OR REPLACE FUNCTION public.{name}("
    start = MIGRATION.index(marker)
    return MIGRATION[start:MIGRATION.index("\n$$;", start) + 4]


def test_inline_authoring_gate_defaults_closed():
    assert inline_authoring_is_enabled() is False
    assert "MLC3_COACH_INLINE_AUTHORING_ENABLED" in SERVICE


def test_release_migration_is_manifested_as_0324():
    manifest = (ROOT / "migrations/manifest.txt").read_text()
    assert "0324\tadd_mlc3_coach_inline_exercise_authoring_d5.sql" in manifest
    assert "release migration 0324" in MIGRATION


def test_completed_take_is_typed_as_source_not_practice():
    context = _function("prepare_coach_inline_guidance_context_v1")
    assert "source_before_exercise" in context
    assert "exercise_practice_attempt" not in context
    assert "exercise_practice_outcome" not in context
    assert "complete_synthetic_coach_guidance_batch_v1" in context
    assert "record_synthetic_guidance_reveal_access_v1" in context
    assert 'r["transcript"] = ""' in COACH_ROUTE
    assert '"playback_reference_id": assignment_id' in COACH_ROUTE
    assert '"audio_ref": row.get("audio_ref")' not in COACH_ROUTE[
        COACH_ROUTE.index("def v2_coach_confidence_queue"):
        COACH_ROUTE.index("def v2_coach_confirm_session_language")
    ]
    assert "source-playback/<assignment_id>" in COACH_SERVICE_ROUTE
    assert COACH_SERVICE_ROUTE.count(
        "resolve_coach_inline_blind_audio_read"
    ) >= 1
    prepare = _function("prepare_coach_inline_blind_batch_v1")
    assert "ml_review_assignments" in prepare
    assert "exercise_blind_packets" in prepare
    assert "ml_presentations" in prepare
    assert "feedback_v3_membership_items" in prepare
    assert "exercise_practice_attempt" not in prepare


def test_visible_response_is_the_exact_batch_judgment():
    render = _function("ack_coach_inline_blind_render_v1")
    exact_writer = _function("submit_mlc2_confidence_blind_judgment_v1")
    judgment = _function("submit_coach_inline_blind_judgment_v1")
    assert "ack_mlc2_rendered_exposure_v1" in render
    assert "submit_mlc2_confidence_blind_judgment_v1" in judgment
    assert "blind_judgment_submitted" in judgment
    assert "mlc2-blind-judgment-assignment:" in exact_writer
    assert "mlc2-blind-judgment-idempotency:" in exact_writer
    assert "LEAST(assignment_lock, idempotency_lock)" in exact_writer
    assert "'replayed', true" in exact_writer
    assert exact_writer.index("WHERE row.idempotency_key") < exact_writer.index(
        "event.event_kind = 'revealed'"
    )
    assert "require_coach_guidance_assignment_live_v1" in render
    assert "require_coach_guidance_assignment_live_v1" in judgment
    assert "inline/assignments/<assignment_id>/render" in COACH_SERVICE_ROUTE
    assert "inline/assignments/<assignment_id>/judgments" in COACH_SERVICE_ROUTE


def test_canonical_queue_preserves_two_assignments_for_one_snippet():
    project_id = str(uuid4())
    take_id = str(uuid4())
    snippet_id = str(uuid4())

    def item(position: int) -> dict[str, object]:
        assignment_id = str(uuid4())
        return {
            "review_batch_id": str(uuid4()),
            "review_assignment_id": assignment_id,
            "blind_packet_id": str(uuid4()),
            "take_id": take_id,
            "snippet_id": snippet_id,
            "playback_reference_id": assignment_id,
            "presentation_id": str(uuid4()),
            "acknowledgement_token": str(uuid4()),
            "visible_payload_sha256": "a" * 64,
            "canonical_position": position,
            "judgment": None,
        }

    first, second = item(1), item(2)
    rows = _coach_inline_canonical_queue_rows(
        {"items": [first, second]},
        session_id=take_id,
        project_id=project_id,
    )
    assert len(rows) == 2
    assert [row["snippet_id"] for row in rows] == [snippet_id, snippet_id]
    assert [row["review_assignment_id"] for row in rows] == [
        first["review_assignment_id"], second["review_assignment_id"],
    ]
    assert [row["canonical_position"] for row in rows] == [1, 2]


def test_canonical_queue_fails_closed_on_reordered_inventory():
    assignment_id = str(uuid4())
    with pytest.raises(ValueError, match="COACH_INLINE_CANONICAL_ORDER_INVALID"):
        _coach_inline_canonical_queue_rows(
            {"items": [{
                "review_batch_id": str(uuid4()),
                "review_assignment_id": assignment_id,
                "blind_packet_id": str(uuid4()),
                "take_id": str(uuid4()),
                "snippet_id": str(uuid4()),
                "playback_reference_id": assignment_id,
                "presentation_id": str(uuid4()),
                "acknowledgement_token": str(uuid4()),
                "visible_payload_sha256": "a" * 64,
                "canonical_position": 2,
            }]},
            session_id=str(uuid4()),
            project_id=str(uuid4()),
        )


def test_context_requires_exact_feedback_response_and_no_match_offer():
    context = _function("prepare_coach_inline_guidance_context_v1")
    assert "require_feedback_v3_service_response_v1" in context
    assert "feedback_response_binding_id" in context
    assert "coach_exercise_requested" in context
    assert "LEFT JOIN LATERAL" in context
    assert "COALESCE(item.offer_outcome = 'coach_exercise_requested', false)" in context
    assert "selected_exercise_version_id" not in context or (
        "exercise_version_id', NULL" in context
    )
    assert "exercise_n1_source_pattern_results" in context
    assert "result_origin" not in context or "source_result" in context
    assert "packet.asr_transcript AS frozen_transcript" in context
    assert "snippet.transcript" not in context
    assert "COACH_INLINE_FROZEN_PACKET_INVENTORY_MISMATCH" in context


def test_ordinary_guidance_has_exact_assignment_bound_write_path():
    authority = _function("issue_coach_inline_general_authority_v1")
    guidance = _function("create_coach_inline_general_guidance_v1")
    assert "source_snapshot.receipt_id" not in authority
    assert "processing_authorization_receipts" not in authority
    assert "packet_snapshot.receipt_id" in authority
    assert "require_coach_guidance_receipt_authority_v1" in authority
    assert "coach_inline_general_guidance" in authority
    assert "pooled_learning_eligible" in authority
    assert "false" in authority
    assert "p_review_batch_id" in guidance
    assert "p_reveal_access_id" in guidance
    assert "p_review_assignment_id" in guidance
    assert "coach_inline_source_roles" in guidance
    assert "feedback_membership_id, feedback_candidate_id" in guidance
    assert "p_review_assignment_id, NULL, NULL" in guidance
    assert "general_product_guidance" in guidance
    assert "require_coach_guidance_media_live_v1" in guidance
    assert "exercise_practice" not in guidance
    assert "ml_judgments" not in guidance
    assert "create_coach_inline_general_guidance" in ROUTE
    assert "issue_coach_inline_general_authority" in ROUTE
    assert "not runtime_is_enabled() and not inline_authoring_is_enabled()" in ROUTE


def test_exercise_attachments_keep_exact_feedback_identity_required():
    constraint = "coach_guidance_feedback_identity_class_check"
    assert constraint in MIGRATION
    assert "attachment_class = 'general_product_guidance'" in MIGRATION
    assert "feedback_membership_id IS NOT NULL" in MIGRATION
    exercise = _function("create_coach_inline_exercise_attachment_v1")
    assert "p_feedback_membership_id" in exercise
    assert "p_feedback_candidate_id" in exercise
    assert "feedback_item.membership_id =" in exercise
    assert "feedback_item.candidate_id =" in exercise


def test_draft_is_case_bound_nonserving_and_nondataset():
    draft = _function("create_coach_inline_exercise_draft_v1")
    attachment = _function("create_coach_inline_exercise_attachment_v1")
    assert "user_source_dependent" in draft
    assert "source_before_exercise" in draft
    assert "awaiting_review" in MIGRATION
    assert "require_coach_guidance_assignment_live_v1" in draft
    assert "require_coach_guidance_media_live_v1" in draft
    assert "selected_exercise_version_id IS NULL" in attachment
    assert "serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user)" in MIGRATION
    assert "dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)" in MIGRATION


def test_private_preview_revalidates_and_returns_no_url():
    resolver = _function("resolve_coach_inline_media_read_v1")
    assert "coach-guidance-media-validity:" in resolver
    assert "require_coach_guidance_assignment_live_v1" in resolver
    assert "require_coach_guidance_authority_v1" in resolver
    assert "require_coach_guidance_media_live_v1" in resolver
    assert "object_key" in resolver
    assert "presign" not in resolver.lower()
    assert "CoachVideoR2Storage().get" in ROUTE
    assert ROUTE.count("resolve_coach_inline_media_read") >= 2
    assert '"Cache-Control"] = "private, no-store, max-age=0"' in ROUTE


def test_rpc_only_rls_and_terminal_schema_reload():
    for table in (
        "coach_inline_source_roles",
        "coach_inline_exercise_drafts",
        "coach_inline_context_assessments",
        "coach_inline_exercise_eligibility_reviews",
    ):
        rls_fragment = MIGRATION[
            MIGRATION.index(f"ALTER TABLE public.{table}"):
        ][:140]
        assert "ENABLE ROW LEVEL SECURITY" in rls_fragment
        assert any(dependency.relation == table for dependency in DEPENDENCIES)
    assert "GRANT SELECT ON TABLE public.coach_inline_exercise_drafts TO service_role" in MIGRATION
    assert "GRANT INSERT" not in MIGRATION
    assert (
        "REVOKE ALL ON FUNCTION public.reject_coach_inline_mutation_v1()\n"
        "    FROM PUBLIC, anon, authenticated, service_role;"
    ) in MIGRATION
    assert "resolve_coach_inline_blind_audio_read_v1" in MIGRATION
    assert "NOTIFY pgrst, 'reload schema';\nCOMMIT;" in MIGRATION


def test_principal_reviewer_and_deletion_edges_are_complete():
    assert "exercise_blind_packets_id_assignment_lineage_key" in MIGRATION
    assert "exercise_audio_lineages_id_principal_key" in MIGRATION
    assert "FOREIGN KEY (review_assignment_id, reviewer_principal_id)" in MIGRATION
    assert "FOREIGN KEY (audio_lineage_id, acquisition_principal_id)" in MIGRATION
    names = {dependency.code for dependency in DEPENDENCIES}
    assert "coach_inline_source_role_reviewers" in names
    assert "coach_inline_exercise_draft_authors" in names


def test_route_upload_is_r2_only_and_durable_before_write():
    assert "require_coach_video_r2()" in ROUTE
    assert "reserve_coach_inline_upload" in ROUTE
    assert ROUTE.index("reserve_coach_inline_upload") < ROUTE.index(
        "store_exact_object", ROUTE.index("def v2_coach_inline_exercise_draft")
    )
    assert "write_started" in ROUTE
    assert "write_acknowledged" in ROUTE
    assert '"finalized"' in ROUTE
    assert '"state": "awaiting_review"' in ROUTE


def test_ordinary_note_uses_inline_gate_and_exact_canonical_identity(monkeypatch):
    ids = {name: str(uuid4()) for name in (
        "user", "reviewer", "batch", "grant", "access", "assignment",
        "authority", "attachment",
    )}
    captured: dict[str, dict] = {}
    repository = SimpleNamespace(
        issue_coach_inline_general_authority=lambda payload: (
            captured.setdefault("authority", payload) or {"id": ids["authority"]}
        ),
        create_coach_inline_general_guidance=lambda payload: (
            captured.setdefault("attachment", payload)
            or {"id": ids["attachment"]}
        ),
    )
    # setdefault returns the payload, so use explicit exact stubs.
    def issue(payload):
        captured["authority"] = payload
        return {"id": ids["authority"]}

    def create(payload):
        captured["attachment"] = payload
        return {"id": ids["attachment"]}

    repository.issue_coach_inline_general_authority = issue
    repository.create_coach_inline_general_guidance = create
    monkeypatch.setattr(guidance_routes, "db", repository)
    monkeypatch.setattr(
        guidance_routes.identity_db,
        "get_owner_principal_for_user",
        lambda _user_id: {"id": ids["reviewer"]},
    )
    monkeypatch.setattr(guidance_routes, "runtime_is_enabled", lambda: False)
    monkeypatch.setattr(
        guidance_routes, "inline_authoring_is_enabled", lambda: True
    )
    app = Flask(__name__)
    view = guidance_routes.v2_coach_guidance_attachment
    while hasattr(view, "__wrapped__"):
        view = view.__wrapped__
    with app.test_request_context(
        "/api/v2/coach/guidance/attachments",
        method="POST",
        data={
            "review_batch_id": ids["batch"],
            "reveal_grant_id": ids["grant"],
            "reveal_access_id": ids["access"],
            "review_assignment_id": ids["assignment"],
            "feedback_membership_id": "",
            "feedback_candidate_id": "",
            "attachment_class": "general_product_guidance",
            "product_subcategory": "delivery",
            "written_note": "Slow down at the close.",
        },
        headers={"Idempotency-Key": "ordinary-note-1"},
    ):
        request.user_id = ids["user"]
        response, status = view()
    assert status == 201
    assert response.get_json()["serves_user"] is False
    assert captured["authority"] == {
        "p_review_batch_id": ids["batch"],
        "p_reveal_grant_id": ids["grant"],
        "p_reveal_access_id": ids["access"],
        "p_review_assignment_id": ids["assignment"],
        "p_reviewer_principal_id": ids["reviewer"],
        "p_idempotency_key": "ordinary-note-1:authority",
    }
    assert captured["attachment"]["p_authorization_snapshot_id"] == ids[
        "authority"
    ]
    assert "p_feedback_membership_id" not in captured["attachment"]
    assert "p_feedback_candidate_id" not in captured["attachment"]


def test_missing_exercise_feedback_identity_rejects_before_side_effects(
    monkeypatch,
):
    ids = {name: str(uuid4()) for name in ("user", "reviewer", "access")}
    side_effects: list[str] = []
    monkeypatch.setattr(
        guidance_routes.identity_db,
        "get_owner_principal_for_user",
        lambda _user_id: {"id": ids["reviewer"]},
    )
    monkeypatch.setattr(guidance_routes, "runtime_is_enabled", lambda: True)
    monkeypatch.setattr(
        guidance_routes, "inline_authoring_is_enabled", lambda: True
    )
    monkeypatch.setattr(
        guidance_routes,
        "_store_inline_general_media",
        lambda **_kwargs: side_effects.append("inline-storage"),
    )
    monkeypatch.setattr(
        guidance_routes,
        "store_exact_object",
        lambda **_kwargs: side_effects.append("service-storage"),
    )
    app = Flask(__name__)
    view = guidance_routes.v2_coach_guidance_attachment
    while hasattr(view, "__wrapped__"):
        view = view.__wrapped__
    with app.test_request_context(
        "/api/v2/coach/guidance/attachments",
        method="POST",
        data={
            "reveal_access_id": ids["access"],
            "feedback_membership_id": "",
            "feedback_candidate_id": "",
            "attachment_class": "mlc3_exercise",
            "written_note": "Exercise instructions.",
        },
        headers={"Idempotency-Key": "missing-exercise-identity"},
    ):
        request.user_id = ids["user"]
        response, status = view()
    assert status == 400
    assert response.get_json() == {"code": "INVALID_INPUT"}
    assert side_effects == []
