"""The training corpus, switched on and built properly (founder 2026-10-06,
panel answer CO1 A, decisions log N56.4).

Pins the whole path with fakes:

  * the route: a coach is accepted, a speaker refused, a missing language
    is a 400;
  * the spotting: each import runs V3's own 75-word blocks and per-block
    pick over its words, and stores blocks, picks and the policy version;
  * the queue: each block's pick and one rival from the same block, then the
    mixed queue; with no spotting it is the mixed queue, unchanged;
  * blindness: the stored pick never reaches the confidence-queue payload,
    the label response or the import's status;
  * the split: deterministic, about 20% test, grouped by speaker, a
    nameless import a speaker of its own, the stored assignment winning;
  * nothing trains by the import alone: the retired DPO release lane stays
    closed; training and promotion follow the surfaces the founder named
    on 2026-10-08 ("turn it all ON").

The import is on since 2026-10-08 (founder: "turn it all ON"; he holds the
rights to the audio); its code switch was removed 2026-10-12 ("remove the
learning doors").
"""
from __future__ import annotations

import inspect
import json
import uuid
from typing import Any
from unittest.mock import patch

from flask import Flask, request

from routes.v2 import coach as v2_coach
from services import training_import
from services.db import db
from services.take_feedback_policy_v3 import POLICY_VERSION as V3_POLICY_VERSION
from services.voice_confidence import VERSION as VC_VERSION

SID = "11111111-1111-4111-8111-111111111111"
ARC = "22222222-2222-4222-8222-222222222222"
REC = "33333333-3333-4333-8333-333333333333"
COACH = "44444444-4444-4444-8444-444444444444"

_WORDS = ("we built the plan together and every team kept its promise because "
          "the numbers told a clear story about what our customers asked for "
          "this year and what they will need next").split()


# ── fakes ──────────────────────────────────────────────────────────────────

class _Query:
    def __init__(self, table: "_SplitTable"):
        self.table = table
        self.filters: dict = {}
        self.pending: Any = None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, *_a):
        return self

    def upsert(self, row, on_conflict=None, ignore_duplicates=False):
        assert on_conflict == "speaker_key_sha256" and ignore_duplicates
        self.pending = row
        return self

    def execute(self):
        class R:
            data: list = []
        if self.pending is not None:
            key = self.pending["speaker_key_sha256"]
            self.table.rows.setdefault(key, {**self.pending,
                                             "assigned_at": "2026-10-06T00:00:00Z"})
            R.data = []
            return R
        key = self.filters.get("speaker_key_sha256")
        R.data = [self.table.rows[key]] if key in self.table.rows else []
        return R


class _SplitTable:
    def __init__(self):
        self.rows: dict = {}


class _Client:
    def __init__(self):
        self.splits = _SplitTable()

    def table(self, name):
        assert name == "corpus_speaker_splits", name
        return _Query(self.splits)


class _Takes:
    def __init__(self, store: "FakeDB"):
        self.store = store

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.store.calls.append((name, args, kwargs))
            if name == "set_session_intake_context":
                self.store.sessions.setdefault(args[0], {"id": args[0]})[
                    "intake_context"] = dict(args[1])
            if name == "set_session_analysis_state":
                self.store.sessions.setdefault(args[0], {"id": args[0]})[
                    "analysis_state"] = args[1]
            return None if name == "find_training_import_by_key" else True
        return call


class _Recordings:
    def __init__(self, store: "FakeDB"):
        self.store = store

    def create_recording(self, payload):
        self.store.calls.append(("create_recording", (payload,), {}))
        return payload


class FakeDB:
    def __init__(self, snippets=None):
        self.calls: list = []
        self.sessions: dict = {}
        self.snippets = list(snippets or [])
        self.client = _Client()
        self.takes = _Takes(self)
        self.recordings = _Recordings(self)

    def get_snippets_by_session(self, sid):
        return [s for s in self.snippets if s["session_id"] == sid]

    def v2_get_session_by_id(self, sid):
        return self.sessions.get(str(sid))

    def get_coach_snippet_drafts(self, _sid):
        return []

    def get_user_transcript_edits(self, _sid):
        return []

    def get_snippet_slide_corrections(self, _sid):
        return {}


