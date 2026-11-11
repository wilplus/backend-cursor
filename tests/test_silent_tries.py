"""
STORY    As the founder, I want "Catch more" or "Catch fewer" on one thing the
         walk notices to run silently beside the live setting first, so that
         I see what it would catch and what coaches say before anything a
         speaker sees changes (N647 item 3).
OUTCOME
  O1  One try per thing at a time; a second start is refused.
  O2  Re-scoring the last 20 stored recordings makes the result ready at
      once; it counts only the cases that differ from live, and only
      SETTLED coach answers (a singleton never counts).
  O3  "Use it" makes the candidate live, once, and only when the try is
      ready and at least 10 settled answers exist.
  O4  "Go back", or a try left for 60 days, changes nothing live.
PROVES   O1 -> test_one_try_per_thing
         O2 -> test_twenty_stored_recordings_give_the_result_at_once
         O3 -> test_use_it_needs_ten_settled_answers_then_goes_live
         O4 -> test_go_back_and_expiry_change_nothing_live
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services import silent_tries as st

T0 = datetime(2026, 11, 11, tzinfo=timezone.utc)


class FakeConfig:
    """runtime_config with its compare-and-swap, in memory."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.ticks = 0

    def get_runtime_config_entry(self, key):
        row = self.rows.get(key)
        return dict(row) if row else None

    def put_runtime_config_entry(self, key, value, *, updated_by, expected_updated_at):
        row = self.rows.get(key)
        if (row is None) != (expected_updated_at is None):
            return False
        if row is not None and row["updated_at"] != expected_updated_at:
            return False
        self.ticks += 1
        self.rows[key] = {"value": value, "updated_at": f"t{self.ticks}"}
        return True


def start(db, thing="hedging", direction="more", at=T0):
    return st.start(db, thing=thing, direction=direction,
                    candidate={"HEDGE_MIN_COUNT": 1}, candidate_version="dial-x",
                    live_version="defaults", started_by="founder", at=at)


def evaluate(clip, candidate):
    """Live fires at 2 hedges, the candidate at 1."""
    n = clip.get("count")
    if n is None:
        return None, None
    return n >= 2, n >= candidate["HEDGE_MIN_COUNT"]


def clips(counts):
    return [{"snippet_id": f"c{i}", "count": n} for i, n in enumerate(counts)]


class Tries(unittest.TestCase):

    def test_one_try_per_thing(self):
        db = FakeConfig()
        start(db)
        with self.assertRaises(st.TryRefused) as refused:
            start(db, direction="fewer")
        self.assertEqual(refused.exception.reason, "try_in_progress")
        start(db, thing="filler_cluster")  # another thing may run beside it

    def test_twenty_stored_recordings_give_the_result_at_once(self):
        db = FakeConfig()
        start(db)
        # 12 clips with one hedge (candidate catches, live does not), 8 with
        # none, 2 unmeasurable (do not count), one repeated (counts once).
        stored = clips([1] * 12 + [0] * 8) + [{"snippet_id": "x1"}, {"snippet_id": "x2"}]
        self.assertEqual(st.add_recordings(db, "hedging", stored, evaluate, at=T0), 20)
        self.assertEqual(st.add_recordings(db, "hedging", stored[:1], evaluate, at=T0), 0)
        now = st.current(db, "hedging", at=T0)
        self.assertEqual(now["state"], st.READY)
        settled = {f"c{i}": "yes" for i in range(4)} | {"c4": "no", "c5": "in_between"}
        result = st.summarize(now, settled)
        self.assertEqual((result["seen"], result["changed"], result["settled"], result["agreed"]),
                         (20, 12, 6, 4))
        self.assertFalse(result["enough_answers"])
        self.assertEqual(sorted(st.differing_clips(now)), sorted(f"c{i}" for i in range(12)))

    def test_use_it_needs_ten_settled_answers_then_goes_live(self):
        db = FakeConfig()
        try_id = start(db)["id"]
        written = []
        st.add_recordings(db, "hedging", clips([1] * 12 + [0] * 8), evaluate, at=T0)
        few = {f"c{i}": "yes" for i in range(9)}
        with self.assertRaises(st.TryRefused) as refused:
            st.use(db, "hedging", try_id=try_id, settled=few,
                   write_live=lambda c, by: written.append(c), by="founder")
        self.assertEqual(refused.exception.reason, "not_enough_answers")
        self.assertEqual(written, [])
        enough = few | {"c9": "no"}
        done = st.use(db, "hedging", try_id=try_id, settled=enough,
                      write_live=lambda c, by: written.append(c), by="founder")
        self.assertEqual(written, [{"HEDGE_MIN_COUNT": 1}])
        self.assertEqual((done["state"], done["result"]["agreed"]), (st.USED, 9))
        self.assertIsNone(st.current(db, "hedging"))
        self.assertNotIn("differing", st.history(db, "hedging")[-1])

    def test_go_back_and_expiry_change_nothing_live(self):
        db = FakeConfig()
        try_id = start(db)["id"]
        st.add_recordings(db, "hedging", clips([1] * 20), evaluate, at=T0)
        st.drop(db, "hedging", try_id=try_id, by="founder", at=T0)
        self.assertEqual(st.history(db, "hedging")[-1]["state"], st.DROPPED)
        self.assertIsNone(st.current(db, "hedging"))
        start(db, at=T0)  # a new try may start once the old one is gone
        later = T0 + timedelta(days=st.EXPIRES_AFTER_DAYS)
        self.assertIsNone(st.current(db, "hedging", at=later))
        self.assertEqual(st.history(db, "hedging")[-1]["state"], st.EXPIRED)
        # Nothing in this module can write a live setting except use().
        self.assertEqual([k for k in db.rows], ["silent_try:hedging"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
