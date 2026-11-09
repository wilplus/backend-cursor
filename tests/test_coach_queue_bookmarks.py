"""
STORY    As a coach, I want my queue to open fast and list each Take's
         bookmarked moments in the order the speaker said them.
OUTCOME
  O1  A Take's bookmarked moments come in talk order (start, then id), only
      those that exist in that Take; a Take whose bookmarks are not frozen
      yet waits for its text.
  O2  The queue reads only the bookmarked pieces, in one read for every
      Take, never every piece of every Take (the queue took 6.7 s).
  O3  A failed piece read lists no moments rather than failing the queue,
      even when only one of its chunks failed: never some of a Take's
      moments.
  O4  The walk asks for the coach's languages, the queue and the waiting
      plans together, not one after another (the walk took 1.1 s).
PROVES   O1, O2 -> QueueBookmarksTests::test_bookmarks_in_talk_order_from_one_read_of_only_them
         O3 -> QueueBookmarksTests::test_a_failed_read_lists_no_moments
         O4 -> QueueBookmarksTests::test_the_walks_first_reads_go_out_together
WHY      Founder 2026-10-21 (N99): "please make sure it is smooth that it
         loads fast"; 2026-11-09: the walk took 1.1 s.
"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from services.coach_moments_queue import walk_for_coach
from services.coach_queue import Bookmarks, bookmarks_for

T1, T2 = "take-1", "take-2"
A, B, C, X = "a1", "b2", "c3", "x9"


class _Db:
    def __init__(self, pieces, fails_with=None):
        self.pieces, self.fails_with, self.reads = pieces, fails_with, []

    def get_ideal_text_feedback_sets(self, session_ids):
        return {T1: [{"arc_id": "arc"}]}

    def get_snippet_order_by_ids(self, ids, *, strict=False):
        self.reads.append(set(ids))
        if self.pieces is None or self.fails_with in ids:  # the read failed
            if strict:
                raise RuntimeError("Server disconnected")
            return []
        return [p for p in self.pieces if p["id"] in ids]


def _bookmarked(row, session_id, sets):
    # The route's reading of a frozen selection: None until it is frozen.
    return {B, A, X, C} if sets.get(session_id) else None


ROWS = [{"id": T1, "arc_id": "arc"}, {"id": T2, "arc_id": "arc"}]


class QueueBookmarksTests(unittest.TestCase):
    def test_bookmarks_in_talk_order_from_one_read_of_only_them(self):
        db = _Db([
            {"id": B, "session_id": T1, "start_offset_ms": 500},
            {"id": A, "session_id": T1, "start_offset_ms": 1000},
            {"id": C, "session_id": "another-take", "start_offset_ms": 0},
        ])
        moments_for = bookmarks_for(db, ROWS, _bookmarked)
        self.assertEqual(moments_for(ROWS[0]), [B, A])
        self.assertIsNone(moments_for(ROWS[1]))
        self.assertEqual(db.reads, [{A, B, C, X}])

    def test_a_failed_read_lists_no_moments(self):
        moments_for = bookmarks_for(_Db(None), ROWS, _bookmarked)
        self.assertEqual(moments_for(ROWS[0]), [])
        self.assertIsNone(moments_for(ROWS[1]))
        # Two reads of two clips each, and only the one with A fails.
        pieces = [{"id": i, "session_id": T1, "start_offset_ms": n}
                  for n, i in enumerate((A, B, C, X))]
        with mock.patch.object(Bookmarks, "ORDER_CHUNK", 2):
            moments_for = bookmarks_for(_Db(pieces, fails_with=A), ROWS, _bookmarked)
            self.assertEqual(moments_for(ROWS[0]), [])

    def test_the_walks_first_reads_go_out_together(self):
        # Each answers only once all three are being read: one after the
        # other, the first would wait for the others and time out.
        together = threading.Barrier(3, timeout=5)

        class Walk:
            def get_user_proficient_languages(self, rater_id):
                together.wait()
                return ["en"]

            def list_review_queue(self):
                together.wait()
                return []

            def list_waiting_plans(self):
                together.wait()
                return []

            def __getattr__(self, name):  # every later read finds nothing
                return lambda *a, **k: {} if name.startswith("get_") else []

        self.assertEqual(walk_for_coach(
            Walk(), rater_id="coach-1", matched_rows=lambda rows, *_: rows,
            bookmarked=_bookmarked, pseudonym_for=str), [])


if __name__ == "__main__":
    unittest.main()
