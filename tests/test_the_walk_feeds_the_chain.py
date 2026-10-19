"""
STORY    As a coach, I want only my blind answers to become the confidence
         chain's training judgements, so that an answer given after I saw the
         machine's side never counts as blind.
OUTCOME
  O1  NEVER-2: a coach who has seen the moment's non-blind side gets no
      packet, and their answer writes no blind judgement (the rating itself
      is still saved).
  O2  A blind coach gets the packet as four identifiers only (nothing about
      the moment leaves the server), and their answer becomes the chain's
      judgement.
  O3  A coach who already rated the moment gets no packet.
  O4  The walk is never refused because of the chain: a failing chain still
      answers 200 with no packet, and the rating is still saved.
  O5  Dark mode writes nothing to the chain.
PROVES   O1 -> test_a_coach_who_saw_the_non_blind_side_gets_no_packet
         O1 -> test_an_answer_after_the_non_blind_side_is_never_a_blind_judgement
         O2 -> test_a_blind_coach_gets_four_ids_and_nothing_about_the_moment
         O2 -> test_a_blind_answer_becomes_the_chains_judgement
         O3 -> test_a_coach_who_already_rated_gets_no_packet
         O4 -> test_a_failing_chain_never_refuses_the_walk
         O5 -> test_dark_writes_nothing
WHY      Founder 2026-10-05, N48.5 Q27 A; BLIND COACH, 35g-11.
"""
from __future__ import annotations

import inspect
import json
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask, request

ASSIGNMENT = str(uuid.uuid4())
PRESENTATION = str(uuid.uuid4())
TOKEN = str(uuid.uuid4())
EXPOSURE = str(uuid.uuid4())
REVIEWER = str(uuid.uuid4())
COACH = str(uuid.uuid4())
TAKE = str(uuid.uuid4())
SNIPPET = str(uuid.uuid4())
SHA = "c" * 64
PREPARE = "prepare_mlc2_confidence_coach_packet_v1"
SUBMIT = "submit_mlc2_confidence_coach_judgment_v1"
# The shape the packet RPC really returns (0304 through 0393): the hash is
# named visible_packet_sha256, and the packet carries the moment itself.
PACKET = {
    "review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
    "acknowledgement_token": TOKEN, "visible_packet_sha256": SHA,
    "visible_packet": {"clip": {"audio_sha256": "moment-audio-hash"}},
    "candidate_id": "machine-candidate-c1", "replayed": False,
}
HANDLE = {"review_assignment_id": ASSIGNMENT, "presentation_id": PRESENTATION,
          "acknowledgement_token": TOKEN, "visible_payload_sha256": SHA}


