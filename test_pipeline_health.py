"""Queue saturation signal — the verdict that decides worker sizing.

The trap this guards: scaling on RUN time. More workers shrink the WAIT
(enqueued → started) and can never shrink the RUN (started → finished,
which is Whisper + the LLM calls). A verdict that fires on slow takes
would have you paying for containers while every take stays exactly as
slow. So "saturated" must depend on WAIT, and a long run with no queue
must read healthy.

Run: python3 -m unittest test_pipeline_health
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

try:
    import services.pipeline_health as ph
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    ph = None  # type: ignore[assignment]
    _IMPORT_ERR = e


def _ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _finished(wait_s, run_s, status="completed", error=None, age_h=0):
    """A terminal job that finished ``age_h`` hours ago."""
    end = datetime.now(timezone.utc) - timedelta(hours=age_h)
    start = end - timedelta(seconds=run_s)
    enq = start - timedelta(seconds=wait_s)
    return {"status": status, "enqueued_at": enq.isoformat(),
            "started_at": start.isoformat(), "finished_at": end.isoformat(),
            "error": error}


class _FakeDb:
    def __init__(self, active=None, finished=None):
        self._active = active or []
        self._finished = finished or []

    def list_active_processing_jobs(self, max_rows=500):
        if isinstance(self._active, Exception):
            raise self._active
        return self._active

    def list_recent_finished_processing_jobs(self, max_rows=200):
        return self._finished


@unittest.skipIf(ph is None, f"import failed: {_IMPORT_ERR}")
class SaturationVerdictTests(unittest.TestCase):

    def _health(self, active=None, finished=None):
        with patch.object(ph, "db", _FakeDb(active, finished)):
            return ph.queue_health()

    def test_empty_queue_is_healthy(self):
        h = self._health(active=[], finished=[_finished(1, 31)])
        self.assertEqual(h["saturation"], "healthy")
        self.assertIn("Adding workers would change nothing",
                      h["recommendation"])

    def test_slow_takes_with_no_queue_stay_healthy(self):
        """THE trap: a 10-minute take is not saturation. Nobody is waiting,
        so more workers would buy nothing."""
        h = self._health(active=[], finished=[_finished(0, 600)] * 5)
        self.assertEqual(h["saturation"], "healthy")

    def test_short_wait_beside_a_long_take_is_only_busy(self):
        h = self._health(
            active=[{"status": "pending", "enqueued_at": _ago(10)}],
            finished=[_finished(2, 300)] * 5)
        self.assertEqual(h["saturation"], "busy")

    def test_wait_reaching_run_time_is_saturated(self):
        h = self._health(
            active=[{"status": "pending", "enqueued_at": _ago(40)}],
            finished=[_finished(1, 31)] * 5)
        self.assertEqual(h["saturation"], "saturated")
        self.assertIn("WORKER_COUNT", h["recommendation"])

    def test_counts_and_oldest_are_reported(self):
        h = self._health(active=[
            {"status": "pending", "enqueued_at": _ago(30)},
            {"status": "pending", "enqueued_at": _ago(5)},
            {"status": "processing", "enqueued_at": _ago(60)},
        ], finished=[_finished(1, 31)])
        self.assertEqual(h["queue"]["pending"], 2)
        self.assertEqual(h["queue"]["processing"], 1)
        self.assertGreaterEqual(h["queue"]["oldest_pending_seconds"], 29)

    def test_failures_are_surfaced_and_excluded_from_latency(self):
        h = self._health(active=[], finished=[
            _finished(1, 31),
            _finished(1, 5, status="failed", error="storage mismatch"),
        ])
        self.assertEqual(h["failures"]["recent"], 1)
        self.assertIn("storage mismatch", h["failures"]["last_error"])
        self.assertEqual(h["latency"]["sample"], 1)   # failed run excluded

    def test_old_failures_age_out_of_the_count(self):
        """THE fix (2026-08-06): the count was over the last 200 ROWS, so a
        bad morning stayed in the number for months at low volume — reading
        as "4 failures" long after the cause was fixed. It is a TIME window
        now, so yesterday's outage is yesterday's."""
        h = self._health(active=[], finished=[
            _finished(1, 5, status="failed", error="old", age_h=48),
            _finished(1, 5, status="failed", error="old", age_h=30),
            _finished(1, 31),
        ])
        self.assertEqual(h["failures"]["recent"], 0)
        self.assertIsNone(h["failures"]["last_error"])

    def test_failures_inside_the_window_still_count(self):
        h = self._health(active=[], finished=[
            _finished(1, 5, status="failed", error="fresh", age_h=1),
            _finished(1, 5, status="failed", error="old", age_h=48),
        ])
        self.assertEqual(h["failures"]["recent"], 1)
        self.assertEqual(h["failures"]["last_error"], "fresh")

    def test_window_is_reported_so_the_number_is_readable(self):
        h = self._health(active=[], finished=[_finished(1, 31)])
        self.assertEqual(h["failures"]["window_hours"], 24)

    def test_window_is_env_tunable_and_never_crashes(self):
        import os
        with patch.dict(os.environ, {"PIPELINE_FAILURE_WINDOW_HOURS": "1"}):
            h = self._health(active=[], finished=[
                _finished(1, 5, status="failed", error="2h ago", age_h=2)])
            self.assertEqual(h["failures"]["recent"], 0)
        with patch.dict(os.environ, {"PIPELINE_FAILURE_WINDOW_HOURS": "lots"}):
            self.assertEqual(ph.failure_window_hours(), 24)

    def test_latency_stays_sample_windowed_not_time_windowed(self):
        """Deliberately NOT symmetric: percentiles need a sample, and a time
        window returns nothing on a quiet day. An old completed take still
        tells you how long a take takes."""
        h = self._health(active=[], finished=[_finished(1, 31, age_h=72)])
        self.assertEqual(h["latency"]["sample"], 1)
        self.assertEqual(h["latency"]["run_p50_s"], 31.0)

    def test_unparseable_finish_time_counts_rather_than_vanishing(self):
        h = self._health(active=[], finished=[
            {"status": "failed", "error": "broken ts", "finished_at": "nope"}])
        self.assertEqual(h["failures"]["recent"], 1)

    def test_no_history_does_not_crash_or_claim_saturation(self):
        h = self._health(
            active=[{"status": "pending", "enqueued_at": _ago(999)}],
            finished=[])
        self.assertIn(h["saturation"], ("busy", "healthy"))
        self.assertIsNone(h["latency"]["run_p50_s"])

    def test_db_failure_degrades_to_unknown_not_an_exception(self):
        with patch.object(ph, "db", _FakeDb(active=RuntimeError("down"))):
            h = ph.queue_health()
        self.assertEqual(h["saturation"], "unknown")

    def test_percentiles_are_computed(self):
        h = self._health(active=[], finished=[_finished(1, r)
                                              for r in range(10, 110, 10)])
        self.assertIsNotNone(h["latency"]["run_p50_s"])
        self.assertGreaterEqual(h["latency"]["run_p95_s"],
                                h["latency"]["run_p50_s"])


@unittest.skipIf(ph is None, f"import failed: {_IMPORT_ERR}")
class LogSaturationTests(unittest.TestCase):

    def test_returns_the_verdict(self):
        self.assertEqual(
            ph.log_saturation({"saturation": "saturated", "queue": {},
                               "recommendation": "add slots"}),
            "saturated")

    def test_accepts_a_prebuilt_snapshot_without_requerying(self):
        with patch.object(ph, "db", _FakeDb(active=RuntimeError("must not"))):
            self.assertEqual(
                ph.log_saturation({"saturation": "healthy", "queue": {}}),
                "healthy")


if __name__ == "__main__":
    unittest.main()
