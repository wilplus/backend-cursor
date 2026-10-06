"""A coach judges an imported corpus clip end to end (founder 2026-10-06,
panel answer CO1 A, decisions log N56.4: "Tests cover the whole path:
import, spotting, queue, label, split").

With ``Config.TRAINING_IMPORT_ENABLED`` on, one import walks the whole path
against fakes, through the real routes and their real decorators:

  import (prepare_training_import) -> analysis (the authorized wrapper
  process_lab_recording, transcription stubbed below it) -> V3 spotting
  stored -> GET confidence-queue returns the import's cohort in its blind
  order, with no pick, block or policy marker -> GET the clip's playback
  returns a short-lived signed URL -> PUT confidence-label saves a coach
  label -> the speaker's split is recorded.

Plus: playback refuses a speaker, an anonymous caller, a clip outside an
import's queue and a closed switch; an ordinary Take's queue is unchanged;
under PLF1 enforce mode an ownerless import is refused before any provider
call and is never processed under the importing coach's principal.
"""
from __future__ import annotations

import io
import json
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask

import auth
from routes import admin as admin_mod
from routes.v2 import coach as v2_coach
from services import corpus_coach_queue, corpus_split, training_import
from services.processing_authorization import ProcessingAuthorizationError
from services.take_feedback_policy_v3 import POLICY_VERSION as V3_POLICY_VERSION
from services.voice_confidence import VERSION as VC_VERSION

IMPORTER = "44444444-4444-4444-8444-444444444444"
COACH = "77777777-7777-4777-8777-777777777777"
SPEAKER = "88888888-8888-4888-8888-888888888888"
BUCKET = "coach_feedback_videos"

_WORDS = ("we built the plan together and every team kept its promise because "
          "the numbers told a clear story about what our customers asked for "
          "this year and what they will need next").split()


# ── fakes ──────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _SplitQuery:
    def __init__(self, rows: dict):
        self.rows = rows
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
        if self.pending is not None:
            key = self.pending["speaker_key_sha256"]
            self.rows.setdefault(key, {**self.pending,
                                       "assigned_at": "2026-10-06T00:00:00Z"})
            return _Result([])
        key = self.filters.get("speaker_key_sha256")
        return _Result([self.rows[key]] if key in self.rows else [])


class _Client:
    def __init__(self):
        self.splits: dict = {}

    def table(self, name):
        assert name == "corpus_speaker_splits", name
        return _SplitQuery(self.splits)


class _Takes:
    """The take repository calls an import makes, kept on ``sessions``."""

    def __init__(self, store: "FakeDB"):
        self.store = store

    def _row(self, sid):
        return self.store.sessions.setdefault(str(sid), {"id": str(sid)})

    def find_training_import_by_key(self, _key):
        return None

    def v2_create_internal_session(self, sid):
        self.store.sessions[str(sid)] = {"id": str(sid), "user_id": None,
                                         "status": "processing"}
        return self.store.sessions[str(sid)]

    def set_session_intake_context(self, sid, ctx):
        self._row(sid)["intake_context"] = dict(ctx)
        return True

    def set_session_source(self, sid, source):
        self._row(sid)["source"] = source
        return True

    def set_session_user_id(self, sid, user_id):
        self._row(sid)["user_id"] = user_id
        return True

    def set_session_arc(self, sid, arc_id, take_index):
        self._row(sid).update({"arc_id": arc_id, "take_index": take_index})
        return True

    def set_session_analysis_state(self, sid, state, error=None):
        self._row(sid)["analysis_state"] = state
        return True

    def set_session_presentation_duration(self, sid, _duration):
        return True

    def v2_set_session_recording(self, sid, recording_id):
        self._row(sid)["recording_id"] = recording_id
        return True


class _Recordings:
    def __init__(self, store: "FakeDB"):
        self.store = store

    def create_recording(self, payload):
        self.store.recordings_rows[payload["id"]] = dict(payload)
        return payload


class _IdealText:
    """An import has no canonical evidence span, and is given none."""

    def __init__(self):
        self.evidence_reads: list = []

    def get_canonical_confidence_evidence(self, *, take_id, snippet_id):
        self.evidence_reads.append((take_id, snippet_id))
        return None