class _Client:
    """The service-role RPC seam; records every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.raises = None

    def rpc(self, name, params):
        self.calls.append((name, params))
        if self.raises:
            raise self.raises
        answer = {PREPARE: PACKET,
                  SUBMIT: {"judgment_id": "j-1", "review_assignment_id": ASSIGNMENT,
                           "revealed": True, "replayed": False}}.get(name)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=answer))

    def names(self):
        return [name for name, _ in self.calls]


class _FakeDB:
    """The rows the packet and label routes read, and the writes they make."""

    def __init__(self):
        self.client = _Client()
        self.labels: list[dict] = []
        self.exposed = False
        self.ratings: list[dict] = []
        self.ideal_text = SimpleNamespace(get_canonical_confidence_evidence=lambda **_: None)

    def get_snippet_by_id(self, _sid):
        return {"id": SNIPPET, "session_id": TAKE, "transcript": "we kept the promise"}

    def v2_get_session_by_id(self, _sid):
        return {"id": TAKE, "intake_context": {"language": "en"}}

    def get_user_proficient_languages(self, _uid):
        return ["en"]

    def get_confidence_labels_by_snippet_ids(self, _ids):
        return {SNIPPET: list(self.labels)}

    def list_coach_clip_exposures(self, _coach, ids):
        return [{"clip_id": i} for i in ids] if self.exposed else []

    def get_owner_principal_for_user(self, _uid):
        return {"id": REVIEWER}

    def upsert_state_rating(self, **rating):
        self.ratings.append(rating)
        return True

    def list_take_feedback_self_reports_by_snippet(self, _sid):
        return []


@pytest.fixture
def chain(monkeypatch):
    from config import Config
    from routes.v2 import coach
    from routes.v2 import confidence_chain_coach as packet_route
    from services import rings
    rings.forget_writer_kill_cache()
    monkeypatch.setattr(rings, "confidence_writer_killed", lambda **_: False)
    monkeypatch.setattr(Config, "MLC2_CONFIDENCE_CUTOVER_MODE", "founder_canary")
    fake = _FakeDB()
    monkeypatch.setattr(packet_route, "db", fake)
    monkeypatch.setattr(coach, "db", fake)

    def call(route, *args, **ctx):
        with Flask(__name__).test_request_context(**ctx):
            request.user_id = COACH
            response, status = inspect.unwrap(route)(*args)
        return status, response.get_json()

    def packet():
        return call(packet_route.v2_coach_confidence_chain_packet, SNIPPET, method="POST")

    def answer(value="yes"):
        body = {"state_id": "confidence", "value": value,
                "mlc2": {**HANDLE, "exposure_id": EXPOSURE}}
        return call(coach.v2_coach_put_confidence_label, SNIPPET, method="PUT", json=body)

    fake.packet, fake.answer = packet, answer
    fake.mode = lambda value: monkeypatch.setattr(
        Config, "MLC2_CONFIDENCE_CUTOVER_MODE", value)
    return fake


def test_a_coach_who_saw_the_non_blind_side_gets_no_packet(chain):
    chain.exposed = True
    assert chain.packet() == (200, {"mlc2_blind_review": None})
    assert chain.client.calls == []


def test_an_answer_after_the_non_blind_side_is_never_a_blind_judgement(chain):
    chain.exposed = True
    status, body = chain.answer()
    assert status == 200 and body["saved"] is True and body["value"] == "yes"
    assert len(chain.ratings) == 1
    assert body["mlc2"] is None
    assert SUBMIT not in chain.client.names()


def test_a_blind_coach_gets_four_ids_and_nothing_about_the_moment(chain):
    status, body = chain.packet()
    assert status == 200
    assert body == {"mlc2_blind_review": HANDLE}
    text = json.dumps(body)
    for leaked in ("moment-audio-hash", "machine-candidate-c1", "visible_packet\""):
        assert leaked not in text
    assert chain.client.names() == [PREPARE]


def test_a_blind_answer_becomes_the_chains_judgement(chain):
    status, body = chain.answer("yes")
    assert status == 200 and body["saved"] is True
    assert chain.client.names() == [SUBMIT]
    params = chain.client.calls[0][1]
    assert params["p_decision"] == "rating_yes"
    assert params["p_exposure_id"] == EXPOSURE
    assert params["p_reviewer_principal_id"] == REVIEWER
    assert body["mlc2"]["judgment_id"] == "j-1"


def test_a_coach_who_already_rated_gets_no_packet(chain):
    chain.labels = [{"rater_id": COACH, "value": "no", "lane": "coach"}]
    assert chain.packet() == (200, {"mlc2_blind_review": None})
    assert chain.client.calls == []


def test_a_failing_chain_never_refuses_the_walk(chain):
    chain.client.raises = RuntimeError("chain is down")
    assert chain.packet() == (200, {"mlc2_blind_review": None})
    status, body = chain.answer()
    assert status == 200 and body["saved"] is True and body["mlc2"] is None
    assert len(chain.ratings) == 1


def test_dark_writes_nothing(chain):
    chain.mode("dark")
    assert chain.packet() == (200, {"mlc2_blind_review": None})
    status, body = chain.answer()
    assert status == 200 and body["saved"] is True and body["mlc2"] is None
    assert chain.client.calls == []
