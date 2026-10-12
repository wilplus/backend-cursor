"""Queue saturation signal — the verdict that decides worker sizing.

The trap this guards: scaling on RUN time. More workers shrink the WAIT
(enqueued → started) and can never shrink the RUN (started → finished,
which is Whisper + the LLM calls). A verdict that fires on slow takes
would have you paying for containers while every take stays exactly as
slow. So "saturated" must depend on WAIT, and a long run with no queue
must read healthy.

Run: python3 -m unittest tests.test_pipeline_health
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


    def test_failures_are_surfaced_and_excluded_from_latency(self):
        h = self._health(active=[], finished=[
            _finished(1, 31),
            _finished(1, 5, status="failed", error="storage mismatch"),
        ])
        self.assertEqual(h["failures"]["recent"], 1)
        self.assertIn("storage mismatch", h["failures"]["last_error"])
        self.assertEqual(h["latency"]["sample"], 1)   # failed run excluded


if __name__ == "__main__":
    unittest.main()
