"""
STORY    As a coach, I want my queue to open fast and list each Take's
         bookmarked moments in the order the speaker said them.
OUTCOME
  O1  A Take's bookmarked moments come in talk order (start, then id), only
      those that exist in that Take; a Take whose bookmarks are not frozen
      yet waits for its text.
  O2  The queue reads only the bookmarked pieces, in one read for every
      Take, never every piece of every Take (the queue took 6.7 s).
  O3  A failed piece read lists no moments rather than failing the queue.
PROVES   O1, O2 -> QueueBookmarksTests::test_bookmarks_in_talk_order_from_one_read_of_only_them
         O3 -> QueueBookmarksTests::test_a_failed_read_lists_no_moments
WHY      Founder 2026-10-21 (N99): "please make sure it is smooth that it
         loads fast".
"""
from __future__ import annotations

import unittest

from services.coach_queue import bookmarks_for

T1, T2 = "take-1", "take-2"
A, B, C, X = "a1", "b2", "c3", "x9"


class _Db:
    def __init__(self, pieces):
        self.pieces, self.reads = pieces, []

    def get_ideal_text_feedback_sets(self, session_ids):
        return {T1: [{"arc_id": "arc"}]}

    def get_snippet_order_by_ids(self, ids):
        self.reads.append(set(ids))
        return [p for p in self.pieces if p["id"] in ids] if self.pieces is not None else []


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


if __name__ == "__main__":
    unittest.main()
