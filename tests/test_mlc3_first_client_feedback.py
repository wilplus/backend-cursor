from hashlib import sha256

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
            # THIS FIXTURE'S IDEAL TEXT IS ITS TRANSCRIPT, which is why the
            # served span equals the document span here and why nothing in
            # this file could ever have caught the coordinate defect of
            # 2026-09-19: V3 filled `span` (an Ideal Text offset, drawn on by
            # the client) from the transcript, and with one document that is
            # invisible. Fine for what these tests are about -- the 75-word
            # budget, the service identity, the enrollment fallbacks -- but
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
        frame=frame, take_document=document, served_text=document["text"],
        feedback_candidates=[],
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
        self.client = self

    def rpc(self, name, payload):
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


class _NoEnrollmentDatabase(_Database):
    """A principal the exercise enrollment will not serve.

    On 2026-09-17 this was EVERY principal alive: enrollment resolves a
    receipt carrying `personalized_exercise_recommendation`, that purpose was
    registered `phase2`, and `accept_phase1_processing_authorization_v1`
    refuses any policy listing one — so the purpose could never be recorded
    and the receipt could never exist.

    That deadlock is gone (0335 reclassified the purpose on 2026-09-16; the
    active policy has carried it since 09-20), and this fixture is not. A
    principal can still be unenrolled for half a dozen ordinary reasons — no
    receipt yet, a service block, a pending purge, an inactive rollout,
    cohort membership — and V3 must survive all of them the same way. What is
    under test is the stand-down, never the reason for it.
    """

    def __init__(self):
        super().__init__()
        self.context_calls = 0

    def ensure_service_enrollment(self, **_payload):
        return None

    def prepare_feedback_v3_service_context(self, payload):
        self.context_calls += 1
        return super().prepare_feedback_v3_service_context(payload)


def test_feedback_survives_an_unavailable_exercise_enrollment(monkeypatch):
    """FOUNDER 2026-09-17, option A: V3 must not need the exercise purpose.

    This gate used to return None, putting the whole of V3 — Manager
    arbitration, the block partition, every Confident Voice item — behind an
    authorization that, at the time, no user could obtain. Feedback now
    surfaces; only the exercise context stands down.

    The ruling outlives the deadlock that provoked it. Enrollment is
    satisfiable today, and it must STILL not be able to empty the Feedback
    surface: F1 does not wait on the learning layer (R12), and a governance
    switch is exactly the kind of thing that flips back.
    """
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()
    database = _NoEnrollmentDatabase()
    rows = prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )
    assert rows is not None and len(rows) == 1
    assert rows[0]["feedback_family"] == "confident_voice"


def test_the_phase2_exercise_path_is_not_called_without_enrollment(monkeypatch):
    """The boundary still holds in the other direction: standing down from
    Phase-2 exercise data is the POINT, not a side effect to be re-added."""
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()
    database = _NoEnrollmentDatabase()
    rows = prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )
    assert database.context_calls == 0
    assert "mlc3_service" not in (rows or [{}])[0]


def test_the_membership_freeze_still_happens_without_enrollment(monkeypatch):
    """The freeze is what makes a served candidate provable (L2). It is
    authorized in PostgreSQL by contract + allowlist, NOT by enrollment, so
    dropping the enrollment gate must not have dropped the freeze with it."""
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()
    database = _NoEnrollmentDatabase()
    rows = prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )
    assert database.membership_payload is not None
    assert database.membership_payload["p_items"][0]["candidate_id"] == (
        (rows or [{}])[0]["candidate_id"]
    )
    assert (rows or [{}])[0]["feedback_membership_id"] == MEMBERSHIP


def test_the_unreachable_gate_does_not_come_back():
    """A grep, deliberately. The gate read as an ordinary fail-closed check
    and would be re-added by anyone tidying the twelve exits back to a
    matching set — its absence is the fix, so the absence is the test."""
    from pathlib import Path

    source = Path("services/mlc3_first_client_feedback.py").read_text()
    # The CALL, not the word — the docstring names the retired reason on
    # purpose, so that the next reader knows why the set is eleven.
    assert '_decline(take_id, "service_enrollment_missing")' not in source


def test_an_empty_inventory_declines_instead_of_serving_zero_rows(monkeypatch):
    """FOUNDER 2026-09-18: "it was loading long and then showed no bookmarks on
    the text ZERO".

    `visible` is built by appending over inventory["visible_rows"]. An empty
    inventory appended nothing and the function returned `[]` — which is not
    None, so `ideal_text_changes` took it for a complete V3 result, replaced
    the working V2 feedback with it and cleared the styles. The user waited
    through every RPC this function makes and got nothing: strictly worse than
    before V3 was activated, which is a live-loop regression.

    `[]` and None must not be the same answer. The empty case declines, the
    legacy response survives, and the log names the reason.
    """
    from config import Config
    import services.mlc3_first_client_feedback as module

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()

    real_inventory = module.prepare_v3_service_inventory

    def _empty(**kwargs):
        inventory = real_inventory(**kwargs)
        if inventory is None:
            return None
        drained = dict(inventory)
        drained["visible_rows"] = []
        return drained

    monkeypatch.setattr(module, "prepare_v3_service_inventory", _empty)

    rows = prepare_first_client_feedback(
        database=_Database(),
        session=session,
        take_document=document,
        served_text=document["text"],
        snippets=snippets,
        suggestions={},
        feedback_candidates=[],
        owner_user_id=USER,
    )

    # UPDATED 2026-09-18 (contract 24h). This asserted `rows is None` — stand
    # down to the legacy response — which was right for one day and is now
    # wrong: an empty inventory is V3 failing on a Take it owns, so it fails
    # VISIBLY. What has not changed is the thing that mattered: zero cards are
    # never served as though they were an answer.
    from services.mlc3_first_client_feedback import V3Unavailable

    assert isinstance(rows, V3Unavailable), (
        f"an empty inventory is a fault, not an answer; got {rows!r}"
    )
    assert rows.reason == "inventory_returned_no_visible_rows"


