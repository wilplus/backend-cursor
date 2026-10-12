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


if __name__ == "__main__":
    unittest.main()
