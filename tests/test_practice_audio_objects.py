"""
STORY    As a speaker who asks for deletion, I want every practice recording
         I make to be registered for deletion, and refused saves to leave
         nothing behind, so that deleting my data really removes my voice.
         (Deletion.)
OUTCOME
  O1  A saved attempt and its recording's registration land together (the
      registration names the exact bytes and the owner); the upload stays.
  O2  If either half is refused, neither stands: the attempt is rolled back
      and the uploaded recording is deleted, verified by its bytes.
  O3  With no owner principal the save is refused before anything is
      written, and the upload is deleted; the take's missing owner falls back
      to the project's.
  O4  The purge turns the registration into a storage target it executes
      (r2_object at the same bucket, key and hash).
PROVES   O1 -> test_a_saved_attempt_registers_its_recording
         O2 -> test_a_refused_half_leaves_neither_attempt_nor_recording
         O3 -> test_no_principal_deletes_the_recording
               test_it_falls_back_to_the_project_when_the_take_has_no_owner
         O4 -> test_the_purge_finds_the_registered_recording
WHY      2026-09-16: practice audio was uploaded with nothing recording that it
         existed, so a purge removed the rows and left the voice in the bucket.
"""
from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from services import practice_audio_objects as pao
from services.data_purge import DataPurgeOrchestrator

PRACTICE = {
    "id": "11111111-1111-4111-8111-111111111111",
    "take_session_id": "22222222-2222-4222-8222-222222222222",
    "owner_user_id": "44444444-4444-4444-8444-444444444444",
}
ROW = {"practice_id": PRACTICE["id"], "attempt_index": 1,
       "storage_path": "confidence-practice/u/p/1-abc.webm",
       "mime_type": "audio/webm"}
AUDIO = b"some audio bytes"


class _Auth:
    def __init__(self, enforced=False):
        self.enforced = enforced

    def resolve_acquisition_principal(self, owner, *, user_id=None,
                                      recording_id=None):
        return "resolved-principal"


class _Db:
    def __init__(self, *, principal="owner-principal", insert_ok=True,
                 register_ok=True, project_principal="project-principal"):
        self.principal = principal
        # projects.owner_principal_id is NOT NULL, so the project's answer is
        # always there; the take's copy is the one that is usually missing.
        self.project_principal = project_principal
        self.insert_ok = insert_ok
        self.register_ok = register_ok
        self.registered: list[dict] = []
        self.deleted: list[str] = []
        self.attempts: list[dict] = []

    def v2_get_session_by_id(self, session_id):
        return {
            "id": session_id,
            "owner_principal_id": self.principal,
            "project_id": "33333333-3333-4333-8333-333333333333",
        }

    def get_project_owner_principal(self, project_id):
        return self.project_principal

    def insert_confident_voice_practice_attempt(self, row):
        if not self.insert_ok:
            return None
        self.attempts.append(row)
        return {"id": "attempt-1", **row}

    def insert_practice_audio_object(self, row):
        if not self.register_ok:
            return None
        self.registered.append({"id": f"object-{len(self.registered) + 1}", **row})
        return dict(row)

    def delete_confident_voice_practice_attempt(self, attempt_id):
        self.deleted.append(attempt_id)
        return True


def _record(db):
    """Save one attempt; returns (saved, the deletes of the uploaded object)."""
    with patch("services.processing_authorization.ProcessingAuthorizationService",
               return_value=_Auth()), \
            patch("services.lab_audio_storage.delete_verified_lab_audio_object",
                  return_value=True) as delete:
        saved = pao.record_practice_attempt(
            db, dict(ROW), practice=PRACTICE, bucket="willab-audio", audio_bytes=AUDIO)
    return saved, delete


UPLOAD_DELETED = [((ROW["storage_path"],), {
    "bucket": "willab-audio", "storage_provider": "r2",
    "expected_sha256": hashlib.sha256(AUDIO).hexdigest()})]


def _deletes(delete):
    return [(c.args, c.kwargs) for c in delete.call_args_list]


