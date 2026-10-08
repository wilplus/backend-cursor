"""The training corpus, switched on and built properly (founder 2026-10-06,
panel answer CO1 A, decisions log N56.4).

Pins the whole path with fakes:

  * the switch: ``Config.TRAINING_IMPORT_ENABLED`` off answers exactly the
    410 / fail-closed tombstone of before and writes nothing; on, a coach is
    accepted, a speaker refused, a missing language is a 400;
  * the spotting: each import runs V3's own 75-word blocks and per-block
    pick over its words, and stores blocks, picks and the policy version;
  * the queue: each block's pick and one rival from the same block, then the
    mixed queue; with no spotting it is the mixed queue, unchanged;
  * blindness: the stored pick never reaches the confidence-queue payload,
    the label response or the import's status;
  * the split: deterministic, about 20% test, grouped by speaker, a
    nameless import a speaker of its own, the stored assignment winning;
  * nothing trains by the import alone: the retired DPO release lane stays
    closed; training and promotion follow their own doors, which the founder
    opened 2026-10-08 ("turn it all ON") for the three coach-answer surfaces.

The import switch itself ships ON since 2026-10-08 (founder: "turn it all
ON"; he holds the rights to the audio); the off tests close it explicitly.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask, request

import auth
from config import Config
from routes import admin as admin_mod
from routes.v2 import coach as v2_coach
from services import confidence_labels, corpus_split, corpus_spotting
from services import training_import
from services.db import db
from services.take_feedback_policy_v3 import POLICY_VERSION as V3_POLICY_VERSION
from services.voice_confidence import VERSION as VC_VERSION

ROOT = Path(__file__).resolve().parents[1]
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


@pytest.fixture
def on():
    # By name, resolved now: a test elsewhere may reload `config`, and the
    # switch is read from whatever `config.Config` is at call time.
    with patch("config.Config.TRAINING_IMPORT_ENABLED", True):
        yield


@pytest.fixture
def off():
    # The switch ships ON since 2026-10-08; the closed behaviour is pinned
    # by closing it here, by name, like ``on``.
    with patch("config.Config.TRAINING_IMPORT_ENABLED", False):
        yield


# ── the switch ─────────────────────────────────────────────────────────────

def test_the_switch_is_a_code_constant_the_founder_turned_on():
    # ON 2026-10-08 (founder: "turn it all ON"). Still a code constant.
    source = (ROOT / "config.py").read_text()
    assert "    TRAINING_IMPORT_ENABLED = True\n" in source
    assert 'getenv("TRAINING_IMPORT_ENABLED")' not in source
    assert Config.TRAINING_IMPORT_ENABLED is True


def test_what_trains_is_what_the_founder_said():
    """N56.4: "nothing trains on the labels until the founder says so".
    He said so on 2026-10-08 ("turn it all ON"): doors 3 and 4 and the
    corpus copy open, for the three coach-answer surfaces only; the
    retired DPO release lane stays closed."""
    three = frozenset({"exercise_script", "praise_line", "clearer_version"})
    assert Config.MLC2_DATASET_RELEASES_ENABLED is False
    assert Config.MLC2_TRAINING_ENABLED is True
    assert Config.MLC2_PROMOTION_ENABLED is True
    assert Config.MLC2_TRAINING_CORPUS_COPY_ENABLED is True
    assert Config.TRAINING_SURFACES == three
    assert Config.PROMOTION_SURFACES == three


def _post(form, *, admin=False, coach=True, token=True):
    app = Flask(__name__)
    headers = {"Authorization": "Bearer t"} if token else {}
    with app.test_request_context("/v2/coach/training-imports", method="POST",
                                  headers=headers, data=form,
                                  content_type="multipart/form-data"):
        with patch.object(auth, "verify_supabase_token",
                          return_value={"sub": COACH, "email": "c@x"}), \
                patch.object(admin_mod, "is_admin", return_value=admin), \
                patch.object(admin_mod, "is_coach", return_value=coach):
            result = v2_coach.v2_coach_training_import()
    resp, status = result if isinstance(result, tuple) else (result, result.status_code)
    return resp.get_json(), status


def _form(**over):
    import io
    form = {"audio_file": (io.BytesIO(b"RIFF....WAVE"), "talk.wav"),
            "topic": "Quarterly plan", "language": "en",
            "speaker_label": "Jane Doe"}
    form.update(over)
    return {k: v for k, v in form.items() if v is not None}


def test_off_the_route_answers_410_before_anything(off):
    with patch.object(training_import, "prepare_training_import") as prepare:
        body, status = _post(_form(), token=False)
    assert status == 410
    assert body["code"] == "PHASE2_DISABLED"
    prepare.assert_not_called()


def test_off_prepare_is_the_tombstone_and_writes_nothing(off):
    fake = FakeDB()
    out = training_import.prepare_training_import(
        audio_bytes=b"x", filename="t.wav", user_id=COACH, topic="t",
        language="en", database=fake)
    assert out == {"ok": False, "reason": "phase2_training_disabled",
                   "detail": "Legacy training imports are unavailable under Phase 1."}
    assert fake.calls == []


def test_on_a_coach_is_accepted(on):
    prepared = {"ok": True, "session_id": SID, "arc_id": ARC, "stages": ["confidence"],
                "duration_sec": 12.0, "speaker_label": "Jane Doe", "language": "en"}
    with patch.object(training_import, "prepare_training_import",
                      return_value=prepared) as prepare, \
            patch.object(training_import, "run_training_import_analysis") as run:
        body, status = _post(_form())
    assert status == 202, body
    assert body["status"] == "processing" and body["session_id"] == SID
    assert prepare.call_args.kwargs["language"] == "en"
    assert prepare.call_args.kwargs["speaker_label"] == "Jane Doe"
    run.assert_called_once()


def test_on_an_admin_is_accepted(on):
    prepared = {"ok": True, "session_id": SID, "arc_id": ARC, "stages": ["confidence"]}
    with patch.object(training_import, "prepare_training_import", return_value=prepared), \
            patch.object(training_import, "run_training_import_analysis"):
        _body, status = _post(_form(), admin=True, coach=False)
    assert status == 202


def test_on_a_speaker_is_refused(on):
    with patch.object(training_import, "prepare_training_import") as prepare:
        body, status = _post(_form(), admin=False, coach=False)
    assert status == 403
    assert body["code"] == "FORBIDDEN"
    prepare.assert_not_called()


def test_on_an_unsigned_caller_is_refused(on):
    with patch.object(training_import, "prepare_training_import") as prepare:
        _body, status = _post(_form(), token=False)
    assert status == 401
    prepare.assert_not_called()


@pytest.mark.parametrize("language", [None, "", "   "])
def test_on_a_missing_language_is_400(on, language):
    with patch.object(training_import, "prepare_training_import") as prepare:
        body, status = _post(_form(language=language))
    assert status == 400
    assert body == {"code": "INVALID_INPUT", "error": "language is required"}
    prepare.assert_not_called()


def test_on_prepare_refuses_a_missing_language_too(on):
    fake = FakeDB()
    out = training_import.prepare_training_import(
        audio_bytes=b"x", filename="t.wav", user_id=COACH, topic="t",
        language=None, database=fake)
    assert out["ok"] is False and out["reason"] == "no_language"
    assert fake.calls == []


def test_only_the_import_route_moved_off_the_phase2_guard():
    """The switch guards the import and, since the corpus queue was made
    judgeable, the corpus clip's playback; nothing else."""
    source = (ROOT / "routes" / "v2" / "coach.py").read_text()
    guarded = ('@v2_bp.route("/coach/training-imports", methods=["POST"])',
               '@v2_bp.route("/coach/corpus/clips/<snippet_id>/playback", '
               'methods=["GET"])')
    for route in guarded:
        head = source[source.index(route):]
        assert head.splitlines()[1] == "@training_import_enabled"
    assert source.count("@training_import_enabled") == len(guarded)
    assert "@phase2_learning_disabled" not in source


