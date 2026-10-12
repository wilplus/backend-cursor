from types import SimpleNamespace

from services import ceo_intelligence as intelligence
from tests.fakes import FakeSupabaseClient, swap_attr

ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FEATURE_ID = "22222222-2222-4222-8222-222222222222"
ARTIFACT_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "33333333-3333-4333-8333-333333333333"
SOURCE_ID = "44444444-4444-4444-8444-444444444444"
REVISION_ID = "55555555-5555-4555-8555-555555555555"


def _architecture_content(*, with_row: bool = False) -> dict:
    rows = []
    if with_row:
        rows = [{
            "id": "recording-flow",
            "cells": [
                {"column_id": "input", "value": "Recording"},
                {
                    "column_id": "measurement",
                    "value": "Qualitative voice evidence",
                },
                {"column_id": "output", "value": "Practice guidance"},
            ],
        }]
    return {
        "columns": [
            {"id": "input", "label": "Input"},
            {"id": "measurement", "label": "Measurement"},
            {"id": "output", "label": "Output"},
        ],
        "rows": rows,
        "risks": [],
        "next_steps": [],
    }


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
            "content": _architecture_content(),
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
