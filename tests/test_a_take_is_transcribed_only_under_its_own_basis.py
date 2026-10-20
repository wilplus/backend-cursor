"""
STORY    As the founder, I want an imported corpus clip transcribed only under
         my corpus basis (N58), and a speaker's or guest's Take never under
         it, so that no Take is processed without its own lawful basis
         (processing authorization on the record -> process step).
OUTCOME
  O1  An ordinary or guest Take goes the Phase-1 way (its owner's receipt);
      refused there, the transcriber is never called and the corpus basis
      is never asked.
  O2  An import goes the corpus way: one corpus permit for the session, the
      transcriber is called, its events are recorded, and no Phase-1 permit
      is ever asked for.
  O3  When the database refuses the corpus permit, or names any basis but
      N58, the import is refused with that code and the transcriber is
      never called.
PROVES   O1 -> test_an_ordinary_or_guest_take_is_never_authorized_by_the_corpus_basis
         O2 -> test_an_import_is_transcribed_under_the_corpus_basis
         O3 -> test_a_refused_corpus_permit_stops_the_import
WHY      Founder 2026-10-07, CO2, decisions log N58. The database client is
         a stand-in that only answers each RPC; the SQL rules themselves
         (who is an import, which basis is in force) run for real in
         tests/test_a_corpus_import_is_processed_under_the_founders_basis_postgres.py.
         Was tests/test_corpus_queue_end_to_end.py.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from services.processing_authorization import ProcessingAuthorizationError

SPEAKER = "88888888-8888-4888-8888-888888888888"
ACQUIRER = "55555555-5555-4555-8555-555555555555"
BASIS_ID = "0d580435-5858-4058-8058-000000000058"
_CORPUS_RPCS = {"register_corpus_import_v1", "issue_corpus_provider_permit_v1",
                "record_corpus_provider_operation_v1"}
_PHASE1_PERMIT = "issue_phase1_provider_permit_v1"
_WORDS = "we built the plan together and every team kept its promise".split()


class _Result:
    def __init__(self, data):
        self.data = data


class _Exec:
    def __init__(self, run):
        self.run = run

    def execute(self):
        return _Result(self.run())


class _Client:
    """Answers each RPC as the database would for the case under test:
    the Phase-1 permit writer refuses (no receipt here); the corpus permit
    writer answers `corpus_permit` (a row, or an error to raise)."""

    def __init__(self):
        self.rpcs: list = []
        self.corpus_permit = None

    def table(self, _name):
        class _Empty:
            def __getattr__(self, _attr):
                return lambda *_a, **_k: self

            def execute(self):
                return _Result([])
        return _Empty()

    def rpc(self, name, params):
        self.rpcs.append((name, dict(params)))
        return _Exec(lambda: self._answer(name, params))

    def _answer(self, name, params):
        if name == "resolve_phase1_acquisition_principal_v1":
            return params["p_product_owner_principal_id"]
        if name == _PHASE1_PERMIT:
            raise RuntimeError("PROCESSING_AUTHORIZATION_REQUIRED")
        if name == "issue_corpus_provider_permit_v1":
            if isinstance(self.corpus_permit, Exception):
                raise self.corpus_permit
            return dict(self.corpus_permit, session_id=params["p_session_id"])
        if name == "record_corpus_provider_operation_v1":
            return str(uuid.uuid4())
        raise AssertionError(f"unexpected rpc {name}")

    def names(self) -> list:
        return [name for name, _ in self.rpcs]


class _Db:
    def __init__(self):
        self.sessions: dict = {}
        self.client = _Client()

    def v2_get_session_by_id(self, sid):
        return self.sessions.get(str(sid))

    def set_recording_transcription_language_if_missing(self, _rid, language):
        return language


class _Whisper:
    """The transcription provider, as the permitted adapter reaches it."""

    calls: list = []

    def __init__(self):
        self.client = object()

    def transcribe_audio(self, _audio, filename, **kwargs):
        _Whisper.calls.append((filename, kwargs.get("usage_session_id")))
        words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
                 for i, w in enumerate(_WORDS)]
        return {"segments": [{"start": 0.0, "end": 5.0, "text": " ".join(_WORDS)}],
                "words": words, "language": "en", "duration": 5.0}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    store = _Db()
    _Whisper.calls = []
    with patch("services.db.db", store), \
            patch("services.openai_service.OpenAIService", _Whisper), \
            patch("services.token_account.charge"):
        yield store


def _transcribe_only(**kwargs):
    """The analysis body cut to its REAL transcription stage (adapter,
    permit, provider call); the rest of the pipeline is not the subject."""
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
    return {"words": len(state.words_all or [])}


def _process(sid: str, rid: str, user_id=None):
    from services.lab_recording import process_lab_recording
    with patch("services.lab_recording._process_lab_recording_impl",
               side_effect=_transcribe_only):
        return process_lab_recording(
            session_id=sid, user_id=user_id, recording_id=rid,
            audio_bytes=b"x", filename="take.webm", session_context={},
            parent_audio_url="s3://b/k")


def _import(fake: _Db) -> tuple:
    sid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    fake.sessions[sid] = {"id": sid, "source": "training_import", "user_id": None,
                          "owner_principal_id": None, "project_id": None,
                          "recording_id": rid}
    return sid, rid


@pytest.mark.parametrize("user_id", [SPEAKER, None], ids=["user", "guest"])
def test_an_ordinary_or_guest_take_is_never_authorized_by_the_corpus_basis(
        fake, user_id):
    sid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    fake.sessions[sid] = {"id": sid, "source": "audit_upload", "user_id": user_id,
                          "owner_principal_id": ACQUIRER,
                          "project_id": str(uuid.uuid4()), "recording_id": rid}
    with pytest.raises(ProcessingAuthorizationError) as refused:
        _process(sid, rid, user_id)
    assert refused.value.code == "PROCESSING_AUTHORIZATION_REQUIRED"
    assert _PHASE1_PERMIT in fake.client.names()
    assert not set(fake.client.names()) & _CORPUS_RPCS
    assert _Whisper.calls == []


def test_an_import_is_transcribed_under_the_corpus_basis(fake):
    sid, rid = _import(fake)
    fake.client.corpus_permit = {
        "permit_id": "permit-1", "provider": "openai",
        "operation_kind": "transcription", "expires_at": "2999-01-01T00:00:00+00:00",
        "basis_id": BASIS_ID, "basis_decision_ref": "N58", "recording_id": rid}
    assert _process(sid, rid)["words"] == len(_WORDS)
    assert len(_Whisper.calls) == 1
    permits = [p for n, p in fake.client.rpcs if n == "issue_corpus_provider_permit_v1"]
    assert [(p["p_session_id"], p["p_recording_id"], p["p_operation_kind"])
            for p in permits] == [(sid, rid, "transcription")]
    events = [p["p_event_kind"] for n, p in fake.client.rpcs
              if n == "record_corpus_provider_operation_v1"]
    assert events == ["started", "completed"]
    assert _PHASE1_PERMIT not in fake.client.names()


@pytest.mark.parametrize("answer, code", [
    (RuntimeError("CORPUS_SESSION_HAS_OWNER"), "CORPUS_SESSION_HAS_OWNER"),
    ({"permit_id": "permit-2", "expires_at": "2999-01-01T00:00:00+00:00",
      "basis_decision_ref": "N99"}, "CORPUS_BASIS_ABSENT"),
], ids=["database-refuses", "another-basis"])
def test_a_refused_corpus_permit_stops_the_import(fake, answer, code):
    sid, rid = _import(fake)
    fake.client.corpus_permit = answer
    with pytest.raises(ProcessingAuthorizationError) as refused:
        _process(sid, rid)
    assert refused.value.code == code
    assert _Whisper.calls == []
    assert _PHASE1_PERMIT not in fake.client.names()