def test_on_prepare_writes_the_import_rows(on):
    fake = FakeDB()
    with patch("services.min_content_gate.evaluate_min_content_bytes",
               return_value={"ok": True, "duration_sec": 120.0}), \
            patch("services.coach_video_storage.put_coach_object_bytes"), \
            patch("services.coach_video_storage.coach_media_public_url",
                  return_value="https://cdn/x.wav"):
        out = training_import.prepare_training_import(
            audio_bytes=b"x", filename="t.wav", user_id=COACH, topic="Plan",
            speaker_label="Jane Doe", language="EN", database=fake)
    assert out["ok"] is True, out
    assert out["language"] == "en"
    names = [c[0] for c in fake.calls]
    assert "set_session_source" in names and "create_recording" in names


# ── the spotting ───────────────────────────────────────────────────────────

def test_spotting_runs_v3_over_the_import_and_keeps_blocks_and_picks():
    snips = _snippets()
    fake = FakeDB(snips)
    fake.sessions[SID] = {"id": SID, "take_index": 1, "recording_id": REC}
    record = corpus_spotting.spot_import(fake, arc_id=ARC, session_id=SID,
                                         recording_id=REC)
    assert record["outcome"] == "spotted"
    assert record["policy_version"] == V3_POLICY_VERSION
    assert record["frame_hash"]
    blocks = record["blocks"]
    # 12 pieces of 30 words: V3's 75-word partition, never one block per piece.
    assert 3 <= len(blocks) <= 6
    covered = [sid for b in blocks for sid in b["snippet_ids"]]
    assert covered == [s["id"] for s in snips], "every piece, in order, once"
    by_id = {s["id"]: s for s in snips}
    for block in blocks:
        assert block["slide_index"] == 0, "a deckless import is one Slide run"
        assert block["selected_snippet_id"] in block["snippet_ids"]
        best = max(block["snippet_ids"],
                   key=lambda i: by_id[i]["metrics"]["voice_confidence"]["score"])
        assert block["selected_snippet_id"] == best
    # No score is kept on the record (the clip's own metrics hold it).
    assert "score" not in json.dumps(record)


