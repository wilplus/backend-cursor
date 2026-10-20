"""
STORY    As the founder, I want an alarm when new speakers' moments stop
         reaching the coaches, so that I hear of it from Sentry, not from an
         empty queue.
OUTCOME
  O1  The 3 newest Takes with moments, sent over 6 hours ago, none of them
      reached: one warning, once a day.
  O2  One of them reached, or a Take is too fresh to judge: no warning.
PROVES   O1 -> ReachAlarmTests::test_fires_once_a_day_when_nothing_new_reached
         O2 -> ReachAlarmTests::test_quiet_while_reach_works_or_takes_are_fresh
WHY      Founder 2026-10-20: the walk (lock 2026-10-12) stopped recording the
         reach and no coach heard the newest tester (frontend #866).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from services import coach_moments_queue as q

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
OLD = ["2026-10-19T08:00:00+00:00", "2026-10-19T09:00:00+00:00", "2026-10-19T10:00:00+00:00"]


class ReachAlarmTests(unittest.TestCase):
    def setUp(self):
        q._alarmed_on = None

    def test_fires_once_a_day_when_nothing_new_reached(self):
        takes = [(t, False) for t in OLD] + [("2026-10-01T10:00:00+00:00", True)]
        with mock.patch("sentry_sdk.capture_message") as sent:
            self.assertTrue(q.reach_alarm(takes, now=NOW))
            self.assertFalse(q.reach_alarm(takes, now=NOW))
        sent.assert_called_once()

    def test_quiet_while_reach_works_or_takes_are_fresh(self):
        one_reached = [(OLD[0], False), (OLD[1], False), (OLD[2], True)]
        too_fresh = [(OLD[0], False), (OLD[1], False), ("2026-10-20T11:00:00+00:00", False)]
        with mock.patch("sentry_sdk.capture_message") as sent:
            self.assertFalse(q.reach_alarm(one_reached, now=NOW))
            self.assertFalse(q.reach_alarm(too_fresh, now=NOW))
        sent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
