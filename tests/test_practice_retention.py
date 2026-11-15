"""
STORY    As a speaker, I want the practice attempt I chose (and any I saved)
         kept, and the rest removed 30 days after the practice closed, so
         that my storage matches the promise. (Deletion.)
OUTCOME
  O1  Thirty days after a practice closed, every attempt it no longer
      promises to keep is deleted: the recording first, then its row.
  O2  Never taken: the attempt they chose, an attempt they saved, an attempt
      the Voice Album admitted, anything in a practice still open.
  O3  If the Album cannot be read, nothing in that practice is deleted.
  O4  A recording that cannot be deleted keeps its row, so a later sweep
      finds it again.
  O5  Every closed practice is reached, however many there are: one that
      was looked at waits a day before it is read again.
PROVES   O1 -> test_after_30_days_the_rest_go_file_first
         O2 -> test_the_chosen_saved_and_album_attempts_stay
               test_an_open_practice_is_never_swept
         O3 -> test_an_unreadable_album_deletes_nothing
         O4 -> test_a_recording_it_cannot_delete_keeps_its_row
         O5 -> test_a_recording_beyond_the_first_fifty_is_deleted
               test_a_practice_looked_at_is_not_read_again_for_a_day
WHY      Founder 2026-09-16, option A ("keep only the attempt they chose;
         delete the rest after 30 days"). Nothing deleted by age before this.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.practice_retention import sweep_practice_retention

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
CLOSED = {"id": "p1", "status": "completed", "selected_attempt_id": "a2"}


def attempt(attempt_id: str, **over) -> dict:
    return {"id": attempt_id, "kept": False, **over}


class _Db:
    """The practice table as the sweep sees it: closed practices past the
    cutoff, those never looked at first, then those last looked at before
    `checked_before`, never more than `limit`."""

    def __init__(self, *, practices=None, attempts=None, album=None,
                 storage_ok=True, album_raises=False):
        self.practices = [dict(row) for row in (
            practices if practices is not None else [CLOSED])]
        shared = attempts if attempts is not None else [
            attempt("a1"), attempt("a2"), attempt("a3")]
        self.attempts = attempts if isinstance(attempts, dict) else {
            row["id"]: list(shared) for row in self.practices}
        self.album = album or []
        self.storage_ok = storage_ok
        self.album_raises = album_raises
        self.events: list[tuple[str, str]] = []
        self.cutoffs: list[str] = []
        self.reads: list[str] = []

    def list_closed_practices_before(self, cutoff_iso, limit, checked_before=None):
        self.cutoffs.append(cutoff_iso)
        closed = [row for row in self.practices if row.get("status") != "open"]
        never = [row for row in closed if not row.get("retention_checked_at")]
        again = sorted(
            (row for row in closed if row.get("retention_checked_at")
             and checked_before and row["retention_checked_at"] < checked_before),
            key=lambda row: row["retention_checked_at"])
        return (never + again)[:limit]

    def mark_practice_retention_checked(self, practice_id, checked_at_iso):
        for row in self.practices:
            if row["id"] == practice_id:
                row["retention_checked_at"] = checked_at_iso
        return True

    def list_confident_voice_practice_attempts(self, practice_id):
        self.reads.append(practice_id)
        return list(self.attempts.get(practice_id, []))

    def list_album_practice_attempt_ids(self, attempt_ids):
        if self.album_raises:
            raise RuntimeError("album read failed")
        return [item for item in self.album if item in set(attempt_ids)]

    def delete_practice_audio_object(self, attempt_id):
        if not self.storage_ok:
            return False
        self.events.append(("file", attempt_id))
        return True

    def delete_confident_voice_practice_attempt(self, attempt_id):
        self.events.append(("row", attempt_id))
        for rows in self.attempts.values():
            rows[:] = [row for row in rows if row["id"] != attempt_id]
        return True


def _sweep(db, now=NOW):
    return sweep_practice_retention(database=db, now=now)


def test_after_30_days_the_rest_go_file_first():
    db = _Db()
    tally = _sweep(db)
    assert db.cutoffs == [(NOW - timedelta(days=30)).isoformat()]
    assert db.events == [("file", "a1"), ("row", "a1"), ("file", "a3"), ("row", "a3")]
    assert (tally["attempts"], tally["failed"]) == (2, 0)


def test_the_chosen_saved_and_album_attempts_stay():
    db = _Db(attempts=[attempt("a1"), attempt("a2"), attempt("a3", kept=True),
                       attempt("a4"), attempt("a5")], album=["a4"])
    _sweep(db)
    gone = {a for kind, a in db.events if kind == "row"}
    assert gone == {"a1", "a5"}  # a2 chosen, a3 saved, a4 in the Album


def test_an_open_practice_is_never_swept():
    db = _Db(practices=[{**CLOSED, "status": "open"}, {**CLOSED, "status": None}])
    assert _sweep(db)["attempts"] == 0
    assert db.events == []


def test_an_unreadable_album_deletes_nothing():
    db = _Db(album_raises=True)
    tally = _sweep(db)
    assert db.events == []
    assert (tally["attempts"], tally["failed"]) == (0, 1)


def test_a_recording_it_cannot_delete_keeps_its_row():
    # A deleted row whose file survives is the exact hole 0334 closed.
    db = _Db(storage_ok=False)
    tally = _sweep(db)
    assert db.events == []
    assert (tally["attempts"], tally["failed"]) == (0, 2)


def test_a_recording_beyond_the_first_fifty_is_deleted():
    # Sixty closed practices, each keeping only the attempt they chose, and
    # one more behind them with a recording that should have gone.
    practices = [{"id": f"p{n}", "status": "completed",
                  "selected_attempt_id": f"chosen{n}"} for n in range(61)]
    attempts = {row["id"]: [attempt(row["selected_attempt_id"])]
                for row in practices}
    attempts["p60"].append(attempt("late"))
    db = _Db(practices=practices, attempts=attempts)
    for minute in range(3):
        _sweep(db, NOW + timedelta(minutes=minute))
    assert db.events == [("file", "late"), ("row", "late")]


def test_a_practice_looked_at_is_not_read_again_for_a_day():
    db = _Db()
    _sweep(db)
    _sweep(db, NOW + timedelta(minutes=1))
    assert db.reads == ["p1"]
    # A recording that could not be deleted, or a save that was undone, is
    # found by the next day's look.
    db.attempts["p1"].append(attempt("a9"))
    _sweep(db, NOW + timedelta(days=1, minutes=1))
    assert ("row", "a9") in db.events
