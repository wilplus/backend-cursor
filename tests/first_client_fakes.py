from hashlib import sha256

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
            # THIS FIXTURE'S IDEAL TEXT IS ITS TRANSCRIPT, which is why the
            # served span equals the document span here and why nothing in
            # this file could ever have caught the coordinate defect of
            # 2026-09-19: V3 filled `span` (an Ideal Text offset, drawn on by
            # the client) from the transcript, and with one document that is
            # invisible. Fine for what these tests are about -- the 75-word
            # budget, the membership freeze, the enrollment fallbacks -- but
            # the two-document shape lives in
            # `test_v3_end_to_end_production_shape.py` and belongs there.
            "served_start": 0,
            "served_end": len(text),
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
        "recording_id": RECORDING,
        "take_index": 1,
    }
    return session, document, snippets


class _Database:
    def __init__(self):
        self.bundle = None
        self.membership_payload = None
        self.client = self
        self.calls: list[str] = []
        self.enrollment_payloads: list[dict] = []
        self.context_calls: list[dict] = []

    def rpc(self, name, payload):
        self.calls.append(name)
        assert name == "read_feedback_v3_candidate_source_snapshot_v1"
        assert payload == {
            "p_acquisition_principal_id": OWNER,
            "p_project_id": PROJECT,
            "p_take_id": TAKE,
        }
        _, document, _ = _source()
        self._rpc_data = {
            "snapshot_contract_version": (
                "feedback-v3-candidate-source-snapshot-v1"
            ),
            "document_snapshot_id": SNAPSHOT,
            "source_generation": 1,
            "surface": document["text"],
            "surface_sha256": sha256(document["text"].encode()).hexdigest(),
        }
        return self

    def execute(self):
        class Result:
            data = self._rpc_data
        return Result()

    def ensure_service_enrollment(self, **payload):
        self.calls.append("ensure_service_enrollment")
        self.enrollment_payloads.append(payload)
        return {
            "id": "c0000000-0000-4000-8000-000000000001",
            "rollout_revision_id": "d0000000-0000-4000-8000-000000000001",
            "operation_mode": "general_service",
        }

    def record_feedback_v3_service_candidate_set(self, bundle):
        self.calls.append("record_feedback_v3_service_candidate_set")
        self.bundle = bundle
        return {"candidate_set_id": bundle["candidate_set_id"]}

    def get_current_ideal_text_document_snapshot(self, _project_id):
        return {"id": SNAPSHOT, "source_take_session_id": TAKE}

    def freeze_feedback_v3_service_membership(self, payload):
        self.calls.append("freeze_feedback_v3_service_membership")
        self.membership_payload = payload
        return {
            "id": MEMBERSHIP,
            "content_identity_sha256": "c" * 64,
        }

    def prepare_feedback_v3_service_context(self, payload):
        # Retired from serving (L8, contract 66). Still answered here, the
        # way it would answer if an N1 snapshot existed, so a reintroduced
        # call is counted AND would put the block back on the row.
        self.context_calls.append(payload)
        return {
            "n1_candidate_set_id": N1_SET,
            "authorization_check_id": AUTH,
            "source_acquisition_receipt_id": RECEIPT,
        }


# ── no silent fallback (founder 2026-09-18, contract 24h) ──
