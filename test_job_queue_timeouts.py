"""Redis connection profiles for the pipeline queue (2026-08-04 outage).

The bug this pins: services/job_queue.py built ONE connection with
``socket_timeout=5`` and the rq worker used it. rq dequeues with a
BLOCKING BLPOP that waits ~415s (DEFAULT_WORKER_TTL - 5) for a job, so the
5s socket read timeout aborted the blocking read and rq quit —

    INFO  rq.worker: *** Listening on pipeline...
    ERROR rq.worker: Redis connection timeout, quitting...

exactly 5s later, against a completely healthy Redis.

The two sides want opposite things, so there are two profiles:
  * enqueue (web)  — fail fast; a dead broker must not hang an upload.
  * worker         — NO read timeout; blocking dequeue is the normal case.

Run: python3 -m unittest test_job_queue_timeouts
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
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    jq = None  # type: ignore[assignment]
    _IMPORT_ERR = e


# rq's Worker.dequeue_timeout is DEFAULT_WORKER_TTL (420) - 5. Any read
# timeout at or below this would abort a legitimate blocking dequeue.
RQ_BLOCKING_DEQUEUE_SECONDS = 415


class _FakeRedisModule(types.ModuleType):
    """Captures from_url kwargs instead of connecting."""

    def __init__(self):
        super().__init__("redis")
        self.calls = []

    def from_url(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return types.SimpleNamespace(url=url, kwargs=kwargs)


@unittest.skipIf(jq is None, f"import failed: {_IMPORT_ERR}")
class RedisProfileTests(unittest.TestCase):

    def setUp(self):
        jq._redis_conns.clear()
        self.addCleanup(jq._redis_conns.clear)

    def _connect(self, *, for_worker):
        fake = _FakeRedisModule()
        with patch.dict(sys.modules, {"redis": fake}), \
                patch.dict("os.environ", {"REDIS_URL": "redis://h:6379"}):
            conn = jq.get_redis(for_worker=for_worker)
        return conn, fake.calls[-1]

    def test_worker_profile_sets_no_read_timeout(self):
        """THE regression: a socket_timeout here kills the blocking dequeue."""
        _, kw = self._connect(for_worker=True)
        self.assertNotIn(
            "socket_timeout", kw,
            "worker connection must not set socket_timeout — rq blocks on "
            "BLPOP for ~415s and would quit when the read times out",
        )

    def test_worker_profile_survives_a_full_blocking_dequeue(self):
        """Stated as the invariant rather than the key: if a read timeout is
        ever reintroduced, it must exceed rq's blocking dequeue window."""
        _, kw = self._connect(for_worker=True)
        timeout = kw.get("socket_timeout")
        if timeout is not None:
            self.assertGreater(timeout, RQ_BLOCKING_DEQUEUE_SECONDS)

    def test_worker_profile_still_bounds_the_initial_connect(self):
        _, kw = self._connect(for_worker=True)
        self.assertIsNotNone(kw.get("socket_connect_timeout"))
        self.assertLessEqual(kw["socket_connect_timeout"], 10)

    def test_worker_profile_health_checks_the_long_lived_connection(self):
        _, kw = self._connect(for_worker=True)
        self.assertIsNotNone(kw.get("health_check_interval"))

    def test_enqueue_profile_fails_fast(self):
        """The upload route must never hang on a dead broker."""
        _, kw = self._connect(for_worker=False)
        self.assertLessEqual(kw.get("socket_timeout"), 5)
        self.assertLessEqual(kw.get("socket_connect_timeout"), 2)

    def test_profiles_are_cached_separately(self):
        fake = _FakeRedisModule()
        with patch.dict(sys.modules, {"redis": fake}), \
                patch.dict("os.environ", {"REDIS_URL": "redis://h:6379"}):
            w1 = jq.get_redis(for_worker=True)
            w2 = jq.get_redis(for_worker=True)
            c1 = jq.get_redis(for_worker=False)
        self.assertIs(w1, w2, "worker connection should be cached")
        self.assertIsNot(w1, c1, "profiles must not share one connection")
        self.assertEqual(len(fake.calls), 2)

    def test_default_is_the_enqueue_profile(self):
        """Callers that don't opt in get the safe-for-web one."""
        fake = _FakeRedisModule()
        with patch.dict(sys.modules, {"redis": fake}), \
                patch.dict("os.environ", {"REDIS_URL": "redis://h:6379"}):
            jq.get_redis()
        self.assertIn("socket_timeout", fake.calls[-1])

    def test_no_url_returns_none_without_connecting(self):
        fake = _FakeRedisModule()
        with patch.dict(sys.modules, {"redis": fake}), \
                patch.dict("os.environ", {"REDIS_URL": ""}):
            self.assertIsNone(jq.get_redis(for_worker=True))
        self.assertEqual(fake.calls, [])


@unittest.skipIf(jq is None, f"import failed: {_IMPORT_ERR}")
class WorkerUsesWorkerProfileTests(unittest.TestCase):
    """worker.py must ASK for the worker profile — the fix is worthless if
    the entrypoint still takes the default."""

    def test_worker_entrypoint_requests_for_worker(self):
        import inspect
        import worker
        src = inspect.getsource(worker.main)
        self.assertIn("get_redis(for_worker=True)", src)


if __name__ == "__main__":
    unittest.main()
