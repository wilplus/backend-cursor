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


    def test_a_coach_who_saw_the_non_blind_side_gets_no_packet(self, mode, walk):
        mode("founder_canary")
        walk["exposed"] = True
        assert walk["invoke"]() == (200, {"mlc2_blind_review": None})
        assert walk["client"].calls == []


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


    def test_an_answer_after_the_non_blind_side_is_never_a_blind_judgement(self, monkeypatch):
        result, recorded = self._judge(monkeypatch, exposed=True)
        assert result is None and recorded == []
