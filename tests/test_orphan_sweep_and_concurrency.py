"""Orphan reaping + the WORKER_COUNT concurrency dial.

Two gaps this covers, both found live on 2026-08-04:

1. ORPHANED SESSIONS. sweep_stale_jobs only walked processing_jobs, so a
   session flipped to analysis_state='processing' that never got a job row
   (the pre-queue daemon path, or a crash-looping worker window) showed
   "Working on your take" forever with nothing alive to finish it — the
   exact "processing forever" failure the queue was meant to retire,
   reached by an uncovered path.

2. CONCURRENCY. One rq worker processes jobs serially, so a second take
   waited for the first. WORKER_COUNT forks N slots.

Run: python3 -m unittest tests.test_orphan_sweep_and_concurrency
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

try:
    import services.job_queue as jq
    import services.pipeline_jobs as pj
    from services.db import DatabaseService
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    DatabaseService = None  # type: ignore[assignment]
    pj = None  # type: ignore[assignment]
    jq = None  # type: ignore[assignment]
    _IMPORT_ERR = e


_SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SID2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class _FakeDb:
    def __init__(self, orphans=None):
        self.orphans = orphans or []
        self.states = []

    def list_orphaned_processing_sessions(self, stale_minutes=30, max_rows=100):
        self.seen_cutoff = stale_minutes
        return self.orphans

    def set_session_analysis_state(self, sid, state, error=None):
        self.states.append((sid, state, error))
        return True

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>(); this fake
        # implements those methods directly on itself.
        return self

    def list_stale_processing_jobs(self, stale_minutes=15, max_rows=100,
                                   max_runtime_minutes=None):
        return []


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class OrphanSweepTests(unittest.TestCase):


    def test_a_failing_reap_does_not_abort_the_rest(self):
        fake = _FakeDb(orphans=[{"id": _SID}, {"id": _SID2}])
        calls = {"n": 0}

        def _flaky(sid, state, error=None):
            calls["n"] += 1
            if sid == _SID:
                raise RuntimeError("write failed")
            return True

        fake.set_session_analysis_state = _flaky
        with patch.object(pj, "db", fake):
            n = pj.sweep_orphaned_sessions()
        self.assertEqual(n, 1)      # the second one still got reaped
        self.assertEqual(calls["n"], 2)


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class StorageProviderMismatchTests(unittest.TestCase):
    """The live failure of 2026-08-06: three jobs dead at stage=fetch_audio,
    attempts=3. Web had the R2 credentials and wrote there; the worker did
    not, silently resolved to Supabase, and hunted every bucket for an
    object that was never put in one."""


    def test_config_error_is_terminal_not_retried(self):
        """An env var cannot be fixed by waiting — don't burn 3 attempts."""
        fake = _FakeDb()
        fake.get_processing_job = lambda jid: {
            "id": "job-1", "kind": "session_recording", "status": "pending",
            "attempts": 0, "max_attempts": 3, "session_id": _SID,
            "payload": {},
        }
        fake.claim_processing_job = lambda jid, att: {
            "id": "job-1", "kind": "session_recording", "status": "processing",
            "attempts": att + 1, "max_attempts": 3, "session_id": _SID,
            "payload": {},
        }
        fake.finishes = []
        fake.releases = []

        def _finish(job_id, status, error=None, result=None):
            fake.finishes.append((job_id, status, error))
            return True

        def _release(job_id, error=None):
            fake.releases.append(job_id)
            return True

        fake.finish_processing_job = _finish
        fake.release_processing_job_for_retry = _release
        fake.update_processing_job = lambda *a, **k: True
        fake_q = types.SimpleNamespace(enqueue=lambda *a, **k: True,
                                       queue_configured=lambda: True)

        def _boom(job):
            raise pj.ConfigMismatchError("missing R2 creds")

        with patch.object(pj, "db", fake), patch.object(pj, "job_queue", fake_q), \
                patch.dict(pj._KIND_RUNNERS, {"session_recording": _boom}):
            pj.run_processing_job("job-1")
        self.assertEqual(fake.finishes[-1][1], "failed")
        self.assertEqual(fake.releases, [], "must NOT be requeued")
        self.assertEqual(fake.states[-1][1], "failed")


if __name__ == "__main__":
    unittest.main()