class FakeDB:
    def __init__(self):
        self.sessions: dict = {}
        self.snippets: list = []
        self.recordings_rows: dict = {}
        self.labels: dict = {}
        self.upserts: list = []
        self.languages: dict = {COACH: ["en"], IMPORTER: ["en"]}
        self.assignments: list = []
        self.client = _Client()
        self.takes = _Takes(self)
        self.recordings = _Recordings(self)
        self.ideal_text = _IdealText()

    # reads the import, the spotting and the routes make
    def v2_get_session_by_id(self, sid):
        return self.sessions.get(str(sid))

    def get_snippets_by_session(self, sid):
        return [dict(s) for s in self.snippets if s["session_id"] == str(sid)]

    def get_snippet_by_id(self, snippet_id):
        return next((dict(s) for s in self.snippets
                     if s["id"] == str(snippet_id)), None)

    def get_coach_snippet_drafts(self, _sid):
        return []

    def get_user_transcript_edits(self, _sid):
        return []

    def get_snippet_slide_corrections(self, _sid):
        return {}

    def get_user_proficient_languages(self, user_id):
        return self.languages.get(str(user_id), [])

    def get_recording(self, recording_id):
        return self.recordings_rows.get(str(recording_id))

    def list_pending_confidence_rereviews(self, _sid):
        return []

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {str(i): list(self.labels.get(str(i), [])) for i in ids}

    def upsert_state_rating(self, **kwargs):
        self.upserts.append(kwargs)
        row = kwargs["row"]
        self.labels.setdefault(str(kwargs["snippet_id"]), []).append({
            "rater_id": str(kwargs["rater_id"]), "value": row["value"],
            "unrateable": row["unrateable"], "note": row.get("note"),
            "lane": kwargs["lane"], "self_report": kwargs["self_report"],
            "blind": True,
        })
        return True

    def list_take_feedback_self_reports_by_snippet(self, _snippet_id):
        return []

    # the canonical presentation an ordinary Take's queue goes through
    def assign_canonical_coach_confidence_evidence(self, **kwargs):
        self.assignments.append(kwargs)
        return {"assignment_id": str(uuid.uuid4())}


def _stub_analysis(fake: FakeDB, *, count: int = 12, words_each: int = 30):
    """What the transcription and the cutter leave behind, written where the
    real pipeline writes it: pieces on the import's parent audio, each with a
    universal-v3 delivery read (the score only orders V3's pick)."""
    def impl(**kwargs):
        rows = []
        for i in range(count):
            text = " ".join(_WORDS[(i * 7 + k) % len(_WORDS)]
                            for k in range(words_each))
            rows.append({
                "id": str(uuid.UUID(int=i + 1)),
                "session_id": kwargs["session_id"],
                "recording_id": kwargs["recording_id"],
                "audio_segment_path": kwargs["parent_audio_url"],
                "start_offset_ms": i * 10_000,
                "duration_ms": 9_500,
                "transcript": text,
                "language": "en",
                "metrics": {
                    "piece": {"index": i},
                    "voice_confidence": {
                        "version": VC_VERSION,
                        "score": round(((i * 37) % 19) / 10 - 0.9, 2)},
                },
            })
        fake.snippets.extend(rows)
        fake.calls_impl.append(kwargs)
        return {"snippets": rows, "transcript": " ".join(r["transcript"] for r in rows)}
    fake.calls_impl = []  # type: ignore[attr-defined]
    return impl


@pytest.fixture
def on():
    with patch("config.Config.TRAINING_IMPORT_ENABLED", True):
        yield


@pytest.fixture
def fake():
    store = FakeDB()
    with patch.object(v2_coach, "db", store), patch("services.db.db", store):
        yield store


def _import(fake: FakeDB, **analysis) -> str:
    """One import, prepared and analysed, as the route's thread runs it."""
    with patch("services.min_content_gate.evaluate_min_content_bytes",
               return_value={"ok": True, "duration_sec": 120.0}), \
            patch("services.coach_video_storage.put_coach_object_bytes"), \
            patch("services.coach_video_storage.coach_media_public_url",
                  return_value=None):
        prepared = training_import.prepare_training_import(
            audio_bytes=b"RIFF....WAVE", filename="talk.wav", user_id=IMPORTER,
            topic="Quarterly plan", speaker_label="Jane Doe", language="en",
            database=fake)
    assert prepared["ok"] is True, prepared
    with patch("services.lab_recording._process_lab_recording_impl",
               side_effect=_stub_analysis(fake, **analysis)):
        out = training_import.run_training_import_analysis(
            prepared=prepared, audio_bytes=b"RIFF....WAVE", filename="talk.wav",
            database=fake, queue_per_band=5)
    assert out["ok"] is True, out
    return prepared["session_id"]


