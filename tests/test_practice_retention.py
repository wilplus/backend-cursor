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
from datetime import datetime, timedelta, timezone

from services.practice_retention import (
    RETENTION_DAYS,
    cutoff,
    expired_attempts,
    sweep_practice_retention,
)


def attempt(attempt_id: str, **over) -> dict:
    return {"id": attempt_id, "kept": False, **over}


CLOSED = {"id": "p1", "status": "completed", "selected_attempt_id": "a2"}


class TheRuleTests(unittest.TestCase):
    """expired_attempts is pure, so the promise can be read without a database."""

    def test_it_takes_the_attempts_nobody_chose(self):
        got = expired_attempts(
            CLOSED, [attempt("a1"), attempt("a2"), attempt("a3")], [])
        self.assertEqual([a["id"] for a in got], ["a1", "a3"])

    def test_it_never_takes_the_one_they_chose(self):
        got = expired_attempts(CLOSED, [attempt("a2")], [])
        self.assertEqual(got, [])

    def test_it_never_takes_one_they_kept(self):
        got = expired_attempts(CLOSED, [attempt("a1", kept=True)], [])
        self.assertEqual(got, [])

    def test_it_never_takes_one_the_album_admitted(self):
        # Album membership is Machine Yes + User Yes + Coach Yes about THE
        # EXACT recording (L3). Delete the clip and the Album lists something
        # that no longer exists.
        got = expired_attempts(CLOSED, [attempt("a1"), attempt("a3")], ["a1"])
        self.assertEqual([a["id"] for a in got], ["a3"])

    def test_it_never_touches_an_open_practice(self):
        # The speaker is still using it.
        for status in ("open", "", None):
            got = expired_attempts(
                {"id": "p", "status": status, "selected_attempt_id": None},
                [attempt("a1")], [])
            self.assertEqual(got, [], status)

    def test_a_dismissed_practice_is_still_closed(self):
        got = expired_attempts(
            {"id": "p", "status": "dismissed", "selected_attempt_id": None},
            [attempt("a1")], [])
        self.assertEqual([a["id"] for a in got], ["a1"])

    def test_it_returns_nothing_for_anything_it_does_not_understand(self):
        # A sweep that deletes on a misreading is worse than one that deletes
        # nothing.
        for practice in (None, [], "x", 3, {}):
            self.assertEqual(expired_attempts(practice, [attempt("a")], []), [])
        for attempts in (None, "x", 3, {}):
            self.assertEqual(expired_attempts(CLOSED, attempts, []), [])
        self.assertEqual(
            expired_attempts(CLOSED, [None, "x", {}, attempt("a1")], []),
            [attempt("a1")])


class TheCutoffTests(unittest.TestCase):
    def test_it_is_the_founders_thirty_days(self):
        self.assertEqual(RETENTION_DAYS, 30)

    def test_the_cutoff_is_thirty_days_back(self):
        now = datetime(2026, 9, 16, tzinfo=timezone.utc)
        self.assertEqual(cutoff(now), (now - timedelta(days=30)).isoformat())


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
    def test_it_deletes_the_recording_then_the_row(self):
        db = _Db()
        tally = sweep_practice_retention(database=db)
        self.assertEqual(db.objects_deleted, ["a1", "a3"])
        self.assertEqual(db.rows_deleted, ["a1", "a3"])
        self.assertEqual(tally["attempts"], 2)
        self.assertEqual(tally["objects"], 2)
        self.assertEqual(tally["failed"], 0)

    def test_a_recording_it_cannot_delete_keeps_its_row(self):
        # A deleted row whose file survives is the exact hole 0334 closed. The
        # row is how the next sweep finds the file again.
        db = _Db(storage_ok=False)
        tally = sweep_practice_retention(database=db)
        self.assertEqual(db.rows_deleted, [])
        self.assertEqual(tally["attempts"], 0)
        self.assertEqual(tally["failed"], 2)

    def test_it_asks_the_album_about_a_bounded_set_of_attempts(self):
        # Not "every album row in the system". An unfiltered read can be
        # silently truncated by a default row cap, and a truncated protected
        # set UNDER-protects — the one direction this must never fail in.
        db = _Db()
        sweep_practice_retention(database=db)
        self.assertEqual(sorted(db.album_asked_for), ["a1", "a2", "a3"])

    def test_a_failed_album_read_deletes_NOTHING_for_that_practice(self):
        # The protected set is what stops the sweep taking an admitted clip.
        # Treating a failed read as "protect nothing" would widen what gets
        # deleted at the worst possible moment.
        db = _Db(album_raises=True)
        tally = sweep_practice_retention(database=db)
        self.assertEqual(db.objects_deleted, [])
        self.assertEqual(db.rows_deleted, [])
        self.assertEqual(tally["failed"], 1)

    def test_a_failed_practice_list_is_a_quiet_no_op(self):
        class Broken(_Db):
            def list_closed_practices_before(self, cutoff_iso, limit):
                raise RuntimeError("down")

        tally = sweep_practice_retention(database=Broken())
        self.assertEqual(tally, {"practices": 0, "attempts": 0,
                                 "objects": 0, "failed": 0})

    def test_nothing_to_do_is_not_an_error(self):
        db = _Db(practices=[])
        self.assertEqual(sweep_practice_retention(database=db)["attempts"], 0)


class TheClockStartsWhenThePracticeClosedTests(unittest.TestCase):
    """The 30 days run from the close, not from the last touch.

    `updated_at` moves whenever anything writes the row — a coach attaching an
    explanation video to a finished practice would restart the speaker's
    clock, and a row touched every few weeks would never age out at all.
    """

    def test_the_query_keys_on_closed_at(self):
        source = open("services/db.py", encoding="utf-8").read()
        start = source.index("def list_closed_practices_before")
        block = source[start:start + 1400]
        body = block[block.index("try:"):]
        self.assertIn('.lt("closed_at"', body)
        self.assertNotIn('.lt("updated_at"', body)

    def test_the_index_it_needs_exists(self):
        sql = open("migrations/add_practice_audio_objects.sql",
                   encoding="utf-8").read()
        self.assertIn("confident_voice_practice_closed_at_idx", sql)


class ItIsActuallyScheduledTests(unittest.TestCase):
    """A sweep nothing calls is a promise that never runs.

    This module was written, tested and very nearly shipped with no caller at
    all — every test above passed while the 30-day promise was dead code. The
    other sweeps are recovery work, so a missed run only delays something;
    this one is the only thing that deletes a recording because we said we
    would not keep it, and a missed run is the product not doing what it says.
    """

    def test_the_queue_sweeper_runs_it(self):
        source = open("services/pipeline_jobs.py", encoding="utf-8").read()
        self.assertIn(
            "from services.practice_retention import sweep_practice_retention",
            source)
        self.assertIn("sweep_practice_retention(", source)

    def test_it_cannot_break_job_recovery(self):
        # Every pass in that chain is best-effort on purpose: a newer, softer
        # concern must never take down the sweeper that unsticks recordings.
        source = open("services/pipeline_jobs.py", encoding="utf-8").read()
        start = source.index("from services.practice_retention import")
        self.assertIn("except Exception", source[start:start + 900])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