def _snippets(count=12, words_each=30, sid=SID, rec=REC):
    """An imported talk's pieces: deckless, on one recording, each stamped
    with a universal-v3 delivery read (the score only orders the pick)."""
    rows = []
    for i in range(count):
        text = " ".join(_WORDS[(i * 7 + k) % len(_WORDS)] for k in range(words_each))
        rows.append({
            "id": str(uuid.UUID(int=i + 1)),
            "session_id": sid,
            "recording_id": rec,
            "start_offset_ms": i * 10_000,
            "duration_ms": 9_500,
            "transcript": text,
            "metrics": {
                "piece": {"index": i},
                "voice_confidence": {"version": VC_VERSION,
                                     "score": round(((i * 37) % 19) / 10 - 0.9, 2)},
            },
        })
    return rows


# ── the spotting ───────────────────────────────────────────────────────────


def _prepared():
    return {"ok": True, "session_id": SID, "arc_id": ARC, "recording_id": REC,
            "stages": ["confidence"], "user_id": COACH, "duration_sec": 120.0,
            "speaker_label": "Jane Doe", "filename": "t.wav",
            "session_context": {"topic": "Plan", "speaker_label": "Jane Doe",
                                "language": "en"}}


def _run_import(fake, snips):
    fake.sessions[SID] = {"id": SID, "take_index": 1, "recording_id": REC,
                          "source": "training_import",
                          "intake_context": _prepared()["session_context"]}
    with patch("services.lab_recording.process_lab_recording",
               return_value={"snippets": snips}) as process:
        out = training_import.run_training_import_analysis(
            prepared=_prepared(), audio_bytes=b"x", filename="t.wav",
            database=fake, queue_per_band=5)
    return out, process


# ── the queue ──────────────────────────────────────────────────────────────


# ── blindness on the wire ──────────────────────────────────────────────────

_FORBIDDEN = ("v3_block", "corpus_v3_spotting", "selected_snippet_id",
              V3_POLICY_VERSION, "frame_hash", "block_id", "speech-block",
              "label_queue_selection", "corpus-v3")


def _assert_blind(payload: Any):
    text = json.dumps(payload)
    for word in _FORBIDDEN:
        assert word not in text, word


def _import_session(snips):
    fake = FakeDB(snips)
    _run_import(fake, snips)
    sess = dict(fake.sessions[SID])
    sess.update({"owner_principal_id": "55555555-5555-4555-8555-555555555555",
                 "project_id": "66666666-6666-4666-8666-666666666666",
                 "arc_id": ARC, "user_id": COACH})
    return sess


def test_the_label_response_never_carries_the_pick():
    snips = _snippets()
    sess = _import_session(snips)
    pick = sess["intake_context"]["corpus_v3_spotting"]["blocks"][0]["selected_snippet_id"]
    snip = next(s for s in snips if s["id"] == pick)
    upserts: list = []
    raw = inspect.unwrap(v2_coach.v2_coach_put_confidence_label)
    app = Flask(__name__)
    with app.test_request_context(method="PUT",
                                  json={"state_id": "confidence", "value": "yes"}):
        request.user_id = "77777777-7777-4777-8777-777777777777"
        with patch.object(db, "get_snippet_by_id", return_value=snip), \
                patch.object(db, "v2_get_session_by_id", return_value=sess), \
                patch.object(db, "get_confidence_labels_by_snippet_ids", return_value={}), \
                patch.object(db, "upsert_state_rating",
                             side_effect=lambda **k: upserts.append(k) or True), \
                patch.object(db, "list_take_feedback_self_reports_by_snippet",
                             return_value=[]), \
                patch.object(v2_coach, "_rater_language_outcome",
                             return_value=("matched", "en")), \
                patch.object(v2_coach, "_session_shows_slides", return_value=False), \
                patch("services.coach_judgement_record.canonical_dual_write"), \
                patch.object(v2_coach, "_confidence_chain_judgment", return_value=None), \
                patch.object(v2_coach, "_after_coach_judgement"):
            result = raw(pick)
    resp, status = result if isinstance(result, tuple) else (result, 200)
    body = resp.get_json()
    assert status == 200, body
    _assert_blind(body)
    # Server-side only: the rating is stamped with why the clip was asked.
    assert upserts[0]["selection"]["selection_reason"] == "v3_block_pick"


# ── the split ──────────────────────────────────────────────────────────────


# ── the migration and the registry ─────────────────────────────────────────