def _call(view, path, *, method="GET", user=COACH, coach=True, admin=False,
          token=True, json_body=None, args=()):
    app = Flask(__name__)
    headers = {"Authorization": "Bearer t"} if token else {}
    with app.test_request_context(path, method=method, headers=headers,
                                  json=json_body):
        with patch.object(auth, "verify_supabase_token",
                          return_value={"sub": user, "email": "c@x"}), \
                patch.object(admin_mod, "is_admin", return_value=admin), \
                patch.object(admin_mod, "is_coach", return_value=coach):
            result = view(*args)
    resp, status = result if isinstance(result, tuple) else (result, result.status_code)
    return resp, status


def _queue(sid, **kw):
    resp, status = _call(v2_coach.v2_coach_confidence_queue,
                         f"/v2/coach/sessions/{sid}/confidence-queue",
                         args=(sid,), **kw)
    return resp.get_json(), status


def _play(snippet_id, **kw):
    return _call(v2_coach.v2_coach_corpus_clip_playback,
                 f"/v2/coach/corpus/clips/{snippet_id}/playback",
                 args=(snippet_id,), **kw)


def _signed(bucket, key, expires_in=0):
    return f"https://r2.example/{bucket}/{key}?X-Amz-Expires={expires_in}"


_PICK = ("v3_block", "corpus_v3_spotting", "selected_snippet_id",
         V3_POLICY_VERSION, "frame_hash", "block_id", "speech-block",
         "label_queue_selection", "corpus-v3", "selection_reason",
         "sampling_probability", "score")

_FORBIDDEN = ("v3_block", "corpus_v3_spotting", "selected_snippet_id",
              V3_POLICY_VERSION, "frame_hash", "block_id", "speech-block",
              "label_queue_selection", "corpus-v3", "selection", "policy",
              "sampling_probability", "score", "voice_confidence", "metrics",
              "machine_value", "transcript")


def _assert_no_pick(payload: Any):
    """After the answer the route releases the clip (its words, the
    machine's band, the owner's answer: BLINDNESS RELEASE); the V3 pick,
    its block and the cohort's reasons stay server-side even then."""
    text = json.dumps(payload)
    for word in _PICK:
        assert word not in text, word


def _assert_blind(payload: Any):
    text = json.dumps(payload)
    for word in _FORBIDDEN:
        assert word not in text, word
    for word in ("plan", "promise", "customers"):
        assert word not in text, "transcript words before the answer"


# ── the whole path ─────────────────────────────────────────────────────────