def test_a_saved_attempt_registers_its_recording():
    db = _Db()
    saved, delete = _record(db)
    assert saved["id"] == "attempt-1" and db.attempts == [ROW]
    assert [{k: r[k] for k in ("acquisition_principal_id", "practice_attempt_id",
                               "storage_provider", "bucket", "object_key",
                               "exact_bytes_sha256")} for r in db.registered] == [{
        "acquisition_principal_id": "owner-principal", "practice_attempt_id": "attempt-1",
        "storage_provider": "r2", "bucket": "willab-audio", "object_key": ROW["storage_path"],
        "exact_bytes_sha256": hashlib.sha256(AUDIO).hexdigest()}]
    assert _deletes(delete) == [] and db.deleted == []


@pytest.mark.parametrize("refused", ["insert", "register"])
def test_a_refused_half_leaves_neither_attempt_nor_recording(refused):
    db = _Db(insert_ok=refused != "insert", register_ok=refused != "register")
    saved, delete = _record(db)
    assert saved is None and db.registered == []
    assert db.deleted == (["attempt-1"] if refused == "register" else [])
    assert _deletes(delete) == UPLOAD_DELETED


def test_no_principal_deletes_the_recording():
    db = _Db(principal="", project_principal="")
    saved, delete = _record(db)
    assert saved is None and db.attempts == [] and db.registered == []
    assert _deletes(delete) == UPLOAD_DELETED


def test_it_falls_back_to_the_project_when_the_take_has_no_owner():
    # Production 2026-09-16: 348 of 367 takes have a NULL
    # v2_sessions.owner_principal_id; projects.owner_principal_id is NOT NULL.
    db = _Db(principal="")
    saved, _ = _record(db)
    assert saved is not None
    assert db.registered[0]["acquisition_principal_id"] == "project-principal"


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _columns):
        return self

    def eq(self, column, value):
        return _Query([r for r in self.rows if str(r.get(column)) == str(value)])

    def in_(self, column, values):
        return _Query([r for r in self.rows if str(r.get(column)) in set(map(str, values))])

    def limit(self, _n):
        return self

    def range(self, start, end):
        return _Query(self.rows[start:end + 1])

    def execute(self):
        return type("Result", (), {"data": self.rows})()


class _PurgeClient:
    """PostgREST as the orchestrator reads it: the request, the catalog, the
    subject graph and the practice registry."""

    def __init__(self, principal, objects):
        self.tables = {
            "data_purge_requests": [{"id": "req-1", "acquisition_principal_id": principal,
                                     "trigger_kind": "account_deletion", "state": "requested"}],
            "processing_practice_objects": [{**o, "deleted_at": None} for o in objects],
        }
        graph = {k: [] for k in (
            "user_ids", "project_ids", "take_ids", "recording_ids", "snippet_ids",
            "permit_ids", "job_ids", "speaker_ids", "practice_ids", "practice_attempt_ids",
            "exercise_audio_lineage_ids", "exercise_blind_packet_ids", "delivery_job_ids",
            "unresolved_legacy_take_ids")}
        self.rpcs = {
            "audit_phase1_purge_catalog_v1": [{
                "catalog_sha256": "c" * 64,
                "existing_allowlisted_relations": ["processing_practice_objects"]}],
            "resolve_phase1_purge_subject_graph_v3": [{**graph, "principal_ids": [principal]}],
        }

    def table(self, name):
        return _Query(self.tables.get(name, []))

    def rpc(self, name, _args):
        return _Query(self.rpcs[name])


def test_the_purge_finds_the_registered_recording():
    db = _Db()
    _record(db)
    client = _PurgeClient("owner-principal", db.registered)
    inventory = DataPurgeOrchestrator(type("Database", (), {"client": client})()) \
        .build_inventory("req-1")
    storage = [t for t in inventory["targets"] if t.target_ref.startswith("practice-object:")]
    assert [(t.target_kind, t.initial_match_count) for t in storage] == [("r2_object", 1)]
    meta = storage[0].metadata
    assert (meta["bucket"], meta["key"], meta["sha256"], meta["source_relation"]) == (
        "willab-audio", ROW["storage_path"], hashlib.sha256(AUDIO).hexdigest(),
        "processing_practice_objects")