def test_spotting_reuses_v3_and_does_not_reimplement_it():
    source = (ROOT / "services" / "corpus_spotting.py").read_text()
    assert "build_shadow_frame(" in source
    assert "build_transcript_document(" in source
    assert "_partition_run" not in source and "TARGET_WORDS" not in source


def test_no_document_is_an_honest_empty_record():
    record = corpus_spotting.spot_import(FakeDB([]), arc_id=ARC, session_id=SID,
                                         recording_id=REC)
    assert record["outcome"] == "no_document" and record["blocks"] == []


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


def test_the_import_stores_spotting_queue_and_split():
    snips = _snippets()
    fake = FakeDB(snips)
    out, process = _run_import(fake, snips)
    assert out["ok"] is True, out
    process.assert_called_once()
    ctx = fake.sessions[SID]["intake_context"]
    spotting = ctx["corpus_v3_spotting"]
    assert spotting["policy_version"] == V3_POLICY_VERSION
    records = ctx["label_queue_selection"]
    by_reason: dict = {}
    for r in records:
        by_reason.setdefault(r["reason"], []).append(r["snippet_id"])
    picks = {b["selected_snippet_id"] for b in spotting["blocks"]}
    assert set(by_reason["v3_block_pick"]) == picks
    assert len(by_reason.get("v3_block_rival", [])) == len(
        [b for b in spotting["blocks"] if len(b["snippet_ids"]) > 1])
    for r in records:
        if r["reason"] in ("v3_block_pick", "v3_block_rival"):
            assert r["policy_version"] == confidence_labels.CORPUS_SELECTION_POLICY_VERSION
    # Every rival sits in its pick's block.
    block_of = {sid: b["block_id"] for b in spotting["blocks"] for sid in b["snippet_ids"]}
    rivals = by_reason.get("v3_block_rival", [])
    assert {block_of[r] for r in rivals} <= {block_of[p] for p in picks}
    # The split is stored for the speaker.
    split = corpus_split.import_split(fake, SID)
    assert split is not None
    assert split["split"] == corpus_split.corpus_split("jane doe")
    assert fake.sessions[SID]["analysis_state"] == "ready"


def test_the_transcription_goes_through_the_authorized_wrapper():
    """PLF1: the import's Whisper call runs inside process_lab_recording,
    the wrapper that binds every provider call of a recording to the
    canonical authorization/permit path; nothing here calls a provider."""
    source = inspect.getsource(training_import.run_training_import_analysis)
    assert "from services.lab_recording import process_lab_recording" in source
    assert "_process_lab_recording_impl" not in source
    for module in (corpus_spotting, corpus_split):
        text = inspect.getsource(module)
        assert "openai" not in text.lower().replace("openai_service", "")
        assert "transcribe" not in text


def test_a_failed_spotting_falls_back_to_the_mixed_queue():
    snips = _snippets()
    fake = FakeDB(snips)
    with patch.object(corpus_spotting, "spot_import", side_effect=RuntimeError("x")):
        out, _ = _run_import(fake, snips)
    assert out["ok"] is True
    ctx = fake.sessions[SID]["intake_context"]
    assert "corpus_v3_spotting" not in ctx
    assert {r["policy_version"] for r in ctx["label_queue_selection"]} == {
        confidence_labels.SELECTION_POLICY_VERSION}


# ── the queue ──────────────────────────────────────────────────────────────

def test_without_spotting_the_corpus_queue_is_the_mixed_queue():
    pool = _snippets(20)
    assert (confidence_labels.corpus_label_queue(pool, None, target_size=9, seed="s")
            == confidence_labels.mixed_label_queue(pool, target_size=9, seed="s"))


