"""The wall clock on one attempt — the wedged-job hole.

FOUNDER 2026-09-17: "for take to actually be processed. It got stale and now
it needs to function."

Every recovery path in services/pipeline_jobs.py keyed off HEARTBEAT silence,
and `_Heartbeat` is a daemon thread on a timer: it writes `heartbeat_at` every
60 seconds whether or not the runner is advancing. So a runner blocked forever
on a socket that never returns kept its job row looking perfectly healthy, and
all three recovery paths stood down:

  * `list_stale_processing_jobs` never listed it (heartbeat fresh);
  * `run_processing_job` re-delivery early-returned ("another worker is live");
  * `sweep_orphaned_sessions` skipped the session (it HAS a live job).

The take was unrecoverable by any code path in the system. These tests hold the
wall clock in place, because the failure is invisible in every log the module
writes — the only symptom is a user staring at "Working on your take".

Run: python3 -m unittest tests.test_wedged_job_wall_clock
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

import services.pipeline_jobs as pj  # noqa: E402


def _ago(minutes: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).isoformat()


def _job(**over) -> dict:
    """A 'processing' row whose heartbeat is perfectly fresh."""
    row = {
        "id": "job-1",
        "kind": "session_recording",
        "status": "processing",
        "session_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "attempts": 1,
        "max_attempts": 3,
        "started_at": _ago(1),
        "heartbeat_at": _ago(0.1),
        "payload": {},
    }
    row.update(over)
    return row


class WallClockRule(unittest.TestCase):
    def test_deadline_is_always_beyond_the_heartbeat_window(self):
        """A wall clock inside the stale window would fire on every job that
        merely paused — the two rules must not be able to invert."""
        self.assertGreater(pj.max_runtime_minutes(), pj.stale_minutes())

    def test_a_long_running_attempt_is_over_deadline(self):
        self.assertTrue(
            pj._over_deadline(_job(started_at=_ago(pj.max_runtime_minutes() + 1)))
        )

    def test_a_young_attempt_is_not(self):
        self.assertFalse(pj._over_deadline(_job(started_at=_ago(1))))

    def test_unknown_start_is_not_expired(self):
        """`started_at` missing or unparseable means we cannot judge. Guessing
        'expired' would re-run healthy jobs on a data quirk."""
        self.assertFalse(pj._over_deadline(_job(started_at=None)))
        self.assertFalse(pj._over_deadline(_job(started_at="not-a-timestamp")))

    def test_deadline_runs_from_the_ATTEMPT_not_the_job(self):
        """claim_processing_job re-stamps started_at, so a recovered job gets a
        full fresh budget instead of inheriting the wedged attempt's clock."""
        recovered = _job(started_at=_ago(0), attempts=2)
        self.assertFalse(pj._over_deadline(recovered))


class ReDeliveryStandsDown(unittest.TestCase):
    """THE REGRESSION. Fresh heartbeat + past the wall clock used to read as
    'another worker is live on it', which is what made the take permanent."""

    def test_fresh_heartbeat_past_deadline_is_NOT_plausible(self):
        wedged = _job(started_at=_ago(pj.max_runtime_minutes() + 5))
        self.assertTrue(pj._heartbeat_is_fresh(wedged))
        self.assertFalse(pj._worker_still_plausible(wedged))

    def test_fresh_heartbeat_inside_deadline_is_still_plausible(self):
        healthy = _job()
        self.assertTrue(pj._worker_still_plausible(healthy))

    def test_run_processing_job_does_not_abandon_a_wedged_row(self):
        wedged = _job(started_at=_ago(pj.max_runtime_minutes() + 5))
        with patch.object(pj.db, "get_processing_job", return_value=wedged), \
             patch.object(pj.db, "claim_processing_job",
                          return_value=None) as claim:
            pj.run_processing_job("job-1")
        # It got as far as trying to claim — i.e. it did NOT early-return.
        claim.assert_called_once()

    def test_run_processing_job_still_yields_to_a_healthy_worker(self):
        with patch.object(pj.db, "get_processing_job", return_value=_job()), \
             patch.object(pj.db, "claim_processing_job") as claim:
            pj.run_processing_job("job-1")
        claim.assert_not_called()


