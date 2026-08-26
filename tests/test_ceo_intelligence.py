from pathlib import Path
from types import SimpleNamespace

import pytest

from services import ceo, ceo_intelligence as intelligence
from tests.fakes import FakeSupabaseClient, swap_attr


ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FEATURE_ID = "22222222-2222-4222-8222-222222222222"
ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "33333333-3333-4333-8333-333333333333"
SOURCE_ID = "44444444-4444-4444-8444-444444444444"
REVISION_ID = "55555555-5555-4555-8555-555555555555"


def _pilot_rows() -> dict:
    return {
        "ceo_features": [{
            "id": FEATURE_ID,
            "project_key": "product",
            "slug": intelligence.PILOT_SLUG,
            "name": "Confident Voice Practice",
            "status": "active",
        }],
        "ceo_artifacts": [{
            "id": ARTIFACT_ID,
            "project_key": "product",
            "feature_id": FEATURE_ID,
            "lens": "architecture",
            "scope_kind": "feature",
        }],
    }


def test_manual_source_is_immutable_snapshot_for_pilot_only():
    client = FakeSupabaseClient(
        _pilot_rows(),
        rpc_rows={"ceo_capture_source_snapshot": [{"out_snapshot_id": SOURCE_ID}]},
    )
    with swap_attr(intelligence.db, "client", client):
        result = intelligence.add_manual_source(ADMIN_ID, FEATURE_ID, {
            "source_type": "research_paper",
            "title": "Vocal confidence paper",
            "source_ref": "doi:10.0000/example",
            "content": "Methods and findings pasted from the physical paper.",
        })

    assert result == {"source_snapshot_id": SOURCE_ID}
    payload = client.rpcs["ceo_capture_source_snapshot"].payload
    assert payload["p_project_key"] == "product"
    assert payload["p_feature_id"] == FEATURE_ID
    assert payload["p_source_type"] == "research_paper"
    assert len(payload["p_content_hash"]) == 64


def test_analysis_request_is_durable_and_dispatched_only_when_new(monkeypatch):
    client = FakeSupabaseClient(
        _pilot_rows(),
        rpc_rows={"ceo_create_analysis_run": [{
            "out_run_id": RUN_ID,
            "out_created": True,
        }]},
    )
    dispatched: list[str] = []
    monkeypatch.setattr(intelligence, "_dispatch", dispatched.append)
    with swap_attr(intelligence.db, "client", client):
        result = intelligence.request_analysis(ADMIN_ID, ARTIFACT_ID, {
            "reason": "Use the latest implementation.",
        })

    assert result == {"analysis_run_id": RUN_ID, "created": True}
    assert dispatched == [RUN_ID]
    assert client.rpcs["ceo_create_analysis_run"].payload["p_artifact_id"] == ARTIFACT_ID


def test_generated_content_drops_unknown_citations_and_normalizes_rows():
    content = intelligence._generated_content("architecture", {
        "content": {
            "flows": [{
                "input": "Recording",
                "measurement": "Qualitative voice evidence",
                "output": "Practice guidance",
            }],
            "risks": [{"text": "Sparse evidence"}],
            "next_steps": [{"text": "Validate the pipeline"}],
        },
        "citations": [
            {"source_id": SOURCE_ID, "claim": "The source describes the pipeline."},
            {"source_id": "not-evidence", "claim": "Invented citation"},
        ],
    }, {SOURCE_ID})

    assert content["flows"][0]["input"] == "Recording"
    assert len(content["citations"]) == 1
    assert content["citations"][0]["source_id"] == SOURCE_ID


def test_generated_content_requires_at_least_one_real_evidence_citation():
    with pytest.raises(intelligence.CeoIntelligenceError, match="citations"):
        intelligence._generated_content("architecture", {
            "content": {"flows": [], "risks": [], "next_steps": []},
            "citations": [{"source_id": "invented", "claim": "Unsupported"}],
        }, {SOURCE_ID})