def test_a_coach_judges_an_imported_clip_end_to_end(on, fake):
    sid = _import(fake)
    sess = fake.sessions[sid]

    # import + analysis: ownerless, through the authorized wrapper.
    assert sess["source"] == "training_import" and sess["analysis_state"] == "ready"
    assert not sess.get("owner_principal_id") and not sess.get("project_id")
    assert len(fake.calls_impl) == 1  # type: ignore[attr-defined]

    # spotting stored on the import, never shown.
    ctx = sess["intake_context"]
    spotting = ctx["corpus_v3_spotting"]
    assert spotting["outcome"] == "spotted" and spotting["blocks"]
    cohort = [r["snippet_id"] for r in ctx["label_queue_selection"]]
    picks = {b["selected_snippet_id"] for b in spotting["blocks"]}
    assert picks <= set(cohort)

    # queue: the frozen cohort, in its blind order, allowlisted.
    body, status = _queue(sid)
    assert status == 200, body
    assert [row["snippet_id"] for row in body["queue"]] == cohort
    assert body["count"] == len(cohort) and body["labelled"] == 0
    for row in body["queue"]:
        assert set(row) == {"snippet_id", "label", "re_review", "rating_locked",
                            "rating_lock_reason", "learning_exposures"}
        assert row["label"] is None and row["learning_exposures"] == []
    _assert_blind(body)
    # No canonical handle was minted for an import.
    assert fake.assignments == []

    # play: a short-lived signed URL to the import's audio, and the window.
    clip = next(s for s in fake.snippets if s["id"] == cohort[0])
    with patch("services.coach_video_storage.presigned_get_coach_object",
               side_effect=_signed) as presign:
        resp, status = _play(cohort[0])
    played = resp.get_json()
    assert status == 200, played
    assert presign.call_args.kwargs["expires_in"] == corpus_coach_queue.PLAYBACK_TTL_SECONDS
    assert presign.call_args.args[0] == BUCKET
    assert played == {
        "snippet_id": cohort[0],
        "url": _signed(BUCKET, clip["audio_segment_path"].split(f"{BUCKET}/", 1)[1],
                       corpus_coach_queue.PLAYBACK_TTL_SECONDS),
        "start_offset_ms": clip["start_offset_ms"],
        "duration_ms": clip["duration_ms"],
        "expires_in_s": corpus_coach_queue.PLAYBACK_TTL_SECONDS,
    }
    assert "no-store" in resp.headers["Cache-Control"]
    _assert_blind({k: v for k, v in played.items() if k != "url"})

    # label: the coach's blind answer saves as a coach label, stamped
    # server-side with the corpus cohort's reason; the response never
    # carries the pick.
    pick = next(c for c in cohort if c in picks)
    with patch("services.confidence_review_policy.reconcile_confidence_review") as review, \
            patch("services.voice_album.reconcile_voice_album_clip") as album:
        resp, status = _call(
            v2_coach.v2_coach_put_confidence_label,
            f"/v2/coach/snippets/{pick}/confidence-label", method="PUT",
            json_body={"state_id": "confidence", "value": "yes"}, args=(pick,))
    saved = resp.get_json()
    assert status == 200, saved
    assert saved["saved"] is True and saved["lane"] == "coach"
    _assert_no_pick(saved)
    (upsert,) = fake.upserts
    assert upsert["snippet_id"] == pick and upsert["lane"] == "coach"
    assert upsert["self_report"] is False and upsert["rater_id"] == COACH
    assert upsert["session_id"] == sid
    assert upsert["selection"]["selection_reason"] == "v3_block_pick"
    # L3: a corpus label sets off nothing of an owner's (no re-review, no Album).
    review.assert_not_called()
    album.assert_not_called()

    # The queue now resumes the coach's own answer, still blind.
    body, status = _queue(sid)
    assert status == 200 and body["labelled"] == 1
    answered = next(r for r in body["queue"] if r["snippet_id"] == pick)
    assert answered["label"]["value"] == "yes"
    _assert_blind(body)

    # split: the speaker's learn/test assignment is recorded, once.
    split = corpus_split.import_split(fake, sid)
    assert split is not None and split["split"] in ("train", "test")
    assert split["split"] == corpus_split.corpus_split("jane doe")
    assert len(fake.client.splits) == 1


# ── playback refusals ──────────────────────────────────────────────────────

def test_playback_refuses_a_speaker_and_an_anonymous_caller(on, fake):
    sid = _import(fake)
    queued = fake.sessions[sid]["intake_context"]["label_queue_selection"][0]["snippet_id"]
    resp, status = _play(queued, user=SPEAKER, coach=False, admin=False)
    assert status == 403 and resp.get_json()["code"] == "FORBIDDEN"
    _resp, status = _play(queued, token=False)
    assert status == 401


def test_playback_is_closed_with_the_switch(fake):
    resp, status = _play(str(uuid.UUID(int=1)))
    assert status == 410 and resp.get_json()["code"] == "PHASE2_DISABLED"


def test_playback_plays_only_a_queued_import_clip(on, fake):
    sid = _import(fake, count=40, words_each=10)
    cohort = {r["snippet_id"] for r in
              fake.sessions[sid]["intake_context"]["label_queue_selection"]}
    outside = next(s["id"] for s in fake.snippets if s["id"] not in cohort)
    # An ordinary Take's clip.
    take_sid = str(uuid.uuid4())
    fake.sessions[take_sid] = {"id": take_sid, "source": "audit_upload",
                               "intake_context": {"label_queue_selection": [
                                   {"snippet_id": "99999999-9999-4999-8999-999999999999"}]}}
    fake.snippets.append({"id": "99999999-9999-4999-8999-999999999999",
                          "session_id": take_sid, "audio_segment_path": "s3://b/k"})
    for snippet_id in (outside, "99999999-9999-4999-8999-999999999999",
                       str(uuid.uuid4())):
        resp, status = _play(snippet_id)
        assert status == 404, snippet_id
        assert resp.get_json() == {"code": "NOT_FOUND", "error": "clip not found"}
    _resp, status = _play("not-a-uuid")
    assert status == 400


def test_playback_follows_the_rater_language(on, fake):
    sid = _import(fake)
    queued = fake.sessions[sid]["intake_context"]["label_queue_selection"][0]["snippet_id"]
    fake.languages[COACH] = ["pl"]
    resp, status = _play(queued)
    assert status == 409 and resp.get_json()["code"] == "RATER_LANGUAGE_MISMATCH"


