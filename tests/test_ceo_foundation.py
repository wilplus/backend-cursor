from pathlib import Path

import pytest

from services import ceo
from tests.fakes import FakeSupabaseClient, swap_attr


def test_bootstrap_returns_latest_revision_and_default_bug_surface():
    result = ceo.assemble_bootstrap(
        projects=[
            {"project_key": "research", "name": "Research", "position": 1},
            {"project_key": "product", "name": "Product", "position": 0},
        ],
        features=[],
        artifacts=[{"id": "a1", "project_key": "product"}],
        revisions=[
            {"id": "r1", "artifact_id": "a1", "version": 1},
            {"id": "r3", "artifact_id": "a1", "version": 3},
            {"id": "r2", "artifact_id": "a1", "version": 2},
        ],
        view_states=[{
            "project_key": "research",
            "surface": "overview",
            "active_feature_id": "f2",
            "active_lens": "vision",
        }],
    )

    assert [row["project_key"] for row in result["projects"]] == [
        "product",
        "research",
    ]
    assert result["artifacts"][0]["revision"]["id"] == "r3"
    assert result["view_state"] == [
        {
            "project_key": "product",
            "surface": "bugs",
            "active_feature_id": None,
            "active_lens": "architecture",
        },
        {
            "project_key": "research",
            "surface": "overview",
            "active_feature_id": "f2",
            "active_lens": "vision",
        },
    ]


def test_bug_surface_clears_stale_feature_before_storage():
    client = FakeSupabaseClient()
    with swap_attr(ceo.db, "client", client):
        saved = ceo.save_view_state("admin-1", "product", {
            "surface": "bugs",
            "active_feature_id": "stale-feature",
            "active_lens": "ml",
        })

    assert saved["active_feature_id"] is None
    payload = client.tables["ceo_admin_view_state"].payload
    assert payload["admin_user_id"] == "admin-1"
    assert payload["project_key"] == "product"
    assert payload["active_feature_id"] is None


def test_feature_address_cannot_cross_product_research_boundary():
    client = FakeSupabaseClient({
        "ceo_features": [{
            "id": "research-feature",
            "project_key": "research",
            "status": "active",
        }],
    })
    with swap_attr(ceo.db, "client", client):
        with pytest.raises(ceo.CeoValidationError, match="not active"):
            ceo.save_view_state("admin-1", "product", {
                "surface": "overview",
                "active_feature_id": "research-feature",
                "active_lens": "architecture",
            })

    assert "ceo_admin_view_state" not in client.tables


def test_valid_feature_address_is_upserted_with_fixed_vocabulary():
    client = FakeSupabaseClient({
        "ceo_features": [{
            "id": "product-feature",
            "project_key": "product",
            "status": "active",
        }],
    })
    with swap_attr(ceo.db, "client", client):
        saved = ceo.save_view_state("admin-1", "PRODUCT", {
            "surface": "tasks",
            "active_feature_id": "product-feature",
            "active_lens": "VISION",
        })

    assert saved == {
        "project_key": "product",
        "surface": "tasks",
        "active_feature_id": "product-feature",
        "active_lens": "vision",
    }
    query = client.tables["ceo_admin_view_state"]
    assert ("upsert", (query.payload,), {
        "on_conflict": "admin_user_id,project_key",
    }) in query.calls


def test_migration_keeps_ceo_service_role_only_and_seeds_fixed_tree():
    sql = (
        Path(__file__).parents[1] / "migrations" / "add_ceo_foundation.sql"
    ).read_text()

    for table in (
        "ceo_projects",
        "ceo_features",
        "ceo_artifacts",
        "ceo_artifact_revisions",
        "ceo_admin_view_state",
    ):
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated" in sql
    assert "'product', 'Product'" in sql
    assert "'research', 'Research'" in sql
    assert "'vision_document', 'manual'" in sql
