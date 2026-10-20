"""
STORY    As the founder, I want to delete a speaker's waiting moments from the
         coach queue, so that the queue holds only moments worth a coach's ear.
OUTCOME
  O1  A closed moment leaves every coach's queue and stops counting as
      waiting; the reach alarm still hears the Take.
  O2  Delete closes exactly what the speaker's row counts as waiting (never
      an answered moment) and keeps what the Take already holds.
  O3  A Take still waiting for its text (the greyed row) closes whole: it
      leaves every coach's queue, with the moments it gets later.
PROVES   O1 -> FounderClosesMomentsTests::test_a_closed_moment_leaves_every_coachs_queue
         O2 -> FounderClosesMomentsTests::test_closing_takes_only_what_the_row_counts_as_waiting
         O3 -> FounderClosesMomentsTests::test_a_take_waiting_for_its_text_closes_whole
WHY      Founder 2026-10-20: the ⋯ Delete on a speaker's row of the queue,
         like the training corpus; their Takes and Ideal Text stay.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import coach_moments_queue as q

TAKE = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
A, B, C = ("aaaaaaaa-0000-0000-0000-00000000000a", "bbbbbbbb-0000-0000-0000-00000000000b",
           "cccccccc-0000-0000-0000-00000000000c")


def _queue(intake: dict) -> list[dict]:
    row = {"id": TAKE, "user_id": "u1", "review_requested_at": "2026-10-20T08:00:00+00:00",
           "intake_context": intake}
    with mock.patch.object(q, "reach_alarm") as alarm:
        out = q.moments_queue(
            [row], moments_for=lambda _r: [A, B], reached_for=lambda _s: {A, B},
            ratings_for=lambda _s: {}, request_for=lambda _s, _n: None,
            pseudonym_for=lambda _u: "Brave Robin")
    alarm.assert_called_once_with([("2026-10-20T08:00:00+00:00", True)])
    return out


class _Takes:
    def __init__(self, ok: bool = True):
        self.ok, self.writes = ok, []

    def set_session_intake_context(self, sid, ctx):
        self.writes.append((sid, ctx))
        return self.ok


class _Db:
    def __init__(self, ok: bool = True):
        self.takes = _Takes(ok)


class FounderClosesMomentsTests(unittest.TestCase):
    def test_a_closed_moment_leaves_every_coachs_queue(self):
        before = _queue({"topic": "research"})[0]
        after = _queue({"topic": "research", q.CLOSED_KEY: {A: "2026-10-20T10:00:00+00:00"}})[0]
        self.assertEqual(before["waiting"], 2)
        self.assertEqual(after["waiting"], 1)
        self.assertEqual([m["snippet_id"] for m in after["takes"][0]["moments"]], [B])

    def test_closing_takes_only_what_the_row_counts_as_waiting(self):
        queue = [{"takes": [
            {"session_id": TAKE, "moments": [
                {"snippet_id": A, "state": "judge_it"},
                {"snippet_id": B, "state": "answered"},
                {"snippet_id": C, "state": "listen_again"}]},
            {"session_id": OTHER, "moments": [{"snippet_id": C, "state": "judged"}]},
        ]}]
        waiting = q.waiting_moments(queue)
        self.assertEqual(waiting, {TAKE: [A, C]})

        row = {"id": TAKE, "intake_context": {"topic": "research", q.CLOSED_KEY: {A: "earlier"}}}
        db = _Db()
        self.assertEqual(q.close_moments(db, [row, {"id": OTHER}], waiting), 1)
        (sid, ctx), = db.takes.writes
        self.assertEqual(sid, TAKE)
        self.assertEqual(ctx["topic"], "research")
        self.assertEqual(ctx[q.CLOSED_KEY][A], "earlier")
        self.assertIn(C, ctx[q.CLOSED_KEY])
        self.assertNotIn(B, ctx[q.CLOSED_KEY])
        with self.assertRaises(RuntimeError):
            q.close_moments(_Db(ok=False), [{"id": TAKE}], {TAKE: [A]})


    def test_a_take_waiting_for_its_text_closes_whole(self):
        def queue(intake: dict, moments: object) -> list[dict]:
            row = {"id": TAKE, "user_id": "u1", "intake_context": intake,
                   "review_requested_at": "2026-10-20T08:00:00+00:00"}
            return q.moments_queue(
                [row], moments_for=lambda _r: moments, reached_for=lambda _s: {A},
                ratings_for=lambda _s: {}, request_for=lambda _s, _n: None,
                pseudonym_for=lambda _u: "Quiet Sparrow", alarm=False)

        greyed = queue({}, None)
        self.assertEqual(q.waiting_for_text(greyed), {TAKE})
        db = _Db()
        row = {"id": TAKE, "intake_context": {"topic": "research"}}
        self.assertEqual(q.close_moments(db, [row], {}, whole=q.waiting_for_text(greyed)), 1)
        (_sid, ctx), = db.takes.writes
        self.assertEqual(ctx["topic"], "research")
        self.assertEqual(queue(ctx, None), [])   # gone while it waits for its text
        self.assertEqual(queue(ctx, [A]), [])    # and once its moments arrive


if __name__ == "__main__":
    unittest.main()