def test_unsignable_audio_is_503_never_a_raw_reference(on, fake):
    sid = _import(fake)
    queued = fake.sessions[sid]["intake_context"]["label_queue_selection"][0]["snippet_id"]
    with patch("services.coach_video_storage.presigned_get_coach_object",
               side_effect=RuntimeError("no signer")):
        resp, status = _play(queued)
    assert status == 503
    assert "s3://" not in json.dumps(resp.get_json())


# ── the switch and ordinary Takes ──────────────────────────────────────────

def test_with_the_switch_off_an_import_queue_answers_as_before(fake):
    with patch("config.Config.TRAINING_IMPORT_ENABLED", True):
        sid = _import(fake)
    body, status = _queue(sid)
    assert status == 200
    assert body["queue"] == [] and body["count"] == 0


def _ordinary_take(fake: FakeDB, *, owned: bool) -> str:
    sid = str(uuid.uuid4())
    snippets = [{"id": str(uuid.uuid4()), "session_id": sid, "language": "en",
                 "start_offset_ms": i * 1000, "duration_ms": 900,
                 "transcript": "we built the plan", "audio_segment_path": "s3://b/k",
                 "metrics": {}} for i in range(4)]
    fake.snippets.extend(snippets)
    fake.sessions[sid] = {
        "id": sid, "source": "audit_upload", "user_id": SPEAKER,
        "intake_context": {"language": "en", "label_queue_selection": [
            {"snippet_id": s["id"], "policy_version": "p", "reason": "random",
             "sampling_probability": 0.5} for s in snippets]},
        **({"owner_principal_id": str(uuid.uuid4()),
            "project_id": str(uuid.uuid4())} if owned else {}),
    }
    return sid


@pytest.mark.parametrize("switch", [False, True])
def test_an_ordinary_take_queue_is_unchanged(fake, switch):
    sid = _ordinary_take(fake, owned=True)
    evidence = {"evidence_span_id": str(uuid.uuid4()), "audio_ref": "a",
                "start_ms": 0, "end_ms": 1}
    with patch("config.Config.TRAINING_IMPORT_ENABLED", switch), \
            patch.object(fake.ideal_text, "get_canonical_confidence_evidence",
                         return_value=evidence), \
            patch("services.feedback_data_contract.blind_packet_hash",
                  return_value="h"), \
            patch("services.learning_exposures.prepare_blind_confidence_presentation",
                  return_value={"presentation": "p"}), \
            patch("services.confidence_chain_consumer.consumer_enabled",
                  return_value=False):
        body, status = _queue(sid)
    assert status == 200, body
    assert body["count"] == 4
    assert len(fake.assignments) == 4, "the canonical presentation, as before"
    for row in body["queue"]:
        assert set(row) == {"snippet_id", "playback_reference_id", "label",
                            "re_review", "rating_locked", "rating_lock_reason",
                            "learning_exposures"}
        assert row["learning_exposures"] == [{"presentation": "p"}]


@pytest.mark.parametrize("switch", [False, True])
def test_an_unowned_ordinary_take_still_presents_nothing(fake, switch):
    sid = _ordinary_take(fake, owned=False)
    with patch("config.Config.TRAINING_IMPORT_ENABLED", switch):
        body, status = _queue(sid)
    assert status == 200 and body["queue"] == []


def test_an_ordinary_take_label_still_reaches_the_owner_leg(fake):
    sid = _ordinary_take(fake, owned=True)
    snippet_id = fake.sessions[sid]["intake_context"]["label_queue_selection"][0]["snippet_id"]
    with patch("services.confidence_review_policy.reconcile_confidence_review") as review, \
            patch.object(v2_coach, "_reconcile_album_after_judgement") as album:
        v2_coach._after_coach_judgement(
            fake.sessions[sid], snippet_id=snippet_id, session_id=sid,
            lane="coach", self_report=False, value="yes", note=None,
            is_rereview=False)
    review.assert_called_once()
    album.assert_called_once()


# ── PLF1: an import under enforce mode ─────────────────────────────────────

class _EnforceClient:
    """No acquisition attempt for the import's recording; the principal RPC
    refuses an empty product owner, as Postgres does for '' as a UUID."""

    def __init__(self):
        self.rpcs: list = []

    def table(self, _name):
        class Q:
            def select(self, *_a):
                return self

            def eq(self, *_a):
                return self

            def limit(self, *_a):
                return self

            def execute(self):
                return _Result([])
        return Q()

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        raise RuntimeError('invalid input syntax for type uuid: ""')


