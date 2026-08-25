from pathlib import Path

import pytest

from services import ceo_work_items as work
from tests.fakes import FakeSupabaseClient, swap_attr


def test_create_bug_atomically_returns_one_task_then_enriches(monkeypatch):
    client = FakeSupabaseClient(rpc_rows={
        "ceo_create_bug_with_task": [{
            "out_bug_id": "bug-1",
            "out_task_id": "task-1",
        }],
    })
    spawned = []
    monkeypatch.setattr(
        work,
        "_spawn_enrichment",
        lambda bug_id, task_id: spawned.append((bug_id, task_id)),
    )
    with swap_attr(work.db, "client", client):
        result = work.create_bug(
            "admin-1",
            "product",
            "The save button stalls",
            [{"kind": "image", "data_url": "data:image/jpeg;base64,AA"}],
        )

    assert result == {
        "bug_id": "bug-1",
        "task_id": "task-1",
        "generation_status": "pending",
    }
    assert spawned == [("bug-1", "task-1")]
    assert client.rpcs["ceo_create_bug_with_task"].payload == {
        "p_project_key": "product",
        "p_text": "The save button stalls",
        "p_attachments": [{
            "kind": "image",
            "data_url": "data:image/jpeg;base64,AA",
            "name": "",
        }],
        "p_created_by": "admin-1",
    }


def test_attachment_validation_is_bounded_and_repairs_legacy_strings():
    assert work.normalize_attachments(["data:image/png;base64,AA"]) == [{
        "kind": "image",
        "data_url": "data:image/png;base64,AA",
        "name": "",
    }]
    assert work.normalize_attachments(["https://files.example/bug.png"])[0][
        "data_url"
    ].startswith("https://")
    with pytest.raises(work.CeoWorkItemError, match="at most"):
        work.normalize_attachments([
            "data:image/png;base64,AA",
            "data:image/png;base64,BB",
            "data:image/png;base64,CC",
            "data:image/png;base64,DD",
            "data:image/png;base64,EE",
        ])


def test_reorder_uses_midpoints_and_refuses_cross_list_after_id():
    rows = [
        {"id": "a", "order_key": 100},
        {"id": "b", "order_key": 200},
        {"id": "c", "order_key": 300},
    ]
    assert work.plan_reorder(rows, "c", None) == 99
    assert work.plan_reorder(rows, "a", "b") == 250
    with pytest.raises(work.CeoWorkItemError, match="after_id"):
        work.plan_reorder(rows, "a", "research-task")


def test_manual_task_feature_correction_updates_its_source_bug():
    client = FakeSupabaseClient({
        "ceo_features": [{
            "id": "feature-1",
            "project_key": "product",
            "name": "Feature",
            "status": "active",
        }],
        "ceo_tasks": [{
            "id": "task-1",
            "project_key": "product",
            "bug_id": "bug-1",
            "feature_id": "feature-1",
            "attachments": [],
        }],
        "ceo_bugs": [{"id": "bug-1"}],
    })
    with swap_attr(work.db, "client", client):
        updated = work.update_task(
            "product", "task-1", {"feature_id": "feature-1"}
        )

    assert updated["feature_id"] == "feature-1"
    assert client.tables["ceo_tasks"].payload["manually_edited"] is True
    assert client.tables["ceo_bugs"].payload["classification_status"] == "manual"


def test_feature_correction_cannot_cross_product_research():
    client = FakeSupabaseClient({
        "ceo_features": [{
            "id": "research-feature",
            "project_key": "research",
            "name": "Research",
            "status": "active",
        }],
    })
    with swap_attr(work.db, "client", client):
        with pytest.raises(work.CeoWorkItemError, match="not active"):
            work.update_task(
                "product", "task-1", {"feature_id": "research-feature"}
            )


def test_late_model_result_cannot_overwrite_manual_feature_or_task(monkeypatch):
    client = FakeSupabaseClient({
        "ceo_bugs": [{
            "id": "bug-1",
            "project_key": "product",
            "feature_id": "manual-feature",
            "text": "Raw note",
            "classification_status": "manual",
        }],
        "ceo_tasks": [{
            "id": "task-1",
            "project_key": "product",
            "bug_id": "bug-1",
            "feature_id": "manual-feature",
            "title": "Founder title",
            "body": "Founder body",
            "manually_edited": True,
        }],
        "ceo_features": [
            {
                "id": "manual-feature",
                "project_key": "product",
                "name": "Manual",
                "status": "active",
            },
            {
                "id": "model-feature",
                "project_key": "product",
                "name": "Model",
                "status": "active",
            },
        ],
    })
    monkeypatch.setattr(work, "_model_draft", lambda *_args: {
        "feature_id": "model-feature",
        "title": "Model title",
        "body": "Model body",
        "priority": 1,
    })
    with swap_attr(work.db, "client", client):
        assert work.enrich_bug_task("bug-1", "task-1") is True

    assert client.tables["ceo_bugs"].payload is None
    payload = client.tables["ceo_tasks"].payload
    assert payload["feature_id"] == "manual-feature"
    assert payload["generation_status"] == "manual"
    assert "title" not in payload
    assert "body" not in payload


def test_completion_uses_atomic_status_history_and_reevaluation_rpc():
    client = FakeSupabaseClient(
        {"ceo_tasks": [{"id": "task-1", "project_key": "research"}]},
        rpc_rows={"ceo_complete_task": [{
            "out_task_id": "task-1",
            "out_project_key": "research",
            "out_feature_id": None,
        }]},
    )
    with swap_attr(work.db, "client", client):
        changed = work.complete_task("admin-1", "research", "task-1")

    assert changed is True
    assert client.rpcs["ceo_complete_task"].payload == {
        "p_task_id": "task-1",
        "p_admin_user_id": "admin-1",
    }


def test_markdown_keeps_product_and_research_exports_named_separately():
    exported = work.task_markdown("research", [{
        "title": "Validate hypothesis",
        "priority": 1,
        "user_story": "As a researcher, I want evidence.",
        "body": "Pre-register the analysis.",
    }])
    assert exported.startswith("# CEO — Research tasks")
    assert "Validate hypothesis" in exported
    assert "Product" not in exported


def test_phase_two_migration_is_admin_service_role_only_and_migrates_legacy():
    sql = (
        Path(__file__).parents[1] / "migrations" / "add_ceo_work_items.sql"
    ).read_text()
    for table in (
        "ceo_bugs",
        "ceo_tasks",
        "ceo_timeline_events",
        "ceo_reevaluation_requests",
    ):
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated" in sql
    assert "ceo_create_bug_with_task" in sql
    assert "ceo_complete_task" in sql
    assert "ON DELETE CASCADE" in sql
    assert "FROM public.dev_bugs" in sql
    assert "FROM public.dev_tasks" in sql
