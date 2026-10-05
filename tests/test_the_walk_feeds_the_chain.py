"""The coach walk's blind label becomes the confidence chain's judgement.

Founder 2026-10-05, decisions log N48.5 Q27 A ("the coach walk's blind labels
as its judgements"). The walk's Judge screen asks for the chain's blind
packet when it paints a moment (POST /coach/snippets/<id>/mlc2-packet),
acknowledges the paint (the render route), and echoes both on the label PUT,
which writes the immutable blind_coach judgement and its reveal after the
legacy save. Pure unit tests with a recording client; the released lane
proves the wrappers in tests/test_mlc2_confidence_end_to_end_postgres.py.

What must hold: nothing about the moment leaves the server (four ids), a
coach who already rated or saw the non-blind side gets no packet and writes
no judgement (BLIND COACH, 35g-11), the walk is never refused over the
chain, and dark writes nothing.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

ASSIGNMENT = str(uuid.uuid4())
PRESENTATION = str(uuid.uuid4())
TOKEN = str(uuid.uuid4())
REVIEWER = str(uuid.uuid4())
COACH = str(uuid.uuid4())
TAKE = str(uuid.uuid4())
SNIPPET = str(uuid.uuid4())
SHA = "c" * 64
# The shape the packet RPC really returns (0304 through 0393): the hash is
# named visible_packet_sha256 and there is no visible_payload_sha256.
PACKET = {
    "review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
    "acknowledgement_token": TOKEN, "visible_packet_sha256": SHA,
    "visible_packet": {"clip": {"audio_sha256": "x"}}, "candidate_id": "c1",
    "replayed": False,
}


class _Client:
    def __init__(self, answers=None, raises=None):
        self.answers = dict(answers or {})
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        if self.raises:
            raise self.raises
        answer = self.answers.get(name)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=answer))


@pytest.fixture
def mode(monkeypatch):
    from config import Config

    def set_mode(value):
        monkeypatch.setattr(Config, "MLC2_CONFIDENCE_CUTOVER_MODE", value)
    return set_mode


@pytest.fixture
def walk(monkeypatch):
    """The packet route with every seam it reads stubbed: the snippet, this
    coach's ratings, this coach's exposure record and principal."""
    from routes.v2 import confidence_chain_coach as route
    from services import coach_exposure
    state = {"labels": [], "exposed": False, "snippet": {"id": SNIPPET, "session_id": TAKE},
             "client": _Client({"prepare_mlc2_confidence_coach_packet_v1": PACKET})}
    monkeypatch.setattr(route.db, "get_snippet_by_id",
                        lambda sid: state["snippet"], raising=False)
    monkeypatch.setattr(route.db, "get_confidence_labels_by_snippet_ids",
                        lambda ids: {SNIPPET: state["labels"]}, raising=False)
    monkeypatch.setattr(route.db, "get_owner_principal_for_user",
                        lambda user_id: {"id": REVIEWER}, raising=False)
    monkeypatch.setattr(coach_exposure, "is_exposed",
                        lambda database, coach_id, clip_id: state["exposed"])

    def invoke(snippet_id=SNIPPET):
        from flask import Flask, request
        monkeypatch.setattr(route.db, "client", state["client"], raising=False)
        with Flask(__name__).test_request_context(
                f"/v2/coach/snippets/{snippet_id}/mlc2-packet", method="POST"):
            request.user_id = COACH
            response, status = route.v2_coach_confidence_chain_packet.__wrapped__(snippet_id)
        return status, response.get_json()
    state["invoke"] = invoke
    return state


class TestTheWalkAsksForThePacket:
    def test_dark_answers_null_and_prepares_nothing(self, mode, walk):
        mode("dark")
        status, payload = walk["invoke"]()
        assert (status, payload) == (200, {"mlc2_blind_review": None})
        assert walk["client"].calls == []

    def test_a_painted_moment_gets_the_four_identifiers_and_nothing_else(self, mode, walk):
        mode("founder_canary")
        status, payload = walk["invoke"]()
        assert status == 200
        assert payload == {"mlc2_blind_review": {
            "review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
            "acknowledgement_token": TOKEN, "visible_payload_sha256": SHA,
        }}
        (name, params), = walk["client"].calls
        assert name == "prepare_mlc2_confidence_coach_packet_v1"
        assert params["p_take_id"] == TAKE and params["p_snippet_id"] == SNIPPET
        assert params["p_reviewer_principal_id"] == REVIEWER

    def test_a_moment_this_coach_already_rated_gets_no_packet(self, mode, walk):
        mode("founder_canary")
        walk["labels"] = [{"rater_id": COACH, "value": "yes"}]
        assert walk["invoke"]() == (200, {"mlc2_blind_review": None})
        assert walk["client"].calls == []

    def test_another_raters_answer_does_not_close_this_coachs_packet(self, mode, walk):
        mode("founder_canary")
        walk["labels"] = [{"rater_id": str(uuid.uuid4()), "value": "no"}]
        status, payload = walk["invoke"]()
        assert payload["mlc2_blind_review"]["review_assignment_id"] == ASSIGNMENT

    def test_a_coach_who_saw_the_non_blind_side_gets_no_packet(self, mode, walk):
        mode("founder_canary")
        walk["exposed"] = True
        assert walk["invoke"]() == (200, {"mlc2_blind_review": None})
        assert walk["client"].calls == []

    def test_a_moment_the_chain_did_not_select_answers_null(self, mode, walk):
        mode("founder_canary")
        walk["client"] = _Client({"prepare_mlc2_confidence_coach_packet_v1": None})
        assert walk["invoke"]() == (200, {"mlc2_blind_review": None})

    def test_an_unknown_snippet_answers_null(self, mode, walk):
        mode("founder_canary")
        walk["snippet"] = None
        assert walk["invoke"]() == (200, {"mlc2_blind_review": None})
        assert walk["client"].calls == []

    def test_a_failing_packet_never_refuses_the_walk(self, mode, walk):
        mode("founder_canary")
        walk["client"] = _Client(raises=RuntimeError("database down"))
        assert walk["invoke"]() == (200, {"mlc2_blind_review": None})

    def test_a_malformed_id_is_invalid_input(self, mode, walk):
        mode("founder_canary")
        status, payload = walk["invoke"]("not-a-uuid")
        assert status == 400 and payload["code"] == "INVALID_INPUT"


class TestOnlyABlindAnswerBecomesTheChainsJudgement:
    def _judge(self, monkeypatch, *, exposed, self_report=False):
        from routes.v2 import coach
        from services import coach_exposure, confidence_chain_consumer
        recorded = []
        monkeypatch.setattr(coach_exposure, "is_exposed",
                            lambda database, coach_id, clip_id: exposed)
        monkeypatch.setattr(confidence_chain_consumer, "record_coach_judgment",
                            lambda **kwargs: recorded.append(kwargs) or {"judgment_id": "j"})
        monkeypatch.setattr(coach, "_confidence_chain_reviewer_principal",
                            lambda coach_id: REVIEWER)
        result = coach._confidence_chain_judgment(
            {"review_assignment_id": ASSIGNMENT, "exposure_id": str(uuid.uuid4())},
            snippet_id=SNIPPET, rater_id=COACH, value="yes", self_report=self_report)
        return result, recorded

    def test_a_blind_answer_is_written(self, monkeypatch):
        result, recorded = self._judge(monkeypatch, exposed=False)
        assert result == {"judgment_id": "j"}
        assert recorded and recorded[0]["value"] == "yes"
        assert recorded[0]["reviewer_principal_id"] == REVIEWER

    def test_an_answer_after_the_non_blind_side_is_never_a_blind_judgement(self, monkeypatch):
        result, recorded = self._judge(monkeypatch, exposed=True)
        assert result is None and recorded == []

    def test_a_self_report_is_never_a_judgement(self, monkeypatch):
        result, recorded = self._judge(monkeypatch, exposed=False, self_report=True)
        assert result is None and recorded == []


def test_the_packet_route_is_on_the_coach_blueprint_and_coach_only():
    import inspect
    from routes.v2 import confidence_chain_coach as route
    from services import confidence_chain_walk as walk
    assert "@require_admin_or_coach" in inspect.getsource(route)
    for source in (inspect.getsource(route.v2_coach_confidence_chain_packet),
                   inspect.getsource(walk.walk_packet),
                   inspect.getsource(walk.already_rated)):
        for leak in ("transcript", "machine", "predict", "voice_confidence", "score"):
            assert leak not in source


def test_the_route_validates_and_calls_one_service():
    """The route fence (one service call, no direct database call): the
    decisions live in services/confidence_chain_walk.py."""
    import inspect
    from routes.v2 import confidence_chain_coach as route
    source = inspect.getsource(route.v2_coach_confidence_chain_packet)
    assert "walk_packet(db," in source and "db." not in source


def test_an_unreadable_rating_reads_as_rated(monkeypatch):
    from services import confidence_chain_walk as walk

    class _Broken:
        def get_confidence_labels_by_snippet_ids(self, ids):
            raise RuntimeError("labels down")
    assert walk.already_rated(_Broken(), COACH, SNIPPET) is True


def test_the_handle_is_built_from_the_packet_the_rpc_really_returns():
    """Before 2026-10-05 the consumer asked for visible_payload_sha256, a
    key the RPC never returns, so no row ever carried a handle and no coach
    answer ever reached the chain."""
    from services import confidence_chain_consumer as consumer
    assert "visible_payload_sha256" not in PACKET
    assert consumer.coach_packet_handle(PACKET) == {
        "review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
        "acknowledgement_token": TOKEN, "visible_payload_sha256": SHA,
    }