def test_the_caller_treats_an_empty_service_result_as_no_result():
    """The second line of defence, asserted on the source.

    `if _service_rows is not None` accepted `[]`. Nothing at that call site can
    tell an empty V3 answer from a deliberate one, and the cost of guessing
    wrong is the user seeing no feedback at all — so it tests truthiness.
    """
    from pathlib import Path

    source = Path("services/ideal_text_changes.py").read_text(encoding="utf-8")
    assert "if _service_rows:" in source
    assert "if _service_rows is not None:" not in source


# ── no silent fallback (founder 2026-09-18, contract 24h) ──

def test_a_take_outside_the_service_returns_none_not_a_failure(monkeypatch):
    """The distinction the whole rule rests on. A user V3 does not apply to
    has NOT hit a fault, and the legacy answer is correct for them."""
    from config import Config
    from services.mlc3_first_client_feedback import V3Unavailable

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", False)
    session, document, snippets = _source()
    out = prepare_first_client_feedback(
        database=_Database(), session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )
    assert out is None
    assert not isinstance(out, V3Unavailable)


def test_a_take_inside_the_service_that_breaks_returns_a_typed_failure(monkeypatch):
    """Previously indistinguishable from the case above — both were None, so
    a broken V3 and a working one looked identical from the outside."""
    from config import Config
    import services.mlc3_first_client_feedback as module
    from services.mlc3_first_client_feedback import V3Unavailable

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    monkeypatch.setattr(module, "prepare_v3_service_inventory",
                        lambda **kwargs: None)
    session, document, snippets = _source()
    out = prepare_first_client_feedback(
        database=_Database(), session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )
    assert isinstance(out, V3Unavailable)
    assert out.reason == "service_inventory_unavailable"


def test_the_failure_carries_a_reason_a_person_can_act_on():
    """A reason code, not copy. The client renders its own notice and its own
    retry; nothing here asserts anything about the speaker (AC-9)."""
    from services.mlc3_first_client_feedback import V3Unavailable

    failure = V3Unavailable("membership_freeze_failed")
    assert failure.reason == "membership_freeze_failed"
    assert failure == ("membership_freeze_failed",)


class _SnapshotRpcRaises(_Database):
    """PostgreSQL refuses the snapshot read, exactly as production did.

    `read_feedback_v3_candidate_source_snapshot_v1` calls
    `require_mlc3_service_access_v2`, which is the guard that answered
    MLC3_ROLLOUT_NOT_ACTIVE on 2026-09-18 and took every bookmark off the
    document with it."""

    def rpc(self, _name, _payload):
        raise RuntimeError(
            "{'code': 'P0001', 'message': 'MLC3_ROLLOUT_NOT_ACTIVE'}"
        )


def test_a_refused_snapshot_read_names_the_guard_that_refused_it(
    monkeypatch, caplog,
):
    """THE LOG LINE THAT COST A PRODUCTION DAY (2026-09-18).

    `source_snapshot_rpc_failed` narrowed the fault to one call and then the
    bare `except Exception` discarded which of its four guards raised —
    rollout, enrollment, cohort, or an invalid snapshot. Four states, four
    different fixes, one log line that could not tell them apart."""
    import logging

    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()
    with caplog.at_level(logging.INFO,
                         logger="services.mlc3_first_client_feedback"):
        out = prepare_first_client_feedback(
            database=_SnapshotRpcRaises(), session=session,
            take_document=document, served_text=document["text"],
            snippets=snippets, suggestions={}, feedback_candidates=[],
            owner_user_id=USER,
        )
    assert out.reason == "source_snapshot_rpc_failed"
    assert "MLC3_ROLLOUT_NOT_ACTIVE" in caplog.text


def test_the_database_error_stays_in_the_log_and_out_of_the_payload():
    """A reason code is what the client is handed; a PostgreSQL error string
    is a server diagnostic. `V3Unavailable` has one field on purpose, so the
    detail cannot ride out to a user surface even by accident."""
    from services.mlc3_first_client_feedback import V3Unavailable, _decline

    failure = _decline(TAKE, "source_snapshot_rpc_failed", "P0001 ...")
    assert isinstance(failure, V3Unavailable)
    assert failure == ("source_snapshot_rpc_failed",)
    assert len(failure) == 1


def test_the_caller_surfaces_the_failure_rather_than_serving_v2():
    """Asserted on the source: a silent policy swap is the thing 24h forbids,
    and nothing at runtime can tell you it happened."""
    from pathlib import Path

    source = Path("services/ideal_text_changes.py").read_text(encoding="utf-8")
    assert "isinstance(_service_rows, V3Unavailable)" in source
    assert "self.v3_failure = _service_rows.reason" in source
    assert '"feedback_status"' in source