def test_the_corpus_queue_is_deterministic_and_blind_ordered():
    pool = _snippets()
    spotting = {"blocks": [
        {"snippet_ids": [s["id"] for s in pool[:3]], "selected_snippet_id": pool[1]["id"]},
        {"snippet_ids": [s["id"] for s in pool[3:5]], "selected_snippet_id": pool[4]["id"]},
        {"snippet_ids": [pool[5]["id"]], "selected_snippet_id": pool[5]["id"]},
    ]}
    a = confidence_labels.corpus_label_queue(pool, spotting, target_size=3, seed="s")
    b = confidence_labels.corpus_label_queue(pool, spotting, target_size=3, seed="s")
    assert [r["id"] for r in a] == [r["id"] for r in b]
    reasons = {r["id"]: r["_selection"] for r in a}
    assert reasons[pool[1]["id"]]["reason"] == "v3_block_pick"
    assert reasons[pool[4]["id"]]["reason"] == "v3_block_pick"
    assert reasons[pool[3]["id"]]["reason"] == "v3_block_rival"
    assert reasons[pool[3]["id"]]["sampling_probability"] == 1.0
    rival_one = [i for i in (pool[0]["id"], pool[2]["id"])
                 if reasons.get(i, {}).get("reason") == "v3_block_rival"]
    assert len(rival_one) == 1 and reasons[rival_one[0]]["sampling_probability"] == 0.5
    assert len(a) == 2 + 2 + 1 + 3, "two pairs, one lone pick, three mixed"
    # The payload the coach sees carries none of it.
    payload = confidence_labels.queue_payload(a)
    assert all("_selection" not in row for row in payload)
    assert "v3_block" not in json.dumps(payload)


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


def test_the_confidence_queue_payload_never_carries_the_pick():
    snips = _snippets()
    sess = _import_session(snips)
    raw = inspect.unwrap(v2_coach.v2_coach_confidence_queue)
    app = Flask(__name__)
    with app.test_request_context(method="GET"):
        request.user_id = COACH
        with patch.object(db, "v2_get_session_by_id", return_value=sess), \
                patch.object(v2_coach, "_confidence_queue_snippets_and_language_error",
                             return_value=(snips, None)), \
                patch.object(db, "list_pending_confidence_rereviews", return_value=[]), \
                patch.object(db, "get_confidence_labels_by_snippet_ids", return_value={}), \
                patch.object(db.ideal_text, "get_canonical_confidence_evidence",
                             return_value={"evidence_span_id": str(uuid.uuid4()),
                                           "audio_ref": "a", "start_ms": 0, "end_ms": 1}), \
                patch("services.feedback_data_contract.blind_packet_hash", return_value="h"), \
                patch.object(db, "assign_canonical_coach_confidence_evidence",
                             side_effect=lambda **k: {"assignment_id": str(uuid.uuid4())}), \
                patch("services.learning_exposures.prepare_blind_confidence_presentation",
                      return_value={"presentation": "p"}), \
                patch("services.confidence_chain_consumer.consumer_enabled",
                      return_value=False):
            result = raw(SID)
    resp, status = result if isinstance(result, tuple) else (result, 200)
    body = resp.get_json()
    assert status == 200, body
    stored = sess["intake_context"]["label_queue_selection"]
    assert body["count"] == len(stored) > 0
    allowed = {"snippet_id", "playback_reference_id", "label", "re_review",
               "rating_locked", "rating_lock_reason", "learning_exposures"}
    for row in body["queue"]:
        assert set(row) <= allowed
    _assert_blind(body)


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


def test_the_import_status_never_carries_the_pick():
    snips = _snippets()
    sess = _import_session(snips)
    sess["analysis_state"] = "ready"
    raw = inspect.unwrap(v2_coach.v2_coach_training_import_status)
    app = Flask(__name__)
    with app.test_request_context(method="GET"):
        request.user_id = COACH
        with patch.object(db, "v2_get_session_by_id", return_value=sess), \
                patch.object(db, "get_snippets_by_session", return_value=snips):
            result = raw(SID)
    resp, status = result if isinstance(result, tuple) else (result, 200)
    assert status == 200
    _assert_blind(resp.get_json())


# ── the split ──────────────────────────────────────────────────────────────

def test_the_split_is_a_fixed_salted_hash():
    key = "jane doe"
    digest = hashlib.sha256(f"{corpus_split.SPLIT_SALT}:{key}".encode()).hexdigest()
    expected = "test" if int(digest, 16) % 100 < 20 else "train"
    assert corpus_split.corpus_split(key) == expected
    assert all(corpus_split.corpus_split(key) == expected for _ in range(5))


