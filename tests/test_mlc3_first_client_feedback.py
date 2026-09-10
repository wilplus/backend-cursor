from services.feedback_data_contract import build_feedback_exposure_bundle
from services.mlc3_first_client_feedback import prepare_first_client_feedback
from services.take_feedback_policy_v3 import build_service_candidate_frame
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory

OWNER = "10000000-0000-4000-8000-000000000001"
USER = "10000000-0000-4000-8000-000000000002"
PROJECT = "20000000-0000-4000-8000-000000000001"
TAKE = "30000000-0000-4000-8000-000000000001"
RECORDING = "40000000-0000-4000-8000-000000000001"
SNIPPET = "50000000-0000-4000-8000-000000000001"
PART = "60000000-0000-4000-8000-000000000001"
SNAPSHOT = "70000000-0000-4000-8000-000000000001"
MEMBERSHIP = "80000000-0000-4000-8000-000000000001"
N1_SET = "90000000-0000-4000-8000-000000000001"
AUTH = "a0000000-0000-4000-8000-000000000001"
RECEIPT = "b0000000-0000-4000-8000-000000000001"


def _source():
    text = " ".join(f"word{index}" for index in range(75))
    document = {
        "take_session_id": TAKE,
        "text": text,
        "paragraphs": [{
            "part_id": PART,
            "start": 0,
            "end": len(text),
            "slide_index": 0,
        }],
        "pieces": [{
            "snippet_id": SNIPPET,
            "part_id": PART,
            "take_session_id": TAKE,
            "recording_id": RECORDING,
            "audio_ref": "https://audio.invalid/source.webm",
            "text": text,
            "start": 0,
            "end": len(text),
            "start_offset_ms": 120,
            "duration_ms": 5100,
            "slide_index": 0,
        }],
    }
    snippets = [{
        "id": SNIPPET,
        "session_id": TAKE,
        "recording_id": RECORDING,
        "start_offset_ms": 120,
        "duration_ms": 5100,
        "metrics": {"voice_confidence": {
            "version": "voice-confidence-universal-v3",
            "score": 0.63,
        }},
    }]
    session = {
        "id": TAKE,
        "user_id": USER,
        "owner_principal_id": OWNER,
        "project_id": PROJECT,
        "recording_1_id": RECORDING,
        "take_index": 1,
    }
    return session, document, snippets


def test_service_frame_and_bundle_preserve_75_word_budget_without_labels():
    session, document, snippets = _source()
    frame = build_service_candidate_frame(
        take_document=document,
        snippets=snippets,
        suggestions={},
        feedback_candidates=[],
        take_index=1,
        expected_recording_id=RECORDING,
    )
    inventory = prepare_v3_service_inventory(
        frame=frame, take_document=document, feedback_candidates=[]
    )
    assert inventory is not None
    assert len(inventory["selected_keys"]) == 1
    assert inventory["selected_keys"][0]["feedback_family"] == "confident_voice"
    bundle = build_feedback_exposure_bundle(
        session=session,
        transcript_document=document,
        served_text=document["text"],
        candidates=inventory["candidates"],
        selected_keys=inventory["selected_keys"],
        manager_rules_version="take-feedback-policy-v3-serving-v1",
        commit="test",
    )
    assert bundle is not None
    assert all(not row["training_eligible"] for row in bundle["candidates"])


class _Database:
    def __init__(self):
        self.bundle = None
        self.membership_payload = None

    def ensure_service_enrollment(self, **_payload):
        return {
            "id": "c0000000-0000-4000-8000-000000000001",
            "rollout_revision_id": "d0000000-0000-4000-8000-000000000001",
            "operation_mode": "general_service",
        }

    def record_feedback_v3_service_candidate_set(self, bundle):
        self.bundle = bundle
        return {"candidate_set_id": bundle["candidate_set_id"]}

    def get_current_ideal_text_document_snapshot(self, _project_id):
        return {"id": SNAPSHOT, "source_take_session_id": TAKE}

    def freeze_feedback_v3_service_membership(self, payload):
        self.membership_payload = payload
        return {
            "id": MEMBERSHIP,
            "content_identity_sha256": "c" * 64,
        }

    def prepare_feedback_v3_service_context(self, _payload):
        return {
            "n1_candidate_set_id": N1_SET,
            "authorization_check_id": AUTH,
            "source_acquisition_receipt_id": RECEIPT,
        }


def test_first_client_rows_receive_exact_service_identity(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()
    database = _Database()
    rows = prepare_first_client_feedback(
        database=database,
        session=session,
        take_document=document,
        served_text=document["text"],
        snippets=snippets,
        suggestions={},
        feedback_candidates=[],
        owner_user_id=USER,
    )
    assert rows is not None and len(rows) == 1
    identity = rows[0]["mlc3_service"]
    assert identity["membership_id"] == MEMBERSHIP
    assert identity["n1_candidate_set_id"] == N1_SET
    assert identity["authorization_check_id"] == AUTH
    assert identity["source_acquisition_receipt_id"] == RECEIPT
    assert database.membership_payload["p_items"][0]["candidate_id"] == (
        rows[0]["candidate_id"]
    )


def test_closed_backend_gate_returns_legacy_fallback(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", False)
    session, document, snippets = _source()
    assert prepare_first_client_feedback(
        database=_Database(), session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    ) is None
