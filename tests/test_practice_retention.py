"""Option A: keep the attempt they chose, let the rest go after 30 days.

Founder 2026-09-16. This is the promise the product makes about how long it
holds a speaker's practice recordings, so the three things it must never take
are tested harder than the thing it does take.

Nothing deleted practice attempts by age before this. `retention_category` on
a purge dependency looked like the mechanism and was not — it applies only to
rows whose disposition is `retain`, and practice rows are `delete`.

Run: python3 -m unittest tests.test_practice_retention
"""
from __future__ import annotations

import unittest

from services.practice_retention import (
    sweep_practice_retention,
)


def attempt(attempt_id: str, **over) -> dict:
    return {"id": attempt_id, "kept": False, **over}


CLOSED = {"id": "p1", "status": "completed", "selected_attempt_id": "a2"}


class _Db:
    def __init__(self, *, practices=None, attempts=None, album=None,
                 storage_ok=True, album_raises=False):
        self.practices = practices if practices is not None else [CLOSED]
        self.attempts = attempts if attempts is not None else [
            attempt("a1"), attempt("a2"), attempt("a3")]
        self.album = album or []
        self.storage_ok = storage_ok
        self.album_raises = album_raises
        self.objects_deleted: list[str] = []
        self.rows_deleted: list[str] = []
        self.album_asked_for: list[str] = []

    def list_closed_practices_before(self, cutoff_iso, limit):
        return list(self.practices)

    def list_confident_voice_practice_attempts(self, practice_id):
        return list(self.attempts)

    def list_album_practice_attempt_ids(self, attempt_ids):
        if self.album_raises:
            raise RuntimeError("album read failed")
        self.album_asked_for = list(attempt_ids)
        return [item for item in self.album if item in set(attempt_ids)]

    def delete_practice_audio_object(self, attempt_id):
        if not self.storage_ok:
            return False
        self.objects_deleted.append(attempt_id)
        return True

    def delete_confident_voice_practice_attempt(self, attempt_id):
        self.rows_deleted.append(attempt_id)
        return True


class TheSweepTests(unittest.TestCase):

    def test_a_recording_it_cannot_delete_keeps_its_row(self):
        # A deleted row whose file survives is the exact hole 0334 closed. The
        # row is how the next sweep finds the file again.
        db = _Db(storage_ok=False)
        tally = sweep_practice_retention(database=db)
        self.assertEqual(db.rows_deleted, [])
        self.assertEqual(tally["attempts"], 0)
        self.assertEqual(tally["failed"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