class SweeperRecoversTheWedgedJob(unittest.TestCase):
    def _sweep(self, listed):
        released, enqueued = [], []
        with patch.object(pj.db, "list_stale_processing_jobs",
                          return_value=listed) as lister, \
             patch.object(pj.db, "release_processing_job_for_retry",
                          side_effect=lambda jid, err: released.append((jid, err))), \
             patch.object(pj, "_sync_phase1_job"), \
             patch.object(pj, "sweep_orphaned_sessions", return_value=0), \
             patch.object(pj.job_queue, "enqueue",
                          side_effect=lambda *a, **k: enqueued.append(a) or True):
            counts = pj.sweep_stale_jobs()
        return counts, released, enqueued, lister

    def test_the_founder_symptom_is_recovered(self):
        wedged = _job(started_at=_ago(pj.max_runtime_minutes() + 5))
        counts, released, enqueued, _ = self._sweep([wedged])
        self.assertEqual(counts["wedged"], 1)
        self.assertEqual(counts["requeued"], 1)
        self.assertEqual(len(enqueued), 1)
        self.assertIn("wedged", released[0][1])

    def test_the_wall_clock_is_actually_passed_to_the_query(self):
        """A rule the sweeper knows but never asks the database about would
        recover nothing — the row has to be LISTED first."""
        _, _, _, lister = self._sweep([])
        self.assertEqual(
            lister.call_args.kwargs["max_runtime_minutes"],
            pj.max_runtime_minutes(),
        )

    def test_a_wedged_job_out_of_attempts_goes_terminal(self):
        """It must land on 'failed' so the session stops saying 'processing'
        and the user is offered a re-record, rather than looping forever."""
        wedged = _job(started_at=_ago(pj.max_runtime_minutes() + 5), attempts=3)
        with patch.object(pj.db, "list_stale_processing_jobs",
                          return_value=[wedged]), \
             patch.object(pj, "_fail_terminal_for_job") as fail, \
             patch.object(pj, "sweep_orphaned_sessions", return_value=0), \
             patch.object(pj.job_queue, "enqueue", return_value=True):
            counts = pj.sweep_stale_jobs()
        self.assertEqual(counts["failed"], 1)
        fail.assert_called_once()

    def test_an_ordinary_stale_job_still_reads_as_stale(self):
        """The old path must keep its own wording — 'lost' and 'wedged' send
        an investigator to completely different places."""
        stale = _job(started_at=_ago(1), heartbeat_at=_ago(pj.stale_minutes() + 1))
        counts, released, _, _ = self._sweep([stale])
        self.assertEqual(counts["wedged"], 0)
        self.assertEqual(counts["requeued"], 1)
        self.assertIn("stale heartbeat", released[0][1])


class ListingDeduplicates(unittest.TestCase):
    """A long-dead job matches BOTH the heartbeat query and the wall-clock
    query. Handling it twice in one sweep would burn two of its three
    attempts — the recovery would consume the take it is recovering."""

    def test_one_row_from_two_queries_is_returned_once(self):
        from services.db import DatabaseService

        row = _job(started_at=_ago(99), heartbeat_at=_ago(99))

        class _Res:
            def __init__(self, data):
                self.data = data

        class _Q:
            def __init__(self, data):
                self._data = data

            def select(self, *a):
                return self

            def eq(self, *a):
                return self

            def lt(self, *a):
                return self

            def limit(self, *a):
                return self

            def execute(self):
                return _Res(self._data)

        class _Client:
            def table(self, name):
                # Every query answers with the same row: processing-by-
                # heartbeat, pending, and processing-by-wall-clock.
                return _Q([row])

        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _Client()  # type: ignore[attr-defined]
        rows = svc.list_stale_processing_jobs(
            stale_minutes=5, max_rows=10, max_runtime_minutes=20,
        )
        self.assertEqual(len(rows), 1)

    def test_without_the_wall_clock_the_third_query_is_not_run(self):
        """Callers that pass nothing keep exactly the old two-query
        behaviour — the new rule is opt-in at the call site."""
        from services.db import DatabaseService

        seen = []

        class _Res:
            data: list = []

        class _Q:
            def __init__(self, calls):
                self.calls = calls

            def select(self, *a):
                return self

            def eq(self, field, value):
                self.calls.append(value)
                return self

            def lt(self, *a):
                return self

            def limit(self, *a):
                return self

            def execute(self):
                return _Res()

        class _Client:
            def table(self, name):
                return _Q(seen)

        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _Client()  # type: ignore[attr-defined]
        svc.list_stale_processing_jobs(stale_minutes=5, max_rows=10)
        self.assertEqual(seen, ["processing", "pending"])


if __name__ == "__main__":
    unittest.main()