def test_worker_creates_preview_with_usage_and_evidence(monkeypatch):
    client = FakeSupabaseClient(rpc_rows={
        "ceo_claim_analysis_run": [{
            "out_run_id": RUN_ID,
            "out_project_key": "product",
            "out_feature_id": FEATURE_ID,
            "out_artifact_id": ARTIFACT_ID,
            "out_lens": "architecture",
            "out_base_revision_id": REVISION_ID,
            "out_reason": "Sync",
            "out_created_by": ADMIN_ID,
        }],
        "ceo_finish_analysis_run": [{
            "out_revision_id": REVISION_ID,
            "out_version": 2,
        }],
    })
    evidence = intelligence.Evidence(
        id=SOURCE_ID,
        source_type="backend_code",
        source_ref="github:wilplus/backend-cursor:services/example.py",
        title="services/example.py",
        content="def example(): pass",
        metadata={},
    )
    result = SimpleNamespace(
        parsed={
            "content": {"flows": [], "risks": [], "next_steps": []},
            "citations": [{"source_id": SOURCE_ID, "claim": "The source exists."}],
        },
        model="gpt-test",
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        duration_ms=250,
    )
    monkeypatch.setattr(intelligence, "collect_evidence", lambda _run: [evidence])
    import services.llm as llm
    monkeypatch.setattr(llm, "chat_complete", lambda **_kwargs: result)

    with swap_attr(intelligence.db, "client", client):
        assert intelligence.run_analysis(RUN_ID) is True

    payload = client.rpcs["ceo_finish_analysis_run"].payload
    assert payload["p_source_snapshot_ids"] == [SOURCE_ID]
    assert payload["p_total_tokens"] == 140
    assert payload["p_content"]["citations"][0]["source_id"] == SOURCE_ID


def test_review_conflict_never_promotes_stale_preview():
    client = FakeSupabaseClient(rpc_rows={"ceo_review_analysis_run": [{
        "out_run_id": RUN_ID,
        "out_status": "preview_ready",
        "out_revision_id": REVISION_ID,
        "out_conflict": True,
    }]})
    with swap_attr(intelligence.db, "client", client):
        with pytest.raises(intelligence.CeoIntelligenceConflict, match="changed"):
            intelligence.review_analysis(
                ADMIN_ID, RUN_ID, {"decision": "approve"}
            )


def test_bootstrap_exposes_preview_metadata_without_source_bodies():
    client = FakeSupabaseClient({
        "ceo_analysis_runs": [{
            "id": RUN_ID,
            "proposal_revision_id": REVISION_ID,
            "total_tokens": 140,
            "prompt_tokens": 100,
            "completion_tokens": 40,
        }],
        "ceo_artifact_revisions": [{
            "id": REVISION_ID,
            "status": "preview",
            "content": {"flows": []},
        }],
        "ceo_source_snapshots": [{
            "id": SOURCE_ID,
            "title": "Source",
            "content_hash": "0" * 64,
        }],
    })
    with swap_attr(intelligence.db, "client", client):
        payload = intelligence.bootstrap_data()

    assert payload["analysis_runs"][0]["proposal_revision"]["status"] == "preview"
    assert payload["intelligence_usage"]["total_tokens"] == 140
    assert "content" not in payload["source_snapshots"][0]


def test_migration_enforces_evidence_preview_and_admin_review_boundary():
    sql = (
        Path(__file__).parents[1]
        / "migrations"
        / "add_ceo_intelligence_sync.sql"
    ).read_text()
    for table in (
        "ceo_source_snapshots",
        "ceo_analysis_runs",
        "ceo_artifact_revision_sources",
    ):
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated" in sql
    assert "GRANT SELECT, INSERT ON TABLE public.ceo_source_snapshots" in sql
    assert "status = 'preview_ready'" in sql
    assert "p_decision NOT IN ('approve', 'reject')" in sql
    assert "WHERE revision.status = 'official'" in sql
    assert "AND status = 'official'" in sql
    assert "INTO v_next_version" in sql
    assert "DELETE FROM public.ceo_" not in sql


def test_comment_queues_matching_lens_after_atomic_comment(monkeypatch):
    rows = _pilot_rows()
    client = FakeSupabaseClient(rows, rpc_rows={
        "ceo_comment_and_request_reevaluation": [{
            "out_comment_id": "66666666-6666-4666-8666-666666666666",
            "out_request_id": "77777777-7777-4777-8777-777777777777",
        }],
    })
    queued: list[dict] = []
    monkeypatch.setattr(
        intelligence,
        "enqueue_for_artifact",
        lambda **kwargs: queued.append(kwargs) or {
            "analysis_run_id": RUN_ID,
            "created": True,
        },
    )
    monkeypatch.setattr(ceo, "get_bootstrap", lambda _admin: {"comments": []})

    with swap_attr(ceo.db, "client", client):
        result = ceo.comment_and_request_reevaluation(
            ADMIN_ID, ARTIFACT_ID, {"comment": "Re-evaluate the data boundary."}
        )

    assert result["analysis_run"]["analysis_run_id"] == RUN_ID
    assert queued[0]["trigger_type"] == "comment"
    assert queued[0]["artifact_id"] == ARTIFACT_ID
