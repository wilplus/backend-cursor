from pathlib import Path

import pytest

from services import ceo
from tests.fakes import FakeSupabaseClient, swap_attr


ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
FEATURE_ID = "22222222-2222-4222-8222-222222222222"
COMMENT_ID = "33333333-3333-4333-8333-333333333333"


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


def test_bootstrap_attaches_reevaluation_status_to_comments():
    result = ceo.assemble_bootstrap(
        projects=[],
        features=[],
        artifacts=[],
        revisions=[],
        view_states=[],
        timeline_events=[{"id": "event-1"}],
        comments=[{"id": COMMENT_ID, "artifact_id": ARTIFACT_ID}],
        reevaluation_requests=[{
            "trigger_type": "admin_requested",
            "trigger_id": COMMENT_ID,
            "status": "processing",
        }],
    )

    assert result["timeline"] == [{"id": "event-1"}]
    assert result["comments"] == [{
        "id": COMMENT_ID,
        "artifact_id": ARTIFACT_ID,
        "reevaluation_status": "processing",
    }]


def test_architecture_content_is_normalized_to_fixed_contract():
    normalized = ceo.normalize_artifact_content("architecture", {
        "flows": [{
            "input": "Voice sample",
            "measurement": "F0 variance",
            "output": "Practice intervention",
            "ignored": "does not cross the boundary",
        }],
        "risks": [{"text": "Sparse baseline"}],
        "next_steps": [{"text": "Validate with held-out speakers"}],
        "invented_section": [{"text": "ignored"}],
    })

    assert set(normalized) == {"flows", "risks", "next_steps", "citations"}
    assert set(normalized["flows"][0]) == {
        "id", "input", "measurement", "output",
    }
    assert normalized["risks"][0]["text"] == "Sparse baseline"


def test_ml_edges_must_reference_nodes_in_the_same_revision():
    with pytest.raises(ceo.CeoValidationError, match="reference saved nodes"):
        ceo.normalize_artifact_content("ml", {
            "nodes": [{"id": "data", "label": "Data"}],
            "edges": [{"from": "data", "to": "missing"}],
        })


def test_create_feature_uses_atomic_rpc_and_returns_refreshed_bootstrap():
    client = FakeSupabaseClient(rpc_rows={
        "ceo_create_feature": [{"out_feature_id": FEATURE_ID}],
    })
    expected = {"projects": [{"project_key": "product"}]}
    with swap_attr(ceo.db, "client", client), swap_attr(
        ceo, "get_bootstrap", lambda _admin: expected
    ):
        result = ceo.create_feature("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "PRODUCT", {
            "name": "  New signal  ",
            "description": "A bounded feature",
        })

    assert result == {"feature_id": FEATURE_ID, "bootstrap": expected}
    assert client.rpcs["ceo_create_feature"].payload == {
        "p_project_key": "product",
        "p_name": "New signal",
        "p_description": "A bounded feature",
        "p_created_by": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }


def test_artifact_save_rejects_stale_version_before_rpc():
    client = FakeSupabaseClient({
        "ceo_artifacts": [{
            "id": ARTIFACT_ID,
            "project_key": "product",
            "feature_id": FEATURE_ID,
            "lens": "vision",
        }],
        "ceo_artifact_revisions": [{"version": 4}],
    })
    with swap_attr(ceo.db, "client", client):
        with pytest.raises(ceo.CeoConflictError, match="reload"):
            ceo.save_artifact_revision(
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                ARTIFACT_ID,
                {"expected_version": 3, "content": {"document": "Vision"}},
            )

    assert "ceo_save_artifact_revision" not in client.rpcs


def test_artifact_save_appends_manual_revision_and_refreshes_bootstrap():
    client = FakeSupabaseClient(
        {
            "ceo_artifacts": [{
                "id": ARTIFACT_ID,
                "project_key": "product",
                "feature_id": FEATURE_ID,
                "lens": "vision",
            }],
            "ceo_artifact_revisions": [{"version": 2}],
        },
        rpc_rows={"ceo_save_artifact_revision": [{"out_version": 3}]},
    )
    expected = {"artifacts": []}
    with swap_attr(ceo.db, "client", client), swap_attr(
        ceo, "get_bootstrap", lambda _admin: expected
    ):
        result = ceo.save_artifact_revision(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            ARTIFACT_ID,
            {"expected_version": 2, "content": {"document": "North star"}},
        )

    assert result == {"artifact_id": ARTIFACT_ID, "bootstrap": expected}
    assert client.rpcs["ceo_save_artifact_revision"].payload["p_content"] == {
        "document": "North star",
    }


def test_comment_atomically_queues_reevaluation_and_refreshes_bootstrap():
    client = FakeSupabaseClient(
        {"ceo_artifacts": [{
            "id": ARTIFACT_ID,
            "project_key": "product",
            "feature_id": FEATURE_ID,
            "lens": "ml",
        }]},
        rpc_rows={"ceo_comment_and_request_reevaluation": [{
            "out_comment_id": COMMENT_ID,
        }]},
    )
    expected = {"comments": []}
    with swap_attr(ceo.db, "client", client), swap_attr(
        ceo, "get_bootstrap", lambda _admin: expected
    ):
        result = ceo.comment_and_request_reevaluation(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            ARTIFACT_ID,
            {"comment": " Re-check the training boundary. "},
        )

    assert result == {
        "comment_id": COMMENT_ID,
        "analysis_run": None,
        "bootstrap": expected,
    }
    assert client.rpcs["ceo_comment_and_request_reevaluation"].payload == {
        "p_artifact_id": ARTIFACT_ID,
        "p_comment": "Re-check the training boundary.",
        "p_created_by": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }


def test_overview_editing_migration_is_service_role_only_and_versioned():
    sql = (
        Path(__file__).parents[1]
        / "migrations"
        / "add_ceo_overview_editing.sql"
    ).read_text()

    assert "ALTER TABLE public.ceo_artifact_comments ENABLE ROW LEVEL SECURITY" in sql
    assert (
        "REVOKE ALL ON TABLE public.ceo_artifact_comments FROM anon, authenticated"
        in sql
    )
    assert "CREATE OR REPLACE FUNCTION public.ceo_create_feature" in sql
    assert "CREATE OR REPLACE FUNCTION public.ceo_latest_artifact_revisions" in sql
    assert "SELECT DISTINCT ON (revision.artifact_id)" in sql
    assert "CREATE OR REPLACE FUNCTION public.ceo_save_artifact_revision" in sql
    assert "v_version := v_version + 1" in sql
    assert "CREATE OR REPLACE FUNCTION public.ceo_comment_and_request_reevaluation" in sql