def test_about_a_fifth_of_speakers_are_held_out():
    splits = [corpus_split.corpus_split(f"speaker-{i}") for i in range(1000)]
    share = splits.count("test") / len(splits)
    assert 0.15 <= share <= 0.25, share
    assert set(splits) == {"train", "test"}


def test_one_speaker_is_one_group_whatever_the_spelling():
    a = corpus_split.speaker_key_for("Jane Doe", "s1")
    b = corpus_split.speaker_key_for("  JANE   doe ", "s2")
    c = corpus_split.speaker_key_for("Ｊａｎｅ Doe", "s3")  # full-width (NFKC)
    assert a == b == c == "jane doe"
    assert corpus_split.corpus_split(a) == corpus_split.corpus_split(b)


def test_a_nameless_import_is_a_speaker_of_its_own():
    assert corpus_split.speaker_key_for(None, "s1") == "import:s1"
    assert corpus_split.speaker_key_for("   ", "s2") == "import:s2"
    assert corpus_split.speaker_key_for(None, "s1") != corpus_split.speaker_key_for(None, "s2")


def test_two_imports_of_one_speaker_share_a_split():
    fake = FakeDB()
    for sid, label in (("s1", "Jane Doe"), ("s2", "jane doe ")):
        fake.sessions[sid] = {"id": sid, "source": "training_import",
                              "intake_context": {"speaker_label": label}}
        corpus_split.assign_speaker_split(
            fake, corpus_split.speaker_key_for(label, sid))
    one, two = corpus_split.import_split(fake, "s1"), corpus_split.import_split(fake, "s2")
    assert one["split"] == two["split"]
    assert len(fake.client.splits.rows) == 1


def test_the_stored_assignment_wins_over_recomputation():
    fake = FakeDB()
    key = "jane doe"
    computed = corpus_split.corpus_split(key)
    other = "train" if computed == "test" else "test"
    fake.client.splits.rows[corpus_split.speaker_key_digest(key)] = {
        "speaker_key_sha256": corpus_split.speaker_key_digest(key),
        "split": other, "split_version": "an-older-rule", "assigned_at": "t"}
    assert corpus_split.assign_speaker_split(fake, key)["split"] == other
    fake.sessions["s1"] = {"id": "s1", "source": "training_import",
                           "intake_context": {"speaker_label": "Jane Doe"}}
    assert corpus_split.import_split(fake, "s1") == {
        "session_id": "s1", "split": other, "split_version": "an-older-rule",
        "assigned_at": "t"}
    # Even with the salt edited, the stored row stands.
    with patch.object(corpus_split, "SPLIT_SALT", "edited"):
        assert corpus_split.assign_speaker_split(fake, key)["split"] == other


def test_the_table_holds_a_digest_never_the_name():
    fake = FakeDB()
    corpus_split.assign_speaker_split(fake, "jane doe")
    (stored_key, row), = fake.client.splits.rows.items()
    assert "jane" not in json.dumps(row)
    assert len(stored_key) == 64 and stored_key == row["speaker_key_sha256"]
    assert row["split_version"] == corpus_split.SPLIT_VERSION


def test_a_session_that_is_not_an_import_has_no_split():
    fake = FakeDB()
    fake.sessions["s1"] = {"id": "s1", "source": "audit_upload", "intake_context": {}}
    assert corpus_split.import_split(fake, "s1") is None
    assert corpus_split.import_split(fake, "missing") is None


def test_an_unreadable_table_reads_as_unknown_never_a_guess():
    class Down:
        def table(self, _name):
            raise RuntimeError("down")
    fake = FakeDB()
    fake.client = Down()  # type: ignore[assignment]
    assert corpus_split.assign_speaker_split(fake, "jane doe") is None
    assert corpus_split.read_speaker_split(fake, "jane doe") is None


# ── the migration and the registry ─────────────────────────────────────────

def test_the_migration_is_manifested_idempotent_and_closed_to_browsers():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0433\ta_corpus_speaker_keeps_its_split.sql\n" in manifest
    sql = (ROOT / "migrations" / "a_corpus_speaker_keeps_its_split.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.corpus_speaker_splits" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON TABLE public.corpus_speaker_splits FROM PUBLIC" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "user_id" not in sql.split("BEGIN;", 1)[1]


def test_the_registry_names_the_table_non_subject():
    from services.data_purge_registry import NON_SUBJECT_RELATIONS
    assert "corpus_speaker_splits" in NON_SUBJECT_RELATIONS