def test_under_enforce_an_ownerless_import_is_refused_before_any_provider(
        on, fake, monkeypatch):
    """The import's acquisition principal resolves from the session's product
    owner, which an import does not have. Enforce mode therefore refuses the
    analysis before any provider call (PROCESSING_PRINCIPAL_UNRESOLVED); the
    importing coach's own principal is never used as the acquirer of a third
    party's audio. The import reads failed, with no spotting and no queue."""
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    client = _EnforceClient()
    _splits = fake.client
    fake.client = client  # type: ignore[assignment]
    with patch("services.min_content_gate.evaluate_min_content_bytes",
               return_value={"ok": True, "duration_sec": 120.0}), \
            patch("services.coach_video_storage.put_coach_object_bytes"), \
            patch("services.coach_video_storage.coach_media_public_url",
                  return_value=None):
        prepared = training_import.prepare_training_import(
            audio_bytes=b"x", filename="talk.wav", user_id=IMPORTER,
            topic="Plan", speaker_label="Jane Doe", language="en", database=fake)
    impl = _stub_analysis(fake)
    with patch("services.lab_recording._process_lab_recording_impl",
               side_effect=impl) as body:
        out = training_import.run_training_import_analysis(
            prepared=prepared, audio_bytes=b"x", filename="talk.wav",
            database=fake)
    fake.client = _splits
    body.assert_not_called()
    assert out["ok"] is False and out["reason"] == "analysis_failed"
    sid = prepared["session_id"]
    assert fake.sessions[sid]["analysis_state"] == "failed"
    ctx = fake.sessions[sid]["intake_context"]
    assert "corpus_v3_spotting" not in ctx and "label_queue_selection" not in ctx
    # The resolver was asked about an EMPTY product owner, never the coach's
    # principal, and no permit was requested.
    assert [name for name, _ in client.rpcs] == [
        "resolve_phase1_acquisition_principal_v1"]
    assert client.rpcs[0][1]["p_product_owner_principal_id"] == ""


def test_the_wrapper_raises_the_typed_refusal(fake, monkeypatch):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    sid = str(uuid.uuid4())
    fake.sessions[sid] = {"id": sid, "source": "training_import", "user_id": IMPORTER}
    fake.client = _EnforceClient()  # type: ignore[assignment]
    from services.lab_recording import process_lab_recording
    with patch("services.lab_recording._process_lab_recording_impl") as body:
        with pytest.raises(ProcessingAuthorizationError) as refused:
            process_lab_recording(session_id=sid, user_id=IMPORTER,
                                  recording_id=str(uuid.uuid4()),
                                  audio_bytes=io.BytesIO(b"x").read())
    body.assert_not_called()
    assert refused.value.code == "PROCESSING_PRINCIPAL_UNRESOLVED"


# ── 0434: a TRUNCATE cannot re-shuffle the splits either ───────────────────

def test_0434_is_manifested_after_0433_and_idempotent():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "migrations" / "manifest.txt").read_text()
    assert ("0433\ta_corpus_speaker_keeps_its_split.sql\n"
            "0434\ta_corpus_split_survives_a_truncate.sql\n") in manifest
    sql = (root / "migrations" / "a_corpus_split_survives_a_truncate.sql").read_text()
    body = sql.split("BEGIN;", 1)[1]
    assert "DROP TRIGGER IF EXISTS corpus_speaker_splits_never_truncate" in body
    assert "BEFORE TRUNCATE ON public.corpus_speaker_splits" in body
    assert "FOR EACH STATEMENT EXECUTE FUNCTION " \
           "public.corpus_speaker_splits_never_change()" in body
    assert "REVOKE ALL ON FUNCTION public.corpus_speaker_splits_never_change() " \
           "FROM PUBLIC" in body
    for destructive in ("DROP TABLE", "DROP FUNCTION", "DELETE FROM",
                        "TRUNCATE public", "ALTER TABLE", "GRANT "):
        assert destructive not in body, destructive
    rehearsal = (root / "tests" / "integration" / "confident_moment_rehearsal.sh").read_text()
    assert rehearsal.count("hard migrations/a_corpus_split_survives_a_truncate.sql") == 2
    tier = (root / "scripts" / "rehearsal_tier.sh").read_text()
    assert "tests/test_a_corpus_split_survives_a_truncate_postgres.py" in tier
