from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/add_confident_moment_coaching_bundle_v1.sql").read_text()


def test_d11_projection_revalidates_blind_coach_and_delivery_authority():
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1", 1
    )[1].split("END $$;", 1)[0]
    shared_guard = SQL.split(
        "CREATE OR REPLACE FUNCTION public.require_feedback_language_coach_source_live_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "require_feedback_language_coach_source_live_v1" in projection
    for required in (
        "coach_guidance_reveal_accesses",
        "coach_guidance_reveal_grants",
        "coach_guidance_reveal_grant_judgments",
        "coach_guidance_review_frame_items",
        "coach_inline_source_roles",
        "ml_judgments",
        "actor_provenance='blind_coach'",
        "require_coach_guidance_reviewer_access_v1",
        "require_coach_guidance_assignment_live_v1",
        "feedback_candidate_output_sha256_v1(revision_row.feedback_candidate_id)=p_candidate_output_sha256",
    ):
        assert required in shared_guard
