"""A coach judges an imported corpus clip end to end (founder 2026-10-06,
panel answer CO1 A, decisions log N56.4: "Tests cover the whole path:
import, spotting, queue, label, split").

With the corpus import on, one import walks the whole path
against fakes, through the real routes and their real decorators:

  import (prepare_training_import) -> analysis (the authorized wrapper
  process_lab_recording, transcription stubbed below it) -> V3 spotting
  stored -> GET confidence-queue returns the import's cohort in its blind
  order, with no pick, block or policy marker -> GET the clip's playback
  returns a short-lived signed URL -> PUT confidence-label saves a coach
  label -> the speaker's split is recorded.

Plus: playback refuses a speaker, an anonymous caller and a clip outside an
import's queue; an ordinary Take's queue is unchanged.

Under PLF1 enforce mode (founder 2026-10-07, CO2, decisions log N58) an
import registered by the coach import route is analysed under the founder's
corpus basis: its permit names N58 and the session, the provider is called
and the spotting stored; never under the importing coach's principal. Refused:
an ordinary or guest Take, a forged source flag, an import
the route did not create, no basis in force. CO3 A: the importer's own blind
judgement on their import is not a self-report.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from routes.v2 import coach as v2_coach
from services.processing_authorization import ProcessingAuthorizationError
from services.voice_confidence import VERSION as VC_VERSION

IMPORTER = "44444444-4444-4444-8444-444444444444"
COACH = "77777777-7777-4777-8777-777777777777"
SPEAKER = "88888888-8888-4888-8888-888888888888"

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
def fake():
    store = FakeDB()
    with patch.object(v2_coach, "db", store), patch("services.db.db", store):
        yield store


# ── the whole path ─────────────────────────────────────────────────────────


# ── playback refusals ──────────────────────────────────────────────────────


# ── ordinary Takes ──────────────────────────────────────────


# ── PLF1: an import under enforce mode, on the corpus basis (N58) ──────────

BASIS_ID = "0d580435-5858-4058-8058-000000000058"
ACQUIRER = "55555555-5555-4555-8555-555555555555"
_CORPUS_RPCS = {"register_corpus_import_v1", "issue_corpus_provider_permit_v1",
                "record_corpus_provider_operation_v1"}


class _Exec:
    def __init__(self, run):
        self.run = run

    def execute(self):
        return _Result(self.run())


class _EnforceClient:
    """The database half under enforce mode, as 0435 and 0355 decide it:
    the corpus RPCs keep 0435's rule (registered by the route, a training
    import, no owner or project, its own admin_import recording, no Phase-1
    intake, a basis in force); the Phase-1 resolver resolves an owned Take
    to its owner, and the Phase-1 permit writer refuses (no receipt here).
    The SQL itself runs in
    tests/test_a_corpus_import_is_processed_under_the_founders_basis_postgres.py."""

    def __init__(self, store: FakeDB, *, basis: bool = True):
        self.store = store
        self.basis = basis
        self.rpcs: list = []
        self.registrations: dict = {}
        self.permits: list = []
        self.events: list = []
        self.splits = store.client.splits

    def table(self, name):
        if name == "corpus_speaker_splits":
            return _SplitQuery(self.splits)

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
        self.rpcs.append((name, dict(params)))
        return _Exec(lambda: getattr(self, "_" + name)(params))

    def _refusal(self, sid, rid):
        take = self.store.sessions.get(str(sid))
        if not take or take.get("source") != "training_import":
            return "CORPUS_SOURCE_NOT_IMPORT"
        if take.get("owner_principal_id") or take.get("project_id"):
            return "CORPUS_SESSION_HAS_OWNER"
        rec = self.store.recordings_rows.get(str(rid))
        if (not rec or rec.get("session_v2_id") != str(sid)
                or rec.get("recording_origin") != "admin_import"):
            return "CORPUS_RECORDING_NOT_IMPORT"
        return None

    def _register_corpus_import_v1(self, p):
        sid, rid = p["p_session_id"], p["p_recording_id"]
        if sid not in self.registrations:
            refusal = self._refusal(sid, rid)
            if refusal:
                raise RuntimeError(refusal)
            if not self.basis:
                raise RuntimeError("CORPUS_BASIS_ABSENT")
            self.registrations[sid] = rid
        return {"session_id": sid, "recording_id": rid, "basis_id": BASIS_ID,
                "basis_decision_ref": "N58"}

    def _issue_corpus_provider_permit_v1(self, p):
        sid = p["p_session_id"]
        rid = self.registrations.get(sid)
        if rid is None or (p["p_recording_id"] and p["p_recording_id"] != rid):
            raise RuntimeError("CORPUS_IMPORT_UNREGISTERED")
        refusal = self._refusal(sid, rid)
        if refusal:
            raise RuntimeError(refusal)
        if not self.basis:
            raise RuntimeError("CORPUS_BASIS_ABSENT")
        permit = {"permit_id": str(uuid.uuid4()), "provider": p["p_provider"],
                  "operation_kind": p["p_operation_kind"],
                  "expires_at": "2999-01-01T00:00:00+00:00",
                  "basis_id": BASIS_ID, "basis_decision_ref": "N58",
                  "session_id": sid, "recording_id": rid}
        self.permits.append(permit)
        return permit

    def _record_corpus_provider_operation_v1(self, p):
        self.events.append((p["p_permit_id"], p["p_event_kind"]))
        return str(uuid.uuid4())

    def _resolve_phase1_acquisition_principal_v1(self, p):
        owner = p["p_product_owner_principal_id"]
        if not owner:
            raise RuntimeError('invalid input syntax for type uuid: ""')
        return owner

    def _issue_phase1_provider_permit_v1(self, _p):
        raise RuntimeError("PROCESSING_AUTHORIZATION_REQUIRED")


class _Whisper:
    """The transcription provider, as the permitted adapter reaches it."""

    calls: list = []

    def __init__(self):
        self.client = object()

    def transcribe_audio(self, _audio, filename, **kwargs):
        _Whisper.calls.append((filename, kwargs.get("usage_session_id")))
        words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
                 for i, w in enumerate(_WORDS[:12])]
        return {"segments": [{"start": 0.0, "end": 5.0,
                              "text": " ".join(_WORDS[:12])}],
                "words": words, "language": "en", "duration": 120.0}


def _through_whisper(fake: FakeDB):
    """The analysis body: the REAL transcription stage (its adapter, its
    permit, its provider call), then the pieces the cutter leaves behind."""
    pieces = _stub_analysis(fake)

    def impl(**kwargs):
        from services.recording_state import RecordingState
        from services.recording_transcription import transcribe_recording
        state = transcribe_recording(RecordingState(
            session_id=kwargs["session_id"], user_id=kwargs["user_id"],
            recording_id=kwargs["recording_id"],
            audio_bytes=kwargs["audio_bytes"], filename=kwargs["filename"],
            session_context=kwargs["session_context"],
            parent_audio_url=kwargs["parent_audio_url"],
            recording_kind="spoken", paired_session_id=None,
            run_analytics=False))
        assert state.words_all, "the transcript came back"
        return pieces(**kwargs)
    return impl


@pytest.fixture
def enforce(fake, monkeypatch):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    client = _EnforceClient(fake)
    fake.client = client  # type: ignore[assignment]
    fake.set_recording_transcription_language_if_missing = (  # type: ignore[attr-defined]
        lambda _rid, language: language)
    _Whisper.calls = []
    with patch("services.openai_service.OpenAIService", _Whisper), \
            patch("services.token_account.charge"):
        yield client


def _names(client) -> set:
    return {name for name, _ in client.rpcs}


def _owned_take(fake: FakeDB, *, source: str, user_id) -> tuple:
    sid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    fake.sessions[sid] = {"id": sid, "source": source, "user_id": user_id,
                          "owner_principal_id": ACQUIRER,
                          "project_id": str(uuid.uuid4()), "recording_id": rid}
    fake.recordings_rows[rid] = {"id": rid, "session_v2_id": sid}
    return sid, rid


def _process(fake: FakeDB, sid: str, rid: str, user_id=None):
    from services.lab_recording import process_lab_recording
    with patch("services.lab_recording._process_lab_recording_impl",
               side_effect=_through_whisper(fake)):
        return process_lab_recording(
            session_id=sid, user_id=user_id, recording_id=rid,
            audio_bytes=b"x", filename="take.webm", session_context={},
            parent_audio_url="s3://b/k")


def _corpus_permit(fake: FakeDB, sid: str, rid, principal: str = ""):
    from services.processing_authorization import CorpusImportAuthorization
    return CorpusImportAuthorization(fake).issue_provider_permit(
        acquisition_principal_id=principal, take_id=sid, recording_id=rid,
        provider="openai", operation_kind="transcription",
        minimum_data_manifest={}, idempotency_key="corpus-test-key")


@pytest.mark.parametrize("user_id", [SPEAKER, None], ids=["user", "guest"])
def test_an_ordinary_or_guest_take_is_never_authorized_by_the_corpus_basis(
        enforce, fake, user_id):
    """A Take of a user, or of a guest (no account yet), goes the Phase-1 way
    (its owner's receipt) and is refused there; the corpus basis is never
    asked. Asked directly, it refuses both registration and permit."""
    sid, rid = _owned_take(fake, source="audit_upload", user_id=user_id)
    with pytest.raises(ProcessingAuthorizationError) as refused:
        _process(fake, sid, rid, user_id)
    assert refused.value.code == "PROCESSING_AUTHORIZATION_REQUIRED"
    assert _Whisper.calls == []
    assert not _names(enforce) & _CORPUS_RPCS

    from services.processing_authorization import register_corpus_import
    with pytest.raises(ProcessingAuthorizationError) as refused:
        register_corpus_import(fake, session_id=sid, recording_id=rid)
    assert refused.value.code == "CORPUS_SOURCE_NOT_IMPORT"
    with pytest.raises(ProcessingAuthorizationError) as refused:
        _corpus_permit(fake, sid, rid)
    assert refused.value.code == "CORPUS_IMPORT_UNREGISTERED"
    assert enforce.permits == []


# ── CO3 A: a coach's judgement on a clip they imported counts ──────────────


# ── 0435: the corpus basis, in the database ────────────────────────────────


# ── 0434: a TRUNCATE cannot re-shuffle the splits either ───────────────────
