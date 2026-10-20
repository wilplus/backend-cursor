"""
STORY    As a coach labelling imported talks, I want never to see which clip
         the machine picked, so that my label stays blind.
OUTCOME
  O1  NEVER-2: the label response carries the coach's saved answer and no
      pick, block or policy data.
  O2  The pick is kept server-side: the import stores V3's blocks, picks and
      policy version, and the coach's rating is stamped with why the clip
      was asked (``v3_block_pick``).
  O3  NEVER-2: the import's status poll reports the import (ready, pieces,
      queue size) and no pick, block or policy data.
PROVES   O1 -> test_the_label_response_never_carries_the_pick
         O2 -> test_the_label_response_never_carries_the_pick
         O3 -> test_the_import_status_never_carries_the_pick
WHY      Founder 2026-10-06, panel answer CO1 A, decisions log N56.4.
"""
from __future__ import annotations

import inspect
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask, request

from routes.v2 import coach as v2_coach
from services import training_import
from services.take_feedback_policy_v3 import POLICY_VERSION as V3_POLICY_VERSION
from services.voice_confidence import VERSION as VC_VERSION

SID = "11111111-1111-4111-8111-111111111111"
ARC = "22222222-2222-4222-8222-222222222222"
REC = "33333333-3333-4333-8333-333333333333"
IMPORTER = "44444444-4444-4444-8444-444444444444"
COACH = "77777777-7777-4777-8777-777777777777"

_WORDS = ("we built the plan together and every team kept its promise because "
          "the numbers told a clear story about what our customers asked for "
          "this year and what they will need next").split()

_FORBIDDEN = ("v3_block", "corpus_v3_spotting", "selected_snippet_id",
              V3_POLICY_VERSION, "frame_hash", "block_id", "speech-block",
              "label_queue_selection", "corpus-v3")


class _Takes:
    """The session writes the import makes, kept on the fake's sessions."""

    def __init__(self, store: "FakeDB"):
        self.store = store

    def set_session_intake_context(self, sid, ctx):
        self.store.sessions[sid]["intake_context"] = dict(ctx)
        return True

    def set_session_analysis_state(self, sid, state, error=None):
        self.store.sessions[sid]["analysis_state"] = state
        return True


class FakeDB:
    """One imported talk, and the rows the label and status routes read."""

    def __init__(self, snippets):
        self.snippets = list(snippets)
        self.sessions: dict = {}
        self.ratings: list = []
        self.takes = _Takes(self)
        self.ideal_text = SimpleNamespace(get_canonical_confidence_evidence=lambda **_: None)

    def get_snippets_by_session(self, sid):
        return [s for s in self.snippets if s["session_id"] == sid]

    def get_snippet_by_id(self, sid):
        return next((s for s in self.snippets if s["id"] == sid), None)

    def v2_get_session_by_id(self, sid):
        return self.sessions.get(str(sid))

    def get_recording(self, rid):
        return {"id": rid}

    def get_user_proficient_languages(self, _uid):
        return ["en"]

    def get_confidence_labels_by_snippet_ids(self, _ids):
        return {}

    def upsert_state_rating(self, **rating):
        self.ratings.append(rating)
        return True

    def list_take_feedback_self_reports_by_snippet(self, _sid):
        return []


def _snippets(count=12, words_each=30):
    """An imported talk's pieces: deckless, on one recording, each stamped
    with a universal-v3 delivery read (the score only orders the pick)."""
    rows = []
    for i in range(count):
        text = " ".join(_WORDS[(i * 7 + k) % len(_WORDS)] for k in range(words_each))
        rows.append({
            "id": str(uuid.UUID(int=i + 1)), "session_id": SID, "recording_id": REC,
            "start_offset_ms": i * 10_000, "duration_ms": 9_500, "transcript": text,
            "metrics": {
                "piece": {"index": i},
                "voice_confidence": {"version": VC_VERSION,
                                     "score": round(((i * 37) % 19) / 10 - 0.9, 2)},
            },
        })
    return rows


@pytest.fixture
def imported(monkeypatch):
    """A talk imported end to end through the service, its analysis faked."""
    fake = FakeDB(_snippets())
    context = {"topic": "Plan", "speaker_label": "Jane Doe", "language": "en"}
    fake.sessions[SID] = {"id": SID, "arc_id": ARC, "take_index": 1, "recording_id": REC,
                          "source": "training_import", "user_id": IMPORTER,
                          "intake_context": dict(context)}
    prepared = {"ok": True, "session_id": SID, "arc_id": ARC, "recording_id": REC,
                "stages": ["confidence"], "user_id": IMPORTER, "duration_sec": 120.0,
                "speaker_label": "Jane Doe", "filename": "t.wav",
                "session_context": context}
    with patch("services.lab_recording.process_lab_recording",
               return_value={"snippets": fake.snippets}):
        out = training_import.run_training_import_analysis(
            prepared=prepared, audio_bytes=b"x", filename="t.wav",
            database=fake, queue_per_band=5)
    assert out["ok"] is True, out
    monkeypatch.setattr(v2_coach, "db", fake)
    return fake


def _call(route, *args, **ctx) -> tuple[int, Any]:
    with Flask(__name__).test_request_context(**ctx):
        request.user_id = COACH
        resp, status = inspect.unwrap(route)(*args)
    return status, resp.get_json()


def _assert_blind(payload: Any):
    text = json.dumps(payload)
    for word in _FORBIDDEN:
        assert word not in text, word


def test_the_label_response_never_carries_the_pick(imported):
    spotting = imported.sessions[SID]["intake_context"]["corpus_v3_spotting"]
    assert spotting["policy_version"] == V3_POLICY_VERSION
    pick = spotting["blocks"][0]["selected_snippet_id"]
    status, body = _call(v2_coach.v2_coach_put_confidence_label, pick, method="PUT",
                         json={"state_id": "confidence", "value": "yes"})
    assert status == 200, body
    assert body["saved"] is True and body["value"] == "yes"
    assert body["snippet_id"] == pick and body["transcript"]
    _assert_blind(body)
    # Server-side only: the rating is stamped with why the clip was asked.
    assert imported.ratings[0]["selection"]["selection_reason"] == "v3_block_pick"


def test_the_import_status_never_carries_the_pick(imported):
    status, body = _call(v2_coach.v2_coach_training_import_status, SID, method="GET")
    assert status == 200, body
    assert body["status"] == "ready" and body["snippet_count"] == 12
    assert body["queue_count"] > 0
    _assert_blind(body)
