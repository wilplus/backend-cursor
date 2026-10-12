"""A practice recording a speaker cannot delete is the bug this closes.

Found 2026-09-16 while preparing the phase-1 reclassification. The practice
route uploaded a speaker's attempt to R2 and inserted the attempt row, and
NOTHING recorded that the file existed. services/data_purge.py deletes
storage only for objects it finds in processing_audio_objects,
processing_orphan_objects and (since 0334) processing_practice_objects — so
purging a speaker removed their practice rows and left the recordings in the
bucket, unreferenced.

WHAT THIS PINS DOWN:
  * an attempt and its registration land together, or neither does. The gap
    existed because they were two things a caller could do one of;
  * a missing principal refuses the attempt BEFORE anything is written — no
    principal means no FK, means no registry row, means audio the purge
    cannot reach;
  * the purge produces a real deletion target for a practice recording, of a
    kind that resolve_targets actually executes. A target_kind of
    "storage_object" would have been an inventory line that deletes nothing,
    which is the trap this design avoided.

Run: python3 -m unittest tests.test_practice_audio_objects
"""
from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from services import practice_audio_objects as pao

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
        self.registered.append(row)
        return dict(row)

    def delete_confident_voice_practice_attempt(self, attempt_id):
        self.deleted.append(attempt_id)
        return True


def _record(db, row=None, **over):
    kwargs = dict(practice=PRACTICE, bucket="willab-audio", audio_bytes=AUDIO)
    kwargs.update(over)
    with patch("services.processing_authorization.ProcessingAuthorizationService",
               return_value=_Auth()):
        return pao.record_practice_attempt(
            db, dict(ROW if row is None else row), **kwargs)


class RecordPracticeAttemptTests(unittest.TestCase):


    def test_it_falls_back_to_the_project_when_the_take_has_no_owner(self):
        # THE 95% CASE, measured on production 2026-09-16: 348 of 367 user
        # takes have a NULL v2_sessions.owner_principal_id. That column is a
        # denormalised copy; projects.owner_principal_id is NOT NULL and is
        # what the recording path has always resolved from. Reading only the
        # copy meant refusing to save a retake for almost every speaker — the
        # refusal working exactly as designed, on an answer that was never
        # authoritative.
        db = _Db(principal="")
        saved = _record(db)
        self.assertIsNotNone(saved)
        self.assertEqual(
            db.registered[0]["acquisition_principal_id"], "project-principal")


class ARefusedSaveLeavesNoRecordingTests(unittest.TestCase):
    """F1 Repair Plan Phase 4: the route uploads before it records, and the
    orphan sweep never sees this path, so every refusal deletes the object
    it was handed -- verified by its bytes -- and a saved attempt never."""

    def _run(self, db, **over):
        with patch("services.lab_audio_storage."
                   "delete_verified_lab_audio_object",
                   return_value=True) as delete:
            result = _record(db, **over)
        return result, delete

    def _assert_deleted(self, delete):
        delete.assert_called_once_with(
            ROW["storage_path"], bucket="willab-audio", storage_provider="r2",
            expected_sha256=hashlib.sha256(AUDIO).hexdigest())


    def test_no_principal_deletes_the_recording(self):
        saved, delete = self._run(_Db(principal="", project_principal=""))
        self.assertIsNone(saved)
        self._assert_deleted(delete)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
