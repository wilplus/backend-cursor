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
    def test_the_attempt_and_its_recording_land_together(self):
        db = _Db()
        saved = _record(db)
        self.assertEqual(saved["id"], "attempt-1")
        self.assertEqual(len(db.registered), 1)
        registered = db.registered[0]
        self.assertEqual(registered["practice_attempt_id"], "attempt-1")
        self.assertEqual(registered["object_key"], ROW["storage_path"])
        self.assertEqual(registered["bucket"], "willab-audio")
        self.assertEqual(registered["storage_provider"], "r2")

    def test_it_records_the_exact_bytes_so_the_object_is_identifiable(self):
        db = _Db()
        _record(db)
        self.assertEqual(db.registered[0]["exact_bytes_sha256"],
                         hashlib.sha256(AUDIO).hexdigest())
        self.assertEqual(db.registered[0]["byte_size"], len(AUDIO))

    def test_a_failed_registration_rolls_the_attempt_back(self):
        # An attempt whose audio the purge cannot see is the exact state this
        # module exists to prevent. Losing one retake is the smaller harm.
        db = _Db(register_ok=False)
        self.assertIsNone(_record(db))
        self.assertEqual(db.deleted, ["attempt-1"])

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

    def test_no_principal_anywhere_still_refuses_before_anything_is_written(self):
        # The honest floor: when neither the take nor its project can name an
        # owner, there is no FK, so no registry row, so audio the purge cannot
        # reach. Refuse before writing.
        db = _Db(principal="", project_principal="")
        self.assertIsNone(_record(db))
        self.assertEqual(db.attempts, [])
        self.assertEqual(db.registered, [])

    def test_the_registration_points_at_the_row_s_own_object(self):
        # The key and the content type are read from the row, never passed
        # beside it. As two parameters, a caller could have registered one key
        # while the attempt recorded another — the purge would delete the
        # registered one and leave the real recording behind, which is this
        # module's own bug in a new shape.
        db = _Db()
        _record(db, row={**ROW, "storage_path": "practice/other.m4a",
                         "mime_type": "audio/mp4"})
        self.assertEqual(db.registered[0]["object_key"], "practice/other.m4a")
        self.assertEqual(db.registered[0]["content_type"], "audio/mp4")
        self.assertEqual(db.attempts[0]["storage_path"], "practice/other.m4a")

    def test_a_row_with_no_content_type_still_registers(self):
        db = _Db()
        self.assertIsNotNone(_record(db, row={**ROW, "mime_type": ""}))
        self.assertEqual(db.registered[0]["content_type"],
                         "application/octet-stream")

    def test_missing_storage_coordinates_roll_back_too(self):
        for row, over in (({}, {"bucket": None}), ({}, {"bucket": ""}),
                          ({"storage_path": ""}, {}), ({}, {"audio_bytes": b""})):
            db = _Db()
            self.assertIsNone(_record(db, row={**ROW, **row}, **over), (row, over))
            self.assertEqual(db.deleted, ["attempt-1"], (row, over))

    def test_a_failed_insert_registers_nothing(self):
        db = _Db(insert_ok=False)
        self.assertIsNone(_record(db))
        self.assertEqual(db.registered, [])
        self.assertEqual(db.deleted, [])

    def test_junk_never_throws(self):
        db = _Db()
        for practice in (None, [], "x", {}):
            with patch(
                "services.processing_authorization."
                "ProcessingAuthorizationService", return_value=_Auth(),
            ):
                self.assertIsNone(pao.record_practice_attempt(
                    db, dict(ROW), practice=practice, bucket="b",
                    audio_bytes=AUDIO))


class PurgeReachesPracticeAudioTests(unittest.TestCase):
    """Source fences on the half that does the deleting."""

    def setUp(self):
        self.source = open("services/data_purge.py", encoding="utf-8").read()

    def test_the_purge_reads_the_practice_registry(self):
        self.assertIn('"processing_practice_objects"', self.source)
        self.assertIn("practice-object:", self.source)

    def test_it_emits_a_kind_that_is_actually_deleted(self):
        # resolve_targets only deletes r2_object / supabase_object. A
        # PurgeDependency with target_kind "storage_object" would have been an
        # inventory line that deletes nothing — the trap this avoided.
        start = self.source.index('"processing_practice_objects"')
        block = self.source[start:start + 1200]
        self.assertIn('"r2_object" if provider == "r2" else "supabase_object"',
                      block)
        self.assertIn('and row.get("target_kind") in ("r2_object", "supabase_object")',
                      self.source)

    def test_an_already_purged_object_is_not_deleted_twice(self):
        start = self.source.index('"processing_practice_objects"')
        block = self.source[start:start + 1200]
        self.assertIn('already_purged = row.get("deleted_at") is not None', block)

    def test_the_migration_is_registered_and_additive(self):
        manifest = open("migrations/manifest.txt", encoding="utf-8").read()
        self.assertIn("add_practice_audio_objects.sql", manifest)
        sql = open("migrations/add_practice_audio_objects.sql",
                   encoding="utf-8").read()
        self.assertIn("CREATE TABLE IF NOT EXISTS public.processing_practice_objects",
                      sql)
        # Additive only: it must not touch the tables it deliberately did not
        # reuse, and must never drop anything.
        self.assertNotIn("ALTER TABLE public.processing_audio_objects", sql)
        self.assertNotIn("DROP", sql.upper())

    def test_one_registry_row_per_attempt_and_per_object(self):
        sql = open("migrations/add_practice_audio_objects.sql",
                   encoding="utf-8").read()
        self.assertIn("UNIQUE (storage_provider, bucket, object_key)", sql)
        self.assertIn("UNIQUE (practice_attempt_id)", sql)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
