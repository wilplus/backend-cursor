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

Run: python3 -m unittest test_orphan_sweep_and_concurrency
"""
from __future__ import annotations

import os
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
    from services.db import DatabaseService
    import services.pipeline_jobs as pj
    import services.job_queue as jq
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    DatabaseService = None  # type: ignore[assignment]
    pj = None  # type: ignore[assignment]
    jq = None  # type: ignore[assignment]
    _IMPORT_ERR = e


_SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SID2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class _Chain:
    """PostgREST fake that answers per-table."""

    def __init__(self, tables, calls):
        self.tables = tables
        self.calls = calls
        self.cap = {}

    def table(self, name):
        self.cap = {"table": name}
        self.calls.append(self.cap)
        self._name = name
        return self

    def select(self, cols):
        self.cap["select"] = cols
        return self

    def eq(self, col, val):
        self.cap.setdefault("eq", []).append((col, val))
        return self

    def in_(self, col, vals):
        self.cap.setdefault("in_", []).append((col, list(vals)))
        return self

    def lt(self, col, val):
        self.cap.setdefault("lt", []).append((col, val))
        return self

    def limit(self, n):
        self.cap["limit"] = n
        return self

    def execute(self):
        data = self.tables.get(self._name, [])
        if isinstance(data, Exception):
            raise data
        return types.SimpleNamespace(data=data)


@unittest.skipIf(DatabaseService is None, f"import failed: {_IMPORT_ERR}")
class OrphanQueryTests(unittest.TestCase):

    def _svc(self, tables):
        svc = DatabaseService.__new__(DatabaseService)
        calls = []
        svc.client = _Chain(tables, calls)
        return svc, calls

    def test_session_without_any_job_is_orphaned(self):
        svc, calls = self._svc({
            "v2_sessions": [{"id": _SID, "analysis_state": "processing"}],
            "processing_jobs": [],
        })
        out = svc.list_orphaned_processing_sessions()
        self.assertEqual([r["id"] for r in out], [_SID])
        # Only 'processing' sessions older than the cutoff are candidates.
        sess_call = calls[0]
        self.assertEqual(sess_call["table"], "v2_sessions")
        self.assertIn(("analysis_state", "processing"), sess_call["eq"])
        self.assertTrue(sess_call["lt"][0][0] == "created_at")

    def test_session_with_a_live_job_is_protected(self):
        svc, _ = self._svc({
            "v2_sessions": [{"id": _SID, "analysis_state": "processing"}],
            "processing_jobs": [{"session_id": _SID, "status": "processing"}],
        })
        self.assertEqual(svc.list_orphaned_processing_sessions(), [])

    def test_only_the_unprotected_one_is_returned(self):
        svc, _ = self._svc({
            "v2_sessions": [
                {"id": _SID, "analysis_state": "processing"},
                {"id": _SID2, "analysis_state": "processing"},
            ],
            "processing_jobs": [{"session_id": _SID, "status": "pending"}],
        })
        out = svc.list_orphaned_processing_sessions()
        self.assertEqual([r["id"] for r in out], [_SID2])

    def test_guard_query_failure_fails_closed(self):
        """If we cannot tell orphaned from live, reap NOTHING — failing a
        running take is worse than a banner that clears one sweep later."""
        svc, _ = self._svc({
            "v2_sessions": [{"id": _SID, "analysis_state": "processing"}],
            "processing_jobs": RuntimeError("postgrest down"),
        })
        self.assertEqual(svc.list_orphaned_processing_sessions(), [])

    def test_no_candidates_skips_the_guard_query(self):
        svc, calls = self._svc({"v2_sessions": [], "processing_jobs": []})
        self.assertEqual(svc.list_orphaned_processing_sessions(), [])
        self.assertEqual([c["table"] for c in calls], ["v2_sessions"])


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

    def list_stale_processing_jobs(self, stale_minutes=15, max_rows=100):
        return []


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class OrphanSweepTests(unittest.TestCase):

    def test_orphan_is_failed_so_the_fe_stops_polling(self):
        fake = _FakeDb(orphans=[{"id": _SID, "created_at": "2026-08-04T08:00:00Z"}])
        with patch.object(pj, "db", fake):
            n = pj.sweep_orphaned_sessions()
        self.assertEqual(n, 1)
        sid, state, err = fake.states[0]
        self.assertEqual((sid, state), (_SID, "failed"))
        self.assertIn("record again", err)

    def test_orphan_window_is_wider_than_the_job_window(self):
        """A session with no job row gets more rope than one a job protects."""
        self.assertGreater(pj.orphan_stale_minutes(), pj.stale_minutes())

    def test_main_sweep_reports_orphans(self):
        fake = _FakeDb(orphans=[{"id": _SID}])
        fake_q = types.SimpleNamespace(
            enqueue=lambda *a, **k: True, queue_configured=lambda: True)
        with patch.object(pj, "db", fake), patch.object(pj, "job_queue", fake_q):
            counts = pj.sweep_stale_jobs()
        self.assertEqual(counts["orphans_failed"], 1)

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


@unittest.skipIf(jq is None, f"import failed: {_IMPORT_ERR}")
class WorkerCountTests(unittest.TestCase):

    def _count(self, value):
        import worker
        env = {} if value is None else {"WORKER_COUNT": value}
        with patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop("WORKER_COUNT", None)
            return worker.worker_count()

    def test_default_is_two(self):
        self.assertEqual(self._count(None), 2)

    def test_explicit_value(self):
        self.assertEqual(self._count("4"), 4)

    def test_one_is_allowed_for_tight_memory(self):
        self.assertEqual(self._count("1"), 1)

    def test_zero_and_negative_floor_at_one(self):
        self.assertEqual(self._count("0"), 1)
        self.assertEqual(self._count("-3"), 1)

    def test_malformed_falls_back_to_default(self):
        self.assertEqual(self._count("lots"), 2)


@unittest.skipIf(jq is None, f"import failed: {_IMPORT_ERR}")
class ForkSafetyTests(unittest.TestCase):
    """redis-py pools are not fork-safe: siblings sharing the parent's
    socket interleave replies. Every slot must dial its own."""

    def test_reset_connections_clears_the_cache(self):
        jq._redis_conns["worker"] = object()
        jq._redis_conns["client"] = object()
        jq.reset_connections()
        self.assertEqual(jq._redis_conns, {})

    def test_child_resets_before_connecting(self):
        import inspect
        import worker
        src = inspect.getsource(worker._worker_child)
        reset_at = src.index("reset_connections")
        connect_at = src.index("get_redis")
        self.assertLess(reset_at, connect_at,
                        "the child must drop the inherited pool BEFORE "
                        "building its own connection")

    def test_only_slot_zero_runs_the_scheduler(self):
        import inspect
        import worker
        src = inspect.getsource(worker._worker_child)
        self.assertIn("with_scheduler=(slot == 0)", src)

    def test_child_drops_the_pools_signal_handlers(self):
        """Found by actually forking the pool: the parent's SIGTERM handler
        closes over its process table, so a child that inherits it dies with
        "can only test a child process" on every shutdown."""
        import inspect
        import worker
        src = inspect.getsource(worker._worker_child)
        self.assertIn("SIG_DFL", src)
        reset_at = src.index("SIG_DFL")
        loop_at = src.index("_run_worker_loop")
        self.assertLess(reset_at, loop_at)


if __name__ == "__main__":
    unittest.main()
