"""Q2: the legacy coach card consumes the confidence chain, only while it writes.

Pure unit tests with a recording client. The released rehearsal lane proves
the three 0393 wrappers against PostgreSQL in
tests/test_mlc2_confidence_end_to_end_postgres.py.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import confidence_chain_consumer as consumer


ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = str(uuid.uuid4())
PRESENTATION = str(uuid.uuid4())
TOKEN = str(uuid.uuid4())
REVIEWER = str(uuid.uuid4())
TAKE = str(uuid.uuid4())
SNIPPET = str(uuid.uuid4())
EXPOSURE = str(uuid.uuid4())
SHA = "c" * 64
PACKET = {
    "review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
    "acknowledgement_token": TOKEN, "visible_packet_sha256": SHA,
    "visible_payload_sha256": SHA,
    "visible_packet": {"clip": {"audio_sha256": "x"}}, "candidate_id": "c1",
    "replayed": False,
}


class _Client:
    def __init__(self, answers):
        self.answers = dict(answers)
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        answer = self.answers.get(name)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=answer))


@pytest.fixture
def mode(monkeypatch):
    from config import Config

    def set_mode(value):
        monkeypatch.setattr(Config, "MLC2_CONFIDENCE_CUTOVER_MODE", value)
    return set_mode


class TestTheConsumerFollowsTheWriterState:
    def test_dark_is_off(self, mode):
        mode("dark")
        assert consumer.consumer_enabled() is False

    def test_founder_canary_is_on(self, mode):
        mode("founder_canary")
        assert consumer.consumer_enabled() is True

    def test_killed_and_nonsense_are_off(self, mode):
        for value in ("killed", "", "open"):
            mode(value)
            assert consumer.consumer_enabled() is False

    def test_the_constant_is_still_dark(self):
        from config import Config
        assert Config.MLC2_CONFIDENCE_CUTOVER_MODE == "dark"


class TestTheHandle:
    def test_carries_the_four_identifiers_and_nothing_of_the_packet(self):
        handle = consumer.coach_packet_handle(PACKET)
        assert handle == {
            "review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
            "acknowledgement_token": TOKEN, "visible_payload_sha256": SHA,
        }
        assert "visible_packet" not in handle and "candidate_id" not in handle


class TestAttachingThePacketToAQueueRow:
    def test_dark_leaves_the_row_untouched_and_calls_nothing(self, mode):
        mode("dark")
        client = _Client({"prepare_mlc2_confidence_coach_packet_v1": PACKET})
        row = consumer.attach_coach_packet(
            {"snippet_id": SNIPPET, "label": None},
            store=consumer.ConfidenceChainConsumerStore(client),
            take_id=TAKE, snippet_id=SNIPPET, reviewer_principal_id=REVIEWER,
        )
        assert consumer.HANDLE_KEY not in row and client.calls == []

    def test_founder_canary_attaches_the_handle_for_an_unlabelled_row(self, mode):
        mode("founder_canary")
        client = _Client({"prepare_mlc2_confidence_coach_packet_v1": PACKET})
        row = consumer.attach_coach_packet(
            {"snippet_id": SNIPPET, "label": None},
            store=consumer.ConfidenceChainConsumerStore(client),
            take_id=TAKE, snippet_id=SNIPPET, reviewer_principal_id=REVIEWER,
        )
        assert row[consumer.HANDLE_KEY]["review_assignment_id"] == ASSIGNMENT
        name, params = client.calls[0]
        assert name == "prepare_mlc2_confidence_coach_packet_v1"
        assert params == {
            "p_take_id": TAKE, "p_snippet_id": SNIPPET,
            "p_reviewer_principal_id": REVIEWER, "p_delivery_mode": "canary",
        }

    def test_an_answered_row_is_history_not_a_new_exposure(self, mode):
        mode("founder_canary")
        client = _Client({"prepare_mlc2_confidence_coach_packet_v1": PACKET})
        row = consumer.attach_coach_packet(
            {"snippet_id": SNIPPET, "label": {"value": "yes"}},
            store=consumer.ConfidenceChainConsumerStore(client),
            take_id=TAKE, snippet_id=SNIPPET, reviewer_principal_id=REVIEWER,
        )
        assert consumer.HANDLE_KEY not in row and client.calls == []

    def test_no_candidate_means_no_handle(self, mode):
        mode("founder_canary")
        client = _Client({"prepare_mlc2_confidence_coach_packet_v1": None})
        row = consumer.attach_coach_packet(
            {"snippet_id": SNIPPET, "label": None},
            store=consumer.ConfidenceChainConsumerStore(client),
            take_id=TAKE, snippet_id=SNIPPET, reviewer_principal_id=REVIEWER,
        )
        assert consumer.HANDLE_KEY not in row

    def test_no_reviewer_principal_means_no_call(self, mode):
        mode("founder_canary")
        client = _Client({"prepare_mlc2_confidence_coach_packet_v1": PACKET})
        consumer.attach_coach_packet(
            {"snippet_id": SNIPPET, "label": None},
            store=consumer.ConfidenceChainConsumerStore(client),
            take_id=TAKE, snippet_id=SNIPPET, reviewer_principal_id=None,
        )
        assert client.calls == []

    def test_a_failing_packet_never_breaks_the_queue(self, mode):
        mode("founder_canary")

        class _Broken:
            def rpc(self, name, params):
                raise RuntimeError("boom")

        row = consumer.attach_coach_packet(
            {"snippet_id": SNIPPET, "label": None},
            store=consumer.ConfidenceChainConsumerStore(_Broken()),
            take_id=TAKE, snippet_id=SNIPPET, reviewer_principal_id=REVIEWER,
        )
        assert row == {"snippet_id": SNIPPET, "label": None}


class TestTheRenderReceipt:
    def test_passes_the_identity_through_to_the_wrapper(self):
        client = _Client({"ack_mlc2_confidence_coach_render_v1": {"id": EXPOSURE}})
        row = consumer.ConfidenceChainConsumerStore(client).ack_render(
            review_assignment_id=ASSIGNMENT, presentation_id=PRESENTATION,
            acknowledgement_token=TOKEN, reviewer_principal_id=REVIEWER,
            render_instance_id=EXPOSURE, client_rendered_at="2026-09-29T10:00:00Z",
            visible_payload_sha256=SHA, idempotency_key="k1",
        )
        assert row == {"id": EXPOSURE}
        name, params = client.calls[0]
        assert name == "ack_mlc2_confidence_coach_render_v1"
        assert params["p_client_version"] == "coach-card-blind-v1"
        assert params["p_visible_payload_sha256"] == SHA

    def test_a_non_uuid_is_refused_before_any_call(self):
        client = _Client({})
        with pytest.raises(consumer.ConfidenceChainConsumerError):
            consumer.ConfidenceChainConsumerStore(client).ack_render(
                review_assignment_id="nope", presentation_id=PRESENTATION,
                acknowledgement_token=TOKEN, reviewer_principal_id=REVIEWER,
                render_instance_id=EXPOSURE, client_rendered_at="t",
                visible_payload_sha256=SHA, idempotency_key="k1",
            )
        assert client.calls == []


class TestTheJudgment:
    @pytest.mark.parametrize("value,decision", sorted(consumer.DECISION_OF.items()))
    def test_each_of_the_five_answers_maps_to_its_own_decision(self, mode, value, decision):
        mode("founder_canary")
        client = _Client({"submit_mlc2_confidence_coach_judgment_v1": {
            "judgment_id": "j1", "review_assignment_id": ASSIGNMENT,
            "revealed": True, "replayed": False,
        }})
        result = consumer.record_coach_judgment(
            store=consumer.ConfidenceChainConsumerStore(client),
            handle={"review_assignment_id": ASSIGNMENT, "exposure_id": EXPOSURE},
            reviewer_principal_id=REVIEWER, value=value, idempotency_key="k2",
        )
        assert result == {"judgment_id": "j1", "review_assignment_id": ASSIGNMENT,
                          "revealed": True, "replayed": False}
        name, params = client.calls[0]
        assert name == "submit_mlc2_confidence_coach_judgment_v1"
        assert params["p_decision"] == decision
        assert params["p_exposure_id"] == EXPOSURE

    def test_the_legacy_pair_cannot_become_a_decision(self, mode):
        mode("founder_canary")
        client = _Client({})
        for legacy in ("neutral", "unrateable"):
            with pytest.raises(consumer.ConfidenceChainConsumerError):
                consumer.record_coach_judgment(
                    store=consumer.ConfidenceChainConsumerStore(client),
                    handle={"review_assignment_id": ASSIGNMENT, "exposure_id": EXPOSURE},
                    reviewer_principal_id=REVIEWER, value=legacy, idempotency_key="k3",
                )
        assert client.calls == []

    def test_dark_writes_nothing_even_with_a_handle(self, mode):
        mode("dark")
        client = _Client({})
        assert consumer.record_coach_judgment(
            store=consumer.ConfidenceChainConsumerStore(client),
            handle={"review_assignment_id": ASSIGNMENT, "exposure_id": EXPOSURE},
            reviewer_principal_id=REVIEWER, value="yes", idempotency_key="k4",
        ) is None
        assert client.calls == []

    def test_a_handle_without_an_exposure_is_refused(self, mode):
        mode("founder_canary")
        client = _Client({})
        with pytest.raises(consumer.ConfidenceChainConsumerError):
            consumer.record_coach_judgment(
                store=consumer.ConfidenceChainConsumerStore(client),
                handle={"review_assignment_id": ASSIGNMENT},
                reviewer_principal_id=REVIEWER, value="yes", idempotency_key="k5",
            )
        assert client.calls == []


class TestTheRenderRoute:
    def _invoke(self, monkeypatch, body, answers, headers=None):
        from flask import Flask, request
        from routes.v2 import confidence_chain_coach as route
        client = _Client(answers)
        monkeypatch.setattr(route.db, "client", client, raising=False)
        monkeypatch.setattr(
            route.db, "get_owner_principal_for_user",
            lambda user_id: {"id": REVIEWER}, raising=False)
        with Flask(__name__).test_request_context(
            f"/v2/coach/mlc2/assignments/{ASSIGNMENT}/render", method="POST",
            json=body, headers={"Idempotency-Key": "render-1"} if headers is None else headers,
        ):
            request.user_id = str(uuid.uuid4())
            response, status = route.v2_coach_confidence_chain_render.__wrapped__(ASSIGNMENT)
        return status, response.get_json(), client

    def test_dark_answers_404_and_calls_nothing(self, mode, monkeypatch):
        mode("dark")
        status, payload, client = self._invoke(monkeypatch, {}, {})
        assert status == 404 and payload["code"] == "NOT_FOUND" and client.calls == []

    def test_a_painted_card_gets_its_exposure_id(self, mode, monkeypatch):
        mode("founder_canary")
        status, payload, client = self._invoke(monkeypatch, {
            "presentation_id": PRESENTATION, "acknowledgement_token": TOKEN,
            "render_instance_id": EXPOSURE, "client_rendered_at": "2026-09-29T10:00:00Z",
            "visible_payload_sha256": SHA,
        }, {"ack_mlc2_confidence_coach_render_v1": {"id": EXPOSURE}})
        assert status == 201 and payload == {"exposure_id": EXPOSURE}
        assert client.calls[0][1]["p_reviewer_principal_id"] == REVIEWER
        assert client.calls[0][1]["p_idempotency_key"] == "render-1"

    def test_a_missing_idempotency_key_is_invalid_input(self, mode, monkeypatch):
        mode("founder_canary")
        status, payload, client = self._invoke(monkeypatch, {
            "presentation_id": PRESENTATION, "acknowledgement_token": TOKEN,
            "render_instance_id": EXPOSURE, "client_rendered_at": "t",
            "visible_payload_sha256": SHA,
        }, {}, headers={})
        assert status == 400 and payload["code"] == "INVALID_INPUT" and client.calls == []

    def test_a_refused_receipt_is_409_never_faked(self, mode, monkeypatch):
        mode("founder_canary")
        status, payload, _client = self._invoke(monkeypatch, {
            "presentation_id": PRESENTATION, "acknowledgement_token": TOKEN,
            "render_instance_id": EXPOSURE, "client_rendered_at": "t",
            "visible_payload_sha256": SHA,
        }, {"ack_mlc2_confidence_coach_render_v1": None})
        assert status == 409 and payload["code"] == "CONFIDENCE_CHAIN_RENDER_NOT_RECORDED"


class TestTheWiringInTheCoachRoutes:
    """Source pins on routes/v2/coach.py: the seam, and its order."""

    def test_the_queue_attaches_the_handle_only_through_the_consumer(self):
        source = (ROOT / "routes" / "v2" / "coach.py").read_text()
        assert "attach_coach_packet(" in source
        assert "_confidence_chain_reviewer_principal(" in source
        assert "mlc2_confidence" not in source

    def test_the_label_route_writes_the_judgment_after_the_legacy_save_and_never_on_a_self_report(self):
        source = (ROOT / "routes" / "v2" / "coach.py").read_text()
        save = source.index("saved = db.upsert_state_rating(")
        judgment = source.index("canonical_judgment = _confidence_chain_judgment(")
        reconcile = source.index("reconcile_confidence_review(\n")
        assert save < judgment < reconcile
        assert "if mlc2_handle is None or self_report:" in source
        assert "mlc2_handle = _pop_confidence_chain_handle(body)" in source
        assert '"mlc2": canonical_judgment' in source

    def test_the_route_module_is_registered(self):
        source = (ROOT / "routes" / "v2" / "__init__.py").read_text()
        assert '"confidence_chain_coach"' in source
